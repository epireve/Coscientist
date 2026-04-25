#!/usr/bin/env python3
"""tournament: emit pairwise pairings the ranker sub-agent should judge.

Strategies:
- round-robin: every pair (n choose 2)
- top-k-vs-rest: top-K by Elo paired against everyone else (cheaper for large N)
- top-k-internal: pairs within the top-K (refines the top of the leaderboard)
"""

from __future__ import annotations

import argparse
import itertools
import json
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import run_db_path  # noqa: E402

VALID_STRATEGIES = {"round-robin", "top-k-vs-rest", "top-k-internal"}


def _hypotheses(run_id: str) -> list[dict]:
    db = run_db_path(run_id)
    if not db.exists():
        raise SystemExit(f"no run DB at {db}")
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT hyp_id, elo, n_matches FROM hypotheses WHERE run_id=? "
        "ORDER BY elo DESC, hyp_id", (run_id,),
    )]
    con.close()
    return rows


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", required=True)
    p.add_argument("--strategy", choices=sorted(VALID_STRATEGIES),
                   default="top-k-vs-rest")
    p.add_argument("--top-k", type=int, default=3)
    p.add_argument("--exclude-played", action="store_true",
                   help="Skip pairs that have already been judged in this run")
    args = p.parse_args()

    hyps = _hypotheses(args.run_id)
    if len(hyps) < 2:
        raise SystemExit(f"need at least 2 hypotheses, found {len(hyps)}")

    ids = [h["hyp_id"] for h in hyps]
    top_k = ids[:args.top_k]
    rest = ids[args.top_k:]

    pairs: list[tuple[str, str]] = []
    if args.strategy == "round-robin":
        pairs = list(itertools.combinations(ids, 2))
    elif args.strategy == "top-k-vs-rest":
        pairs = [(a, b) for a in top_k for b in rest if a != b]
    elif args.strategy == "top-k-internal":
        pairs = list(itertools.combinations(top_k, 2))

    if args.exclude_played:
        db = run_db_path(args.run_id)
        con = sqlite3.connect(db)
        played = {
            tuple(sorted([r[0], r[1]]))
            for r in con.execute(
                "SELECT hyp_a, hyp_b FROM tournament_matches WHERE run_id=?",
                (args.run_id,),
            )
        }
        con.close()
        pairs = [
            (a, b) for a, b in pairs
            if tuple(sorted([a, b])) not in played
        ]

    print(json.dumps({
        "strategy": args.strategy,
        "n_hypotheses": len(hyps),
        "n_pairs": len(pairs),
        "pairs": [{"hyp_a": a, "hyp_b": b} for a, b in pairs],
    }, indent=2))


if __name__ == "__main__":
    main()
