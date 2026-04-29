#!/usr/bin/env python3
"""tournament: register a new hypothesis at default Elo 1200.

v0.156 — optional tree positioning. Pass `--tree-root` to stamp the
new row as a tree root (tree_id := hyp_id, depth := 0). Pass
`--parent-hyp-id` to stamp it as a child of an existing hypothesis
(tree_id + depth inherited from parent). Without either flag the
script behaves exactly as before — flat insert with NULL tree
columns. `--branch-index` overrides the auto-computed next sibling
slot. The two tree-positioning flags are mutually exclusive.
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

from lib import idea_tree  # noqa: E402
from lib.cache import run_db_path  # noqa: E402


def _csv(s: str | None) -> list[str]:
    return [t.strip() for t in (s or "").split(",") if t.strip()]


def _parse_json_array(s: str | None, field: str) -> list:
    if s is None or s == "":
        return []
    try:
        out = json.loads(s)
    except json.JSONDecodeError as e:
        raise SystemExit(f"--{field} not valid JSON: {e}")
    if not isinstance(out, list):
        raise SystemExit(f"--{field} must be a JSON array")
    return out


# Accepted agent names. Original 4 retained for back-compat; v0.156
# adds the three Expedition personas that emit hypothesis trees.
_AGENT_CHOICES = [
    "theorist", "thinker", "evolver", "rude",
    "architect", "visionary", "mutator",
    "idea-tree-generator",
]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", required=True)
    p.add_argument("--agent-name", required=True, choices=_AGENT_CHOICES)
    p.add_argument("--hyp-id", required=True)
    p.add_argument("--statement", required=True)
    p.add_argument("--method-sketch", default=None)
    p.add_argument("--predicted-observables", default=None,
                   help="JSON array")
    p.add_argument("--falsifiers", default=None, help="JSON array")
    p.add_argument("--supporting-ids", default=None,
                   help="comma-separated canonical_ids")
    p.add_argument("--gap-ref", default=None)
    p.add_argument("--parent-hyp-id", default=None,
                   help="parent hyp_id; stamps row as tree child")
    p.add_argument("--tree-root", action="store_true",
                   help="stamp row as a new tree root (tree_id := hyp_id)")
    p.add_argument("--branch-index", type=int, default=None,
                   help="override sibling order under parent (0-based)")
    args = p.parse_args()

    if not args.statement.strip():
        raise SystemExit("statement empty")

    if args.tree_root and args.parent_hyp_id:
        raise SystemExit(
            "--tree-root and --parent-hyp-id are mutually exclusive"
        )

    observables = _parse_json_array(args.predicted_observables,
                                     "predicted-observables")
    falsifiers = _parse_json_array(args.falsifiers, "falsifiers")
    supporting = _csv(args.supporting_ids)

    db = run_db_path(args.run_id)
    if not db.exists():
        raise SystemExit(f"no run DB at {db}")

    con = sqlite3.connect(db)
    now = datetime.now(UTC).isoformat()
    try:
        with con:
            con.execute(
                "INSERT INTO hypotheses "
                "(hyp_id, run_id, agent_name, gap_ref, parent_hyp_id, statement, "
                "method_sketch, predicted_observables, falsifiers, supporting_ids, "
                "elo, n_matches, n_wins, n_losses, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1200.0, 0, 0, 0, ?)",
                (args.hyp_id, args.run_id, args.agent_name, args.gap_ref,
                 args.parent_hyp_id, args.statement, args.method_sketch,
                 json.dumps(observables), json.dumps(falsifiers),
                 json.dumps(supporting), now),
            )
    except sqlite3.IntegrityError as e:
        raise SystemExit(f"duplicate hyp_id {args.hyp_id!r}: {e}")
    con.close()

    tree_id: str | None = None
    depth: int | None = None
    branch_index: int | None = None

    # Stamp tree-shape columns if requested.
    if args.tree_root:
        try:
            tree_id = idea_tree.record_root_hypothesis(db, args.hyp_id)
            depth = 0
            if args.branch_index is not None:
                # Honor explicit branch index even on root.
                con = sqlite3.connect(db)
                with con:
                    con.execute(
                        "UPDATE hypotheses SET branch_index=? WHERE hyp_id=?",
                        (args.branch_index, args.hyp_id),
                    )
                con.close()
                branch_index = args.branch_index
            else:
                branch_index = 0
        except Exception as e:
            print(json.dumps({"error": f"record_root_hypothesis failed: {e}"}),
                  file=sys.stderr)
            sys.exit(1)
    elif args.parent_hyp_id:
        try:
            idea_tree.record_child_hypothesis(
                db, args.parent_hyp_id, args.hyp_id,
            )
        except Exception as e:
            print(json.dumps({"error": f"record_child_hypothesis failed: {e}"}),
                  file=sys.stderr)
            sys.exit(1)
        # Pull back stamped values.
        con = sqlite3.connect(db)
        try:
            row = con.execute(
                "SELECT tree_id, depth, branch_index FROM hypotheses "
                "WHERE hyp_id=?",
                (args.hyp_id,),
            ).fetchone()
            if row:
                tree_id, depth, branch_index = row
            if args.branch_index is not None:
                with con:
                    con.execute(
                        "UPDATE hypotheses SET branch_index=? WHERE hyp_id=?",
                        (args.branch_index, args.hyp_id),
                    )
                branch_index = args.branch_index
        finally:
            con.close()

    out = {
        "hyp_id": args.hyp_id, "elo": 1200.0,
        "parent_hyp_id": args.parent_hyp_id,
    }
    if tree_id is not None:
        out["tree_id"] = tree_id
        out["depth"] = depth
        out["branch_index"] = branch_index
    print(json.dumps(out))


if __name__ == "__main__":
    main()
