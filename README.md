# Coscientist

A personal academic-research-agent toolkit for Claude Code. Assembled Lego-style from atomic skills + existing MCP servers rather than a monolithic app.

## What it does

Given a research question, an agent works through it end-to-end:

1. **Discovery** — searches across Consensus (200M+ papers), Semantic Scholar, arXiv, PubMed, bioRxiv, IEEE, Springer, and 20+ other sources in parallel.
2. **Triage** — decides per-paper whether the abstract/TLDR is enough, or whether full text is needed.
3. **Acquisition** — fetches PDFs through an open-access fallback chain, falling through to your institution's access via OpenAthens when OA sources don't have it.
4. **Extraction** — Docling converts PDFs into structured Markdown with figures, tables, equations, and references preserved.
5. **Analysis** — 10 specialized sub-agents (Grounder, Historian, Gaper, Vision, Theorist, Rude, Synthesizer, Thinker, Scribe, Social) work through the corpus with three human-in-the-loop review breaks.
6. **Output** — produces a Research Brief + six-section Understanding Map, with every claim traceable to its source paper in a SQLite run log.

## Architecture

Each skill is atomic and does one job. Skills compose through a shared **paper artifact** on disk — no skill calls another skill directly, so any piece can be swapped out.

```
~/.cache/coscientist/papers/<paper_id>/
  manifest.json       metadata.json
  content.md          frontmatter.yaml
  figures/  tables/   references.json
  equations.json      raw/  extraction.log
```

State flows: `discovered → triaged → acquired → extracted → read → cited`.

## Skills

| Skill | Job |
|---|---|
| `/paper-discovery` | Multi-source search with dedup across discovery MCPs |
| `/paper-triage` | Decide metadata-sufficient vs full-text-needed |
| `/paper-acquire` | OA fallback chain + handoff to institutional access |
| `/institutional-access` | OpenAthens login + per-publisher PDF fetch via Playwright |
| `/arxiv-to-markdown` | Fast path for arXiv: HTML → clean Markdown |
| `/pdf-extract` | Docling extraction + Claude vision fallback |
| `/research-eval` | Reference and claim auditing |
| `/deep-research` | Orchestrates the 10 sub-agents end-to-end |

## MCP servers used

Registered in `.mcp.json`:

- **Consensus** (HTTP+OAuth) — semantic search + claim extraction over 200M papers
- **paper-search-mcp** — 25+ sources, OA fallback downloads
- **academic-mcp** — 19+ sources including IEEE/Springer/ScienceDirect
- **Semantic Scholar** — citation graph traversal
- **Playwright MCP** — scripted browser for institutional-access
- **browser-use MCP** — LLM-guided browser fallback
- **Zotero** (local) — wraps Zotero's HTTP API for institutional PDF resolution + permanent library

## Setup

```bash
# Python deps (Docling, Playwright, arxiv2markdown, etc.)
uv sync

# One-time: bootstrap OpenAthens session for institutional-access
uv run python .claude/skills/institutional-access/scripts/login.py

# Playwright browsers
uv run playwright install chromium
```

Then in Claude Code: `/deep-research "your research question"`.

## Guardrails

The `institutional-access` skill enforces:

- **10 second delay** between PDF fetches per publisher domain
- **Triage gate**: no PDF is fetched unless `paper-triage` explicitly marked the paper as needing full text
- **Audit log**: every download recorded with DOI, timestamp, source tier
- Sci-Hub tier disabled by default

## Credits

Ports concepts and code from three MIT-licensed projects:

- [anvix9/basis_research_agents](https://github.com/anvix9/basis_research_agents) — the 10-agent SEEKER pipeline
- [timf34/arxiv2md](https://github.com/timf34/arxiv2md) — arXiv HTML to Markdown
- [openags/paper-search-mcp](https://github.com/openags/paper-search-mcp) — multi-source academic search

## License

MIT.
