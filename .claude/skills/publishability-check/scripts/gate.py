#!/usr/bin/env python3
"""publishability-check gate: enforce structure on a publishability verdict.

Rejects:
- missing probability per venue
- fewer than 3 up-factors or 3 down-factors
- missing or vague kill_criterion
- hedge words in reasoning
- probability/verdict inconsistency
"""

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

from lib import calibration as _cal  # noqa: E402
from lib.cache import cache_root, run_db_path  # noqa: E402

MIN_FACTORS = 3
HEDGE_WORDS = re.compile(
    r"\b(maybe|perhaps|potentially|could\s+be|might\s+be|possibly|seems?\s+to|appears?\s+to|somewhat)\b",
    re.IGNORECASE,
)
VAGUE_KILL = re.compile(
    r"\b(if it'?s bad|depends on reviewers|hard to say|it depends|unclear)\b",
    re.IGNORECASE,
)


def _strip_quoted(text: str) -> str:
    """Remove quoted spans before hedge scanning (v0.12.1)."""
    if not text:
        return ""
    text = re.sub(r'"[^"]*"', " ", text)
    text = re.sub(r"'[^']*'", " ", text)
    text = re.sub(r"`[^`]*`", " ", text)
    return text
VERDICT_P_RANGE = {
    "accept": (0.65, 1.0),
    "borderline-with-revisions": (0.30, 0.65),
    "reject": (0.0, 0.30),
}


def validate(report: dict) -> list[str]:
    errors: list[str] = []
    verdicts = report.get("venues")
    if not isinstance(verdicts, list) or not verdicts:
        return ["no venue verdicts in report"]

    for v in verdicts:
        venue = v.get("venue", "?")
        p = v.get("probability_of_acceptance")
        try:
            p = float(p)
        except (TypeError, ValueError):
            errors.append(f"[{venue}] missing/invalid probability_of_acceptance")
            continue
        if not 0.0 <= p <= 1.0:
            errors.append(f"[{venue}] probability {p} outside [0,1]")

        verdict = v.get("verdict")
        if verdict not in VERDICT_P_RANGE:
            errors.append(f"[{venue}] verdict '{verdict}' not recognized")
        else:
            lo, hi = VERDICT_P_RANGE[verdict]
            if not lo <= p <= hi:
                errors.append(
                    f"[{venue}] verdict='{verdict}' but p={p} outside expected [{lo}, {hi}]"
                )

        up = v.get("factors_up") or []
        down = v.get("factors_down") or []
        if len(up) < MIN_FACTORS:
            errors.append(f"[{venue}] only {len(up)} up-factors — need ≥{MIN_FACTORS}")
        if len(down) < MIN_FACTORS:
            errors.append(f"[{venue}] only {len(down)} down-factors — need ≥{MIN_FACTORS}")
        for f in up + down:
            if not f.get("factor") or "weight" not in f:
                errors.append(f"[{venue}] factor missing factor/weight: {f}")

        kill = (v.get("kill_criterion") or "").strip()
        if not kill:
            errors.append(f"[{venue}] missing kill_criterion")
        elif VAGUE_KILL.search(kill):
            errors.append(f"[{venue}] kill_criterion too vague: {kill!r}")

        reasoning = v.get("reasoning", "")
        if HEDGE_WORDS.search(_strip_quoted(reasoning)):
            errors.append(
                f"[{venue}] reasoning contains hedge word (outside quotes) — commit to a position"
            )

        if not v.get("tier_up_requirements"):
            errors.append(f"[{venue}] missing tier_up_requirements")

    return errors


def calibration_warning(report: dict) -> str | None:
    """Warn if a per-venue calibration set exists but the verdict's
    reasoning/kill_criterion never references any case from it.

    Uses `lib.calibration` as the single source of truth for slug
    convention + on-disk schema (v0.62).
    """
    root = cache_root()
    cal_dir = root / "calibration" / "venues"
    if not cal_dir.exists():
        return None
    referenced = 0
    venues_with_set = 0
    for v in report.get("venues", []):
        venue_name = v.get("venue", "")
        slug = _cal.slugify_venue(venue_name)
        cal_file = cal_dir / f"{slug}.json"
        if not cal_file.exists():
            continue
        venues_with_set += 1
        cset = _cal.load(root, venue_name)
        titles = [
            c.title for bucket in ("accepted", "rejected", "borderline")
            for c in getattr(cset, bucket)
        ]
        canonical_ids = [
            c.canonical_id for bucket in ("accepted", "rejected", "borderline")
            for c in getattr(cset, bucket) if c.canonical_id
        ]
        reasoning = (v.get("reasoning", "") + " "
                     + (v.get("kill_criterion") or "")).lower()
        title_hit = any(t.lower()[:40] in reasoning for t in titles if t)
        cid_hit = any(cid.lower() in reasoning for cid in canonical_ids if cid)
        if title_hit or cid_hit:
            referenced += 1
    if venues_with_set == 0:
        return None
    if referenced == 0:
        return (
            "calibration set present but no calibration cases referenced "
            "in reasoning — verdict may be un-anchored"
        )
    return None


def persist(report: dict, manuscript_id: str, run_id: str | None) -> Path:
    out_dir = cache_root() / "manuscripts" / manuscript_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "publishability_verdict.json"
    out.write_text(json.dumps(report, indent=2))

    if run_id:
        db = run_db_path(run_id)
        if db.exists():
            con = sqlite3.connect(db)
            with con:
                for v in report.get("venues", []):
                    con.execute(
                        "INSERT INTO publishability_verdicts "
                        "(run_id, manuscript_id, venue, verdict, probability, "
                        "kill_criterion, report_json, at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            run_id,
                            manuscript_id,
                            v.get("venue"),
                            v.get("verdict"),
                            v.get("probability_of_acceptance"),
                            v.get("kill_criterion"),
                            json.dumps(v),
                            datetime.now(UTC).isoformat(),
                        ),
                    )
            con.close()
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--target-manuscript-id", required=True)
    p.add_argument("--run-id", default=None)
    p.add_argument("--allow-uncalibrated", action="store_true",
                   help="v0.12.1: don't fail when calibration set is present "
                        "but not referenced (warning instead)")
    args = p.parse_args()

    report = json.loads(Path(args.input).read_text())
    errors = validate(report)

    if errors:
        print("[publishability-check] REJECTED", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        # v0.93b — emit gate span before exiting.
        try:
            from lib.gate_trace import emit_gate_span
            emit_gate_span(
                run_id=args.run_id, gate_name="publishability-check",
                verdict="rejected", errors=errors,
                target_id=args.target_manuscript_id,
            )
        except Exception:
            pass
        sys.exit(2)

    # v0.12.1: hard-fail when a calibration set is present but unreferenced.
    # Pass --allow-uncalibrated to revert to v0.10 warning behavior.
    warn = calibration_warning(report)
    warnings = [warn] if warn else []
    if warn:
        if args.allow_uncalibrated:
            print(f"[publishability-check] WARN: {warn}", file=sys.stderr)
        else:
            print(f"[publishability-check] REJECTED: {warn}", file=sys.stderr)
            print(
                "  pass --allow-uncalibrated to override (not recommended)",
                file=sys.stderr,
            )
            try:
                from lib.gate_trace import emit_gate_span
                emit_gate_span(
                    run_id=args.run_id, gate_name="publishability-check",
                    verdict="rejected", errors=[warn],
                    target_id=args.target_manuscript_id,
                )
            except Exception:
                pass
            sys.exit(2)

    out = persist(report, args.target_manuscript_id, args.run_id)
    print(f"[publishability-check] OK → {out}")
    # v0.93b — gate passed.
    try:
        from lib.gate_trace import emit_gate_span
        emit_gate_span(
            run_id=args.run_id, gate_name="publishability-check",
            verdict="ok", warnings=warnings,
            target_id=args.target_manuscript_id,
        )
    except Exception:
        pass


if __name__ == "__main__":
    main()
