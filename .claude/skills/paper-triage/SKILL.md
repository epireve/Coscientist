---
name: paper-triage
description: For each discovered paper, decide whether the abstract/TLDR/Consensus-snippets are enough, or whether the full text is needed. LLM-judgment per paper. Gates `paper-acquire` — no PDF may be fetched without a "needs full text" verdict here.
when_to_use: After `paper-discovery` has written metadata stubs. Before `paper-acquire`. The gate is mandatory — do not skip.
---

# paper-triage

For each paper in the shortlist, read its metadata artifact and decide:

- **`sufficient: true`** — the abstract + TLDR + Consensus claim snippets already answer the research question (or the role this paper plays in it). No need for full text.
- **`sufficient: false`** — we need the full text (figures, methods, specific numbers, citations). Permission granted to `paper-acquire` to fetch.

The decision + rationale is written back to `manifest.json["triage"]` and the paper's state advances to `triaged`.

## Inputs

- `canonical_id` list (or `run_id` to process every paper in that run)
- Research question (the triage criterion)

## Agent-facing procedure

You (the calling agent) make the judgment. This skill's script enforces the gate and records your verdict.

For each paper:

1. Read `metadata.json` (title, abstract, tldr, claims, venue, year).
2. Compare to the research question. Ask yourself:
   - Does the abstract already answer it, or am I guessing at details?
   - Do the claims (if from Consensus) cover the specific angle I care about?
   - Would figures/methods change my interpretation?
   - Is this a seminal paper where I really need to read the argument, not just the conclusion?
3. Produce a verdict: `sufficient: true|false`, `rationale: "..."` (1–3 sentences).
4. Record:

```bash
uv run python .claude/skills/paper-triage/scripts/record.py \
  --canonical-id <cid> \
  --sufficient true|false \
  --rationale "..."
```

Or batch-record from a JSON file:

```bash
uv run python .claude/skills/paper-triage/scripts/record.py \
  --batch /tmp/triage.json
```

Where `/tmp/triage.json` looks like:

```json
[
  {"canonical_id": "...", "sufficient": true,  "rationale": "..."},
  {"canonical_id": "...", "sufficient": false, "rationale": "..."}
]
```

## Outputs

- `manifest.json["triage"]` = `{sufficient, rationale, at}`
- `manifest.json["state"]` advances to `triaged`
- List of `canonical_id`s with `sufficient=false` printed to stdout (those are what `paper-acquire` will fetch)

## Guardrails

- The only way to mark a paper "approved to fetch" is via this skill. `paper-acquire` hard-checks `triage.sufficient == false` before touching any network.
- If the metadata artifact is missing abstract + tldr + claims all together, the script refuses to record a "sufficient" verdict and errors out — forcing either acquisition or an explicit override.

## CLI flag reference (drift coverage)

- `record.py`: `--force`
