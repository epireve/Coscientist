#!/usr/bin/env python3
"""attack-vectors checker: validate structure of an attack-findings report.

Rejects:
- unrecognized attack names
- missing severity or evidence
- 'fatal' verdicts without a steelman sentence
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import run_db_path  # noqa: E402
from lib.paper_artifact import PaperArtifact  # noqa: E402

KNOWN_ATTACKS = {
    "p-hacking",
    "harking",
    "selective-baselines",
    "missing-controls",
    "confounders",
    "underpowered",
    "circular-reasoning",
    "oversold-delta",
    "irreproducibility",
    "cherry-picked-test-set",
    "inappropriate-statistics",
    "goodharts-law",
}
VALID_SEVERITY = {"pass", "minor", "fatal"}


def validate(report: dict) -> list[str]:
    errors: list[str] = []
    findings = report.get("findings")
    if not isinstance(findings, list) or not findings:
        return ["no findings"]

    seen: set[str] = set()
    for f in findings:
        name = f.get("attack")
        if name not in KNOWN_ATTACKS:
            errors.append(f"unknown attack: {name!r}")
        if name in seen:
            errors.append(f"duplicate attack: {name}")
        seen.add(name)

        sev = f.get("severity")
        if sev not in VALID_SEVERITY:
            errors.append(f"[{name}] severity '{sev}' not in {VALID_SEVERITY}")
        if not (f.get("evidence") or "").strip():
            errors.append(f"[{name}] missing evidence")
        if sev == "fatal" and not (f.get("steelman") or "").strip():
            errors.append(f"[{name}] fatal finding without a steelman")

    return errors


def persist(report: dict, target_cid: str, run_id: str | None) -> Path:
    art = PaperArtifact(target_cid)
    out = art.root / "attack_findings.json"
    out.write_text(json.dumps(report, indent=2))

    if run_id:
        db = run_db_path(run_id)
        if db.exists():
            con = sqlite3.connect(db)
            with con:
                for f in report.get("findings", []):
                    con.execute(
                        "INSERT INTO attack_findings "
                        "(run_id, target_canonical_id, attack, severity, evidence, "
                        "steelman, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            run_id,
                            target_cid,
                            f.get("attack"),
                            f.get("severity"),
                            f.get("evidence"),
                            f.get("steelman"),
                            datetime.now(UTC).isoformat(),
                        ),
                    )
            con.close()
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--target-canonical-id", required=True)
    p.add_argument("--run-id", default=None)
    args = p.parse_args()

    report = json.loads(Path(args.input).read_text())
    errors = validate(report)
    if errors:
        print("[attack-vectors] REJECTED", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(2)

    out = persist(report, args.target_canonical_id, args.run_id)
    n_fatal = sum(1 for f in report["findings"] if f.get("severity") == "fatal")
    n_minor = sum(1 for f in report["findings"] if f.get("severity") == "minor")
    print(f"[attack-vectors] OK → {out} ({n_fatal} fatal, {n_minor} minor)")


if __name__ == "__main__":
    main()
