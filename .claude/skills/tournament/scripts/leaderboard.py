#!/usr/bin/env python3
"""tournament: top-N hypotheses by Elo with stats and parent lineage."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import run_db_path  # noqa: E402


def _ancestor_chain(con: sqlite3.Connection, hyp_id: str) -> list[str]:
    """Walk parent_hyp_id back to the root. Returns [root, ..., direct parent]."""
    chain: list[str] = []
    seen: set[str] = set()
    current = hyp_id
    while current:
        row = con.execute(
            "SELECT parent_hyp_id FROM hypotheses WHERE hyp_id=?", (current,),
        ).fetchone()
        if not row or not row[0]:
            break
        if row[0] in seen:
            break  # defensive against pathological cycles
        chain.append(row[0])
        seen.add(row[0])
        current = row[0]
    return list(reversed(chain))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", required=True)
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--format", choices=["json", "md"], default="json")
    args = p.parse_args()

    db = run_db_path(args.run_id)
    if not db.exists():
        raise SystemExit(f"no run DB at {db}")

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT hyp_id, agent_name, statement, elo, n_matches, n_wins, "
        "n_losses, parent_hyp_id FROM hypotheses WHERE run_id=? "
        "ORDER BY elo DESC, hyp_id LIMIT ?", (args.run_id, args.top),
    )]
    for r in rows:
        r["ancestors"] = _ancestor_chain(con, r["hyp_id"])
    con.close()

    if args.format == "md":
        lines = [
            f"# Tournament leaderboard — run {args.run_id}",
            "",
            "| Rank | hyp_id | Elo | W-L-M | Agent | Statement |",
            "|---|---|---:|---|---|---|",
        ]
        for i, r in enumerate(rows, start=1):
            ancestry = " ← ".join(r["ancestors"]) if r["ancestors"] else ""
            statement = r["statement"][:80].replace("|", "\\|")
            label = r["hyp_id"] + (f" ({ancestry})" if ancestry else "")
            lines.append(
                f"| {i} | {label} | {r['elo']:.0f} | "
                f"{r['n_wins']}-{r['n_losses']}-{r['n_matches']} | "
                f"{r['agent_name']} | {statement} |"
            )
        print("\n".join(lines))
    else:
        print(json.dumps({"run_id": args.run_id, "top": rows},
                         indent=2, default=str))


if __name__ == "__main__":
    main()
