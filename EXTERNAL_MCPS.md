# External MCPs Coscientist consumes

Coscientist depends on several third-party Model Context Protocol
servers that it does **not** redistribute. They're authored and
maintained by other developers; we just call them.

This list is for users setting up the full pipeline. The custom MCPs
shipped *in* this repo are documented separately — see
[MCP_SERVERS.md](./MCP_SERVERS.md).

## Custom MCPs (shipped here, install via `/plugin install`)

| Plugin | What it does |
|---|---|
| `coscientist-retraction-mcp` | Crossref + PubPeer retraction + comment lookups |
| `coscientist-manuscript-mcp` | `.docx` / `.tex` / `.md` → AST |
| `coscientist-graph-query-mcp` | Read-only graph primitives over project DBs |

See [MCP_SERVERS.md](./MCP_SERVERS.md) for full tool reference.

## External MCPs (install separately)

These are referenced from `.mcp.json` (gitignored — contains API
keys). To set up, copy `.mcp.json.example` to `.mcp.json`, fill in
your API keys, then ensure the external MCPs are reachable.

### `consensus`

- **What**: 200M+ paper search via Consensus's hosted MCP endpoint.
- **Type**: HTTP (hosted at `https://mcp.consensus.app/mcp`).
- **API key**: Not required — public endpoint.
- **Used by**: `paper-discovery`, `scout` persona.
- **Source**: [consensus.app](https://consensus.app/)

### `paper-search`

- **What**: Cross-source paper search (arXiv, bioRxiv, medRxiv,
  PubMed, Google Scholar, IEEE, DOAJ, Zenodo, Unpaywall, CORE).
- **Type**: stdio. Install: `uvx paper-search-mcp`.
- **API keys**: Several optional — Semantic Scholar, CORE, DOAJ,
  Zenodo, IEEE, Unpaywall (just an email).
- **Used by**: `paper-discovery`, `paper-acquire`, all Phase A
  search-using personas.
- **Source**: [openags/paper-search-mcp](https://github.com/openags/paper-search-mcp) (MIT)

### `academic`

- **What**: Academic search aggregator — Semantic Scholar
  citation/reference walks, OpenAlex, Crossref.
- **Type**: stdio. Install: `uvx academic-mcp`.
- **API keys**: None required.
- **Used by**: `cartographer`, `chronicler` personas.
- **Source**: [LinXueyuanStdio/academic-mcp](https://github.com/LinXueyuanStdio/academic-mcp) (MIT)

### `semantic-scholar`

- **What**: Direct Semantic Scholar API access — paper lookup,
  citation graph, author profiles, recommendations.
- **Type**: stdio. Install: `uvx semantic-scholar-mcp`.
- **API key**: `SEMANTIC_SCHOLAR_API_KEY` recommended (higher rate
  limit). Free at [semanticscholar.org/product/api](https://www.semanticscholar.org/product/api).
- **Used by**: `cartographer`, `chronicler`, `surveyor`,
  `architect`, `visionary` personas; `resolve-citation` skill.

### `playwright`

- **What**: Browser automation. Headful mode preferred for
  institutional access flows.
- **Type**: stdio. Install: `npx -y @playwright/mcp@latest`.
- **API keys**: None.
- **Used by**: `institutional-access` skill (Tier 1 publisher
  adapters).
- **Source**: [microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp)

### `browser-use`

- **What**: Browser automation with built-in LLM agent — used as
  Tier 2 fallback for publishers without a Playwright adapter.
- **Type**: stdio. Install: `uvx --with browser-use==0.1.40 browser-use-mcp-server`.
- **API keys**: Whatever LLM provider you give it.
- **Used by**: `institutional-access` skill (Tier 2 fallback).
- **Source**: [browser-use/browser-use](https://github.com/browser-use/browser-use)

### `zotero`

- **What**: Bidirectional sync with local Zotero (via Better
  BibTeX-style HTTP server on port 23119).
- **Type**: stdio. Install: `uvx zotero-mcp`.
- **API keys**: None — talks to local Zotero (`http://127.0.0.1:23119`).
- **Used by**: `reference-agent`, `librarian` persona.

## Why these aren't republished here

| Reason | Detail |
|---|---|
| Authorship | Each is owned by another developer; redistributing under `epireve/coscientist` would be vendoring without permission. |
| Update cadence | Upstream maintainers ship faster than we'd track. |
| Plugin scope | Coscientist's plugins ship the *novel* surface — pipelines, custom MCPs, atomic skills. External MCPs are dependencies. |

If a third-party MCP becomes unmaintained and we genuinely need it,
we'd fork + rename rather than republish.

## Setup checklist for full pipeline

1. Install the Coscientist marketplace plugins:
   ```
   /plugin marketplace add epireve/coscientist
   /plugin install coscientist-deep-research@coscientist
   /plugin install coscientist-retraction-mcp@coscientist
   /plugin install coscientist-manuscript-mcp@coscientist
   /plugin install coscientist-graph-query-mcp@coscientist
   ```

2. Copy `.mcp.json.example` to `.mcp.json` and fill in API keys for
   the external MCPs you want to use.

3. Ensure the external MCPs are reachable:
   - `paper-search`, `academic`, `semantic-scholar`, `zotero`,
     `browser-use` all install via `uvx <name>` on first call.
   - `playwright` installs via `npx -y @playwright/mcp@latest`.
   - `consensus` is HTTP-hosted — nothing to install locally.

4. Verify with: `claude mcp list` — should show all configured
   servers as connected.
