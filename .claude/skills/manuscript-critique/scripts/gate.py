#!/usr/bin/env python3
"""manuscript-critique gate: enforce four-reviewer structure + severity discipline."""

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
from lib.transaction import multi_db_tx  # noqa: E402  v0.14

REQUIRED_REVIEWERS = {"methodological", "theoretical", "big_picture", "nitpicky"}
VALID_SEVERITY = {"fatal", "major", "minor"}
VALID_VERDICT = {"accept", "borderline", "reject"}
HEDGE_WORDS = re.compile(
    r"\b(maybe|perhaps|potentially|could\s+be|might\s+be|possibly|seems?\s+to|appears?\s+to)\b",
    re.IGNORECASE,
)
VERDICT_CONF_RANGE = {
    "accept": (0.6, 1.0),
    "borderline": (0.3, 0.7),
    "reject": (0.0, 0.4),
}


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
    reviewers = report.get("reviewers") or {}
    missing = REQUIRED_REVIEWERS - set(reviewers.keys())
    if missing:
        errors.append(f"missing reviewer personas: {sorted(missing)}")

    for name in REQUIRED_REVIEWERS & set(reviewers.keys()):
        r = reviewers[name]
        findings = r.get("findings") or []
        summary = (r.get("summary") or "").strip()
        if not findings and not summary:
            errors.append(f"[{name}] zero findings and no summary")
        if HEDGE_WORDS.search(_strip_quoted(summary)):
            errors.append(f"[{name}] summary contains hedge word (outside quotes)")

        for f in findings:
            fid = f.get("id", "?")
            sev = f.get("severity")
            if sev not in VALID_SEVERITY:
                errors.append(f"[{name}/{fid}] severity {sev!r} not in {VALID_SEVERITY}")
            for field in ("location", "issue"):
                if not (f.get(field) or "").strip():
                    errors.append(f"[{name}/{fid}] missing {field}")
            if sev == "fatal" and not (f.get("steelman") or "").strip():
                errors.append(f"[{name}/{fid}] fatal finding requires steelman")

    verdict = report.get("overall_verdict")
    if verdict not in VALID_VERDICT:
        errors.append(f"overall_verdict {verdict!r} not in {VALID_VERDICT}")

    conf = report.get("confidence")
    try:
        cf = float(conf) if conf is not None else None
    except (TypeError, ValueError):
        cf = None
    if cf is None:
        errors.append("missing/invalid confidence")
    elif verdict in VERDICT_CONF_RANGE:
        lo, hi = VERDICT_CONF_RANGE[verdict]
        if not lo <= cf <= hi:
            errors.append(
                f"confidence {cf} inconsistent with verdict={verdict!r} (expected [{lo},{hi}])"
            )

    return errors


def _write_findings(con: sqlite3.Connection, manuscript_id: str,
                    reviewers: dict, now: str) -> None:
    """v0.14: caller manages BEGIN/COMMIT (via multi_db_tx)."""
    for name, r in reviewers.items():
        for f in r.get("findings") or []:
            con.execute(
                "INSERT INTO manuscript_critique_findings "
                "(manuscript_id, reviewer, severity, location, issue, "
                "suggested_fix, steelman, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    manuscript_id, name,
                    f["severity"], f["location"], f["issue"],
                    f.get("suggested_fix"), f.get("steelman"), now,
                ),
            )


def persist(report: dict, manuscript_id: str,
            run_id: str | None, project_id: str | None) -> Path:
    """v0.14: dual-DB writes wrapped in multi_db_tx — atomic across both."""
    out_dir = cache_root() / "manuscripts" / manuscript_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "critique_report.json"
    out.write_text(json.dumps(report, indent=2))

    now = datetime.now(UTC).isoformat()
    reviewers = report["reviewers"]

    targets: list[Path] = []
    if run_id:
        rdb = run_db_path(run_id)
        if rdb.exists():
            targets.append(rdb)
    if project_id:
        pdb = cache_root() / "projects" / project_id / "project.db"
        if pdb.exists():
            targets.append(pdb)

    if targets:
        with multi_db_tx(targets) as cons:
            for con in cons:
                _write_findings(con, manuscript_id, reviewers, now)

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
        print("[manuscript-critique] REJECTED", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(2)

    out = persist(report, args.manuscript_id, args.run_id, args.project_id)
    n_fatal = sum(
        1 for r in report["reviewers"].values()
        for f in (r.get("findings") or []) if f.get("severity") == "fatal"
    )
    print(
        f"[manuscript-critique] OK → {out} "
        f"(verdict={report['overall_verdict']}, p={report.get('confidence')}, {n_fatal} fatal)"
    )


if __name__ == "__main__":
    main()
