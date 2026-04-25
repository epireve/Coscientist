#!/usr/bin/env python3
"""deep-research DB helpers: init, record phases, record breaks, query state.

All run state lives in ~/.cache/coscientist/runs/run-<run_id>.db.
Schema is in lib/sqlite_schema.sql.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import run_db_path  # noqa: E402

SCHEMA_PATH = _REPO_ROOT / "lib" / "sqlite_schema.sql"

PHASES_IN_ORDER = [
    "social",
    "grounder",
    "historian",
    "gaper",
    "vision",
    "theorist",
    "rude",
    "synthesizer",
    "thinker",
    "scribe",
]
BREAK_AFTER = {"social": 0, "gaper": 1, "synthesizer": 2}


def _connect(run_id: str) -> sqlite3.Connection:
    db = run_db_path(run_id)
    fresh = not db.exists()
    if fresh:
        # Build base schema first
        con = sqlite3.connect(db)
        con.executescript(SCHEMA_PATH.read_text())
        con.close()
    # v0.14: apply any unapplied migrations before returning the connection
    from lib.migrations import ensure_current
    ensure_current(db)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def cmd_init(args: argparse.Namespace) -> None:
    run_id = secrets.token_hex(4)
    con = _connect(run_id)
    config = (
        json.loads(Path(args.config).read_text()) if args.config else {}
    )
    with con:
        con.execute(
            "INSERT INTO runs (run_id, question, started_at, config_json) VALUES (?, ?, ?, ?)",
            (run_id, args.question, datetime.now(UTC).isoformat(), json.dumps(config)),
        )
        for i, name in enumerate(PHASES_IN_ORDER):
            con.execute(
                "INSERT INTO phases (run_id, name, ordinal) VALUES (?, ?, ?)",
                (run_id, name, i),
            )
    con.close()
    print(run_id)


def cmd_record_phase(args: argparse.Namespace) -> None:
    con = _connect(args.run_id)
    now = datetime.now(UTC).isoformat()
    output = Path(args.output_json).read_text() if args.output_json else None
    with con:
        if args.start:
            con.execute(
                "UPDATE phases SET started_at=? WHERE run_id=? AND name=?",
                (now, args.run_id, args.phase),
            )
        if args.complete:
            con.execute(
                "UPDATE phases SET completed_at=?, output_json=? WHERE run_id=? AND name=?",
                (now, output, args.run_id, args.phase),
            )
        if args.error:
            con.execute(
                "UPDATE phases SET error=? WHERE run_id=? AND name=?",
                (args.error, args.run_id, args.phase),
            )
    con.close()


def cmd_record_break(args: argparse.Namespace) -> None:
    con = _connect(args.run_id)
    now = datetime.now(UTC).isoformat()
    with con:
        if args.prompt:
            con.execute(
                "INSERT INTO breaks (run_id, break_number, prompted_at) VALUES (?, ?, ?)",
                (args.run_id, args.break_number, now),
            )
        if args.resolve:
            con.execute(
                "UPDATE breaks SET resolved_at=?, user_input=? "
                "WHERE run_id=? AND break_number=? AND resolved_at IS NULL",
                (now, args.user_input or "", args.run_id, args.break_number),
            )
    con.close()


def cmd_record_claim(args: argparse.Namespace) -> None:
    con = _connect(args.run_id)
    supporting = json.dumps(args.supporting_ids.split(",")) if args.supporting_ids else None
    with con:
        con.execute(
            "INSERT INTO claims (run_id, canonical_id, agent_name, text, kind, confidence, supporting_ids) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                args.run_id,
                args.canonical_id,
                args.agent_name,
                args.text,
                args.kind,
                args.confidence,
                supporting,
            ),
        )
    con.close()


def cmd_next_phase(args: argparse.Namespace) -> None:
    """Print the name of the next phase to run, or BREAK_<n>, or DONE."""
    con = _connect(args.run_id)
    rows = con.execute(
        "SELECT name, started_at, completed_at FROM phases WHERE run_id=? ORDER BY ordinal",
        (args.run_id,),
    ).fetchall()
    con.close()

    for row in rows:
        if row["completed_at"] is None:
            # If a break is configured after the *previous* phase and unresolved, return it
            prev_idx = PHASES_IN_ORDER.index(row["name"]) - 1
            if prev_idx >= 0:
                prev_name = PHASES_IN_ORDER[prev_idx]
                if prev_name in BREAK_AFTER:
                    bn = BREAK_AFTER[prev_name]
                    con = _connect(args.run_id)
                    unresolved = con.execute(
                        "SELECT 1 FROM breaks WHERE run_id=? AND break_number=? AND resolved_at IS NULL",
                        (args.run_id, bn),
                    ).fetchone()
                    con.close()
                    # If previous is completed but this break hasn't been resolved, signal it
                    prev_row = next(r for r in rows if r["name"] == prev_name)
                    if prev_row["completed_at"] is not None and unresolved:
                        print(f"BREAK_{bn}")
                        return
                    if prev_row["completed_at"] is not None and not unresolved:
                        # Check if break row even exists
                        con = _connect(args.run_id)
                        exists = con.execute(
                            "SELECT 1 FROM breaks WHERE run_id=? AND break_number=?",
                            (args.run_id, bn),
                        ).fetchone()
                        con.close()
                        if not exists:
                            print(f"BREAK_{bn}")
                            return
            print(row["name"])
            return
    print("DONE")


def cmd_resume(args: argparse.Namespace) -> None:
    """Print a summary of current state + next action."""
    con = _connect(args.run_id)
    run = con.execute("SELECT * FROM runs WHERE run_id=?", (args.run_id,)).fetchone()
    if not run:
        con.close()
        raise SystemExit(f"no such run: {args.run_id}")
    phases = con.execute(
        "SELECT name, started_at, completed_at, error FROM phases WHERE run_id=? ORDER BY ordinal",
        (args.run_id,),
    ).fetchall()
    con.close()

    print(json.dumps({
        "run_id": args.run_id,
        "question": run["question"],
        "status": run["status"],
        "phases": [dict(r) for r in phases],
    }, indent=2))


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init"); pi.add_argument("--question", required=True); pi.add_argument("--config", default=None)
    pi.set_defaults(func=cmd_init)

    pp = sub.add_parser("record-phase")
    pp.add_argument("--run-id", required=True); pp.add_argument("--phase", required=True)
    pp.add_argument("--start", action="store_true"); pp.add_argument("--complete", action="store_true")
    pp.add_argument("--output-json", default=None); pp.add_argument("--error", default=None)
    pp.set_defaults(func=cmd_record_phase)

    pb = sub.add_parser("record-break")
    pb.add_argument("--run-id", required=True); pb.add_argument("--break-number", type=int, required=True)
    pb.add_argument("--prompt", action="store_true"); pb.add_argument("--resolve", action="store_true")
    pb.add_argument("--user-input", default=None)
    pb.set_defaults(func=cmd_record_break)

    pc = sub.add_parser("record-claim")
    pc.add_argument("--run-id", required=True); pc.add_argument("--agent-name", required=True)
    pc.add_argument("--text", required=True); pc.add_argument("--kind", default="finding")
    pc.add_argument("--canonical-id", default=None); pc.add_argument("--confidence", type=float, default=None)
    pc.add_argument("--supporting-ids", default="")
    pc.set_defaults(func=cmd_record_claim)

    pn = sub.add_parser("next-phase"); pn.add_argument("--run-id", required=True)
    pn.set_defaults(func=cmd_next_phase)

    pr = sub.add_parser("resume"); pr.add_argument("--run-id", required=True)
    pr.set_defaults(func=cmd_resume)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
