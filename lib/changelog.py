"""v0.79 — derive CHANGELOG.md from ROADMAP.md "Shipped" sections.

Walks ROADMAP.md, extracts every `### v0.X — <title>` heading under a
`## Shipped` block + the body text below it, emits a chronologically
ordered CHANGELOG.md.

Pure stdlib regex.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChangelogEntry:
    version: str  # e.g. "v0.78"
    title: str    # e.g. "feature loop closure"
    date: str     # e.g. "2026-04-28" (or "" if none)
    body: str     # markdown body (may be empty)


_HEADING_RE = re.compile(
    r"^### (v\d+\.\d+(?:\.\d+)?(?:[a-z])?)\s*"
    r"(?:[—-]\s*([^\n✅]+?))?"
    r"\s*(?:✅\s*\(([^)]+)\))?\s*$",
    re.MULTILINE,
)


def parse_roadmap(text: str) -> list[ChangelogEntry]:
    """Return every ### v* heading from ROADMAP.md `## Shipped` sections.

    Order: as encountered (newest first in ROADMAP convention).
    """
    out: list[ChangelogEntry] = []
    matches = list(_HEADING_RE.finditer(text))
    for i, m in enumerate(matches):
        version = m.group(1).strip()
        title = (m.group(2) or "").strip()
        date = (m.group(3) or "").strip()
        body_start = m.end()
        body_end = (
            matches[i + 1].start() if i + 1 < len(matches) else len(text)
        )
        body = text[body_start:body_end].strip()
        # Cut off the body at the next `## ` heading (next major section).
        next_section = re.search(r"^## ", body, re.MULTILINE)
        if next_section:
            body = body[:next_section.start()].rstrip()
        out.append(ChangelogEntry(
            version=version, title=title, date=date, body=body,
        ))
    return out


def _version_key(entry: ChangelogEntry) -> tuple[int, ...]:
    """Sort-key: parse v0.78a → (0, 78, 1). Letters become indices."""
    s = entry.version.lstrip("v")
    parts = s.split(".")
    nums: list[int] = []
    for p in parts:
        m = re.match(r"^(\d+)([a-z]?)$", p)
        if m:
            nums.append(int(m.group(1)))
            if m.group(2):
                nums.append(ord(m.group(2)) - ord("a") + 1)
        else:
            try:
                nums.append(int(p))
            except ValueError:
                nums.append(0)
    return tuple(nums)


_HEADER = """# Changelog

Auto-generated from ROADMAP.md by `lib/changelog.py`. Regenerate via:

```bash
uv run python -m lib.changelog > CHANGELOG.md
```

A test (`tests/test_changelog.py`) asserts this file matches the
generator output, so a stale `CHANGELOG.md` will fail CI.

Versions are listed newest first.
"""


def render_changelog(entries: list[ChangelogEntry]) -> str:
    sorted_entries = sorted(
        entries, key=_version_key, reverse=True,
    )
    lines = [_HEADER.rstrip("\n")]
    for e in sorted_entries:
        lines.append("")
        date_str = f" ({e.date})" if e.date else ""
        title = f" — {e.title}" if e.title else ""
        lines.append(f"## {e.version}{title}{date_str}")
        if e.body:
            lines.append("")
            lines.append(e.body)
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    roadmap = repo_root / "ROADMAP.md"
    entries = parse_roadmap(roadmap.read_text())
    print(render_changelog(entries), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
