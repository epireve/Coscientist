---
name: manuscript-audit
description: Gate-enforced per-claim audit of a user's manuscript. Extracts every substantive claim, checks each against its cited sources, flags overclaim / uncited / unsupported / outdated / retracted. Refuses empty reports and hedge words.
when_to_use: You have an ingested manuscript artifact and want to know which of its claims hold up against the literature it cites. Used by the `manuscript-auditor` sub-agent.
---

# manuscript-audit

Discipline layer. The sub-agent reads the manuscript, finds claims, checks sources. This gate enforces that the resulting report has the required structure and no hedging.

## What an audit report must contain

```
{
  "manuscript_id": "...",
  "claims": [
    {
      "claim_id": "c-1",
      "text": "<verbatim from source>",
      "location": "§3.2 ¶2",
      "cited_sources": ["canonical_id1", ...],   // may be empty
      "findings": [
        {
          "kind": "overclaim|uncited|unsupported|outdated|retracted",
          "severity": "info|minor|major",
          "evidence": "<specific, no hedge words>"
        }
      ]
    },
    ...
  ]
}
```

A `claim` with zero `findings` is a pass — the claim stands.

## Agent-facing procedure

1. Read `source.md` from the manuscript artifact.
2. Extract every substantive claim — every sentence that asserts a fact, makes a comparison, or states a conclusion. Skip definitions and pure setup.
3. For each claim: identify inline citations (`\cite{key}`, `[@key]`, `[1]`, footnotes) and resolve to canonical_ids where possible.
4. For each cited source: read its `content.md` or abstract and check — does it actually say this? Flag `unsupported` if no, `overclaim` if weaker than the manuscript's framing.
5. Flag `uncited` when a factual claim has no citation at all. Flag `outdated` when a cited paper is >7 years old in a fast-moving field and newer work exists. Flag `retracted` if the cited paper has been retracted (check Retraction Watch or equivalent when the retraction-mcp lands).
6. Pipe the report to the gate:

```bash
uv run python .claude/skills/manuscript-audit/scripts/gate.py \
  --input /tmp/audit-report.json \
  --manuscript-id <mid>
```

The gate exits non-zero if:
- No claims extracted (you didn't analyze)
- A finding's `kind` or `severity` is outside the allowed set
- Evidence contains hedge words ("may", "could potentially", "seems to")
- A finding is missing evidence
- A claim has citation in the text but `cited_sources` is empty (you skipped resolution)

## Principles this enforces

From `RESEARCHER.md`: **2 (Cite What You've Read)**, **7 (Commit to a Number — or at least a specific finding)**, **9 (Premortem — check each citation before claiming it supports the text)**.

## Outputs

- `~/.cache/coscientist/manuscripts/<mid>/audit_report.json` — full report
- Rows in `manuscript_claims` and `manuscript_audit_findings` (one row per claim, one per finding)
- `manifest.state` advances to `audited`
