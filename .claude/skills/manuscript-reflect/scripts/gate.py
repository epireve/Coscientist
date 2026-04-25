#!/usr/bin/env python3
"""manuscript-reflect gate: enforce structural-reflection fields."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root, run_db_path  # noqa: E402

HEDGE_WORDS = re.compile(
    r"\b(maybe|perhaps|potentially|could\s+be|might\s+be|possibly|seems?\s+to|appears?\s+to)\b",
    re.IGNORECASE,
)
VAGUE_EXPERIMENT = re.compile(
    r"^(more research|further investigation|additional study|future work|do more)\b",
    re.IGNORECASE,
)
VALID_FRAGILITY = {"low", "medium", "high"}


def _strip_quoted(text: str) -> str:
    """Remove quoted spans before hedge scanning (v0.12.1)."""
    if not text:
        return ""
    text = re.sub(r'"[^"]*"', " ", text)
    text = re.sub(r"'[^']*'", " ", text)
    text = re.sub(r"`[^`]*`", " ", text)
    return text


def validate(report: dict) -> list[str]:
    errors: list[str] = []

    arg = report.get("argument_structure") or {}
    for field in ("thesis", "conclusion"):
        if not (arg.get(field) or "").strip():
            errors.append(f"argument_structure.{field} missing")
    premises = arg.get("premises") or []
    if len(premises) < 2:
        errors.append(f"premises: {len(premises)} — need ≥2")
    chain = arg.get("evidence_chain") or []
    if not chain:
        errors.append("evidence_chain empty")
    for i, e in enumerate(chain):
        if not (e.get("claim") or "").strip():
            errors.append(f"evidence_chain[{i}] missing claim")
        try:
            s = float(e.get("strength"))
            if not 0.0 <= s <= 1.0:
                errors.append(f"evidence_chain[{i}] strength {s} outside [0,1]")
        except (TypeError, ValueError):
            errors.append(f"evidence_chain[{i}] strength missing/invalid")

    assumptions = report.get("implicit_assumptions") or []
    if len(assumptions) < 2:
        errors.append(f"implicit_assumptions: {len(assumptions)} — need ≥2")
    for i, a in enumerate(assumptions):
        if not (a.get("assumption") or "").strip():
            errors.append(f"implicit_assumptions[{i}] missing text")
        if a.get("fragility") not in VALID_FRAGILITY:
            errors.append(f"implicit_assumptions[{i}] fragility not in {VALID_FRAGILITY}")

    weakest = report.get("weakest_link") or {}
    for field in ("what", "why"):
        if not (weakest.get(field) or "").strip():
            errors.append(f"weakest_link.{field} missing")

    exp = report.get("one_experiment") or {}
    for field in ("description", "expected_impact"):
        if not (exp.get(field) or "").strip():
            errors.append(f"one_experiment.{field} missing")
    if exp.get("description") and VAGUE_EXPERIMENT.match(exp["description"].strip()):
        errors.append("one_experiment.description is too vague (looks like a research program)")

    # hedge-word scan across key prose fields (v0.12.1: skip quoted spans)
    for section, text in (
        ("thesis", arg.get("thesis", "")),
        ("conclusion", arg.get("conclusion", "")),
        ("weakest_link.why", weakest.get("why", "")),
        ("one_experiment.description", exp.get("description", "")),
    ):
        if text and HEDGE_WORDS.search(_strip_quoted(text)):
            errors.append(f"{section} contains hedge word (outside quotes)")

    return errors


def _write_reflection(con: sqlite3.Connection, manuscript_id: str,
                       report: dict, now: str) -> None:
    with con:
        con.execute(
            "INSERT OR REPLACE INTO manuscript_reflections "
            "(manuscript_id, thesis, weakest_link, one_experiment, report_json, at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                manuscript_id,
                report["argument_structure"]["thesis"],
                json.dumps(report["weakest_link"]),
                json.dumps(report["one_experiment"]),
                json.dumps(report),
                now,
            ),
        )


def persist(report: dict, manuscript_id: str,
            run_id: str | None, project_id: str | None) -> Path:
    out_dir = cache_root() / "manuscripts" / manuscript_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "reflect_report.json"
    out.write_text(json.dumps(report, indent=2))

    now = datetime.now(UTC).isoformat()

    if run_id:
        db = run_db_path(run_id)
        if db.exists():
            con = sqlite3.connect(db)
            _write_reflection(con, manuscript_id, report, now)
            con.close()

    if project_id:
        proj_db = cache_root() / "projects" / project_id / "project.db"
        if proj_db.exists():
            con = sqlite3.connect(proj_db)
            _write_reflection(con, manuscript_id, report, now)
            con.close()

    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--manuscript-id", required=True)
    p.add_argument("--run-id", default=None)
    p.add_argument("--project-id", default=None)
    args = p.parse_args()

    report = json.loads(Path(args.input).read_text())
    errors = validate(report)
    if errors:
        print("[manuscript-reflect] REJECTED", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(2)

    out = persist(report, args.manuscript_id, args.run_id, args.project_id)
    print(f"[manuscript-reflect] OK → {out}")


if __name__ == "__main__":
    main()
