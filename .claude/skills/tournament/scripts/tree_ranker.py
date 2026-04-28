#!/usr/bin/env python3
"""tournament: tree-aware ranker (v0.155).

Subcommands:
  pairs        — emit pairings within a tree (siblings|round-robin|depth-bands)
  prune        — prune low-Elo subtrees once min-matches reached
  leaderboard  — Elo-sorted leaderboard scoped to one tree

All output is JSON on stdout. Errors come back as JSON dicts with
an "error" key, never raised tracebacks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib import tree_ranker  # noqa: E402


def _cmd_pairs(args: argparse.Namespace) -> int:
    db = Path(args.run_db)
    if not db.exists():
        print(json.dumps({"error": f"no run DB at {db}"}))
        return 1
    pairs = tree_ranker.tree_pairs(db, args.tree_id, strategy=args.strategy)
    print(json.dumps({
        "tree_id": args.tree_id,
        "strategy": args.strategy,
        "n_pairs": len(pairs),
        "pairs": [{"hyp_a": a, "hyp_b": b} for a, b in pairs],
    }, indent=2))
    return 0


def _cmd_prune(args: argparse.Namespace) -> int:
    db = Path(args.run_db)
    if not db.exists():
        print(json.dumps({"error": f"no run DB at {db}"}))
        return 1
    pruned = tree_ranker.prune_low_elo_subtrees(
        db, args.tree_id,
        threshold=args.threshold, min_matches=args.min_matches,
    )
    print(json.dumps({
        "tree_id": args.tree_id,
        "threshold": args.threshold,
        "min_matches": args.min_matches,
        "n_pruned": len(pruned),
        "pruned": pruned,
    }, indent=2))
    return 0


def _cmd_leaderboard(args: argparse.Namespace) -> int:
    db = Path(args.run_db)
    if not db.exists():
        print(json.dumps({"error": f"no run DB at {db}"}))
        return 1
    rows = tree_ranker.tree_leaderboard(db, args.tree_id)
    print(json.dumps({
        "tree_id": args.tree_id,
        "n": len(rows),
        "leaderboard": rows,
    }, indent=2, default=str))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="tree_ranker")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("pairs", help="emit tree-scoped pairings")
    sp.add_argument("--run-db", required=True)
    sp.add_argument("--tree-id", required=True)
    sp.add_argument("--strategy",
                    choices=list(tree_ranker.VALID_STRATEGIES),
                    default="siblings")
    sp.set_defaults(func=_cmd_pairs)

    sp = sub.add_parser("prune", help="prune low-Elo subtrees")
    sp.add_argument("--run-db", required=True)
    sp.add_argument("--tree-id", required=True)
    sp.add_argument("--threshold", type=float, default=1100.0)
    sp.add_argument("--min-matches", type=int, default=3)
    sp.set_defaults(func=_cmd_prune)

    sp = sub.add_parser("leaderboard", help="tree-scoped leaderboard")
    sp.add_argument("--run-db", required=True)
    sp.add_argument("--tree-id", required=True)
    sp.set_defaults(func=_cmd_leaderboard)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
