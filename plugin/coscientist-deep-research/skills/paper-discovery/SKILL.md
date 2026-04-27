---
name: paper-discovery
description: Search for academic papers across Consensus, paper-search MCP, academic MCP, and Semantic Scholar. Deduplicate results, write artifact stubs, and return a ranked shortlist. First step of any research task.
when_to_use: Starting a new research thread, or explicitly asked to "find papers on X". Not for fetching PDFs — that's `paper-acquire`. Not for reading — that's `arxiv-to-markdown` or `pdf-extract`.
---

# paper-discovery

Orchestrates the four discovery MCPs in parallel, merges results on DOI/arXiv-ID/normalized-title, and writes a stub artifact per paper. Output is a ranked shortlist; no PDFs are fetched.

## Source selection heuristics

Always run Consensus first — its claim-extraction is the best input for `paper-triage`. Then run others in parallel. Use all four unless the query strongly matches one domain:

| Domain | Primary MCPs |
|---|---|
| Biomed / clinical | `paper-search` (PubMed, PMC, Europe PMC) + `consensus` |
| CS / ML / physics / math | `paper-search` (arXiv) + `semantic-scholar` + `consensus` |
| Crypto | `paper-search` (IACR) + `semantic-scholar` |
| Engineering | `academic` (IEEE, Springer, ScienceDirect) + `consensus` |
| Humanities / philosophy | `consensus` + `academic` |
| Broad / cross-disciplinary | all four |

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
