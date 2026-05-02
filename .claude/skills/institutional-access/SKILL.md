---
name: institutional-access
description: Fetch a paper's PDF via the user's authenticated Chrome browser using the claude-in-chrome MCP. Cookies live in Chrome profile — login once via normal browsing, every fetch reuses session. Final tier of `paper-acquire` for paywalled DOIs.
when_to_use: Invoked by `paper-acquire` after all OA tiers (arxiv, OpenAlex oa_url, Unpaywall) fail. Not called directly by agents except for manual debugging.
---

# institutional-access

**v0.205 refactor**: replaced 837-line Playwright + 14 publisher adapters + storage-state cookie-jar with **claude-in-chrome MCP**.

## Why Chrome MCP

User already authenticated to OpenAthens / Shibboleth / EZproxy / publisher-direct sessions via normal Chrome browsing. Cookies persist in Chrome profile. We delegate:

- **No infra to maintain** — no Playwright install, no per-publisher adapters, no Cloudflare bypass
- **No anti-bot fight** — real browser, real user fingerprint, real cookies
- **No credential storage on our side** — auth state lives in Chrome where it belongs
- **Auto-refresh** — when cookie expires, user re-auths in normal Chrome browsing → all future fetches resume

## Setup (one-time)

1. **Install claude-in-chrome MCP** (Chrome extension + MCP server). See [Anthropic docs](https://docs.anthropic.com/en/docs/claude-in-chrome).
2. **Log into your institution** via Chrome:
   - Visit `https://my.openathens.net/?passiveLogin=false`
   - Complete SSO + MFA
   - Optionally visit one paywalled article (e.g., a Nature URL) to ensure publisher cookies set
3. **That's it.** No Coscientist setup, no Playwright, no storage_state.json.

Cookie expiry: OpenAthens ~12h, individual publisher cookies vary (1d–30d). When fetches start failing with login redirects, re-auth in Chrome.

## Architecture

```
paper-acquire orchestrator
  └── (calls) institutional-access/scripts/chrome_fetch.py plan
        └── emits JSON plan describing Chrome MCP steps
               ↓
           orchestrator (parent w/ MCP access) executes:
             1. mcp__Claude_in_Chrome__navigate   → doi.org/<doi>
             2. mcp__Claude_in_Chrome__find       → "PDF download button"
             3. mcp__Claude_in_Chrome__computer   → click; browser downloads
             4. shell wait + locate newest PDF in ~/Downloads
             5. chrome_fetch.py record → persist + audit
```

The script is a **plan-emitter**, not an MCP-caller. Same harvest pattern used everywhere in coscientist (orchestrator drives MCP, script reads result). Reason: sub-agents may not inherit MCP access (per v0.186 closure).

## CLI

```bash
# Step 1: emit plan for orchestrator to execute
uv run python .claude/skills/institutional-access/scripts/chrome_fetch.py \
  plan --canonical-id <cid> [--doi 10.1234/x]

# Step 2: after orchestrator drives Chrome MCP and downloads PDF
uv run python .claude/skills/institutional-access/scripts/chrome_fetch.py \
  record --canonical-id <cid> --pdf ~/Downloads/<file>.pdf
```

`record` updates manifest.json (`state=acquired`, `acquired_via=chrome-claude`), copies PDF to `~/.cache/coscientist/papers/<cid>/raw/paper.pdf`, appends one line to `~/.cache/coscientist/audit.log`.

## Failure modes

- **Login redirect** — Chrome session expired. User re-authenticates via normal browsing, retries.
- **PDF link not found** — `find()` returned no results. Fall back to manual nav + screenshot for debugging.
- **Publisher anti-bot** — extremely rare with real Chrome session. If it happens, Tier 2 = browser-use MCP (separate skill).
- **Sci-Hub** — disabled by default. Enable only if institutionally-allowed and `COSCIENTIST_ALLOW_SCIHUB=1` set.

## What was removed (v0.205 refactor)

837 LOC + 14 publisher adapters dropped:

- `scripts/login.py` — Playwright bootstrap
- `scripts/idp_runner.py` — 383-line IdP automation
- `scripts/import_cookies.py` — cookie import from browser
- `scripts/check.py` — Playwright sanity check
- `scripts/fetch.py` — Playwright fetch w/ adapter dispatch
- `scripts/adapters/{acm,acs,elsevier,emerald,generic,ieee,jstor,nature,sage,springer,wiley}.py` — per-publisher click logic
- `state/storage_state.json` — Playwright cookie jar
- `state/chrome_profile/` — Playwright persistent context (local-only, gitignored)
- `institutions/{_template,um}.json` — IdP configs

Playwright dep can be dropped from `pyproject.toml` once no other skill needs it.

## Audit trail

Every fetch logs to `~/.cache/coscientist/audit.log`:

```json
{"at": "2026-04-30T...", "action": "fetch", "canonical_id": "...", "tier": "chrome-claude", "pdf_size": 1234567, "doi": "10.1234/x"}
```

Same format as v0.17 paper-acquire audit. `audit-query` skill aggregates across all tiers.
