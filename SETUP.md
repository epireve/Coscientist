# Coscientist Setup Guide

How to install + run the Coscientist deep-research toolkit. Two paths: **local project mode** (full toolkit, all 55 skills + 31 sub-agents) and **Cowork plugin mode** (deep-research only, runs anywhere).

---

## Path A — Local Project Mode (full toolkit)

Best when you want the complete research workbench: manuscript drafting, peer-review simulation, tournament/evolution, project-dashboards, cross-project memory.

### Prerequisites

- macOS or Linux
- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Claude Code 2.0+
- Docker (only for `experiment-reproduce` / `reproducibility-mcp`)
- Pandoc (only for `manuscript-format`, `citation-format-converter`) — `brew install pandoc`

### Install

```bash
git clone https://github.com/epireve/coscientist
cd coscientist
uv sync
```

### Configure MCPs

`.mcp.json` ships with these MCP servers wired:

| MCP | Purpose | Auth |
|---|---|---|
| `consensus` | Primary literature search (claim extraction, TLDRs) | Free tier 3 results, Pro = unlimited |
| `semantic-scholar` | Citation graph, author resolution, bulk papers | API key in env block |
| `paper-search` | Google Scholar + arXiv + bioRxiv + medRxiv + PubMed | None |
| `academic` | Multi-source academic | None |
| `zotero` | Bridge to your Zotero library | API key + library ID |
| `playwright` | Browser automation for paper-acquire Tier 2 | None |
| `perplexity` | Web-grounded reasoning | API key |

Add your **Semantic Scholar API key** ([apply here](https://www.semanticscholar.org/product/api#api-key-form)) to `.mcp.json`:

```json
"semantic-scholar": {
  "type": "stdio",
  "command": "uvx",
  "args": ["semantic-scholar-mcp"],
  "env": {
    "SEMANTIC_SCHOLAR_API_KEY": "<your-key>"
  }
}
```

For **Consensus Pro**, the MCP server reads its auth token from `~/.config/consensus/auth.json` after you sign in via the Consensus CLI / browser flow once.

### Run a research question

```bash
# In Claude Code, opened to the coscientist repo root:
/deep-research "your research question here"
```

Or directly via CLI:

```bash
run_id=$(uv run python .claude/skills/deep-research/scripts/db.py init \
  --question "your question")
uv run python .claude/skills/deep-research/scripts/db.py resume --run-id $run_id
```

### Outputs

- `~/.cache/coscientist/runs/run-<run_id>/brief.md` — Research Brief
- `~/.cache/coscientist/runs/run-<run_id>/understanding_map.md` — six-section map
- `~/.cache/coscientist/runs/run-<run_id>/eval.md` — reference + claim audit
- `~/.cache/coscientist/runs/run-<run_id>.db` — full SQLite state (resumable)

---

## Path B — Cowork Plugin Mode (deep-research only)

Best when you want `/deep-research` available in any Cowork session without cloning the full repo. Bundles the 10 Expedition agents + dependent skills + vendored `lib/` into one installable plugin.

### Install

In Cowork (or any Claude Code session):

```
/plugin marketplace add epireve/coscientist
/plugin install coscientist-deep-research@coscientist
```

That fetches the plugin from `https://github.com/epireve/coscientist` (the `.claude-plugin/marketplace.json` at the repo root advertises the plugin source).

For local dev, point at your checkout:

```
/plugin marketplace add /Users/you/dev/coscientist
/plugin install coscientist-deep-research@coscientist
```

### Configure MCPs in Cowork

Cowork sessions inherit MCPs from your **user-level** `~/.claude/settings.json` or per-Cowork-environment configuration. The plugin assumes these are already wired:

- `consensus` (Pro auth recommended — the plugin defaults to Consensus first)
- `semantic-scholar` (key required)
- `paper-search`

If any are missing, the orchestrator falls through gracefully but coverage drops.

### What you get

- `/deep-research "question"` slash command
- All 10 Expedition sub-agents (scout → steward)
- Bundled skills: `deep-research`, `paper-discovery`, `paper-triage`, `paper-acquire`, `pdf-extract`, `arxiv-to-markdown`, `research-eval`, `novelty-check`, `publishability-check`, `attack-vectors`
- Vendored `lib/` (cache, persona_input, paper_artifact, project, graph, migrations, schema)

### What you DON'T get (vs. Path A)

- Manuscript skills (drafting, audit, critique, format, version, ingest, revise, reflect, peer-review, reviewer-assistant)
- Project / journal / dashboard / cross-project-memory
- Tournament + mutator (hypothesis evolution)
- Experiment / dataset / Zenodo / DMP / IRB
- 21 other Phase B/C/D/E/F sub-agents

For those, install Path A.

---

## Verifying install

```bash
# In any Claude Code session:
/plugin list
# Should show: coscientist-deep-research@coscientist (enabled)

# Confirm S2 key live:
# Run an MCP call — check_api_key_status — and look for `api_key_configured: true`
```

---

## Cost expectations

A full 10-phase Expedition run on a non-trivial question:
- ~$3–5 in Anthropic API tokens
- 30–60 min wall-clock
- 50–200 candidate papers seeded by `scout`
- 10–30 PDFs acquired via `paper-acquire` (only those `paper-triage` flags as needing full text)
- 3 human-in-the-loop break points (skippable via `--overnight`)

---

## Troubleshooting

**`/deep-research` not found in Cowork.** Plugin not installed or marketplace not added. Run `/plugin marketplace list` then `/plugin list`.

**`semantic-scholar` rate-limit (E3001).** Either the shared anonymous tier (1 RPS shared) or your key exceeded 1 RPS. Orchestrator falls through to paper-search. To fix permanently, get/rotate API key.

**`Consensus capped at 3 results`.** Free-tier limit. Sign in to Consensus Pro and re-auth the MCP.

**`paper-acquire` blocked on triage.** Guardrail: no PDF fetched until triage marks `sufficient: false`. Run paper-triage first.

**Old `social/grounder/historian/...` phase names in old runs.** Backward-compat aliases in `db.py PHASE_ALIASES` — these resume correctly.

---

## Companion docs

- `CLAUDE.md` — project guide for Claude (read before editing `.claude/`)
- `RESEARCHER.md` — principles every research sub-agent follows
- `ROADMAP.md` — what's shipped, in flight, parked
- `.claude/skills/deep-research/SKILL.md` — full orchestrator specification
