---
name: reference-agent
description: Bidirectional bridge between Coscientist's paper cache and Zotero + citation-graph operations. Sync Zotero items into paper artifacts, export BibTeX for a manuscript or run, track reading state per paper per project, flag retractions. Cashes in on the graph layer from v0.3.
when_to_use: You need to sync Zotero; export citations for a manuscript; know which papers you've read; or check whether any cited paper has been retracted.
---

# reference-agent

Small, focused skill with six jobs, each one mechanical script:

| Job | Script |
|---|---|
| Sync from Zotero → paper artifacts + graph | `scripts/sync_from_zotero.py` |
| Export BibTeX for a manuscript or run | `scripts/export_bibtex.py` |
| Get / set reading state per paper per project | `scripts/reading_state.py` |
| Record retraction flags (from Semantic Scholar or manual) | `scripts/mark_retracted.py` |
| Populate citation edges (cites / cited-by) from Semantic Scholar | `scripts/populate_citations.py` |
| Populate concept edges (about) from run-log claims | `scripts/populate_concepts.py` |

No Zotero HTTP calls live in these scripts — that's the `zotero` MCP's job. The scripts consume structured JSON that the calling agent has already fetched via the MCP.

## sync-from-zotero

**Flow**: Agent calls `mcp__zotero__zotero_search_items` and/or `mcp__zotero__zotero_item_metadata`, dumps results to a JSON file, pipes to the script.

```bash
uv run python .claude/skills/reference-agent/scripts/sync_from_zotero.py \
  --input /tmp/zotero-items.json \
  --project-id <pid>
```

Expected JSON shape (flat list of items):

```json
[
  {
    "zotero_key": "ABC123",
    "zotero_library": "user:123456",
    "title": "Attention is all you need",
    "authors": ["Vaswani, A.", "Shazeer, N.", ...],
    "year": 2017,
    "doi": "10.48550/arXiv.1706.03762",
    "abstract": "...",
    "venue": "NeurIPS",
    "tags": ["transformers", "attention"]
  },
  ...
]
```

For each item:
1. Derive `canonical_id` from title + authors + year + DOI
2. Create/update the paper artifact (manifest + metadata)
3. Insert a row into `zotero_links` so future sync doesn't duplicate
4. Add a `graph_nodes` entry for `paper:<cid>` in the project
5. For each author, add a `graph_nodes` entry + `authored-by` edge
6. Register the artifact in `artifact_index`
7. Default reading state = `to-read` unless already set

## export-bibtex

```bash
# For a manuscript — exports every paper in cited_sources across manuscript_claims
uv run python .claude/skills/reference-agent/scripts/export_bibtex.py \
  --manuscript-id <mid> \
  --out /tmp/refs.bib

# For a deep-research run — exports papers_in_run
uv run python .claude/skills/reference-agent/scripts/export_bibtex.py \
  --run-id <rid> \
  --out /tmp/refs.bib
```

Writes valid BibTeX with `@article` or `@misc` entries keyed by `canonical_id`. Includes DOI when present, `note` field with canonical_id for round-trip traceability.

## reading-state

```bash
# Set
uv run python .claude/skills/reference-agent/scripts/reading_state.py \
  --canonical-id <cid> \
  --project-id <pid> \
  --state to-read|reading|read|annotated|cited|skipped \
  [--notes "..."]

# Get (prints current state or 'unknown')
uv run python .claude/skills/reference-agent/scripts/reading_state.py \
  --canonical-id <cid> --project-id <pid> --get

# List (filter by state or project)
uv run python .claude/skills/reference-agent/scripts/reading_state.py \
  --project-id <pid> --list-by-state to-read
```

State is per-project: a paper in two projects can have two different reading states.

## mark-retracted

For each paper you've cited, the sub-agent queries `mcp__semantic-scholar__get_paper` with field `isRetracted`. Batch-pipe results through:

```bash
uv run python .claude/skills/reference-agent/scripts/mark_retracted.py \
  --input /tmp/retractions.json \
  --project-id <pid>
```

Input shape:

```json
[
  {"canonical_id": "...", "retracted": true, "source": "semantic-scholar", "detail": "..."},
  ...
]
```

The script populates `retraction_flags`. `manuscript-audit` reads from this table when checking citations.

## populate-citations

Populate `cites` + `cited-by` edges in the project graph from Semantic Scholar references/citations.

Flow: agent calls `mcp__semantic-scholar__get_paper_references` and `get_paper_citations` for each paper of interest, packages the results as a flat list, pipes to the script.

```bash
uv run python .claude/skills/reference-agent/scripts/populate_citations.py \
  --input /tmp/citation-records.json \
  --project-id <pid>
```

Input shape:

```json
[
  {
    "from_canonical_id": "vaswani_2017_attention_abc123",
    "references": [{"canonical_id": "...", "title": "...", "year": 2014, "doi": "..."}],
    "citations": [{"canonical_id": "...", "title": "...", "year": 2019}]
  }
]
```

Idempotent: re-running doesn't duplicate edges. Creates paper nodes on demand for referenced papers that aren't yet in the project.

## populate-concepts

Promote run-log claims into the project graph. For every row in a run's `claims` table, creates a `concept` node and `about` edges from it to each supporting paper.

```bash
uv run python .claude/skills/reference-agent/scripts/populate_concepts.py \
  --run-id <run_id> \
  --project-id <pid>
```

Scans the run DB directly — no MCP calls, no input JSON needed. Makes `graph.hubs(project_id, kind='paper', relation='about')` return the papers most attached to findings/tensions/hypotheses in the run, which is the actual "key papers in this research question" view.

## Sub-agent

Persona file: `.claude/agents/reference-agent.md`. The agent wraps these scripts with sensible orchestration: "sync my Zotero library, then flag retractions across the last-year's cited papers, then show me what's still to-read."

## Principles this enforces

- Every artifact-state mutation goes through scripts (not direct DB writes)
- Zotero stays the source of truth for manual reading — the agent pulls, it doesn't push blindly
- No speculative fetches — only items the Zotero MCP already returned
