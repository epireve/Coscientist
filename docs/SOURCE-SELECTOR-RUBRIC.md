# Source Selector Rubric

Operator guide for `lib/source_selector.py` (v0.147) and the wired call sites (v0.159 — `populate_citations`, `populate_concepts`). Decides which paper-discovery source to call given research phase, mode, seed, and budget.

## The phase-driven model

Every paper-discovery call belongs to exactly one of four phases:

| Phase | What it does | Example |
|---|---|---|
| **discovery** | Find papers from question | First-pass search on novel question |
| **ingestion** | Pull refs/cites for known seed | Expand graph from a seed DOI |
| **enrichment** | Add TLDR, embeddings, influence | Backfill known papers with S2 metadata |
| **graph-walk** | Structural traversal of refs / cited_by | BFS hub detection, citation chasing |

Phase is the dominant signal. Mode and budget refine. Seed short-circuits.

## Rubric: phase × mode → source

| Phase | Mode | Has seed? | Budget | Primary | Fallbacks | Why |
|---|---|---|---|---|---|---|
| any | — | yes | — | openalex | s2, paper-search | Skip discovery entirely; graph-first |
| ingestion | — | — | — | openalex | s2 | Graph backbone — refs/cites/topics |
| graph-walk | — | — | — | openalex | s2 | Structural; refs + cited_by edges |
| enrichment | — | — | — | s2 | openalex | TLDR + embeddings + influentialCitationCount |
| discovery | quick | — | — | s2 | openalex | Cheap TLDR triage suffices |
| discovery | — | — | free | s2 | openalex | No paid API allowed |
| discovery | wide | — | — | openalex | s2 | Batch metadata, fan-out cheap |
| discovery | deep | — | paid (open Q) | consensus | s2, openalex | Best triage — claims + study quality |
| discovery | deep | — | paid (concrete) | openalex | s2 | Metadata sufficient — no triage premium |
| (fallback) | — | — | — | openalex | s2 | Safe default |

## Cost shape

Free vs paid sources:

- **OpenAlex** — free, no key required. 200M papers, refs+cites+OA URLs+topics+institutions+funders. Default workhorse.
- **Semantic Scholar (S2)** — free with API key. 200M+ papers, TLDR, embeddings, influentialCitationCount. Best for enrichment.
- **Consensus** — **paid**. Best for triage (claims + study quality + sample size). Use only when triage premium is worth it (deep + open question).
- **paper-search-mcp** — free. Fallback aggregator (arXiv/bioRxiv/medRxiv/PubMed). Used when primary source returns nothing.

Rule of thumb: spend Consensus credits only when triage signal materially changes the shortlist. Concrete questions ("what's the citation count for X?") don't benefit from claim extraction; metadata is enough.

## When seed is given vs unknown

Seed = DOI / arXiv ID / openalex_id supplied upfront.

- **Seed given** → `select_source(has_seed=True, ...)` → always **openalex**. No discovery needed; jump to graph traversal. This short-circuits the rest of the rubric.
- **No seed** → phase + mode + budget govern routing.

Wide → Deep handoff (v0.53) hands a 30-paper shortlist forward as seeds. Subsequent phases skip discovery entirely.

## Budget tier

- **`free`** — excludes Consensus (the only paid source today). Forces S2 / OpenAlex / paper-search-mcp.
- **`paid`** — full menu including Consensus. Default when running deep mode on user-funded keys.
- **`None`** — unspecified; treated as paid for ingestion/enrichment/graph-walk; treated as paid for deep+open-question discovery; treated as free for quick/wide.

Set via `--budget-tier free` on `lib.source_selector` CLI, or `budget_tier="free"` in the API call.

## How `--source auto` resolves

`populate_citations.py` and `populate_concepts.py` (v0.159) accept `--source auto` and delegate to `lib.source_selector.select_source`. Resolution path:

1. Caller derives phase from operation:
   - `populate_citations` → **ingestion** (loading refs/cites for a known paper)
   - `populate_concepts` → **enrichment** (adding S2 topic/concept metadata)
2. Caller passes `mode=None`, `has_seed=True` (always — caller already has the paper).
3. `select_source` returns SourceRecommendation.
4. Caller invokes `recommendation.primary`. On failure, walks `recommendation.fallbacks`.

Reference these scripts as canonical wiring examples:

```bash
.claude/skills/reference-agent/scripts/populate_citations.py
.claude/skills/reference-agent/scripts/populate_concepts.py
```

Both pass `phase=` literal + `has_seed=True` because the entry point is always a known paper.

## When to override

Override = pass an explicit `--source` instead of `--source auto`.

- **Concrete factual lookup** ("citation count of paper X") → `--source openalex`. Skip Consensus even on deep mode; saves credits.
- **Open-ended exploration** with budget for triage → `--source consensus`. Force Consensus even when rubric says S2 (e.g. quick mode where you actually want depth).
- **Comparing sources** for QA / debugging → run twice with explicit `--source openalex` and `--source s2`; diff results.
- **Source down / rate-limited** → manually pick the next fallback.

CLI invocation:

```bash
uv run python -m lib.source_selector \
  --phase discovery \
  --mode deep \
  --open-question \
  --json
# {"primary":"consensus","fallbacks":["s2","openalex"],"reasoning":"..."}
```

## See also

- `lib/source_selector.py` — implementation + 21 tests in `tests/test_source_selector.py`
- `.claude/skills/reference-agent/scripts/populate_citations.py` — ingestion call site
- `.claude/skills/reference-agent/scripts/populate_concepts.py` — enrichment call site
- `docs/IDEA-TREE-USAGE.md` — sibling operator guide for the tournament workflow
