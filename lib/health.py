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


# v0.113 — alert thresholds. Tunable via env, kwargs, or v0.114
# config file at ~/.cache/coscientist/health_thresholds.json.
DEFAULT_THRESHOLDS = {
    "max_stale_spans": 0,           # any stale = alert
    "max_failed_spans": 5,          # >5 failed = alert
    "max_tool_error_rate": 0.20,    # >20% errors per tool = alert
    "min_quality_score": 0.50,      # mean < 0.5 per agent = alert
    "max_active_runs": 10,          # parallel runs >10 = alert
}


def _config_path() -> Path:
    """v0.114 — global config file path."""
    from lib.cache import cache_root
    return cache_root() / "health_thresholds.json"


def _project_config_path(project_id: str) -> Path:
    """v0.126 — per-project config file path."""
    from lib.cache import cache_root
    return (
        cache_root() / "projects" / project_id /
        "health_thresholds.json"
    )


def _apply_overrides(
    out: dict[str, Any], data: Any,
) -> None:
    """Mutate `out` with type-checked values from `data` dict."""
    if not isinstance(data, dict):
        return
    for k, v in data.items():
        if k not in DEFAULT_THRESHOLDS:
            continue
        expected_type = type(DEFAULT_THRESHOLDS[k])
        if isinstance(v, expected_type):
            out[k] = v
        elif expected_type is float and isinstance(v, int):
            out[k] = float(v)


def _read_config(path: Path) -> dict[str, Any]:
    """Read config file; silent fallback on errors."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def load_thresholds(
    *,
    overrides: dict[str, Any] | None = None,
    config_path: Path | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """v0.114/v0.126 — resolve thresholds with precedence:
    DEFAULT_THRESHOLDS < global_config < project_config < overrides.

    `config_path` overrides the global path lookup (for tests +
    explicit config). `project_id` adds per-project overlay
    after global, before kwargs.

    Bad config file (missing/invalid JSON/wrong types) silent
    fallback. Unknown keys ignored.
    """
    out = dict(DEFAULT_THRESHOLDS)
    cfg = config_path if config_path is not None else _config_path()
    _apply_overrides(out, _read_config(cfg))
    if project_id:
        _apply_overrides(
            out, _read_config(_project_config_path(project_id)),
        )
    if overrides:
        _apply_overrides(out, overrides)
    return out


def evaluate_alerts(
    report: dict[str, Any],
    *,
    thresholds: dict[str, Any] | None = None,
    config_path: Path | None = None,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """v0.113 — derive named alerts from a health report.

    Each alert: {severity: 'warn'|'crit', code, message, value,
    threshold}.

    v0.114 — thresholds resolved via load_thresholds.
    v0.126 — `project_id` adds per-project overlay between
    global config and kwargs.
    """
    t = load_thresholds(
        overrides=thresholds, config_path=config_path,
        project_id=project_id,
    )
    alerts: list[dict[str, Any]] = []

    n_stale = len(report.get("stale", []))
    if n_stale > t["max_stale_spans"]:
        alerts.append({
            "severity": "warn", "code": "stale_spans",
            "message": f"{n_stale} stale span(s) past threshold",
            "value": n_stale,
            "threshold": t["max_stale_spans"],
        })

    n_failed = report.get("failed_spans_total", 0) or 0
    if n_failed > t["max_failed_spans"]:
        alerts.append({
            "severity": "crit", "code": "failed_spans",
            "message": f"{n_failed} failed spans across runs",
            "value": n_failed,
            "threshold": t["max_failed_spans"],
        })

    n_active = len(report.get("active", []))
    if n_active > t["max_active_runs"]:
        alerts.append({
            "severity": "warn", "code": "too_many_active",
            "message": f"{n_active} active runs",
            "value": n_active,
            "threshold": t["max_active_runs"],
        })

    by_tool = report.get("tool_latency", {}).get("by_tool", {}) or {}
    for name, d in by_tool.items():
        if d.get("n", 0) >= 5 and d.get("n_errors", 0) > 0:
            rate = d["n_errors"] / max(1, d["n"])
            if rate > t["max_tool_error_rate"]:
                alerts.append({
                    "severity": "crit",
                    "code": "tool_error_rate",
                    "message": (
                        f"{name} error rate "
                        f"{rate:.0%} ({d['n_errors']}/{d['n']})"
                    ),
                    "value": round(rate, 3),
                    "threshold": t["max_tool_error_rate"],
                })

    by_agent = report.get("quality", {}).get("by_agent", {}) or {}
    for agent, d in by_agent.items():
        if d.get("n", 0) >= 3 and d.get("mean", 1.0) < t["min_quality_score"]:
            alerts.append({
                "severity": "warn",
                "code": "low_quality",
                "message": (
                    f"{agent} mean {d['mean']:.2f} below "
                    f"{t['min_quality_score']:.2f}"
                ),
                "value": round(d["mean"], 3),
                "threshold": t["min_quality_score"],
            })

    return alerts


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

    # tool latency + quality leaderboards + harvest summary
    try:
        tool_latency = trace_status.tool_call_latency_across_runs()
    except Exception:
        tool_latency = {"n_rows": 0, "by_tool": {}}
    try:
        quality = agent_quality.leaderboard()
    except Exception:
        quality = {"n_rows": 0, "by_agent": {}}
    try:
        harvests = trace_status.harvest_summary_across_runs()
    except Exception:
        harvests = {"n_harvests": 0, "by_persona": {},
                    "totals": {"raw": 0, "deduped": 0,
                                "kept": 0, "queries": 0}}
    try:
        gates = trace_status.gate_summary_across_runs()
    except Exception:
        gates = {"n_gates": 0, "by_gate": {}}

    return {
        "n_runs": n_runs,
        "active": active,
        "stale": stale,
        "tool_latency": tool_latency,
        "quality": quality,
        "harvests": harvests,
        "gates": gates,
        "failed_spans_total": failed_total,
    }


def render_md(report: dict[str, Any],
              *, alerts: list[dict] | None = None) -> str:
    lines = ["# Coscientist health", ""]
    # v0.113 — alerts banner first if any
    if alerts:
        lines.append("## Alerts")
        lines.append("")
        for a in alerts:
            emoji = "🚨" if a["severity"] == "crit" else "⚠️"
            lines.append(
                f"- {emoji} **{a['code']}** {a['message']} "
                f"(threshold={a['threshold']})"
            )
        lines.append("")
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

    gates = report.get("gates") or {}
    by_gate = gates.get("by_gate", {})
    if by_gate:
        lines.append("## Gate decisions")
        lines.append("")
        for name, d in sorted(
            by_gate.items(), key=lambda kv: -kv[1]["n_rejected"],
        ):
            lines.append(
                f"- **{name}** ok={d['n_ok']} "
                f"rejected={d['n_rejected']} "
                f"(total={d['n_total']})"
            )
            for err in d["recent_errors"][:2]:
                lines.append(f"  - ❌ {err[:100]}")
        lines.append("")

    harvests = report.get("harvests") or {}
    by_persona = harvests.get("by_persona", {})
    if by_persona:
        lines.append("## Harvest activity (per persona)")
        lines.append("")
        for persona, d in sorted(
            by_persona.items(), key=lambda kv: -kv[1]["kept"],
        ):
            lines.append(
                f"- **{persona}** harvests={d['n']} "
                f"raw={d['raw']} → deduped={d['deduped']} "
                f"→ kept={d['kept']} (queries={d['queries']})"
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
    p.add_argument(
        "--no-alerts", action="store_true",
        help="v0.113: suppress alert banner (raw report only).",
    )
    p.add_argument(
        "--show-thresholds", action="store_true",
        help="v0.114: print resolved thresholds + config path "
             "as JSON, then exit.",
    )
    p.add_argument(
        "--project-id", default=None,
        help="v0.126: apply per-project threshold overlay "
             "from <cache>/projects/<pid>/health_thresholds.json.",
    )
    args = p.parse_args(argv)
    if args.show_thresholds:
        out = {
            "global_config_path": str(_config_path()),
            "global_config_exists": _config_path().exists(),
            "project_id": args.project_id,
            "project_config_path": (
                str(_project_config_path(args.project_id))
                if args.project_id else None
            ),
            "project_config_exists": (
                _project_config_path(args.project_id).exists()
                if args.project_id else False
            ),
            "thresholds": load_thresholds(
                project_id=args.project_id,
            ),
        }
        sys.stdout.write(json.dumps(out, indent=2) + "\n")
        return 0
    report = collect(max_age_minutes=args.max_age)
    alerts = (
        [] if args.no_alerts
        else evaluate_alerts(report, project_id=args.project_id)
    )
    if args.format == "json":
        out = dict(report)
        out["alerts"] = alerts
        sys.stdout.write(
            json.dumps(out, indent=2, default=str) + "\n"
        )
    else:
        sys.stdout.write(render_md(report, alerts=alerts))
    # v0.113 — non-zero exit if any 'crit' alert fires (CI/cron hook)
    if any(a["severity"] == "crit" for a in alerts):
        return 2
    if alerts:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
