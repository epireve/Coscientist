"""Wide Research — orchestrator-worker fan-out for processing N items.

v0.53.1 — POC: TaskSpec dataclass + orchestrator decomposition logic +
filesystem-as-memory for sub-agents. Single-sub-agent execution path
(synchronous). v0.53.2 adds asyncio fan-out via Claude Code Task tool.

Three modes total:
  - Quick: single agent, 30s-2min, $0.05-0.30
  - Deep: 10-phase Expedition pipeline (existing), 15-30min, $3-5
  - Wide: this module — orchestrator + N parallel sub-agents, 5-20min,
    $5-30, scales to 10-250 items

Wide TaskSpec types (v0.53.1 ships triage; v0.53.4 adds rest):
  - triage: relevance scoring across N candidate papers
  - read: PDF + extraction → structured per-paper data
  - rank: pairwise Elo
  - compare: per-item feature extraction across fixed schema
  - survey: per-author publication trajectory
  - screen: PRISMA-style include/exclude per criterion

Wide → Deep handoff (v0.53.5):
  - L1 seed: Wide-triage CSV → Deep scout
  - L2 full-text: Wide-read populates paper artifacts
  - L3 cumulative: Deep → Wide → Deep refinement

Engineering principles (Manus + Anthropic):
  - KV-cache stability: no timestamps in prompt prefixes
  - Filesystem-as-memory: each sub-agent writes to wide/<sub-id>/
  - Tool masking via Claude Code subagent_type frontmatter (not removal)
  - Error retention: failures stay in sub-agent context
  - Attention recitation: task_progress.md rewritten end-of-context
  - 15× token multiplier (Anthropic) — bounded via per-sub-agent
    max_tokens_budget + total run ceiling
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


WideTaskType = Literal[
    "triage", "read", "rank", "compare", "survey", "screen",
]


# Cost / token economics defaults
DEFAULT_MAX_TOOL_CALLS_PER_SUB = 15
DEFAULT_MAX_TOKENS_PER_SUB = 50_000
DEFAULT_CONCURRENCY_CAP = 30
HARD_DOLLAR_CEILING = 50.0  # block at $50 unless --allow-expensive
WIDE_THRESHOLD_ITEMS = 10   # below this, single-agent (Quick/Deep) wins
WIDE_MAX_ITEMS = 250        # above this, redirect to systematic-review skill


@dataclass
class TaskSpec:
    """Per-sub-agent input contract.

    Each sub-agent receives one TaskSpec and runs in fresh context with
    its own filesystem workspace. Sub-agents do not communicate; all
    coordination routes through orchestrator.
    """
    sub_agent_id: str             # e.g. "wide-<run_id>-item-007"
    task_type: WideTaskType        # triage / read / rank / compare / survey / screen
    objective: str                 # specific bounded task — not "research X" but
                                   # "find founding year, headcount, funding round of X"
    input_item: dict               # per-item input (e.g. paper metadata)
    output_schema: dict            # {fields: [...], format: "json|markdown|csv-row"}
    tools_allowed: list[str]       # subagent_type tool restriction
    tools_forbidden: list[str] = field(default_factory=list)
    scope_exclusions: str = ""     # "Other sub-agents are covering X, Y, Z — don't duplicate"
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS_PER_SUB
    max_tokens_budget: int = DEFAULT_MAX_TOKENS_PER_SUB
    filesystem_workspace: str = ""  # filled by orchestrator to wide/<sub-id>/

    def to_dict(self) -> dict:
        return {
            "sub_agent_id": self.sub_agent_id,
            "task_type": self.task_type,
            "objective": self.objective,
            "input_item": self.input_item,
            "output_schema": self.output_schema,
            "tools_allowed": self.tools_allowed,
            "tools_forbidden": self.tools_forbidden,
            "scope_exclusions": self.scope_exclusions,
            "max_tool_calls": self.max_tool_calls,
            "max_tokens_budget": self.max_tokens_budget,
            "filesystem_workspace": self.filesystem_workspace,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TaskSpec":
        return cls(
            sub_agent_id=d["sub_agent_id"],
            task_type=d["task_type"],
            objective=d["objective"],
            input_item=d.get("input_item", {}),
            output_schema=d.get("output_schema", {}),
            tools_allowed=d.get("tools_allowed", []),
            tools_forbidden=d.get("tools_forbidden", []),
            scope_exclusions=d.get("scope_exclusions", ""),
            max_tool_calls=d.get("max_tool_calls", DEFAULT_MAX_TOOL_CALLS_PER_SUB),
            max_tokens_budget=d.get("max_tokens_budget", DEFAULT_MAX_TOKENS_PER_SUB),
            filesystem_workspace=d.get("filesystem_workspace", ""),
        )

    def to_prompt(self) -> str:
        """Render TaskSpec as sub-agent system prompt.

        Stable prefix (no timestamps, no per-call variation) preserves
        KV-cache. Append-only context. Deterministic JSON serialization.
        """
        return f"""You are a Wide Research sub-agent (id: {self.sub_agent_id}).

## Task type
{self.task_type}

## Objective
{self.objective}

## Input item
{json.dumps(self.input_item, indent=2, sort_keys=True)}

## Output schema
{json.dumps(self.output_schema, indent=2, sort_keys=True)}

## Tools allowed
{', '.join(self.tools_allowed) if self.tools_allowed else '(none)'}

## Scope exclusions
{self.scope_exclusions or '(none — coordinate via orchestrator if you find duplicate scope)'}

## Filesystem workspace
{self.filesystem_workspace}

Write intermediate findings to your workspace. Keep only file paths
in context, not raw content. Maintain `task_progress.md` at the end of
your context — rewrite it as you make progress so the objective stays
in your recent attention window.

If a tool fails, the failure stays in your context. Read the error,
adapt your approach, do not repeat the failed action verbatim. Do not
attempt to hide errors from yourself — they are your evidence to learn
from.

Return final result as JSON matching the output schema above. Stop
when complete."""


@dataclass
class WideRunPlan:
    """Orchestrator's decomposition output, presented at HITL Gate 1."""
    run_id: str
    parent_run_id: str | None      # for Deep → Wide → Deep refinement loop
    task_type: WideTaskType
    user_query: str
    items: list[dict]              # input items (e.g. candidate papers)
    sub_specs: list[TaskSpec]
    estimated_total_tokens: int
    estimated_dollar_cost: float
    concurrency_cap: int = DEFAULT_CONCURRENCY_CAP

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "parent_run_id": self.parent_run_id,
            "task_type": self.task_type,
            "user_query": self.user_query,
            "n_items": len(self.items),
            "n_sub_agents": len(self.sub_specs),
            "estimated_total_tokens": self.estimated_total_tokens,
            "estimated_dollar_cost": round(self.estimated_dollar_cost, 2),
            "concurrency_cap": self.concurrency_cap,
            "sub_specs": [s.to_dict() for s in self.sub_specs],
        }

    def render_decomposition_table(self) -> str:
        """Markdown table for HITL Gate 1 user approval."""
        n = len(self.sub_specs)
        lines = [
            f"## Wide Research decomposition — run {self.run_id}",
            "",
            f"**Task type**: {self.task_type}",
            f"**Items**: {len(self.items)}",
            f"**Sub-agents**: {n}",
            f"**Concurrency cap**: {self.concurrency_cap}",
            f"**Estimated tokens**: {self.estimated_total_tokens:,}",
            f"**Estimated cost**: ${self.estimated_dollar_cost:.2f}",
            "",
        ]
        if self.estimated_dollar_cost > HARD_DOLLAR_CEILING:
            lines.append(
                f"⚠ Cost estimate ${self.estimated_dollar_cost:.2f} > "
                f"${HARD_DOLLAR_CEILING:.0f} hard ceiling. Pass "
                f"`--allow-expensive` to proceed."
            )
            lines.append("")

        lines += [
            "| # | Sub-agent | Objective (truncated) | Tools |",
            "|---|---|---|---|",
        ]
        for i, spec in enumerate(self.sub_specs):
            obj = spec.objective[:60] + "..." if len(spec.objective) > 60 else spec.objective
            tools = ", ".join(spec.tools_allowed[:3])
            lines.append(f"| {i+1} | `{spec.sub_agent_id}` | {obj} | {tools} |")
        return "\n".join(lines)


# TaskSpec defaults per task_type
TASK_TYPE_DEFAULTS: dict[WideTaskType, dict] = {
    "triage": {
        "tools_allowed": ["paper-discovery", "Read"],
        "output_schema": {
            "fields": ["canonical_id", "title", "year",
                        "relevance_score", "recommend", "reason"],
            "format": "json",
            "values": {
                "relevance_score": "float in [0, 1]",
                "recommend": "include | review | exclude",
            },
        },
        "max_tool_calls": 5,   # triage is light — just abstract reading
        "max_tokens_budget": 15_000,
    },
    "read": {
        "tools_allowed": ["paper-triage", "paper-acquire", "pdf-extract",
                           "arxiv-to-markdown", "Read"],
        "output_schema": {
            "fields": ["canonical_id", "method", "dataset", "results",
                        "limitations", "claims", "figures_referenced"],
            "format": "json",
        },
        "max_tool_calls": 25,
        "max_tokens_budget": 80_000,
    },
    "rank": {
        "tools_allowed": ["tournament", "Read"],
        "output_schema": {
            "fields": ["item_a", "item_b", "winner", "reasoning"],
            "format": "json",
        },
        "max_tool_calls": 5,
        "max_tokens_budget": 10_000,
    },
    "compare": {
        "tools_allowed": ["Read", "Bash"],
        "output_schema": {"fields": [], "format": "json"},
        "max_tool_calls": 15,
        "max_tokens_budget": 40_000,
    },
    "survey": {
        "tools_allowed": ["semantic-scholar", "Read"],
        "output_schema": {
            "fields": ["author", "h_index", "recent_venues",
                        "top_papers"],
            "format": "json",
        },
        "max_tool_calls": 10,
        "max_tokens_budget": 30_000,
    },
    "screen": {
        "tools_allowed": ["paper-triage", "Read"],
        "output_schema": {
            "fields": ["canonical_id", "include", "criteria_failed"],
            "format": "json",
        },
        "max_tool_calls": 8,
        "max_tokens_budget": 20_000,
    },
}


# Token-cost estimates (rough, for HITL Gate 1 display)
# Claude Sonnet pricing: $3/Mtok input, $15/Mtok output (uncached)
# Cached input: $0.30/Mtok (10× discount)
# Assume 30% cache hit rate average (conservative for new runs)
DEFAULT_INPUT_PRICE_PER_MTOK = 3.00
DEFAULT_OUTPUT_PRICE_PER_MTOK = 15.00
DEFAULT_CACHE_HIT_RATE = 0.30
DEFAULT_OUTPUT_RATIO = 0.01  # ~100:1 input:output ratio per Manus blog


def _estimate_cost(total_input_tokens: int, total_output_tokens: int) -> float:
    """Estimate $ cost given token totals + cache hit assumption."""
    cached = total_input_tokens * DEFAULT_CACHE_HIT_RATE
    uncached = total_input_tokens - cached
    input_cost = (
        cached * 0.30 / 1_000_000
        + uncached * DEFAULT_INPUT_PRICE_PER_MTOK / 1_000_000
    )
    output_cost = total_output_tokens * DEFAULT_OUTPUT_PRICE_PER_MTOK / 1_000_000
    # 15x multiplier for orchestrator + synthesizer overhead
    overhead = (input_cost + output_cost) * 0.15
    return input_cost + output_cost + overhead


def decompose(
    run_id: str,
    user_query: str,
    items: list[dict],
    task_type: WideTaskType,
    *,
    parent_run_id: str | None = None,
    custom_objective: str | None = None,
    custom_tools: list[str] | None = None,
    workspace_root: Path | None = None,
) -> WideRunPlan:
    """Orchestrator: decompose task into N TaskSpecs.

    Args:
        run_id: this Wide run's ID
        user_query: original user prompt (preserved for synthesizer)
        items: list of input items (papers, authors, protocols, etc.)
        task_type: which TaskSpec template to use
        parent_run_id: for Deep → Wide → Deep refinement (L3 handoff)
        custom_objective: override default objective string for task_type
        custom_tools: override default tools_allowed list
        workspace_root: ~/.cache/coscientist/runs/run-<id>/wide/

    Returns:
        WideRunPlan ready for HITL Gate 1 user approval.
    """
    n = len(items)
    if n < WIDE_THRESHOLD_ITEMS:
        raise ValueError(
            f"Wide Research requires ≥{WIDE_THRESHOLD_ITEMS} items "
            f"(got {n}). Use Quick or Deep mode for fewer items."
        )
    if n > WIDE_MAX_ITEMS:
        raise ValueError(
            f"Wide Research caps at {WIDE_MAX_ITEMS} items (got {n}). "
            f"Use systematic-review skill for larger corpora."
        )
    if task_type not in TASK_TYPE_DEFAULTS:
        raise ValueError(
            f"unknown task_type {task_type!r}; valid: "
            f"{list(TASK_TYPE_DEFAULTS)}"
        )

    defaults = TASK_TYPE_DEFAULTS[task_type]
    tools = custom_tools or defaults["tools_allowed"]
    workspace_root = workspace_root or Path.home() / ".cache/coscientist/runs"

    sub_specs: list[TaskSpec] = []
    for i, item in enumerate(items):
        sub_id = f"wide-{run_id}-item-{i:04d}"
        # Per-sub-agent objective: type default + item context
        if custom_objective:
            obj = f"{custom_objective} (item: {_summarize_item(item)})"
        else:
            obj = _default_objective(task_type, item)

        # scope_exclusions: tell each sub-agent what others are doing
        # so they don't duplicate
        scope_excl = (
            f"Other {n-1} sub-agents in this run are processing different "
            f"items of the same task type. Each sub-agent owns exactly "
            f"one item; do not search for or synthesize across other "
            f"items. Stay scoped to your input_item."
        )

        sub_specs.append(TaskSpec(
            sub_agent_id=sub_id,
            task_type=task_type,
            objective=obj,
            input_item=item,
            output_schema=defaults["output_schema"],
            tools_allowed=tools,
            scope_exclusions=scope_excl,
            max_tool_calls=defaults["max_tool_calls"],
            max_tokens_budget=defaults["max_tokens_budget"],
            filesystem_workspace=str(workspace_root / f"run-{run_id}/wide/{sub_id}"),
        ))

    # Cost estimation
    avg_input = sum(s.max_tokens_budget for s in sub_specs)
    avg_output = int(avg_input * DEFAULT_OUTPUT_RATIO)
    cost = _estimate_cost(avg_input, avg_output)

    return WideRunPlan(
        run_id=run_id,
        parent_run_id=parent_run_id,
        task_type=task_type,
        user_query=user_query,
        items=items,
        sub_specs=sub_specs,
        estimated_total_tokens=avg_input + avg_output,
        estimated_dollar_cost=cost,
    )


def _summarize_item(item: dict) -> str:
    """Brief item summary for objective string."""
    if "title" in item:
        return item["title"][:80]
    if "canonical_id" in item:
        return item["canonical_id"]
    if "name" in item:
        return item["name"]
    return str(item)[:80]


def _default_objective(task_type: WideTaskType, item: dict) -> str:
    """Per-task-type default objective, item-aware."""
    title = item.get("title", "this item")
    cid = item.get("canonical_id", "")
    if task_type == "triage":
        return (
            f"Read the abstract of '{title}'. Score relevance to "
            f"the user's research query (0-1). Recommend "
            f"include|review|exclude with one-sentence reason. "
            f"Tools: paper-discovery for metadata if missing."
        )
    if task_type == "read":
        return (
            f"For paper '{title}' ({cid}): run paper-triage; if "
            f"sufficient=false, run paper-acquire; run pdf-extract or "
            f"arxiv-to-markdown. Emit structured: method, dataset, "
            f"results, limitations, key claims, figures referenced."
        )
    if task_type == "rank":
        return (
            f"Compare item_a vs item_b on the user's ranking criterion. "
            f"Pick winner; record reasoning. Updates Elo via tournament."
        )
    if task_type == "compare":
        return (
            f"Extract features per the output schema for '{title}'. "
            f"Stay within the schema; do not invent fields."
        )
    if task_type == "survey":
        return (
            f"For author '{item.get('name', cid)}': fetch h-index, "
            f"recent venues, top 10 papers. Use semantic-scholar."
        )
    if task_type == "screen":
        return (
            f"Apply PRISMA inclusion/exclusion criteria to '{title}'. "
            f"Return include: bool + criteria_failed: list."
        )
    return f"Process '{title}'."


def write_workspace(spec: TaskSpec) -> Path:
    """Create sub-agent's filesystem workspace + initial files.

    Returns workspace path. Creates:
      - taskspec.json (the spec itself, for sub-agent to re-read)
      - task_progress.md (initial; sub-agent rewrites as it works)
      - findings/ (directory for intermediate results)
    """
    ws = Path(spec.filesystem_workspace)
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "taskspec.json").write_text(
        json.dumps(spec.to_dict(), indent=2, sort_keys=True)
    )
    (ws / "task_progress.md").write_text(
        f"# Task progress — {spec.sub_agent_id}\n\n"
        f"## Objective\n{spec.objective}\n\n"
        f"## Status\nINITIALIZED\n\n"
        f"## Steps\n_(rewrite this section as you progress)_\n"
    )
    (ws / "findings").mkdir(exist_ok=True)
    return ws


def collect_results(plan: WideRunPlan) -> list[dict]:
    """Read each sub-agent's final output from filesystem.

    Each sub-agent writes its result to <workspace>/result.json when
    COMPLETE. Orchestrator's synthesizer reads these as file refs +
    summaries (not raw — minimizes synthesizer context bloat).
    """
    results: list[dict] = []
    for spec in plan.sub_specs:
        ws = Path(spec.filesystem_workspace)
        result_path = ws / "result.json"
        progress_path = ws / "task_progress.md"
        entry = {
            "sub_agent_id": spec.sub_agent_id,
            "task_type": spec.task_type,
            "input_item_summary": _summarize_item(spec.input_item),
            "result_path": str(result_path),
            "progress_path": str(progress_path),
        }
        if result_path.exists():
            try:
                entry["result"] = json.loads(result_path.read_text())
                entry["status"] = "complete"
            except (json.JSONDecodeError, OSError) as e:
                entry["status"] = f"parse_error: {e}"
        else:
            entry["status"] = "missing"
        results.append(entry)
    return results
