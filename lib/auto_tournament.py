"""v0.203 — auto-tournament hook for inquisitor → weaver transition.

Closes the architectural gap from dogfood run 86926630: architect
produces a hypothesis tree, inquisitor attacks them, but ranker
never dispatches, so `tournament_matches` stays empty and the
brief's hypothesis-cards section degrades to v0.199 fallback.

Design: don't add a new phase row to PHASES_IN_ORDER (back-compat
hazard). Instead, when `db.py record-phase --phase inquisitor
--complete --auto-tournament` runs (or env var
`COSCIENTIST_AUTO_TOURNAMENT=1`), this module sweeps every tree in
the run, dispatches `tree_pairs` per tree, runs each pair through
a deterministic heuristic judge, records matches via direct Elo
update + `tournament_matches` insert (mirroring
`tournament/scripts/record_match.py`), and finishes with one pass
of `prune_low_elo_subtrees` per tree.

This is a placeholder judge — true sub-agent ranking would need
ranker dispatch which we don't have here. The point is to populate
`tournament_matches` so the brief renders properly.

Pure stdlib. WAL via `lib.cache.connect_wal`. All errors swallowed
locally and surfaced in the return dict — never raised.
"""

from __future__ import annotations

import os
import random
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from lib.cache import connect_wal
from lib.tree_ranker import prune_low_elo_subtrees, tree_pairs

DEFAULT_ELO = 1200.0
K_FACTOR_NEW = 32.0
K_FACTOR_MID = 16.0
K_FACTOR_OLD = 8.0


def should_auto_tournament(run_db: Path | str) -> bool:
    """Return True iff:
      - env var COSCIENTIST_AUTO_TOURNAMENT=1, AND
      - run DB has >=2 hypotheses with non-NULL tree_id (i.e. real trees)
    """
    if os.environ.get("COSCIENTIST_AUTO_TOURNAMENT") != "1":
        return False
    return _has_tree(run_db)


def _has_tree(run_db: Path | str) -> bool:
    db = Path(run_db)
    if not db.exists():
        return False
    try:
        con = connect_wal(db)
    except Exception:
        return False
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM hypotheses WHERE tree_id IS NOT NULL"
        ).fetchone()[0]
    except sqlite3.Error:
        n = 0
    finally:
        con.close()
    return n >= 2


def _k_for(n_matches: int) -> float:
    if n_matches < 5:
        return K_FACTOR_NEW
    if n_matches < 15:
        return K_FACTOR_MID
    return K_FACTOR_OLD


def _expected(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def _falsifier_len(row: dict) -> int:
    """Length of the falsifiers JSON blob — heuristic for
    rigour. Longer = more falsifiable claim. Treats NULL as 0."""
    f = row.get("falsifiers")
    if not f:
        return 0
    return len(str(f))


def _supporting_count(row: dict) -> int:
    """Count entries in supporting_ids JSON array. NULL → 0."""
    s = row.get("supporting_ids")
    if not s:
        return 0
    # cheap parse: it's stored as JSON-encoded list
    import json
    try:
        v = json.loads(s)
        if isinstance(v, list):
            return len(v)
    except Exception:
        pass
    return 0


def _judge_pair(hyp_a: dict, hyp_b: dict, seed: int) -> str:
    """Deterministic heuristic judge.

    Tie-break order:
      1. Higher current Elo wins.
      2. Longer falsifiers field wins (more rigour).
      3. More supporting_ids wins.
      4. Alphabetical hyp_id (lower wins) — guaranteed deterministic.

    Returns the winning hyp_id. Never returns 'draw' — pure ranking.
    Seed currently unused (deterministic chain) but accepted for
    future RNG-based tiebreaks; kept in the API so callers can vary.
    """
    a_id = hyp_a["hyp_id"]
    b_id = hyp_b["hyp_id"]
    a_elo = float(hyp_a.get("elo") or DEFAULT_ELO)
    b_elo = float(hyp_b.get("elo") or DEFAULT_ELO)
    if a_elo != b_elo:
        return a_id if a_elo > b_elo else b_id
    a_fl = _falsifier_len(hyp_a)
    b_fl = _falsifier_len(hyp_b)
    if a_fl != b_fl:
        return a_id if a_fl > b_fl else b_id
    a_sc = _supporting_count(hyp_a)
    b_sc = _supporting_count(hyp_b)
    if a_sc != b_sc:
        return a_id if a_sc > b_sc else b_id
    # Final deterministic fallback — alphabetical hyp_id (lower wins).
    # Note: seed reserved for future use; kept in the signature so
    # the contract stays stable.
    _ = seed
    return a_id if a_id < b_id else b_id


def _record_match(
    con: sqlite3.Connection,
    run_id: str,
    hyp_a: dict,
    hyp_b: dict,
    winner: str,
    judge_reasoning: str,
) -> None:
    """Update Elo for both hypotheses and insert one tournament_matches
    row. Mirrors the math in tournament/scripts/record_match.py."""
    a_id = hyp_a["hyp_id"]
    b_id = hyp_b["hyp_id"]
    elo_a = float(hyp_a.get("elo") or DEFAULT_ELO)
    elo_b = float(hyp_b.get("elo") or DEFAULT_ELO)
    n_a = int(hyp_a.get("n_matches") or 0)
    n_b = int(hyp_b.get("n_matches") or 0)
    score_a = 1.0 if winner == a_id else 0.0
    e_a = _expected(elo_a, elo_b)
    e_b = 1.0 - e_a
    k_a = _k_for(n_a)
    k_b = _k_for(n_b)
    new_a = elo_a + k_a * (score_a - e_a)
    new_b = elo_b + k_b * ((1.0 - score_a) - e_b)
    now = datetime.now(UTC).isoformat()
    con.execute(
        "UPDATE hypotheses SET elo=?, n_matches=n_matches+1, "
        "n_wins=n_wins+?, n_losses=n_losses+? WHERE hyp_id=?",
        (new_a, 1 if score_a == 1.0 else 0,
         1 if score_a == 0.0 else 0, a_id),
    )
    con.execute(
        "UPDATE hypotheses SET elo=?, n_matches=n_matches+1, "
        "n_wins=n_wins+?, n_losses=n_losses+? WHERE hyp_id=?",
        (new_b, 1 if score_a == 0.0 else 0,
         1 if score_a == 1.0 else 0, b_id),
    )
    con.execute(
        "INSERT INTO tournament_matches "
        "(run_id, hyp_a, hyp_b, winner, judge_reasoning, at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, a_id, b_id, winner, judge_reasoning, now),
    )
    # Mutate the local dicts so subsequent matches in the same sweep
    # see updated Elo + n_matches.
    hyp_a["elo"] = new_a
    hyp_b["elo"] = new_b
    hyp_a["n_matches"] = n_a + 1
    hyp_b["n_matches"] = n_b + 1


def run_auto_tournament(
    run_db: Path | str,
    *,
    strategy: str = "round-robin",
    seed: int = 42,
    prune_threshold: float = 1100.0,
    prune_min_matches: int = 3,
) -> dict:
    """Sweep every tree in the run, dispatch tree_pairs, judge each
    pair via _judge_pair, persist matches, then prune low-Elo
    subtrees once per tree.

    Returns
    -------
    {
      "matches_recorded": int,
      "trees_processed": int,
      "pruned": list[str],          # all pruned root hyp_ids across trees
      "errors": list[str],          # any per-tree exceptions, swallowed
    }
    """
    db = Path(run_db)
    if not db.exists():
        return {"matches_recorded": 0, "trees_processed": 0,
                "pruned": [], "errors": [f"run_db {db} missing"]}

    rng = random.Random(seed)  # noqa: F841 — reserved for future use

    # Discover run_id + unique tree_ids.
    con = connect_wal(db)
    try:
        run_row = con.execute(
            "SELECT run_id FROM runs LIMIT 1"
        ).fetchone()
        run_id = run_row[0] if run_row else None
        tree_rows = con.execute(
            "SELECT DISTINCT tree_id FROM hypotheses "
            "WHERE tree_id IS NOT NULL ORDER BY tree_id"
        ).fetchall()
    finally:
        con.close()

    if run_id is None or not tree_rows:
        return {"matches_recorded": 0, "trees_processed": 0,
                "pruned": [], "errors": []}

    matches_recorded = 0
    trees_processed = 0
    pruned_all: list[str] = []
    errors: list[str] = []

    for (tree_id,) in tree_rows:
        try:
            pairs = tree_pairs(db, tree_id, strategy=strategy)
        except Exception as e:
            errors.append(f"tree_pairs({tree_id}): {e}")
            continue
        if not pairs:
            trees_processed += 1
            continue

        # Pull hypothesis rows for this tree once; mutate in place
        # as matches accumulate.
        con = connect_wal(db)
        try:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT hyp_id, elo, n_matches, falsifiers, "
                "supporting_ids FROM hypotheses WHERE tree_id=?",
                (tree_id,),
            ).fetchall()
            by_id: dict[str, dict] = {
                r["hyp_id"]: dict(r) for r in rows
            }
        finally:
            con.close()

        # Run all pair matches in a single transaction per tree.
        con = connect_wal(db)
        try:
            with con:
                for a_id, b_id in pairs:
                    if a_id not in by_id or b_id not in by_id:
                        continue
                    hyp_a = by_id[a_id]
                    hyp_b = by_id[b_id]
                    winner = _judge_pair(hyp_a, hyp_b, seed)
                    _record_match(
                        con, run_id, hyp_a, hyp_b, winner,
                        judge_reasoning="auto-tournament v0.203 "
                        "heuristic judge (Elo > falsifier-len > "
                        "supporting-count > alpha hyp_id)",
                    )
                    matches_recorded += 1
        except Exception as e:
            errors.append(f"matches({tree_id}): {e}")
        finally:
            con.close()

        # Prune once per tree after all matches land.
        try:
            pruned = prune_low_elo_subtrees(
                db, tree_id,
                threshold=prune_threshold,
                min_matches=prune_min_matches,
            )
            pruned_all.extend(pruned)
        except Exception as e:
            errors.append(f"prune({tree_id}): {e}")

        trees_processed += 1

    return {
        "matches_recorded": matches_recorded,
        "trees_processed": trees_processed,
        "pruned": pruned_all,
        "errors": errors,
    }
