#!/usr/bin/env python3
"""v0.146 — Tier 0 OA fallback: resolve PDF via OpenAlex.

OpenAlex tracks Unpaywall + 50+ OA repositories. When a paper
has any OA copy, OpenAlex's `open_access.oa_url` (or
`primary_location.pdf_url`) returns it directly. Saves one hop
in the OA fallback chain.

CLI:
    uv run python oa_via_openalex.py --canonical-id <cid>
    # → prints oa_url to stdout (exit 0) or "no OA URL" (exit 1)

Lookup keys (in priority order):
    1. paper artifact's manifest.json doi → OpenAlex by DOI
    2. paper artifact's manifest.json arxiv_id → OpenAlex search
    3. paper artifact's openalex_id field (if scout populated it)
    4. paper artifact's title → search

Pure stdlib via lib.openalex_client. Best-effort — falls
through silently when no OA URL.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import paper_dir  # noqa: E402
from lib.openalex_client import OpenAlexClient  # noqa: E402


def resolve_oa_url(
    canonical_id: str,
    client: OpenAlexClient | None = None,
) -> dict:
    """Look up paper in OpenAlex; return OA URL if any.

    Returns: {
      "ok": bool,
      "oa_url": str | None,
      "openalex_id": str | None,
      "lookup_via": "doi" | "arxiv" | "openalex_id" | "title" | None,
      "error": str | None,
    }
    """
    pdir = paper_dir(canonical_id)
    manifest_path = pdir / "manifest.json"
    if not manifest_path.exists():
        return {
            "ok": False,
            "oa_url": None,
            "openalex_id": None,
            "lookup_via": None,
            "error": f"no manifest at {manifest_path}",
        }
    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as e:
        return {
            "ok": False, "oa_url": None,
            "openalex_id": None, "lookup_via": None,
            "error": f"manifest JSON invalid: {e}",
        }

    cli = client or OpenAlexClient()

    # 1. DOI lookup
    doi = manifest.get("doi")
    if doi:
        work = cli.get_work(doi)
        if "error" not in work:
            url = OpenAlexClient.extract_oa_url(work)
            oa_id = (work.get("id") or "").rsplit("/", 1)[-1]
            return {
                "ok": url is not None,
                "oa_url": url,
                "openalex_id": oa_id or None,
                "lookup_via": "doi",
                "error": None if url else "no OA URL in record",
            }

    # 2. arXiv ID
    arxiv = manifest.get("arxiv_id")
    if arxiv:
        # OpenAlex doesn't lookup arXiv directly; search
        res = cli.search_works(arxiv, per_page=3)
        if "error" not in res:
            for w in res.get("results", []):
                landing = (w.get("primary_location") or {}).get(
                    "landing_page_url", "",
                )
                if arxiv in (landing or ""):
                    url = OpenAlexClient.extract_oa_url(w)
                    oa_id = (w.get("id") or "").rsplit("/", 1)[-1]
                    return {
                        "ok": url is not None,
                        "oa_url": url,
                        "openalex_id": oa_id or None,
                        "lookup_via": "arxiv",
                        "error": None if url else "no OA URL",
                    }

    # 3. Direct OpenAlex ID (set by scout if available)
    oa_id = manifest.get("openalex_id")
    if oa_id:
        work = cli.get_work(oa_id)
        if "error" not in work:
            url = OpenAlexClient.extract_oa_url(work)
            return {
                "ok": url is not None,
                "oa_url": url,
                "openalex_id": oa_id,
                "lookup_via": "openalex_id",
                "error": None if url else "no OA URL",
            }

    # 4. Title fallback (lower confidence)
    title = manifest.get("title")
    if title:
        res = cli.search_works(title, per_page=3)
        if "error" not in res:
            results = res.get("results", [])
            if results:
                # Take first hit as best guess
                w = results[0]
                url = OpenAlexClient.extract_oa_url(w)
                oa_id = (w.get("id") or "").rsplit("/", 1)[-1]
                return {
                    "ok": url is not None,
                    "oa_url": url,
                    "openalex_id": oa_id or None,
                    "lookup_via": "title",
                    "error": None if url else "no OA URL",
                }

    return {
        "ok": False, "oa_url": None,
        "openalex_id": None, "lookup_via": None,
        "error": "no lookup key matched",
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="oa_via_openalex")
    p.add_argument("--canonical-id", required=True)
    p.add_argument("--format", choices=("text", "json"),
                    default="text")
    args = p.parse_args(argv)

    res = resolve_oa_url(args.canonical_id)
    if args.format == "json":
        sys.stdout.write(json.dumps(res, indent=2) + "\n")
    else:
        if res["ok"]:
            sys.stdout.write(res["oa_url"] + "\n")
        else:
            sys.stderr.write(
                f"no OA URL: {res.get('error')}\n",
            )
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
