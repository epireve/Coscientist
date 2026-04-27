#!/usr/bin/env python3
"""gap-analyzer CLI — per-gap structured analysis.

Sources two ways:
  - --run-id: pulls Surveyor's output_json from the run DB +
    confidences from `claims`
  - --gaps-file + --confidences: loads from JSON files (ad-hoc use)

Always writes JSON to stdout. With --write-output, also persists
gap_analysis.{json,md} to the run dir (or cwd if no run id).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_PLUGIN_ROOT = _HERE.parents[3]
_REPO_ROOT = (
    _HERE.parents[4] if (_HERE.parents[4] / "lib").exists()
    else _PLUGIN_ROOT
)
for _p in (_REPO_ROOT, _PLUGIN_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lib.cache import cache_root  # noqa: E402
from lib.gap_analyzer import (  # noqa: E402
    analyze_gaps, render_brief,
)


def _load_from_run(run_id: str) -> tuple[list[dict], dict]:
    db = cache_root() / "runs" / f"run-{run_id}.db"
    if not db.exists():
        raise SystemExit(f"no run DB at {db}")
    con = sqlite3.connect(db)
    try:
        # Pull surveyor output
        row = con.execute(
            "SELECT output_json FROM phases "
            "WHERE run_id=? AND name='surveyor'",
            (run_id,),
        ).fetchone()
        if not row or not row[0]:
            raise SystemExit("surveyor phase has no output_json")
        out = json.loads(row[0])
        gaps = out.get("gaps", []) or []
        # Confidences: average per supporting cid from claims table
        rows = con.execute(
            "SELECT canonical_id, AVG(confidence) "
            "FROM claims WHERE run_id=? "
            "AND canonical_id IS NOT NULL "
            "AND confidence IS NOT NULL "
            "GROUP BY canonical_id",
            (run_id,),
        ).fetchall()
        confs = {r[0]: float(r[1]) for r in rows}
    finally:
        con.close()
    return gaps, confs


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-id", default=None,
                   help="Pull gaps from a deep-research run's surveyor output")
    p.add_argument("--gaps-file", default=None,
                   help="Path to a JSON file of gap dicts")
    p.add_argument("--confidences", default=None,
                   help="Path to JSON file mapping cid -> confidence")
    p.add_argument("--write-output", action="store_true",
                   help="Also write gap_analysis.{json,md} alongside the run")
    p.add_argument("--persist-db", default=None,
                   help="If set, write gap_analyses rows to this DB (v0.57)")
    args = p.parse_args()

    if args.run_id:
        gaps, confs = _load_from_run(args.run_id)
    elif args.gaps_file:
        gaps = json.loads(Path(args.gaps_file).read_text())
        confs = (
            json.loads(Path(args.confidences).read_text())
            if args.confidences else {}
        )
    else:
        raise SystemExit("provide --run-id OR --gaps-file")

    analyses = analyze_gaps(gaps, supporting_paper_confidences=confs)
    payload = {
        "n_gaps": len(analyses),
        "tier_distribution": _tier_distribution(analyses),
        "analyses": [a.to_dict() for a in analyses],
    }

    if args.write_output:
        if args.run_id:
            run_dir = cache_root() / "runs" / f"run-{args.run_id}"
            run_dir.mkdir(parents=True, exist_ok=True)
        else:
            run_dir = Path.cwd()
        (run_dir / "gap_analysis.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True)
        )
        (run_dir / "gap_analysis.md").write_text(render_brief(analyses))
        payload["json_path"] = str(run_dir / "gap_analysis.json")
        payload["md_path"] = str(run_dir / "gap_analysis.md")

    # v0.57 persistence
    if args.persist_db:
        from lib.skill_persist import persist_gap_analyses
        persist_gap_analyses(
            Path(args.persist_db),
            run_id=args.run_id,
            analyses=analyses,
        )
        payload["persisted_to"] = args.persist_db

    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _tier_distribution(analyses) -> dict:
    counts = {"A": 0, "B": 0, "C": 0, "none": 0}
    for a in analyses:
        counts[a.publishability_tier] = counts.get(a.publishability_tier, 0) + 1
    return counts


if __name__ == "__main__":
    main()
