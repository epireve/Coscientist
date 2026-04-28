#!/usr/bin/env python3
"""manuscript-draft: scaffold a new manuscript artifact from a venue template.

Subcommands
-----------
init      Create manifest + outline.json + source.md with placeholder sections.
section   Write or update one section in source.md; updates outline.json stats.
status    Print outline with per-section word counts, status, and cite keys.

Typical workflow
----------------
  # 1. Scaffold
  python draft.py init --title "My Paper" --venue neurips [--project-id pid]

  # 2. Fill sections (agent writes content, passes via --text or stdin)
  python draft.py section --manuscript-id <mid> --section introduction \\
      --text "Recent work on... [@vaswani2017attention]..."

  # 3. Check progress
  python draft.py status --manuscript-id <mid>

  # 4. Feed to manuscript-ingest for analysis
  python manuscript-ingest/scripts/ingest.py --source <source.md path> ...
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.artifact import ManuscriptArtifact  # noqa: E402
from lib.cache import cache_root  # noqa: E402

_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS_DIR))
from outline import (  # noqa: E402
    KNOWN_VENUES,
    completion_summary,
    get_section,
    load_outline,
    outline_from_template,
    save_outline,
    total_word_count,
    update_section_stats,
)
from section import (  # noqa: E402
    build_source_md,
    count_words,
    find_cite_keys,
    replace_section,
)

# --------------------------------------------------------------------------- #
# manuscript_id derivation (mirrors manuscript-ingest logic)                  #
# --------------------------------------------------------------------------- #

def _slug(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text).strip("_")
    return text[:40]


def _make_manuscript_id(title: str, venue: str) -> str:
    digest = hashlib.blake2s(f"{title}::{venue}".encode()).hexdigest()[:6]
    return f"{_slug(title)}_{digest}"


# --------------------------------------------------------------------------- #
# project DB registration (optional)                                          #
# --------------------------------------------------------------------------- #

def _register_in_project(manuscript_id: str, title: str, project_id: str) -> None:
    """Insert a row into the project's artifact_index."""
    import sqlite3
    project_dir = cache_root() / "projects" / project_id
    if not project_dir.exists():
        print(f"WARNING: project {project_id!r} not found — skipping registration",
              file=sys.stderr)
        return

    try:
        from lib.migrations import ensure_current
        db_path = project_dir / "project.db"
        conn = sqlite3.connect(db_path)
        ensure_current(conn)
        conn.execute(
            "INSERT OR IGNORE INTO artifact_index "
            "(artifact_id, kind, state, title, project_id, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (manuscript_id, "manuscript", "drafted", title, project_id,
             datetime.now(UTC).isoformat()),
        )
        conn.commit()
        conn.close()
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: could not register in project DB: {exc}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# Subcommand: init                                                             #
# --------------------------------------------------------------------------- #

def cmd_init(args: argparse.Namespace) -> int:
    venue = args.venue.lower()
    if venue not in KNOWN_VENUES:
        print(f"ERROR: unknown venue {venue!r}. Known: {', '.join(sorted(KNOWN_VENUES))}",
              file=sys.stderr)
        return 2

    manuscript_id = _make_manuscript_id(args.title, venue)
    art = ManuscriptArtifact(manuscript_id)

    # Guard against clobbering an existing draft
    if (art.root / "outline.json").exists() and not args.force:
        print(f"ERROR: {manuscript_id} already exists. Use --force to reinitialise.",
              file=sys.stderr)
        return 1

    # Build outline from template
    outline = outline_from_template(manuscript_id, args.title, venue)
    save_outline(outline, art.root)

    # Build source.md with placeholder sections
    sections = [
        {"heading": s.heading, "name": s.name,
         "notes": s.notes, "target_words": s.target_words}
        for s in outline.sections
    ]
    source_md = build_source_md(args.title, outline.venue_full_name, manuscript_id, sections)
    (art.root / "source.md").write_text(source_md)

    # Write manifest (state=drafted)
    m = art.load_manifest()
    m.extras["title"] = args.title
    m.extras["venue"] = venue
    art.save_manifest(m)

    # Optional project registration
    if args.project_id:
        _register_in_project(manuscript_id, args.title, args.project_id)

    print(manuscript_id)
    return 0


# --------------------------------------------------------------------------- #
# Subcommand: section                                                          #
# --------------------------------------------------------------------------- #

def cmd_section(args: argparse.Namespace) -> int:
    art = ManuscriptArtifact(args.manuscript_id)
    if not (art.root / "outline.json").exists():
        print(f"ERROR: manuscript {args.manuscript_id!r} not found or not initialised.",
              file=sys.stderr)
        return 1

    outline = load_outline(art.root)

    # Validate section name
    try:
        sec = get_section(outline, args.section)
    except KeyError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    # Read new content
    if args.text:
        new_body = args.text
    elif not sys.stdin.isatty():
        new_body = sys.stdin.read()
    else:
        print("ERROR: provide --text or pipe content via stdin.", file=sys.stderr)
        return 2

    # Update source.md
    source_path = art.root / "source.md"
    source = source_path.read_text()
    updated = replace_section(source, sec.heading, new_body)
    if updated == source and sec.status == "placeholder":
        # Section heading not found — append it
        updated = source.rstrip("\n") + f"\n\n## {sec.heading}\n\n{new_body.strip()}\n\n"
    source_path.write_text(updated)

    # Update outline stats
    words = count_words(new_body)
    keys = find_cite_keys(new_body)
    status = args.status if args.status else "drafted"
    update_section_stats(outline, args.section, words, keys, status)
    save_outline(outline, art.root)

    print(f"section:{args.section} words:{words} cite_keys:{len(keys)} status:{status}")
    return 0


# --------------------------------------------------------------------------- #
# Subcommand: status                                                           #
# --------------------------------------------------------------------------- #

def cmd_status(args: argparse.Namespace) -> int:
    art = ManuscriptArtifact(args.manuscript_id)
    if not (art.root / "outline.json").exists():
        print(f"ERROR: manuscript {args.manuscript_id!r} not found.", file=sys.stderr)
        return 1

    outline = load_outline(art.root)
    summary = completion_summary(outline)
    total_w = total_word_count(outline)

    print(f"manuscript: {outline.manuscript_id}")
    print(f"title:      {outline.title}")
    print(f"venue:      {outline.venue_full_name}")
    print(f"word_limit: {outline.word_limit}")
    print(f"total_words:{total_w}")
    print(f"sections:   {summary}")
    print()

    # Table header
    col = "{:<22} {:>6}  {:>7}  {:>9}  {}"
    print(col.format("section", "status", "words", "target", "cite_keys"))
    print("-" * 72)
    for s in outline.sections:
        req = "" if s.required else "(opt)"
        keys_str = ",".join(s.cite_keys[:5])
        if len(s.cite_keys) > 5:
            keys_str += f" +{len(s.cite_keys)-5}"
        print(col.format(
            f"{s.name[:22]}{req}",
            s.status[:9],
            str(s.word_count),
            str(s.target_words),
            keys_str,
        ))
    return 0


# --------------------------------------------------------------------------- #
# Subcommand: venues                                                           #
# --------------------------------------------------------------------------- #

def cmd_venues(_args: argparse.Namespace) -> int:
    _TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
    import json as _json
    for venue in sorted(KNOWN_VENUES):
        tmpl = _json.loads((_TEMPLATES / f"{venue}.json").read_text())
        n_sections = len(tmpl["sections"])
        print(f"  {venue:<10}  {tmpl['full_name']}  "
              f"({n_sections} sections, ≤{tmpl['word_limit']} words)")
    return 0


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #

def main() -> int:
    p = argparse.ArgumentParser(
        prog="draft.py",
        description="Scaffold and fill a new manuscript artifact.",
    )
    sub = p.add_subparsers(dest="subcommand", required=True)

    # init
    pi = sub.add_parser("init", help="Create manifest + outline + source.md")
    pi.add_argument("--title", required=True, help="Paper title")
    pi.add_argument(
        "--venue",
        required=True,
        choices=sorted(KNOWN_VENUES),
        help="Venue template",
    )
    pi.add_argument("--project-id", dest="project_id",
                    help="Register in this project's artifact_index")
    pi.add_argument("--force", action="store_true",
                    help="Overwrite existing draft")

    # section
    ps = sub.add_parser("section", help="Write or update one section")
    ps.add_argument("--manuscript-id", required=True, dest="manuscript_id")
    ps.add_argument("--section", required=True,
                    help="Section name (e.g. 'introduction')")
    ps.add_argument("--text", help="Section body text (or pipe via stdin)")
    ps.add_argument(
        "--status",
        choices=["drafted", "revised"],
        default="drafted",
        help="Section status to record (default: drafted)",
    )

    # status
    pst = sub.add_parser("status", help="Print section progress table")
    pst.add_argument("--manuscript-id", required=True, dest="manuscript_id")

    # venues
    sub.add_parser("venues", help="List available venue templates")

    args = p.parse_args()
    dispatch = {
        "init": cmd_init,
        "section": cmd_section,
        "status": cmd_status,
        "venues": cmd_venues,
    }
    return dispatch[args.subcommand](args)


if __name__ == "__main__":
    sys.exit(main())
