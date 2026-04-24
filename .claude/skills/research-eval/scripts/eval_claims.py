#!/usr/bin/env python3
"""Claim-attribution audit for a deep-research run.

For each claim in the run DB, check that supporting_ids exist in
papers_in_run. Flag unattributed claims. Writes a markdown report.
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

from lib.cache import cache_root, run_db_path  # noqa: E402


def audit(run_id: str) -> dict:
    db_path = run_db_path(run_id)
    if not db_path.exists():
        raise SystemExit(f"no run db at {db_path}")

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    papers = {
        r["canonical_id"]
        for r in con.execute(
            "SELECT canonical_id FROM papers_in_run WHERE run_id=?", (run_id,)
        )
    }

    claims = con.execute(
        "SELECT claim_id, canonical_id, agent_name, text, kind, confidence, supporting_ids "
        "FROM claims WHERE run_id=?",
        (run_id,),
    ).fetchall()

    unattributed: list[dict] = []
    bad_support: list[dict] = []
    by_kind: dict[str, int] = {}

    for c in claims:
        kind = c["kind"] or "unknown"
        by_kind[kind] = by_kind.get(kind, 0) + 1

        supports = []
        if c["supporting_ids"]:
            try:
                supports = json.loads(c["supporting_ids"])
            except json.JSONDecodeError:
                supports = []

        direct = c["canonical_id"]
        all_ids = ([direct] if direct else []) + supports
        if not all_ids:
            unattributed.append(dict(c))
            continue

        missing = [x for x in all_ids if x not in papers]
        if missing:
            bad_support.append({**dict(c), "missing": missing})

    return {
        "run_id": run_id,
        "at": datetime.now(UTC).isoformat(),
        "claims_total": len(claims),
        "by_kind": by_kind,
        "unattributed": unattributed,
        "bad_support": bad_support,
        "unattributed_ratio": (len(unattributed) / len(claims)) if claims else 0.0,
    }


def format_md(report: dict) -> str:
    lines = [
        f"# Claim audit — run {report['run_id']}",
        f"_generated {report['at']}_",
        "",
        f"- Total claims: **{report['claims_total']}**",
        f"- Unattributed: **{len(report['unattributed'])}** "
        f"({report['unattributed_ratio'] * 100:.0f}%)",
        f"- With missing supporting papers: **{len(report['bad_support'])}**",
        "",
        "## Claims by kind",
    ]
    for k, n in sorted(report["by_kind"].items(), key=lambda x: -x[1]):
        lines.append(f"- {k}: {n}")

    if report["unattributed"]:
        lines += ["", "## Unattributed claims"]
        for c in report["unattributed"][:20]:
            lines.append(f"- _({c['agent_name']})_ {c['text'][:160]}")
        if len(report["unattributed"]) > 20:
            lines.append(f"- … +{len(report['unattributed']) - 20} more")

    if report["bad_support"]:
        lines += ["", "## Claims with missing supporting papers"]
        for c in report["bad_support"][:20]:
            lines.append(
                f"- _({c['agent_name']})_ {c['text'][:140]} — missing: {c['missing']}"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", required=True)
    p.add_argument("--format", choices=["json", "md"], default="md")
    args = p.parse_args()

    report = audit(args.run_id)

    out = cache_root() / "runs" / f"run-{args.run_id}-claims.md"
    out.write_text(format_md(report))

    if args.format == "json":
        print(json.dumps(report, indent=2, default=str))
    else:
        print(format_md(report))

    if report["unattributed_ratio"] > 0.3:
        sys.exit(2)


if __name__ == "__main__":
    main()
