#!/usr/bin/env python3
"""reference-agent: export a BibTeX file for a manuscript or a deep-research run.

For a manuscript, exports every canonical_id found in manuscript_claims.cited_sources.
For a run, exports every canonical_id in papers_in_run.
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

from lib.cache import cache_root, run_db_path  # noqa: E402


def _bib_escape(s: str) -> str:
    """Minimal BibTeX-safe escape for braces, backslash."""
    if s is None:
        return ""
    return (
        s.replace("\\", "\\textbackslash ")
         .replace("{", "\\{")
         .replace("}", "\\}")
         .replace("\n", " ")
    )


def _bib_key(cid: str) -> str:
    # BibTeX keys should be alphanumeric + underscore
    return re.sub(r"[^A-Za-z0-9_]", "_", cid)


def _load_metadata(cid: str) -> dict:
    path = cache_root() / "papers" / cid / "metadata.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _load_manifest(cid: str) -> dict:
    path = cache_root() / "papers" / cid / "manifest.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def bib_entry(cid: str) -> str:
    meta = _load_metadata(cid)
    manifest = _load_manifest(cid)
    if not meta and not manifest:
        return ""

    title = _bib_escape(meta.get("title") or cid)
    authors = meta.get("authors") or []
    author_str = _bib_escape(" and ".join(authors)) if authors else "Unknown"
    year = meta.get("year") or ""
    venue = _bib_escape(meta.get("venue") or "")
    doi = manifest.get("doi") or ""
    arxiv_id = manifest.get("arxiv_id") or ""

    entry_type = "@article" if venue else "@misc"
    fields = [
        f"  author = {{{author_str}}}",
        f"  title = {{{title}}}",
    ]
    if year:
        fields.append(f"  year = {{{year}}}")
    if venue:
        fields.append(f"  journal = {{{venue}}}")
    if doi:
        fields.append(f"  doi = {{{_bib_escape(doi)}}}")
    if arxiv_id:
        fields.append(f"  note = {{arXiv:{_bib_escape(arxiv_id)}, canonical_id:{cid}}}")
    else:
        fields.append(f"  note = {{canonical_id:{cid}}}")

    return f"{entry_type}{{{_bib_key(cid)},\n" + ",\n".join(fields) + "\n}\n"


def csl_entry(cid: str) -> dict:
    """Build a CSL-JSON entry. Returns {} if no metadata."""
    meta = _load_metadata(cid)
    manifest = _load_manifest(cid)
    if not meta and not manifest:
        return {}

    authors = meta.get("authors") or []
    csl_authors = []
    for a in authors:
        # Heuristic name split — last token is family
        parts = a.strip().split()
        if not parts:
            continue
        if len(parts) == 1:
            csl_authors.append({"family": parts[0]})
        else:
            csl_authors.append({"given": " ".join(parts[:-1]), "family": parts[-1]})

    entry = {
        "id": _bib_key(cid),
        "type": "article-journal" if meta.get("venue") else "article",
        "title": meta.get("title") or cid,
        "author": csl_authors,
        "note": f"canonical_id:{cid}",
    }
    if meta.get("year"):
        entry["issued"] = {"date-parts": [[int(meta["year"])]]}
    if meta.get("venue"):
        entry["container-title"] = meta["venue"]
    if manifest.get("doi"):
        entry["DOI"] = manifest["doi"]
    if manifest.get("arxiv_id"):
        entry["URL"] = f"https://arxiv.org/abs/{manifest['arxiv_id']}"
    if meta.get("abstract"):
        entry["abstract"] = meta["abstract"]
    return entry


def canonical_ids_for_manuscript(mid: str, run_id: str | None) -> list[str]:
    if not run_id:
        # Fall back to scanning manuscript artifact
        path = cache_root() / "manuscripts" / mid / "audit_report.json"
        if not path.exists():
            return []
        report = json.loads(path.read_text())
        cids: set[str] = set()
        for c in report.get("claims", []):
            for s in c.get("cited_sources") or []:
                cids.add(s)
        return sorted(cids)

    db = run_db_path(run_id)
    if not db.exists():
        return []
    con = sqlite3.connect(db)
    rows = con.execute(
        "SELECT cited_sources FROM manuscript_claims WHERE manuscript_id=?", (mid,)
    ).fetchall()
    con.close()
    cids: set[str] = set()
    for (raw,) in rows:
        try:
            cids.update(json.loads(raw) or [])
        except json.JSONDecodeError:
            continue
    return sorted(cids)


def canonical_ids_for_run(run_id: str) -> list[str]:
    db = run_db_path(run_id)
    if not db.exists():
        raise SystemExit(f"no run DB at {db}")
    con = sqlite3.connect(db)
    rows = con.execute(
        "SELECT canonical_id FROM papers_in_run WHERE run_id=?", (run_id,)
    ).fetchall()
    con.close()
    return [r[0] for r in rows]


def main() -> None:
    p = argparse.ArgumentParser()
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--manuscript-id")
    grp.add_argument("--run-id")
    p.add_argument("--out", required=True)
    p.add_argument("--context-run-id", default=None,
                   help="When --manuscript-id is given, also read claims from this run DB")
    p.add_argument("--format", default="bibtex", choices=["bibtex", "csl-json"],
                   help="Output format (default: bibtex)")
    args = p.parse_args()

    if args.manuscript_id:
        cids = canonical_ids_for_manuscript(args.manuscript_id, args.context_run_id)
    else:
        cids = canonical_ids_for_run(args.run_id)

    if not cids:
        raise SystemExit("no canonical_ids to export")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.format == "csl-json":
        entries = [csl_entry(cid) for cid in cids]
        entries = [e for e in entries if e]
        out_path.write_text(json.dumps(entries, indent=2))
        print(f"{len(entries)} CSL-JSON entries → {out_path}")
    else:
        entries = [bib_entry(cid) for cid in cids]
        entries = [e for e in entries if e]
        out_path.write_text("\n".join(entries))
        print(f"{len(entries)} BibTeX entries → {out_path}")


if __name__ == "__main__":
    main()
