#!/usr/bin/env python3
"""manuscript-ingest: copy a markdown draft into a manuscript artifact.

When --project-id is given, this also:
- Creates a manuscript node in the project graph
- Parses inline citations from the source → manuscript_citations
- Parses the bibliography section (v0.9) → manuscript_references
- Creates placeholder paper nodes + `cites` edges from the manuscript

No LLM calls, no network. Pure filesystem + SQLite.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.artifact import ArtifactKind, ManuscriptArtifact  # noqa: E402
from lib.cache import cache_root  # noqa: E402


# Inline citation patterns in academic markdown/LaTeX drafts
# Captures the *key* (group 1) for pandoc/bibtex-style, or the full match for fallback
CITATION_PATTERNS = [
    # \cite{key1,key2,...}  or \citep / \citet / \citeauthor
    (re.compile(r"\\cite[a-z]*\{([^}]+)\}"), "latex"),
    # pandoc [@key] or [@key; @key2]
    (re.compile(r"\[@([^;\]\s]+)(?:\s*;\s*@([^;\]\s]+))*\]"), "pandoc"),
    # numeric [1], [1,2,3]
    (re.compile(r"\[(\d+(?:\s*[,-]\s*\d+)*)\]"), "numeric"),
    # (Author, Year) / (Author et al., Year)
    (re.compile(r"\(([A-Z][a-zA-Z]+(?:\s+et\s+al\.?)?,?\s+\d{4}[a-z]?)\)"), "author-year"),
]


BIB_HEADERS = re.compile(
    r"^#{1,3}\s*(References|Bibliography|Works\s+Cited|Literature\s+Cited)\b",
    re.IGNORECASE | re.MULTILINE,
)
BIB_NUMBERED = re.compile(r"^\s*(?:\[(\d+)\]|\((\d+)\)|(\d+)\.)\s+(.+)$")
BIB_BULLET = re.compile(r"^\s*[-*]\s+(.+)$")
BIBTEX_ENTRY = re.compile(
    r"@(?:article|inproceedings|book|misc|phdthesis|mastersthesis|techreport|"
    r"incollection|conference|proceedings|unpublished|manual)\s*\{([^,]+),",
    re.IGNORECASE,
)
# v0.23: pandoc-style "@key prose ..." (no curly braces). The fourth common
# bib format. Distinguish from BibTeX-block lines (which start with
# @<entry-type>{ and were already handled). The pandoc form has the key
# directly after @ and is followed by whitespace + prose, not a brace.
BIB_PANDOC_KEY = re.compile(
    r"^@([A-Za-z][A-Za-z0-9._:-]*)\s+(\S.*)$"
)
DOI_RX = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)\b")
YEAR_RX = re.compile(r"\b(19\d{2}|20\d{2})\b")
# Heuristic: infer a BibTeX-style key from "Author (Year)" or "Author, Year"
KEY_AUTHOR_YEAR = re.compile(r"^([A-Z][A-Za-z-]+).*?(\b(?:19|20)\d{2}\b)")


def extract_bibliography(text: str) -> list[dict]:
    """Extract bibliography entries from a markdown manuscript's reference list.

    Handles three common styles:
    1. Numbered: `[1] Smith, J. (2020). Title...`
    2. Markdown bullets: `- Smith, J. (2020). Title...`
    3. BibTeX blocks: `@article{smith2020, ...}`

    Returns a list of dicts: {entry_key, raw_text, ordinal, doi, year, title}.
    If no bibliography section is found, returns [].
    """
    m = BIB_HEADERS.search(text)
    if not m:
        return []
    bib_text = text[m.end():]

    # Chop at the next top-level header if any (e.g., an appendix after refs)
    next_hdr = re.search(r"^\s*#{1,3}\s+\w+", bib_text, re.MULTILINE)
    if next_hdr and next_hdr.start() > 10:
        bib_text = bib_text[:next_hdr.start()]

    entries: list[dict] = []

    # Try BibTeX-style blocks first (unambiguous)
    bibtex_hits = list(BIBTEX_ENTRY.finditer(bib_text))
    if bibtex_hits:
        for i, hit in enumerate(bibtex_hits, start=1):
            start = hit.start()
            end = bibtex_hits[i].start() if i < len(bibtex_hits) else len(bib_text)
            block = bib_text[start:end].strip()
            entries.append({
                "entry_key": hit.group(1).strip(),
                "raw_text": block,
                "ordinal": i,
                "doi": _extract_doi(block),
                "year": _extract_year(block),
                "title": _extract_bibtex_title(block),
            })
        return entries

    # Fall back to numbered / bullet / pandoc-key style — parse line by line
    ordinal = 0
    pending_text: list[str] = []
    pending_ordinal: int | None = None
    pending_explicit_key: str | None = None  # v0.23: pandoc-style explicit key
    for raw_line in bib_text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            # Blank separates entries; flush
            if pending_text:
                ordinal += 1 if pending_ordinal is None else 0
                entries.append(_make_entry(
                    pending_text, pending_ordinal or ordinal,
                    explicit_key=pending_explicit_key,
                ))
                pending_text = []
                pending_ordinal = None
                pending_explicit_key = None
            continue
        nm = BIB_NUMBERED.match(line)
        if nm:
            if pending_text:
                ordinal = pending_ordinal or (ordinal + 1)
                entries.append(_make_entry(
                    pending_text, ordinal,
                    explicit_key=pending_explicit_key,
                ))
                pending_text = []
                pending_explicit_key = None
            pending_ordinal = int(nm.group(1) or nm.group(2) or nm.group(3))
            pending_text = [nm.group(4)]
            continue
        # v0.23: pandoc-style "@key prose" — must be checked BEFORE BIB_BULLET
        # since "- @key prose" never matches and "@key" alone is unambiguous.
        pm = BIB_PANDOC_KEY.match(line)
        if pm:
            if pending_text:
                ordinal = pending_ordinal or (ordinal + 1)
                entries.append(_make_entry(
                    pending_text, ordinal,
                    explicit_key=pending_explicit_key,
                ))
                pending_text = []
                pending_ordinal = None
                pending_explicit_key = None
            pending_explicit_key = pm.group(1)
            pending_text = [pm.group(2)]
            continue
        bm = BIB_BULLET.match(line)
        if bm:
            if pending_text:
                ordinal = pending_ordinal or (ordinal + 1)
                entries.append(_make_entry(
                    pending_text, ordinal,
                    explicit_key=pending_explicit_key,
                ))
                pending_text = []
                pending_ordinal = None
                pending_explicit_key = None
            pending_text = [bm.group(1)]
            continue
        # Continuation of the previous entry
        if pending_text:
            pending_text.append(line.strip())

    if pending_text:
        ordinal = pending_ordinal or (ordinal + 1)
        entries.append(_make_entry(
            pending_text, ordinal,
            explicit_key=pending_explicit_key,
        ))

    return entries


def _make_entry(lines: list[str], ordinal: int,
                explicit_key: str | None = None) -> dict:
    raw = " ".join(lines).strip()
    return {
        "entry_key": explicit_key or _infer_entry_key(raw),
        "raw_text": raw,
        "ordinal": ordinal,
        "doi": _extract_doi(raw),
        "year": _extract_year(raw),
        "title": None,
    }


def _extract_doi(text: str) -> str | None:
    m = DOI_RX.search(text)
    return m.group(1) if m else None


def _extract_year(text: str) -> int | None:
    m = YEAR_RX.search(text)
    return int(m.group(1)) if m else None


def _extract_bibtex_title(block: str) -> str | None:
    m = re.search(r"title\s*=\s*\{+([^}]+)\}+", block, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _infer_entry_key(raw: str) -> str | None:
    """Produce a BibTeX-style key from Author+Year if inferrable."""
    m = KEY_AUTHOR_YEAR.match(raw.strip())
    if m:
        return f"{m.group(1).lower()}{m.group(2)}"
    return None


def disambiguate_entry_keys(entries: list[dict]) -> list[dict]:
    """Add `disambiguated_key` to every entry, auto-suffixing collisions.

    Academic convention: Wang (2020) [paper A] + Wang (2020) [paper B] →
    wang2020a, wang2020b (ordered by ordinal). The bare key stays in
    `entry_key`; the disambiguated form goes in `disambiguated_key`.

    Entries without an inferred entry_key (None) are left with
    `disambiguated_key=None`. Entries with unique keys get the
    disambiguated_key equal to the entry_key.
    """
    # Group by entry_key; preserve original order within groups via ordinal
    groups: dict[str, list[dict]] = {}
    for e in entries:
        k = e.get("entry_key")
        if k is None:
            continue
        groups.setdefault(k, []).append(e)

    # For each entry, decide its disambiguated_key
    out: list[dict] = []
    for e in entries:
        e = dict(e)  # shallow copy
        k = e.get("entry_key")
        if k is None:
            e["disambiguated_key"] = None
            out.append(e)
            continue
        group = groups[k]
        if len(group) == 1:
            e["disambiguated_key"] = k
        else:
            # Multiple entries share this key — assign a/b/c... by ordinal
            sorted_group = sorted(group, key=lambda x: x["ordinal"])
            suffix_idx = sorted_group.index(e)
            suffix = chr(ord("a") + suffix_idx) if suffix_idx < 26 else f"z{suffix_idx - 25}"
            e["disambiguated_key"] = f"{k}{suffix}"
        out.append(e)
    return out


def collision_groups(entries: list[dict]) -> dict[str, list[dict]]:
    """Return only the collision groups (entry_key → list of ≥2 entries)."""
    groups: dict[str, list[dict]] = {}
    for e in entries:
        k = e.get("entry_key")
        if k is not None:
            groups.setdefault(k, []).append(e)
    return {k: v for k, v in groups.items() if len(v) > 1}


def _slugify(s: str) -> str:
    out: list[str] = []
    for ch in (s or "").lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")[:60] or "untitled"


def derive_manuscript_id(title: str, source_text: str) -> str:
    slug = _slugify(title)
    h = hashlib.blake2s(source_text.encode("utf-8"), digest_size=3).hexdigest()
    return f"{slug}_{h}"


def extract_citations(source_text: str) -> list[dict]:
    """Return [{citation_key, location, style}, ...] for every inline citation.

    Location is a rough "§<section> ¶<paragraph>" derived from markdown headers
    and blank-line-separated paragraphs. Falls back to line numbers.
    """
    cites: list[dict] = []
    current_section = "body"
    paragraph_idx = 0
    lines = source_text.splitlines()

    # Build line → (section, paragraph) map
    line_loc: dict[int, tuple[str, int]] = {}
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            # Update current section to the header text
            current_section = stripped.lstrip("#").strip() or "body"
            paragraph_idx = 0
            line_loc[i] = (current_section, paragraph_idx)
            continue
        if not stripped:
            # Paragraph break
            paragraph_idx += 1
            line_loc[i] = (current_section, paragraph_idx)
            continue
        # If previous line was blank or a header, start a new paragraph
        if i > 0:
            prev = lines[i - 1].strip()
            if not prev or prev.startswith("#"):
                if paragraph_idx == 0 or (prev and prev.startswith("#")):
                    paragraph_idx += 1
        line_loc[i] = (current_section, paragraph_idx)

    seen: set[tuple[str, str]] = set()  # (key, location) for dedup

    for pattern, style in CITATION_PATTERNS:
        for m in pattern.finditer(source_text):
            # Compute the line for this match
            line_no = source_text.count("\n", 0, m.start())
            section, para = line_loc.get(line_no, (current_section, 0))
            location = f"§{section} ¶{para}"

            if style == "latex":
                # Comma-separated keys inside braces
                for key in m.group(1).split(","):
                    key = key.strip()
                    if key and (key, location) not in seen:
                        cites.append({"citation_key": key, "location": location, "style": style})
                        seen.add((key, location))
            elif style == "pandoc":
                # Extract every @key in the match (pandoc allows multi-key)
                keys = re.findall(r"@([A-Za-z0-9_:-]+)", m.group(0))
                for key in keys:
                    if key and (key, location) not in seen:
                        cites.append({"citation_key": key, "location": location, "style": style})
                        seen.add((key, location))
            elif style == "numeric":
                # [1,2,3] → three separate citations
                nums = re.findall(r"\d+", m.group(1))
                for n in nums:
                    key = f"[{n}]"
                    if (key, location) not in seen:
                        cites.append({"citation_key": key, "location": location, "style": style})
                        seen.add((key, location))
            elif style == "author-year":
                key = m.group(1).strip()
                if (key, location) not in seen:
                    cites.append({"citation_key": key, "location": location, "style": style})
                    seen.add((key, location))

    return cites


def _project_db(project_id: str) -> Path:
    p = cache_root() / "projects" / project_id / "project.db"
    if not p.exists():
        raise SystemExit(f"no project DB at {p} — create the project first")
    return p


def populate_graph_and_citations(
    mid: str,
    citations: list[dict],
    bib_entries: list[dict],
    project_id: str,
) -> dict:
    """Write manuscript_citations + manuscript_references + graph nodes/edges.

    Returns counts for the caller's summary.
    """
    now = datetime.now(UTC).isoformat()
    con = sqlite3.connect(_project_db(project_id))
    citations_recorded = 0
    references_recorded = 0
    placeholder_nodes = 0
    cites_edges = 0

    with con:
        # Manuscript node
        ms_node = f"manuscript:{mid}"
        con.execute(
            "INSERT OR IGNORE INTO graph_nodes "
            "(node_id, kind, label, data_json, created_at) "
            "VALUES (?, 'manuscript', ?, NULL, ?)",
            (ms_node, mid, now),
        )

        # Dedup citation keys for graph edges (keep location variants in the
        # manuscript_citations table but only one edge per key→manuscript)
        unique_keys: set[str] = set()

        for c in citations:
            # manuscript_citations: record every (manuscript, key, location)
            # (UNIQUE on triple)
            cur = con.execute(
                "INSERT OR IGNORE INTO manuscript_citations "
                "(manuscript_id, citation_key, location, at) "
                "VALUES (?, ?, ?, ?)",
                (mid, c["citation_key"], c["location"], now),
            )
            if cur.rowcount:
                citations_recorded += 1

            # Graph: placeholder paper node (prefix with citation-key: so it's
            # distinct from canonical_id-based paper nodes — resolution later
            # replaces/merges)
            placeholder_id = f"paper:unresolved:{c['citation_key']}"
            if c["citation_key"] not in unique_keys:
                unique_keys.add(c["citation_key"])
                cur_node = con.execute(
                    "INSERT OR IGNORE INTO graph_nodes "
                    "(node_id, kind, label, data_json, created_at) "
                    "VALUES (?, 'paper', ?, ?, ?)",
                    (placeholder_id, c["citation_key"],
                     json.dumps({"unresolved": True, "style": c["style"]}), now),
                )
                if cur_node.rowcount:
                    placeholder_nodes += 1

                # One cites edge per manuscript → unresolved paper
                # (dedup: only add if not already present)
                exists = con.execute(
                    "SELECT 1 FROM graph_edges "
                    "WHERE from_node=? AND to_node=? AND relation='cites'",
                    (ms_node, placeholder_id),
                ).fetchone()
                if not exists:
                    con.execute(
                        "INSERT INTO graph_edges "
                        "(from_node, to_node, relation, weight, data_json, created_at) "
                        "VALUES (?, ?, 'cites', 1.0, ?, ?)",
                        (ms_node, placeholder_id,
                         json.dumps({"citation_key": c["citation_key"]}), now),
                    )
                    cites_edges += 1

        # Bibliography entries with v0.10 collision disambiguation
        disambiguated = disambiguate_entry_keys(bib_entries)
        for entry in disambiguated:
            cur = con.execute(
                "INSERT OR IGNORE INTO manuscript_references "
                "(manuscript_id, entry_key, disambiguated_key, raw_text, ordinal, "
                "doi, title, year, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    mid, entry.get("entry_key"), entry.get("disambiguated_key"),
                    entry["raw_text"], entry["ordinal"],
                    entry.get("doi"), entry.get("title"),
                    entry.get("year"), now,
                ),
            )
            if cur.rowcount:
                references_recorded += 1

    con.close()
    return {
        "citations_recorded": citations_recorded,
        "references_recorded": references_recorded,
        "placeholder_paper_nodes": placeholder_nodes,
        "cites_edges": cites_edges,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True, help="Path to manuscript .md file")
    p.add_argument("--title", required=True)
    p.add_argument("--project-id", default=None)
    args = p.parse_args()

    src = Path(args.source).expanduser().resolve()
    if not src.exists():
        raise SystemExit(f"source not found: {src}")
    if src.suffix.lower() not in (".md", ".markdown"):
        raise SystemExit(f"only markdown supported in this iteration; got {src.suffix}")

    text = src.read_text()
    if not text.strip():
        raise SystemExit("source is empty")

    mid = derive_manuscript_id(args.title, text)
    art = ManuscriptArtifact(mid)
    (art.root / "source.md").write_text(text)

    m = art.load_manifest()
    m.extras["title"] = args.title
    m.extras["source_path"] = str(src)
    m.extras["char_count"] = len(text)
    art.save_manifest(m)

    citations = extract_citations(text)
    bib_entries = extract_bibliography(text)
    summary: dict = {
        "manuscript_id": mid,
        "citations_found_in_source": len(citations),
        "bibliography_entries_found": len(bib_entries),
    }

    if args.project_id:
        from lib.project import register_artifact
        register_artifact(args.project_id, mid, ArtifactKind.manuscript.value,
                          "drafted", art.root)
        graph_stats = populate_graph_and_citations(
            mid, citations, bib_entries, args.project_id
        )
        summary.update(graph_stats)

    # Print the mid on the first line for backward-compat with existing callers
    print(mid)
    # Then the detailed summary as JSON on stderr so it doesn't break pipes
    print(json.dumps(summary, indent=2), file=sys.stderr)


if __name__ == "__main__":
    main()
