#!/usr/bin/env python3
"""project-dashboard: read-only aggregate view across one or all projects."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402


def _list_projects() -> list[Path]:
    base = cache_root() / "projects"
    if not base.exists():
        return []
    return sorted(p for p in base.iterdir() if (p / "project.db").exists())


def _summarize_project(project_dir: Path) -> dict:
    pid = project_dir.name
    db = project_dir / "project.db"
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    proj = con.execute(
        "SELECT name, question, created_at FROM projects WHERE project_id=?",
        (pid,),
    ).fetchone()

    seven_days_ago = (datetime.now(UTC) - timedelta(days=7)).isoformat()

    journal_recent = con.execute(
        "SELECT COUNT(*) FROM journal_entries WHERE project_id=? AND at >= ?",
        (pid, seven_days_ago),
    ).fetchone()[0]
    audit_recent = con.execute(
        "SELECT COUNT(*) FROM manuscript_audit_findings WHERE at >= ?",
        (seven_days_ago,),
    ).fetchone()[0]
    citations_recent = con.execute(
        "SELECT COUNT(*) FROM manuscript_citations WHERE at >= ?",
        (seven_days_ago,),
    ).fetchone()[0]

    reading = {
        row["state"]: row["n"] for row in con.execute(
            "SELECT state, COUNT(*) AS n FROM reading_state WHERE project_id=? "
            "GROUP BY state", (pid,),
        )
    }

    ms_by_state = {
        row["state"]: row["n"] for row in con.execute(
            "SELECT state, COUNT(*) AS n FROM artifact_index "
            "WHERE project_id=? AND kind='manuscript' GROUP BY state", (pid,),
        )
    }

    audit_kinds = {
        row["kind"]: row["n"] for row in con.execute(
            "SELECT kind, COUNT(*) AS n FROM manuscript_audit_findings "
            "GROUP BY kind",
        )
    }

    journal_recent_entries = [dict(r) for r in con.execute(
        "SELECT entry_id, entry_date, body FROM journal_entries WHERE project_id=? "
        "ORDER BY entry_date DESC, entry_id DESC LIMIT 5", (pid,),
    )]
    for e in journal_recent_entries:
        e["body"] = e["body"][:200] + ("..." if len(e["body"]) > 200 else "")

    graph_stats = {
        "papers": con.execute(
            "SELECT COUNT(*) FROM graph_nodes WHERE kind='paper'"
        ).fetchone()[0],
        "concepts": con.execute(
            "SELECT COUNT(*) FROM graph_nodes WHERE kind='concept'"
        ).fetchone()[0],
        "authors": con.execute(
            "SELECT COUNT(*) FROM graph_nodes WHERE kind='author'"
        ).fetchone()[0],
        "edges": con.execute(
            "SELECT COUNT(*) FROM graph_edges"
        ).fetchone()[0],
    }

    con.close()

    return {
        "project_id": pid,
        "name": proj["name"] if proj else pid,
        "question": proj["question"] if proj else None,
        "created_at": proj["created_at"] if proj else None,
        "activity_7d": {
            "journal_entries": journal_recent,
            "audit_findings": audit_recent,
            "citations_recorded": citations_recent,
        },
        "reading_state": reading,
        "manuscripts_by_state": ms_by_state,
        "open_audit_issues_by_kind": audit_kinds,
        "recent_journal_entries": journal_recent_entries,
        "graph": graph_stats,
    }


def _to_markdown(report: dict) -> str:
    lines = [f"# Coscientist dashboard — {report['generated_at']}", ""]
    if not report["projects"]:
        lines.append("_No projects yet._")
        return "\n".join(lines)

    for p in report["projects"]:
        lines += [
            f"## {p['name']} (`{p['project_id']}`)",
            f"_Question: {p['question'] or '(none)'}_  ·  _Created: {p['created_at']}_",
            "",
            f"**Last 7 days**: {p['activity_7d']['journal_entries']} journal entries, "
            f"{p['activity_7d']['audit_findings']} audit findings, "
            f"{p['activity_7d']['citations_recorded']} citations recorded",
            "",
            "**Reading state**:",
        ]
        if p["reading_state"]:
            for state, n in sorted(p["reading_state"].items(), key=lambda x: -x[1]):
                lines.append(f"- {state}: {n}")
        else:
            lines.append("- _(none)_")
        lines += ["", "**Manuscripts by state**:"]
        if p["manuscripts_by_state"]:
            for state, n in sorted(p["manuscripts_by_state"].items(), key=lambda x: -x[1]):
                lines.append(f"- {state}: {n}")
        else:
            lines.append("- _(none)_")
        if p["open_audit_issues_by_kind"]:
            lines += ["", "**Open audit issues**:"]
            for kind, n in sorted(p["open_audit_issues_by_kind"].items(), key=lambda x: -x[1]):
                lines.append(f"- {kind}: {n}")
        g = p["graph"]
        lines += [
            "",
            f"**Graph**: {g['papers']} papers · {g['concepts']} concepts · "
            f"{g['authors']} authors · {g['edges']} edges",
        ]
        if p["recent_journal_entries"]:
            lines += ["", "**Recent journal entries**:"]
            for e in p["recent_journal_entries"]:
                lines.append(f"- _{e['entry_date']}_ ({e['entry_id']}): {e['body'][:120]}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--project-id", default=None)
    p.add_argument("--format", choices=["json", "md"], default="json")
    args = p.parse_args()

    project_dirs = _list_projects()
    if args.project_id:
        target = cache_root() / "projects" / args.project_id
        if not (target / "project.db").exists():
            raise SystemExit(f"no such project: {args.project_id}")
        project_dirs = [target]

    summaries = [_summarize_project(d) for d in project_dirs]
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "project_count": len(summaries),
        "projects": summaries,
    }
    if args.format == "md":
        print(_to_markdown(report))
    else:
        print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
