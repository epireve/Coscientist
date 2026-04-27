#!/usr/bin/env python3
"""harvest.py — orchestrator-side MCP shortlist writer (Plan 5 Stage 2).

Six search-using personas (social, grounder, historian, gaper, theorist,
thinker) used to call MCPs themselves. In runtimes where sub-agents
don't inherit MCP access, that breaks. This script lifts MCP harvesting
into the orchestrator (the parent agent has MCP access) and persists
the result as a shortlist file under
`~/.cache/coscientist/runs/run-<id>/inputs/<persona>-<phase>.json`.

Modes
=====

The orchestrator passes raw MCP results in via stdin as a JSON array
of result-entry dicts (or via --input-file). harvest.py merges/dedups
through paper-discovery's merge.py logic, applies the persona's
budget, then writes the shortlist via lib.persona_input.save().

This script does NOT call MCPs itself — that's the orchestrator's job.
Keeping MCP IO in the orchestrator means we can:
  - Test this script with mocked MCP results (no network)
  - Swap MCPs without touching personas
  - Apply per-call rate limits in one place (the orchestrator)

Usage
=====

# Orchestrator collects MCP results, then:
echo '<json-array>' | python harvest.py write \\
    --run-id <id> --persona social --phase phase0 \\
    --query "<the original question>" \\
    [--max-papers 200] [--notes "<free-form>"]

# Or:
python harvest.py write \\
    --run-id <id> --persona social --phase phase0 \\
    --query "..." --input-file /tmp/mcp-results.json

# Show what's been harvested for a run:
python harvest.py status --run-id <id>

# Show what a persona will read:
python harvest.py show --run-id <id> --persona social --phase phase0
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.persona_input import (  # noqa: E402
    PersonaInput, PersonaInputError, exists, input_path, list_for_run,
    load, save,
)

# Personas allowed to receive harvested input. Adding a new persona
# here without also creating an upstream consumer is a config error,
# so we list them explicitly.
KNOWN_PERSONAS = {
    "social", "grounder", "historian", "gaper",
    "theorist", "thinker",
}

# Per-persona budget defaults. Orchestrator can override via flags.
PERSONA_BUDGETS = {
    "social":    {"max_papers": 200, "max_mcp_calls": 30},
    "grounder":  {"max_papers": 30,  "max_mcp_calls": 20},
    "historian": {"max_papers": 50,  "max_mcp_calls": 15},
    "gaper":     {"max_papers": 25,  "max_mcp_calls": 10},
    "theorist":  {"max_papers": 30,  "max_mcp_calls": 15},
    "thinker":   {"max_papers": 30,  "max_mcp_calls": 15},
}


def _import_pd_merge():
    """Import paper-discovery's merge module without polluting sys.path."""
    import importlib.util
    pd_merge_path = (
        _REPO_ROOT / ".claude" / "skills" / "paper-discovery"
        / "scripts" / "merge.py"
    )
    spec = importlib.util.spec_from_file_location("pd_merge", pd_merge_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read_input(args: argparse.Namespace) -> list[dict]:
    if args.input_file:
        text = Path(args.input_file).read_text()
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        raise SystemExit(
            "no MCP results provided. Pipe JSON into stdin or pass "
            "--input-file <path>."
        )
    if not text.strip():
        return []
    raw = json.loads(text)
    if isinstance(raw, dict) and "results" in raw:
        raw = raw["results"]
    if not isinstance(raw, list):
        raise SystemExit(
            f"input must be a JSON array of MCP result dicts; got "
            f"{type(raw).__name__}"
        )
    return raw


def cmd_write(args: argparse.Namespace) -> dict:
    if args.persona not in KNOWN_PERSONAS:
        raise SystemExit(
            f"unknown persona {args.persona!r}; expected one of "
            f"{sorted(KNOWN_PERSONAS)}"
        )

    raw = _read_input(args)

    # Dedup + rank using paper-discovery's logic so personas see the
    # same shape they used to get from their own MCP calls.
    pd_merge = _import_pd_merge()
    merged = pd_merge.merge_entries(raw)
    ranked = pd_merge.rank(merged)

    budget = dict(PERSONA_BUDGETS.get(args.persona, {}))
    if args.max_papers:
        budget["max_papers"] = args.max_papers
    if args.max_mcp_calls:
        budget["max_mcp_calls"] = args.max_mcp_calls

    if budget.get("max_papers"):
        ranked = ranked[: budget["max_papers"]]

    inp = PersonaInput(
        run_id=args.run_id,
        persona=args.persona,
        phase=args.phase,
        query=args.query,
        results=ranked,
        budget=budget,
        harvested_by=args.harvested_by or "orchestrator",
        notes=args.notes or "",
    )
    path = save(inp)
    return {
        "wrote": str(path),
        "run_id": args.run_id,
        "persona": args.persona,
        "phase": args.phase,
        "raw_count": len(raw),
        "deduped_count": len(merged),
        "kept_count": len(inp.results),
        "budget": budget,
    }


def cmd_status(args: argparse.Namespace) -> dict:
    paths = list_for_run(args.run_id)
    out: list[dict] = []
    for p in paths:
        try:
            inp = load(args.run_id, *p.stem.split("-", 1))
            out.append({
                "file": p.name,
                "persona": inp.persona,
                "phase": inp.phase,
                "results": len(inp.results),
                "harvested_at": inp.harvested_at,
            })
        except PersonaInputError as e:
            out.append({"file": p.name, "error": str(e)})
    return {"run_id": args.run_id, "shortlists": out, "count": len(out)}


def cmd_show(args: argparse.Namespace) -> dict:
    if not exists(args.run_id, args.persona, args.phase):
        raise SystemExit(
            f"no shortlist for {args.persona}/{args.phase} in run "
            f"{args.run_id}. Path expected: "
            f"{input_path(args.run_id, args.persona, args.phase)}"
        )
    inp = load(args.run_id, args.persona, args.phase)
    return inp.to_dict()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("write", help="write a persona shortlist file")
    w.add_argument("--run-id", required=True)
    w.add_argument("--persona", required=True,
                    choices=sorted(KNOWN_PERSONAS))
    w.add_argument("--phase", required=True,
                    help="e.g. phase0, phase1, phase2")
    w.add_argument("--query", required=True,
                    help="the run's research question")
    w.add_argument("--input-file",
                    help="path to JSON array of MCP results "
                         "(if absent, read from stdin)")
    w.add_argument("--max-papers", type=int)
    w.add_argument("--max-mcp-calls", type=int)
    w.add_argument("--notes", default="")
    w.add_argument("--harvested-by", default="orchestrator")
    w.set_defaults(func=cmd_write)

    s = sub.add_parser("status",
                         help="list shortlists harvested for a run")
    s.add_argument("--run-id", required=True)
    s.set_defaults(func=cmd_status)

    sh = sub.add_parser("show",
                          help="dump one shortlist for inspection")
    sh.add_argument("--run-id", required=True)
    sh.add_argument("--persona", required=True)
    sh.add_argument("--phase", required=True)
    sh.set_defaults(func=cmd_show)

    args = p.parse_args()
    out = args.func(args)
    sys.stdout.write(json.dumps(out, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()
