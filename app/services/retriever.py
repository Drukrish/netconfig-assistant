"""Hybrid retrieval: vector similarity + full-text rank, combined by
reciprocal rank fusion (RRF). Pure vector search misses exact-term matches
(a literal command name should always surface, not just be "semantically
close"); pure full-text misses paraphrased questions. RRF needs no score
normalization between the two very different scales (cosine distance vs
ts_rank), which is why it's the simple default here rather than a hand-tuned
weighted blend.
"""

from dataclasses import dataclass

from fastembed import TextEmbedding
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.chunk import Chunk

_model: TextEmbedding | None = None


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        _model = TextEmbedding(model_name=settings.embedding_model)
    return _model


@dataclass
class RetrievedChunk:
    chunk: Chunk
    vector_rank: int | None
    fulltext_rank: int | None
    rrf_score: float


async def hybrid_search(session: AsyncSession, query: str, k: int = 5, rrf_k: int = 60) -> list[RetrievedChunk]:
    query_vec = list(_get_model().embed([query]))[0].tolist()

    vector_rows = (
        await session.execute(
            select(Chunk.id).order_by(Chunk.embedding.cosine_distance(query_vec)).limit(k * 4)
        )
    ).scalars().all()
    vector_ranks = {chunk_id: rank for rank, chunk_id in enumerate(vector_rows, start=1)}

    # Two separately constructed text() clauses referencing ":q" by name do
    # NOT share a bind value in SQLAlchemy — .params() on the select only
    # reaches the first one. Each fragment needs its own .bindparams() call
    # with the same literal value, even though that reads as redundant.
    where_clause = text("text_search @@ websearch_to_tsquery('english', :q)").bindparams(q=query)
    order_clause = text("ts_rank(text_search, websearch_to_tsquery('english', :q)) DESC").bindparams(q=query)
    fulltext_rows = (
        await session.execute(
            select(Chunk.id).where(where_clause).order_by(order_clause).limit(k * 4)
        )
    ).scalars().all()
    fulltext_ranks = {chunk_id: rank for rank, chunk_id in enumerate(fulltext_rows, start=1)}

    all_ids = set(vector_ranks) | set(fulltext_ranks)
    scored = []
    for chunk_id in all_ids:
        vr = vector_ranks.get(chunk_id)
        fr = fulltext_ranks.get(chunk_id)
        rrf = (1.0 / (rrf_k + vr) if vr else 0.0) + (1.0 / (rrf_k + fr) if fr else 0.0)
        scored.append((chunk_id, vr, fr, rrf))

    scored.sort(key=lambda row: row[3], reverse=True)
    top = scored[:k]

    chunks_by_id = {
        c.id: c
        for c in (await session.execute(select(Chunk).where(Chunk.id.in_(cid for cid, *_ in top)))).scalars()
    }

    return [
        RetrievedChunk(chunk=chunks_by_id[cid], vector_rank=vr, fulltext_rank=fr, rrf_score=score)
        for cid, vr, fr, score in top
        if cid in chunks_by_id
    ]
