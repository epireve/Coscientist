#!/usr/bin/env python3
"""grant-draft: main CLI for grant scaffold management."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa
import importlib.util as _ilu

_spec = _ilu.spec_from_file_location("outline", Path(__file__).parent / "outline.py")
_outline_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_outline_mod)


def grant_dir(grant_id: str) -> Path:
    return cache_root() / "grants" / grant_id


def _load_manifest(grant_id: str) -> dict:
    p = grant_dir(grant_id) / "manifest.json"
    if not p.exists():
        raise FileNotFoundError(f"grant {grant_id!r} not found")
    return json.loads(p.read_text())


def _load_outline(grant_id: str) -> dict:
    p = grant_dir(grant_id) / "outline.json"
    if not p.exists():
        raise FileNotFoundError(f"outline not found for grant {grant_id!r}")
    return json.loads(p.read_text())


def _save_outline(grant_id: str, outline: dict) -> None:
    (grant_dir(grant_id) / "outline.json").write_text(json.dumps(outline, indent=2))


def cmd_init(args: argparse.Namespace) -> None:
    funder = args.funder.lower()
    mechanism = args.mechanism

    # Validate before creating anything
    _outline_mod.get_template(funder, mechanism)

    grant_id = _outline_mod.make_grant_id(args.title, funder)
    gd = grant_dir(grant_id)

    if (gd / "manifest.json").exists() and not args.force:
        raise SystemExit(
            f"grant {grant_id!r} already exists. Use --force to re-init."
        )
    gd.mkdir(parents=True, exist_ok=True)

    outline = _outline_mod.build_outline(args.title, funder, mechanism)
    source_md = _outline_mod.build_source_md(outline)

    manifest = {
        "grant_id": grant_id,
        "title": args.title,
        "funder": funder,
        "mechanism": outline["mechanism"],
        "state": "drafted",
        "created_at": datetime.now(UTC).isoformat(),
    }
    (gd / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (gd / "outline.json").write_text(json.dumps(outline, indent=2))
    (gd / "source.md").write_text(source_md)

    print(json.dumps({
        "grant_id": grant_id,
        "funder": funder,
        "mechanism": outline["mechanism"],
        "n_sections": len(outline["sections"]),
        "path": str(gd),
    }, indent=2))


def cmd_section(args: argparse.Namespace) -> None:
    outline = _load_outline(args.grant_id)
    section = next(
        (s for s in outline["sections"] if s["id"] == args.section),
        None,
    )
    if section is None:
        valid = [s["id"] for s in outline["sections"]]
        raise SystemExit(f"unknown section {args.section!r}; valid: {valid}")

    # Update source.md
    source_path = grant_dir(args.grant_id) / "source.md"
    source = source_path.read_text() if source_path.exists() else ""
    # Replace placeholder with new content
    old_placeholder = f"[PLACEHOLDER: {section['title']}]"
    if old_placeholder in source:
        source = source.replace(old_placeholder, args.content)
    else:
        source += f"\n\n## {section['title']}\n{args.content}\n"
    source_path.write_text(source)

    # Update outline stats
    wc = _outline_mod.count_words(args.content)
    section["word_count"] = wc
    section["status"] = "drafted"
    section["content_preview"] = args.content[:60]
    _save_outline(args.grant_id, outline)

    print(json.dumps({
        "grant_id": args.grant_id,
        "section": args.section,
        "word_count": wc,
        "status": "drafted",
    }, indent=2))


def cmd_status(args: argparse.Namespace) -> None:
    manifest = _load_manifest(args.grant_id)
    outline = _load_outline(args.grant_id)
    sections = outline["sections"]
    total_words = sum(s.get("word_count", 0) for s in sections)
    target_words = sum(s.get("target_words", 0) for s in sections)
    drafted = sum(1 for s in sections if s.get("status") == "drafted")
    print(json.dumps({
        "grant_id": args.grant_id,
        "title": manifest["title"],
        "funder": manifest["funder"],
        "mechanism": manifest["mechanism"],
        "state": manifest["state"],
        "sections_total": len(sections),
        "sections_drafted": drafted,
        "total_words": total_words,
        "target_words": target_words,
        "sections": [
            {k: s[k] for k in ["id", "title", "status", "word_count", "target_words", "required"]}
            for s in sections
        ],
    }, indent=2))


def cmd_funders(args: argparse.Namespace) -> None:
    result = []
    for key, tmpl in _outline_mod.FUNDERS.items():
        result.append({
            "funder": key,
            "label": tmpl["label"],
            "mechanisms": tmpl["mechanisms"],
            "default_mechanism": tmpl["default_mechanism"],
            "n_sections": len(tmpl["sections"]),
        })
    print(json.dumps(result, indent=2))


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init")
    pi.add_argument("--title", required=True)
    pi.add_argument("--funder", required=True, choices=sorted(_outline_mod.FUNDERS))
    pi.add_argument("--mechanism", default=None)
    pi.add_argument("--force", action="store_true", default=False)
    pi.set_defaults(func=cmd_init)

    ps = sub.add_parser("section")
    ps.add_argument("--grant-id", required=True)
    ps.add_argument("--section", required=True)
    ps.add_argument("--content", required=True)
    ps.set_defaults(func=cmd_section)

    pst = sub.add_parser("status")
    pst.add_argument("--grant-id", required=True)
    pst.set_defaults(func=cmd_status)

    pf = sub.add_parser("funders")
    pf.set_defaults(func=cmd_funders)

    args = p.parse_args()
    try:
        args.func(args)
    except (ValueError, FileNotFoundError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
