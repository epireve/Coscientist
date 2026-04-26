#!/usr/bin/env python3
"""idea-attacker gate: validate + optionally persist an attack report.

Usage:
  python gate.py --input /tmp/attack.json [--project-id P] [--hyp-id H]

Exit codes:
  0 = valid
  1 = structural error (missing fields, bad values)
  2 = content error (generic evidence, missing steelman on fatal, etc.)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402

KNOWN_ATTACKS = {
    "untestable",
    "already-known",
    "confounded-by-design",
    "base-rate-neglect",
    "scope-too-broad",
    "implementation-wall",
    "incentive-problem",
    "measurement-gap",
    "wrong-level",
    "status-quo-survives",
}

VALID_VERDICTS = {"pass", "minor", "fatal"}

GENERIC_PHRASES = {
    "needs more work",
    "unclear",
    "not sure",
    "could be better",
    "requires further",
    "may be",
    "might be",
}


def _is_generic(text: str) -> bool:
    t = text.lower().strip()
    return any(ph in t for ph in GENERIC_PHRASES) or len(t.split()) < 5


def validate(report: dict) -> tuple[list[str], list[str]]:
    """Return (structural_errors, content_errors)."""
    struct: list[str] = []
    content: list[str] = []

    # Top-level required fields
    if not report.get("statement", "").strip():
        struct.append("missing 'statement'")
    if not report.get("steelman", "").strip():
        struct.append("missing top-level 'steelman'")
    if not report.get("weakest_link", "").strip():
        struct.append("missing 'weakest_link'")
    survival = report.get("survival")
    if not isinstance(survival, int) or not (1 <= survival <= 5):
        struct.append(f"'survival' must be int 1–5, got {survival!r}")
    if not report.get("survival_reasoning", "").strip():
        struct.append("missing 'survival_reasoning'")

    attacks = report.get("attacks")
    if not isinstance(attacks, list):
        struct.append("'attacks' must be a list")
        return struct, content

    seen: set[str] = set()
    attack_names: set[str] = set()
    for a in attacks:
        name = a.get("attack", "")
        if name not in KNOWN_ATTACKS:
            struct.append(f"unknown attack: {name!r}")
        if name in seen:
            struct.append(f"duplicate attack: {name!r}")
        seen.add(name)
        attack_names.add(name)

        verdict = a.get("verdict", "")
        if verdict not in VALID_VERDICTS:
            struct.append(f"[{name}] verdict {verdict!r} not in {VALID_VERDICTS}")

        evidence = (a.get("evidence") or "").strip()
        if verdict != "pass" and not evidence:
            struct.append(f"[{name}] non-pass verdict requires evidence")
        elif verdict != "pass" and _is_generic(evidence):
            content.append(
                f"[{name}] evidence is too generic: {evidence[:80]!r}"
            )

        if verdict == "fatal":
            st = (a.get("steelman") or "").strip()
            if not st:
                struct.append(f"[{name}] fatal verdict requires steelman")
            kt = (a.get("killer_test") or "").strip()
            if not kt:
                struct.append(f"[{name}] fatal verdict requires killer_test")

        if verdict in ("minor", "fatal"):
            kt = (a.get("killer_test") or "").strip()
            if not kt:
                content.append(
                    f"[{name}] non-pass verdict should have a killer_test"
                )

    missing = KNOWN_ATTACKS - attack_names
    for m in sorted(missing):
        struct.append(f"missing required attack: {m!r}")

    # weakest_link must name a known attack
    wl = report.get("weakest_link", "")
    if wl and wl not in KNOWN_ATTACKS:
        struct.append(
            f"'weakest_link' {wl!r} must be one of the 10 attack keys"
        )

    return struct, content


def persist(report: dict, project_id: str) -> None:
    """Write report to projects/<pid>/idea_attacks/<hyp_id>.json."""
    hyp_id = report.get("hyp_id") or "unnamed"
    attacks_dir = cache_root() / "projects" / project_id / "idea_attacks"
    attacks_dir.mkdir(parents=True, exist_ok=True)
    out = attacks_dir / f"{hyp_id}.json"
    out.write_text(json.dumps(report, indent=2))

    # Append a journal entry row if the project DB exists
    db_path = cache_root() / "projects" / project_id / "project.db"
    if db_path.exists():
        import sqlite3
        survival = report.get("survival", "?")
        statement = report.get("statement", "")[:80]
        fatals = sum(
            1 for a in report.get("attacks", []) if a.get("verdict") == "fatal"
        )
        minors = sum(
            1 for a in report.get("attacks", []) if a.get("verdict") == "minor"
        )
        body = (
            f"idea-attacker report for hyp_id={hyp_id!r}: "
            f"survival={survival}/5, {fatals} fatal / {minors} minor. "
            f"Idea: {statement}…"
        )
        try:
            con = sqlite3.connect(db_path)
            con.execute(
                "INSERT INTO journal_entries "
                "(project_id, entry_date, body, tags, links, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    project_id,
                    datetime.now(UTC).date().isoformat(),
                    body,
                    json.dumps(["idea-attack", "adversarial"]),
                    json.dumps({}),
                    datetime.now(UTC).isoformat(),
                ),
            )
            con.commit()
            con.close()
        except Exception:
            pass  # journal write is best-effort


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, help="Path to attack report JSON")
    p.add_argument("--project-id", default=None, help="Persist to project DB")
    p.add_argument("--hyp-id", default=None, help="Override hyp_id in report")
    args = p.parse_args()

    report_path = Path(args.input)
    if not report_path.exists():
        print(json.dumps({"error": f"file not found: {args.input}"}), file=sys.stderr)
        sys.exit(1)

    try:
        report = json.loads(report_path.read_text())
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"invalid JSON: {e}"}), file=sys.stderr)
        sys.exit(1)

    if args.hyp_id:
        report["hyp_id"] = args.hyp_id

    struct_errors, content_errors = validate(report)

    if struct_errors:
        print(
            json.dumps({"status": "rejected", "structural_errors": struct_errors, "content_errors": content_errors}),
            file=sys.stderr,
        )
        sys.exit(1)

    if content_errors:
        print(
            json.dumps({"status": "rejected", "structural_errors": [], "content_errors": content_errors}),
            file=sys.stderr,
        )
        sys.exit(2)

    if args.project_id:
        persist(report, args.project_id)
        print(json.dumps({"status": "accepted", "persisted": True, "project_id": args.project_id}))
    else:
        print(json.dumps({"status": "accepted", "persisted": False}))


if __name__ == "__main__":
    main()
