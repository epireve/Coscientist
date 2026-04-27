#!/usr/bin/env python3
"""novelty-check gate: enforce structure on a novelty report before acceptance.

Rejects:
- contributions with fewer than 5 prior-work anchors
- verdicts of 'novel' where no anchor has delta_sufficient=true
- verdicts containing hedge words
- missing confidence numbers

On pass, writes novelty_assessment.json into the target paper artifact
and inserts a row into novelty_assessments (if target run DB is
provided).
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import paper_dir, run_db_path  # noqa: E402

MIN_ANCHORS = 5
HEDGE_WORDS = re.compile(
    r"\b(maybe|perhaps|potentially|could\s+be|might\s+be|possibly|seems?\s+to|appears?\s+to|somewhat|arguably)\b",
    re.IGNORECASE,
)
VALID_VERDICTS = {"novel", "incremental", "not-novel"}


def _strip_quoted(text: str) -> str:
    """Remove quoted spans before hedge scanning (v0.12.1).

    A hedge word inside quotes (e.g. quoting another paper) is not the
    auditor's hedge. Strip "..." 'sometext' and `code` spans first.
    """
    if not text:
        return ""
    text = re.sub(r'"[^"]*"', " ", text)
    text = re.sub(r"'[^']*'", " ", text)
    text = re.sub(r"`[^`]*`", " ", text)
    return text


def validate(report: dict) -> list[str]:
    errors: list[str] = []
    contribs = report.get("contributions")
    if not isinstance(contribs, list) or not contribs:
        return ["no contributions in report"]

    for c in contribs:
        cid = c.get("id", "?")
        decomp = c.get("decomposition") or {}
        for key in ("method", "domain", "finding", "metric"):
            if not decomp.get(key):
                errors.append(f"[{cid}] decomposition missing '{key}'")

        anchors = c.get("anchors") or []
        if len(anchors) < MIN_ANCHORS:
            errors.append(
                f"[{cid}] only {len(anchors)} anchors — need ≥{MIN_ANCHORS}"
            )
        # v0.12.1: anchor uniqueness — five copies of the same paper isn't five anchors
        unique_cids = {
            a.get("canonical_id") for a in anchors if a.get("canonical_id")
        }
        if len(anchors) >= MIN_ANCHORS and len(unique_cids) < MIN_ANCHORS:
            errors.append(
                f"[{cid}] {len(anchors)} anchors but only {len(unique_cids)} unique "
                f"canonical_ids — need ≥{MIN_ANCHORS} distinct prior works"
            )
        for a in anchors:
            if not a.get("canonical_id"):
                errors.append(f"[{cid}] anchor missing canonical_id")
            if not a.get("delta"):
                errors.append(f"[{cid}] anchor missing delta")
            if "delta_sufficient" not in a:
                errors.append(f"[{cid}] anchor missing delta_sufficient")

        verdict = c.get("verdict")
        if verdict not in VALID_VERDICTS:
            errors.append(f"[{cid}] verdict '{verdict}' not in {VALID_VERDICTS}")
        if verdict == "novel" and not any(a.get("delta_sufficient") for a in anchors):
            errors.append(
                f"[{cid}] verdict='novel' but no anchor has delta_sufficient=true"
            )

        conf = c.get("confidence")
        if conf is None:
            errors.append(f"[{cid}] missing confidence")
        else:
            try:
                cf = float(conf)
                if not 0.0 <= cf <= 1.0:
                    errors.append(f"[{cid}] confidence {cf} outside [0,1]")
            except (TypeError, ValueError):
                errors.append(f"[{cid}] confidence not a number: {conf!r}")

        reasoning = c.get("reasoning", "")
        if HEDGE_WORDS.search(_strip_quoted(reasoning)):
            errors.append(
                f"[{cid}] reasoning contains hedge word (outside quotes) — commit to a position"
            )

    return errors


def persist(report: dict, target_cid: str, run_id: str | None) -> Path:
    out = paper_dir(target_cid) / "novelty_assessment.json"
    out.write_text(json.dumps(report, indent=2))

    if run_id:
        db = run_db_path(run_id)
        if db.exists():
            con = sqlite3.connect(db)
            with con:
                for c in report.get("contributions", []):
                    con.execute(
                        "INSERT INTO novelty_assessments "
                        "(run_id, target_canonical_id, contribution_id, verdict, "
                        "confidence, anchor_count, report_json, at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            run_id,
                            target_cid,
                            c.get("id"),
                            c.get("verdict"),
                            c.get("confidence"),
                            len(c.get("anchors") or []),
                            json.dumps(c),
                            datetime.now(UTC).isoformat(),
                        ),
                    )
            con.close()
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, help="JSON file with the novelty report")
    p.add_argument("--target-canonical-id", required=True)
    p.add_argument("--run-id", default=None)
    args = p.parse_args()

    report = json.loads(Path(args.input).read_text())
    errors = validate(report)

    if errors:
        print("[novelty-check] REJECTED", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(2)

    out = persist(report, args.target_canonical_id, args.run_id)
    print(f"[novelty-check] OK → {out}")


if __name__ == "__main__":
    main()
