#!/usr/bin/env python3
"""reviewer-assistant: scaffold a structured peer review."""
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

VALID_VENUES = {"neurips", "iclr", "nature", "generic"}
VALID_DECISIONS = {"accept", "weak-accept", "borderline", "weak-reject", "reject"}
VALID_SECTIONS = {"summary", "strengths", "weaknesses", "specific", "required"}
VALID_STATES = ("drafted", "submitted")

VENUE_TEMPLATES = {
    "neurips": {
        "tone": "Direct, technical",
        "target_words": 800,
        "extra_sections": ["soundness", "presentation", "contribution", "questions"],
    },
    "iclr": {
        "tone": "Public, rebuttal-aware",
        "target_words": 700,
        "extra_sections": ["soundness", "presentation", "contribution", "questions", "ethics"],
    },
    "nature": {
        "tone": "Editorial-style",
        "target_words": 500,
        "extra_sections": ["significance", "two_step_decision"],
    },
    "generic": {
        "tone": "Balanced",
        "target_words": 600,
        "extra_sections": [],
    },
}


def _slug(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:40].strip("_")


def make_review_id(target_title: str) -> str:
    h = hashlib.blake2s(target_title.encode(), digest_size=3).hexdigest()
    return f"{_slug(target_title)}_{h}"


def review_dir(review_id: str) -> Path:
    return cache_root() / "reviews" / review_id


def _load_manifest(review_id: str) -> dict:
    p = review_dir(review_id) / "manifest.json"
    if not p.exists():
        raise FileNotFoundError(f"review {review_id!r} not found")
    return json.loads(p.read_text())


def _load_review(review_id: str) -> dict:
    p = review_dir(review_id) / "review.json"
    if not p.exists():
        raise FileNotFoundError(f"review record not found for {review_id!r}")
    return json.loads(p.read_text())


def _save_manifest(review_id: str, manifest: dict) -> None:
    manifest["updated_at"] = datetime.now(UTC).isoformat()
    (review_dir(review_id) / "manifest.json").write_text(
        json.dumps(manifest, indent=2)
    )


def _save_review(review_id: str, review: dict) -> None:
    (review_dir(review_id) / "review.json").write_text(
        json.dumps(review, indent=2)
    )


def _register(project_id: str, review_id: str, state: str) -> None:
    try:
        from lib.project import register_artifact
        register_artifact(
            project_id=project_id,
            artifact_id=review_id,
            kind="review",
            state=state,
            path=review_dir(review_id),
        )
    except Exception as e:
        print(json.dumps({"warning": f"could not register: {e}"}), file=sys.stderr)


def cmd_init(args: argparse.Namespace) -> None:
    if args.venue not in VALID_VENUES:
        raise SystemExit(f"--venue must be one of {sorted(VALID_VENUES)}")
    if not args.target_title.strip():
        raise SystemExit("--target-title must be non-empty")

    review_id = make_review_id(args.target_title)
    rd = review_dir(review_id)
    if (rd / "manifest.json").exists() and not args.force:
        raise SystemExit(f"review {review_id!r} already exists. Use --force.")
    rd.mkdir(parents=True, exist_ok=True)

    template = VENUE_TEMPLATES[args.venue]
    now = datetime.now(UTC).isoformat()

    manifest = {
        "artifact_id": review_id,
        "kind": "review",
        "state": "drafted",
        "project_id": args.project_id,
        "created_at": now,
        "updated_at": now,
    }
    review = {
        "review_id": review_id,
        "target_title": args.target_title,
        "venue": args.venue,
        "tone": template["tone"],
        "target_words": template["target_words"],
        "extra_sections": template["extra_sections"],
        "summary": "",
        "strengths": [],
        "weaknesses": [],
        "specific": [],
        "required": [],
        "recommendation": None,
        "confidence": None,
        "expected_strengths_count": args.strengths_count,
        "expected_weaknesses_count": args.weaknesses_count,
        "created_at": now,
    }
    _save_manifest(review_id, manifest)
    _save_review(review_id, review)

    if args.project_id:
        _register(args.project_id, review_id, "drafted")

    print(json.dumps({
        "review_id": review_id,
        "venue": args.venue,
        "target_words": template["target_words"],
        "extra_sections": template["extra_sections"],
        "path": str(rd),
    }, indent=2))


def cmd_add_comment(args: argparse.Namespace) -> None:
    if args.section not in VALID_SECTIONS:
        raise SystemExit(f"--section must be one of {sorted(VALID_SECTIONS)}")
    if not args.comment.strip():
        raise SystemExit("--comment must be non-empty")

    review = _load_review(args.review_id)
    if args.section == "summary":
        review["summary"] = args.comment.strip()
    else:
        review[args.section].append(args.comment.strip())
    _save_review(args.review_id, review)

    print(json.dumps({
        "review_id": args.review_id,
        "section": args.section,
        "added": True,
        "current_count": (1 if args.section == "summary"
                          else len(review[args.section])),
    }, indent=2))


def cmd_set_recommendation(args: argparse.Namespace) -> None:
    if args.decision not in VALID_DECISIONS:
        raise SystemExit(
            f"--decision must be one of {sorted(VALID_DECISIONS)}"
        )
    if not (1 <= args.confidence <= 5):
        raise SystemExit("--confidence must be 1-5")

    review = _load_review(args.review_id)
    review["recommendation"] = args.decision
    review["confidence"] = args.confidence
    _save_review(args.review_id, review)

    print(json.dumps({
        "review_id": args.review_id,
        "recommendation": args.decision,
        "confidence": args.confidence,
    }, indent=2))


def _render_markdown(review: dict) -> str:
    lines = [
        f"# Review of: {review['target_title']}",
        "",
        f"**Venue:** {review['venue']}  ",
        f"**Recommendation:** {review.get('recommendation') or '*(not set)*'}  ",
        f"**Confidence:** {review.get('confidence') or '*(not set)*'} / 5",
        "",
        "## Summary",
        "",
        review.get("summary") or "*[Summary not yet written.]*",
        "",
        "## Strengths",
        "",
    ]
    for s in review.get("strengths", []):
        lines.append(f"- {s}")
    if not review.get("strengths"):
        lines.append("*[No strengths recorded.]*")
    lines.extend(["", "## Weaknesses", ""])
    for w in review.get("weaknesses", []):
        lines.append(f"- {w}")
    if not review.get("weaknesses"):
        lines.append("*[No weaknesses recorded.]*")
    lines.extend(["", "## Specific Comments", ""])
    for c in review.get("specific", []):
        lines.append(f"- {c}")
    if not review.get("specific"):
        lines.append("*[No specific comments.]*")
    lines.extend(["", "## Required Revisions", ""])
    for r in review.get("required", []):
        lines.append(f"- {r}")
    if not review.get("required"):
        lines.append("*[None required.]*")
    return "\n".join(lines)


def cmd_export(args: argparse.Namespace) -> None:
    review = _load_review(args.review_id)
    if args.format == "json":
        out = json.dumps(review, indent=2)
    elif args.format == "markdown":
        out = _render_markdown(review)
        # Write to source.md
        (review_dir(args.review_id) / "source.md").write_text(out)
    else:
        raise SystemExit(f"unknown format: {args.format}")
    print(out)


def cmd_status(args: argparse.Namespace) -> None:
    review = _load_review(args.review_id)
    manifest = _load_manifest(args.review_id)
    print(json.dumps({
        "review_id": args.review_id,
        "target_title": review["target_title"],
        "venue": review["venue"],
        "state": manifest["state"],
        "summary_set": bool(review.get("summary")),
        "strengths_count": len(review.get("strengths", [])),
        "weaknesses_count": len(review.get("weaknesses", [])),
        "specific_count": len(review.get("specific", [])),
        "required_count": len(review.get("required", [])),
        "recommendation": review.get("recommendation"),
        "confidence": review.get("confidence"),
        "ready_to_submit": bool(
            review.get("summary")
            and review.get("strengths")
            and review.get("weaknesses")
            and review.get("recommendation")
            and review.get("confidence")
        ),
    }, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Scaffold a structured peer review.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init")
    pi.add_argument("--target-title", required=True)
    pi.add_argument("--venue", required=True, choices=sorted(VALID_VENUES))
    pi.add_argument("--strengths-count", type=int, default=3)
    pi.add_argument("--weaknesses-count", type=int, default=3)
    pi.add_argument("--project-id", default=None)
    pi.add_argument("--force", action="store_true", default=False)
    pi.set_defaults(func=cmd_init)

    pa = sub.add_parser("add-comment")
    pa.add_argument("--review-id", required=True)
    pa.add_argument("--section", required=True, choices=sorted(VALID_SECTIONS))
    pa.add_argument("--comment", required=True)
    pa.set_defaults(func=cmd_add_comment)

    pr = sub.add_parser("set-recommendation")
    pr.add_argument("--review-id", required=True)
    pr.add_argument("--decision", required=True, choices=sorted(VALID_DECISIONS))
    pr.add_argument("--confidence", type=int, required=True)
    pr.set_defaults(func=cmd_set_recommendation)

    pe = sub.add_parser("export")
    pe.add_argument("--review-id", required=True)
    pe.add_argument("--format", default="markdown", choices=["markdown", "json"])
    pe.set_defaults(func=cmd_export)

    ps = sub.add_parser("status")
    ps.add_argument("--review-id", required=True)
    ps.set_defaults(func=cmd_status)

    args = p.parse_args()
    try:
        args.func(args)
    except (FileNotFoundError, ValueError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
