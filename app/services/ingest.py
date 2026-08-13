"""Ingest the corpus: chunk -> embed -> write to Postgres. Run with:
    python -m app.services.ingest

Creates the schema if it doesn't exist, wipes and reloads all chunks (this
project doesn't have incremental corpus updates yet — v1 is a full rebuild
each time, which is fine at 226 chunks and gets revisited if the corpus
grows enough to matter).
"""

import asyncio
from pathlib import Path

from fastembed import TextEmbedding
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal, Base, engine
from app.models.chunk import Chunk
from app.services.chunker import chunk_corpus


async def ingest() -> int:
    corpus_dir = Path(__file__).resolve().parents[2] / "corpus" / "rfcs"
    chunks = chunk_corpus(corpus_dir)
    print(f"chunked {len(chunks)} sections from {corpus_dir}")

    model = TextEmbedding(model_name=settings.embedding_model)
    texts = [c.text for c in chunks]
    print(f"embedding {len(texts)} chunks with {settings.embedding_model}...")
    vectors = list(model.embed(texts))
    assert len(vectors) == len(chunks), "embedding count must match chunk count"
    for v in vectors:
        assert len(v) == settings.embedding_dim, (
            f"embedding dim {len(v)} != configured {settings.embedding_dim} — "
            "config and model are out of sync"
        )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session: AsyncSession
    async with AsyncSessionLocal() as session:
        await session.execute(delete(Chunk))
        for c, vec in zip(chunks, vectors):
            session.add(
                Chunk(
                    rfc_number=c.rfc_number,
                    rfc_title=c.rfc_title,
                    section=c.section,
                    heading=c.heading,
                    source_url=c.source_url,
                    text=c.text,
                    embedding=vec.tolist(),
                )
            )
        await session.commit()

    print(f"ingested {len(chunks)} chunks into Postgres")
    return len(chunks)


if __name__ == "__main__":
    asyncio.run(ingest())
