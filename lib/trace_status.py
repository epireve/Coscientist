"""v0.95 — quick trace-status summary.

Faster + more compact than `trace_render --format md` when you
just want "is run X alive, what phase, any failed spans". Built
for live smoke-test inspection.

Two surfaces:
  - `summarize_trace(db_path, trace_id)` → dict
  - `summarize_runs(roots=None)` → list[dict] across all run DBs

CLI:
    uv run python -m lib.trace_status                    # all runs
    uv run python -m lib.trace_status --run-id <rid>     # one run
    uv run python -m lib.trace_status --format md|json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


def _runs_root() -> Path:
    """Default: ~/.cache/coscientist/runs/."""
    from lib.cache import runs_dir
    return runs_dir()


def _open(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def summarize_trace(db_path: Path, trace_id: str) -> dict[str, Any]:
    """Return concise status for one trace.

    Shape:
      {
        trace_id, run_id, status, started_at, completed_at,
        n_spans, n_failed, n_running, n_ok,
        by_kind: {phase: 3, gate: 1, tool-call: 7, ...},
        latest_phase: <name>|None,
        latest_error: {span, name, kind, msg}|None,
      }
    Returns {found: False} if trace_id absent.
    """
    if not db_path.exists():
        return {"found": False, "trace_id": trace_id,
                "error": f"db not found: {db_path}"}
    con = _open(db_path)
    try:
        try:
            t = con.execute(
                "SELECT * FROM traces WHERE trace_id=?",
                (trace_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return {"found": False, "trace_id": trace_id,
                    "error": "no traces table (pre-v11 db)"}
        if t is None:
            return {"found": False, "trace_id": trace_id}
        spans = list(con.execute(
            "SELECT span_id, name, kind, status, error_kind, "
            "error_msg, started_at FROM spans "
            "WHERE trace_id=? ORDER BY started_at",
            (trace_id,),
        ))
        by_kind: dict[str, int] = {}
        n_failed = n_running = n_ok = 0
        latest_phase = None
        latest_error = None
        for s in spans:
            k = s["kind"]
            by_kind[k] = by_kind.get(k, 0) + 1
            if s["status"] == "error":
                n_failed += 1
                latest_error = {
                    "span_id": s["span_id"],
                    "name": s["name"],
                    "kind": k,
                    "msg": s["error_msg"],
                }
            elif s["status"] == "running":
                n_running += 1
            elif s["status"] == "ok":
                n_ok += 1
            if k == "phase":
                latest_phase = s["name"]
        return {
            "found": True,
            "trace_id": t["trace_id"],
            "run_id": t["run_id"],
            "status": t["status"],
            "started_at": t["started_at"],
            "completed_at": t["completed_at"],
            "n_spans": len(spans),
            "n_failed": n_failed,
            "n_running": n_running,
            "n_ok": n_ok,
            "by_kind": by_kind,
            "latest_phase": latest_phase,
            "latest_error": latest_error,
        }
    finally:
        con.close()


def summarize_runs(roots: list[Path] | None = None) -> list[dict[str, Any]]:
    """Walk all run DBs and summarize each trace they contain."""
    out: list[dict[str, Any]] = []
    root = roots[0] if roots else _runs_root()
    if not root.exists():
        return out
    for db in sorted(root.glob("run-*.db")):
        try:
            con = _open(db)
            try:
                traces = list(con.execute("SELECT trace_id FROM traces"))
            except sqlite3.OperationalError:
                con.close()
                continue
            con.close()
            for r in traces:
                tid = r["trace_id"]
                summary = summarize_trace(db, tid)
                summary["db_path"] = str(db)
                out.append(summary)
        except Exception as e:
            out.append({"db_path": str(db), "error": str(e),
                        "found": False})
    return out


def render_md(summaries: list[dict[str, Any]]) -> str:
    if not summaries:
        return "# Trace status\n\n_No traces found._\n"
    lines = ["# Trace status", "",
             f"_{len(summaries)} trace(s)._", ""]
    for s in summaries:
        if not s.get("found"):
            err = s.get("error", "not found")
            lines.append(f"- ❓ `{s.get('trace_id', '?')}` — {err}")
            continue
        emoji = {"running": "🔄", "ok": "✅",
                 "error": "❌"}.get(s["status"], "·")
        kind_str = ", ".join(
            f"{k}={n}" for k, n in sorted(s["by_kind"].items())
        ) or "(none)"
        lines.append(
            f"- {emoji} `{s['trace_id']}` "
            f"run=`{s.get('run_id') or '-'}` "
            f"status={s['status']} "
            f"spans={s['n_spans']} "
            f"(ok={s['n_ok']}, run={s['n_running']}, "
            f"err={s['n_failed']}) "
            f"latest_phase=`{s.get('latest_phase') or '-'}`"
        )
        lines.append(f"  - kinds: {kind_str}")
        if s.get("latest_error"):
            e = s["latest_error"]
            lines.append(
                f"  - ❌ `{e['name']}` ({e['kind']}): "
                f"{(e['msg'] or '')[:100]}"
            )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="trace_status",
        description="Quick status across coscientist run traces.",
    )
    p.add_argument("--run-id", default=None,
                    help="Inspect one run; default scans all runs.")
    p.add_argument("--format", choices=("md", "json"), default="md")
    args = p.parse_args(argv)
    if args.run_id:
        from lib.cache import run_db_path
        s = summarize_trace(run_db_path(args.run_id), args.run_id)
        summaries = [s]
    else:
        summaries = summarize_runs()
    if args.format == "json":
        sys.stdout.write(json.dumps(summaries, indent=2,
                                     default=str) + "\n")
    else:
        sys.stdout.write(render_md(summaries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
