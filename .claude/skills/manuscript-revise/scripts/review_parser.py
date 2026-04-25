"""review_parser — pure parsing of journal reviewer comment text.

No CLI, no side effects. Import and call.

Public API
----------
parse_review(text)         -> list[dict]   [{reviewer, comment_num, text}]
count_comments(parsed)     -> dict         {reviewer_id: count}
format_response_stub(comment) -> str       markdown stub for one comment
"""

from __future__ import annotations

import re
from typing import Any

# Match "Reviewer N:" or "Reviewer N" at start of a line (N = integer)
_REVIEWER_HEADER = re.compile(
    r"^\s*Reviewer\s+(\d+)\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Match numbered comment starters: "1.", "1)", "(1)", "[1]"
_COMMENT_NUM = re.compile(
    r"^\s*(?:\[(\d+)\]|\((\d+)\)|(\d+)[.):])\s+(.*)"
)


def parse_review(text: str) -> list[dict]:
    """Parse reviewer comment text into a flat list of comment dicts.

    Each dict has: {reviewer: int, comment_num: int, text: str}

    Handles:
    - "Reviewer N:" / "Reviewer N" headers
    - Numbered comments: 1. / 1) / (1) / [1]
    - Multi-paragraph comments (blank lines within a numbered block are
      treated as paragraph breaks within the same comment)
    - Blank lines between numbered items trigger the end of the previous item
    """
    if not text or not text.strip():
        return []

    # Split into reviewer blocks by locating all Reviewer headers
    headers = list(_REVIEWER_HEADER.finditer(text))
    if not headers:
        return []

    results: list[dict] = []

    for i, header in enumerate(headers):
        reviewer_id = int(header.group(1))
        block_start = header.end()
        block_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        block = text[block_start:block_end]

        comments = _parse_comments_block(reviewer_id, block)
        results.extend(comments)

    return results


def _parse_comments_block(reviewer_id: int, block: str) -> list[dict]:
    """Extract numbered comments from a single reviewer's block."""
    lines = block.splitlines()
    comments: list[dict] = []
    current_num: int | None = None
    current_lines: list[str] = []

    def _flush():
        if current_num is not None and current_lines:
            body = " ".join(
                line.strip() for line in current_lines if line.strip()
            ).strip()
            if body:
                comments.append({
                    "reviewer": reviewer_id,
                    "comment_num": current_num,
                    "text": body,
                })

    for line in lines:
        m = _COMMENT_NUM.match(line)
        if m:
            # Start of a new numbered comment — flush previous
            _flush()
            current_num = int(m.group(1) or m.group(2) or m.group(3))
            current_lines = [m.group(4)]
        elif current_num is not None:
            # Continuation line (including blank lines within a comment)
            current_lines.append(line)

    _flush()
    return comments


def count_comments(parsed: list[dict]) -> dict[int, int]:
    """Return {reviewer_id: comment_count} mapping."""
    counts: dict[int, int] = {}
    for c in parsed:
        rid = c["reviewer"]
        counts[rid] = counts.get(rid, 0) + 1
    return counts


def format_response_stub(comment: dict) -> str:
    """Return a markdown stub for one reviewer comment.

    Format:
        ## [REVIEWER N, COMMENT M]

        > <original comment text>

        [YOUR RESPONSE HERE]
    """
    reviewer = comment["reviewer"]
    num = comment["comment_num"]
    text = comment["text"]

    # Quote the comment text, handling multi-line gracefully
    quoted_lines = "\n".join(f"> {line}" if line.strip() else ">"
                             for line in text.splitlines())
    if not quoted_lines:
        quoted_lines = f"> {text}"

    return (
        f"## [REVIEWER {reviewer}, COMMENT {num}]\n\n"
        f"{quoted_lines}\n\n"
        f"[YOUR RESPONSE HERE]\n"
    )
