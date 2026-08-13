"""One chunk = one citable section of one RFC. Vector column for semantic
search, tsvector column for full-text search — hybrid from day one, not
bolted on later. See the plan's "hybrid search via Postgres, not a separate
Elasticsearch cluster" decision: an exact command name like `ip ospf priority`
should always surface via full-text match even when it wouldn't rank top-1 on
vector similarity alone.
"""

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.models.base import Base


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Citation metadata — every field a reader needs to actually verify the
    # source, per the chunker's own citation property (RFC {number} §{section}).
    rfc_number: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    rfc_title: Mapped[str] = mapped_column(String(256), nullable=False)
    section: Mapped[str] = mapped_column(String(32), nullable=False)
    heading: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)

    text: Mapped[str] = mapped_column(Text, nullable=False)

    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dim), nullable=False)

    # Generated column, not populated from Python: Postgres derives it from
    # `text` on write, so the tsvector can never drift out of sync with the
    # text it indexes — a hand-maintained duplicate column could go stale.
    text_search: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', text)", persisted=True),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_chunks_text_search", "text_search", postgresql_using="gin"),
        # HNSW over cosine distance — the metric that matches how retrieval
        # actually queries this table (see retriever.py).
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    @property
    def citation(self) -> str:
        return f"RFC {self.rfc_number} §{self.section}"
