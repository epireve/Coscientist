#!/usr/bin/env python3
"""Overnight mode helpers for deep-research runs.

Subcommands
-----------
queue-break  --run-id <rid> --break-number <0|1|2> --prompt "..."
    Record the break as auto-resolved with an overnight placeholder, so the
    pipeline can continue without blocking on user input.

digest       --run-id <rid>
    Generate ~/.cache/coscientist/runs/run-<rid>/digest.md summarising all
    queued breaks and final outputs. Idempotent (overwrites).

status       --run-id <rid>
    Print whether the run is overnight mode, which breaks were queued vs
    user-resolved, and whether the digest has been generated.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import run_db_path, runs_dir  # noqa: E402

# The standard placeholder inserted when a break is auto-resolved overnight.
OVERNIGHT_PLACEHOLDER = (
    "[overnight: proceeding with default parameters — review digest to redirect]"
)

BREAK_PROMPTS = {
    0: (
        "Break 0 — source pool review: the Social agent has completed its "
        "literature sweep. Review the discovered papers and confirm the source "
        "pool is adequate, or redirect with additional search terms / excluded venues."
    ),
    1: (
        "Break 1 — foundation review: Grounder, Historian, and Gaper have "
        "completed. Validate the foundational claims and upload any Phase 2 "
        "instructions (e.g. theoretical framings to emphasise or ignore)."
    ),
    2: (
        "Break 2 — coherence review: Vision, Theorist, Rude, and Synthesizer "
        "have completed. Approve the overall coherence of the synthesis and "
        "specify the final artifact format (brief length, map sections, etc.)."
    ),
}


def _connect(run_id: str) -> sqlite3.Connection:
    db = run_db_path(run_id)
    if not db.exists():
        raise SystemExit(f"no such run: {run_id}")
    from lib.migrations import ensure_current
    ensure_current(db)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def _run_dir(run_id: str) -> Path:
    d = runs_dir() / f"run-{run_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Subcommand: queue-break
# ---------------------------------------------------------------------------

def cmd_queue_break(args: argparse.Namespace) -> None:
    bn = args.break_number
    if bn not in (0, 1, 2):
        raise SystemExit(f"--break-number must be 0, 1, or 2; got {bn}")

    prompt_text = args.prompt if args.prompt else BREAK_PROMPTS.get(bn, "")
    con = _connect(args.run_id)
    now = datetime.now(UTC).isoformat()

    # Check if this break was already resolved (idempotency guard).
    existing = con.execute(
        "SELECT break_id, resolved_at FROM breaks "
        "WHERE run_id=? AND break_number=?",
        (args.run_id, bn),
    ).fetchone()

    if existing and existing["resolved_at"] is not None:
        con.close()
        raise SystemExit(
            f"break {bn} for run {args.run_id} is already resolved — "
            "cannot queue-break a resolved break"
        )

    with con:
        if existing is None:
            # Insert the break row (prompted_at) and resolve it immediately.
            con.execute(
                "INSERT INTO breaks (run_id, break_number, prompted_at, resolved_at, user_input) "
                "VALUES (?, ?, ?, ?, ?)",
                (args.run_id, bn, now, now, OVERNIGHT_PLACEHOLDER),
            )
        else:
            # Break was opened (prompted) but not yet resolved — resolve it.
            con.execute(
                "UPDATE breaks SET resolved_at=?, user_input=? "
                "WHERE run_id=? AND break_number=? AND resolved_at IS NULL",
                (now, OVERNIGHT_PLACEHOLDER, args.run_id, bn),
            )

    con.close()
    print(f"break {bn} queued")


# ---------------------------------------------------------------------------
# Subcommand: digest
# ---------------------------------------------------------------------------

def cmd_digest(args: argparse.Namespace) -> None:
    con = _connect(args.run_id)
    run = con.execute(
        "SELECT question, started_at, overnight FROM runs WHERE run_id=?",
        (args.run_id,),
    ).fetchone()
    if not run:
        con.close()
        raise SystemExit(f"no such run: {args.run_id}")

    breaks = con.execute(
        "SELECT break_number, prompted_at, resolved_at, user_input "
        "FROM breaks WHERE run_id=? ORDER BY break_number",
        (args.run_id,),
    ).fetchall()

    phases = con.execute(
        "SELECT name, started_at, completed_at, error "
        "FROM phases WHERE run_id=? ORDER BY ordinal",
        (args.run_id,),
    ).fetchall()
    con.close()

    run_dir = _run_dir(args.run_id)
    brief_path = run_dir / "brief.md"
    map_path = run_dir / "understanding_map.md"

    lines: list[str] = []
    lines.append("# Overnight Run Digest")
    lines.append("")
    lines.append(f"**Run ID**: `{args.run_id}`")
    lines.append(f"**Question**: {run['question']}")
    lines.append(f"**Started**: {run['started_at']}")
    lines.append(f"**Overnight mode**: {'yes' if run['overnight'] else 'no'}")
    lines.append("")

    # --- Break summaries ---
    lines.append("## Queued Breaks")
    lines.append("")

    breaks_by_num = {b["break_number"]: b for b in breaks}
    for bn in (0, 1, 2):
        lines.append(f"### Break {bn}")
        lines.append("")
        lines.append(f"**Pipeline prompt**: {BREAK_PROMPTS.get(bn, '(no prompt recorded)')}")
        lines.append("")
        b = breaks_by_num.get(bn)
        if b:
            auto_answer = b["user_input"] or ""
            is_overnight_auto = auto_answer == OVERNIGHT_PLACEHOLDER
            lines.append(f"**Auto-answer**: {auto_answer}")
            lines.append("")
            if is_overnight_auto:
                lines.append(
                    "**Pipeline decision**: continued with default parameters "
                    "(overnight mode — no human redirect)"
                )
            else:
                lines.append(
                    f"**Pipeline decision**: user-provided input was used: {auto_answer!r}"
                )
        else:
            lines.append("**Status**: break not yet reached")
        lines.append("")

    # --- Phase summary ---
    lines.append("## Phase Summary")
    lines.append("")
    lines.append("| Phase | Started | Completed | Error |")
    lines.append("|-------|---------|-----------|-------|")
    for ph in phases:
        started = ph["started_at"] or "-"
        completed = ph["completed_at"] or "-"
        error = ph["error"] or "-"
        lines.append(f"| {ph['name']} | {started} | {completed} | {error} |")
    lines.append("")

    # --- Final outputs ---
    lines.append("## Final Outputs")
    lines.append("")
    if brief_path.exists():
        lines.append(f"- **Research Brief**: `{brief_path}`")
    else:
        lines.append("- **Research Brief**: not yet generated")
    if map_path.exists():
        lines.append(f"- **Understanding Map**: `{map_path}`")
    else:
        lines.append("- **Understanding Map**: not yet generated")
    lines.append("")
    lines.append(
        "> To redirect the pipeline, use `--resume` on the run and answer "
        "the next break interactively."
    )
    lines.append("")

    digest_path = run_dir / "digest.md"
    digest_path.write_text("\n".join(lines))
    print(str(digest_path))


# ---------------------------------------------------------------------------
# Subcommand: status
# ---------------------------------------------------------------------------

def cmd_status(args: argparse.Namespace) -> None:
    con = _connect(args.run_id)
    run = con.execute(
        "SELECT question, started_at, overnight FROM runs WHERE run_id=?",
        (args.run_id,),
    ).fetchone()
    if not run:
        con.close()
        raise SystemExit(f"no such run: {args.run_id}")

    breaks = con.execute(
        "SELECT break_number, resolved_at, user_input "
        "FROM breaks WHERE run_id=? ORDER BY break_number",
        (args.run_id,),
    ).fetchall()
    con.close()

    run_dir = _run_dir(args.run_id)
    digest_exists = (run_dir / "digest.md").exists()

    print(f"run_id:   {args.run_id}")
    print(f"overnight: {'yes' if run['overnight'] else 'no'}")
    print(f"digest:   {'generated' if digest_exists else 'not generated'}")
    print()
    print("breaks:")
    breaks_by_num = {b["break_number"]: b for b in breaks}
    for bn in (0, 1, 2):
        b = breaks_by_num.get(bn)
        if b is None:
            status = "pending"
        elif b["resolved_at"] is None:
            status = "open (not resolved)"
        elif b["user_input"] == OVERNIGHT_PLACEHOLDER:
            status = "queued (overnight auto-answer)"
        else:
            status = "resolved by user"
        print(f"  break {bn}: {status}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(
        prog="overnight.py",
        description="Overnight mode helpers for deep-research runs.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # queue-break
    pqb = sub.add_parser(
        "queue-break",
        help="Auto-resolve a break with overnight placeholder so the pipeline continues.",
    )
    pqb.add_argument("--run-id", required=True, dest="run_id")
    pqb.add_argument("--break-number", required=True, type=int, dest="break_number")
    pqb.add_argument("--prompt", default=None,
                     help="Optional custom prompt text to record (defaults to standard break prompt)")
    pqb.set_defaults(func=cmd_queue_break)

    # digest
    pd = sub.add_parser(
        "digest",
        help="Generate digest.md summarising all queued breaks and final outputs.",
    )
    pd.add_argument("--run-id", required=True, dest="run_id")
    pd.set_defaults(func=cmd_digest)

    # status
    ps = sub.add_parser(
        "status",
        help="Print overnight mode status and which breaks were queued vs user-resolved.",
    )
    ps.add_argument("--run-id", required=True, dest="run_id")
    ps.set_defaults(func=cmd_status)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
