#!/usr/bin/env python3
"""preprint-alerts: show current subscription."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa


def sub_dir(project_id: str) -> Path:
    return cache_root() / "projects" / project_id / "preprint_alerts"


def get_subscription(project_id: str) -> dict:
    p = sub_dir(project_id) / "subscription.json"
    if not p.exists():
        return {"project_id": project_id, "topics": [], "authors": [], "sources": [],
                "status": "no_subscription"}
    sub = json.loads(p.read_text())
    sub["status"] = "active"
    return sub


def _render_table(sub: dict) -> str:
    lines = [f"Project: {sub['project_id']}  Status: {sub.get('status', '?')}"]
    lines.append(f"Topics:  {', '.join(sub.get('topics', [])) or '(none)'}")
    lines.append(f"Authors: {', '.join(sub.get('authors', [])) or '(none)'}")
    lines.append(f"Sources: {', '.join(sub.get('sources', [])) or '(none)'}")
    if sub.get("updated_at"):
        lines.append(f"Updated: {sub['updated_at'][:19]}")
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--project-id", required=True)
    p.add_argument("--format", default="json", choices=["json", "table"])
    args = p.parse_args()
    sub = get_subscription(args.project_id)
    if args.format == "table":
        print(_render_table(sub))
    else:
        print(json.dumps(sub, indent=2))


if __name__ == "__main__":
    main()
