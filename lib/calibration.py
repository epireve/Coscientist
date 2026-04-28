"""Calibration set management (v0.61).

Per-venue reference set of known-accepted / known-rejected / borderline
papers, used by `publishability-check` to anchor verdicts against
empirical priors instead of model intuition.

Storage: filesystem JSON at
  ~/.cache/coscientist/calibration/venues/<venue-slug>.json

Schema:
  {
    "venue": "NeurIPS 2024",
    "accepted":   [{"title", "canonical_id"?, "doi"?, "reasons_for_accept": [...], "year"?, "added_at"}, ...],
    "rejected":   [{"title", "canonical_id"?, "doi"?, "reasons_for_reject": [...], "year"?, "added_at"}, ...],
    "borderline": [{"title", "canonical_id"?, "doi"?, "outcome", "notes": "...", "year"?, "added_at"}, ...]
  }

Pure stdlib; no LLM, no MCP. The user maintains the set manually
through this skill's CLI.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

Bucket = Literal["accepted", "rejected", "borderline"]
_VALID_BUCKETS = ("accepted", "rejected", "borderline")


def slugify_venue(name: str) -> str:
    """Lowercase + alphanumeric/hyphen-only slug for filename."""
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


@dataclass
class CalibrationCase:
    title: str
    canonical_id: str | None = None
    doi: str | None = None
    year: int | None = None
    reasons: list[str] = field(default_factory=list)
    notes: str = ""
    outcome: str = ""  # for borderline entries
    added_at: str = ""

    def to_dict(self, bucket: Bucket) -> dict:
        d = {
            "title": self.title,
            "canonical_id": self.canonical_id,
            "doi": self.doi,
            "year": self.year,
            "added_at": self.added_at,
        }
        if bucket == "accepted":
            d["reasons_for_accept"] = list(self.reasons)
        elif bucket == "rejected":
            d["reasons_for_reject"] = list(self.reasons)
        else:
            d["outcome"] = self.outcome
            d["notes"] = self.notes
        return {k: v for k, v in d.items() if v not in (None, "")}

    @classmethod
    def from_dict(cls, d: dict, bucket: Bucket) -> CalibrationCase:
        reasons: list[str] = []
        if bucket == "accepted":
            reasons = d.get("reasons_for_accept", []) or []
        elif bucket == "rejected":
            reasons = d.get("reasons_for_reject", []) or []
        return cls(
            title=d["title"],
            canonical_id=d.get("canonical_id"),
            doi=d.get("doi"),
            year=d.get("year"),
            reasons=list(reasons),
            notes=d.get("notes", ""),
            outcome=d.get("outcome", ""),
            added_at=d.get("added_at", ""),
        )


@dataclass
class CalibrationSet:
    venue: str
    accepted: list[CalibrationCase] = field(default_factory=list)
    rejected: list[CalibrationCase] = field(default_factory=list)
    borderline: list[CalibrationCase] = field(default_factory=list)

    def n_total(self) -> int:
        return len(self.accepted) + len(self.rejected) + len(self.borderline)

    def to_dict(self) -> dict:
        return {
            "venue": self.venue,
            "accepted": [c.to_dict("accepted") for c in self.accepted],
            "rejected": [c.to_dict("rejected") for c in self.rejected],
            "borderline": [c.to_dict("borderline") for c in self.borderline],
        }

    @classmethod
    def from_dict(cls, d: dict) -> CalibrationSet:
        return cls(
            venue=d.get("venue", ""),
            accepted=[
                CalibrationCase.from_dict(x, "accepted")
                for x in d.get("accepted", []) or []
            ],
            rejected=[
                CalibrationCase.from_dict(x, "rejected")
                for x in d.get("rejected", []) or []
            ],
            borderline=[
                CalibrationCase.from_dict(x, "borderline")
                for x in d.get("borderline", []) or []
            ],
        )


def calibration_dir(cache_root: Path) -> Path:
    p = cache_root / "calibration" / "venues"
    p.mkdir(parents=True, exist_ok=True)
    return p


def calibration_path(cache_root: Path, venue: str) -> Path:
    return calibration_dir(cache_root) / f"{slugify_venue(venue)}.json"


def load(cache_root: Path, venue: str) -> CalibrationSet:
    """Load (or initialize empty) calibration set for `venue`."""
    p = calibration_path(cache_root, venue)
    if not p.exists():
        return CalibrationSet(venue=venue)
    data = json.loads(p.read_text())
    return CalibrationSet.from_dict(data)


def save(cache_root: Path, cset: CalibrationSet) -> Path:
    """Atomic-ish write: tmp + rename."""
    p = calibration_path(cache_root, cset.venue)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cset.to_dict(), indent=2, sort_keys=True))
    tmp.rename(p)
    return p


def add_case(
    cset: CalibrationSet, bucket: Bucket, case: CalibrationCase,
) -> None:
    """Append a case to the chosen bucket; refuses duplicate (by
    canonical_id if present, else by exact title match).
    """
    if bucket not in _VALID_BUCKETS:
        raise ValueError(
            f"bucket must be one of {_VALID_BUCKETS}; got {bucket!r}"
        )
    bucket_list = getattr(cset, bucket)
    for existing in bucket_list:
        if case.canonical_id and existing.canonical_id == case.canonical_id:
            raise ValueError(
                f"calibration set already has canonical_id "
                f"{case.canonical_id!r} in {bucket}"
            )
        if not case.canonical_id and existing.title.lower() == case.title.lower():
            raise ValueError(
                f"calibration set already has title {case.title!r} in {bucket}"
            )
    if not case.added_at:
        case.added_at = datetime.now(UTC).isoformat()
    bucket_list.append(case)


def remove_case(
    cset: CalibrationSet, bucket: Bucket, *,
    canonical_id: str | None = None, title: str | None = None,
) -> bool:
    """Remove a case by canonical_id or title. Returns True if removed."""
    if bucket not in _VALID_BUCKETS:
        raise ValueError(f"bucket must be one of {_VALID_BUCKETS}")
    if not canonical_id and not title:
        raise ValueError("provide canonical_id or title")
    bucket_list = getattr(cset, bucket)
    for i, c in enumerate(bucket_list):
        match = (
            (canonical_id and c.canonical_id == canonical_id)
            or (title and c.title.lower() == title.lower())
        )
        if match:
            bucket_list.pop(i)
            return True
    return False


def render_summary(cset: CalibrationSet) -> str:
    """One-screen markdown summary of a calibration set."""
    lines = [
        f"# Calibration set — {cset.venue}",
        "",
        f"**Total cases**: {cset.n_total()}",
        f"- Accepted: {len(cset.accepted)}",
        f"- Rejected: {len(cset.rejected)}",
        f"- Borderline: {len(cset.borderline)}",
        "",
    ]
    for bucket_name in ("accepted", "rejected", "borderline"):
        cases: list[CalibrationCase] = getattr(cset, bucket_name)
        if not cases:
            continue
        lines.append(f"## {bucket_name.capitalize()} ({len(cases)})")
        lines.append("")
        for c in cases:
            year = f" ({c.year})" if c.year else ""
            lines.append(f"- **{c.title}**{year}")
            if c.canonical_id:
                lines.append(f"  - `canonical_id`: {c.canonical_id}")
            if c.doi:
                lines.append(f"  - `doi`: {c.doi}")
            if c.reasons:
                lines.append("  - Reasons: " + "; ".join(c.reasons))
            if c.outcome:
                lines.append(f"  - Outcome: {c.outcome}")
            if c.notes:
                lines.append(f"  - Notes: {c.notes}")
        lines.append("")
    return "\n".join(lines)


def coverage_check(cset: CalibrationSet) -> dict:
    """Read-only health check on a calibration set.

    Surfaces:
      - n_total (total cases)
      - sufficient (>= 5 cases per bucket recommended; flag below)
      - missing_buckets (which of accepted/rejected/borderline are empty)
      - n_with_canonical_id (anchored to real papers)
    """
    out = {
        "venue": cset.venue,
        "n_total": cset.n_total(),
        "n_accepted": len(cset.accepted),
        "n_rejected": len(cset.rejected),
        "n_borderline": len(cset.borderline),
        "missing_buckets": [
            b for b in _VALID_BUCKETS
            if len(getattr(cset, b)) == 0
        ],
        "below_recommended": [
            b for b in _VALID_BUCKETS
            if 0 < len(getattr(cset, b)) < 3
        ],
    }
    n_anchored = sum(
        1 for b in _VALID_BUCKETS for c in getattr(cset, b)
        if c.canonical_id
    )
    out["n_with_canonical_id"] = n_anchored
    out["anchored_pct"] = (
        round(100.0 * n_anchored / cset.n_total(), 1)
        if cset.n_total() else 0.0
    )
    return out
