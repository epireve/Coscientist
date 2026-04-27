# Research Modes — Plan

_Status: design draft. Builds on v0.50-v0.52 deep-research. Quality audit (run a933c2db, see QUALITY-AUDIT-a933c2db.md) motivates this._

## Three modes

Coscientist now ships **deep-research** (v0.50-v0.52). Plan adds two more, plus reframes existing as named mode.

| Mode | Use when | Pipeline shape | Time | Cost (approx) | Output |
|---|---|---|---|---|---|
| **Quick** | Single fact-finding, name-of-paper lookup, "what's X" | Single agent, 3-10 tool calls | 30s-2min | $0.05-$0.30 | Direct answer + 3-5 cited papers |
| **Deep** (existing) | Sharpen a research question; map a field's tensions; generate hypotheses | 10-phase Expedition + 3 break points | 15-30 min | $3-5 | brief.md + understanding_map.md + eval.md |
| **Wide** (NEW) | Process N items in parallel — survey 100+ papers, screen meta-analysis candidates, profile a subfield's authors, compare 50 protocols | Orchestrator → fan-out N sub-agents → synthesizer | 5-20 min depending on N | $5-30 | Per-item structured output + roll-up summary |

Modes are not mutually exclusive — Wide can feed into Deep (use Wide to triage 100 papers → top 30 → run Deep on the question they raise).

## Why three not four

Considered also a **systematic-review** mode (PRISMA-strict). Already exists as `systematic-review` skill, separate workflow. Modes are for `/deep-research`-equivalent commands; systematic-review remains its own skill.

Considered **interview** mode (single human interlocutor, dialectical). Belongs to a separate skill family — not search/synthesis, just conversation. Skip.

---

## Wide Research — design

### Architecture: Orchestrator-Worker fan-out

```
User Query (typed: "process N items")
    │
    ▼
┌─────────────────────────────────────────────┐
│         WIDE-RESEARCH ORCHESTRATOR          │
│  (Plan 1 reads → emits N TaskSpecs)         │
└──────────┬──────────────────────────────────┘
           │  HITL Gate 1: approve decomposition
           │
           │  Fan-Out (parallel async)
   ┌───────┼───────┐
   ▼       ▼       ▼
[Sub-1] [Sub-2] [Sub-N]
   │       │       │     Each: fresh context + filesystem-as-memory + tools
   │       │       │     Single TaskSpec per sub-agent
   │       │       │     Outputs structured JSON to artifact
   └───────┴───────┘
           │
           │  HITL Gate 2 (optional): mid-research preview
           │
           │  Fan-In (collect file refs + summaries, not raw content)
           ▼
┌─────────────────────────────────────────────┐
│              SYNTHESIZER                    │
│  (fresh context — only summaries, not raw)  │
│  Roll-up → markdown report + structured CSV │
└─────────────────────────────────────────────┘
           │
           │  HITL Gate 3 (optional): re-run flagged items
           ▼
       OUTPUT
```

### State machines

**Orchestrator**:
```
RECEIVED_QUERY → DECOMPOSING → AWAITING_HUMAN_APPROVAL (Gate 1)
              → DELEGATING (spawn N sub-agents asyncio.gather)
              → COLLECTING → AWAITING_MID_REVIEW (Gate 2 optional)
              → SYNTHESIZING_READY → AWAITING_FINAL_CHECK (Gate 3)
              → SYNTHESIZING → OUTPUT_READY
```

**Sub-agent** (one per item):
```
INITIALIZED → PLANNING (parse TaskSpec, select tools)
           → EXECUTING ──→ TOOL_RESULT → refine → EXECUTING
                       ──→ ERROR_RECOVERY (failure stays in context)
                       ──→ COMPLETE (write artifact to filesystem)
           → REPORTING (lightweight reference + summary back to orchestrator)
```

### Context engineering principles (Manus/Anthropic-derived)

| Principle | Coscientist implementation |
|---|---|
| KV-cache stability | Stable system-prompt prefix per persona. NO timestamps inside prompts. Append-only context within sub-agent. Deterministic JSON serialization (sorted keys) for tool args |
| Tool masking, not removal | All tools defined upfront; mask via state machine logits (Claude Code's tool-restriction frontmatter is the equivalent) |
| Filesystem-as-memory | Each sub-agent writes intermediate findings to `~/.cache/coscientist/runs/run-<id>/wide/<sub-id>/` (extends existing inputs/ pattern). Context holds only file paths + brief summaries |
| Error retention | Tool errors stay in sub-agent context — never wiped. Sub-agent can adapt strategy on next call |
| Attention recitation | Per sub-agent: rewrite `task_progress.md` at end of context every step. Pushes objective into recency window |
| Few-shot diversity | Vary phrasing of tool-call serialization slightly across iterations to avoid pattern collapse |
| Anti-drift | Dedicated planner-executor split: orchestrator decomposes, sub-agents execute. ~33% action waste avoided per Manus blog post |

### Token economics

| Metric | Value | Source |
|---|---|---|
| Token multiplier vs single-agent | ~15× | [Anthropic engineering blog](https://www.anthropic.com/engineering/built-multi-agent-research-system) |
| Cache hit rate target | >70% | Manus reports KV-cache as #1 production metric |
| Input:output token ratio | ~100:1 in agent loops | Manus blog |
| Cached vs uncached cost | 10× difference (Claude Sonnet) | Anthropic pricing |
| Practical sub-agent count | 1 (simple) → 250 (Wide max) | Anthropic + Manus practitioner reports |

**Wide threshold**: >10 items justifies fan-out. Below that, single deep-research wins on cost.

### Sub-agent count selection

```
items < 10:       single sub-agent (= Quick or Deep mode)
items 10-30:      one sub-agent per item, all parallel
items 30-100:     one sub-agent per item; concurrency cap ~30 to respect MCP rate limits
items 100-250:    chunked — N sub-agents each handling 1-3 items; cap at 30 concurrent
items > 250:      reject; user should use systematic-review skill instead
```

### TaskSpec schema (per sub-agent input)

```json
{
  "sub_agent_id": "wide-<run_id>-<item_index>",
  "objective": "Specific bounded task — not 'research X' but 'find founding year, headcount, last funding round of Company X'",
  "input_item": {...},
  "output_schema": {
    "fields": ["...", "..."],
    "format": "json|markdown|csv-row"
  },
  "tools_allowed": ["paper-discovery", "consensus-search", "..."],
  "tools_forbidden": ["paper-acquire"],
  "scope_exclusions": "Other sub-agents are covering X, Y, Z — don't duplicate",
  "max_tool_calls": 15,
  "max_tokens_budget": 50000,
  "filesystem_workspace": "~/.cache/coscientist/runs/run-<id>/wide/<sub-id>/"
}
```

### HITL gates

**Gate 1 (Post-decomposition)** — required:
- Orchestrator emits N TaskSpecs as table
- User: approve / edit / cancel
- Catches scope misalignment **before** $5-30 of compute is spent

**Gate 2 (Mid-research preview)** — optional, fires when ≥30 sub-agents:
- After 30% of sub-agents complete: surface preview
- "20/50 done. Here's the structure. Continue / adjust scope?"
- Catches systematic errors (wrong source, wrong field interpretation)

**Gate 3 (Pre-synthesis)** — optional:
- "All sub-agents done. Flag items needing re-run."
- User marks IDs for re-research with additional guidance

Rule: humans **gate**, do not **execute**. LLM generates options; human approves/rejects/steers.

### Failure modes (production lessons)

| Failure | Mitigation |
|---|---|
| Vague delegation → sub-agents duplicate work | TaskSpec must include `scope_exclusions` listing other sub-agents' coverage |
| Context pollution between sub-agents | Sub-agents do NOT communicate; all coordination via orchestrator |
| Sub-agent context bloat from raw web pages | Filesystem-as-memory: write to file, keep only path in context |
| Synthesizer overwhelmed by raw research | Sub-agents return file refs + structured summaries, NOT raw content |
| Token cost runaway (15× multiplier × N items) | Per-sub-agent `max_tokens_budget` cap. Orchestrator-level total ceiling |
| Lost-in-the-middle on long sub-agent runs | task_progress.md recitation at end of context every step |
| Cache invalidation from per-call timestamps | Strict no-timestamps rule in system prompts |
| Schema hallucination from removing tools mid-run | All tools defined upfront, masked via state machine |

---

## Wide Research — Coscientist-specific use cases

| Scenario | N items | TaskSpec objective |
|---|---|---|
| Triage 100 candidate papers | 100 | "Read abstract; classify (relevant/irrelevant); extract method/year/citation_count" |
| Survey 50 BFT protocols | 50 | "Find paper for protocol X; extract message complexity, fault model, throughput claim" |
| Per-author publication map | 30 authors | "List author X's last 10 papers in subfield Y; extract h-index, recent venues" |
| Cross-project lit comparison | 20 projects | "For project X, summarize stated research question + top 3 cited papers" |
| Per-paper full-text extraction | 30 papers | "Acquire PDF; run pdf-extract; emit structured claims + figures" |
| Cross-venue paper-by-paper screening (PRISMA-like) | 200 | "Read abstract; apply inclusion-criteria; emit include/exclude with reason" |

Notably: **Wide complements Deep**. Run Wide to triage 100 → 30 → feed those 30 to Deep as scout's seed.

---

## Implementation phasing

### v0.53.1 — Decomposition + single sub-agent (POC)
- `lib/wide_research.py` — TaskSpec dataclass, orchestrator-decompose() heuristic + LLM
- `db.py wide-decompose --run-id <id>` returns N TaskSpecs as JSON
- `db.py wide-set-decomposition` locks user-confirmed list
- One sub-agent invoked synchronously, validate full state machine

### v0.53.2 — Fan-out 3-5 sub-agents
- `asyncio.gather()` parallel dispatch in orchestrator
- Verify no context contamination
- HITL Gate 1 wired

### v0.53.3 — Scale + observability
- Concurrency cap (default 30)
- Per-run total token budget enforcement
- Tracing: which sub-agent, which tools, where coordination broke
- HITL Gate 2 + Gate 3

### v0.53.4 — Synthesis quality
- Dedicated synthesizer with fresh context (file refs only, not raw)
- Citation roll-up
- Per-mode templates: paper-screening, author-survey, protocol-comparison

### v0.53.5 — Mode-selector at /deep-research entry
- Auto-detect Quick vs Deep vs Wide from prompt shape
- "Process these 50 papers" → Wide
- "What is X" → Quick
- "Sharpen my research question on Y" → Deep
- User can override with `--mode quick|deep|wide`

---

## Open questions

1. **Sub-agent runtime**: Claude Code's `Task` tool with `subagent_type` already gives parallel async dispatch. Sufficient for v0.53.1-v0.53.3. For v0.53.4+, may want Docker-isolated sub-agents per Manus pattern (isolation + reproducibility).

2. **Synthesizer model choice**: Frontier model for orchestrator + synthesizer (Opus); cheap model for sub-agents (Sonnet/Haiku). Per Anthropic 2-tier split. Currently we run Sonnet 4.7 throughout.

3. **Filesystem-as-memory schema**: Existing `~/.cache/coscientist/runs/run-<id>/inputs/` is for harvest shortlists. Wide adds `wide/<sub-id>/` per sub-agent. Compatible.

4. **Mode interaction**: Wide → Deep handoff design. Wide outputs structured CSV per item; Deep's scout consumes top-K rows as seed. TaskSpec schema must align.

5. **Cost transparency**: Display estimated $ before user approves Gate 1. Block if >$50 unless `--allow-expensive`.

---

## References

- [Manus: Context Engineering for AI Agents](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)
- [Anthropic: How we built our multi-agent research system](https://www.anthropic.com/engineering/built-multi-agent-research-system)
- [Six Context Engineering Techniques That Make Manus Work in Production](https://tianpan.co/blog/2026-03-02-context-engineering-lessons-from-manus)
- [Token Economics for AI Agents](https://tianpan.co/blog/2026-02-09-token-economics-ai-agents-cost-optimization)
- [The Four Sub-Agent Orchestration Patterns That Cover 90% of Production Claude Workloads](https://readysolutions.ai/blog/2026-04-18-sub-agent-orchestration-patterns-claude/)
