---
name: paper-acquire
description: Fetch a PDF for a paper that triage marked as needing full text. Runs an OA-first fallback chain, handing off to `institutional-access` as the last resort. Enforces the triage gate, per-publisher rate limits, and the audit log.
when_to_use: After `paper-triage` has marked a paper `sufficient=false`. Never call speculatively — the gate script will refuse.
---

# paper-acquire

Orchestrates PDF acquisition via a five-tier fallback. Never implements HTTP logic itself — delegates to existing MCPs.

## The acquisition ladder (in order)

| Tier | Source | How |
|---|---|---|
| 0 | arXiv HTML → markdown | If `manifest.arxiv_id` is set: invoke `/arxiv-to-markdown` and **skip the PDF entirely**. State jumps straight to `extracted`. |
| 1 | arXiv PDF | `paper-search` MCP's `download_arxiv` tool |
| 2 | OA fallback chain | `paper-search` MCP's `download_with_fallback` — covers Unpaywall, Europe PMC, PMC, OpenAIRE, CORE in one call |
| 3 | Zotero "Find Available PDF" | `zotero` MCP — honors your institutional proxy if Zotero is configured for it |
| 4 | `institutional-access` | Playwright browser session logged into OpenAthens; per-publisher adapter |
| 5 | Sci-Hub (disabled) | Only if `COSCIENTIST_ALLOW_SCIHUB=1` — off by default |

## How to use (agent-facing procedure)

1. Enforce the gate:

```bash
uv run python .claude/skills/paper-acquire/scripts/gate.py --canonical-id <cid>
```

Exits 0 if `manifest.triage.sufficient == false`; otherwise exits non-zero with reason. Never bypass.

2. If `manifest.arxiv_id` is set: call `/arxiv-to-markdown --arxiv-id <id> --canonical-id <cid>` and stop. Done.

3. Otherwise, walk tiers 1→5 in order. On each tier, call the appropriate MCP tool. On success, save the PDF to `~/.cache/coscientist/papers/<cid>/raw/<publisher>.pdf` via:

```bash
uv run python .claude/skills/paper-acquire/scripts/record.py \
  --canonical-id <cid> \
  --source <tier-name> \
  --pdf-path <path-to-downloaded-pdf>
```

4. On final failure (all tiers), record the failure and exit — the paper stays in state `triaged`; `deep-research` will know it can't read it.

The `record.py` script:
- Writes the PDF into `raw/`
- Advances `manifest.state` to `acquired`
- Appends to `~/.cache/coscientist/audit.log` with DOI, timestamp, source tier
- Records the source attempt in the manifest

## Rate-limit & guardrails

- `paper-acquire` calls `lib.rate_limit.wait(<domain>)` before every publisher fetch. Default 10s per domain (`COSCIENTIST_PUBLISHER_DELAY`).
- Every successful + failed fetch is logged to `~/.cache/coscientist/audit.log`. This is non-optional.
- `gate.py` refuses to run if `manifest.triage.sufficient` is missing or `true`.

## What to do on partial success

If Tier 2 returns a paywall landing page (HTML, not PDF), mark `record.py --failed` for that tier and continue. Don't cache junk.

## Outputs

- `raw/<source>.pdf` on success
- Updates to `manifest.json`: `state=acquired`, `sources_tried[]` appended
- Line appended to `~/.cache/coscientist/audit.log`
