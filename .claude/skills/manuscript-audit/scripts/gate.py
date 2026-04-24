#!/usr/bin/env python3
"""manuscript-audit gate: enforce structure on an audit report."""

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

from lib.cache import cache_root  # noqa: E402

HEDGE_WORDS = re.compile(
    r"\b(maybe|perhaps|potentially|could\s+be|might\s+be|possibly|seems?\s+to|appears?\s+to)\b",
    re.IGNORECASE,
)
VALID_KINDS = {"overclaim", "uncited", "unsupported", "outdated", "retracted"}
VALID_SEVERITY = {"info", "minor", "major"}
INLINE_CITATION = re.compile(r"(\\cite\{|\[@|\[\d+\]|\(\w+\s+\d{4}\))")


def validate(report: dict) -> list[str]:
    errors: list[str] = []
    claims = report.get("claims")
    if not isinstance(claims, list) or not claims:
        return ["no claims extracted — audit did not analyze the manuscript"]

    seen_ids: set[str] = set()
    for c in claims:
        cid = c.get("claim_id", "?")
        if not cid or cid in seen_ids:
            errors.append(f"claim_id duplicate or missing: {cid!r}")
        seen_ids.add(cid)
        for field in ("text", "location"):
            if not (c.get(field) or "").strip():
                errors.append(f"[{cid}] missing {field}")

        text_has_inline = bool(INLINE_CITATION.search(c.get("text", "")))
        cited = c.get("cited_sources", [])
        if text_has_inline and not cited:
            errors.append(
                f"[{cid}] text contains an inline citation but cited_sources is empty — "
                "you skipped resolution"
            )

        for f in c.get("findings") or []:
            if f.get("kind") not in VALID_KINDS:
                errors.append(f"[{cid}] finding kind {f.get('kind')!r} not in {VALID_KINDS}")
            if f.get("severity") not in VALID_SEVERITY:
                errors.append(f"[{cid}] severity {f.get('severity')!r} not in {VALID_SEVERITY}")
            evidence = (f.get("evidence") or "").strip()
            if not evidence:
                errors.append(f"[{cid}] finding missing evidence")
            elif HEDGE_WORDS.search(evidence):
                errors.append(f"[{cid}] evidence contains hedge word")

    return errors


def persist(report: dict, manuscript_id: str, run_id: str | None) -> Path:
    out_dir = cache_root() / "manuscripts" / manuscript_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "audit_report.json"
    out.write_text(json.dumps(report, indent=2))

    if run_id:
        from lib.cache import run_db_path
        db = run_db_path(run_id)
        if db.exists():
            con = sqlite3.connect(db)
            now = datetime.now(UTC).isoformat()
            with con:
                for c in report["claims"]:
                    con.execute(
                        "INSERT OR IGNORE INTO manuscript_claims "
                        "(manuscript_id, claim_id, text, location, cited_sources, at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            manuscript_id,
                            c["claim_id"],
                            c["text"],
                            c["location"],
                            json.dumps(c.get("cited_sources", [])),
                            now,
                        ),
                    )
                    for f in c.get("findings") or []:
                        con.execute(
                            "INSERT INTO manuscript_audit_findings "
                            "(manuscript_id, claim_id, kind, severity, evidence, at) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                manuscript_id,
                                c["claim_id"],
                                f["kind"],
                                f["severity"],
                                f["evidence"],
                                now,
                            ),
                        )
            con.close()
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--manuscript-id", required=True)
    p.add_argument("--run-id", default=None)
    args = p.parse_args()

    report = json.loads(Path(args.input).read_text())
    errors = validate(report)
    if errors:
        print("[manuscript-audit] REJECTED", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(2)

    out = persist(report, args.manuscript_id, args.run_id)
    n_major = sum(
        1 for c in report["claims"] for f in (c.get("findings") or [])
        if f.get("severity") == "major"
    )
    print(f"[manuscript-audit] OK → {out} ({len(report['claims'])} claims, {n_major} major findings)")


if __name__ == "__main__":
    main()
