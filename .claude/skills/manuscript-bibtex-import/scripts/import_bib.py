#!/usr/bin/env python3
"""manuscript-bibtex-import: parse .bib → paper artifacts on disk + project registration.

Reverse of reference-agent export-bibtex. Stdlib-only bibtex parser
sufficient for typical Zotero/Mendeley exports. Handles:
  - @article{key, field = {value}, ...}
  - Multi-line field values
  - Nested braces in values
  - Common escapes (\\&, \\textendash, etc.)
  - Author lists with `and` separator
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

from lib.paper_artifact import (  # noqa: E402
    Manifest, Metadata, PaperArtifact, State,
    canonical_id, extract_arxiv_id,
)
from lib.project import project_db_path  # noqa: E402


# Strip common LaTeX escapes for plain-text fields (title/abstract).
_ESCAPES = {
    r"\&": "&",
    r"\%": "%",
    r"\_": "_",
    r"\#": "#",
    r"\textendash": "–",
    r"\textemdash": "—",
    r"\ldots": "…",
    r"\textquoteleft": "'",
    r"\textquoteright": "'",
    r"\textquotedblleft": "“",
    r"\textquotedblright": "”",
}


def _unbrace(value: str) -> str:
    """Remove outer { } and {{ }} groups from a field value."""
    v = value.strip()
    while len(v) >= 2 and v[0] == "{" and v[-1] == "}":
        v = v[1:-1].strip()
    return v


def _unescape(value: str) -> str:
    out = value
    for k, v in _ESCAPES.items():
        out = out.replace(k, v)
    # Strip leftover braces around individual words: {Word} → Word
    out = re.sub(r"\{([^{}]*)\}", r"\1", out)
    return out.strip()


def _split_authors(raw: str) -> list[str]:
    if not raw:
        return []
    # BibTeX uses "Last, First and Last2, First2" or "First Last and First2 Last2"
    parts = re.split(r"\s+and\s+", raw)
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if "," in p:
            last, first = [s.strip() for s in p.split(",", 1)]
            out.append(f"{first} {last}".strip())
        else:
            out.append(p)
    return out


# Match "@type{key, ... }" — walk the body manually because nested braces
# defeat simple regex.
_ENTRY_HEADER = re.compile(r"@(\w+)\s*\{\s*([^,]+),", re.M)


def parse_bibtex(text: str) -> list[dict]:
    """Return list of entries: {type, key, fields: {name: value}}."""
    entries: list[dict] = []
    pos = 0
    while True:
        m = _ENTRY_HEADER.search(text, pos)
        if not m:
            break
        entry_type = m.group(1).lower()
        entry_key = m.group(2).strip()
        # Find matching closing brace by counting depth from after the
        # opening brace of @type{
        body_start = text.find("{", m.start()) + 1
        depth = 1
        i = body_start
        while i < len(text) and depth > 0:
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        body = text[m.end():i]  # everything after "@type{key,"
        fields = _parse_fields(body)
        entries.append({"type": entry_type, "key": entry_key,
                        "fields": fields})
        pos = i + 1
    return entries


def _parse_fields(body: str) -> dict[str, str]:
    """Parse `name = value, name2 = value2, ...` with brace-aware values."""
    fields: dict[str, str] = {}
    i = 0
    n = len(body)
    while i < n:
        # Skip whitespace + commas
        while i < n and body[i] in " \t\n\r,":
            i += 1
        if i >= n:
            break
        # Read field name up to "="
        name_start = i
        while i < n and body[i] not in "=":
            i += 1
        if i >= n:
            break
        name = body[name_start:i].strip().lower()
        i += 1  # skip "="
        # Skip whitespace
        while i < n and body[i] in " \t\n\r":
            i += 1
        if i >= n:
            break
        # Read value: braced, quoted, or bareword
        if body[i] == "{":
            depth = 1
            i += 1
            value_start = i
            while i < n and depth > 0:
                if body[i] == "{":
                    depth += 1
                elif body[i] == "}":
                    depth -= 1
                if depth == 0:
                    break
                i += 1
            value = body[value_start:i]
            i += 1  # consume closing "}"
        elif body[i] == '"':
            i += 1
            value_start = i
            while i < n and body[i] != '"':
                i += 1
            value = body[value_start:i]
            i += 1
        else:
            value_start = i
            while i < n and body[i] not in ",\n":
                i += 1
            value = body[value_start:i]
        fields[name] = _unescape(_unbrace(value))
    return fields


def _build_canonical(entry: dict) -> str:
    f = entry["fields"]
    title = f.get("title", "")
    year = None
    if f.get("year"):
        m = re.search(r"\d{4}", f["year"])
        if m:
            year = int(m.group())
    authors = _split_authors(f.get("author", ""))
    first_author = authors[0] if authors else None
    doi = f.get("doi") or None
    return canonical_id(
        title=title, year=year,
        first_author=first_author, doi=doi,
    )


def _arxiv_from_url(url: str) -> str | None:
    if not url:
        return None
    return extract_arxiv_id(url)


def _ensure_project(project_id: str) -> None:
    db = project_db_path(project_id)
    if not db.exists():
        raise SystemExit(f"no project DB at {db}")


def _register_in_project(
    project_id: str, cid: str, reading_state: str, art: PaperArtifact,
) -> bool:
    """INSERT into artifact_index + reading_state. Returns True if newly inserted."""
    db = project_db_path(project_id)
    con = sqlite3.connect(db)
    with con:
        cur = con.execute(
            "INSERT OR IGNORE INTO artifact_index "
            "(artifact_id, kind, project_id, state, path, created_at, updated_at) "
            "VALUES (?, 'paper', ?, 'discovered', ?, datetime('now'), datetime('now'))",
            (cid, project_id, str(art.root)),
        )
        inserted = cur.rowcount > 0
        # reading_state per (canonical_id, project_id) — UPSERT
        con.execute(
            "INSERT INTO reading_state "
            "(canonical_id, project_id, state, updated_at) "
            "VALUES (?, ?, ?, datetime('now')) "
            "ON CONFLICT(canonical_id, project_id) "
            "DO UPDATE SET state=excluded.state, updated_at=excluded.updated_at",
            (cid, project_id, reading_state),
        )
    con.close()
    return inserted


def import_entries(
    entries: list[dict], project_id: str,
    reading_state: str = "to-read",
    dry_run: bool = False,
) -> dict:
    """Run the full import. Returns summary dict."""
    summary = {
        "total": len(entries),
        "imported": 0,
        "skipped_duplicate": 0,
        "skipped_thin": 0,
        "errors": [],
        "canonical_ids": [],
    }
    for entry in entries:
        try:
            f = entry["fields"]
            title = f.get("title", "").strip()
            if not title:
                summary["skipped_thin"] += 1
                continue
            cid = _build_canonical(entry)

            if dry_run:
                summary["canonical_ids"].append(cid)
                summary["imported"] += 1
                continue

            # Write artifact
            art = PaperArtifact(cid)
            manifest = art.load_manifest()
            doi = f.get("doi") or None
            arxiv_id = _arxiv_from_url(f.get("url", "")) or _arxiv_from_url(
                f.get("eprint", "")
            ) or f.get("archiveprefix-arxiv-id")
            if doi and not manifest.doi:
                manifest.doi = doi
            if arxiv_id and not manifest.arxiv_id:
                manifest.arxiv_id = arxiv_id
            art.save_manifest(manifest)

            authors = _split_authors(f.get("author", ""))
            year = None
            if f.get("year"):
                m = re.search(r"\d{4}", f["year"])
                if m:
                    year = int(m.group())
            venue = (f.get("journal") or f.get("booktitle")
                     or f.get("publisher") or None)
            keywords = [k.strip() for k in
                         re.split(r"[,;]", f.get("keywords", ""))
                         if k.strip()]
            existing = art.load_metadata()
            md_obj = Metadata(
                title=title,
                authors=authors,
                venue=venue,
                year=year,
                abstract=(f.get("abstract")
                          or (existing.abstract if existing else None)),
                tldr=(existing.tldr if existing else None),
                keywords=keywords or (existing.keywords if existing else []),
                claims=(existing.claims if existing else []),
                discovered_via=list({
                    *(existing.discovered_via if existing else []),
                    "bibtex-import",
                }),
            )
            art.save_metadata(md_obj)

            # Register in project
            inserted = _register_in_project(project_id, cid, reading_state, art)
            if inserted:
                summary["imported"] += 1
                summary["canonical_ids"].append(cid)
            else:
                summary["skipped_duplicate"] += 1
        except Exception as e:
            summary["errors"].append({
                "key": entry.get("key", "?"),
                "error": str(e),
            })
    return summary


def cmd_import(args: argparse.Namespace) -> dict:
    text = Path(args.bib).read_text()
    entries = parse_bibtex(text)
    if args.parse_only:
        return {"entries": entries, "count": len(entries)}
    if not args.dry_run:
        _ensure_project(args.project_id)
    return import_entries(
        entries, args.project_id,
        reading_state=args.reading_state,
        dry_run=args.dry_run,
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bib", required=True, help="Path to .bib file")
    p.add_argument("--project-id", default=None,
                    help="Required unless --parse-only or --dry-run")
    p.add_argument("--reading-state", default="to-read",
                    choices=["to-read", "reading", "read", "annotated",
                              "cited", "skipped"])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--parse-only", action="store_true",
                    help="Print parsed entries; no project DB needed")
    args = p.parse_args()

    if not args.parse_only and not args.dry_run and not args.project_id:
        raise SystemExit(
            "--project-id required (unless --parse-only or --dry-run)"
        )

    out = cmd_import(args)
    sys.stdout.write(json.dumps(out, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()
