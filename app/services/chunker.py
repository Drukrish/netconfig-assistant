"""Split an RFC plaintext file into section-level chunks with citation metadata.

A citation must point at something concrete and checkable — a section a human
could open the RFC and verify — not just "the corpus". Splitting on the RFC's
own numbered section headings (e.g. "4.2. Checksum Adjustment") gives exactly
that: real chunks readers can look at right where the assistant said to look.
"""

import re
from dataclasses import dataclass
from pathlib import Path

# Matches RFC-style numbered section headings: "1. Introduction", "3.0. Translation
# phases", "2.1 Overview of Basic NAT". Anchored to line start, uppercase heading
# text follows immediately after the number so it doesn't false-match numbered
# list items or addresses embedded in body text.
SECTION_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+([A-Z][A-Za-z].*)$")

# RFC page-break artifacts: form feed, "[Page N]" footers, blank running headers.
PAGE_ARTIFACT = re.compile(r"\x0c|\[Page \d+\]\s*$")

FILENAME_PATTERN = re.compile(r"^rfc(\d+)_(.+)\.txt$")


@dataclass
class Chunk:
    rfc_number: str
    rfc_title: str
    section: str  # e.g. "4.2"
    heading: str  # e.g. "Checksum Adjustment"
    text: str
    source_url: str

    @property
    def citation(self) -> str:
        return f"RFC {self.rfc_number} §{self.section}"


def _extract_title(lines: list[str]) -> str:
    """RFC title is the first all-caps-ish centered line after the header block,
    typically within the first ~15 lines. Fall back to the filename if not found."""
    for line in lines[:15]:
        stripped = line.strip()
        if stripped and stripped == stripped.title() or (stripped and stripped.isupper() and len(stripped) > 3):
            return stripped
    return "Untitled"


def chunk_rfc_file(path: Path) -> list[Chunk]:
    m = FILENAME_PATTERN.match(path.name)
    if not m:
        raise ValueError(f"Filename doesn't match rfcNNNN_Name.txt: {path.name}")
    rfc_number, _ = m.groups()
    source_url = f"https://www.rfc-editor.org/rfc/rfc{rfc_number}.txt"

    raw = path.read_text(encoding="utf-8", errors="replace")
    lines = [PAGE_ARTIFACT.sub("", ln) for ln in raw.splitlines()]
    title = _extract_title(lines)

    # Walk lines, opening a new chunk at each section heading and accumulating
    # body text until the next one.
    chunks: list[Chunk] = []
    current_section: str | None = None
    current_heading: str | None = None
    buffer: list[str] = []

    def flush():
        if current_section is not None:
            text = "\n".join(buffer).strip()
            if text:
                chunks.append(
                    Chunk(
                        rfc_number=rfc_number,
                        rfc_title=title,
                        section=current_section,
                        heading=current_heading or "",
                        text=text,
                        source_url=source_url,
                    )
                )

    for line in lines:
        heading_match = SECTION_HEADING.match(line)
        if heading_match:
            flush()
            current_section, current_heading = heading_match.groups()
            buffer = []
        else:
            buffer.append(line)
    flush()

    return chunks


def chunk_corpus(corpus_dir: Path) -> list[Chunk]:
    all_chunks: list[Chunk] = []
    for rfc_file in sorted(corpus_dir.glob("rfc*.txt")):
        all_chunks.extend(chunk_rfc_file(rfc_file))
    return all_chunks


def demo() -> None:
    """Run with `python -m app.services.chunker` from the project root.
    No API calls, no DB — proves the chunker produces real, checkable chunks
    before anything downstream (embeddings, retrieval) is built on top of it."""
    corpus_dir = Path(__file__).resolve().parents[2] / "corpus" / "rfcs"
    chunks = chunk_corpus(corpus_dir)

    assert chunks, "chunker produced zero chunks — something is wrong with the corpus or the regex"

    by_rfc: dict[str, int] = {}
    for c in chunks:
        by_rfc[c.rfc_number] = by_rfc.get(c.rfc_number, 0) + 1

    print(f"{len(chunks)} chunks across {len(by_rfc)} RFCs")
    for rfc, count in sorted(by_rfc.items()):
        print(f"  RFC {rfc}: {count} sections")

    sample = chunks[len(chunks) // 2]
    print(f"\nsample chunk: {sample.citation} — {sample.heading}")
    print(f"  source: {sample.source_url}")
    print(f"  text preview: {sample.text[:200]!r}")

    # Every chunk must carry enough metadata to actually be cited and verified.
    for c in chunks:
        assert c.rfc_number, "chunk missing rfc_number"
        assert c.section, "chunk missing section number"
        assert c.source_url.startswith("https://www.rfc-editor.org/rfc/"), "bad source_url"
        assert len(c.text) > 0, f"empty chunk body at {c.citation}"

    print("\nchunker self-check passed: every chunk has rfc_number, section, source_url, non-empty text")


if __name__ == "__main__":
    demo()
