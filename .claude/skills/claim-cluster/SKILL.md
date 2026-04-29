---
name: claim-cluster
description: Read-only Jaccard clustering of claims across project papers — surfaces shared findings, outlier claims, claim-density heat. Pure stdlib heuristic.
when_to_use: Asking "which papers in my project assert the same finding?" or "what's the consensus claim in this set?"
---

# claim-cluster

Read-only — no LLM, no writes. Walks every paper artifact registered
in a project's `artifact_index` (kind=paper), reads
`metadata.json:claims[].text`, tokenizes each paper's claim bag (lower
case, drop short tokens + stop-words), and clusters by all-pairs
token-Jaccard ≥ threshold using single-link union-find.

Per cluster: papers, top-K most-common content tokens (heat), and
the longest claim as a representative.

Hard cap at 200 papers — all-pairs Jaccard is O(n²); larger projects
should pass a representative subset (`--top-n` won't help; the cap is
on input).

## How to invoke

```bash
uv run python .claude/skills/claim-cluster/scripts/cluster_claims.py \
  --project-id <pid> \
  [--min-jaccard 0.4] [--min-cluster-size 2] \
  [--top-n 50] [--format json|text]
```

## What "done" looks like

- `{clusters: [...], outliers: [cid, ...]}` JSON or human text.
- Empty project → clean `{clusters: [], outliers: []}`.
- >200 papers → `{error: "..."}`, exit 0.
- Missing metadata.json on a paper → that paper is skipped silently.

## What this skill does NOT do

- Does not embed, doesn't call any LLM.
- Does not write the project DB or any artifact files.
- Does not infer semantic equivalence beyond bag-of-tokens Jaccard.
- Does not fetch new papers or expand the graph.
