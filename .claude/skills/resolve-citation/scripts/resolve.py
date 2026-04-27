#!/usr/bin/env python3
"""resolve-citation CLI (v0.58).

Two modes:
  - --interactive: parse the partial reference only and emit JSON.
  - --candidates <path>: parse + score candidates harvested by the
    orchestrator from Semantic Scholar; emit best match (or
    matched=false if nothing scores ≥ 0.5).

The script never calls an MCP. Orchestrator-harvest pattern.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
# parents[3] = plugin layout (vendored lib/ at plugin root)
# parents[4] = repo layout (.claude/ inside project root with lib/)
_PLUGIN_ROOT = _HERE.parents[3]
_REPO_ROOT = _HERE.parents[4] if (_HERE.parents[4] / "lib").exists() else _PLUGIN_ROOT
for _p in (_REPO_ROOT, _PLUGIN_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lib.citation_resolver import (  # noqa: E402
    ACCEPT_THRESHOLD, parse_partial, pick_best, score_match,
)
from lib.paper_artifact import canonical_id  # noqa: E402


def _candidate_first_author(c: dict) -> str | None:
    authors = c.get("authors") or []
    if not authors:
        return None
    a = authors[0]
    if isinstance(a, dict):
        name = a.get("name") or ""
    else:
        name = str(a)
    if not name:
        return None
    if "," in name:
        return name.split(",", 1)[0].strip()
    parts = name.strip().split()
    return parts[-1] if parts else None


def _build_canonical(c: dict) -> str:
    return canonical_id(
        title=c.get("title") or "",
        year=c.get("year") if isinstance(c.get("year"), int) else None,
        first_author=_candidate_first_author(c),
        doi=c.get("doi"),
    )


def cmd_resolve(args: argparse.Namespace) -> int:
    partial = parse_partial(args.text or "")

    if args.interactive or not args.candidates:
        # Parse-only mode.
        out = partial.to_dict()
        json.dump(out, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    cand_path = Path(args.candidates)
    if not cand_path.exists():
        print(f"error: --candidates path not found: {cand_path}", file=sys.stderr)
        return 2
    try:
        candidates = json.loads(cand_path.read_text(encoding="utf-8") or "[]")
    except json.JSONDecodeError as e:
        print(f"error: failed to parse {cand_path}: {e}", file=sys.stderr)
        return 2
    if not isinstance(candidates, list):
        print("error: --candidates JSON must be a list", file=sys.stderr)
        return 2

    best, score = pick_best(partial, candidates, threshold=args.threshold)

    if best is None:
        # Show the highest-scoring candidate even if below threshold so
        # the orchestrator can fall back to manual judgment.
        below: dict | None = None
        below_score = 0.0
        for c in candidates:
            s = score_match(partial, c)
            if s > below_score:
                below_score = s
                below = c
        out = {
            "matched": False,
            "score": round(below_score, 4),
            "threshold": args.threshold,
            "partial": partial.to_dict(),
            "best_below_threshold": below,
        }
    else:
        out = {
            "matched": True,
            "score": score,
            "threshold": args.threshold,
            "canonical_id": _build_canonical(best),
            "doi": best.get("doi"),
            "title": best.get("title"),
            "year": best.get("year"),
            "candidate": best,
            "partial": partial.to_dict(),
        }

    if args.persist_db:
        # v0.58: persistence deferred. Emit the db-notify line shape only.
        notice = {
            "kind": "db-notify",
            "skill": "resolve-citation",
            "target_table": "citation_resolutions",
            "n_rows": 0,
            "detail": "persistence deferred; v0.58 emits notice only",
        }
        sys.stderr.write(f"[db-notify] {json.dumps(notice)}\n")

    json.dump(out, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="resolve-citation",
        description="Resolve an incomplete citation to canonical_id + DOI.",
    )
    p.add_argument("--text", required=True,
                   help="free-form citation reference, e.g. 'Smith 2020 X'")
    p.add_argument("--candidates", default=None,
                   help="path to JSON file with pre-harvested S2 candidates")
    p.add_argument("--interactive", action="store_true",
                   help="parse-only: emit the structured PartialCitation")
    p.add_argument("--threshold", type=float, default=ACCEPT_THRESHOLD,
                   help=f"acceptance threshold (default {ACCEPT_THRESHOLD})")
    p.add_argument("--persist-db", action="store_true",
                   help="emit a [db-notify] line (v0.58 placeholder; "
                        "actual table write deferred)")
    args = p.parse_args(argv)
    return cmd_resolve(args)


if __name__ == "__main__":
    sys.exit(main())
