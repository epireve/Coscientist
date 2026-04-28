#!/usr/bin/env python3
"""paper-discovery: dedup MCP results, write artifact stubs, return ranked shortlist.

Input JSON format (a flat list):
[
  {
    "source": "consensus|paper-search|academic|semantic-scholar",
    "title": "...",
    "authors": ["...", ...],
    "year": 2024,
    "abstract": "...",
    "tldr": "...",             # optional
    "doi": "10.1234/...",      # optional
    "arxiv_id": "2401.12345",  # optional
    "s2_id": "...",            # optional
    "pmid": "...",             # optional
    "venue": "...",            # optional
    "citation_count": 42,       # optional
    "claims": [{"text": "...", "section": "..."}]  # optional (Consensus)
  },
  ...
]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import run_db_path  # noqa: E402
from lib.paper_artifact import (  # noqa: E402
    Metadata,
    PaperArtifact,
    canonical_id,
)


def _norm_title(title: str) -> str:
    t = re.sub(r"[^a-z0-9]+", "", (title or "").lower())
    return t[:80]


def _key(entry: dict) -> tuple[str, str]:
    if entry.get("doi"):
        return ("doi", entry["doi"].lower())
    if entry.get("arxiv_id"):
        return ("arxiv", entry["arxiv_id"].lower())
    return ("title", _norm_title(entry.get("title", "")))


def merge_entries(entries: list[dict]) -> list[dict]:
    """Merge by DOI → arXiv → normalized title."""
    by_key: dict[tuple[str, str], dict] = {}
    for e in entries:
        k = _key(e)
        if k in by_key:
            cur = by_key[k]
            cur.setdefault("discovered_via", []).append(e["source"])
            # Prefer richer fields
            for field in ("abstract", "tldr", "doi", "arxiv_id", "pmid", "s2_id", "venue"):
                if not cur.get(field) and e.get(field):
                    cur[field] = e[field]
            if (e.get("citation_count") or 0) > (cur.get("citation_count") or 0):
                cur["citation_count"] = e["citation_count"]
            # Merge claims
            cur.setdefault("claims", []).extend(e.get("claims") or [])
        else:
            new = dict(e)
            new["discovered_via"] = [e["source"]]
            by_key[k] = new
    return list(by_key.values())


def rank(entries: list[dict]) -> list[dict]:
    def score(e: dict) -> tuple:
        return (
            -len(set(e.get("discovered_via", []))),
            -(e.get("citation_count") or 0),
            -(e.get("year") or 0),
        )

    return sorted(entries, key=score)


def write_stubs(entries: list[dict], run_id: str | None) -> list[str]:
    cids: list[str] = []

    for e in entries:
        first_author = (e.get("authors") or [None])[0]
        cid = canonical_id(
            title=e.get("title", ""),
            year=e.get("year"),
            first_author=first_author,
            doi=e.get("doi"),
        )
        art = PaperArtifact(cid)

        manifest = art.load_manifest()
        manifest.doi = manifest.doi or e.get("doi")
        manifest.arxiv_id = manifest.arxiv_id or e.get("arxiv_id")
        manifest.pmid = manifest.pmid or e.get("pmid")
        manifest.s2_id = manifest.s2_id or e.get("s2_id")
        art.save_manifest(manifest)

        existing = art.load_metadata()
        merged_claims = (existing.claims if existing else []) + (e.get("claims") or [])
        merged_sources = list(
            dict.fromkeys(
                (existing.discovered_via if existing else [])
                + e.get("discovered_via", [])
            )
        )
        art.save_metadata(
            Metadata(
                title=e.get("title") or (existing.title if existing else "untitled"),
                authors=e.get("authors") or (existing.authors if existing else []),
                venue=e.get("venue") or (existing.venue if existing else None),
                year=e.get("year") or (existing.year if existing else None),
                abstract=e.get("abstract") or (existing.abstract if existing else None),
                tldr=e.get("tldr") or (existing.tldr if existing else None),
                claims=merged_claims,
                citation_count=e.get("citation_count")
                or (existing.citation_count if existing else None),
                discovered_via=merged_sources,
            )
        )
        cids.append(cid)

    if run_id:
        # Build cid → (year, citation_count) lookup for cites_per_year
        # computation. Uses post-dedup entries so we get the merged citation
        # count, not the first-seen value.
        from datetime import UTC, datetime
        cur_year = datetime.now(UTC).year
        cid_meta: dict[str, tuple[int | None, int | None]] = {}
        for e in entries:
            doi = (e.get("doi") or "").lower()
            cid_e = canonical_id(
                title=e.get("title") or "",
                first_author=(
                    e.get("authors")[0].split()[-1]
                    if e.get("authors") else "anon"
                ),
                year=e.get("year"),
                doi=doi or None,
            )
            cid_meta[cid_e] = (e.get("year"), e.get("citation_count"))

        db = run_db_path(run_id)
        if db.exists():
            con = sqlite3.connect(db)
            with con:
                for cid in cids:
                    year, cites = cid_meta.get(cid, (None, None))
                    cpy: float | None = None
                    if year and cites:
                        age = max(1, cur_year - int(year))
                        cpy = float(cites) / age
                    # UPSERT — insert with harvest_count=1 OR increment
                    # existing row's harvest_count + refresh cites_per_year.
                    # Repeat-hit signal: paper surfaced by multiple persona
                    # harvests is a foundational-paper proxy.
                    con.execute(
                        "INSERT INTO papers_in_run "
                        "(run_id, canonical_id, added_in_phase, role, "
                        " harvest_count, cites_per_year) "
                        "VALUES (?, ?, ?, ?, 1, ?) "
                        "ON CONFLICT(run_id, canonical_id) DO UPDATE SET "
                        "  harvest_count = harvest_count + 1, "
                        "  cites_per_year = COALESCE(excluded.cites_per_year, "
                        "                            cites_per_year)",
                        (run_id, cid, "social", "seed", cpy),
                    )
            con.close()

    return cids


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, help="JSON file with raw MCP results")
    p.add_argument("--query", required=True, help="Original research question")
    p.add_argument("--run-id", default=None)
    p.add_argument("--out", required=True, help="Where to write the ranked shortlist")
    args = p.parse_args()

    raw = json.loads(Path(args.input).read_text())
    merged = merge_entries(raw)
    ranked = rank(merged)
    cids = write_stubs(ranked, args.run_id)

    shortlist = []
    for cid, e in zip(cids, ranked, strict=True):
        shortlist.append(
            {
                "canonical_id": cid,
                "title": e.get("title"),
                "authors": e.get("authors"),
                "year": e.get("year"),
                "doi": e.get("doi"),
                "arxiv_id": e.get("arxiv_id"),
                "sources": sorted(set(e.get("discovered_via", []))),
                "citation_count": e.get("citation_count"),
                "tldr": e.get("tldr"),
            }
        )
    Path(args.out).write_text(json.dumps(shortlist, indent=2))
    print(f"{len(shortlist)} unique papers → {args.out}")


if __name__ == "__main__":
    main()
