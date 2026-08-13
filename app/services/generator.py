"""Ties retrieval, generation, and citation enforcement together. The model
is asked to answer ONLY from the retrieved chunks and to cite every claim —
then citation_guard verifies that structurally rather than trusting the
model's word for it. A response failing the guard is rejected before it
reaches a caller, not flagged and returned anyway.
"""

import json
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai import call_claude
from app.services.citation_guard import CitationCheck, check_citations
from app.services.retriever import RetrievedChunk, hybrid_search


@dataclass
class AnswerResult:
    answer: str | None
    citations: list[str]
    retrieved: list[RetrievedChunk]
    citation_check: CitationCheck
    raw_model_output: str


def _build_prompt(query: str, chunks: list[RetrievedChunk]) -> str:
    context = "\n\n".join(
        f"[{r.chunk.citation}] {r.chunk.heading}\n{r.chunk.text}" for r in chunks
    )
    return f"""You answer network configuration questions using ONLY the reference material below. \
Do not use any knowledge outside it, even if you know the answer — this material is what will be cited \
as the source, so an answer from outside it cannot be verified.

Reference material:
{context}

Question: {query}

Respond with ONLY a JSON object, no prose outside it:
{{"answer": "...", "citations": ["RFC NNNN §X.Y", ...]}}

"citations" must list every source you actually drew on, using the exact bracketed citation labels \
above (e.g. "RFC 2131 §4.1"). If the reference material does not contain enough information to \
answer, say so plainly in "answer" and return an empty citations list — do not guess."""


def _extract_json(raw: str) -> dict:
    """Tolerates the model wrapping its reply in prose or a ```json fence,
    same defensive parsing as growth-os's extractJsonPayload."""
    text = raw.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    first = text.find("{")
    last = text.rfind("}")
    if first == -1 or last == -1:
        raise ValueError(f"no JSON object found in model output: {raw[:200]!r}")
    return json.loads(text[first : last + 1])


async def answer_question(session: AsyncSession, query: str, k: int = 5) -> AnswerResult:
    retrieved = await hybrid_search(session, query, k=k)

    if not retrieved:
        empty_check = check_citations([], [])
        return AnswerResult(
            answer=None, citations=[], retrieved=[], citation_check=empty_check, raw_model_output=""
        )

    prompt = _build_prompt(query, retrieved)
    raw = await call_claude(prompt, max_tokens=1500)

    try:
        parsed = _extract_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        failed_check = CitationCheck(
            passed=False, cited=[], retrieved=[r.chunk.citation for r in retrieved],
            unverifiable=[], reason=f"model output was not valid JSON: {e}",
        )
        return AnswerResult(
            answer=None, citations=[], retrieved=retrieved, citation_check=failed_check, raw_model_output=raw,
        )

    answer = parsed.get("answer")
    citations = parsed.get("citations", [])
    retrieved_citations = [r.chunk.citation for r in retrieved]

    check = check_citations(citations, retrieved_citations)

    return AnswerResult(
        answer=answer if check.passed else None,  # structural rejection: no answer without verified citations
        citations=citations,
        retrieved=retrieved,
        citation_check=check,
        raw_model_output=raw,
    )
