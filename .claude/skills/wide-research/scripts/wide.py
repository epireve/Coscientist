#!/usr/bin/env python3
"""wide-research CLI — orchestrator for fan-out sub-agent runs.

v0.53.1 POC: init + decompose + show-plan + collect. Single-sub-agent
synchronous execution path. v0.53.2 adds asyncio.gather fan-out via
Claude Code Task tool dispatch.

Wide run state lives at:
  ~/.cache/coscientist/runs/run-<wide-id>/
    plan.json                  # WideRunPlan (decomposition + cost estimate)
    wide/<sub-id>/             # per-sub-agent workspace
      taskspec.json
      task_progress.md
      result.json (when complete)
      findings/                # intermediate files
    wide-output.{csv,md}       # synthesizer roll-up (after collect)

Hard limits enforced:
  - 10 ≤ items ≤ 250
  - concurrency cap 30
  - $50 run ceiling unless --allow-expensive
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402
from lib.wide_research import (  # noqa: E402
    HARD_DOLLAR_CEILING, TASK_TYPE_DEFAULTS, TaskSpec, WideRunPlan,
    collect_results, decompose, write_workspace,
)


def _wide_run_dir(run_id: str) -> Path:
    p = cache_root() / "runs" / f"run-{run_id}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _plan_path(run_id: str) -> Path:
    return _wide_run_dir(run_id) / "plan.json"


def cmd_init(args: argparse.Namespace) -> dict:
    """Create new Wide run + decompose into TaskSpecs.

    Reads --items from JSON file (list of dicts). Writes plan.json.
    Output: run_id + plan summary (for HITL Gate 1).
    """
    items_path = Path(args.items)
    if not items_path.exists():
        raise SystemExit(f"items file not found: {items_path}")
    items = json.loads(items_path.read_text())
    if not isinstance(items, list):
        raise SystemExit("--items file must be a JSON array of item dicts")

    run_id = uuid.uuid4().hex[:8]
    run_dir = _wide_run_dir(run_id)

    try:
        plan = decompose(
            run_id=run_id,
            user_query=args.query,
            items=items,
            task_type=args.type,
            parent_run_id=args.parent_run_id,
            workspace_root=cache_root() / "runs",
        )
    except ValueError as e:
        raise SystemExit(f"decompose failed: {e}")

    if (plan.estimated_dollar_cost > HARD_DOLLAR_CEILING
            and not args.allow_expensive):
        raise SystemExit(
            f"plan exceeds ${HARD_DOLLAR_CEILING} hard ceiling "
            f"(${plan.estimated_dollar_cost:.2f}). "
            f"Pass --allow-expensive to proceed."
        )

    # Persist plan
    _plan_path(run_id).write_text(
        json.dumps(plan.to_dict(), indent=2, sort_keys=True)
    )

    # Pre-create each sub-agent's workspace + initial files
    for spec in plan.sub_specs:
        write_workspace(spec)

    return {
        "run_id": run_id,
        "n_items": len(items),
        "n_sub_agents": len(plan.sub_specs),
        "task_type": args.type,
        "estimated_total_tokens": plan.estimated_total_tokens,
        "estimated_dollar_cost": plan.estimated_dollar_cost,
        "concurrency_cap": plan.concurrency_cap,
        "plan_path": str(_plan_path(run_id)),
        "next_step": (
            f"Run `wide.py decompose --run-id {run_id}` to review the "
            f"plan, then dispatch sub-agents via the orchestrator."
        ),
    }


def cmd_decompose(args: argparse.Namespace) -> dict:
    """Show decomposition plan (HITL Gate 1)."""
    p = _plan_path(args.run_id)
    if not p.exists():
        raise SystemExit(f"no plan for run {args.run_id} at {p}")
    plan_dict = json.loads(p.read_text())

    if args.format == "md":
        # Reconstruct WideRunPlan to get render_decomposition_table
        sub_specs = [TaskSpec.from_dict(s) for s in plan_dict["sub_specs"]]
        plan = WideRunPlan(
            run_id=plan_dict["run_id"],
            parent_run_id=plan_dict.get("parent_run_id"),
            task_type=plan_dict["task_type"],
            user_query=plan_dict["user_query"],
            items=[],  # not needed for table render
            sub_specs=sub_specs,
            estimated_total_tokens=plan_dict["estimated_total_tokens"],
            estimated_dollar_cost=plan_dict["estimated_dollar_cost"],
            concurrency_cap=plan_dict["concurrency_cap"],
        )
        sys.stdout.write(plan.render_decomposition_table() + "\n")
        return {}
    return plan_dict


def cmd_show_spec(args: argparse.Namespace) -> dict:
    """Show one sub-agent's TaskSpec (for orchestrator dispatch)."""
    p = _plan_path(args.run_id)
    if not p.exists():
        raise SystemExit(f"no plan for run {args.run_id}")
    plan_dict = json.loads(p.read_text())

    matches = [
        s for s in plan_dict["sub_specs"]
        if s["sub_agent_id"] == args.sub_agent_id
    ]
    if not matches:
        raise SystemExit(
            f"sub-agent {args.sub_agent_id} not in run {args.run_id}"
        )
    return matches[0]


def cmd_collect(args: argparse.Namespace) -> dict:
    """Collect sub-agent results (Fan-In step).

    Reads each sub-agent's result.json. Writes synthesizer-friendly
    roll-up (CSV + markdown summary) to run dir.
    """
    p = _plan_path(args.run_id)
    if not p.exists():
        raise SystemExit(f"no plan for run {args.run_id}")
    plan_dict = json.loads(p.read_text())

    # Reconstruct minimal WideRunPlan for collect_results
    sub_specs = [TaskSpec.from_dict(s) for s in plan_dict["sub_specs"]]
    plan = WideRunPlan(
        run_id=plan_dict["run_id"],
        parent_run_id=plan_dict.get("parent_run_id"),
        task_type=plan_dict["task_type"],
        user_query=plan_dict["user_query"],
        items=[],
        sub_specs=sub_specs,
        estimated_total_tokens=plan_dict["estimated_total_tokens"],
        estimated_dollar_cost=plan_dict["estimated_dollar_cost"],
        concurrency_cap=plan_dict["concurrency_cap"],
    )

    results = collect_results(plan)

    # Status counts
    n_complete = sum(1 for r in results if r["status"] == "complete")
    n_missing = sum(1 for r in results if r["status"] == "missing")
    n_error = sum(1 for r in results if r["status"].startswith("parse_error"))

    # Write outputs
    run_dir = _wide_run_dir(args.run_id)
    if args.write_outputs:
        # CSV: each result row, fields per output_schema
        csv_lines = _to_csv(results, plan.task_type)
        (run_dir / "wide-output.csv").write_text("\n".join(csv_lines))
        # Markdown summary
        md = _to_markdown(results, plan)
        (run_dir / "wide-output.md").write_text(md)

    summary = {
        "run_id": args.run_id,
        "task_type": plan.task_type,
        "n_total": len(results),
        "n_complete": n_complete,
        "n_missing": n_missing,
        "n_error": n_error,
        "csv_path": (
            str(run_dir / "wide-output.csv")
            if args.write_outputs else None
        ),
        "md_path": (
            str(run_dir / "wide-output.md")
            if args.write_outputs else None
        ),
    }
    if args.format == "full":
        summary["results"] = results
    return summary


def _to_csv(results: list[dict], task_type: str) -> list[str]:
    """Render results as CSV. Schema depends on task_type."""
    if not results:
        return []
    # Infer header from first complete result; fall back to TaskSpec defaults
    header = ["sub_agent_id", "input_item_summary", "status"]
    sample_result = next(
        (r["result"] for r in results
         if r["status"] == "complete" and "result" in r),
        None,
    )
    if sample_result and isinstance(sample_result, dict):
        for k in sample_result.keys():
            if k not in header:
                header.append(k)
    else:
        # Use TaskSpec output_schema default
        defaults = TASK_TYPE_DEFAULTS.get(task_type, {})
        for k in defaults.get("output_schema", {}).get("fields", []):
            if k not in header:
                header.append(k)

    lines = [",".join(header)]
    for r in results:
        row = []
        for col in header:
            if col in r:
                v = r[col]
            elif r.get("result") and col in r["result"]:
                v = r["result"][col]
            else:
                v = ""
            # CSV-escape: quote if contains comma/quote/newline
            s = str(v).replace('"', '""')
            if "," in s or '\n' in s or '"' in s:
                s = f'"{s}"'
            row.append(s)
        lines.append(",".join(row))
    return lines


def _to_markdown(results: list[dict], plan: WideRunPlan) -> str:
    """Synthesizer-friendly markdown summary."""
    n = len(results)
    n_done = sum(1 for r in results if r["status"] == "complete")
    lines = [
        f"# Wide Research output — run {plan.run_id}",
        "",
        f"**Task type**: {plan.task_type}",
        f"**Items**: {n}",
        f"**Complete**: {n_done}",
        f"**User query**: {plan.user_query}",
        "",
        "## Per-item results",
        "",
        "| Sub-agent | Item | Status | Result preview |",
        "|---|---|---|---|",
    ]
    for r in results:
        item = r.get("input_item_summary", "")[:40]
        status = r["status"]
        if status == "complete" and "result" in r:
            preview = json.dumps(r["result"])[:80]
        else:
            preview = "—"
        lines.append(
            f"| `{r['sub_agent_id']}` | {item} | {status} | {preview} |"
        )

    if plan.parent_run_id:
        lines += [
            "",
            "## Provenance",
            "",
            f"This Wide run was seeded from parent run "
            f"`{plan.parent_run_id}`.",
        ]

    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init",
                         help="Create new Wide run + decompose into TaskSpecs")
    pi.add_argument("--query", required=True,
                     help="User query (preserved for synthesizer)")
    pi.add_argument("--items", required=True,
                     help="Path to JSON file with list of item dicts")
    pi.add_argument("--type", required=True,
                     choices=list(TASK_TYPE_DEFAULTS.keys()),
                     help="Wide TaskSpec type")
    pi.add_argument("--parent-run-id", default=None,
                     help="Parent Deep run for L3 cumulative refinement")
    pi.add_argument("--allow-expensive", action="store_true",
                     help="Bypass $50 hard ceiling")
    pi.set_defaults(func=cmd_init)

    pd = sub.add_parser("decompose",
                         help="Show decomposition plan (HITL Gate 1)")
    pd.add_argument("--run-id", required=True)
    pd.add_argument("--format", choices=["json", "md"], default="json")
    pd.set_defaults(func=cmd_decompose)

    ps = sub.add_parser("show-spec",
                         help="Show one sub-agent's TaskSpec")
    ps.add_argument("--run-id", required=True)
    ps.add_argument("--sub-agent-id", required=True)
    ps.set_defaults(func=cmd_show_spec)

    pc = sub.add_parser("collect",
                         help="Fan-In: collect sub-agent results")
    pc.add_argument("--run-id", required=True)
    pc.add_argument("--write-outputs", action="store_true",
                     help="Write wide-output.csv + wide-output.md to run dir")
    pc.add_argument("--format", choices=["summary", "full"],
                     default="summary",
                     help="summary = counts; full = all per-item results")
    pc.set_defaults(func=cmd_collect)

    args = p.parse_args()
    out = args.func(args)
    if out is not None and out != {}:
        sys.stdout.write(json.dumps(out, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()
