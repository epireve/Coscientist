#!/usr/bin/env python3
"""tournament evolve-loop: orchestration ledger for self-play + evolution.

Out-of-band ledger. Does NOT call sub-agents. Caller drives:
    1. open-round  — start a round, snapshot top-1
    2. (caller runs ranker matches via record_match.py)
    3. (caller runs evolver agent, posts children via record_hypothesis.py
       with --parent-hyp-id set)
    4. close-round — record stats; detect plateau (top-1 unchanged)
    5. status      — JSON snapshot of all rounds + current top
    6. lineage     — markdown tree of parent→child for top-N

Termination is the caller's call. Loop reports plateau_count; caller
decides when to stop. Mirrors v0.36 contract: ledger writes, no LLM.
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
from lib.migrations import ensure_current  # noqa: E402


def _connect(run_id: str) -> sqlite3.Connection:
    db = run_db_path(run_id)
    if not db.exists():
        raise SystemExit(f"no run DB at {db}")
    ensure_current(db)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _top1(con: sqlite3.Connection, run_id: str) -> tuple[str | None, float | None, int]:
    row = con.execute(
        "SELECT hyp_id, elo FROM hypotheses WHERE run_id=? "
        "ORDER BY elo DESC, hyp_id LIMIT 1", (run_id,),
    ).fetchone()
    n = con.execute(
        "SELECT COUNT(*) FROM hypotheses WHERE run_id=?", (run_id,),
    ).fetchone()[0]
    if not row:
        return None, None, n
    return row["hyp_id"], float(row["elo"]), n


def _last_round(con: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    return con.execute(
        "SELECT * FROM evolution_rounds WHERE run_id=? "
        "ORDER BY round_index DESC LIMIT 1", (run_id,),
    ).fetchone()


def cmd_open_round(args: argparse.Namespace) -> None:
    con = _connect(args.run_id)
    try:
        last = _last_round(con, args.run_id)
        if last and last["closed_at"] is None:
            raise SystemExit(
                f"round {last['round_index']} still open; close it first"
            )
        next_idx = (last["round_index"] + 1) if last else 0
        top_id, top_elo, n_hyp = _top1(con, args.run_id)
        if n_hyp == 0:
            raise SystemExit("no hypotheses recorded for this run yet")
        con.execute(
            "INSERT INTO evolution_rounds "
            "(run_id, round_index, top_hyp_id, top_elo, n_hypotheses, "
            "n_matches, n_new_children, plateau_count, started_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (args.run_id, next_idx, top_id, top_elo, n_hyp, 0, 0, 0, _now()),
        )
        con.commit()
        print(json.dumps({
            "run_id": args.run_id,
            "round_index": next_idx,
            "top_hyp_id": top_id,
            "top_elo": top_elo,
            "n_hypotheses": n_hyp,
            "started_at": _now(),
        }, indent=2))
    finally:
        con.close()


def cmd_close_round(args: argparse.Namespace) -> None:
    con = _connect(args.run_id)
    try:
        last = _last_round(con, args.run_id)
        if not last:
            raise SystemExit("no round open")
        if last["closed_at"]:
            raise SystemExit(
                f"round {last['round_index']} already closed at {last['closed_at']}"
            )

        # Match count delta — count tournament_matches rows newer than the
        # round's started_at.
        n_matches = con.execute(
            "SELECT COUNT(*) FROM tournament_matches "
            "WHERE run_id=? AND at >= ?",
            (args.run_id, last["started_at"]),
        ).fetchone()[0]

        # New-children delta — hypotheses created during this round with a
        # parent_hyp_id set (i.e. evolver output, not raw theorist/thinker).
        n_new_children = con.execute(
            "SELECT COUNT(*) FROM hypotheses "
            "WHERE run_id=? AND created_at >= ? AND parent_hyp_id IS NOT NULL",
            (args.run_id, last["started_at"]),
        ).fetchone()[0]

        # Plateau detection — top-1 unchanged from prior CLOSED round?
        # `last` is the currently-open round; its plateau_count is still 0.
        # Walk back one closed round for the chained count.
        prev_closed = con.execute(
            "SELECT plateau_count, top_hyp_id FROM evolution_rounds "
            "WHERE run_id=? AND closed_at IS NOT NULL "
            "ORDER BY round_index DESC LIMIT 1",
            (args.run_id,),
        ).fetchone()
        prev_top = last["top_hyp_id"]
        new_top, new_elo, n_hyp = _top1(con, args.run_id)
        if prev_top and prev_top == new_top:
            base = prev_closed["plateau_count"] if prev_closed else 0
            plateau_count = base + 1
        else:
            plateau_count = 0

        con.execute(
            "UPDATE evolution_rounds SET "
            "n_matches=?, n_new_children=?, plateau_count=?, "
            "top_hyp_id=?, top_elo=?, n_hypotheses=?, closed_at=? "
            "WHERE round_id=?",
            (n_matches, n_new_children, plateau_count,
             new_top, new_elo, n_hyp, _now(), last["round_id"]),
        )
        con.commit()
        print(json.dumps({
            "run_id": args.run_id,
            "round_index": last["round_index"],
            "n_matches": n_matches,
            "n_new_children": n_new_children,
            "top_hyp_id": new_top,
            "top_elo": new_elo,
            "top_changed": prev_top != new_top,
            "plateau_count": plateau_count,
            "should_stop": plateau_count >= args.plateau_threshold,
        }, indent=2))
    finally:
        con.close()


def cmd_status(args: argparse.Namespace) -> None:
    con = _connect(args.run_id)
    try:
        rounds = [dict(r) for r in con.execute(
            "SELECT * FROM evolution_rounds WHERE run_id=? "
            "ORDER BY round_index", (args.run_id,),
        )]
        top_id, top_elo, n_hyp = _top1(con, args.run_id)
        print(json.dumps({
            "run_id": args.run_id,
            "rounds": rounds,
            "current_top_hyp_id": top_id,
            "current_top_elo": top_elo,
            "current_n_hypotheses": n_hyp,
        }, indent=2, default=str))
    finally:
        con.close()


def _children(con: sqlite3.Connection, run_id: str, parent: str) -> list[sqlite3.Row]:
    return list(con.execute(
        "SELECT hyp_id, elo, statement FROM hypotheses "
        "WHERE run_id=? AND parent_hyp_id=? "
        "ORDER BY elo DESC, hyp_id",
        (run_id, parent),
    ).fetchall())


def _render_subtree(con: sqlite3.Connection, run_id: str,
                    hyp_id: str, depth: int, lines: list[str]) -> None:
    row = con.execute(
        "SELECT hyp_id, elo, statement FROM hypotheses "
        "WHERE hyp_id=?", (hyp_id,),
    ).fetchone()
    if not row:
        return
    indent = "  " * depth
    stmt = (row["statement"] or "")[:80].replace("\n", " ")
    lines.append(f"{indent}- `{row['hyp_id']}` (Elo {row['elo']:.0f}) — {stmt}")
    for child in _children(con, run_id, hyp_id):
        _render_subtree(con, run_id, child["hyp_id"], depth + 1, lines)


def cmd_lineage(args: argparse.Namespace) -> None:
    con = _connect(args.run_id)
    try:
        # Find roots: top-K by Elo with no parent
        roots = list(con.execute(
            "SELECT hyp_id FROM hypotheses "
            "WHERE run_id=? AND parent_hyp_id IS NULL "
            "ORDER BY elo DESC LIMIT ?",
            (args.run_id, args.top_roots),
        ).fetchall())
        if not roots:
            # Fallback — top by elo even if parented
            roots = list(con.execute(
                "SELECT hyp_id FROM hypotheses WHERE run_id=? "
                "ORDER BY elo DESC LIMIT ?", (args.run_id, args.top_roots),
            ).fetchall())

        lines = [f"# Evolution lineage — run {args.run_id}", ""]
        for r in roots:
            _render_subtree(con, args.run_id, r["hyp_id"], 0, lines)
            lines.append("")

        # Append rounds table
        rounds = list(con.execute(
            "SELECT round_index, top_hyp_id, top_elo, n_hypotheses, "
            "n_matches, n_new_children, plateau_count "
            "FROM evolution_rounds WHERE run_id=? ORDER BY round_index",
            (args.run_id,),
        ))
        if rounds:
            lines.append("## Rounds")
            lines.append("")
            lines.append("| Round | Top hyp | Top Elo | #hyp | #matches | #children | plateau |")
            lines.append("|---:|---|---:|---:|---:|---:|---:|")
            for r in rounds:
                lines.append(
                    f"| {r['round_index']} | "
                    f"`{r['top_hyp_id'] or '—'}` | "
                    f"{r['top_elo']:.0f} | {r['n_hypotheses']} | "
                    f"{r['n_matches']} | {r['n_new_children']} | "
                    f"{r['plateau_count']} |"
                )
        print("\n".join(lines))
    finally:
        con.close()


def main() -> None:
    p = argparse.ArgumentParser(description="Tournament evolve-loop ledger.")
    sub = p.add_subparsers(dest="cmd", required=True)

    po = sub.add_parser("open-round", help="Start a new evolution round")
    po.add_argument("--run-id", required=True)
    po.set_defaults(func=cmd_open_round)

    pc = sub.add_parser("close-round", help="Close the current round")
    pc.add_argument("--run-id", required=True)
    pc.add_argument("--plateau-threshold", type=int, default=2,
                    help="should_stop=true when plateau_count >= this")
    pc.set_defaults(func=cmd_close_round)

    ps = sub.add_parser("status", help="JSON of all rounds + current top")
    ps.add_argument("--run-id", required=True)
    ps.set_defaults(func=cmd_status)

    pl = sub.add_parser("lineage", help="Markdown lineage tree of top roots")
    pl.add_argument("--run-id", required=True)
    pl.add_argument("--top-roots", type=int, default=3)
    pl.set_defaults(func=cmd_lineage)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
