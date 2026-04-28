#!/usr/bin/env python3
"""venue-match CLI."""
from __future__ import annotations

import argparse
import json
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

from lib.venue_match import (  # noqa: E402
    ManuscriptChars,
    recommend,
    render_brief,
)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--domains", nargs="+", required=True,
                   help="Manuscript domains (e.g. ml nlp)")
    p.add_argument("--kind", required=True,
                   choices=["empirical", "theoretical", "review",
                             "systematic-review", "position", "method",
                             "tool", "dataset"],
                   help="Manuscript kind")
    p.add_argument("--novelty", type=float, default=0.5,
                   help="Novelty score in [0, 1]")
    p.add_argument("--rigor", type=float, default=0.5,
                   help="Rigor score in [0, 1]")
    p.add_argument("--open-science", action="store_true",
                   help="Prefer OA venues")
    p.add_argument("--deadline-days", type=int, default=None,
                   help="Max acceptable review turnaround")
    p.add_argument("--require-tier", choices=["A", "B", "C"], default=None,
                   help="Hard floor on venue tier")
    p.add_argument("--top-k", type=int, default=5,
                   help="Number of recommendations")
    p.add_argument("--audience", choices=["specialist", "broad"],
                   default="specialist")
    p.add_argument("--write-output", default=None,
                   help="If set, write markdown brief to this path")
    p.add_argument("--persist-db", default=None,
                   help="If set, write venue_recommendations rows here (v0.57)")
    p.add_argument("--manuscript-id", default=None,
                   help="Optional scope tag for the persisted rows")
    p.add_argument("--run-id", default=None,
                   help="Optional run scope for the persisted rows")
    args = p.parse_args()

    chars = ManuscriptChars(
        domains=tuple(args.domains),
        kind=args.kind,
        novelty_score=args.novelty,
        rigor_score=args.rigor,
        open_science_intent=args.open_science,
        deadline_days=args.deadline_days,
        require_tier=args.require_tier,
        target_audience=args.audience,
    )
    recs = recommend(chars, top_k=args.top_k)

    payload = {
        "n": len(recs),
        "recommendations": [r.to_dict() for r in recs],
    }

    if args.write_output:
        Path(args.write_output).write_text(render_brief(recs))
        payload["md_path"] = args.write_output

    # v0.57 persistence
    if args.persist_db:
        from lib.skill_persist import persist_venue_recommendations
        persist_venue_recommendations(
            Path(args.persist_db),
            manuscript_id=args.manuscript_id,
            run_id=args.run_id,
            recommendations=recs,
        )
        payload["persisted_to"] = args.persist_db

    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
