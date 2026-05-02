# coscientist — Cowork plugin

Academic research-agent toolkit packaged for [Claude Cowork](https://claude.com/cowork).

70 skills + 42 sub-agent personas:

- **Deep research** — 10-phase Expedition pipeline (Scout → Cartographer → Chronicler → Surveyor → Synthesist → Architect → Inquisitor → Weaver → Visionary → Steward)
- **Manuscript subsystem** — ingest, audit, critique, reflect, draft, revise, version, format export
- **Citation graph** — reference-agent + Zotero sync, OpenAlex/Semantic-Scholar/Consensus discovery
- **Hypothesis tournaments** — rooted trees, Elo + auto-prune (Google Co-scientist pattern)
- **Critical judgment** — novelty + publishability + red-team gates with structured verdicts
- **Wide research** — fan-out N-item processing (10-250 items in parallel)
- **Graph analytics** — replication-finder, coauthor-network, funding-graph, claim-cluster, citation-decay, PageRank, Louvain

## Install — Cowork desktop

1. Zip this folder:

   ```bash
   cd /path/to/coscientist
   zip -r coscientist-cowork.zip plugin/coscientist-cowork \
     -x '*.DS_Store' '*__pycache__*'
   ```

2. Open **Cowork** → **Customize** (left sidebar) → **Browse plugins** → **Upload custom plugin**
3. Select `coscientist-cowork.zip`
4. Review permissions → **Authorise**

## Install — CLI

```bash
claude plugin marketplace add /path/to/coscientist
claude plugin install coscientist
```

## Required env vars

Optional but recommended for full functionality:

```bash
export OPENALEX_MAILTO="your-email@example.com"   # polite-pool (free)
export CONSENSUS_API_KEY="..."                     # lifts 3-result cap
export SEMANTIC_SCHOLAR_API_KEY="..."              # lifts 1 req/s rate
export ZOTERO_API_KEY="..."                        # reference-agent sync
export COSCIENTIST_CACHE_DIR="$HOME/.cache/coscientist"
```

Without keys, OpenAlex polite-pool + Consensus 3-result + S2 anon all still work — just slower / capped.

## Cache layout

```
~/.cache/coscientist/
├── papers/<canonical_id>/      # paper artifacts
├── manuscripts/<mid>/          # your manuscripts
├── runs/run-<run_id>.db        # deep-research run logs
├── projects/<pid>/project.db   # project-scoped graph + reading state
└── audit.log                   # PDF fetch audit trail
```

## First steps

```
/deep-research "your research question"
```

Or kick off a project:

```bash
uv run python .claude/skills/project-manager/scripts/project.py init \
  --name "My Project" --question "Your question"
```

## Architecture invariants

- **Pure-stdlib `lib/`** — no external Python deps in core
- **WAL-mode SQLite** — concurrent reads safe
- **Best-effort instrumentation** — tracing failures never break parent flow
- **Markdown-first manuscripts** — pandoc converts to LaTeX/.docx at submission

## Project status

48 versions shipped (v0.156-v0.203). 2530 tests passing. End-to-end deep-research run produces real artifacts.

## License

MIT. Source: https://github.com/epireve/coscientist
