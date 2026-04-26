"""Grant outline data model and funder templates."""
from __future__ import annotations
import hashlib, json, re
from pathlib import Path

FUNDERS = {
    "nih": {
        "label": "NIH",
        "mechanisms": ["R01", "R21", "K99", "F31"],
        "default_mechanism": "R01",
        "sections": [
            {"id": "specific_aims", "title": "Specific Aims", "target_words": 400, "required": True,
             "notes": "One page. State objectives and central hypothesis. Three aims max."},
            {"id": "significance", "title": "Significance", "target_words": 500, "required": True,
             "notes": "Why is this important? What is the gap? What will change if you succeed?"},
            {"id": "innovation", "title": "Innovation", "target_words": 300, "required": True,
             "notes": "What is new? Avoid 'novel' without specifics. Name the prior approach and the delta."},
            {"id": "approach", "title": "Approach", "target_words": 2500, "required": True,
             "notes": "Experimental design per aim. Include pitfalls + alternatives for each."},
            {"id": "human_subjects", "title": "Human Subjects", "target_words": 300, "required": False,
             "notes": "IRB, risks, protections. N/A for non-human research."},
            {"id": "bibliography", "title": "Bibliography", "target_words": 0, "required": True,
             "notes": "No page limit. Use NIH citation format."},
        ],
    },
    "nsf": {
        "label": "NSF",
        "mechanisms": ["Standard", "CAREER", "RAPID", "EAGER"],
        "default_mechanism": "Standard",
        "sections": [
            {"id": "project_summary", "title": "Project Summary", "target_words": 250, "required": True,
             "notes": "One page. Overview, intellectual merit, broader impacts — all three required."},
            {"id": "project_description", "title": "Project Description", "target_words": 2500, "required": True,
             "notes": "15 pages max (standard). Objectives, methods, expected outcomes."},
            {"id": "broader_impacts", "title": "Broader Impacts", "target_words": 500, "required": True,
             "notes": "Not a footnote. Substantive section. Education, diversity, public benefit."},
            {"id": "references", "title": "References Cited", "target_words": 0, "required": True,
             "notes": "No page limit."},
            {"id": "facilities", "title": "Facilities and Resources", "target_words": 300, "required": False,
             "notes": "Equipment, computing, lab space available."},
        ],
    },
    "erc": {
        "label": "ERC",
        "mechanisms": ["Starting", "Consolidator", "Advanced", "Proof of Concept"],
        "default_mechanism": "Starting",
        "sections": [
            {"id": "extended_synopsis", "title": "Extended Synopsis", "target_words": 500, "required": True,
             "notes": "5 pages. Vision + frontier challenge + objectives."},
            {"id": "state_of_art", "title": "State of the Art and Beyond", "target_words": 1000, "required": True,
             "notes": "What is the frontier? Where does your idea go beyond it?"},
            {"id": "methodology", "title": "Methodology", "target_words": 1500, "required": True,
             "notes": "Work packages, milestones, risk management."},
            {"id": "resources", "title": "Resources", "target_words": 500, "required": True,
             "notes": "Team composition, budget justification, infrastructure."},
            {"id": "ethical_issues", "title": "Ethical Issues", "target_words": 200, "required": False,
             "notes": "Data protection, dual use, research ethics."},
        ],
    },
    "wellcome": {
        "label": "Wellcome Trust",
        "mechanisms": ["Discovery", "Investigator", "Collaborative"],
        "default_mechanism": "Discovery",
        "sections": [
            {"id": "scientific_abstract", "title": "Scientific Abstract", "target_words": 200, "required": True,
             "notes": "Plain language abstract. Non-specialist readable."},
            {"id": "background", "title": "Background and Rationale", "target_words": 800, "required": True,
             "notes": "The problem, what is known, why now."},
            {"id": "research_plan", "title": "Research Plan", "target_words": 1500, "required": True,
             "notes": "Objectives, approach, deliverables. Patient/public involvement if applicable."},
            {"id": "team", "title": "Team and Environment", "target_words": 400, "required": True,
             "notes": "Why this team? Track record. Collaborators."},
            {"id": "impact", "title": "Impact and Translation", "target_words": 400, "required": True,
             "notes": "Wellcome mission alignment. Health impact pathway."},
            {"id": "references", "title": "References", "target_words": 0, "required": True,
             "notes": "No page limit."},
        ],
    },
}


def _slug(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:40].strip("_")


def make_grant_id(title: str, funder: str) -> str:
    h = hashlib.blake2s(f"{title}::{funder}".encode(), digest_size=3).hexdigest()
    return f"{_slug(title)}_{_slug(funder)}_{h}"


def get_template(funder: str, mechanism: str | None = None) -> dict:
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


def build_outline(title: str, funder: str, mechanism: str | None = None) -> dict:
    tmpl = get_template(funder, mechanism)
    sections = []
    for s in tmpl["sections"]:
        sections.append({
            **s,
            "status": "placeholder",
            "word_count": 0,
            "content_preview": "",
        })
    return {
        "title": title,
        "funder": funder,
        "mechanism": tmpl["mechanism"],
        "sections": sections,
    }


def build_source_md(outline: dict) -> str:
    lines = [
        f"---",
        f"title: \"{outline['title']}\"",
        f"funder: {outline['funder']}",
        f"mechanism: {outline['mechanism']}",
        f"---",
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


def extract_section(source: str, section_title: str) -> str:
    lines = source.splitlines()
    in_section = False
    content_lines = []
    for line in lines:
        if line.strip() == f"## {section_title}":
            in_section = True
            continue
        if in_section:
            if line.startswith("## ") and line.strip() != f"## {section_title}":
                break
            content_lines.append(line)
    return "\n".join(content_lines).strip()
