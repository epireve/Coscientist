#!/usr/bin/env python3
"""search-strategy-critique gate — validate + persist adversarial critique.

Refuses critiques that:
- Have a "high" severity finding but verdict "accept"
- Use hedge words in recommendation ("maybe", "could be", "potentially",
  "perhaps", "might")
- Lack a confidence number
- Have findings without specific sub_area / component references

On pass, writes critique JSON to runs.strategy_critique_json.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import run_db_path  # noqa: E402

HEDGE_PATTERN = re.compile(
    r"\b(maybe|might|could be|potentially|perhaps|possibly|seems? to|"
    r"appear[s]? to|may\b|kind of|sort of)\b",
    re.IGNORECASE,
)


def _validate(c: dict) -> list[str]:
    """Return list of validation errors. Empty list = pass."""
    errs: list[str] = []

    # Required keys
    for k in ("blind_spots", "missing_anti_coverage", "redundant_sub_areas",
              "premature_commitments", "verdict", "recommendation",
              "confidence"):
        if k not in c:
            errs.append(f"missing key: {k}")

    if errs:
        return errs

    # Verdict
    if c["verdict"] not in ("accept", "revise", "reject"):
        errs.append(
            f"verdict must be accept|revise|reject, got {c['verdict']!r}"
        )

    # Confidence
    conf = c.get("confidence")
    if not isinstance(conf, (int, float)):
        errs.append("confidence must be a number 0.0-1.0")
    elif not (0.0 <= conf <= 1.0):
        errs.append(f"confidence out of range: {conf}")

    # Hedge words in recommendation
    rec = c.get("recommendation", "")
    if HEDGE_PATTERN.search(rec):
        errs.append(
            f"recommendation contains hedge words; rewrite committedly. "
            f"Found: {HEDGE_PATTERN.findall(rec)}"
        )

    # High-severity finding inconsistent with accept verdict
    high_findings = [
        f for f in c.get("blind_spots", []) if f.get("severity") == "high"
    ]
    if high_findings and c.get("verdict") == "accept":
        errs.append(
            f"verdict 'accept' but {len(high_findings)} high-severity "
            f"blind_spots found — must be 'revise' or 'reject'"
        )

    # Findings without sub_area / component references
    for kind in ("missing_anti_coverage", "redundant_sub_areas",
                  "premature_commitments"):
        for i, f in enumerate(c.get(kind, [])):
            has_ref = any(
                k in f for k in ("sub_area", "sub_areas", "component",
                                  "phrasing")
            )
            if not has_ref:
                errs.append(
                    f"{kind}[{i}] lacks specific sub_area/component "
                    f"reference; finding is too abstract"
                )

    return errs


def cmd_validate(args: argparse.Namespace) -> dict:
    raw = Path(args.input).read_text()
    critique = json.loads(raw)
    errs = _validate(critique)
    if errs:
        return {"ok": False, "errors": errs}
    return {"ok": True, "verdict": critique["verdict"],
            "confidence": critique["confidence"],
            "n_blind_spots": len(critique["blind_spots"]),
            "n_anti_coverage": len(critique["missing_anti_coverage"]),
            "n_redundant": len(critique["redundant_sub_areas"]),
            "n_premature": len(critique["premature_commitments"])}


def cmd_persist(args: argparse.Namespace) -> dict:
    """Write critique to runs.strategy_critique_json. Validates first."""
    raw = Path(args.input).read_text()
    critique = json.loads(raw)
    errs = _validate(critique)
    if errs and not args.force:
        raise SystemExit(
            "validation failed; pass --force to persist anyway:\n"
            + "\n".join(f"  - {e}" for e in errs)
        )

    db = run_db_path(args.run_id)
    if not db.exists():
        raise SystemExit(f"run DB missing: {db}")

    con = sqlite3.connect(db)
    try:
        with con:
            con.execute(
                "UPDATE runs SET strategy_critique_json=? WHERE run_id=?",
                (json.dumps(critique, indent=2), args.run_id),
            )
    finally:
        con.close()

    return {
        "ok": True,
        "run_id": args.run_id,
        "verdict": critique["verdict"],
        "confidence": critique["confidence"],
        "validation_warnings": errs if errs else [],
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate",
                        help="Validate critique JSON without persisting")
    v.add_argument("--input", required=True,
                    help="Path to critique JSON file")
    v.set_defaults(func=cmd_validate)

    pp = sub.add_parser("persist",
                         help="Validate + persist to runs.strategy_critique_json")
    pp.add_argument("--run-id", required=True)
    pp.add_argument("--input", required=True,
                     help="Path to critique JSON file")
    pp.add_argument("--force", action="store_true",
                     help="Persist even if validation fails")
    pp.set_defaults(func=cmd_persist)

    args = p.parse_args()
    out = args.func(args)
    sys.stdout.write(json.dumps(out, indent=2) + "\n")


if __name__ == "__main__":
    main()
