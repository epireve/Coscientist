---
name: resolve-citation
description: Resolve an incomplete citation reference (e.g. "Smith 2020", "Vaswani et al., 2017 — Attention", or just keywords + year) to a canonical Coscientist paper artifact via Semantic Scholar. Pure heuristic match; no PDFs are fetched.
when_to_use: A user, manuscript, or journal entry mentions a paper informally and you need a `canonical_id` + DOI for it. Distinct from `paper-discovery` (broad multi-MCP search) — this is a one-shot disambiguator for a known-but-incomplete reference.
---

# resolve-citation

Single job: turn an informal reference into a canonical paper.

Two phases:

1. **Parse** the partial reference into structured fields (authors, year, title tokens, venue hint).
2. **Match** it against Semantic Scholar candidates the orchestrator harvested for you, returning the best scoring match (or nothing, if no candidate scores ≥ 0.5).

The match step never calls an MCP. The orchestrator (parent agent) is responsible for harvesting; this skill is the deterministic scorer.

## How to use this skill (agent-facing)

### Step 1 — parse only

Get the structured partial so you know what S2 query to fire:

```bash
uv run python .claude/skills/resolve-citation/scripts/resolve.py \
  --text "Vaswani et al., 2017 — Attention is all you need" \
  --interactive
```

Output (stdout, JSON):

```json
{
  "raw": "Vaswani et al., 2017 — Attention is all you need",
  "authors": ["vaswani"],
  "year": 2017,
  "title_tokens": ["all", "attention", "need"],
  "venue_hint": null
}
```

### Step 2 — harvest S2 candidates

Use the parsed fields to drive a focused Semantic Scholar query. Prefer `mcp__semantic-scholar__search_papers_match` (designed exactly for this) when the partial includes enough signal; fall back to `mcp__semantic-scholar__search_papers` with `query=<author lastname> <title fragment> <year>` otherwise.

Dump the result list to a JSON file. Expected shape (flat list, only fields that matter):

```json
[
  {
    "title": "Attention is all you need",
    "authors": ["Ashish Vaswani", "Noam Shazeer", "..."],
    "year": 2017,
    "doi": "10.48550/arXiv.1706.03762",
    "venue": "NeurIPS",
    "s2_id": "204e3073..."
  },
  ...
]
```

### Step 3 — pick best

```bash
uv run python .claude/skills/resolve-citation/scripts/resolve.py \
  --text "Vaswani et al., 2017 — Attention is all you need" \
  --candidates /tmp/s2-candidates.json
```

Output (JSON to stdout):

```json
{
  "matched": true,
  "score": 0.92,
  "canonical_id": "vaswani_2017_attention-is-all-you-need_a1b2c3",
  "doi": "10.48550/arXiv.1706.03762",
  "title": "Attention is all you need",
  "year": 2017,
  "candidate": { ... full candidate dict ... },
  "partial": { ... parsed partial ... }
}
```

If no candidate scores ≥ 0.5:

```json
{ "matched": false, "score": 0.0, "partial": { ... }, "best_below_threshold": { ... } }
```

## Scoring

Pure stdlib, deterministic. Components:

- **Author lastname overlap** — 45% weight — fraction of the partial's lastnames that appear in the candidate's author list.
- **Year exact match** — 25% weight — strict equality.
- **Title token Jaccard** — 30% weight — Jaccard over normalized tokens (lowercased, stopworded, length ≥ 3).

Threshold for acceptance: **0.5**. Below that, the script reports `matched: false` and returns the best-below-threshold candidate for the orchestrator to consider manually.

## What this skill does NOT do

- No MCP calls of its own. Orchestrator harvests, hands script the JSON.
- No PDF fetching. `paper-acquire` does that, with the triage gate.
- No artifact stub creation. Use `paper-discovery`'s merge step or call `lib.paper_artifact.canonical_id()` directly if you need to materialize the resolved paper.
- DB persistence (v0.63): `--persist-db` writes the outcome (matched + score + canonical_id, or below-threshold + best candidate) to the `citation_resolutions` table. Requires one of `--db-path`, `--run-id`, or `--project-id` to locate the SQLite DB. Migration v10 creates the table on first call. Both matched and below-threshold attempts are recorded so you can later audit "what couldn't I resolve".

## Examples

```bash
# Just keywords and a year
uv run python .claude/skills/resolve-citation/scripts/resolve.py \
  --text "transformer attention all you need 2017" --interactive

# Multi-author with em-dash title
uv run python .claude/skills/resolve-citation/scripts/resolve.py \
  --text "He, Zhang, Ren, Sun (2016) — Deep Residual Learning" --interactive

# Score against pre-harvested candidates
uv run python .claude/skills/resolve-citation/scripts/resolve.py \
  --text "Smith 2020 X" --candidates /tmp/empty.json
```

## Exit test

The skill is done when:

- The partial parses into a `PartialCitation` with at least one of `{authors, year, title_tokens}` populated.
- If candidates are supplied: either a match ≥ 0.5 is reported with `canonical_id` + DOI, or the script clearly reports `matched: false`.
- The orchestrator can take the `canonical_id` straight to `paper-discovery` / `paper-triage` / the project graph.

## CLI flag reference (drift coverage)

- `resolve.py`: `--threshold`
