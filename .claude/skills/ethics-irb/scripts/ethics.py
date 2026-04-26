#!/usr/bin/env python3
"""ethics-irb: IRB application scaffold + COI registry."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402

VALID_REVIEW_LEVELS = {"exempt", "expedited", "full-board"}
VALID_COI_TYPES = {"funding", "consulting", "stock", "family", "advisory", "other"}

IRB_TEMPLATES = {
    "exempt": [
        {"id": "study_description", "title": "Study Description", "target_words": 300, "required": True},
        {"id": "exemption_category", "title": "Exemption Category", "target_words": 100, "required": True},
        {"id": "data_security", "title": "Data Security", "target_words": 200, "required": True},
    ],
    "expedited": [
        {"id": "study_description", "title": "Study Description", "target_words": 400, "required": True},
        {"id": "risk_assessment", "title": "Risk Assessment", "target_words": 300, "required": True},
        {"id": "consent", "title": "Informed Consent", "target_words": 300, "required": True},
        {"id": "recruitment", "title": "Recruitment", "target_words": 200, "required": True},
        {"id": "data_security", "title": "Data Security", "target_words": 200, "required": True},
        {"id": "monitoring", "title": "Safety Monitoring", "target_words": 200, "required": True},
    ],
    "full-board": [
        {"id": "study_description", "title": "Study Description", "target_words": 600, "required": True},
        {"id": "risk_assessment", "title": "Risk-Benefit Assessment", "target_words": 500, "required": True},
        {"id": "consent", "title": "Informed Consent", "target_words": 500, "required": True},
        {"id": "recruitment", "title": "Recruitment", "target_words": 300, "required": True},
        {"id": "vulnerable_populations", "title": "Vulnerable Populations", "target_words": 300, "required": True},
        {"id": "equity", "title": "Equity & Inclusion", "target_words": 250, "required": True},
        {"id": "data_security", "title": "Data Security", "target_words": 300, "required": True},
        {"id": "dsmb", "title": "Data and Safety Monitoring Board", "target_words": 300, "required": True},
        {"id": "oversight", "title": "Oversight & Reporting", "target_words": 200, "required": True},
    ],
}


def _slug(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:40].strip("_")


def make_app_id(title: str, level: str) -> str:
    h = hashlib.blake2s(f"{title}::{level}".encode(), digest_size=3).hexdigest()
    return f"{_slug(title)}_{_slug(level)}_{h}"


def app_dir(app_id: str) -> Path:
    return cache_root() / "irb" / app_id


def coi_path(project_id: str) -> Path:
    p = cache_root() / "projects" / project_id
    p.mkdir(parents=True, exist_ok=True)
    return p / "coi.json"


def cmd_irb_init(args: argparse.Namespace) -> None:
    if args.review_level not in VALID_REVIEW_LEVELS:
        raise SystemExit(f"--review-level must be one of {sorted(VALID_REVIEW_LEVELS)}")
    sections = list(IRB_TEMPLATES[args.review_level])
    app_id = make_app_id(args.title, args.review_level)
    d = app_dir(app_id)
    if (d / "manifest.json").exists() and not args.force:
        raise SystemExit(f"IRB application {app_id!r} already exists. Use --force.")
    d.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    (d / "manifest.json").write_text(json.dumps({
        "application_id": app_id, "title": args.title,
        "review_level": args.review_level,
        "has_vulnerable_pop": args.has_vulnerable_pop,
        "state": "drafted", "created_at": now,
    }, indent=2))
    outline = {
        "application_id": app_id, "review_level": args.review_level,
        "sections": [
            {**s, "status": "placeholder", "word_count": 0}
            for s in sections
        ],
    }
    (d / "outline.json").write_text(json.dumps(outline, indent=2))
    print(json.dumps({
        "application_id": app_id,
        "review_level": args.review_level,
        "n_sections": len(sections),
        "path": str(d),
    }, indent=2))


def cmd_irb_section(args: argparse.Namespace) -> None:
    d = app_dir(args.application_id)
    op = d / "outline.json"
    if not op.exists():
        raise FileNotFoundError(f"IRB application {args.application_id!r} not found")
    outline = json.loads(op.read_text())
    section = next((s for s in outline["sections"] if s["id"] == args.section), None)
    if section is None:
        valid = [s["id"] for s in outline["sections"]]
        raise SystemExit(f"unknown section {args.section!r}; valid: {valid}")
    section["word_count"] = len(args.content.split())
    section["status"] = "drafted"
    section["content"] = args.content
    op.write_text(json.dumps(outline, indent=2))
    print(json.dumps({
        "application_id": args.application_id,
        "section": args.section,
        "word_count": section["word_count"],
        "status": "drafted",
    }, indent=2))


def cmd_irb_status(args: argparse.Namespace) -> None:
    d = app_dir(args.application_id)
    mp = d / "manifest.json"
    op = d / "outline.json"
    if not mp.exists():
        raise FileNotFoundError(f"IRB application {args.application_id!r} not found")
    manifest = json.loads(mp.read_text())
    outline = json.loads(op.read_text())
    sections = outline["sections"]
    drafted = sum(1 for s in sections if s.get("status") == "drafted")
    print(json.dumps({
        "application_id": args.application_id,
        "title": manifest["title"],
        "review_level": manifest["review_level"],
        "sections_total": len(sections),
        "sections_drafted": drafted,
        "total_words": sum(s.get("word_count", 0) for s in sections),
    }, indent=2))


def _load_coi(project_id: str) -> list[dict]:
    p = coi_path(project_id)
    if not p.exists():
        return []
    return json.loads(p.read_text())


def _save_coi(project_id: str, entries: list[dict]) -> None:
    coi_path(project_id).write_text(json.dumps(entries, indent=2))


def cmd_coi_add(args: argparse.Namespace) -> None:
    if args.type not in VALID_COI_TYPES:
        raise SystemExit(f"--type must be one of {sorted(VALID_COI_TYPES)}")
    if not args.entity.strip():
        raise SystemExit("--entity must be non-empty")
    entries = _load_coi(args.project_id)
    new_id = max((e.get("id", 0) for e in entries), default=0) + 1
    entry = {
        "id": new_id,
        "entity": args.entity,
        "type": args.type,
        "value": args.value,
        "declared_at": datetime.now(UTC).isoformat(),
    }
    entries.append(entry)
    _save_coi(args.project_id, entries)
    print(json.dumps({
        "project_id": args.project_id,
        "added_id": new_id,
        "total_count": len(entries),
    }, indent=2))


def cmd_coi_list(args: argparse.Namespace) -> None:
    entries = _load_coi(args.project_id)
    print(json.dumps({
        "project_id": args.project_id,
        "entries": entries,
        "total": len(entries),
    }, indent=2))


def cmd_coi_remove(args: argparse.Namespace) -> None:
    entries = _load_coi(args.project_id)
    new = [e for e in entries if e.get("id") != args.entry_id]
    if len(new) == len(entries):
        raise SystemExit(f"no entry with id={args.entry_id}")
    _save_coi(args.project_id, new)
    print(json.dumps({
        "project_id": args.project_id,
        "removed_id": args.entry_id,
        "total_count": len(new),
    }, indent=2))


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("irb-init")
    pi.add_argument("--title", required=True)
    pi.add_argument("--review-level", required=True, choices=sorted(VALID_REVIEW_LEVELS))
    pi.add_argument("--has-vulnerable-pop", action="store_true", default=False)
    pi.add_argument("--force", action="store_true", default=False)
    pi.set_defaults(func=cmd_irb_init)

    ps = sub.add_parser("irb-section")
    ps.add_argument("--application-id", required=True)
    ps.add_argument("--section", required=True)
    ps.add_argument("--content", required=True)
    ps.set_defaults(func=cmd_irb_section)

    pst = sub.add_parser("irb-status")
    pst.add_argument("--application-id", required=True)
    pst.set_defaults(func=cmd_irb_status)

    pca = sub.add_parser("coi-add")
    pca.add_argument("--project-id", required=True)
    pca.add_argument("--entity", required=True)
    pca.add_argument("--type", required=True, choices=sorted(VALID_COI_TYPES))
    pca.add_argument("--value", default="")
    pca.set_defaults(func=cmd_coi_add)

    pcl = sub.add_parser("coi-list")
    pcl.add_argument("--project-id", required=True)
    pcl.set_defaults(func=cmd_coi_list)

    pcr = sub.add_parser("coi-remove")
    pcr.add_argument("--project-id", required=True)
    pcr.add_argument("--entry-id", type=int, required=True)
    pcr.set_defaults(func=cmd_coi_remove)

    args = p.parse_args()
    try:
        args.func(args)
    except (FileNotFoundError, ValueError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
