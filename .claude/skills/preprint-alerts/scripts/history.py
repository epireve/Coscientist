#!/usr/bin/env python3
"""preprint-alerts: list past digests."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa


def sub_dir(project_id: str) -> Path:
    return cache_root() / "projects" / project_id / "preprint_alerts"


def list_history(project_id: str, limit: int = 10) -> list[dict]:
    d = sub_dir(project_id)
    if not d.exists():
        return []
    digest_files = sorted(d.glob("digest_*.json"), reverse=True)[:limit]
    summaries = []
    for f in digest_files:
        try:
            data = json.loads(f.read_text())
            summaries.append({
                "date": data.get("date"),
                "n_candidates": data.get("n_candidates", 0),
                "n_matched": data.get("n_matched", 0),
                "file": str(f),
            })
        except Exception:
            pass
    return summaries


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--project-id", required=True)
    p.add_argument("--limit", type=int, default=10)
    args = p.parse_args()
    result = list_history(args.project_id, args.limit)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
