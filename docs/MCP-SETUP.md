# MCP Setup Guide

Per-MCP auth + API-key requirements for the seven servers registered in
[`.mcp.json`](../.mcp.json). For each: what's required to start, what's
optional but improves rate limits / coverage, and where to obtain
credentials.

> Most paper-search functionality works without any keys. The keys
> below are for higher rate limits, premium sources (IEEE, Springer,
> Elsevier), or LLM-driven browser automation.

## Quick reference

| MCP | Upstream | Required to start | Optional but useful |
|---|---|---|---|
| `consensus` | hosted at `mcp.consensus.app/mcp` | Consensus account + OAuth (auto on first connect) | — |
| `paper-search` | [openags/paper-search-mcp](https://github.com/openags/paper-search-mcp) | none | Unpaywall email, Semantic Scholar key, CORE key, DOAJ key, IEEE/ACM keys |
| `academic` | [LinXueyuanStdio/academic-mcp](https://github.com/LinXueyuanStdio/academic-mcp) | none | IEEE / Scopus / Springer / ScienceDirect / CORE keys |
| `semantic-scholar` | [hy20191108/semantic-scholar-mcp](https://github.com/hy20191108/semantic-scholar-mcp) | none (anonymous tier works) | `SEMANTIC_SCHOLAR_API_KEY` for higher rate limits |
| `playwright` | [microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp) | none | — |
| `browser-use` | [co-browser/browser-use-mcp-server](https://github.com/co-browser/browser-use-mcp-server) | `OPENAI_API_KEY` | — |
| `zotero` | [kujenga/zotero-mcp](https://github.com/kujenga/zotero-mcp) | Zotero Desktop (local) **or** `ZOTERO_API_KEY` + `ZOTERO_LIBRARY_ID` (Web API) | — |

## Where to get each key

### Free / open

- **Semantic Scholar API key** — https://www.semanticscholar.org/product/api. Click "Get an API key", form takes <1 min. Use as `SEMANTIC_SCHOLAR_API_KEY` (consumed by both `paper-search` and `semantic-scholar` MCPs; the latter falls back to anonymous if unset).
- **Unpaywall email** — no key needed; just an email address you own. Set as `PAPER_SEARCH_MCP_UNPAYWALL_EMAIL`. Without it, Unpaywall (the OA-PDF resolver) is silently skipped from `paper-acquire`'s OA chain.
- **CORE API key** — https://core.ac.uk/services/api. Free tier, registration form. Set as `CORE_API_KEY` (academic) or `PAPER_SEARCH_MCP_CORE_API_KEY` (paper-search).
- **DOAJ key** — https://doaj.org/account/register. Free; only needed to raise hourly rate limits. Set as `PAPER_SEARCH_MCP_DOAJ_API_KEY`.
- **OpenAI API key** (for `browser-use`) — https://platform.openai.com/api-keys. Pay-as-you-go; the browser-use agent makes one or more LLM calls per browse step. Set as `OPENAI_API_KEY`.

### Premium / institutional

These are the keys that gate paid databases. You need an existing subscription
or institutional access to obtain them. **Skip these unless your university
already provides access.**

- **IEEE Xplore API key** — https://developer.ieee.org/. Requires institutional subscription. Set as `IEEE_API_KEY` (academic) or `PAPER_SEARCH_MCP_IEEE_API_KEY` (paper-search).
- **Scopus API key** — https://dev.elsevier.com/sc_apis.html. Requires Scopus subscription. Set as `SCOPUS_API_KEY`.
- **Springer Link API key** — https://dev.springernature.com/. Requires Springer subscription. Set as `SPRINGER_API_KEY`.
- **ScienceDirect (Elsevier) API key** — https://dev.elsevier.com/sd_apis.html. Same registration as Scopus. Set as `SCIENCEDIRECT_API_KEY`.
- **ACM Digital Library** — https://libraries.acm.org/digital-library/api. Institutional only. Set as `PAPER_SEARCH_MCP_ACM_API_KEY`.

For these, the recommended path in this project is **`institutional-access`**
(headful Playwright + OpenAthens SSO, configured per-publisher in
[`.claude/skills/institutional-access/scripts/adapters/`](../.claude/skills/institutional-access/scripts/adapters/)).
That's how you fetch a paid PDF without managing five separate publisher API
keys. The keys above are only useful for *search* over the premium databases;
the actual PDF fetch goes through the institutional adapter regardless.

### OAuth / browser flows

- **Consensus** — no API key. The hosted MCP at `mcp.consensus.app/mcp` opens a browser for OAuth on first connect. You need a Consensus account (https://consensus.app — free tier covers most usage; paid tier raises limits).

### Local app required

- **Zotero (local)** — needs the Zotero desktop app running on your machine with "Allow other applications on this computer to communicate with Zotero" enabled (Settings → Advanced → Files and Folders). The MCP talks to `http://127.0.0.1:23119`. No API key needed in this mode.
- **Zotero (Web API)** — alternative if the desktop app isn't available. Generate a key at https://www.zotero.org/settings/keys. Set `ZOTERO_API_KEY` and `ZOTERO_LIBRARY_ID` (your user ID is shown at https://www.zotero.org/settings/keys).

## Setting env vars

Two ways:

1. **In `.mcp.json` per-server** — under `"env"`:

   ```json
   "semantic-scholar": {
     "type": "stdio",
     "command": "uvx",
     "args": ["semantic-scholar-mcp"],
     "env": {
       "SEMANTIC_SCHOLAR_API_KEY": "your-key-here"
     }
   }
   ```

2. **In your shell profile** (`~/.zshrc` / `~/.bashrc`) — exported before
   Claude Code starts. Picked up by every MCP that reads from process env.

Don't commit secrets. `.mcp.json` is checked into the repo; if you put keys
there, gitignore your local copy or use a `.mcp.local.json` (Claude Code will
merge both).

## Verification

After setting any key, restart Claude Code and run a small probe to confirm
the MCP started cleanly:

- For paper-search MCPs: ask the agent to search for one paper. If the MCP
  failed to start (bad key format, missing dep), the search returns an
  obvious error rather than empty results.
- For Zotero: ask the agent to list your Zotero collections. Empty result
  with no error usually means desktop-app communication isn't enabled.
- For browser-use: ask the agent to navigate to a URL. It will loudly fail
  if `OPENAI_API_KEY` is missing or invalid.

## What this project actually needs

The core deep-research pipeline only requires:

- **Semantic Scholar** (anonymous works, key strongly recommended for
  research-scale runs)
- **paper-search** + **academic** (no keys needed for the free/OA sources
  that cover most of arXiv / PubMed / OpenAlex / Crossref)
- **Consensus** (free tier OK for most usage)
- **Playwright** (no key)

Optional and adding later as needed:

- **Zotero** — once you want bidirectional sync between the paper cache
  and your Zotero library
- **browser-use** — only when an institutional-access publisher doesn't
  have a per-publisher Playwright adapter and you fall back to LLM-driven
  navigation
- **IEEE/Springer/Elsevier keys** — only if you specifically want to
  *search* those premium databases. Most institutional users get the actual
  PDFs through `institutional-access` + OpenAthens, which doesn't need any
  publisher API keys.
