"""Persistence helpers for skill outputs (v0.57).

Each skill that produces structured output should call one of these
to persist a row + emit a db-notify line. Keeps record-keeping
consistent across debate, gap-analyzer, contribution-mapper,
venue-match, mode-selector, and future skills.

Each helper:
  1. Connects to a DB (auto-create + migration)
  2. Inserts the row(s)
  3. Calls db_notify.record_write
  4. Returns the notification dict so caller can stderr-emit it

Pattern: connection lifecycle is per-call (open + close). Cheap on
SQLite. Avoids passing connections through the call stack.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

# resolve repo root for schema lookup
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[1]
_SCHEMA_SQL = _REPO_ROOT / "lib" / "sqlite_schema.sql"


def _ensure_db(db_path: Path) -> sqlite3.Connection:
    """Open or create DB; ensure schema + migrations applied.

    v0.66: returns a WAL-mode connection (lib.cache.connect_wal) so
    parallel skill writers (Wide Research orchestrator-worker) don't
    deadlock on SQLITE_BUSY. WAL is a per-DB on-disk flag; pre-existing
    rollback-journal DBs upgrade transparently on first connect_wal
    open.
    """
    from lib.cache import connect_wal
    fresh = not db_path.exists()
    if fresh:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(db_path)
        con.executescript(_SCHEMA_SQL.read_text())
        con.close()
    from lib.migrations import ensure_current
    ensure_current(db_path)
    return connect_wal(db_path)


def _emit(note: dict) -> None:
    """Print db-notify line to stderr."""
    from lib.db_notify import format_notification
    sys.stderr.write(format_notification(note) + "\n")


# ---------- Debate ----------

def persist_debate(
    db_path: Path,
    *,
    debate_id: str,
    run_id: str | None,
    topic: str,
    target_id: str,
    target_claim: str,
    verdict: str,
    delta: float,
    kill_criterion: str,
    pro_mean: float,
    con_mean: float,
    transcript_path: str,
) -> dict:
    from lib.db_notify import record_write
    con = _ensure_db(db_path)
    try:
        now = datetime.now(UTC).isoformat()
        with con:
            con.execute(
                "INSERT OR REPLACE INTO debates "
                "(debate_id, run_id, topic, target_id, target_claim, "
                "verdict, delta, kill_criterion, pro_mean, con_mean, "
                "transcript_path, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (debate_id, run_id, topic, target_id, target_claim,
                 verdict, delta, kill_criterion, pro_mean, con_mean,
                 transcript_path, now),
            )
        note = record_write(
            con, "debates", 1, "debate",
            run_id=debate_id,
            detail=f"topic={topic}, verdict={verdict}",
        )
        _emit(note)
        return note
    finally:
        con.close()


# ---------- Gap analyzer ----------

def persist_gap_analyses(
    db_path: Path,
    *,
    run_id: str | None,
    analyses: list,  # list of GapAnalysis objects (or dicts with same fields)
) -> dict:
    from lib.db_notify import record_write
    con = _ensure_db(db_path)
    try:
        now = datetime.now(UTC).isoformat()
        n = 0
        with con:
            for a in analyses:
                d = a.to_dict() if hasattr(a, "to_dict") else dict(a)
                con.execute(
                    "INSERT OR REPLACE INTO gap_analyses "
                    "(run_id, gap_id, kind, real_or_artifact, "
                    "addressable, publishability_tier, "
                    "expected_difficulty, "
                    "adjacent_field_analogues_json, reasoning, at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (run_id, d["gap_id"], d["kind"],
                     d["real_or_artifact"],
                     1 if d.get("addressable") else 0,
                     d["publishability_tier"],
                     d["expected_difficulty"],
                     json.dumps(d.get("adjacent_field_analogues", [])),
                     d.get("reasoning", ""), now),
                )
                n += 1
        note = record_write(
            con, "gap_analyses", n, "gap-analyzer",
            run_id=run_id,
        )
        _emit(note)
        return note
    finally:
        con.close()


# ---------- Venue match ----------

def persist_venue_recommendations(
    db_path: Path,
    *,
    manuscript_id: str | None,
    run_id: str | None,
    recommendations: list,
) -> dict:
    from lib.db_notify import record_write
    con = _ensure_db(db_path)
    try:
        now = datetime.now(UTC).isoformat()
        n = 0
        with con:
            for rank, r in enumerate(recommendations, 1):
                d = r.to_dict() if hasattr(r, "to_dict") else dict(r)
                con.execute(
                    "INSERT INTO venue_recommendations "
                    "(manuscript_id, run_id, venue_name, venue_type, "
                    "venue_tier, score, rank, reasons_for_json, "
                    "reasons_against_json, at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (manuscript_id, run_id, d["venue"], d["type"],
                     d["tier"], d["score"], rank,
                     json.dumps(d.get("reasons_for", [])),
                     json.dumps(d.get("reasons_against", [])), now),
                )
                n += 1
        note = record_write(
            con, "venue_recommendations", n, "venue-match",
            run_id=manuscript_id or run_id,
        )
        _emit(note)
        return note
    finally:
        con.close()


# ---------- Contribution mapper ----------

def persist_contribution_landscape(
    db_path: Path,
    *,
    manuscript_id: str | None,
    run_id: str | None,
    contributions: list,
    anchors: list,
) -> dict:
    """Persist one row per contribution × closest-anchor pair."""
    from lib.contribution_mapper import closest_anchor
    from lib.db_notify import record_write
    con = _ensure_db(db_path)
    try:
        now = datetime.now(UTC).isoformat()
        n = 0
        with con:
            for c in contributions:
                a, (dm, dd, df) = closest_anchor(c, anchors)
                con.execute(
                    "INSERT INTO contribution_landscapes "
                    "(manuscript_id, run_id, contribution_label, "
                    "method_distance, domain_distance, finding_distance, "
                    "closest_anchor_canonical_id, "
                    "method_tokens_json, domain_tokens_json, "
                    "finding_tokens_json, at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (manuscript_id, run_id, c.label, dm, dd, df,
                     a.canonical_id if a else None,
                     json.dumps(sorted(c.method)),
                     json.dumps(sorted(c.domain)),
                     json.dumps(sorted(c.finding)), now),
                )
                n += 1
        note = record_write(
            con, "contribution_landscapes", n, "contribution-mapper",
            run_id=manuscript_id or run_id,
        )
        _emit(note)
        return note
    finally:
        con.close()


# ---------- Mode selector ----------

def persist_mode_selection(
    db_path: Path,
    *,
    user_query: str,
    n_items: int,
    selected_mode: str,
    confidence: float,
    explicit_override: bool,
    reasoning: str,
    warnings: list,
) -> dict:
    from lib.db_notify import record_write
    con = _ensure_db(db_path)
    try:
        now = datetime.now(UTC).isoformat()
        with con:
            con.execute(
                "INSERT INTO mode_selections "
                "(user_query, n_items, selected_mode, confidence, "
                "explicit_override, reasoning, warnings_json, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_query, n_items, selected_mode, confidence,
                 1 if explicit_override else 0,
                 reasoning, json.dumps(warnings), now),
            )
        note = record_write(
            con, "mode_selections", 1, "mode-selector",
            detail=f"mode={selected_mode}, items={n_items}",
        )
        _emit(note)
        return note
    finally:
        con.close()


# ---------- Citation resolver (v0.63) ----------

def persist_citation_resolution(
    db_path: Path,
    *,
    run_id: str | None = None,
    project_id: str | None = None,
    input_text: str,
    partial: dict,
    matched: bool,
    score: float,
    threshold: float,
    canonical_id: str | None = None,
    doi: str | None = None,
    title: str | None = None,
    year: int | None = None,
    candidate: dict | None = None,
) -> dict:
    """Persist a resolve-citation outcome to citation_resolutions.

    Always writes — both matched and below-threshold attempts are
    recorded so the user can later audit "what couldn't I resolve".
    """
    from lib.db_notify import record_write
    con = _ensure_db(db_path)
    try:
        now = datetime.now(UTC).isoformat()
        with con:
            con.execute(
                "INSERT INTO citation_resolutions "
                "(run_id, project_id, input_text, partial_json, matched, "
                "score, threshold, canonical_id, doi, title, year, "
                "candidate_json, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, project_id, input_text,
                 json.dumps(partial, sort_keys=True),
                 1 if matched else 0,
                 float(score), float(threshold),
                 canonical_id, doi, title, year,
                 json.dumps(candidate, sort_keys=True) if candidate else None,
                 now),
            )
        note = record_write(
            con, "citation_resolutions", 1, "resolve-citation",
            run_id=run_id,
            detail=("matched" if matched else "below-threshold")
                   + f" score={score:.3f}",
        )
        _emit(note)
        return note
    finally:
        con.close()
