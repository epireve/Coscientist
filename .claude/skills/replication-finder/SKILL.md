---
name: replication-finder
description: Read-only heuristic that flags replications, contradictions, and follow-ups for a target paper using citation-context stems + claim Jaccard.
when_to_use: After a paper is in the project graph, ask "who tried to replicate this?" or "did anyone fail this?"
---

# replication-finder

Read-only heuristic — no LLM, no writes. Given a target paper's
canonical_id and a project, walks the project graph for papers that
cite the target, then scores each citer by:

1. **Citation-context stems** in the citer's claims/content:
   - `replicate` / `reproduce` / `confirm` → +1 replication
   - `fail to replicate` / `did not replicate` / `contradict` /
     `refute` → +1 refutation (overrides plain "replicate")
   - `extend` / `build on` / `follow-up` → +1 follow-up
2. **Claim Jaccard overlap** between target claims[].text tokens
   and citer claims[].text tokens. Overlap >0.4 boosts the
   matched signal (replicates / refutes).

Output: ranked JSON list of
`{cid, signal, score, reasons[]}` where signal ∈
`replicates | refutes | follow-up | weak`.

## How to invoke

```bash
uv run python .claude/skills/replication-finder/scripts/find_replications.py \
  --project-id <pid> --canonical-id <target_cid> \
  [--top-n 20] [--format json|text]
```

## What "done" looks like

- Returns ranked list (best signal first).
- Best-effort: missing metadata.json on a citer → skipped, never crashes.
- Errors return a dict with `error` key, exit 0 (read-only).

## What this skill does NOT do

- Does not fetch new papers.
- Does not write to the project DB or graph.
- Does not call any LLM — pure stem matching + Jaccard.
- Does not infer citation polarity beyond the stem table above.
