#!/usr/bin/env python3
"""manuscript-ingest: copy a markdown draft into a manuscript artifact.

When --project-id is given, this also:
- Creates a manuscript node in the project graph
- Parses inline citations from the source
- Populates manuscript_citations (raw citation keys + locations, unresolved)
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
    project_id: str,
) -> dict:
    """Write manuscript_citations rows + graph nodes + cites edges.

    Returns counts for the caller's summary.
    """
    now = datetime.now(UTC).isoformat()
    con = sqlite3.connect(_project_db(project_id))
    citations_recorded = 0
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

    con.close()
    return {
        "citations_recorded": citations_recorded,
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
    summary: dict = {
        "manuscript_id": mid,
        "citations_found_in_source": len(citations),
    }

    if args.project_id:
        from lib.project import register_artifact
        register_artifact(args.project_id, mid, ArtifactKind.manuscript.value,
                          "drafted", art.root)
        graph_stats = populate_graph_and_citations(mid, citations, args.project_id)
        summary.update(graph_stats)

    # Print the mid on the first line for backward-compat with existing callers
    print(mid)
    # Then the detailed summary as JSON on stderr so it doesn't break pipes
    print(json.dumps(summary, indent=2), file=sys.stderr)


if __name__ == "__main__":
    main()
