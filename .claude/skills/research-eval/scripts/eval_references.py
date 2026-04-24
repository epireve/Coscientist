#!/usr/bin/env python3
"""Reference quality audit for a deep-research run.

Ports SEEKER's eval_references.py concepts: dangling refs, orphan papers,
DOI resolution rate, source diversity.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root, run_db_path  # noqa: E402
from lib.paper_artifact import PaperArtifact  # noqa: E402


def audit(run_id: str) -> dict:
    db_path = run_db_path(run_id)
    if not db_path.exists():
        raise SystemExit(f"no run db at {db_path}")

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    papers = [r["canonical_id"] for r in con.execute(
        "SELECT canonical_id FROM papers_in_run WHERE run_id=?", (run_id,)
    )]
    citations = con.execute(
        "SELECT from_canonical, to_canonical FROM citations WHERE run_id=?", (run_id,)
    ).fetchall()

    papers_set = set(papers)
    cited_to = {c["to_canonical"] for c in citations if c["to_canonical"]}

    orphans = sorted(papers_set - cited_to)
    dangling = sorted({c["to_canonical"] for c in citations} - papers_set - {None})

    # DOI resolution rate + source diversity
    doi_ok = 0
    sources: list[str] = []
    for cid in papers:
        art = PaperArtifact(cid)
        m = art.load_manifest()
        if m.doi:
            doi_ok += 1
        meta = art.load_metadata()
        if meta:
            sources.extend(meta.discovered_via)

    source_counts = Counter(sources)

    return {
        "run_id": run_id,
        "at": datetime.now(UTC).isoformat(),
        "papers_total": len(papers),
        "orphans": orphans,
        "dangling_refs": dangling,
        "doi_coverage": round(doi_ok / len(papers), 3) if papers else 0.0,
        "source_diversity": dict(source_counts),
    }


def format_md(report: dict) -> str:
    lines = [
        f"# Reference audit — run {report['run_id']}",
        f"_generated {report['at']}_",
        "",
        f"- Papers in run: **{report['papers_total']}**",
        f"- DOI coverage: **{report['doi_coverage'] * 100:.0f}%**",
        f"- Orphan papers (acquired, never cited): **{len(report['orphans'])}**",
        f"- Dangling references (cited, not acquired): **{len(report['dangling_refs'])}**",
        "",
        "## Source diversity",
    ]
    for src, n in sorted(report["source_diversity"].items(), key=lambda x: -x[1]):
        lines.append(f"- {src}: {n}")

    if report["orphans"]:
        lines += ["", "## Orphan papers", *(f"- `{c}`" for c in report["orphans"])]
    if report["dangling_refs"]:
        lines += ["", "## Dangling references", *(f"- `{c}`" for c in report["dangling_refs"])]
    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", required=True)
    p.add_argument("--format", choices=["json", "md"], default="md")
    args = p.parse_args()

    report = audit(args.run_id)

    out = cache_root() / "runs" / f"run-{args.run_id}-eval.md"
    out.write_text(format_md(report))

    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print(format_md(report))

    # Exit non-zero on critical issues
    if report["dangling_refs"] or report["doi_coverage"] < 0.5:
        sys.exit(2)


if __name__ == "__main__":
    main()
