"""section.py — operations on the source.md section blocks.

Sections in source.md are delimited by level-2 headings:

    ## Introduction

    [PLACEHOLDER]

    ## Methods

    ...

A section runs from its own heading (inclusive) to the next ## heading
(exclusive), or to end-of-file. The heading text must match the section's
`heading` field from the outline (case-insensitive, stripped).

find_cite_keys() scans a block of text for all four citation styles so the
outline can record which keys were used in each section.
"""

from __future__ import annotations

import re
from typing import Optional

# Citation patterns shared with manuscript-ingest (kept in sync manually)
_LATEX_CITE = re.compile(r"\\cite[a-z]*\{([^}]+)\}")
_PANDOC_CITE = re.compile(r"\[@([A-Za-z][^;\]\s]*)")
_NUMERIC_CITE = re.compile(r"\[(\d+(?:\s*[,\-]\s*\d+)*)\]")
_AUTHORYEAR_CITE = re.compile(r"\(([A-Z][a-zA-Z]+(?:\s+et\s+al\.?)?,?\s+\d{4}[a-z]?)\)")

# Heading line: ## ... (exactly two hashes, then space)
_H2 = re.compile(r"^##\s+.+", re.MULTILINE)


def _section_bounds(source: str, heading: str) -> Optional[tuple[int, int]]:
    """Return (start, end) byte offsets for the section with the given heading.

    start is the position of the ## line; end is the start of the next ##
    heading or len(source). Returns None if the heading is not found.

    Matching is case-insensitive and strips leading/trailing whitespace.
    """
    target = heading.strip().lower()
    for m in _H2.finditer(source):
        line_text = m.group(0).lstrip("#").strip().lower()
        if line_text == target:
            start = m.start()
            # Find the next ## heading after this one
            rest_offset = m.end()
            next_h2 = _H2.search(source, rest_offset)
            end = next_h2.start() if next_h2 else len(source)
            return (start, end)
    return None


def extract_section(source: str, heading: str) -> Optional[str]:
    """Return the raw text of a section (including its ## heading line)."""
    bounds = _section_bounds(source, heading)
    if bounds is None:
        return None
    return source[bounds[0]:bounds[1]]


def replace_section(source: str, heading: str, new_body: str) -> str:
    """Replace the body of a section, keeping the ## heading line intact.

    new_body should NOT include the ## heading line; it is appended after it.
    If the section does not exist, the source is returned unchanged.

    Trailing newline is normalised to exactly one blank line between sections.
    """
    bounds = _section_bounds(source, heading)
    if bounds is None:
        return source

    start, end = bounds
    # Keep the heading line (first line of the section block)
    heading_line_end = source.index("\n", start) + 1
    heading_line = source[start:heading_line_end]

    body = new_body.strip("\n")
    replacement = heading_line + "\n" + body + "\n\n"

    return source[:start] + replacement + source[end:]


def placeholder_body(section_name: str, notes: str, target_words: int) -> str:
    """Generate a placeholder body for a section not yet drafted."""
    lines = [f"[PLACEHOLDER — {section_name} not yet drafted]"]
    if notes:
        lines.append("")
        lines.append(f"<!-- notes: {notes} -->")
    if target_words:
        lines.append(f"<!-- target: ~{target_words} words -->")
    return "\n".join(lines)


def count_words(text: str) -> int:
    """Count whitespace-delimited tokens, excluding markdown headings and comments."""
    # Strip HTML comments
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    # Strip markdown heading markers and blank lines
    lines = [
        ln for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    return sum(len(ln.split()) for ln in lines)


def find_cite_keys(text: str) -> list[str]:
    """Extract all citation keys from text, deduplicated, sorted."""
    keys: set[str] = set()

    for m in _LATEX_CITE.finditer(text):
        for k in m.group(1).split(","):
            keys.add(k.strip())

    for m in _PANDOC_CITE.finditer(text):
        keys.add(m.group(1).strip())

    # Numeric citations produce ordinals, not keys — skip for key collection
    # Author-year hits are stored as-is (they're not resolvable to BibTeX keys
    # without a resolver pass, but they're useful for audit)
    for m in _AUTHORYEAR_CITE.finditer(text):
        keys.add(m.group(1).strip())

    return sorted(keys)


def build_source_md(title: str, venue_full_name: str, manuscript_id: str,
                    sections: list[dict]) -> str:
    """Assemble a complete source.md from outline sections.

    sections is a list of dicts with keys: heading, name, notes, target_words.
    Each section body is a placeholder.
    """
    header = (
        f"---\n"
        f"title: \"{title}\"\n"
        f"venue: {venue_full_name}\n"
        f"manuscript_id: {manuscript_id}\n"
        f"---\n\n"
        f"# {title}\n\n"
    )
    parts = [header]
    for s in sections:
        body = placeholder_body(s["name"], s.get("notes", ""), s.get("target_words", 0))
        parts.append(f"## {s['heading']}\n\n{body}\n\n")
    return "".join(parts)
