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
    "max_quality_decline": -0.10,   # v0.127: drift delta below this = alert
    "drift_window": 5,              # v0.127: window size for drift check
    "min_thinking_coverage": 0.50,  # v0.170: per-table thinking-log coverage
    "thinking_min_rows": 5,         # v0.170: only alert when n_total > this
    "mcp_degraded_rate": 0.50,      # v0.188: MCP error_rate > this = alert
    "mcp_degraded_min_calls": 5,    # v0.188: only alert when n_calls >= this
    "mcp_window_hours": 24,         # v0.188: rolling window for MCP rates
}


# v0.188 — MCP server name prefixes mapped to canonical source names
# used by lib.source_selector. Tool-call span names look like
# "mcp__<server>__<tool>" (e.g. "mcp__semantic-scholar__search_papers")
# OR are emitted as bare server-prefixed names in some paths. We
# match by substring on the canonical key.
_MCP_SOURCE_KEYS = (
    "consensus",
    "openalex",
    "semantic-scholar",
    "paper-search",
)


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

    # v0.170: thinking-trace coverage alerts (per-table)
    thinking = report.get("thinking", {}) or {}
    for tbl, d in (thinking.get("by_table") or {}).items():
        n_total = d.get("n_total", 0) or 0
        if n_total <= t["thinking_min_rows"]:
            continue
        cov = d.get("coverage", 0.0) or 0.0
        if cov < t["min_thinking_coverage"]:
            alerts.append({
                "severity": "warn",
                "code": "thinking_coverage_low",
                "message": (
                    f"{tbl} thinking-log coverage "
                    f"{cov:.0%} ({d.get('n_with_trace', 0)}/"
                    f"{n_total})"
                ),
                "value": round(cov, 3),
                "threshold": t["min_thinking_coverage"],
            })

    # v0.188: degraded-MCP alerts
    mcp_health = report.get("mcp_health") or {}
    for name, d in mcp_health.items():
        n_calls = d.get("n_calls", 0) or 0
        rate = d.get("error_rate", 0.0) or 0.0
        if (n_calls >= t["mcp_degraded_min_calls"]
                and rate > t["mcp_degraded_rate"]):
            alerts.append({
                "severity": "warn",
                "code": "mcp_degraded",
                "message": (
                    f"{name} error rate {rate:.0%} "
                    f"({d.get('n_errors', 0)}/{n_calls})"
                ),
                "value": round(rate, 3),
                "threshold": t["mcp_degraded_rate"],
            })

    # v0.127: drift alerts
    drift = report.get("drift", {}) or {}
    for agent, d in (drift.get("by_agent") or {}).items():
        if d.get("direction") == "declining":
            delta = d.get("delta_mean", 0)
            if delta <= t["max_quality_decline"]:
                alerts.append({
                    "severity": "warn",
                    "code": "quality_decline",
                    "message": (
                        f"{agent} declined {delta:+.2f} "
                        f"(latest {d['latest_window']['mean']:.2f} "
                        f"vs prior {d['prior_window']['mean']:.2f})"
                    ),
                    "value": delta,
                    "threshold": t["max_quality_decline"],
                })

    return alerts


# v0.170 — tables that carry a `thinking_log_json` column.
_THINKING_TABLES = (
    "hypotheses",
    "attack_findings",
    "novelty_assessments",
    "publishability_verdicts",
)


def _tree_summary_for_db(db: Path) -> dict[str, Any]:
    """v0.170 — per-DB tree-tournament summary.

    Returns: {n_trees, top_per_tree: [{tree_id, top_hyp_id, top_elo}],
              n_pruned}. n_pruned counts distinct hyp ids that appear
    in tournament_matches.{hyp_a,hyp_b} but no longer exist in
    hypotheses (i.e. the row was deleted via subtree pruning).
    """
    out: dict[str, Any] = {
        "n_trees": 0, "top_per_tree": [], "n_pruned": 0,
    }
    if not db.exists():
        return out
    try:
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        try:
            tree_rows = list(con.execute(
                "SELECT tree_id, hyp_id, elo FROM hypotheses "
                "WHERE tree_id IS NOT NULL "
                "ORDER BY tree_id ASC, elo DESC, hyp_id ASC",
            ))
        except sqlite3.OperationalError:
            con.close()
            return out
        seen_trees: set[str] = set()
        for r in tree_rows:
            tid = r["tree_id"]
            if tid in seen_trees:
                continue
            seen_trees.add(tid)
            out["top_per_tree"].append({
                "tree_id": tid,
                "top_hyp_id": r["hyp_id"],
                "top_elo": float(r["elo"] or 0.0),
            })
        out["n_trees"] = len(seen_trees)
        # Pruned-id detection — hyp_a/hyp_b rows that no longer exist
        # in `hypotheses`.
        try:
            pruned = con.execute(
                "SELECT COUNT(*) FROM ("
                "  SELECT hyp_a AS h FROM tournament_matches "
                "  UNION SELECT hyp_b FROM tournament_matches"
                ") WHERE h NOT IN (SELECT hyp_id FROM hypotheses)",
            ).fetchone()[0]
            out["n_pruned"] = int(pruned or 0)
        except sqlite3.OperationalError:
            pass
        con.close()
    except Exception:
        pass
    return out


def _thinking_coverage_for_db(db: Path) -> dict[str, Any]:
    """v0.170 — per-table thinking-log coverage for a single run DB."""
    by_table: dict[str, dict] = {}
    if not db.exists():
        return {"by_table": by_table}
    try:
        con = sqlite3.connect(db)
    except Exception:
        return {"by_table": by_table}
    try:
        for tbl in _THINKING_TABLES:
            try:
                total = con.execute(
                    f"SELECT COUNT(*) FROM {tbl}",
                ).fetchone()[0]
                covered = con.execute(
                    f"SELECT COUNT(*) FROM {tbl} "
                    f"WHERE thinking_log_json IS NOT NULL",
                ).fetchone()[0]
            except sqlite3.OperationalError:
                continue
            if total == 0 and covered == 0:
                # Skip tables that don't exist or are empty here.
                if tbl not in by_table:
                    by_table[tbl] = {
                        "n_total": 0, "n_with_trace": 0,
                        "coverage": 0.0,
                    }
                continue
            d = by_table.setdefault(tbl, {
                "n_total": 0, "n_with_trace": 0, "coverage": 0.0,
            })
            d["n_total"] += int(total or 0)
            d["n_with_trace"] += int(covered or 0)
    finally:
        con.close()
    return {"by_table": by_table}


def trees_summary_across_runs(
    roots: list[Path] | None = None,
) -> dict[str, Any]:
    """v0.170 — aggregate tree-tournament summary across run DBs."""
    from lib.cache import runs_dir
    root = roots[0] if roots else runs_dir()
    out: dict[str, Any] = {
        "n_trees_total": 0, "n_pruned_total": 0,
        "by_run": [],
    }
    if not root.exists():
        return out
    for db in sorted(root.glob("run-*.db")):
        s = _tree_summary_for_db(db)
        if s["n_trees"] == 0 and s["n_pruned"] == 0:
            continue
        out["n_trees_total"] += s["n_trees"]
        out["n_pruned_total"] += s["n_pruned"]
        out["by_run"].append({
            "db_path": str(db),
            "n_trees": s["n_trees"],
            "n_pruned": s["n_pruned"],
            "top_per_tree": s["top_per_tree"],
        })
    return out


def thinking_coverage_across_runs(
    roots: list[Path] | None = None,
) -> dict[str, Any]:
    """v0.170 — aggregate thinking-log coverage per table across runs."""
    from lib.cache import runs_dir
    root = roots[0] if roots else runs_dir()
    by_table: dict[str, dict] = {
        t: {"n_total": 0, "n_with_trace": 0, "coverage": 0.0}
        for t in _THINKING_TABLES
    }
    if not root.exists():
        return {"by_table": by_table}
    for db in sorted(root.glob("run-*.db")):
        s = _thinking_coverage_for_db(db)
        for tbl, d in (s.get("by_table") or {}).items():
            agg = by_table.setdefault(tbl, {
                "n_total": 0, "n_with_trace": 0, "coverage": 0.0,
            })
            agg["n_total"] += d["n_total"]
            agg["n_with_trace"] += d["n_with_trace"]
    for tbl, d in by_table.items():
        d["coverage"] = (
            d["n_with_trace"] / d["n_total"]
            if d["n_total"] > 0 else 0.0
        )
        d["coverage"] = round(d["coverage"], 4)
    return {"by_table": by_table}


def mcp_error_rates(
    *,
    window_hours: int = 24,
    roots: list[Path] | None = None,
) -> dict[str, dict[str, Any]]:
    """v0.188 — aggregate tool-call error rates per MCP server.

    Walks every `run-*.db`, reads `spans` rows with kind='tool-call',
    filters by `started_at >= now - window_hours`, groups by MCP
    source key (substring match on `name` against `_MCP_SOURCE_KEYS`).

    Returns: `{mcp_name: {n_calls, n_errors, error_rate}}`. Empty
    dict on no data or missing tables.
    """
    from datetime import UTC, datetime, timedelta

    from lib.cache import runs_dir
    root = roots[0] if roots else runs_dir()
    out: dict[str, dict[str, Any]] = {}
    if not root.exists():
        return out
    cutoff = (
        datetime.now(UTC) - timedelta(hours=window_hours)
    ).isoformat()
    for db in sorted(root.glob("run-*.db")):
        try:
            con = sqlite3.connect(db)
            con.row_factory = sqlite3.Row
        except Exception:
            continue
        try:
            try:
                rows = list(con.execute(
                    "SELECT name, status, started_at FROM spans "
                    "WHERE kind='tool-call' AND started_at >= ?",
                    (cutoff,),
                ))
            except sqlite3.OperationalError:
                continue
            for r in rows:
                name = (r["name"] or "").lower()
                for key in _MCP_SOURCE_KEYS:
                    if key in name:
                        d = out.setdefault(key, {
                            "n_calls": 0, "n_errors": 0,
                            "error_rate": 0.0,
                        })
                        d["n_calls"] += 1
                        if r["status"] == "error":
                            d["n_errors"] += 1
                        break
        finally:
            con.close()
    for d in out.values():
        n = d["n_calls"]
        d["error_rate"] = (
            round(d["n_errors"] / n, 4) if n else 0.0
        )
    return out


def collect(*, max_age_minutes: int = 30) -> dict[str, Any]:
    """Walk every run-*.db and aggregate health signals."""
    from lib import agent_quality, trace_status
    from lib.cache import runs_dir

    root = runs_dir()
    if not root.exists():
        return {
            "n_runs": 0, "n_uninstrumented": 0,
            "uninstrumented_paths": [],
            "active": [], "stale": [],
            "tool_latency": {}, "quality": {},
            "failed_spans_total": 0,
        }

    active: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    failed_total = 0
    n_runs = 0
    n_uninstrumented = 0  # v0.184 — DBs lacking traces table (pre-v0.89)
    uninstrumented_paths: list[str] = []

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
                # v0.184 — distinguish "no traces table" from generic
                # error so the dump can surface migration-needed DBs.
                n_uninstrumented += 1
                uninstrumented_paths.append(str(db))
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
    try:
        drift = agent_quality.quality_drift()
    except Exception:
        drift = {"n_rows": 0, "by_agent": {}}
    try:
        trees = trees_summary_across_runs()
    except Exception:
        trees = {"n_trees_total": 0, "n_pruned_total": 0, "by_run": []}
    try:
        thinking = thinking_coverage_across_runs()
    except Exception:
        thinking = {"by_table": {}}
    # v0.188 — MCP error-rate aggregation
    try:
        mcp_health = mcp_error_rates()
    except Exception:
        mcp_health = {}

    return {
        "n_runs": n_runs,
        "n_uninstrumented": n_uninstrumented,
        "uninstrumented_paths": uninstrumented_paths,
        "active": active,
        "stale": stale,
        "tool_latency": tool_latency,
        "quality": quality,
        "harvests": harvests,
        "gates": gates,
        "drift": drift,
        "trees": trees,
        "thinking": thinking,
        "mcp_health": mcp_health,
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
    n_unin = report.get("n_uninstrumented", 0)
    if n_unin:
        lines.append(
            f"- **Uninstrumented (pre-v0.89, no traces table)**: {n_unin}"
        )
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

    # v0.170 — tree summary
    trees = report.get("trees") or {}
    if trees.get("n_trees_total", 0) > 0 or trees.get("by_run"):
        lines.append("## Tree tournaments")
        lines.append("")
        lines.append(
            f"- Trees: {trees.get('n_trees_total', 0)}"
        )
        lines.append(
            f"- Pruned hyp ids: {trees.get('n_pruned_total', 0)}"
        )
        for r in trees.get("by_run", [])[:5]:
            for top in r.get("top_per_tree", [])[:3]:
                lines.append(
                    f"  - tree `{top['tree_id']}` top "
                    f"`{top['top_hyp_id']}` "
                    f"Elo {round(top['top_elo'])}"
                )
        lines.append("")

    # v0.170 — thinking-trace coverage
    thinking = report.get("thinking") or {}
    by_table = thinking.get("by_table") or {}
    if any(d.get("n_total", 0) for d in by_table.values()):
        lines.append("## Thinking-trace coverage")
        lines.append("")
        for tbl, d in sorted(by_table.items()):
            if not d.get("n_total"):
                continue
            lines.append(
                f"- **{tbl}** {d['n_with_trace']}/{d['n_total']} "
                f"({d['coverage']:.0%})"
            )
        lines.append("")

    # v0.188 — MCP source health (only if any source is degraded)
    mcp_health = report.get("mcp_health") or {}
    degraded = [
        (n, d) for n, d in mcp_health.items()
        if (d.get("n_calls", 0) >= 5
            and d.get("error_rate", 0.0) > 0.5)
    ]
    if degraded:
        lines.append("## MCP source health")
        lines.append("")
        for name, d in sorted(degraded, key=lambda kv: -kv[1]["error_rate"]):
            lines.append(
                f"- **{name}** error_rate={d['error_rate']:.0%} "
                f"({d['n_errors']}/{d['n_calls']})"
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
