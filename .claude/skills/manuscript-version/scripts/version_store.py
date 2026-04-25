"""version_store.py — pure logic for manuscript version history.

No CLI, no side-effects. All functions are pure or read-only filesystem.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


# ---- helpers --------------------------------------------------------------- #

def _versions_dir(manuscript_dir: Path) -> Path:
    return manuscript_dir / "versions"


def snapshot_hash(source_md: str) -> str:
    """Return sha256 hex digest of source.md content."""
    return hashlib.sha256(source_md.encode("utf-8")).hexdigest()


def _parse_version_n(version_id: str) -> int:
    """Extract the integer prefix N from 'v<N>-<timestamp>'."""
    m = re.match(r"^v(\d+)-", version_id)
    if m:
        return int(m.group(1))
    return 0


def make_version_id(manuscript_dir: Path) -> str:
    """Generate the next v<N>-<YYYYMMDD-HHMMSS> id."""
    existing = list_versions(manuscript_dir)
    if existing:
        # version_id list is already sorted ascending; last is highest N
        max_n = max(_parse_version_n(v["version_id"]) for v in existing)
        n = max_n + 1
    else:
        n = 1
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"v{n}-{ts}"


def list_versions(manuscript_dir: Path) -> list[dict]:
    """Return all meta.json records sorted ascending by version_id (v1 first)."""
    vdir = _versions_dir(manuscript_dir)
    if not vdir.exists():
        return []
    records: list[dict] = []
    for meta_path in vdir.glob("*/meta.json"):
        try:
            records.append(json.loads(meta_path.read_text()))
        except (json.JSONDecodeError, OSError):
            pass
    records.sort(key=lambda r: _parse_version_n(r.get("version_id", "")))
    return records


def latest_version(manuscript_dir: Path) -> dict | None:
    """Return the most recent snapshot's meta, or None if none exist."""
    records = list_versions(manuscript_dir)
    return records[-1] if records else None


def section_word_counts(source_md: str) -> dict[str, int]:
    """Return {section_name: word_count} for each ## heading in source_md.

    Word count excludes the heading line itself and HTML comments.
    A special key "_preamble" captures any text before the first ## heading.
    """
    # Strip HTML comments before processing
    text = re.sub(r"<!--.*?-->", "", source_md, flags=re.DOTALL)

    lines = text.splitlines()
    counts: dict[str, int] = {}
    current_section: str = "_preamble"
    current_lines: list[str] = []

    def _flush(section: str, body_lines: list[str]) -> None:
        words = sum(
            len(ln.split())
            for ln in body_lines
            if ln.strip() and not ln.strip().startswith("#")
        )
        counts[section] = words

    for line in lines:
        if line.startswith("## "):
            _flush(current_section, current_lines)
            current_section = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    _flush(current_section, current_lines)
    return counts
