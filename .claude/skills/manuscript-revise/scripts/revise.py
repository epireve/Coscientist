#!/usr/bin/env python3
"""manuscript-revise: respond-to-reviewers workflow.

Subcommands
-----------
ingest-review  Parse a review file into review.json; print reviewer/comment summary.
plan           Read review.json + source.md + outline.json; write revision_notes.md.
respond        Read review.json + revision_notes.md; write response_letter.md with
               point-by-point stubs. Advances state to 'revised' on success.
status         Count [YOUR RESPONSE HERE] placeholders remaining in response_letter.md.

Typical workflow
----------------
  python revise.py ingest-review --manuscript-id <mid> --review-file reviews.txt
  python revise.py plan          --manuscript-id <mid>
  python revise.py respond       --manuscript-id <mid>
  # (agent / author fills in [YOUR RESPONSE HERE] stubs)
  python revise.py status        --manuscript-id <mid>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.artifact import ManuscriptArtifact  # noqa: E402
from review_parser import count_comments, format_response_stub, parse_review  # noqa: E402

_PLACEHOLDER = "[YOUR RESPONSE HERE]"

# States from which ingest-review is forbidden (past the revision window)
_BLOCKED_STATES = {"submitted", "published"}
# States that are acceptable inputs
_ACCEPTED_STATES = {"drafted", "audited", "critiqued"}


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _load_review_json(art: ManuscriptArtifact) -> list[dict]:
    review_path = art.root / "review.json"
    if not review_path.exists():
        print(
            f"ERROR: review.json not found in {art.root}. "
            "Run 'ingest-review' first.",
            file=sys.stderr,
        )
        sys.exit(1)
    data = json.loads(review_path.read_text())
    # Flatten reviewers → comments list
    flat: list[dict] = []
    for reviewer in data.get("reviewers", []):
        rid = reviewer["id"]
        for c in reviewer.get("comments", []):
            flat.append({"reviewer": rid, "comment_num": c["num"], "text": c["text"]})
    return flat


def _load_outline_sections(art: ManuscriptArtifact) -> list[str]:
    """Return section names from outline.json, or empty list if missing."""
    outline_path = art.root / "outline.json"
    if not outline_path.exists():
        return []
    outline = json.loads(outline_path.read_text())
    return [s["name"] for s in outline.get("sections", [])]


def _load_source_headings(art: ManuscriptArtifact) -> list[str]:
    """Return markdown ## headings from source.md, or empty list if missing."""
    source_path = art.root / "source.md"
    if not source_path.exists():
        return []
    headings = re.findall(r"^##\s+(.+)$", source_path.read_text(), re.MULTILINE)
    return headings


# --------------------------------------------------------------------------- #
# Subcommand: ingest-review                                                    #
# --------------------------------------------------------------------------- #

def cmd_ingest_review(args: argparse.Namespace) -> int:
    art = ManuscriptArtifact(args.manuscript_id)

    # State guard
    m = art.load_manifest()
    state = m.state
    if state in _BLOCKED_STATES and not args.force:
        print(
            f"ERROR: manuscript is in state '{state}'. "
            "Revision after submission/publication is not supported. "
            "Use --force to override.",
            file=sys.stderr,
        )
        return 2

    # Read review text
    if args.review_file:
        review_path = Path(args.review_file).expanduser().resolve()
        if not review_path.exists():
            print(f"ERROR: review file not found: {review_path}", file=sys.stderr)
            return 1
        review_text = review_path.read_text()
    elif args.review_text:
        review_text = args.review_text
    elif not sys.stdin.isatty():
        review_text = sys.stdin.read()
    else:
        print(
            "ERROR: provide --review-file, --review-text, or pipe text via stdin.",
            file=sys.stderr,
        )
        return 2

    if not review_text.strip():
        print("ERROR: review text is empty.", file=sys.stderr)
        return 1

    parsed = parse_review(review_text)
    if not parsed:
        print("WARNING: no reviewer comments found in the review text.", file=sys.stderr)

    # Build the canonical review.json structure
    reviewer_map: dict[int, list[dict]] = {}
    for c in parsed:
        reviewer_map.setdefault(c["reviewer"], []).append(c)

    reviewers_data = []
    for rid in sorted(reviewer_map):
        comments = sorted(reviewer_map[rid], key=lambda x: x["comment_num"])
        reviewers_data.append({
            "id": rid,
            "comments": [{"num": c["comment_num"], "text": c["text"]} for c in comments],
        })

    review_json = {"reviewers": reviewers_data}
    (art.root / "review.json").write_text(json.dumps(review_json, indent=2))

    counts = count_comments(parsed)
    n_reviewers = len(counts)
    n_comments = sum(counts.values())
    print(f"{n_reviewers} reviewer(s), {n_comments} comment(s) total")
    for rid in sorted(counts):
        print(f"  Reviewer {rid}: {counts[rid]} comment(s)")
    return 0


# --------------------------------------------------------------------------- #
# Subcommand: plan                                                             #
# --------------------------------------------------------------------------- #

def cmd_plan(args: argparse.Namespace) -> int:
    art = ManuscriptArtifact(args.manuscript_id)

    comments = _load_review_json(art)
    sections = _load_outline_sections(art)
    headings = _load_source_headings(art)

    # Use section names from outline if available; fall back to headings from source.md
    all_sections = sections if sections else [h.lower() for h in headings]

    lines: list[str] = [
        "# Revision Notes",
        "",
        f"Manuscript: `{args.manuscript_id}`",
        f"Total comments: {len(comments)}",
        "",
        "This document maps reviewer comments to manuscript sections. "
        "Each entry notes the comment source and a suggested action.",
        "",
    ]

    if all_sections:
        lines += [
            "## Sections",
            "",
        ]
        # Group comments by likely section target
        # Simple heuristic: match comment text keywords against section names
        section_comments: dict[str, list[dict]] = {s: [] for s in all_sections}
        unmatched: list[dict] = []

        def _best_section(comment_text: str) -> str | None:
            text_lower = comment_text.lower()
            best = None
            best_score = 0
            for sec in all_sections:
                # Tokenize section name into words and count matches
                words = re.findall(r"[a-z]+", sec.lower())
                score = sum(1 for w in words if len(w) > 3 and w in text_lower)
                if score > best_score:
                    best_score = score
                    best = sec
            return best if best_score > 0 else None

        for c in comments:
            target = _best_section(c["text"])
            if target:
                section_comments[target].append(c)
            else:
                unmatched.append(c)

        for sec in all_sections:
            # Capitalize section heading for display
            display = sec.replace("_", " ").title()
            lines += [f"### {display}", ""]
            matched = section_comments.get(sec, [])
            if matched:
                for c in matched:
                    lines += [
                        f"- **[R{c['reviewer']}C{c['comment_num']}]** "
                        f"(Reviewer {c['reviewer']}, Comment {c['comment_num']}): "
                        f"{c['text'][:120]}{'...' if len(c['text']) > 120 else ''}",
                        f"  - *Action*: [DESCRIBE REVISION HERE]",
                        "",
                    ]
            else:
                lines += ["*(no comments directly mapped to this section)*", ""]

        if unmatched:
            lines += [
                "### General / Cross-cutting",
                "",
            ]
            for c in unmatched:
                lines += [
                    f"- **[R{c['reviewer']}C{c['comment_num']}]** "
                    f"(Reviewer {c['reviewer']}, Comment {c['comment_num']}): "
                    f"{c['text'][:120]}{'...' if len(c['text']) > 120 else ''}",
                    f"  - *Action*: [DESCRIBE REVISION HERE]",
                    "",
                ]
    else:
        # No outline — just list all comments with action stubs
        lines += [
            "## Comments and Planned Revisions",
            "",
        ]
        for c in comments:
            lines += [
                f"### Reviewer {c['reviewer']}, Comment {c['comment_num']}",
                "",
                c["text"],
                "",
                "**Planned action**: [DESCRIBE REVISION HERE]",
                "",
            ]

    notes_text = "\n".join(lines)
    (art.root / "revision_notes.md").write_text(notes_text)
    print(f"revision_notes.md written ({len(comments)} comment(s) mapped)")
    return 0


# --------------------------------------------------------------------------- #
# Subcommand: respond                                                          #
# --------------------------------------------------------------------------- #

def cmd_respond(args: argparse.Namespace) -> int:
    art = ManuscriptArtifact(args.manuscript_id)

    comments = _load_review_json(art)

    # Check for revision_notes.md (optional but expected)
    notes_path = art.root / "revision_notes.md"
    if not notes_path.exists():
        print(
            "WARNING: revision_notes.md not found. "
            "Run 'plan' first for best results. Continuing anyway.",
            file=sys.stderr,
        )

    # Build manifest info for the header
    m = art.load_manifest()
    title = m.extras.get("title", args.manuscript_id)

    header_lines = [
        "# Response to Reviewers",
        "",
        f"**Manuscript**: {title}",
        f"**Manuscript ID**: `{args.manuscript_id}`",
        "",
        "Dear Editor,",
        "",
        "We thank the reviewers for their careful reading and constructive "
        "feedback. Below we address each comment point by point.",
        "",
        "---",
        "",
    ]

    body_lines: list[str] = []
    for c in comments:
        stub = format_response_stub(c)
        body_lines.append(stub)
        body_lines.append("")

    letter_text = "\n".join(header_lines) + "\n".join(body_lines)
    (art.root / "response_letter.md").write_text(letter_text)

    # Advance state to revised
    try:
        art.set_state("revised")
    except ValueError as e:
        print(f"WARNING: could not advance state: {e}", file=sys.stderr)

    n_stubs = letter_text.count(_PLACEHOLDER)
    print(f"response_letter.md written ({len(comments)} comment(s), {n_stubs} stubs)")
    print(f"manuscript state: revised")
    return 0


# --------------------------------------------------------------------------- #
# Subcommand: status                                                           #
# --------------------------------------------------------------------------- #

def cmd_status(args: argparse.Namespace) -> int:
    art = ManuscriptArtifact(args.manuscript_id)
    letter_path = art.root / "response_letter.md"

    if not letter_path.exists():
        print("ERROR: response_letter.md not found. Run 'respond' first.", file=sys.stderr)
        return 1

    text = letter_path.read_text()
    n_remaining = text.count(_PLACEHOLDER)
    print(f"{n_remaining} stubs remaining")
    return 0


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #

def main() -> int:
    p = argparse.ArgumentParser(
        prog="revise.py",
        description="Respond-to-reviewers workflow for a manuscript artifact.",
    )
    sub = p.add_subparsers(dest="subcommand", required=True)

    # ingest-review
    pir = sub.add_parser("ingest-review", help="Parse review file into review.json")
    pir.add_argument("--manuscript-id", required=True, dest="manuscript_id",
                     help="Manuscript artifact ID")
    pir.add_argument("--review-file", dest="review_file",
                     help="Path to plain-text review file")
    pir.add_argument("--review-text", dest="review_text",
                     help="Review text supplied inline (alternative to --review-file)")
    pir.add_argument("--force", action="store_true",
                     help="Override state guard (allow submitted/published)")

    # plan
    pp = sub.add_parser("plan", help="Write revision_notes.md action plan")
    pp.add_argument("--manuscript-id", required=True, dest="manuscript_id")

    # respond
    pr = sub.add_parser("respond", help="Write response_letter.md stubs; advance state")
    pr.add_argument("--manuscript-id", required=True, dest="manuscript_id")

    # status
    ps = sub.add_parser("status", help="Count [YOUR RESPONSE HERE] stubs remaining")
    ps.add_argument("--manuscript-id", required=True, dest="manuscript_id")

    args = p.parse_args()
    dispatch = {
        "ingest-review": cmd_ingest_review,
        "plan": cmd_plan,
        "respond": cmd_respond,
        "status": cmd_status,
    }
    return dispatch[args.subcommand](args)


if __name__ == "__main__":
    sys.exit(main())
