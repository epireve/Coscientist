#!/usr/bin/env python3
"""writing-style: flag paragraphs in a draft that deviate from the project profile.

Deviation metrics per paragraph:
  - sentence-length delta (vs profile avg)
  - hedge density delta
  - first-person rate delta
  - passive voice rate delta
  - paragraph length (sentences) delta

Severity thresholds:
  - info:  1.0–1.5 stddevs from profile (or 1.5x–2x for rates)
  - minor: 1.5–2.5 stddevs (2x–3x rates)
  - major: >2.5 stddevs (>3x rates)
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

from lib.cache import cache_root  # noqa: E402

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from _textstats import (  # noqa: E402
    first_person_rate,
    hedge_density,
    paragraphs,
    passive_voice_rate,
    sentence_length_stats,
    sentences,
)


def _severity(z: float) -> str | None:
    """Convert a standardized deviation to a severity level, or None if within band."""
    a = abs(z)
    if a < 1.0:
        return None
    if a < 1.5:
        return "info"
    if a < 2.5:
        return "minor"
    return "major"


def _rate_severity(ratio: float) -> str | None:
    """For small-rate metrics (hedge, first-person, passive) use ratio to profile value."""
    if ratio is None:
        return None
    if ratio < 1.5:
        return None
    if ratio < 2.0:
        return "info"
    if ratio < 3.0:
        return "minor"
    return "major"


def analyze(source_text: str, profile: dict) -> list[dict]:
    findings: list[dict] = []
    prof_mean_sent = profile["syntactic"]["avg_sentence_length"]
    prof_std_sent = max(profile["syntactic"]["sentence_length_std"], 1.0)  # avoid div/0
    prof_hedge = profile["lexical"]["hedge_density"]
    prof_fp = profile["lexical"]["first_person_rate"]
    prof_passive = profile["syntactic"]["passive_voice_rate"]
    prof_paralen = profile["structural"]["avg_paragraph_length_sentences"]
    prof_paralen_std = max(profile["structural"].get("paragraph_length_std", 1.0), 1.0)

    for i, para in enumerate(paragraphs(source_text), start=1):
        sents = sentences(para)
        if not sents:
            continue
        mean_sent, _ = sentence_length_stats(sents)
        z_sent = (mean_sent - prof_mean_sent) / prof_std_sent

        hedge_r = hedge_density(sents)
        fp_r = first_person_rate(sents)
        passive_r = passive_voice_rate(sents)

        hedge_ratio = (hedge_r / prof_hedge) if prof_hedge > 1e-6 else (1.0 if hedge_r < 1e-6 else 10.0)
        fp_ratio = (fp_r / prof_fp) if prof_fp > 1e-6 else (1.0 if fp_r < 1e-6 else 10.0)
        passive_ratio = (passive_r / prof_passive) if prof_passive > 1e-6 else (1.0 if passive_r < 1e-6 else 10.0)

        para_len = len(sents)
        z_paralen = (para_len - prof_paralen) / prof_paralen_std

        def add(metric: str, severity: str | None, observed, expected, note: str):
            if severity:
                findings.append({
                    "paragraph": i,
                    "metric": metric,
                    "severity": severity,
                    "observed": observed,
                    "expected": expected,
                    "note": note,
                })

        add("sentence_length", _severity(z_sent), round(mean_sent, 1),
            prof_mean_sent, f"z={z_sent:+.2f} vs profile")
        add("hedge_density", _rate_severity(hedge_ratio), round(hedge_r, 3),
            prof_hedge, f"{hedge_ratio:.1f}× profile")
        add("first_person_rate", _rate_severity(fp_ratio), round(fp_r, 3),
            prof_fp, f"{fp_ratio:.1f}× profile")
        add("passive_voice_rate", _rate_severity(passive_ratio), round(passive_r, 3),
            prof_passive, f"{passive_ratio:.1f}× profile")
        add("paragraph_length", _severity(z_paralen), para_len,
            prof_paralen, f"z={z_paralen:+.2f} sentences vs profile")

    return findings


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--manuscript-id", required=True)
    p.add_argument("--project-id", required=True)
    p.add_argument("--out", default=None)
    args = p.parse_args()

    ms_path = cache_root() / "manuscripts" / args.manuscript_id / "source.md"
    if not ms_path.exists():
        raise SystemExit(f"no manuscript source at {ms_path}")

    profile_path = cache_root() / "projects" / args.project_id / "style_profile.json"
    if not profile_path.exists():
        raise SystemExit(
            f"no style profile at {profile_path} — run fingerprint.py first"
        )

    profile = json.loads(profile_path.read_text())
    findings = analyze(ms_path.read_text(), profile)

    report = {
        "manuscript_id": args.manuscript_id,
        "project_id": args.project_id,
        "at": datetime.now(UTC).isoformat(),
        "findings_total": len(findings),
        "by_severity": {
            "info": sum(1 for f in findings if f["severity"] == "info"),
            "minor": sum(1 for f in findings if f["severity"] == "minor"),
            "major": sum(1 for f in findings if f["severity"] == "major"),
        },
        "findings": findings,
    }

    out_path = Path(args.out) if args.out else (
        cache_root() / "manuscripts" / args.manuscript_id / "style_audit.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    print(f"{report['findings_total']} findings ({report['by_severity']}) → {out_path}")


if __name__ == "__main__":
    main()
