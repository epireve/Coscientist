"""v0.173 — MCP cost dashboard.

Read-only aggregation over `spans` (kind='tool-call') across every
run DB. Maps tool span names to MCP servers via substring match,
applies a heuristic cost table, surfaces 7d/30d/all-time call
counts and estimated costs.

Pure stdlib. WAL not required (read-only). CLI:

    uv run python -m lib.cost_dashboard [--format json|text]
                                        [--window-days 7]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Heuristic cost table — dollars per call. Update when pricing
# changes upstream.
COST_PER_CALL: dict[str, float] = {
    "consensus": 0.10,         # paid (Pro tier)
    "openalex": 0.0,           # free
    "semantic-scholar": 0.0,   # free w/ API key
    "paper-search": 0.0,       # free
}

# Substring tokens used to bucket a span name into one of the
# servers above. Lowercased; first match wins. Order matters —
# longer/more-specific tokens go first so e.g. "semantic-scholar"
# wins over a shorter generic prefix.
_SERVER_TOKENS: list[tuple[str, str]] = [
    ("semantic-scholar", "semantic-scholar"),
    ("semantic_scholar", "semantic-scholar"),
    ("paper-search", "paper-search"),
    ("paper_search", "paper-search"),
    ("openalex", "openalex"),
    ("consensus", "consensus"),
]


def classify(span_name: str) -> str | None:
    """Return server slug for a tool span name, or None."""
    if not span_name:
        return None
    s = span_name.lower()
    for token, server in _SERVER_TOKENS:
        if token in s:
            return server
    return None


def _open(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def collect(
    *,
    window_days: int = 7,
    roots: list[Path] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Aggregate tool-call spans into per-server cost report.

    Returns:
      {
        n_dbs, n_calls_total,
        window_days,
        per_server: {server: {n_7d, n_30d, n_all,
                                cost_7d, cost_30d, cost_all,
                                cost_per_call}},
        totals: {n_7d, n_30d, n_all,
                  cost_7d, cost_30d, cost_all,
                  estimated_cost_window},
      }
    """
    from lib.cache import runs_dir
    root = roots[0] if roots else runs_dir()
    if now is None:
        now = datetime.now(UTC)
    cutoff_window = (now - timedelta(days=window_days)).isoformat()
    cutoff_30 = (now - timedelta(days=30)).isoformat()

    per_server: dict[str, dict] = {
        s: {"n_7d": 0, "n_30d": 0, "n_all": 0,
             "cost_7d": 0.0, "cost_30d": 0.0, "cost_all": 0.0,
             "cost_per_call": COST_PER_CALL[s]}
        for s in COST_PER_CALL
    }
    n_dbs = 0
    n_calls_total = 0
    if not root.exists():
        return {
            "n_dbs": 0, "n_calls_total": 0,
            "window_days": window_days,
            "per_server": per_server,
            "totals": {
                "n_7d": 0, "n_30d": 0, "n_all": 0,
                "cost_7d": 0.0, "cost_30d": 0.0,
                "cost_all": 0.0,
                "estimated_cost_window": 0.0,
            },
        }
    for db in sorted(root.glob("run-*.db")):
        try:
            con = _open(db)
            try:
                rows = list(con.execute(
                    "SELECT name, started_at FROM spans "
                    "WHERE kind='tool-call'",
                ))
            except sqlite3.OperationalError:
                con.close()
                continue
            con.close()
        except Exception:
            continue
        n_dbs += 1
        for r in rows:
            server = classify(r["name"] or "")
            if not server:
                continue
            n_calls_total += 1
            d = per_server[server]
            d["n_all"] += 1
            d["cost_all"] += d["cost_per_call"]
            started = r["started_at"] or ""
            if started >= cutoff_30:
                d["n_30d"] += 1
                d["cost_30d"] += d["cost_per_call"]
            if started >= cutoff_window:
                d["n_7d"] += 1
                d["cost_7d"] += d["cost_per_call"]

    totals = {
        "n_7d": sum(d["n_7d"] for d in per_server.values()),
        "n_30d": sum(d["n_30d"] for d in per_server.values()),
        "n_all": sum(d["n_all"] for d in per_server.values()),
        "cost_7d": round(sum(
            d["cost_7d"] for d in per_server.values()
        ), 4),
        "cost_30d": round(sum(
            d["cost_30d"] for d in per_server.values()
        ), 4),
        "cost_all": round(sum(
            d["cost_all"] for d in per_server.values()
        ), 4),
    }
    totals["estimated_cost_window"] = totals["cost_7d"]
    # Round per-server costs.
    for d in per_server.values():
        d["cost_7d"] = round(d["cost_7d"], 4)
        d["cost_30d"] = round(d["cost_30d"], 4)
        d["cost_all"] = round(d["cost_all"], 4)
    return {
        "n_dbs": n_dbs,
        "n_calls_total": n_calls_total,
        "window_days": window_days,
        "per_server": per_server,
        "totals": totals,
    }


def render_text(report: dict[str, Any]) -> str:
    lines = [
        "# MCP cost dashboard",
        f"- DBs scanned: {report['n_dbs']}",
        f"- Tool-calls bucketed: {report['n_calls_total']}",
        f"- Window: {report['window_days']}d",
        "",
        "## Totals",
        f"- {report['window_days']}d: "
        f"{report['totals']['n_7d']} calls "
        f"(${report['totals']['cost_7d']:.4f})",
        f"- 30d: {report['totals']['n_30d']} calls "
        f"(${report['totals']['cost_30d']:.4f})",
        f"- All-time: {report['totals']['n_all']} calls "
        f"(${report['totals']['cost_all']:.4f})",
        "",
        "## Per-server",
    ]
    for server, d in sorted(report["per_server"].items()):
        lines.append(
            f"- **{server}** (${d['cost_per_call']:.2f}/call) "
            f"{report['window_days']}d={d['n_7d']} "
            f"30d={d['n_30d']} all={d['n_all']} "
            f"cost_all=${d['cost_all']:.4f}"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="cost_dashboard",
        description="MCP cost dashboard (v0.173).",
    )
    p.add_argument("--format", choices=("json", "text"),
                    default="text")
    p.add_argument("--window-days", type=int, default=7,
                    help="Short-window in days (default 7)")
    p.add_argument("--root", default=None,
                    help="Override runs root.")
    args = p.parse_args(argv)
    roots = [Path(args.root)] if args.root else None
    report = collect(window_days=args.window_days, roots=roots)
    if args.format == "json":
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
    else:
        sys.stdout.write(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
