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

## Wide TaskSpec types

Single Wide mode, multiple TaskSpec types. User specifies `--type` or auto-detected from prompt.

| Type | Sub-agent objective | Tools | Output schema |
|---|---|---|---|
| `triage` | Read abstract → relevance score → include/review/exclude | paper-discovery, MCP search | `{cid, score, recommend, reason}` |
| `read` | Acquire PDF → pdf-extract → structured per-paper data | paper-triage, paper-acquire, pdf-extract | `{method, dataset, results, limitations, claims, figures}` |
| `rank` | Pairwise compare items → Elo | tournament/record_match | Updated Elo per item |
| `compare` | Per-item feature extraction across fixed schema | paper read tools | `{feature_a, feature_b, ...}` per item |
| `survey` | Per-author publication trajectory | semantic-scholar author tools | `{author, h_index, recent_venues, top_papers}` |
| `screen` | PRISMA-style include/exclude per criterion | paper-triage | `{include: bool, criteria_failed: [...]}` |

`triage` is POC type — minimum viable surface. `read` is primary value-add (closes QUALITY-AUDIT 0% DOI gap).

## Wide → Deep handoff (cleverly)

**Goal**: Wide's structured output flows into Deep's scout phase without re-doing harvest. Closes the audit's thin-corpus + 0% DOI gaps simultaneously.

### Three handoff levels

**Level 1: Seed handoff** — Wide-`triage` output → Deep scout
```
wide-run-<W>: triage 100 → CSV with relevance_score, recommend
  ↓ user picks top-K via Gate 3
  ↓
deep-run-<D>: db.py init --question "..." --seed-from-wide <W> --seed-top-k 30
  ↓
Scout phase reads wide-run-<W>'s `recommend=include` rows, writes to
  ~/.cache/coscientist/runs/run-<D>/inputs/scout-phase0.json
  ↓ MCP harvest skipped — papers already triaged
  ↓
Cartographer/chronicler/surveyor proceed with vetted seed corpus
```

**Level 2: Full-text handoff** — Wide-`read` output → Deep with extracted PDFs
```
wide-run-<W>: read 30 → per-paper {method, dataset, results, ...}
  ↓ Each sub-agent runs paper-acquire + pdf-extract → fills paper artifact's
    content.md, figures/, tables/, references.json
  ↓
deep-run-<D>: db.py init --question "..." --seed-from-wide <W> --seed-mode full-text
  ↓
Cartographer reads references.json (NOW POPULATED) — mechanical seminal detection
  via citation in-degree, not heuristic abstract-only inference
  ↓
Synthesist + Architect operate on full-text claims, not abstract speculation
  ↓
Brief cites verified quantitative claims (HotStuff "-45% latency vs PBFT" now
  grounded in extracted paper, not extrapolated)
```

**Level 3: Cumulative corpus** — Wide → Deep → Wide (refinement loop)
```
deep-run-<D> identifies 6 gaps + 3 hypotheses
  ↓ User wants to operationalize hyp-th-001 (consistency-tier router)
  ↓
wide-run-<W2>: compare 50 protocols, taskspec extracts {commutativity, ops_per_sec, ...}
  ↓ wide pulls in protocols Deep didn't surface
  ↓
deep-run-<D2>: --seed-from-wide <W2> --priors-from-deep <D>
  ↓ Combines D's hypothesis space with W2's empirical data
```

### Handoff mechanism (concrete)

**Database side** — extend `runs` table with provenance:
```sql
ALTER TABLE runs ADD COLUMN parent_run_id TEXT;
ALTER TABLE runs ADD COLUMN seed_mode TEXT;  -- 'cold' | 'wide-triage' | 'wide-read' | 'wide-compare'
```

**CLI side** — extend `db.py init`:
```bash
db.py init --question "..." \
  [--seed-from-wide <run_id>] \           # parent Wide run
  [--seed-top-k 30] \                     # how many items from Wide to seed Deep
  [--seed-filter "recommend=include"] \   # SQL-like filter on Wide's CSV
  [--seed-mode full-text|abstract]        # use Wide-read content.md or just metadata
```

**Scout integration** — when `--seed-from-wide` set, scout's harvest is replaced by:
```python
def harvest_from_wide(parent_run_id: str, top_k: int, filter_expr: str, mode: str):
    parent_db = run_db_path(parent_run_id)
    # Query parent's papers_in_run + Wide CSV output, apply filter, take top-K
    # Write to current run's inputs/scout-phase0.json
    # If mode=='full-text', verify each paper has content.md populated
    # (paper artifact extracted by Wide-read sub-agents)
```

### Wide CSV → papers_in_run schema alignment

Wide TaskSpec `output_schema` must produce rows mappable to `papers_in_run`:
```json
{"canonical_id": "...",                   // matches papers_in_run PK
 "title": "...",
 "year": 2024,
 "relevance_score": 0.87,                  // Wide-triage output
 "recommend": "include|review|exclude",
 "reason": "...",
 "harvest_count_proxy": 1,                 // for harvest_count column
 "extraction_status": "abstract|full-text" // tells Deep which mode possible
}
```

Wide writes this to `runs/run-<W>/wide/output.csv` + a parallel JSON. Scout-handoff reads JSON.

### Why this is clever (not just glue)

1. **Wide-read seed mode unlocks Cartographer's mechanical seminal detection** — currently cartographer infers seminals from abstract patterns; with full-text references.json populated, it computes citation in-degree directly.
2. **Synthesist stops speculating** — i7-class implications ("1999 adversary predates wireless side-channels") become grounded if Wide-read extracted any paper that explicitly addresses post-2020 threat models.
3. **Audit Log gets richer** — papers_cited becomes a tracked subset of papers_extracted, not just papers_seeded. Provenance chain: Wide harvest → Wide-read extraction → Deep cartographer → Steward citation.
4. **Cost discipline** — Wide-triage at $5-15 prunes corpus before paying $30+ Wide-read across only top-30. Deep on filtered + extracted corpus produces research-citable output for ~$50 total vs $5 cold-start brief that's not citable.

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

### v0.53.4 — Synthesis quality + Wide TaskSpec types
- Dedicated synthesizer with fresh context (file refs only, not raw)
- Citation roll-up
- Per-mode templates: paper-screening, author-survey, protocol-comparison
- TaskSpec types: `triage` (POC done in .1-.3), `read`, `rank`, `compare`, `survey`, `screen`

### v0.53.5 — Wide → Deep handoff + mode-selector
- `db.py init --seed-from-wide <run_id> --seed-top-k N --seed-mode full-text|abstract`
- Migration adds `runs.parent_run_id` + `runs.seed_mode`
- Scout phase short-circuit when `seed-from-wide` set — read parent's filtered CSV
- Wide-read sub-agents populate paper artifacts (content.md, references.json) so Deep's cartographer can compute citation in-degree mechanically
- Auto-detect Quick vs Deep vs Wide from prompt shape; user override with `--mode`

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
