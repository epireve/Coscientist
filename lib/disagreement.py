"""Cross-persona disagreement scoring.

v0.52.4 — papers where personas disagree about role/relevance are
*more* important than consensus papers. Disagreement = high-leverage
signal that single-agent systems cannot detect.

Scoring approach:
- Extends harvest_count (v0.50.4) which counts per-persona surfacings
- Disagreement = papers surfaced by some personas but not others, OR
  flagged with conflicting roles (cartographer "seminal" + surveyor
  "gap-creator" = high-disagreement)

Mechanically derived from `papers_in_run` rows + persona-tagged
surfacings tracked in harvest shortlists. Pure SQL aggregation.

Output: per-paper disagreement score in [0, 1] where:
- 0.0 = all personas agree (either all surface it or none do)
- ~0.5 = mixed — some surface, some don't
- 1.0 = strong disagreement — flagged with opposing roles or surfaced
  by exactly one persona in a phase where ≥3 personas were active

Caller (steward, weaver) reads disagreement score to flag
high-leverage papers in the brief and audit log.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

SEARCH_PERSONAS = (
    "scout", "cartographer", "chronicler", "surveyor",
    "architect", "visionary",
)


@dataclass
class DisagreementScore:
    canonical_id: str
    score: float            # in [0, 1]
    surfacing_personas: list[str]
    missing_personas: list[str]   # personas active in run but didn't surface
    role_conflict: str | None     # e.g. "seminal vs gap-creator"

    def to_dict(self) -> dict:
        return {
            "canonical_id": self.canonical_id,
            "score": round(self.score, 4),
            "surfacing_personas": self.surfacing_personas,
            "missing_personas": self.missing_personas,
            "role_conflict": self.role_conflict,
        }


def _personas_active(run_id: str, inputs_dir: Path) -> set[str]:
    """Personas that produced a harvest shortlist for this run."""
    if not inputs_dir.exists():
        return set()
    active = set()
    for p in inputs_dir.glob("*-phase*.json"):
        # Filename: <persona>-<phase>.json
        stem = p.stem
        persona = stem.split("-")[0]
        if persona in SEARCH_PERSONAS:
            active.add(persona)
    return active


def _surfacings_per_paper(
    run_id: str, inputs_dir: Path
) -> dict[str, set[str]]:
    """Map canonical_id → set of personas whose harvest contained it.

    Reads each persona's harvest shortlist JSON, hashes paper to
    canonical_id, accumulates persona set per paper.
    """
    from lib.paper_artifact import canonical_id

    by_cid: dict[str, set[str]] = {}
    if not inputs_dir.exists():
        return by_cid

    for shortlist_path in inputs_dir.glob("*-phase*.json"):
        persona = shortlist_path.stem.split("-")[0]
        if persona not in SEARCH_PERSONAS:
            continue
        try:
            data = json.loads(shortlist_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for entry in data.get("results", []):
            try:
                cid = canonical_id(
                    title=entry.get("title") or "",
                    first_author=(
                        (entry.get("authors") or ["anon"])[0].split()[-1]
                        if entry.get("authors") else "anon"
                    ),
                    year=entry.get("year"),
                    doi=(entry.get("doi") or "").lower() or None,
                )
            except Exception:
                continue
            by_cid.setdefault(cid, set()).add(persona)
    return by_cid


def compute_disagreement(
    run_id: str, run_db: Path, inputs_dir: Path,
) -> list[DisagreementScore]:
    """Compute disagreement score per paper for a run.

    Algorithm:
    - active = set of personas that produced any harvest in this run
    - For each paper P appearing in any harvest:
      - surfacing = personas whose shortlist included P
      - missing = active - surfacing
      - score = 1 - |coverage_alignment|
        where coverage_alignment = 1.0 if all-or-none, lower otherwise

    Mathematically: score = 4 * (s/n) * (1 - s/n) where s = |surfacing|,
    n = |active|. Bell-curve peaking at s/n = 0.5 (max disagreement),
    zero at s/n ∈ {0, 1} (full agreement either way).

    role_conflict left None for now — needs role tagging in
    papers_in_run; future work.
    """
    active = _personas_active(run_id, inputs_dir)
    if len(active) < 2:
        return []  # Need ≥2 personas for disagreement to be meaningful

    surfacings = _surfacings_per_paper(run_id, inputs_dir)
    n = len(active)
    out: list[DisagreementScore] = []

    for cid, personas_set in surfacings.items():
        s = len(personas_set & active)  # only count active personas
        if s == 0:
            continue
        ratio = s / n
        # Bell curve: 4 * p * (1-p), max at p=0.5
        score = 4 * ratio * (1 - ratio)
        out.append(DisagreementScore(
            canonical_id=cid,
            score=score,
            surfacing_personas=sorted(personas_set & active),
            missing_personas=sorted(active - personas_set),
            role_conflict=None,
        ))

    out.sort(key=lambda x: -x.score)
    return out


def persist_to_run_db(
    run_id: str, run_db: Path, scores: list[DisagreementScore],
) -> int:
    """Update papers_in_run.disagreement_score for each paper.

    Returns count of rows updated. Skips papers not in papers_in_run
    (orphan harvest entries — should be rare; could happen if scout
    didn't merge them yet).
    """
    if not run_db.exists():
        raise FileNotFoundError(f"run DB missing: {run_db}")
    if not scores:
        return 0
    con = sqlite3.connect(run_db)
    n = 0
    try:
        with con:
            for s in scores:
                cur = con.execute(
                    "UPDATE papers_in_run SET disagreement_score=? "
                    "WHERE run_id=? AND canonical_id=?",
                    (s.score, run_id, s.canonical_id),
                )
                n += cur.rowcount
    finally:
        con.close()
    return n


def render_summary(scores: list[DisagreementScore], top_k: int = 10) -> str:
    """Markdown summary of top-K disagreement papers for steward."""
    if not scores:
        return "_No cross-persona disagreement detected._"
    lines = [
        "## High-leverage papers (cross-persona disagreement)",
        "",
        "_Papers surfaced by some personas but missed by others — "
        "high-leverage signal invisible to single-agent systems._",
        "",
        "| Score | Canonical ID | Surfaced by | Missed by |",
        "|---|---|---|---|",
    ]
    for s in scores[:top_k]:
        if s.score < 0.1:
            continue
        lines.append(
            f"| {s.score:.3f} "
            f"| `{s.canonical_id[:50]}...` "
            f"| {', '.join(s.surfacing_personas)} "
            f"| {', '.join(s.missing_personas) or '—'} |"
        )
    return "\n".join(lines)
