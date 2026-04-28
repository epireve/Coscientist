"""v0.106 — single-shot health dump across the coscientist stack.

Combines:
  - active runs (in-progress traces)
  - stale spans (status=running past threshold)
  - tool-call latency leaderboard
  - per-agent quality leaderboard
  - failed spans across all runs

One command, one report. Designed for "is anything stuck or
slow?" check during smoke test or daily review.

CLI:
    uv run python -m lib.health [--format md|json] [--max-age 30]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


def collect(*, max_age_minutes: int = 30) -> dict[str, Any]:
    """Walk every run-*.db and aggregate health signals."""
    from lib.cache import runs_dir
    from lib import trace_status, agent_quality

    root = runs_dir()
    if not root.exists():
        return {
            "n_runs": 0, "active": [], "stale": [],
            "tool_latency": {}, "quality": {},
            "failed_spans_total": 0,
        }

    active: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    failed_total = 0
    n_runs = 0

    for db in sorted(root.glob("run-*.db")):
        try:
            con = sqlite3.connect(db)
            con.row_factory = sqlite3.Row
            try:
                traces = list(con.execute(
                    "SELECT trace_id, run_id, status, started_at "
                    "FROM traces",
                ))
            except sqlite3.OperationalError:
                con.close()
                continue
            n_runs += 1
            for t in traces:
                if t["status"] == "running":
                    active.append({
                        "trace_id": t["trace_id"],
                        "run_id": t["run_id"],
                        "started_at": t["started_at"],
                        "db_path": str(db),
                    })
                # count failed spans for this trace
                try:
                    nfail = con.execute(
                        "SELECT COUNT(*) FROM spans "
                        "WHERE trace_id=? AND status='error'",
                        (t["trace_id"],),
                    ).fetchone()[0]
                    failed_total += int(nfail)
                except sqlite3.OperationalError:
                    pass
            con.close()
        except Exception:
            continue
        # stale spans for this DB
        try:
            stale.extend(trace_status.find_stale_spans(
                db, max_age_minutes=max_age_minutes,
            ))
        except Exception:
            pass

    # tool latency + quality leaderboards
    try:
        tool_latency = trace_status.tool_call_latency_across_runs()
    except Exception:
        tool_latency = {"n_rows": 0, "by_tool": {}}
    try:
        quality = agent_quality.leaderboard()
    except Exception:
        quality = {"n_rows": 0, "by_agent": {}}

    return {
        "n_runs": n_runs,
        "active": active,
        "stale": stale,
        "tool_latency": tool_latency,
        "quality": quality,
        "failed_spans_total": failed_total,
    }


def render_md(report: dict[str, Any]) -> str:
    lines = ["# Coscientist health", ""]
    lines.append(f"- **Runs scanned**: {report['n_runs']}")
    lines.append(f"- **Active**: {len(report['active'])}")
    lines.append(f"- **Stale spans**: {len(report['stale'])}")
    lines.append(
        f"- **Failed spans (total)**: {report['failed_spans_total']}"
    )
    lines.append("")

    if report["active"]:
        lines.append("## Active runs")
        lines.append("")
        for a in report["active"]:
            lines.append(
                f"- 🔄 `{a['trace_id']}` started {a['started_at']}"
            )
        lines.append("")

    if report["stale"]:
        lines.append("## Stale spans (still running)")
        lines.append("")
        for s in report["stale"]:
            lines.append(
                f"- ⏳ `{s['kind']}`/{s['name']} "
                f"(trace={s['trace_id'][:16]}) "
                f"age={s['age_minutes']}m"
            )
        lines.append("")

    by_tool = report["tool_latency"].get("by_tool", {})
    if by_tool:
        lines.append("## Tool-call latency (slowest first)")
        lines.append("")
        sorted_tools = sorted(
            by_tool.items(), key=lambda kv: -kv[1]["mean_ms"],
        )[:10]
        for name, d in sorted_tools:
            lines.append(
                f"- `{name}` n={d['n']} "
                f"errors={d['n_errors']} "
                f"mean={d['mean_ms']:.0f}ms "
                f"p95={d['p95_ms']}ms"
            )
        lines.append("")

    by_agent = report["quality"].get("by_agent", {})
    if by_agent:
        lines.append("## Agent quality (lowest mean first)")
        lines.append("")
        sorted_agents = sorted(
            by_agent.items(), key=lambda kv: kv[1]["mean"],
        )
        for agent, d in sorted_agents:
            lines.append(
                f"- **{agent}** mean={d['mean']:.2f} "
                f"latest={d.get('latest_score', 0):.2f} "
                f"(n={d['n']}, runs={d['n_runs']})"
            )
        lines.append("")

    if not (report["active"] or report["stale"]
            or by_tool or by_agent):
        lines.append("_No data — instrumentation hasn't logged yet._")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="health",
        description="Coscientist health dump (v0.106).",
    )
    p.add_argument("--format", choices=("md", "json"), default="md")
    p.add_argument("--max-age", type=int, default=30,
                    help="Stale-span threshold in minutes.")
    args = p.parse_args(argv)
    report = collect(max_age_minutes=args.max_age)
    if args.format == "json":
        sys.stdout.write(
            json.dumps(report, indent=2, default=str) + "\n"
        )
    else:
        sys.stdout.write(render_md(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
