"""Structural citation enforcement — the guardrail-as-code pattern from
growth-os's scanDraft(). One function, called both by the API before a
response leaves it AND by the eval suite in Week 4, so the two cannot drift
apart the way growth-os's Day 3 guardrail bug happened.

A response citing a chunk that wasn't actually retrieved is rejected, not
trusted. This is the safety mechanism the whole project exists to
demonstrate: a hallucinated network config command citing a source that
doesn't say what the model claims it says is exactly the failure mode that
takes down production.
"""

from dataclasses import dataclass


@dataclass
class CitationCheck:
    passed: bool
    cited: list[str]
    retrieved: list[str]
    unverifiable: list[str]  # cited but not in the retrieved set
    reason: str


def check_citations(cited: list[str], retrieved_citations: list[str]) -> CitationCheck:
    """`cited` is what the model's response claims to cite. `retrieved_citations`
    is the actual set of chunk citations that were retrieved for this query
    (e.g. from RetrievedChunk.chunk.citation). A response must cite at least
    one source, and every citation it makes must be verifiable against what
    was actually retrieved — not just plausible-sounding.
    """
    if not cited:
        return CitationCheck(
            passed=False,
            cited=cited,
            retrieved=retrieved_citations,
            unverifiable=[],
            reason="response cited nothing — an unsourced network-config answer is not acceptable output",
        )

    retrieved_set = set(retrieved_citations)
    unverifiable = [c for c in cited if c not in retrieved_set]

    if unverifiable:
        return CitationCheck(
            passed=False,
            cited=cited,
            retrieved=retrieved_citations,
            unverifiable=unverifiable,
            reason=(
                f"response cited {unverifiable} which were not in the retrieved set — "
                "cannot verify the model didn't fabricate the source"
            ),
        )

    return CitationCheck(
        passed=True,
        cited=cited,
        retrieved=retrieved_citations,
        unverifiable=[],
        reason=f"all {len(cited)} citation(s) verified against the retrieved set",
    )


def demo() -> None:
    """Run with `python -m app.services.citation_guard`. No API calls, no DB —
    proves the gate can actually fail before trusting it when it passes."""

    def assert_(ok: bool, msg: str) -> None:
        if not ok:
            raise AssertionError("FAILED: " + msg)

    retrieved = ["RFC 2328 §10.6", "RFC 4271 §5.1.2", "RFC 2131 §4.1"]

    good = check_citations(["RFC 2328 §10.6"], retrieved)
    assert_(good.passed, "a citation that was actually retrieved must pass")

    multi = check_citations(["RFC 2328 §10.6", "RFC 4271 §5.1.2"], retrieved)
    assert_(multi.passed, "multiple real citations must pass")

    uncited = check_citations([], retrieved)
    assert_(not uncited.passed, "an uncited response must fail — that's the whole point of the guardrail")

    fabricated = check_citations(["RFC 9999 §1.1"], retrieved)
    assert_(not fabricated.passed, "a citation not in the retrieved set must fail")
    assert_("RFC 9999 §1.1" in fabricated.unverifiable, "the fabricated citation must be named in the failure")

    # The realistic adversarial case: model cites one real source and one
    # fabricated one, hoping the real one covers for the fake. Must still fail.
    mixed = check_citations(["RFC 2328 §10.6", "RFC 9999 §1.1"], retrieved)
    assert_(not mixed.passed, "one fabricated citation must fail the whole response, not be diluted by a real one")

    # A citation string that's almost right but not exact (wrong section) must
    # still fail — "close enough" is not verifiable.
    near_miss = check_citations(["RFC 2328 §10.7"], retrieved)
    assert_(not near_miss.passed, "a near-miss section number must fail, not fuzzy-match")

    print("citation_guard.py self-check passed (7 assertions)")


if __name__ == "__main__":
    demo()
