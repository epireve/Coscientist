#!/usr/bin/env python3
"""research-journal: append a daily lab-notebook entry."""

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

from lib.cache import cache_root  # noqa: E402


def _project_db(project_id: str) -> Path:
    p = cache_root() / "projects" / project_id / "project.db"
    if not p.exists():
        raise SystemExit(f"no project DB at {p}")
    return p


def _csv(s: str | None) -> list[str]:
    if not s:
        return []
    return [t.strip() for t in s.split(",") if t.strip()]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--project-id", required=True)
    p.add_argument("--text", default=None, help="Inline body (else read stdin)")
    p.add_argument("--date", default=None, help="YYYY-MM-DD (default: today UTC)")
    p.add_argument("--tags", default=None, help="comma-separated tags")
    p.add_argument("--link-papers", default=None)
    p.add_argument("--link-manuscripts", default=None)
    p.add_argument("--link-runs", default=None)
    p.add_argument("--link-experiments", default=None)
    args = p.parse_args()

    body = args.text if args.text is not None else sys.stdin.read()
    body = body.strip()
    if not body:
        raise SystemExit("empty body")

    entry_date = args.date or datetime.now(UTC).strftime("%Y-%m-%d")
    now = datetime.now(UTC).isoformat()
    tags = _csv(args.tags)
    links = {
        "papers": _csv(args.link_papers),
        "manuscripts": _csv(args.link_manuscripts),
        "runs": _csv(args.link_runs),
        "experiments": _csv(args.link_experiments),
    }

    db = _project_db(args.project_id)
    con = sqlite3.connect(db)
    with con:
        cur = con.execute(
            "INSERT INTO journal_entries "
            "(project_id, entry_date, body, tags, links, at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (args.project_id, entry_date, body,
             json.dumps(tags), json.dumps(links), now),
        )
        entry_id = cur.lastrowid
    con.close()

    # Mirror to disk for greppability
    journal_dir = cache_root() / "projects" / args.project_id / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    out = journal_dir / f"{entry_id}.md"
    fm_lines = [
        "---",
        f"entry_id: {entry_id}",
        f"entry_date: {entry_date}",
        f"at: {now}",
    ]
    if tags:
        fm_lines.append(f"tags: [{', '.join(tags)}]")
    for k, v in links.items():
        if v:
            fm_lines.append(f"linked_{k}: [{', '.join(v)}]")
    fm_lines.append("---")
    out.write_text("\n".join(fm_lines) + "\n\n" + body + "\n")

    print(json.dumps({"entry_id": entry_id, "path": str(out)}))


if __name__ == "__main__":
    main()
