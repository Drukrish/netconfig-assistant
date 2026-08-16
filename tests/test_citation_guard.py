"""Structural citation layer as real pytest cases — same seven assertions as
citation_guard.demo(), wired into the suite so CI runs them instead of
requiring a manual `python -m app.services.citation_guard`. No API calls, no
DB: this is the fast, free layer.
"""

from app.services.citation_guard import check_citations

RETRIEVED = ["RFC 2328 §10.6", "RFC 4271 §5.1.2", "RFC 2131 §4.1"]


def test_real_citation_passes():
    result = check_citations(["RFC 2328 §10.6"], RETRIEVED)
    assert result.passed


def test_multiple_real_citations_pass():
    result = check_citations(["RFC 2328 §10.6", "RFC 4271 §5.1.2"], RETRIEVED)
    assert result.passed


def test_uncited_response_fails():
    result = check_citations([], RETRIEVED)
    assert not result.passed


def test_fabricated_citation_fails():
    result = check_citations(["RFC 9999 §1.1"], RETRIEVED)
    assert not result.passed
    assert "RFC 9999 §1.1" in result.unverifiable


def test_one_fabricated_citation_fails_whole_response():
    """The realistic adversarial case: one real citation plus one fabricated
    one, hoping the real one covers for the fake. Must still fail — a
    response isn't partially trustworthy."""
    result = check_citations(["RFC 2328 §10.6", "RFC 9999 §1.1"], RETRIEVED)
    assert not result.passed


def test_near_miss_section_number_fails():
    """Wrong section number must fail, not fuzzy-match to a real one."""
    result = check_citations(["RFC 2328 §10.7"], RETRIEVED)
    assert not result.passed
