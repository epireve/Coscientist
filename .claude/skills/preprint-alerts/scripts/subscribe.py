#!/usr/bin/env python3
"""preprint-alerts: add or update a project subscription."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa

VALID_SOURCES = {"arxiv", "biorxiv", "medrxiv"}


def sub_dir(project_id: str) -> Path:
    return cache_root() / "projects" / project_id / "preprint_alerts"


def load_subscription(project_id: str) -> dict:
    p = sub_dir(project_id) / "subscription.json"
    if not p.exists():
        return {"project_id": project_id, "topics": [], "authors": [], "sources": ["arxiv"]}
    return json.loads(p.read_text())


def save_subscription(project_id: str, sub: dict) -> dict:
    d = sub_dir(project_id)
    d.mkdir(parents=True, exist_ok=True)
    sub["updated_at"] = datetime.now(UTC).isoformat()
    (d / "subscription.json").write_text(json.dumps(sub, indent=2))
    return sub


def subscribe(project_id: str, topics: list[str], authors: list[str],
              sources: list[str], merge: bool = True) -> dict:
    bad_sources = [s for s in sources if s not in VALID_SOURCES]
    if bad_sources:
        raise ValueError(f"invalid sources: {bad_sources}. Valid: {sorted(VALID_SOURCES)}")
    if merge:
        existing = load_subscription(project_id)
        topics = sorted(set(existing["topics"]) | set(topics))
        authors = sorted(set(existing["authors"]) | set(authors))
        sources = sorted(set(existing["sources"]) | set(sources))
    sub = {"project_id": project_id, "topics": topics, "authors": authors, "sources": sources}
    return save_subscription(project_id, sub)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--project-id", required=True)
    p.add_argument("--topics", default="", help="Comma-separated topic keywords")
    p.add_argument("--authors", default="", help="Comma-separated author names")
    p.add_argument("--sources", default="arxiv", help="Comma-separated: arxiv,biorxiv,medrxiv")
    p.add_argument("--replace", action="store_true", default=False,
                   help="Replace rather than merge with existing subscription")
    args = p.parse_args()
    topics = [t.strip() for t in args.topics.split(",") if t.strip()]
    authors = [a.strip() for a in args.authors.split(",") if a.strip()]
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    try:
        result = subscribe(args.project_id, topics, authors, sources, merge=not args.replace)
        print(json.dumps(result, indent=2))
    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
