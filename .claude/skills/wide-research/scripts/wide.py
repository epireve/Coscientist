#!/usr/bin/env python3
"""wide-research CLI — orchestrator for fan-out sub-agent runs.

v0.53.1 POC: init + decompose + show-plan + collect.
v0.53.2: gate1 (HITL approval) + dispatch-manifest (for parent agent
to fire N parallel Task tool calls) + status (per-sub-agent state).
v0.53.3: gate2 (mid-research preview) + gate3 (pre-synthesis flag
re-runs) + observe (token + dollar tracking from sub-agent telemetry).

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

_HERE = Path(__file__).resolve()
# parents[3] = plugin layout (vendored lib/ at plugin root)
# parents[4] = repo layout (.claude/ inside project root with lib/)
# Try both: plugin layout first (matches other skill scripts), then repo.
_PLUGIN_ROOT = _HERE.parents[3]
_REPO_ROOT = _HERE.parents[4] if (_HERE.parents[4] / "lib").exists() else _PLUGIN_ROOT
for _p in (_REPO_ROOT, _PLUGIN_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import sqlite3  # noqa: E402

from lib.cache import cache_root  # noqa: E402
from lib.db_notify import format_notification, record_write  # noqa: E402
from lib.migrations import ensure_current  # noqa: E402
from lib.wide_research import (  # noqa: E402
    DEFAULT_CONCURRENCY_CAP, HARD_DOLLAR_CEILING, TASK_TYPE_DEFAULTS,
    TaskSpec, WideRunPlan, collect_results, decompose, write_workspace,
)
from lib.wide_synthesis import render_brief, synthesize  # noqa: E402


def _wide_db_path(run_id: str) -> Path:
    """Per-Wide-run DB at ~/.cache/coscientist/runs/wide-<rid>.db.

    Mirrors Deep convention (run-<rid>.db). Holds wide_runs +
    wide_sub_agents rows scoped to this Wide run.
    """
    return cache_root() / "runs" / f"wide-{run_id}.db"


def _connect_wide_db(run_id: str) -> sqlite3.Connection:
    """Open (or create) the Wide-run DB; ensure migrations applied.

    v0.66: returns a WAL-mode connection so the orchestrator-worker
    fan-out (cap 30 concurrent sub-agents) can persist results without
    SQLITE_BUSY contention against parallel writers.
    """
    db = _wide_db_path(run_id)
    fresh = not db.exists()
    if fresh:
        # Build base schema first so migration v9 finds expected tables
        db.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(db)
        schema = (_REPO_ROOT / "lib" / "sqlite_schema.sql").read_text()
        con.executescript(schema)
        con.close()
    ensure_current(db)
    from lib.cache import connect_wal
    return connect_wal(db)


def _emit_notification(note: dict) -> None:
    """Print db-notify line to stderr (visible to orchestrator)."""
    sys.stderr.write(format_notification(note) + "\n")


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

    # Resolve compare schema (compare task_type only)
    compare_schema_fields: list[str] | None = None
    if getattr(args, "compare_schema", None):
        cs_path = Path(args.compare_schema)
        if cs_path.exists():
            cs_data = json.loads(cs_path.read_text())
            if isinstance(cs_data, list):
                compare_schema_fields = [str(x) for x in cs_data]
            elif isinstance(cs_data, dict) and "fields" in cs_data:
                compare_schema_fields = [str(x) for x in cs_data["fields"]]
            else:
                raise SystemExit(
                    "--compare-schema must be JSON list or "
                    "{fields: [...]}"
                )
        else:
            # Treat as comma-list literal
            compare_schema_fields = [
                s.strip() for s in args.compare_schema.split(",")
                if s.strip()
            ]

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

    # Override compare schema if provided
    if compare_schema_fields and args.type == "compare":
        for spec in plan.sub_specs:
            spec.output_schema = {
                "fields": compare_schema_fields,
                "format": "json",
            }
    if compare_schema_fields and args.type != "compare":
        raise SystemExit(
            "--compare-schema only valid with --type compare"
        )

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

    # v0.57 — persist Wide run + sub-agent rows to per-Wide DB
    from datetime import UTC, datetime
    now = datetime.now(UTC).isoformat()
    con = _connect_wide_db(run_id)
    try:
        with con:
            con.execute(
                "INSERT INTO wide_runs (wide_run_id, parent_run_id, "
                "user_query, task_type, n_items, n_sub_agents, "
                "estimated_dollar_cost, estimated_total_tokens, "
                "concurrency_cap, plan_path, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, args.parent_run_id, args.query, args.type,
                 len(items), len(plan.sub_specs),
                 plan.estimated_dollar_cost,
                 plan.estimated_total_tokens,
                 plan.concurrency_cap,
                 str(_plan_path(run_id)), now),
            )
            for spec in plan.sub_specs:
                con.execute(
                    "INSERT INTO wide_sub_agents (sub_agent_id, "
                    "wide_run_id, task_type, state, "
                    "input_item_summary, workspace, at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (spec.sub_agent_id, run_id, spec.task_type,
                     "INITIALIZED",
                     str(spec.input_item)[:200],
                     spec.filesystem_workspace, now),
                )
        n_run = record_write(
            con, "wide_runs", 1, "wide-research",
            run_id=run_id,
            detail=f"task_type={args.type}, n_items={len(items)}",
        )
        n_sub = record_write(
            con, "wide_sub_agents", len(plan.sub_specs), "wide-research",
            run_id=run_id,
        )
        _emit_notification(n_run)
        _emit_notification(n_sub)
    finally:
        con.close()

    return {
        "run_id": run_id,
        "n_items": len(items),
        "n_sub_agents": len(plan.sub_specs),
        "task_type": args.type,
        "estimated_total_tokens": plan.estimated_total_tokens,
        "estimated_dollar_cost": plan.estimated_dollar_cost,
        "concurrency_cap": plan.concurrency_cap,
        "plan_path": str(_plan_path(run_id)),
        "wide_db_path": str(_wide_db_path(run_id)),
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


def cmd_gate1(args: argparse.Namespace) -> dict:
    """HITL Gate 1 — record user approval/rejection of decomposition.

    Parent agent invokes this AFTER showing user the decomposition
    table (via `decompose --format md`). User decides; parent agent
    passes the verdict here. On approve, plan.json gets gate1_approved
    + gate1_at timestamp. On reject, run is marked aborted.
    """
    p = _plan_path(args.run_id)
    if not p.exists():
        raise SystemExit(f"no plan for run {args.run_id}")
    plan_dict = json.loads(p.read_text())

    if args.verdict == "approve":
        plan_dict["gate1_approved"] = True
        plan_dict["gate1_user_input"] = args.user_input or ""
        plan_dict["aborted"] = False
    elif args.verdict == "reject":
        plan_dict["gate1_approved"] = False
        plan_dict["gate1_user_input"] = args.user_input or ""
        plan_dict["aborted"] = True
    else:
        raise SystemExit(f"unknown verdict: {args.verdict}")

    p.write_text(json.dumps(plan_dict, indent=2, sort_keys=True))
    return {
        "run_id": args.run_id,
        "verdict": args.verdict,
        "next_step": (
            "Run `wide.py dispatch-manifest --run-id "
            f"{args.run_id}` to get the JSON manifest, then fire "
            "parallel Task tool calls."
        ) if args.verdict == "approve" else "Run aborted at Gate 1.",
    }


def cmd_dispatch_manifest(args: argparse.Namespace) -> dict:
    """Emit dispatch manifest for parent agent's Task-tool fan-out.

    Parent agent reads this manifest, then in a SINGLE message issues
    N parallel Task tool calls (one per sub-agent). Each Task call
    receives the sub-agent's TaskSpec prompt as input. Sub-agents run
    in fresh contexts, write result.json to their workspaces, return
    summary to parent.

    Concurrency cap (30) enforced here — manifest chunked into batches
    if N > cap. Parent agent processes batches sequentially; within a
    batch, all calls are parallel.

    Refuses to emit manifest unless gate1_approved=True (HITL discipline).
    """
    p = _plan_path(args.run_id)
    if not p.exists():
        raise SystemExit(f"no plan for run {args.run_id}")
    plan_dict = json.loads(p.read_text())

    if not plan_dict.get("gate1_approved"):
        raise SystemExit(
            f"Gate 1 not approved for run {args.run_id}. Run "
            f"`wide.py gate1 --run-id {args.run_id} --verdict approve` "
            f"first."
        )

    sub_specs = [TaskSpec.from_dict(s) for s in plan_dict["sub_specs"]]
    cap = plan_dict.get("concurrency_cap", DEFAULT_CONCURRENCY_CAP)
    # v0.53.3 gate2 adjust_remaining persists this set
    skipped_ids = set(plan_dict.get("skipped_sub_agent_ids", []) or [])

    # Skip already-complete or gate2-skipped sub-agents (idempotent re-dispatch)
    pending: list[dict] = []
    for spec in sub_specs:
        if spec.sub_agent_id in skipped_ids and not args.force_redispatch:
            continue
        ws = Path(spec.filesystem_workspace)
        result_path = ws / "result.json"
        if result_path.exists() and not args.force_redispatch:
            continue
        pending.append({
            "sub_agent_id": spec.sub_agent_id,
            "subagent_type": _resolve_subagent_type(spec.task_type),
            "task_type": spec.task_type,
            "prompt": spec.to_prompt(),
            "workspace": spec.filesystem_workspace,
            "max_tool_calls": spec.max_tool_calls,
            "max_tokens_budget": spec.max_tokens_budget,
        })

    # Chunk into batches
    batches: list[list[dict]] = []
    for i in range(0, len(pending), cap):
        batches.append(pending[i:i + cap])

    return {
        "run_id": args.run_id,
        "task_type": plan_dict["task_type"],
        "n_total": len(sub_specs),
        "n_pending": len(pending),
        "n_already_complete": len(sub_specs) - len(pending),
        "concurrency_cap": cap,
        "n_batches": len(batches),
        "batches": batches,
        "instructions": (
            f"Parent agent: for each batch, fire ALL Task tool calls "
            f"in a SINGLE message (parallel). Use subagent_type="
            f"general-purpose unless task_type maps to a registered "
            f"sub-agent type. Process batches sequentially (wait for "
            f"each batch to complete before starting the next). After "
            f"all batches done, run `wide.py collect --run-id "
            f"{args.run_id} --write-outputs`."
        ),
    }


_TASK_TYPE_TO_SUBAGENT = {
    "triage": "wide-triage",
    "read": "wide-read",
    "rank": "wide-rank",
    "compare": "wide-compare",
    "survey": "wide-survey",
    "screen": "wide-screen",
}


def _resolve_subagent_type(task_type: str) -> str:
    """Map Wide task_type → Claude Code subagent_type.

    v0.53.6 — registered dedicated wide-<type> sub-agents in
    .claude/agents/. Falls back to general-purpose for unknown types
    (forward-compat) or when the agent file is missing on disk.
    """
    candidate = _TASK_TYPE_TO_SUBAGENT.get(task_type)
    if not candidate:
        return "general-purpose"
    agent_path = (
        _REPO_ROOT / ".claude" / "agents" / f"{candidate}.md"
    )
    if not agent_path.exists():
        return "general-purpose"
    return candidate


def cmd_status(args: argparse.Namespace) -> dict:
    """Per-sub-agent execution status.

    Reads each sub-agent workspace's state markers:
      - taskspec.json present → INITIALIZED
      - findings/* present + no result.json → IN_PROGRESS
      - result.json present + parses as JSON → COMPLETE
      - result.json present but malformed → ERROR
    """
    p = _plan_path(args.run_id)
    if not p.exists():
        raise SystemExit(f"no plan for run {args.run_id}")
    plan_dict = json.loads(p.read_text())
    sub_specs = [TaskSpec.from_dict(s) for s in plan_dict["sub_specs"]]

    by_state = {"INITIALIZED": 0, "IN_PROGRESS": 0,
                "COMPLETE": 0, "ERROR": 0}
    rows: list[dict] = []
    for spec in sub_specs:
        ws = Path(spec.filesystem_workspace)
        result_path = ws / "result.json"
        findings_dir = ws / "findings"
        n_findings = (
            len(list(findings_dir.iterdir()))
            if findings_dir.exists() else 0
        )

        if result_path.exists():
            try:
                json.loads(result_path.read_text())
                state = "COMPLETE"
            except (json.JSONDecodeError, OSError):
                state = "ERROR"
        elif n_findings > 0:
            state = "IN_PROGRESS"
        else:
            state = "INITIALIZED"
        by_state[state] += 1
        rows.append({
            "sub_agent_id": spec.sub_agent_id,
            "state": state,
            "n_findings": n_findings,
        })

    return {
        "run_id": args.run_id,
        "task_type": plan_dict["task_type"],
        "by_state": by_state,
        "n_total": len(sub_specs),
        "complete_pct": (
            round(by_state["COMPLETE"] / len(sub_specs) * 100, 1)
            if sub_specs else 0.0
        ),
        "sub_agents": rows if args.verbose else None,
    }


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


def cmd_gate2(args: argparse.Namespace) -> dict:
    """HITL Gate 2 — mid-research preview after N% sub-agents complete.

    Fires when parent agent calls this with current --threshold-pct
    crossed (default 30%). Returns preview of completed results so
    user can spot systematic errors (wrong source, wrong field
    interpretation) BEFORE remaining sub-agents finish.

    User options:
      - approve_continue: proceed unchanged
      - adjust_remaining: skip remaining sub-agents (orchestrator
        marks plan partial-complete; collect still works on N% done)
      - abort: terminate run

    Persisted to plan.json as gate2_records (list, since this gate
    can fire multiple times across long runs).
    """
    p = _plan_path(args.run_id)
    if not p.exists():
        raise SystemExit(f"no plan for run {args.run_id}")
    plan_dict = json.loads(p.read_text())

    sub_specs = [TaskSpec.from_dict(s) for s in plan_dict["sub_specs"]]
    n_complete = sum(
        1 for s in sub_specs
        if (Path(s.filesystem_workspace) / "result.json").exists()
    )
    pct = (n_complete / len(sub_specs) * 100) if sub_specs else 0.0

    if args.verdict == "preview":
        # Read-only — emit current preview, don't mutate plan
        plan = WideRunPlan(
            run_id=plan_dict["run_id"],
            parent_run_id=plan_dict.get("parent_run_id"),
            task_type=plan_dict["task_type"],
            user_query=plan_dict["user_query"],
            items=[], sub_specs=sub_specs,
            estimated_total_tokens=plan_dict["estimated_total_tokens"],
            estimated_dollar_cost=plan_dict["estimated_dollar_cost"],
            concurrency_cap=plan_dict["concurrency_cap"],
        )
        results = collect_results(plan)
        return {
            "run_id": args.run_id,
            "n_complete": n_complete,
            "n_total": len(sub_specs),
            "complete_pct": round(pct, 1),
            "preview_results": [
                r for r in results if r["status"] == "complete"
            ][:args.preview_limit],
            "next_step": (
                f"Review preview. Then call gate2 --verdict "
                f"approve_continue|adjust_remaining|abort."
            ),
        }

    # Mutate plan
    record = {
        "verdict": args.verdict,
        "at_pct": round(pct, 1),
        "n_complete_at_gate": n_complete,
        "user_input": args.user_input or "",
    }
    plan_dict.setdefault("gate2_records", []).append(record)

    if args.verdict == "abort":
        plan_dict["aborted"] = True

    if args.verdict == "adjust_remaining":
        # Mark remaining sub-agents as skipped via skip flag
        plan_dict["adjust_remaining_at_gate2"] = True
        # Concrete skip logic: dispatch-manifest filters skipped ids
        plan_dict["skipped_sub_agent_ids"] = [
            s.sub_agent_id for s in sub_specs
            if not (Path(s.filesystem_workspace) / "result.json").exists()
        ]

    p.write_text(json.dumps(plan_dict, indent=2, sort_keys=True))
    return {
        "run_id": args.run_id,
        "verdict": args.verdict,
        "n_complete": n_complete,
        "n_total": len(sub_specs),
        "complete_pct": round(pct, 1),
        "n_skipped": len(plan_dict.get("skipped_sub_agent_ids", [])),
    }


def cmd_gate3(args: argparse.Namespace) -> dict:
    """HITL Gate 3 — pre-synthesis: flag items for re-run.

    Fires after all (non-skipped) sub-agents complete, before
    synthesizer roll-up. User reviews per-item results, marks IDs
    needing re-research with optional additional guidance.

    Re-flagged sub-agents have their result.json renamed to
    result.previous.json and their plan entry gets rerun_guidance
    appended. Subsequent dispatch-manifest will pick them up
    (no result.json present).
    """
    p = _plan_path(args.run_id)
    if not p.exists():
        raise SystemExit(f"no plan for run {args.run_id}")
    plan_dict = json.loads(p.read_text())
    sub_specs = [TaskSpec.from_dict(s) for s in plan_dict["sub_specs"]]

    if args.list_results:
        results = collect_results(WideRunPlan(
            run_id=plan_dict["run_id"],
            parent_run_id=plan_dict.get("parent_run_id"),
            task_type=plan_dict["task_type"],
            user_query=plan_dict["user_query"],
            items=[], sub_specs=sub_specs,
            estimated_total_tokens=plan_dict["estimated_total_tokens"],
            estimated_dollar_cost=plan_dict["estimated_dollar_cost"],
            concurrency_cap=plan_dict["concurrency_cap"],
        ))
        return {"run_id": args.run_id, "results": results}

    # Flag IDs for re-run
    flagged = args.flag_ids.split(",") if args.flag_ids else []
    if not flagged:
        raise SystemExit(
            "Pass --flag-ids id1,id2,... or --list-results to inspect"
        )

    n_renamed = 0
    flagged_records: list[dict] = []
    spec_by_id = {s.sub_agent_id: s for s in sub_specs}

    for sub_id in flagged:
        sub_id = sub_id.strip()
        if sub_id not in spec_by_id:
            raise SystemExit(
                f"unknown sub_agent_id {sub_id!r} in run {args.run_id}"
            )
        spec = spec_by_id[sub_id]
        ws = Path(spec.filesystem_workspace)
        result = ws / "result.json"
        if result.exists():
            archive = ws / "result.previous.json"
            archive.write_text(result.read_text())
            result.unlink()
            n_renamed += 1
        flagged_records.append({
            "sub_agent_id": sub_id,
            "rerun_guidance": args.guidance or "",
        })

    plan_dict.setdefault("gate3_rerun_flags", []).extend(flagged_records)
    p.write_text(json.dumps(plan_dict, indent=2, sort_keys=True))

    return {
        "run_id": args.run_id,
        "flagged_count": len(flagged),
        "results_archived": n_renamed,
        "next_step": (
            f"Run `wide.py dispatch-manifest --run-id {args.run_id}` "
            f"to re-dispatch flagged sub-agents (their workspaces no "
            f"longer have result.json so they'll be in n_pending)."
        ),
    }


def cmd_synthesize(args: argparse.Namespace) -> dict:
    """Fresh-context per-type roll-up — Fan-In synthesizer.

    v0.53.4. Reads result.json refs only (no raw payload bloat).
    Writes:
      - synthesis.json (structured per-type output)
      - synthesis.md (markdown brief)
      - wide-output.csv (mode-specific tabular)
    """
    p = _plan_path(args.run_id)
    if not p.exists():
        raise SystemExit(f"no plan for run {args.run_id}")
    plan_dict = json.loads(p.read_text())
    sub_specs = [TaskSpec.from_dict(s) for s in plan_dict["sub_specs"]]
    plan = WideRunPlan(
        run_id=plan_dict["run_id"],
        parent_run_id=plan_dict.get("parent_run_id"),
        task_type=plan_dict["task_type"],
        user_query=plan_dict["user_query"],
        items=[], sub_specs=sub_specs,
        estimated_total_tokens=plan_dict["estimated_total_tokens"],
        estimated_dollar_cost=plan_dict["estimated_dollar_cost"],
        concurrency_cap=plan_dict["concurrency_cap"],
    )

    results = collect_results(plan)
    synthesis = synthesize(
        plan.task_type, results, user_query=plan.user_query,
    )

    run_dir = _wide_run_dir(args.run_id)
    if args.write_outputs:
        (run_dir / "synthesis.json").write_text(
            json.dumps(synthesis, indent=2, sort_keys=True, default=str)
        )
        (run_dir / "synthesis.md").write_text(render_brief(synthesis))
        # Also (re)write CSV from results (per-row tabular)
        (run_dir / "wide-output.csv").write_text(
            "\n".join(_to_csv(results, plan.task_type))
        )

        # v0.57 — update wide_runs.synthesis_path + completed_at;
        # update sub_agent state per result
        from datetime import UTC, datetime
        now = datetime.now(UTC).isoformat()
        if _wide_db_path(args.run_id).exists():
            con = _connect_wide_db(args.run_id)
            try:
                with con:
                    con.execute(
                        "UPDATE wide_runs SET synthesis_path=?, "
                        "completed_at=? WHERE wide_run_id=?",
                        (str(run_dir / "synthesis.json"), now, args.run_id),
                    )
                    for r in results:
                        state = "COMPLETE" if r["status"] == "complete" \
                            else ("ERROR" if r["status"].startswith(
                                "parse_error") else "INITIALIZED")
                        con.execute(
                            "UPDATE wide_sub_agents SET state=?, "
                            "result_path=?, at=? "
                            "WHERE sub_agent_id=?",
                            (state, r.get("result_path"), now,
                             r["sub_agent_id"]),
                        )
                note = record_write(
                    con, "wide_runs", 1, "wide-research",
                    run_id=args.run_id,
                    detail="synthesis complete",
                )
                _emit_notification(note)
            finally:
                con.close()

    summary = {
        "run_id": args.run_id,
        "task_type": plan.task_type,
        "n_total": synthesis["n_total"],
        "n_complete": synthesis["n_complete"],
        "n_missing": synthesis["n_missing"],
        "n_error": synthesis["n_error"],
        "synthesis_json_path": (
            str(run_dir / "synthesis.json")
            if args.write_outputs else None
        ),
        "synthesis_md_path": (
            str(run_dir / "synthesis.md")
            if args.write_outputs else None
        ),
    }
    if args.format == "full":
        summary["synthesis"] = synthesis
    return summary


def cmd_timeout_sweep(args: argparse.Namespace) -> dict:
    """Mark stale IN_PROGRESS sub-agents as timeout errors.

    v0.53.7. A sub-agent that wrote `findings/` files but never wrote
    `result.json` is IN_PROGRESS. If its workspace mtime is older than
    --max-age-min minutes, it likely crashed or was abandoned. We
    write a synthetic `result.json` with `{error: "timeout"}` so:
      - status shows ERROR (not IN_PROGRESS forever)
      - collect/synthesize counts it correctly under n_error
      - dispatch-manifest can pick it up via --force-redispatch

    Pure mtime sweep, no kill-9 (sub-agents run in caller's harness;
    this script doesn't manage their processes).

    --dry-run prints what would change without mutating.
    """
    import time
    p = _plan_path(args.run_id)
    if not p.exists():
        raise SystemExit(f"no plan for run {args.run_id}")
    plan_dict = json.loads(p.read_text())
    sub_specs = [TaskSpec.from_dict(s) for s in plan_dict["sub_specs"]]

    cutoff = time.time() - (args.max_age_min * 60)
    swept: list[dict] = []
    for spec in sub_specs:
        ws = Path(spec.filesystem_workspace)
        result_path = ws / "result.json"
        if result_path.exists():
            continue
        findings_dir = ws / "findings"
        # Latest activity = newest mtime among workspace files
        candidates = [ws / "task_progress.md", ws / "taskspec.json"]
        if findings_dir.exists():
            candidates.extend(findings_dir.iterdir())
        mtimes = [c.stat().st_mtime for c in candidates if c.exists()]
        if not mtimes:
            continue
        latest = max(mtimes)
        if latest >= cutoff:
            continue
        # Stale — sweep
        swept.append({
            "sub_agent_id": spec.sub_agent_id,
            "stale_seconds": int(time.time() - latest),
            "workspace": str(ws),
        })
        if not args.dry_run:
            result_path.write_text(json.dumps({
                "error": "timeout",
                "swept_at": time.time(),
                "stale_seconds": int(time.time() - latest),
                "max_age_min": args.max_age_min,
            }, indent=2, sort_keys=True))

    return {
        "run_id": args.run_id,
        "max_age_min": args.max_age_min,
        "dry_run": args.dry_run,
        "n_swept": len(swept),
        "swept": swept,
    }


def cmd_observe(args: argparse.Namespace) -> dict:
    """Run-level observability — actual token + dollar usage.

    Reads each sub-agent's telemetry.json (if present) and aggregates.
    Telemetry schema (sub-agent writes on COMPLETE):
      {
        "input_tokens": int,
        "output_tokens": int,
        "n_tool_calls": int,
        "duration_ms": int,
        "errors": [list of error strings]
      }

    Compares against plan's estimated cost. Flags overrun.
    """
    p = _plan_path(args.run_id)
    if not p.exists():
        raise SystemExit(f"no plan for run {args.run_id}")
    plan_dict = json.loads(p.read_text())
    sub_specs = [TaskSpec.from_dict(s) for s in plan_dict["sub_specs"]]

    totals = {
        "input_tokens": 0, "output_tokens": 0,
        "n_tool_calls": 0, "duration_ms": 0,
        "n_errors": 0, "n_with_telemetry": 0,
    }
    per_agent: list[dict] = []
    for spec in sub_specs:
        ws = Path(spec.filesystem_workspace)
        tel_path = ws / "telemetry.json"
        if not tel_path.exists():
            continue
        try:
            tel = json.loads(tel_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        totals["n_with_telemetry"] += 1
        totals["input_tokens"] += tel.get("input_tokens", 0)
        totals["output_tokens"] += tel.get("output_tokens", 0)
        totals["n_tool_calls"] += tel.get("n_tool_calls", 0)
        totals["duration_ms"] += tel.get("duration_ms", 0)
        totals["n_errors"] += len(tel.get("errors", []))
        per_agent.append({
            "sub_agent_id": spec.sub_agent_id,
            **tel,
        })

    # Cost reconstruction (matches lib.wide_research._estimate_cost)
    from lib.wide_research import _estimate_cost
    actual_cost = _estimate_cost(
        totals["input_tokens"], totals["output_tokens"]
    )
    estimated_cost = plan_dict["estimated_dollar_cost"]
    overrun_pct = (
        ((actual_cost - estimated_cost) / estimated_cost * 100)
        if estimated_cost > 0 else 0.0
    )

    summary = {
        "run_id": args.run_id,
        "task_type": plan_dict["task_type"],
        "n_total": len(sub_specs),
        "totals": totals,
        "estimated_cost": round(estimated_cost, 4),
        "actual_cost": round(actual_cost, 4),
        "overrun_pct": round(overrun_pct, 1),
        "alert": (
            "OVERRUN" if overrun_pct > 20.0
            else "WITHIN_BUDGET"
        ),
    }
    if args.verbose:
        summary["per_agent"] = per_agent
    return summary


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
    pi.add_argument("--compare-schema", default=None,
                     help="(compare task_type only) JSON file with "
                          "{fields:[...]} or comma-separated field list "
                          "to use as output schema")
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

    # v0.53.2 — gate1, dispatch-manifest, status
    pg = sub.add_parser("gate1",
                         help="HITL Gate 1 — record user verdict on decomposition")
    pg.add_argument("--run-id", required=True)
    pg.add_argument("--verdict", required=True,
                     choices=["approve", "reject"])
    pg.add_argument("--user-input", default="",
                     help="Free-text user input/comments")
    pg.set_defaults(func=cmd_gate1)

    pdm = sub.add_parser("dispatch-manifest",
                          help="Emit JSON manifest for parent agent's "
                               "Task-tool fan-out (post-Gate-1)")
    pdm.add_argument("--run-id", required=True)
    pdm.add_argument("--force-redispatch", action="store_true",
                      help="Re-dispatch sub-agents that already have "
                           "result.json (default: skip them)")
    pdm.set_defaults(func=cmd_dispatch_manifest)

    pst = sub.add_parser("status",
                          help="Per-sub-agent execution status")
    pst.add_argument("--run-id", required=True)
    pst.add_argument("--verbose", action="store_true",
                      help="Include per-sub-agent rows (default: counts only)")
    pst.set_defaults(func=cmd_status)

    # v0.53.3 — gate2 (mid-research preview), gate3 (pre-synthesis flag),
    # observe (token + dollar tracking)
    pg2 = sub.add_parser("gate2",
                          help="HITL Gate 2 — mid-research preview")
    pg2.add_argument("--run-id", required=True)
    pg2.add_argument("--verdict", required=True,
                      choices=["preview", "approve_continue",
                                "adjust_remaining", "abort"])
    pg2.add_argument("--user-input", default="")
    pg2.add_argument("--preview-limit", type=int, default=5,
                      help="Max preview results when --verdict preview")
    pg2.set_defaults(func=cmd_gate2)

    pg3 = sub.add_parser("gate3",
                          help="HITL Gate 3 — flag items for re-run")
    pg3.add_argument("--run-id", required=True)
    pg3.add_argument("--list-results", action="store_true",
                      help="List per-item results for review")
    pg3.add_argument("--flag-ids", default="",
                      help="Comma-separated sub_agent_ids to re-run")
    pg3.add_argument("--guidance", default="",
                      help="Re-run guidance for flagged sub-agents")
    pg3.set_defaults(func=cmd_gate3)

    pts = sub.add_parser("timeout-sweep",
                          help="Mark stale IN_PROGRESS sub-agents as timeout errors")
    pts.add_argument("--run-id", required=True)
    pts.add_argument("--max-age-min", type=int, default=30,
                      help="Sub-agents idle longer than N minutes get "
                           "swept (default: 30)")
    pts.add_argument("--dry-run", action="store_true",
                      help="Report sweep candidates without mutating")
    pts.set_defaults(func=cmd_timeout_sweep)

    po = sub.add_parser("observe",
                         help="Run-level token + dollar usage from telemetry")
    po.add_argument("--run-id", required=True)
    po.add_argument("--verbose", action="store_true")
    po.set_defaults(func=cmd_observe)

    # v0.53.4 — synthesize (per-type fresh-context fan-in)
    psy = sub.add_parser("synthesize",
                          help="Per-type roll-up over collected results")
    psy.add_argument("--run-id", required=True)
    psy.add_argument("--write-outputs", action="store_true",
                      help="Write synthesis.json + synthesis.md to run dir")
    psy.add_argument("--format", choices=["summary", "full"],
                      default="summary")
    psy.set_defaults(func=cmd_synthesize)

    args = p.parse_args()
    out = args.func(args)
    if out is not None and out != {}:
        sys.stdout.write(json.dumps(out, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()
