#!/usr/bin/env python3
"""project-manager: project lifecycle CLI + active-project marker."""
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

from lib import project as project_lib  # noqa: E402
from lib.cache import cache_root  # noqa: E402


def _active_marker_path() -> Path:
    return cache_root() / "active_project.json"


def get_active_project_id() -> str | None:
    """Public API for other skills."""
    p = _active_marker_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        return data.get("project_id")
    except (json.JSONDecodeError, OSError):
        return None


def cmd_init(args: argparse.Namespace) -> None:
    if not args.name.strip():
        raise SystemExit("--name must be non-empty")
    pid = project_lib.create(args.name, args.question, args.description)
    proj = project_lib.get(pid)
    print(json.dumps({
        "project_id": pid,
        "name": proj["name"],
        "created_at": proj["created_at"],
        "path": str(project_lib.project_root(pid)),
    }, indent=2))


def cmd_list(args: argparse.Namespace) -> None:
    projects = project_lib.list_all()
    if not args.include_archived:
        projects = [p for p in projects if not p.get("archived_at")]
    print(json.dumps({
        "projects": projects,
        "total": len(projects),
        "active_project_id": get_active_project_id(),
    }, indent=2))


def cmd_activate(args: argparse.Namespace) -> None:
    proj = project_lib.get(args.project_id)
    if proj is None:
        raise SystemExit(f"project {args.project_id!r} not found")
    if proj.get("archived_at"):
        raise SystemExit(f"project {args.project_id!r} is archived; unarchive first")
    p = _active_marker_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "project_id": args.project_id,
        "activated_at": datetime.now(UTC).isoformat(),
    }, indent=2))
    print(json.dumps({
        "project_id": args.project_id,
        "name": proj["name"],
        "active": True,
    }, indent=2))


def cmd_current(args: argparse.Namespace) -> None:
    pid = get_active_project_id()
    if pid is None:
        print(json.dumps({"active_project_id": None, "message": "no active project"}, indent=2))
        return
    proj = project_lib.get(pid)
    print(json.dumps({
        "project_id": pid,
        "name": proj["name"] if proj else "(missing)",
        "exists": proj is not None,
    }, indent=2))


def cmd_deactivate(args: argparse.Namespace) -> None:
    p = _active_marker_path()
    was_active = None
    if p.exists():
        try:
            was_active = json.loads(p.read_text()).get("project_id")
        except (json.JSONDecodeError, OSError):
            pass
        p.unlink()
    print(json.dumps({
        "deactivated": True,
        "previous_project_id": was_active,
    }, indent=2))


def _set_archived_at(project_id: str, value: str | None) -> None:
    proj = project_lib.get(project_id)
    if proj is None:
        raise SystemExit(f"project {project_id!r} not found")
    db = project_lib.project_db_path(project_id)
    con = sqlite3.connect(db)
    with con:
        con.execute(
            "UPDATE projects SET archived_at = ? WHERE project_id = ?",
            (value, project_id),
        )
    con.close()


def cmd_archive(args: argparse.Namespace) -> None:
    proj = project_lib.get(args.project_id)
    if proj is None:
        raise SystemExit(f"project {args.project_id!r} not found")
    if proj.get("archived_at"):
        raise SystemExit(f"project {args.project_id!r} already archived")
    now = datetime.now(UTC).isoformat()
    _set_archived_at(args.project_id, now)
    # Auto-deactivate if archiving the active project
    active = get_active_project_id()
    deactivated = False
    if active == args.project_id:
        _active_marker_path().unlink(missing_ok=True)
        deactivated = True
    print(json.dumps({
        "project_id": args.project_id,
        "archived_at": now,
        "deactivated": deactivated,
    }, indent=2))


def cmd_unarchive(args: argparse.Namespace) -> None:
    proj = project_lib.get(args.project_id)
    if proj is None:
        raise SystemExit(f"project {args.project_id!r} not found")
    if not proj.get("archived_at"):
        raise SystemExit(f"project {args.project_id!r} is not archived")
    _set_archived_at(args.project_id, None)
    print(json.dumps({
        "project_id": args.project_id,
        "archived_at": None,
    }, indent=2))


def cmd_status(args: argparse.Namespace) -> None:
    proj = project_lib.get(args.project_id)
    if proj is None:
        raise SystemExit(f"project {args.project_id!r} not found")
    db = project_lib.project_db_path(args.project_id)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    counts = {}
    for kind in ("paper", "manuscript", "experiment", "dataset", "figure",
                 "review", "grant", "negative-result"):
        try:
            row = con.execute(
                "SELECT COUNT(*) AS c FROM artifact_index WHERE kind = ? AND project_id = ?",
                (kind, args.project_id),
            ).fetchone()
            counts[kind] = row["c"] if row else 0
        except sqlite3.OperationalError:
            counts[kind] = 0
    con.close()
    print(json.dumps({
        "project_id": args.project_id,
        "name": proj["name"],
        "question": proj.get("question"),
        "description": proj.get("description"),
        "created_at": proj.get("created_at"),
        "archived_at": proj.get("archived_at"),
        "is_active": (get_active_project_id() == args.project_id),
        "artifact_counts": counts,
        "path": str(project_lib.project_root(args.project_id)),
    }, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Project lifecycle CLI.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init")
    pi.add_argument("--name", required=True)
    pi.add_argument("--question", default=None)
    pi.add_argument("--description", default=None)
    pi.set_defaults(func=cmd_init)

    pl = sub.add_parser("list")
    pl.add_argument("--include-archived", action="store_true", default=False)
    pl.set_defaults(func=cmd_list)

    pa = sub.add_parser("activate")
    pa.add_argument("--project-id", required=True)
    pa.set_defaults(func=cmd_activate)

    pc = sub.add_parser("current")
    pc.set_defaults(func=cmd_current)

    pd = sub.add_parser("deactivate")
    pd.set_defaults(func=cmd_deactivate)

    par = sub.add_parser("archive")
    par.add_argument("--project-id", required=True)
    par.set_defaults(func=cmd_archive)

    pun = sub.add_parser("unarchive")
    pun.add_argument("--project-id", required=True)
    pun.set_defaults(func=cmd_unarchive)

    ps = sub.add_parser("status")
    ps.add_argument("--project-id", required=True)
    ps.set_defaults(func=cmd_status)

    args = p.parse_args()
    try:
        args.func(args)
    except (FileNotFoundError, ValueError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
