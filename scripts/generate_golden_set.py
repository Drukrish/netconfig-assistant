"""Generates candidate golden-set question/citation pairs from the real
corpus, mirroring growth-os's refresh-golden.ts mechanism: an LLM proposes
candidates, a human is the actual ground truth.

Every item is written with reviewed: false. Nothing in this file is trusted
until Chandru reads each one against the source RFC text and either corrects
it or marks it reviewed: true — see risk #4 in the Phase 2 plan. test_rag_triad.py
refuses to run against anything still marked reviewed: false.

Run with: python scripts/generate_golden_set.py
Costs real money (~20 short Claude calls) - not part of CI.
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.chunk import Chunk
from app.services.ai import call_claude

TOTAL_QUESTIONS = 20
OUTPUT_PATH = Path(__file__).parent.parent / "tests" / "golden_set.json"

QUESTION_PROMPT = """Below is one section of a real RFC. Write ONE realistic question a \
network engineer would ask that this section, by itself, directly and fully answers. \
Do not invent facts outside the text. Keep the question under 20 words.

RFC {rfc_number} §{section} — {heading}
{text}

Respond with ONLY a JSON object, no prose: {{"question": "..."}}"""


def _allocate_quotas(counts: dict[str, int], total: int) -> dict[str, int]:
    """Proportional allocation across RFCs, minimum 1 each, summing to exactly
    `total` — so no RFC with real content is skipped just because it's short
    (RFC 2827 has only 11 chunks but still deserves representation)."""
    rfcs = list(counts)
    corpus_size = sum(counts.values())
    raw = {rfc: max(1, round(counts[rfc] / corpus_size * total)) for rfc in rfcs}
    # Adjust to hit `total` exactly - largest bucket absorbs the remainder.
    diff = total - sum(raw.values())
    biggest = max(raw, key=lambda r: counts[r])
    raw[biggest] += diff
    return raw


def _pick_evenly_spaced(chunks: list[Chunk], n: int) -> list[Chunk]:
    """Spreads picks across the RFC's sections instead of clustering at the
    start, so the golden set covers breadth, not just the first few topics."""
    if n >= len(chunks):
        return chunks
    step = len(chunks) / n
    return [chunks[int(i * step)] for i in range(n)]


def _extract_json(raw: str) -> dict:
    text = raw.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    first, last = text.find("{"), text.rfind("}")
    return json.loads(text[first : last + 1])


async def main() -> None:
    async with AsyncSessionLocal() as session:
        all_chunks = list((await session.execute(select(Chunk).order_by(Chunk.rfc_number, Chunk.id))).scalars())

    by_rfc: dict[str, list[Chunk]] = {}
    for chunk in all_chunks:
        by_rfc.setdefault(chunk.rfc_number, []).append(chunk)

    quotas = _allocate_quotas({rfc: len(cs) for rfc, cs in by_rfc.items()}, TOTAL_QUESTIONS)
    selected = [c for rfc, chunks in by_rfc.items() for c in _pick_evenly_spaced(chunks, quotas[rfc])]

    print(f"Selected {len(selected)} chunks across {len(by_rfc)} RFCs: "
          f"{ {rfc: quotas[rfc] for rfc in by_rfc} }")

    items = []
    for i, chunk in enumerate(selected, start=1):
        prompt = QUESTION_PROMPT.format(
            rfc_number=chunk.rfc_number, section=chunk.section,
            heading=chunk.heading, text=chunk.text,
        )
        raw = await call_claude(prompt, max_tokens=200, role="golden_set_generation")
        try:
            question = _extract_json(raw)["question"]
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            print(f"  [{i}/{len(selected)}] SKIPPED {chunk.citation} — bad model output: {e}")
            continue

        print(f"  [{i}/{len(selected)}] {chunk.citation}: {question}")
        items.append({
            "id": i,
            "rfc_number": chunk.rfc_number,
            "citation": chunk.citation,
            "heading": chunk.heading,
            "question": question,
            "expected_citations": [chunk.citation],
            "source_excerpt": chunk.text[:300],
            "reviewed": False,
        })

    OUTPUT_PATH.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {len(items)} candidates to {OUTPUT_PATH}")
    print("Every item is reviewed: false — review each against the source RFC "
          "before test_rag_triad.py will use any of them.")


if __name__ == "__main__":
    asyncio.run(main())
