---
name: institutional-access
description: Fetch a paper's PDF via your university's OpenAthens SSO using a headful Playwright session. Per-publisher adapters handle the "download PDF" click; browser-use MCP is the Tier 2 fallback for publishers without an adapter. Final tier of `paper-acquire`.
when_to_use: Invoked by `paper-acquire` after all OA tiers fail. Not called directly by agents except for manual debugging.
---

# institutional-access

A local-browser adapter for entitled publisher access. Runs headful Chromium with a persistent storage state — so you log in through OpenAthens (including MFA) exactly once, and the session is reused until cookies expire.

## One-time setup

```bash
# 1. Install Chromium
uv run playwright install chromium

# 2. Bootstrap the OpenAthens session (opens a browser window)
uv run python .claude/skills/institutional-access/scripts/login.py \
  --idp https://my.openathens.net/?passiveLogin=false
```

Steps inside the bootstrap:

1. Browser opens to the OpenAthens entry point
2. You find your institution, sign in with SSO + MFA
3. When you reach your OpenAthens dashboard, press `Enter` in the terminal
4. The script saves `storage_state.json` (cookies + local storage) to `.claude/skills/institutional-access/state/`

The state directory is gitignored. Never commit it.

## How `paper-acquire` invokes it

```bash
uv run python .claude/skills/institutional-access/scripts/fetch.py \
  --canonical-id <cid>
```

The script:

1. Loads `manifest.doi` from the paper artifact
2. Determines the publisher from the DOI prefix (`10.1016` → Elsevier, `10.1007` → Springer, etc.)
3. Calls the matching adapter in `scripts/adapters/`
4. Adapter launches Chromium with the saved storage state, navigates, finds the PDF link, downloads to `raw/institutional.pdf`
5. If no adapter matches, falls through to `browser-use` MCP (Tier 2)
6. On success, prints the PDF path (for `paper-acquire/scripts/record.py` to ingest)

## Per-publisher adapters

Seeded adapters:

| Prefix | Publisher | Adapter |
|---|---|---|
| 10.1016 | Elsevier / ScienceDirect | `adapters/elsevier.py` |
| 10.1007 | Springer | `adapters/springer.py` |
| 10.1002 | Wiley | `adapters/wiley.py` |
| 10.1109 | IEEE | `adapters/ieee.py` |
| 10.1038 | Nature / Springer Nature | `adapters/nature.py` |
| 10.1021 | ACS | `adapters/acs.py` |

Each adapter is ~30 lines and exports `async def fetch_pdf(context, doi, out_path) -> Path`. When a publisher's HTML changes, the failure mode is "fall through to Tier 2", not "skill is broken".

## Rate-limit + guardrails

- `lib.rate_limit.wait(<publisher_domain>)` runs before every navigation. Default 10s per domain.
- Every fetch (success or failure) is appended to `~/.cache/coscientist/audit.log` with DOI + timestamp + tier.
- **Triage gate**: `paper-acquire/scripts/gate.py` must pass before this skill is touched. No speculative fetches.
- **Sci-Hub**: off by default. Set `COSCIENTIST_ALLOW_SCIHUB=1` to enable (still requires a separate adapter).
- **Headful only**: persistent profile and real window match a human session and reduce bot-flag risk. Do not switch to `--headless`.

## Session expiry

When `fetch.py` detects a redirect back to the OpenAthens IdP (SSO expired), it exits with code 10 and a clear message: "re-run login.py". Don't try to re-auth programmatically.

## Adding a new publisher

1. Create `scripts/adapters/<publisher>.py` with `async def fetch_pdf(context, doi, out_path)`.
2. Register the DOI prefix → module mapping in `scripts/adapters/__init__.py`.
3. Keep the adapter tiny — publishers change their UI often. The `browser-use` fallback handles the long tail.
