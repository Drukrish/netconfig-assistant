"""Throwaway verification script, not part of the app. Proves hybrid search
does real work against the live ingested corpus: at least one exact-term
query should surface a full-text hit that ranks poorly (or not at all) on
pure vector similarity — otherwise the tsvector column is dead weight.
"""

import asyncio

from app.database import AsyncSessionLocal
from app.services.retriever import hybrid_search

QUERIES = [
    "AS_PATH attribute",
    "Checksum Adjustment",
    "how does DHCP handle a lease renewal",
    "what happens when a BGP session fails",
    "giaddr field",
]


async def main():
    async with AsyncSessionLocal() as session:
        for q in QUERIES:
            results = await hybrid_search(session, q, k=5)
            print(f"\nquery: {q!r}")
            for r in results:
                print(
                    f"  {r.chunk.citation:20s} vec_rank={str(r.vector_rank):5s} "
                    f"ft_rank={str(r.fulltext_rank):5s} rrf={r.rrf_score:.4f}  "
                    f"{r.chunk.heading[:50]}"
                )

    # The actual sanity check the plan requires: find a real case where a top
    # result came from full-text alone, proving the hybrid design isn't just
    # present in the schema but doing real work. "AS_PATH attribute" was tried
    # first and honestly failed this check — bge-small's embeddings turned out
    # strong enough on that particular jargon that vector search found it fine
    # on its own. "giaddr field" (an exact DHCP protocol field name) is the
    # case that actually demonstrates the gap: full-text ranks RFC 2131 §4.1
    # first, and vector search doesn't surface it in its candidates at all.
    async with AsyncSessionLocal() as session:
        results = await hybrid_search(session, "giaddr field", k=5)
        top = next(r for r in results if r.chunk.citation == "RFC 2131 §4.1")
        assert top.fulltext_rank == 1, f"expected RFC 2131 §4.1 to be the top full-text match, got rank {top.fulltext_rank}"
        assert top.vector_rank is None, (
            f"expected vector search to miss this chunk entirely, but it found it at rank "
            f"{top.vector_rank} — the hybrid case may no longer hold if the embedding model changes"
        )
        print(f"\nhybrid sanity check passed: 'giaddr field' surfaces RFC 2131 §4.1 at "
              f"fulltext_rank=1, which vector search does not find at all (vector_rank=None) — "
              "hybrid search is doing real, non-redundant work, not just present in the schema")


if __name__ == "__main__":
    asyncio.run(main())
