#!/usr/bin/env python3
"""retraction-watch: write retraction alerts and research-journal entry.

Reads retraction_flags WHERE retracted=1, writes retraction_alerts.json
to the project dir, and optionally appends a research-journal entry.
Idempotent — overwrites existing alert file with current DB state.
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

from lib.cache import cache_root  # noqa: E402


def _project_db(project_id: str) -> Path:
    return cache_root() / "projects" / project_id / "project.db"


def _retracted_papers(project_id: str) -> list[dict]:
    db = _project_db(project_id)
    if not db.exists():
        raise SystemExit(f"no project DB at {db}")
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT canonical_id, source, detail, checked_at "
            "FROM retraction_flags WHERE retracted=1 ORDER BY checked_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def _write_alerts(project_id: str, retracted: list[dict], output: Path) -> dict:
    alert = {
        "project_id": project_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "retracted_count": len(retracted),
        "retracted": retracted,
    }
    output.write_text(json.dumps(alert, indent=2))
    return alert


def _journal_body(project_id: str, retracted: list[dict]) -> str:
    lines = [
        f"Retraction-watch scan for project {project_id}: "
        f"{len(retracted)} retracted paper(s) found.",
        "",
    ]
    for r in retracted:
        detail = r.get("detail") or "no detail available"
        lines.append(f"- {r['canonical_id']} (source: {r['source']}): {detail}")
    if not retracted:
        lines.append("No retractions found among cited papers.")
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--project-id", required=True)
    p.add_argument("--output", default=None,
                   help="Path for retraction_alerts.json (default: project dir)")
    p.add_argument("--no-journal", action="store_true", default=False,
                   help="Skip writing a research-journal entry")
    args = p.parse_args()

    retracted = _retracted_papers(args.project_id)
    project_dir = cache_root() / "projects" / args.project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    output_path = Path(args.output) if args.output else project_dir / "retraction_alerts.json"
    alert = _write_alerts(args.project_id, retracted, output_path)

    result = {
        "alert_path": str(output_path),
        "retracted_count": len(retracted),
        "retracted": retracted,
    }

    if not args.no_journal and retracted:
        # Attempt to write journal entry via add_entry.py
        journal_script = (
            _REPO_ROOT / ".claude/skills/research-journal/scripts/add_entry.py"
        )
        if journal_script.exists():
            import subprocess
            body = _journal_body(args.project_id, retracted)
            proc = subprocess.run(
                [
                    sys.executable, str(journal_script),
                    "--project-id", args.project_id,
                    "--text", body,
                    "--tags", "retraction,alert",
                ],
                capture_output=True, text=True,
            )
            result["journal_entry_written"] = proc.returncode == 0
            if proc.returncode != 0:
                result["journal_error"] = proc.stderr.strip()
        else:
            result["journal_entry_written"] = False
            result["journal_note"] = "research-journal script not found; skipped"
    else:
        result["journal_entry_written"] = False

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
