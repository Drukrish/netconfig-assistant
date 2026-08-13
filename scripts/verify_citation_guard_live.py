"""Live verification against the real Anthropic API and the real corpus.
Costs real money to run (a few cents) - not part of CI, a documented record
of the first real test.

Run with: python scripts/verify_citation_guard_live.py

Two real, dated findings from the first run of this script (2026-08-13):

1. Asked "How does OSPF calculate the cost of a route?" The model answered
   using RFC 2328 section 16 ("Calculation of the routing table") but cited
   invented subsections - "RFC 2328 §16.1" through "§16.8" - that do not
   exist. Confirmed directly against the raw RFC text: section 16 has no
   subsections at all, just one flat section. The guardrail rejected the
   answer. This is the exact failure mode the whole project exists to catch,
   caught on the very first live query, not staged.

2. Asked "What is the giaddr field used for in DHCP?" The model answered
   correctly and cited three real chunks (RFC 2131 §2, §4.1, §4.3.1), all
   genuinely present in the retrieved set. The guardrail passed it. Proves
   the gate isn't just rejecting everything - it discriminates real citations
   from fabricated ones.
"""

import asyncio

from app.database import AsyncSessionLocal
from app.services.generator import answer_question


async def run_case(question: str) -> bool:
    """Reports the observed outcome rather than asserting a fixed expected
    one. Sonnet 5 refuses a pinned temperature (same finding as growth-os),
    so generation is non-deterministic - re-running the OSPF question is not
    guaranteed to hallucinate the same way twice. Hard-asserting a specific
    pass/fail here would make this flake for the wrong reason: a rerun that
    behaves *better* than the first run isn't a bug."""
    async with AsyncSessionLocal() as session:
        result = await answer_question(session, question)

    status = "PASS" if result.citation_check.passed else "REJECTED"
    print(f"[{status}] {question!r}")
    print(f"    reason: {result.citation_check.reason}")
    return result.citation_check.passed


async def main() -> None:
    await run_case("How does OSPF calculate the cost of a route?")
    await run_case("What is the giaddr field used for in DHCP?")
    print(
        "\nRecorded outcomes above. The dated finding in this file's docstring is what "
        "happened on 2026-08-13's first run, not a claim this run will match it - see the "
        "non-determinism note in run_case()."
    )


if __name__ == "__main__":
    asyncio.run(main())
