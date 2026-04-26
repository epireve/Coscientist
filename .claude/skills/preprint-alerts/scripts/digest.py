#!/usr/bin/env python3
"""preprint-alerts: filter papers and write digest."""
from __future__ import annotations
import argparse, json, sys
from datetime import UTC, datetime, date
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa


def sub_dir(project_id: str) -> Path:
    return cache_root() / "projects" / project_id / "preprint_alerts"


def load_subscription(project_id: str) -> dict:
    p = sub_dir(project_id) / "subscription.json"
    if not p.exists():
        return {"project_id": project_id, "topics": [], "authors": [], "sources": ["arxiv"]}
    return json.loads(p.read_text())


def _matches_topic(paper: dict, topics: list[str]) -> list[str]:
    text = (paper.get("title", "") + " " + paper.get("abstract", "")).lower()
    return [t for t in topics if t.lower() in text]


def _matches_author(paper: dict, followed: list[str]) -> list[str]:
    paper_authors = [a.lower() for a in paper.get("authors", [])]
    matched = []
    for fa in followed:
        fa_lower = fa.lower()
        if any(fa_lower in pa for pa in paper_authors):
            matched.append(fa)
    return matched


def filter_papers(papers: list[dict], subscription: dict) -> list[dict]:
    topics = subscription.get("topics", [])
    authors = subscription.get("authors", [])
    sources = subscription.get("sources", ["arxiv"])
    matches = []
    for paper in papers:
        if paper.get("source") and paper["source"] not in sources:
            continue
        matched_topics = _matches_topic(paper, topics)
        matched_authors = _matches_author(paper, authors)
        if matched_topics or matched_authors:
            entry = dict(paper)
            entry["matched_topics"] = matched_topics
            entry["matched_authors"] = matched_authors
            matches.append(entry)
    return matches


def write_digest(project_id: str, papers: list[dict],
                 digest_date: str | None = None) -> dict:
    if digest_date is None:
        digest_date = date.today().isoformat()
    sub = load_subscription(project_id)
    matches = filter_papers(papers, sub)
    digest = {
        "project_id": project_id,
        "date": digest_date,
        "generated_at": datetime.now(UTC).isoformat(),
        "n_candidates": len(papers),
        "n_matched": len(matches),
        "topics": sub.get("topics", []),
        "authors": sub.get("authors", []),
        "matches": matches,
    }
    d = sub_dir(project_id)
    d.mkdir(parents=True, exist_ok=True)
    digest_path = d / f"digest_{digest_date}.json"
    digest_path.write_text(json.dumps(digest, indent=2))
    return digest


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--project-id", required=True)
    p.add_argument("--input", required=True, help="JSON array of papers")
    p.add_argument("--date", default=None, help="YYYY-MM-DD override")
    args = p.parse_args()

    papers = json.loads(Path(args.input).read_text())
    result = write_digest(args.project_id, papers, args.date)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
