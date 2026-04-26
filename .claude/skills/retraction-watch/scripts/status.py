#!/usr/bin/env python3
"""retraction-watch: show retraction flag status for a project."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402


def _project_db(project_id: str) -> Path:
    return cache_root() / "projects" / project_id / "project.db"


def get_status(project_id: str) -> dict:
    db = _project_db(project_id)
    if not db.exists():
        raise SystemExit(f"no project DB at {db}")
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT canonical_id, retracted, source, detail, checked_at "
            "FROM retraction_flags ORDER BY retracted DESC, checked_at DESC"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        con.close()

    flags = [dict(r) for r in rows]
    retracted = [f for f in flags if f["retracted"]]
    not_retracted = [f for f in flags if not f["retracted"]]
    return {
        "project_id": project_id,
        "total_checked": len(flags),
        "retracted_count": len(retracted),
        "not_retracted_count": len(not_retracted),
        "retracted": retracted,
        "not_retracted": not_retracted,
    }


def _render_table(status: dict) -> str:
    flags = status["retracted"] + status["not_retracted"]
    if not flags:
        return f"No retraction flags for project {status['project_id']}."
    header = f"{'canonical_id':<45} {'retracted':<10} {'source':<20} {'checked_at':<26}"
    rows = [header, "-" * len(header)]
    for f in flags:
        ret = "YES ⚠" if f["retracted"] else "no"
        rows.append(
            f"{f['canonical_id'][:43]:<45} {ret:<10} {f['source'][:18]:<20} {f['checked_at'][:24]:<26}"
        )
    rows.append("")
    rows.append(
        f"Total: {status['total_checked']} checked, "
        f"{status['retracted_count']} retracted, "
        f"{status['not_retracted_count']} clean"
    )
    return "\n".join(rows)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--project-id", required=True)
    p.add_argument("--format", default="json", choices=["json", "table"])
    args = p.parse_args()
    status = get_status(args.project_id)
    if args.format == "table":
        print(_render_table(status))
    else:
        print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
