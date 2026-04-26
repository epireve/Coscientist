#!/usr/bin/env python3
"""credit-tracker: CRediT taxonomy per-manuscript contribution tracking."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402

CREDIT_ROLES = [
    "conceptualization",
    "data-curation",
    "formal-analysis",
    "funding-acquisition",
    "investigation",
    "methodology",
    "project-administration",
    "resources",
    "software",
    "supervision",
    "validation",
    "visualization",
    "writing-original-draft",
    "writing-review-editing",
]
CREDIT_ROLE_SET = set(CREDIT_ROLES)

# Required: every manuscript must have ≥1 author per role
REQUIRED_ROLES = {
    "conceptualization",
    "methodology",
    "writing-original-draft",
}
RECOMMENDED_ROLES = {
    "formal-analysis",
    "investigation",
    "writing-review-editing",
}

# Display labels (CRediT canonical capitalization)
ROLE_LABELS = {
    "conceptualization": "Conceptualization",
    "data-curation": "Data curation",
    "formal-analysis": "Formal analysis",
    "funding-acquisition": "Funding acquisition",
    "investigation": "Investigation",
    "methodology": "Methodology",
    "project-administration": "Project administration",
    "resources": "Resources",
    "software": "Software",
    "supervision": "Supervision",
    "validation": "Validation",
    "visualization": "Visualization",
    "writing-original-draft": "Writing — original draft",
    "writing-review-editing": "Writing — review & editing",
}


def credit_dir(manuscript_id: str) -> Path:
    d = cache_root() / "manuscripts" / manuscript_id / "credit"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _contrib_path(manuscript_id: str) -> Path:
    return credit_dir(manuscript_id) / "contributions.json"


def _load(manuscript_id: str) -> dict[str, list[str]]:
    p = _contrib_path(manuscript_id)
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def _save(manuscript_id: str, data: dict[str, list[str]]) -> None:
    _contrib_path(manuscript_id).write_text(json.dumps(data, indent=2, sort_keys=True))


def _parse_roles(roles_str: str) -> list[str]:
    raw = [r.strip().lower() for r in roles_str.split(",") if r.strip()]
    invalid = [r for r in raw if r not in CREDIT_ROLE_SET]
    if invalid:
        raise SystemExit(
            f"unknown CRediT role(s): {invalid}. Valid: {CREDIT_ROLES}"
        )
    # dedupe preserving order
    seen = set()
    out = []
    for r in raw:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def cmd_assign(args: argparse.Namespace) -> None:
    if not args.author.strip():
        raise SystemExit("--author must be non-empty")
    new_roles = _parse_roles(args.roles)
    if not new_roles:
        raise SystemExit("--roles must list at least one role")

    data = _load(args.manuscript_id)
    existing = set(data.get(args.author, []))
    merged = sorted(existing | set(new_roles))
    data[args.author] = merged
    _save(args.manuscript_id, data)

    print(json.dumps({
        "manuscript_id": args.manuscript_id,
        "author": args.author,
        "roles": merged,
        "added": [r for r in new_roles if r not in existing],
    }, indent=2))


def cmd_unassign(args: argparse.Namespace) -> None:
    data = _load(args.manuscript_id)
    if args.author not in data:
        raise SystemExit(f"author {args.author!r} not found in contributions")

    if args.roles:
        remove = set(_parse_roles(args.roles))
        kept = [r for r in data[args.author] if r not in remove]
        if kept:
            data[args.author] = kept
        else:
            del data[args.author]
    else:
        del data[args.author]
    _save(args.manuscript_id, data)

    print(json.dumps({
        "manuscript_id": args.manuscript_id,
        "author": args.author,
        "remaining_roles": data.get(args.author, []),
    }, indent=2))


def cmd_list(args: argparse.Namespace) -> None:
    data = _load(args.manuscript_id)
    print(json.dumps({
        "manuscript_id": args.manuscript_id,
        "authors": data,
        "total_authors": len(data),
    }, indent=2))


def cmd_audit(args: argparse.Namespace) -> None:
    data = _load(args.manuscript_id)
    role_to_authors: dict[str, list[str]] = {r: [] for r in CREDIT_ROLES}
    for author, roles in data.items():
        for r in roles:
            role_to_authors[r].append(author)

    missing_required = [r for r in REQUIRED_ROLES if not role_to_authors[r]]
    missing_recommended = [r for r in RECOMMENDED_ROLES if not role_to_authors[r]]
    no_role_authors = [a for a, rs in data.items() if not rs]

    passed = not missing_required and not no_role_authors

    print(json.dumps({
        "manuscript_id": args.manuscript_id,
        "passed": passed,
        "missing_required_roles": sorted(missing_required),
        "missing_recommended_roles": sorted(missing_recommended),
        "authors_without_roles": no_role_authors,
        "role_coverage": {r: len(role_to_authors[r]) for r in CREDIT_ROLES},
        "total_authors": len(data),
    }, indent=2))

    if not passed:
        sys.exit(1)


def cmd_statement(args: argparse.Namespace) -> None:
    data = _load(args.manuscript_id)
    if not data:
        raise SystemExit(f"no contributions recorded for {args.manuscript_id!r}")

    if args.style == "narrative":
        lines = []
        for author in sorted(data):
            roles = data[author]
            labels = [ROLE_LABELS[r] for r in roles]
            lines.append(f"**{author}**: {', '.join(labels)}.")
        statement = "\n".join(lines)
        print(statement)
    elif args.style == "table":
        # Build markdown table: rows = authors, cols = roles
        used_roles = sorted({r for rs in data.values() for r in rs},
                            key=lambda r: CREDIT_ROLES.index(r))
        header = "| Author | " + " | ".join(ROLE_LABELS[r] for r in used_roles) + " |"
        sep = "|" + "---|" * (len(used_roles) + 1)
        rows = [header, sep]
        for author in sorted(data):
            cells = [author]
            for r in used_roles:
                cells.append("✓" if r in data[author] else "")
            rows.append("| " + " | ".join(cells) + " |")
        print("\n".join(rows))
    else:
        raise SystemExit(f"unknown style: {args.style}")


def cmd_roles(args: argparse.Namespace) -> None:
    print(json.dumps({
        "roles": CREDIT_ROLES,
        "required": sorted(REQUIRED_ROLES),
        "recommended": sorted(RECOMMENDED_ROLES),
        "labels": ROLE_LABELS,
    }, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="CRediT taxonomy per manuscript.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("assign")
    pa.add_argument("--manuscript-id", required=True)
    pa.add_argument("--author", required=True)
    pa.add_argument("--roles", required=True,
                    help="Comma-separated role keys (e.g. conceptualization,methodology)")
    pa.set_defaults(func=cmd_assign)

    pu = sub.add_parser("unassign")
    pu.add_argument("--manuscript-id", required=True)
    pu.add_argument("--author", required=True)
    pu.add_argument("--roles", default=None,
                    help="If omitted, removes the author entirely")
    pu.set_defaults(func=cmd_unassign)

    pl = sub.add_parser("list")
    pl.add_argument("--manuscript-id", required=True)
    pl.set_defaults(func=cmd_list)

    pad = sub.add_parser("audit")
    pad.add_argument("--manuscript-id", required=True)
    pad.set_defaults(func=cmd_audit)

    ps = sub.add_parser("statement")
    ps.add_argument("--manuscript-id", required=True)
    ps.add_argument("--style", default="narrative", choices=["narrative", "table"])
    ps.set_defaults(func=cmd_statement)

    pr = sub.add_parser("roles")
    pr.set_defaults(func=cmd_roles)

    args = p.parse_args()
    try:
        args.func(args)
    except (FileNotFoundError, ValueError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
