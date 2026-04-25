"""outline.py — outline data model and template loading for manuscript-draft.

An outline is the authoritative record of a draft's section structure. It lives
at <manuscript_dir>/outline.json alongside manifest.json. Every section has a
status field that draft.py uses to track progress.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

KNOWN_VENUES = {"imrad", "neurips", "acl", "nature", "thesis"}


@dataclass
class SectionOutline:
    name: str           # machine name, e.g. "introduction"
    heading: str        # display heading, e.g. "Introduction"
    ordinal: int
    target_words: int
    required: bool
    notes: str
    status: str = "placeholder"     # placeholder | drafted | revised
    word_count: int = 0
    cite_keys: list[str] = field(default_factory=list)


@dataclass
class Outline:
    manuscript_id: str
    title: str
    venue: str
    venue_full_name: str
    word_limit: int
    created_at: str
    sections: list[SectionOutline]
    extras: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Template loading                                                             #
# --------------------------------------------------------------------------- #

def load_template(venue: str) -> dict:
    """Load a venue template dict. Raises ValueError for unknown venues."""
    venue = venue.lower()
    if venue not in KNOWN_VENUES:
        raise ValueError(
            f"Unknown venue {venue!r}. Known: {', '.join(sorted(KNOWN_VENUES))}"
        )
    path = _TEMPLATES_DIR / f"{venue}.json"
    return json.loads(path.read_text())


def outline_from_template(manuscript_id: str, title: str, venue: str) -> Outline:
    """Build a fresh Outline from a venue template."""
    tmpl = load_template(venue)
    sections = [
        SectionOutline(
            name=s["name"],
            heading=s["heading"],
            ordinal=s["ordinal"],
            target_words=s["target_words"],
            required=s["required"],
            notes=s["notes"],
        )
        for s in tmpl["sections"]
    ]
    return Outline(
        manuscript_id=manuscript_id,
        title=title,
        venue=venue,
        venue_full_name=tmpl["full_name"],
        word_limit=tmpl["word_limit"],
        created_at=datetime.now(UTC).isoformat(),
        sections=sections,
    )


# --------------------------------------------------------------------------- #
# Persistence                                                                  #
# --------------------------------------------------------------------------- #

def save_outline(outline: Outline, manuscript_dir: Path) -> None:
    path = manuscript_dir / "outline.json"
    data = asdict(outline)
    path.write_text(json.dumps(data, indent=2, default=str))


def load_outline(manuscript_dir: Path) -> Outline:
    path = manuscript_dir / "outline.json"
    if not path.exists():
        raise FileNotFoundError(f"No outline.json in {manuscript_dir}")
    data = json.loads(path.read_text())
    sections = [SectionOutline(**s) for s in data.pop("sections")]
    return Outline(sections=sections, **data)


# --------------------------------------------------------------------------- #
# Section helpers                                                              #
# --------------------------------------------------------------------------- #

def get_section(outline: Outline, name: str) -> SectionOutline:
    for s in outline.sections:
        if s.name == name:
            return s
    raise KeyError(f"No section {name!r} in outline for venue {outline.venue!r}. "
                   f"Known: {', '.join(s.name for s in outline.sections)}")


def update_section_stats(
    outline: Outline,
    name: str,
    word_count: int,
    cite_keys: list[str],
    status: str = "drafted",
) -> None:
    """Update section word_count, cite_keys, and status in place."""
    sec = get_section(outline, name)
    sec.word_count = word_count
    sec.cite_keys = cite_keys
    sec.status = status


def total_word_count(outline: Outline) -> int:
    return sum(s.word_count for s in outline.sections)


def completion_summary(outline: Outline) -> dict[str, int]:
    """Return counts by status."""
    counts: dict[str, int] = {"placeholder": 0, "drafted": 0, "revised": 0}
    for s in outline.sections:
        counts[s.status] = counts.get(s.status, 0) + 1
    return counts
