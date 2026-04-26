#!/usr/bin/env python3
"""dmp-generator: funder-specific Data Management Plan scaffold."""
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

FUNDERS = {
    "nih": {
        "label": "NIH (DMSP)",
        "mechanisms": ["R01", "R21", "U01", "K99", "F31"],
        "default_mechanism": "R01",
        "sections": [
            {"id": "data_type", "title": "Data Type", "target_words": 250, "required": True,
             "notes": "Describe data types/scale/file formats. Specify if scientific data per NIH definition."},
            {"id": "tools_standards", "title": "Related Tools, Software, Standards", "target_words": 200, "required": True,
             "notes": "Software, code, ontologies needed to access/use the data."},
            {"id": "preservation", "title": "Data Preservation, Access, Timeline", "target_words": 300, "required": True,
             "notes": "Repository (e.g., dbGaP, GEO, generalist), metadata, persistent ID, access timing."},
            {"id": "access_distribution", "title": "Access, Distribution, Reuse", "target_words": 250, "required": True,
             "notes": "Who can access, when, under what license. Anticipate restrictions."},
            {"id": "oversight", "title": "Oversight of DMS", "target_words": 150, "required": True,
             "notes": "Who is responsible. Compliance monitoring."},
        ],
    },
    "nsf": {
        "label": "NSF (DMP)",
        "mechanisms": ["Standard", "CAREER", "RAPID"],
        "default_mechanism": "Standard",
        "sections": [
            {"id": "data_description", "title": "Data Description", "target_words": 200, "required": True,
             "notes": "Types of data, samples, physical collections, software, models, etc."},
            {"id": "standards", "title": "Standards for Data and Metadata", "target_words": 150, "required": True,
             "notes": "Format, content, structure, metadata standards."},
            {"id": "access_sharing", "title": "Policies for Access and Sharing", "target_words": 200, "required": True,
             "notes": "How data will be shared. Privacy, IP, confidentiality concerns."},
            {"id": "reuse_redistribution", "title": "Re-use, Redistribution, Derivatives", "target_words": 150, "required": True,
             "notes": "Permitted uses; ethical/legal restrictions."},
            {"id": "archiving", "title": "Plans for Archiving", "target_words": 200, "required": True,
             "notes": "Long-term preservation. Repository commitment."},
        ],
    },
    "wellcome": {
        "label": "Wellcome (Output Management Plan)",
        "mechanisms": ["Discovery", "Investigator", "Career"],
        "default_mechanism": "Discovery",
        "sections": [
            {"id": "data_output", "title": "Outputs Generated", "target_words": 200, "required": True,
             "notes": "Datasets, code, materials. Volume, sensitivity."},
            {"id": "sharing_strategy", "title": "Strategy for Sharing", "target_words": 250, "required": True,
             "notes": "When + where. Default open. FAIR principles."},
            {"id": "resources", "title": "Resources Required", "target_words": 150, "required": True,
             "notes": "Costs for data sharing — include in budget."},
            {"id": "ethics", "title": "Ethics, Legal, Commercial Considerations", "target_words": 200, "required": True,
             "notes": "Patient consent, GDPR, embargo periods, IP."},
        ],
    },
    "erc": {
        "label": "ERC (Horizon Europe DMP)",
        "mechanisms": ["Starting", "Consolidator", "Advanced", "Synergy"],
        "default_mechanism": "Starting",
        "sections": [
            {"id": "findability", "title": "Findability (FAIR-F)", "target_words": 150, "required": True,
             "notes": "Persistent IDs (DOI), metadata, registration in searchable resource."},
            {"id": "accessibility", "title": "Accessibility (FAIR-A)", "target_words": 200, "required": True,
             "notes": "Repository choice, access protocol, authentication if restricted."},
            {"id": "interoperability", "title": "Interoperability (FAIR-I)", "target_words": 150, "required": True,
             "notes": "Standard formats, controlled vocabularies, ontologies."},
            {"id": "reuse", "title": "Reusability (FAIR-R)", "target_words": 200, "required": True,
             "notes": "License (CC-BY preferred), provenance, community standards."},
            {"id": "resources_security", "title": "Resources, Costs, Security", "target_words": 200, "required": False,
             "notes": "Storage costs, data security, sensitive data handling."},
        ],
    },
}


def _slug(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:40].strip("_")


def make_dmp_id(title: str, funder: str) -> str:
    h = hashlib.blake2s(f"{title}::{funder}".encode(), digest_size=3).hexdigest()
    return f"{_slug(title)}_{_slug(funder)}_{h}"


def dmp_dir(dmp_id: str) -> Path:
    return cache_root() / "dmps" / dmp_id


def get_template(funder: str, mechanism: str | None) -> dict:
    if funder not in FUNDERS:
        raise ValueError(f"unknown funder {funder!r}; valid: {sorted(FUNDERS)}")
    tmpl = FUNDERS[funder]
    mech = mechanism or tmpl["default_mechanism"]
    if mech not in tmpl["mechanisms"]:
        raise ValueError(
            f"unknown mechanism {mech!r} for {funder}; valid: {tmpl['mechanisms']}"
        )
    return {"funder": funder, "label": tmpl["label"], "mechanism": mech,
            "sections": [dict(s) for s in tmpl["sections"]]}


def build_outline(title: str, funder: str, mechanism: str | None) -> dict:
    tmpl = get_template(funder, mechanism)
    return {
        "title": title,
        "funder": funder,
        "mechanism": tmpl["mechanism"],
        "sections": [
            {**s, "status": "placeholder", "word_count": 0, "content_preview": ""}
            for s in tmpl["sections"]
        ],
    }


def build_source_md(outline: dict) -> str:
    lines = [
        "---",
        f'title: "{outline["title"]}"',
        f"funder: {outline['funder']}",
        f"mechanism: {outline['mechanism']}",
        "---",
        "",
    ]
    for s in outline["sections"]:
        lines.append(f"## {s['title']}")
        lines.append(f"<!-- target: {s['target_words']} words | {s['notes']} -->")
        lines.append("")
        lines.append(f"[PLACEHOLDER: {s['title']}]")
        lines.append("")
    return "\n".join(lines)


def count_words(text: str) -> int:
    return len(text.split())


def cmd_init(args: argparse.Namespace) -> None:
    funder = args.funder.lower()
    get_template(funder, args.mechanism)
    dmp_id = make_dmp_id(args.title, funder)
    d = dmp_dir(dmp_id)
    if (d / "manifest.json").exists() and not args.force:
        raise SystemExit(f"DMP {dmp_id!r} already exists. Use --force.")
    d.mkdir(parents=True, exist_ok=True)
    outline = build_outline(args.title, funder, args.mechanism)
    src = build_source_md(outline)
    now = datetime.now(UTC).isoformat()
    (d / "manifest.json").write_text(json.dumps({
        "dmp_id": dmp_id, "title": args.title, "funder": funder,
        "mechanism": outline["mechanism"], "state": "drafted",
        "created_at": now, "updated_at": now,
    }, indent=2))
    (d / "outline.json").write_text(json.dumps(outline, indent=2))
    (d / "source.md").write_text(src)
    print(json.dumps({
        "dmp_id": dmp_id, "funder": funder,
        "mechanism": outline["mechanism"],
        "n_sections": len(outline["sections"]),
        "path": str(d),
    }, indent=2))


def cmd_section(args: argparse.Namespace) -> None:
    d = dmp_dir(args.dmp_id)
    op = d / "outline.json"
    sp = d / "source.md"
    if not op.exists():
        raise FileNotFoundError(f"DMP {args.dmp_id!r} not found")
    outline = json.loads(op.read_text())
    section = next((s for s in outline["sections"] if s["id"] == args.section), None)
    if section is None:
        valid = [s["id"] for s in outline["sections"]]
        raise SystemExit(f"unknown section {args.section!r}; valid: {valid}")
    src = sp.read_text() if sp.exists() else ""
    placeholder = f"[PLACEHOLDER: {section['title']}]"
    if placeholder in src:
        src = src.replace(placeholder, args.content)
    else:
        src += f"\n\n## {section['title']}\n{args.content}\n"
    sp.write_text(src)
    wc = count_words(args.content)
    section["word_count"] = wc
    section["status"] = "drafted"
    section["content_preview"] = args.content[:60]
    op.write_text(json.dumps(outline, indent=2))
    print(json.dumps({
        "dmp_id": args.dmp_id, "section": args.section,
        "word_count": wc, "status": "drafted",
    }, indent=2))


def cmd_status(args: argparse.Namespace) -> None:
    d = dmp_dir(args.dmp_id)
    mp = d / "manifest.json"
    op = d / "outline.json"
    if not mp.exists():
        raise FileNotFoundError(f"DMP {args.dmp_id!r} not found")
    manifest = json.loads(mp.read_text())
    outline = json.loads(op.read_text())
    sections = outline["sections"]
    drafted = sum(1 for s in sections if s.get("status") == "drafted")
    print(json.dumps({
        "dmp_id": args.dmp_id,
        "title": manifest["title"],
        "funder": manifest["funder"],
        "mechanism": manifest["mechanism"],
        "sections_total": len(sections),
        "sections_drafted": drafted,
        "total_words": sum(s.get("word_count", 0) for s in sections),
        "target_words": sum(s.get("target_words", 0) for s in sections),
    }, indent=2))


def cmd_funders(args: argparse.Namespace) -> None:
    out = []
    for k, v in FUNDERS.items():
        out.append({
            "funder": k, "label": v["label"],
            "mechanisms": v["mechanisms"],
            "default_mechanism": v["default_mechanism"],
            "n_sections": len(v["sections"]),
        })
    print(json.dumps(out, indent=2))


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("init")
    pi.add_argument("--title", required=True)
    pi.add_argument("--funder", required=True, choices=sorted(FUNDERS))
    pi.add_argument("--mechanism", default=None)
    pi.add_argument("--force", action="store_true", default=False)
    pi.set_defaults(func=cmd_init)
    ps = sub.add_parser("section")
    ps.add_argument("--dmp-id", required=True)
    ps.add_argument("--section", required=True)
    ps.add_argument("--content", required=True)
    ps.set_defaults(func=cmd_section)
    pst = sub.add_parser("status")
    pst.add_argument("--dmp-id", required=True)
    pst.set_defaults(func=cmd_status)
    pf = sub.add_parser("funders")
    pf.set_defaults(func=cmd_funders)
    args = p.parse_args()
    try:
        args.func(args)
    except (FileNotFoundError, ValueError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
