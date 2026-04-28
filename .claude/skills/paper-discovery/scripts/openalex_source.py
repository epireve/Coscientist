#!/usr/bin/env python3
"""v0.145 — OpenAlex producer for paper-discovery merge.py.

Calls lib.openalex_client.OpenAlexClient.search_works, maps each
result into the merge.py input format, writes JSON to stdout (or
the path given via --out).

Used as the 5th source after Consensus / S2 / paper-search /
academic. Caller pipes output into merge.py:

    python openalex_source.py --query "transformer attention" \
      --per-page 25 > /tmp/oa.json
    cat /tmp/oa.json /tmp/consensus.json /tmp/s2.json | merge.py ...

Or use --out + chain via shell.

Polite-pool (free) by default. Set $OPENALEX_API_KEY to upgrade.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.openalex_client import OpenAlexClient  # noqa: E402


def _map_work(work: dict) -> dict:
    """OpenAlex work record → merge.py input shape."""
    # Authors
    authors: list[str] = []
    for ship in (work.get("authorships") or []):
        a = (ship.get("author") or {}).get("display_name")
        if a:
            authors.append(a)

    # OA URL
    oa_url = OpenAlexClient.extract_oa_url(work)

    # Abstract
    abstract = OpenAlexClient.reconstruct_abstract(
        work.get("abstract_inverted_index"),
    )

    # IDs
    doi = work.get("doi")
    if doi and doi.startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/"):]

    oa_id = work.get("id") or ""
    if oa_id.startswith("https://openalex.org/"):
        oa_id = oa_id[len("https://openalex.org/"):]

    # arXiv detection — OpenAlex sometimes records it in
    # primary_location.landing_page_url
    arxiv_id = None
    primary = work.get("primary_location") or {}
    landing = primary.get("landing_page_url") or ""
    if "arxiv.org/abs/" in landing:
        arxiv_id = landing.rsplit("/", 1)[-1].split("v")[0]

    # PMID detection — in `ids` map
    ids = work.get("ids") or {}
    pmid = None
    pmid_url = ids.get("pmid")
    if pmid_url and "ncbi.nlm.nih.gov/pubmed/" in pmid_url:
        pmid = pmid_url.rsplit("/", 1)[-1]

    # Venue
    venue = None
    source = primary.get("source") or {}
    if source.get("display_name"):
        venue = source["display_name"]

    out: dict = {
        "source": "openalex",
        "title": work.get("title") or work.get("display_name") or "",
        "authors": authors,
        "year": work.get("publication_year"),
        "abstract": abstract,
        "doi": doi,
        "arxiv_id": arxiv_id,
        "pmid": pmid,
        "openalex_id": oa_id,
        "venue": venue,
        "citation_count": work.get("cited_by_count") or 0,
        "oa_url": oa_url,  # consumed by paper-acquire later
    }
    # Topics → claim-style for downstream concept ingest
    topics = OpenAlexClient.extract_topics(work, min_score=0.5)
    if topics:
        out["topics"] = [
            {"id": t["id"], "name": t["display_name"],
             "score": t["score"], "level": t["level"]}
            for t in topics
        ]
    return out


def search_to_records(
    query: str,
    *,
    per_page: int = 25,
    page: int = 1,
    filters: dict | None = None,
    client: OpenAlexClient | None = None,
) -> list[dict]:
    """Hit OpenAlex search + map to merge.py records.

    On error, returns empty list (errors logged via trace if env set).
    """
    cli = client or OpenAlexClient()
    res = cli.search_works(
        query, per_page=per_page, page=page, filters=filters,
    )
    if isinstance(res, dict) and "error" in res:
        return []
    works = (res or {}).get("results") or []
    return [_map_work(w) for w in works]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="openalex_source")
    p.add_argument("--query", required=True)
    p.add_argument("--per-page", type=int, default=25)
    p.add_argument("--page", type=int, default=1)
    p.add_argument(
        "--filter", action="append", default=[],
        help="Repeatable: --filter is_oa:true --filter "
             "from_publication_date:2024-01-01",
    )
    p.add_argument(
        "--out", default=None,
        help="Output path (default stdout)",
    )
    args = p.parse_args(argv)

    filters = {}
    for f in args.filter:
        if ":" in f:
            k, v = f.split(":", 1)
            filters[k] = v

    records = search_to_records(
        args.query, per_page=args.per_page, page=args.page,
        filters=filters or None,
    )

    payload = json.dumps(records, indent=2)
    if args.out:
        Path(args.out).write_text(payload)
        sys.stdout.write(
            f"wrote {len(records)} records to {args.out}\n",
        )
    else:
        sys.stdout.write(payload + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
