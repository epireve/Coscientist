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


def find_stale_spans(
    db_path: Path, *, max_age_minutes: int = 30,
    now_iso: str | None = None,
) -> list[dict[str, Any]]:
    """v0.97 — return spans still status='running' past `max_age_minutes`.

    Useful during smoke tests: a phase or sub-agent crashed without
    closing its span, leaving status=running indefinitely. Caller
    decides whether to mark them error or just report.

    Each entry: {span_id, trace_id, kind, name, started_at,
                 age_minutes}.
    """
    from datetime import UTC, datetime, timedelta
    if now_iso is None:
        now = datetime.now(UTC)
    else:
        now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    cutoff = now - timedelta(minutes=max_age_minutes)
    if not db_path.exists():
        return []
    con = _open(db_path)
    try:
        try:
            rows = list(con.execute(
                "SELECT span_id, trace_id, kind, name, started_at "
                "FROM spans WHERE status='running' "
                "ORDER BY started_at",
            ))
        except sqlite3.OperationalError:
            return []
    finally:
        con.close()
    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            started = datetime.fromisoformat(
                r["started_at"].replace("Z", "+00:00"),
            )
        except (ValueError, AttributeError):
            continue
        if started < cutoff:
            age = int((now - started).total_seconds() / 60)
            out.append({
                "span_id": r["span_id"],
                "trace_id": r["trace_id"],
                "kind": r["kind"],
                "name": r["name"],
                "started_at": r["started_at"],
                "age_minutes": age,
            })
    return out


def tool_call_latency(
    db_path: Path, *, trace_id: str | None = None,
) -> dict[str, Any]:
    """v0.100 — aggregate tool-call span durations by tool name.

    Returns: {n_rows, by_tool: {name: {n, n_errors, mean_ms,
                                       p50_ms, p95_ms, max_ms}}}.
    Filters to spans with kind='tool-call' and a non-null
    duration_ms.
    """
    if not db_path.exists():
        return {"n_rows": 0, "by_tool": {}}
    con = _open(db_path)
    try:
        try:
            if trace_id:
                rows = list(con.execute(
                    "SELECT name, duration_ms, status FROM spans "
                    "WHERE trace_id=? AND kind='tool-call' "
                    "AND duration_ms IS NOT NULL",
                    (trace_id,),
                ))
            else:
                rows = list(con.execute(
                    "SELECT name, duration_ms, status FROM spans "
                    "WHERE kind='tool-call' "
                    "AND duration_ms IS NOT NULL",
                ))
        except sqlite3.OperationalError:
            return {"n_rows": 0, "by_tool": {}}
    finally:
        con.close()
    by_tool: dict[str, dict] = {}
    for r in rows:
        d = by_tool.setdefault(
            r["name"],
            {"n": 0, "n_errors": 0, "durations": []},
        )
        d["n"] += 1
        if r["status"] == "error":
            d["n_errors"] += 1
        d["durations"].append(int(r["duration_ms"]))
    for name, d in by_tool.items():
        durs = sorted(d.pop("durations"))
        n = len(durs)
        d["mean_ms"] = sum(durs) / n if n else 0.0
        d["p50_ms"] = durs[n // 2] if n else 0
        d["p95_ms"] = durs[min(n - 1, int(n * 0.95))] if n else 0
        d["max_ms"] = durs[-1] if n else 0
    return {"n_rows": len(rows), "by_tool": by_tool}


def tool_call_latency_across_runs(
    roots: list[Path] | None = None,
) -> dict[str, Any]:
    """v0.100 — tool-call latency aggregated across every run DB."""
    from lib.cache import runs_dir
    root = roots[0] if roots else runs_dir()
    by_tool: dict[str, dict] = {}
    n_dbs = 0
    n_rows = 0
    if not root.exists():
        return {"n_rows": 0, "n_dbs": 0, "by_tool": {}}
    for db in sorted(root.glob("run-*.db")):
        try:
            con = _open(db)
            try:
                rows = list(con.execute(
                    "SELECT name, duration_ms, status FROM spans "
                    "WHERE kind='tool-call' "
                    "AND duration_ms IS NOT NULL",
                ))
            except sqlite3.OperationalError:
                con.close()
                continue
            con.close()
            n_dbs += 1
            n_rows += len(rows)
            for r in rows:
                d = by_tool.setdefault(
                    r["name"],
                    {"n": 0, "n_errors": 0, "durations": []},
                )
                d["n"] += 1
                if r["status"] == "error":
                    d["n_errors"] += 1
                d["durations"].append(int(r["duration_ms"]))
        except Exception:
            continue
    for name, d in by_tool.items():
        durs = sorted(d.pop("durations"))
        n = len(durs)
        d["mean_ms"] = sum(durs) / n if n else 0.0
        d["p50_ms"] = durs[n // 2] if n else 0
        d["p95_ms"] = durs[min(n - 1, int(n * 0.95))] if n else 0
        d["max_ms"] = durs[-1] if n else 0
    return {"n_rows": n_rows, "n_dbs": n_dbs, "by_tool": by_tool}


def mark_stale_error(
    db_path: Path, *, max_age_minutes: int = 30,
    reason: str = "stale-span auto-close",
    now_iso: str | None = None,
) -> list[dict[str, Any]]:
    """v0.98 — close stale running spans by setting status='error'.

    Mutates only spans returned by `find_stale_spans`. Sets
    `error_kind='stale'`, `error_msg=<reason>`, `ended_at=now`.
    Returns the list of closed spans (same shape as
    find_stale_spans + `closed_at`).
    """
    from datetime import UTC, datetime
    stale = find_stale_spans(
        db_path, max_age_minutes=max_age_minutes, now_iso=now_iso,
    )
    if not stale:
        return []
    now = datetime.now(UTC).isoformat() if now_iso is None else now_iso
    con = _open(db_path)
    try:
        with con:
            for s in stale:
                con.execute(
                    "UPDATE spans SET status='error', "
                    "error_kind='stale', error_msg=?, ended_at=? "
                    "WHERE span_id=? AND status='running'",
                    (reason, now, s["span_id"]),
                )
                s["closed_at"] = now
    finally:
        con.close()
    return stale


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
    p.add_argument(
        "--stale-only", action="store_true",
        help="v0.97: list spans still running past --max-age minutes.",
    )
    p.add_argument("--max-age", type=int, default=30,
                    help="Stale threshold in minutes (default 30).")
    p.add_argument(
        "--mark-error", action="store_true",
        help="v0.98: mutate stale spans to status=error.",
    )
    p.add_argument(
        "--reason", default="stale-span auto-close",
        help="error_msg used when --mark-error fires.",
    )
    p.add_argument(
        "--tool-latency", action="store_true",
        help="v0.100: aggregate tool-call span durations by name.",
    )
    args = p.parse_args(argv)
    if args.tool_latency:
        from lib.cache import run_db_path
        if args.run_id:
            out = tool_call_latency(
                run_db_path(args.run_id),
                trace_id=args.run_id,
            )
        else:
            out = tool_call_latency_across_runs()
        if args.format == "json":
            sys.stdout.write(json.dumps(out, indent=2,
                                         default=str) + "\n")
        else:
            lines = ["# Tool-call latency", "",
                     f"_{out['n_rows']} call(s)._", ""]
            for name, d in sorted(out["by_tool"].items(),
                                   key=lambda kv: -kv[1]["mean_ms"]):
                lines.append(
                    f"- `{name}` n={d['n']} "
                    f"errors={d['n_errors']} "
                    f"mean={d['mean_ms']:.0f}ms "
                    f"p50={d['p50_ms']}ms "
                    f"p95={d['p95_ms']}ms "
                    f"max={d['max_ms']}ms"
                )
            lines.append("")
            sys.stdout.write("\n".join(lines))
        return 0
    if args.stale_only:
        from lib.cache import run_db_path, runs_dir
        op = (
            (lambda db: mark_stale_error(
                db, max_age_minutes=args.max_age,
                reason=args.reason,
            ))
            if args.mark_error
            else (lambda db: find_stale_spans(
                db, max_age_minutes=args.max_age,
            ))
        )
        if args.run_id:
            stale = op(run_db_path(args.run_id))
        else:
            stale = []
            d = runs_dir()
            if d.exists():
                for db in sorted(d.glob("run-*.db")):
                    stale.extend(op(db))
        if args.format == "json":
            sys.stdout.write(json.dumps(stale, indent=2,
                                         default=str) + "\n")
        else:
            if not stale:
                sys.stdout.write("# Stale spans\n\n_None._\n")
            else:
                lines = ["# Stale spans (still running)", ""]
                for s in stale:
                    lines.append(
                        f"- ⏳ `{s['kind']}`/{s['name']} "
                        f"(span={s['span_id'][:16]}, "
                        f"trace={s['trace_id'][:16]}) "
                        f"age={s['age_minutes']}m"
                    )
                lines.append("")
                sys.stdout.write("\n".join(lines))
        return 0
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
