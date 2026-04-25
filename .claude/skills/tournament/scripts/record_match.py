#!/usr/bin/env python3
"""tournament: record a pairwise match outcome and update Elo for both hypotheses.

Standard Elo with K=32. Winner can be either hyp_id or 'draw'.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import run_db_path  # noqa: E402

K_FACTOR = 32.0  # default for new players (n_matches < 5)


def expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def k_factor(n_matches: int) -> float:
    """v0.12.1: per-player K decays with experience.

    Standard chess practice: cold-start K=32 for volatility, drops to 16
    once a hypothesis has played a few matches, then to 8 for established
    ones. Asymmetric K is the cost; the trade is fewer wild Elo swings.
    """
    if n_matches < 5:
        return 32.0
    if n_matches < 15:
        return 16.0
    return 8.0


def update_elo(rating_a: float, rating_b: float, score_a: float,
               k_a: float = K_FACTOR, k_b: float | None = None) -> tuple[float, float]:
    """Returns (new_rating_a, new_rating_b). Each player has its own K."""
    if k_b is None:
        k_b = k_a
    e_a = expected_score(rating_a, rating_b)
    e_b = 1.0 - e_a
    new_a = rating_a + k_a * (score_a - e_a)
    new_b = rating_b + k_b * ((1.0 - score_a) - e_b)
    return (new_a, new_b)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", required=True)
    p.add_argument("--hyp-a", required=True)
    p.add_argument("--hyp-b", required=True)
    p.add_argument("--winner", required=True,
                   help="hyp_id of winner, or 'draw'")
    p.add_argument("--judge-reasoning", default=None)
    args = p.parse_args()

    if args.hyp_a == args.hyp_b:
        raise SystemExit("hyp-a and hyp-b must differ")
    if args.winner not in (args.hyp_a, args.hyp_b, "draw"):
        raise SystemExit(
            f"--winner must be {args.hyp_a!r}, {args.hyp_b!r}, or 'draw'"
        )

    db = run_db_path(args.run_id)
    if not db.exists():
        raise SystemExit(f"no run DB at {db}")

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    rows = {
        r["hyp_id"]: r
        for r in con.execute(
            "SELECT hyp_id, elo, n_matches, n_wins, n_losses FROM hypotheses "
            "WHERE hyp_id IN (?, ?)", (args.hyp_a, args.hyp_b),
        )
    }
    missing = {args.hyp_a, args.hyp_b} - set(rows.keys())
    if missing:
        con.close()
        raise SystemExit(f"unknown hypothesis IDs: {sorted(missing)}")

    elo_a = rows[args.hyp_a]["elo"]
    elo_b = rows[args.hyp_b]["elo"]
    if args.winner == args.hyp_a:
        score_a = 1.0
    elif args.winner == args.hyp_b:
        score_a = 0.0
    else:
        score_a = 0.5

    k_a = k_factor(rows[args.hyp_a]["n_matches"])
    k_b = k_factor(rows[args.hyp_b]["n_matches"])
    new_a, new_b = update_elo(elo_a, elo_b, score_a, k_a=k_a, k_b=k_b)
    now = datetime.now(UTC).isoformat()

    with con:
        con.execute(
            "UPDATE hypotheses SET elo=?, n_matches=n_matches+1, "
            "n_wins=n_wins+?, n_losses=n_losses+? WHERE hyp_id=?",
            (new_a, 1 if score_a == 1.0 else 0,
             1 if score_a == 0.0 else 0, args.hyp_a),
        )
        con.execute(
            "UPDATE hypotheses SET elo=?, n_matches=n_matches+1, "
            "n_wins=n_wins+?, n_losses=n_losses+? WHERE hyp_id=?",
            (new_b, 1 if score_a == 0.0 else 0,
             1 if score_a == 1.0 else 0, args.hyp_b),
        )
        con.execute(
            "INSERT INTO tournament_matches "
            "(run_id, hyp_a, hyp_b, winner, judge_reasoning, at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (args.run_id, args.hyp_a, args.hyp_b,
             args.winner, args.judge_reasoning, now),
        )
    con.close()

    print(json.dumps({
        "hyp_a": args.hyp_a, "elo_a": round(new_a, 2),
        "hyp_b": args.hyp_b, "elo_b": round(new_b, 2),
        "winner": args.winner,
        "delta_a": round(new_a - elo_a, 2),
        "delta_b": round(new_b - elo_b, 2),
    }))


if __name__ == "__main__":
    main()
