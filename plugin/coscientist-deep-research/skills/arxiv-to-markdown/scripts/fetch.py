#!/usr/bin/env python3
"""arxiv-to-markdown: arXiv paper → structured Markdown via arxiv2markdown.

Writes to the paper artifact at ~/.cache/coscientist/papers/<canonical_id>/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

# Make lib importable when running the script directly
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.paper_artifact import (  # noqa: E402
    Metadata,
    PaperArtifact,
    State,
    canonical_id,
    extract_arxiv_id,
)


def normalize_arxiv_id(s: str) -> str:
    aid = extract_arxiv_id(s)
    if not aid:
        raise SystemExit(f"could not parse arXiv id from {s!r}")
    return aid


def run(
    arxiv_input: str,
    cid: str | None,
    remove_refs: bool,
    remove_toc: bool,
    remove_citations: bool,
    sections: list[str] | None,
) -> str:
    try:
        from arxiv2md import ingest_paper
    except ImportError as e:
        raise SystemExit(
            "arxiv2md not installed. Run `uv add arxiv2markdown` first."
        ) from e

    aid = normalize_arxiv_id(arxiv_input)

    html_url = f"https://arxiv.org/html/{aid}"
    ar5iv_url = f"https://ar5iv.org/abs/{aid}"

    result, meta = asyncio.run(
        ingest_paper(
            arxiv_id=aid,
            version=None,
            html_url=html_url,
            ar5iv_url=ar5iv_url,
            remove_refs=remove_refs,
            remove_toc=remove_toc,
            remove_inline_citations=remove_citations,
            section_filter_mode="include" if sections else "all",
            sections=sections or [],
            include_frontmatter=True,
        )
    )

    md: str = result.content or ""

    if not md.strip():
        raise SystemExit("arxiv2markdown returned empty content")

    title = meta.get("title") or f"arxiv:{aid}"
    year = meta.get("year")
    authors = meta.get("authors") or []
    first_author = authors[0] if authors else None
    doi = meta.get("doi")

    if cid is None:
        cid = canonical_id(title=title, year=year, first_author=first_author, doi=doi)

    art = PaperArtifact(cid)

    # content.md
    art.content_path.write_text(md)

    # frontmatter.yaml
    fm_lines = [
        "---",
        f'title: "{title}"',
        f"arxiv_id: {aid}",
    ]
    if doi:
        fm_lines.append(f"doi: {doi}")
    if year:
        fm_lines.append(f"year: {year}")
    if authors:
        fm_lines.append("authors:")
        fm_lines.extend(f"  - {a}" for a in authors)
    fm_lines.append("---")
    art.frontmatter_path.write_text("\n".join(fm_lines) + "\n")

    # metadata.json — merge over any existing
    existing = art.load_metadata()
    md_obj = Metadata(
        title=title,
        authors=authors,
        venue=meta.get("venue") or "arXiv",
        year=year,
        abstract=meta.get("abstract") or (existing.abstract if existing else None),
        tldr=existing.tldr if existing else None,
        keywords=meta.get("keywords") or (existing.keywords if existing else []),
        claims=existing.claims if existing else [],
        discovered_via=(existing.discovered_via if existing else []) + ["arxiv-to-markdown"],
    )
    art.save_metadata(md_obj)

    # manifest — set arxiv_id, advance state, record attempt
    manifest = art.load_manifest()
    manifest.arxiv_id = aid
    if doi:
        manifest.doi = doi
    manifest.state = State.extracted
    art.save_manifest(manifest)
    art.record_source_attempt(
        "arxiv-to-markdown",
        "ok",
        {"chars": len(md), "sections": len(re.findall(r"^##? ", md, re.M))},
    )

    # extraction.log
    art.extraction_log.write_text(
        json.dumps(
            {
                "extractor": "arxiv2markdown",
                "arxiv_id": aid,
                "at": datetime.now(UTC).isoformat(),
                "chars": len(md),
            },
            indent=2,
        )
    )

    return cid


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--arxiv-id", required=True, help="arXiv ID or URL")
    p.add_argument("--canonical-id", default=None, help="Override derived canonical_id")
    p.add_argument("--remove-refs", action="store_true")
    p.add_argument("--remove-toc", action="store_true")
    p.add_argument("--remove-citations", action="store_true")
    p.add_argument("--sections", default=None, help="Comma-separated section titles to keep")
    args = p.parse_args()

    sections = [s.strip() for s in args.sections.split(",")] if args.sections else None
    cid = run(
        arxiv_input=args.arxiv_id,
        cid=args.canonical_id,
        remove_refs=args.remove_refs,
        remove_toc=args.remove_toc,
        remove_citations=args.remove_citations,
        sections=sections,
    )
    print(cid)


if __name__ == "__main__":
    main()
