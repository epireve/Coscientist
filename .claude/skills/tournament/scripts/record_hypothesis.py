#!/usr/bin/env python3
"""tournament: register a new hypothesis at default Elo 1200."""

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


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", required=True)
    p.add_argument("--agent-name", required=True,
                   choices=["theorist", "thinker", "evolver", "rude"])
    p.add_argument("--hyp-id", required=True)
    p.add_argument("--statement", required=True)
    p.add_argument("--method-sketch", default=None)
    p.add_argument("--predicted-observables", default=None,
                   help="JSON array")
    p.add_argument("--falsifiers", default=None, help="JSON array")
    p.add_argument("--supporting-ids", default=None,
                   help="comma-separated canonical_ids")
    p.add_argument("--gap-ref", default=None)
    p.add_argument("--parent-hyp-id", default=None)
    args = p.parse_args()

    if not args.statement.strip():
        raise SystemExit("statement empty")

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

    print(json.dumps({
        "hyp_id": args.hyp_id, "elo": 1200.0,
        "parent_hyp_id": args.parent_hyp_id,
    }))


if __name__ == "__main__":
    main()
