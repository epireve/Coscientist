---
name: paper-discovery
description: Search for academic papers across Consensus, paper-search MCP, academic MCP, Semantic Scholar, and OpenAlex (v0.145). Deduplicate results, write artifact stubs, and return a ranked shortlist. First step of any research task.
when_to_use: Starting a new research thread, or explicitly asked to "find papers on X". Not for fetching PDFs — that's `paper-acquire`. Not for reading — that's `arxiv-to-markdown` or `pdf-extract`.
---

# paper-discovery

Orchestrates the five discovery sources in parallel, merges results on DOI/arXiv-ID/OpenAlex-ID/normalized-title, and writes a stub artifact per paper. Output is a ranked shortlist; no PDFs are fetched.

## Known caveats

**arxiv backend date-bias** (v0.189): `mcp__paper-search__search_arxiv` returns
date-sorted results, NOT relevance-sorted. Open-ended topical queries get
recent-but-irrelevant papers. Use OpenAlex or Consensus for relevance-sensitive
discovery; reserve `paper-search` arxiv for **exact arXiv-ID lookups** (pattern
`\d{4}\.\d{4,5}`) or recency-sorted needs (latest preprints in domain). The
`lib.source_selector` demote rule (v0.189) auto-handles this — leave routing to
the helper unless you have a specific reason to override.

## Source selection heuristics

Always run Consensus first — its claim-extraction is the best input for `paper-triage`. Then run others in parallel. Use all five unless the query strongly matches one domain:

| Domain | Primary sources |
|---|---|
| Biomed / clinical | `paper-search` (PubMed, PMC, Europe PMC) + `consensus` + `openalex` |
| CS / ML / physics / math | `paper-search` (arXiv) + `semantic-scholar` + `openalex` + `consensus` |
| Crypto | `paper-search` (IACR) + `semantic-scholar` + `openalex` |
| Engineering | `academic` (IEEE, Springer, ScienceDirect) + `consensus` + `openalex` |
| Humanities / philosophy | `consensus` + `academic` + `openalex` |
| Broad / cross-disciplinary | all five |
| OA-only / quick / preprint-heavy | `openalex` (10 req/s polite-pool, free) |

**OpenAlex** (v0.145, via `lib.openalex_client` — not an MCP) gives:
- 250M works, ORCID-linked authors, ROR institutions
- Pre-scored topic tags (saves manual concept inference)
- OA URL directly in metadata (eliminates one fallback hop in `paper-acquire`)
- 10 req/s polite-pool (free with `OPENALEX_MAILTO`), 100 req/s with `OPENALEX_API_KEY`
- Invoke via:
  ```bash
  uv run python .claude/skills/paper-discovery/scripts/openalex_source.py \
    --query "your query" --per-page 25 --out /tmp/openalex.json
  ```
- Then concat with other source outputs and pipe to `merge.py`.

## How to use this skill (agent-facing instructions)

You (the calling Claude agent) drive the MCPs directly. This skill gives you the playbook. Mechanical bits (dedup, artifact stubs, ranking) are done by the helper script.

**Procedure:**

1. Reformulate the user's question into 2–4 focused queries (different angles, not paraphrases). Record them.
2. Call each selected MCP's search tool with each query. Expect 10–25 results per call.
3. Collect every result's title, authors, year, abstract, DOI, arxiv_id, venue, source into a JSON list.
4. Pass the combined list to the helper:

```bash
uv run python .claude/skills/paper-discovery/scripts/merge.py \
  --input /tmp/discovery-raw.json \
  --query "<original research question>" \
  [--run-id <run_id>] \
  --out /tmp/discovery-ranked.json
```

5. Return the ranked shortlist to the caller (and, if `--run-id` is set, rows are inserted into `papers_in_run`).

## Dedup rules

Papers are merged in this priority order:

1. Same DOI → same paper
2. Same arXiv ID → same paper
3. Same normalized title (lowercased, non-alphanumeric stripped, author last-name suffix) → same paper

Merged papers combine `discovered_via` sources (e.g. `["consensus", "semantic-scholar"]`).

## Ranking signal

Default: papers appearing in multiple sources rank higher; ties broken by `citation_count` then recency. Not a semantic relevance score — that's the triage step's job.

## Outputs

For every unique paper:

- `~/.cache/coscientist/papers/<canonical_id>/manifest.json` — `state=discovered`, IDs populated
- `~/.cache/coscientist/papers/<canonical_id>/metadata.json` — title, authors, abstract, tldr, claims, `discovered_via`
- No `content.md` yet — that comes after triage + acquire + extract

Plus a caller-consumable ranked list at `--out`.

## What this skill does NOT do

- Does not download PDFs (→ `paper-acquire`)
- Does not decide what to read in full (→ `paper-triage`)
- Does not synthesize findings (→ `deep-research` sub-agents)

## CLI flag reference (drift coverage)

- `openalex_source.py`: `--filter`, `--page`
