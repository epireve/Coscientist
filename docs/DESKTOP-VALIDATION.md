# Desktop Validation Guide

Strategic test plan for validating Coscientist on a real desktop with live MCPs, APIs,
and Zotero. Run phases in order — each phase is a gate for the next. A failure in Phase 2
(MCP probes) means there is no point testing Phase 3 (per-skill smoke tests).

## Prerequisites

| Item | What to check |
|---|---|
| Python ≥ 3.11 | `python --version` |
| `uv` installed | `uv --version` |
| Claude Code CLI | `claude --version` |
| Zotero Desktop (local mode) | App open, Settings → Advanced → "Allow other apps" enabled |
| Shell env vars set | See [`docs/MCP-SETUP.md`](./MCP-SETUP.md) Method 2 |

---

## Phase 0 — Environment Setup

**Goal**: repo installs cleanly and MCPs register without errors.

```bash
# 1. Clone / pull to current state
git pull origin main

# 2. Install Python deps
uv sync

# 3. Verify Claude Code sees the registered MCPs
claude mcp list
```

**Expected**: `claude mcp list` prints all 7 entries:
`consensus`, `paper-search`, `academic`, `semantic-scholar`, `playwright`, `browser-use`, `zotero`

**Fail signals**:
- `uvx: command not found` → install uv: `curl -Lsf https://astral.sh/uv/install.sh | sh`
- `browser-use` shows error → `OPENAI_API_KEY` not set; set it or skip browser-use for now (not required for core pipeline)
- `zotero` shows error → Zotero Desktop not running or "Allow other apps" not toggled

**Recovery**: fix the specific MCP; re-run `claude mcp list`. The core pipeline needs
`consensus`, `semantic-scholar`, and `paper-search` at minimum.

---

## Phase 1 — Local Test Suite

**Goal**: all 327 unit/integration tests pass with no network access required.

```bash
cd /path/to/Coscientist
python -m tests.run_all
```

**Expected**:
```
Ran 327 tests in N.Ns
OK
```

**Fail signals**:
- `ModuleNotFoundError: lib.paper_artifact` → `uv sync` not done or wrong venv active
- Any `FAIL` or `ERROR` → look at the failing test class name; each maps to a specific subsystem
- `ImportError: docling` appearing in non-docling tests → test isolation broken; check `tests/_shim.py`

**Recovery**: never proceed to Phase 2 with failing tests. The suite is designed to
run without network; failures here are code regressions, not env problems.

---

## Phase 2 — Individual MCP Probes

Run each probe as a one-liner inside a Claude Code session (`claude`). Paste each
command and observe the output. These are read-only queries — nothing is written to disk.

### 2a. Semantic Scholar

```
Search Semantic Scholar for papers about "attention is all you need" — just the top 3 titles.
```

**Expected**: 3 paper titles printed, year ≈ 2017, authors include Vaswani.

**Fail signals**:
- `403 Forbidden` from `api.semanticscholar.org` → egress proxy is blocking the API.
  Workaround: use `SEMANTIC_SCHOLAR_API_KEY` (authenticated calls may route differently).
  Documented constraint — see ROADMAP.md.
- `rate limit` → anonymous tier; add `SEMANTIC_SCHOLAR_API_KEY` (free, 1-min signup).

### 2b. paper-search-mcp

```
Use paper-search-mcp to search for the paper "BERT: Pre-training of Deep Bidirectional Transformers". Return just the title and year.
```

**Expected**: title + 2019, possibly with DOI.

**Fail signals**:
- Tool not found → paper-search MCP not started; check `claude mcp list` again.
- Empty result → check whether `PAPER_SEARCH_MCP_SEMANTIC_SCHOLAR_API_KEY` is set.

### 2c. academic-mcp

```
Use academic-mcp to search for papers about "transformer language models". Return 2 results with titles only.
```

**Expected**: 2 paper titles about transformers/language models.

### 2d. Consensus

```
Use Consensus to search for "does exercise improve cognitive performance?" Return the top claim.
```

**Expected**: a synthesized claim about exercise and cognition, with paper citations.

**Fail signals**:
- OAuth prompt appears in terminal → complete the browser login once; it persists.
- `401 Unauthorized` → Consensus session expired; re-authenticate via browser.

### 2e. Playwright

```
Use Playwright to navigate to https://arxiv.org and take a screenshot. Confirm the page title contains "arXiv".
```

**Expected**: screenshot file or description confirming arXiv homepage loaded.

**Fail signals**:
- `Executable doesn't exist` → run `npx playwright install chromium`.
- Display error → set `DISPLAY=:0` or ensure a desktop session is active (Playwright runs headful).

### 2f. Zotero (local)

```
List my Zotero collections. Return just the collection names.
```

**Expected**: your Zotero collection names printed.

**Fail signals**:
- `Connection refused 127.0.0.1:23119` → Zotero Desktop is not running or "Allow other apps" not toggled.
- Empty list (no error) → Zotero running but no collections exist; that's OK — proceed.

### 2g. browser-use (optional)

```
Use browser-use to navigate to https://example.com and return the page title.
```

**Expected**: `Example Domain`

**Fail signals**:
- `OPENAI_API_KEY not set` → set it or skip; browser-use is Tier 2 fallback only.

---

## Phase 3 — Per-Skill Smoke Tests

These write real artifacts to `~/.cache/coscientist/`. Each test is independent — you
can run them in any order once Phase 2 passes.

### 3a. paper-discovery

```
/paper-discovery "vision transformers for medical image segmentation" --limit 5
```

**Expected**: 5 paper stubs in `~/.cache/coscientist/papers/`, each with `manifest.json`
+ `metadata.json`. Run:

```bash
ls ~/.cache/coscientist/papers/ | head -5
cat ~/.cache/coscientist/papers/<first-result>/manifest.json
```

Confirm `state: discovered` and `sources_tried` lists ≥ 1 MCP.

**Fail signals**:
- 0 papers → all MCPs returned empty; check query spelling and MCP connectivity.
- Papers missing `metadata.json` → discovery wrote manifest but failed on metadata fetch.

### 3b. paper-triage

Pick one paper from 3a and triage it:

```
/paper-triage <canonical_id> --question "How do vision transformers compare to CNNs for medical image segmentation?"
```

**Expected**: `manifest.json` state advances to `triaged`; `triage.sufficient` is `true` or `false`
with a rationale string.

### 3c. arxiv-to-markdown

```
/arxiv-to-markdown 1706.03762
```

**Expected**: paper directory created at `~/.cache/coscientist/papers/vaswani_2017_attention_*/`
with `content.md` (>50 lines), `frontmatter.yaml`, and `state: extracted`.

```bash
wc -l ~/.cache/coscientist/papers/vaswani_2017_attention_*/content.md
```

**Fail signals**:
- `arxiv2markdown not installed` → `uv add arxiv2markdown` or `uv sync`.
- `HTTP 429` from arXiv → wait 60s and retry; arXiv rate-limits aggressively.

### 3d. paper-acquire (OA path)

Use an open-access paper for this test (guaranteed free path):

```
/paper-acquire arxiv:2010.11929
```

(arXiv:2010.11929 = "An Image is Worth 16x16 Words" — ViT paper, freely available.)

**Expected**: PDF in `raw/arxiv.pdf`, state = `acquired`, audit log entry:

```bash
grep "2010.11929" ~/.cache/coscientist/audit.log
```

**Fail signals**:
- `state != triaged` error → triage the paper first (or use `--force` if testing acquire in isolation).
- Network error → check general internet connectivity.

### 3e. pdf-extract

```
/pdf-extract <canonical_id_from_3d>
```

**Expected**: `content.md` (>100 lines), `extraction.log` present, state = `extracted`.

**Fail signals**:
- `docling not installed` → `uv add docling`; docling has heavy deps (~2GB). If on a low-RAM machine,
  test the vision fallback: `/pdf-extract <id> --engine vision`.
- `not a PDF` → the acquired file is an HTML login wall; the publisher redirect was not resolved.
  Try with a confirmed OA PDF.

---

## Phase 4 — Manuscript Subsystem

**Goal**: full ingest → audit → critique → reflect chain on a real draft.

### 4a. Prepare a draft

Have a real `.md` or `.tex` manuscript ready, or use the test fixture:

```bash
ls tests/fixtures/
```

If none exist, create a minimal one-page draft at `/tmp/test_draft.md`:

```markdown
---
title: "Test Draft"
authors: ["Test Author"]
venue: "NeurIPS 2025"
---

# Introduction

Recent work on attention mechanisms [@vaswani2017attention] has shown...

## References

[@vaswani2017attention]: Vaswani et al. (2017). Attention Is All You Need.
```

### 4b. Ingest

```
/manuscript-ingest /tmp/test_draft.md
```

**Expected**: manuscript artifact created at `~/.cache/coscientist/manuscripts/<mid>/`,
state = `drafted`, `references.json` contains the Vaswani citation.

```bash
ls ~/.cache/coscientist/manuscripts/
cat ~/.cache/coscientist/manuscripts/<mid>/manifest.json
```

### 4c. Audit

```
/manuscript-audit <mid>
```

**Expected**: `audit_report.json` created, state = `audited`. Claims checked against
cited sources. Look for any `OVERCLAIM` or `UNCITED` flags.

### 4d. Critique

```
/manuscript-critique <mid>
```

**Expected**: `critique_report.json` with 4-persona critique (methodological, theoretical,
big-picture, nitpicky). Each persona has findings with severity levels.

### 4e. Reflect

```
/manuscript-reflect <mid>
```

**Expected**: `reflection.json` with thesis, premises, evidence chain, weakest link,
and recommended experiment.

**Full chain verification**:

```bash
cat ~/.cache/coscientist/manuscripts/<mid>/manifest.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['state'])"
```

Should print `revised` (or `critiqued` if reflect hasn't advanced state yet).

---

## Phase 5 — Reference Agent + Zotero

**Prerequisite**: Phase 2f (Zotero) passed.

### 5a. Sync a paper to Zotero

```
/reference-agent sync <canonical_id_from_3a>
```

**Expected**: paper appears in your Zotero library. Open Zotero Desktop to confirm.

### 5b. Export BibTeX

```
/reference-agent export-bib <run_id_or_mid>
```

**Expected**: `.bib` file with valid BibTeX entries.

### 5c. Retraction check

```
/reference-agent check-retractions <mid>
```

**Expected**: report listing any retracted papers in the manuscript's reference list.
(OK if none — that's the expected result for a clean draft.)

---

## Phase 6 — Personal Knowledge Layer

### 6a. Research journal

```
/research-journal add "First desktop validation run — all phases passing."
```

**Expected**: entry created in `~/.cache/coscientist/journal/`.

```bash
ls ~/.cache/coscientist/journal/
```

### 6b. Project dashboard

```
/project-dashboard
```

**Expected**: summary of active projects, recent papers, and manuscripts in flight.
On first run, will show empty/zeroed state — that's correct.

### 6c. Cross-project memory

```
/cross-project-memory "attention mechanism"
```

**Expected**: any papers/notes mentioning "attention mechanism" across all projects.
(Empty result is fine if no prior data; confirms search runs without error.)

---

## Phase 7 — Tournament

### 7a. Record a hypothesis

```
/tournament record-hypothesis "Vision transformers outperform CNNs on small medical datasets because self-attention captures global context unavailable to local convolutions."
```

**Expected**: hypothesis stored in run DB with a generated ID.

### 7b. Record a match

With two hypothesis IDs from 7a (run it twice first):

```
/tournament pairwise <h1_id> <h2_id>
```

**Expected**: pairwise judgment returned with Elo scores updated.

### 7c. Leaderboard

```
/tournament leaderboard
```

**Expected**: ranked list of hypotheses with current Elo scores.

---

## Phase 8 — End-to-End Deep Research

**This is the longest phase. Budget 30–60 minutes for a real run.**

### 8a. Resume the paused run (if applicable)

Run `aa41d0cb` was paused due to the egress proxy blocking Semantic Scholar.
If the proxy constraint is resolved:

```
/deep-research --resume aa41d0cb
```

Otherwise start a fresh narrow run (fewer papers = less API exposure):

```
/deep-research "How do vision transformers handle distribution shift compared to CNNs?" --max-papers 10
```

### 8b. Break checkpoints

The pipeline has 3 hard stops. At each break:

| Break | After agent | What to confirm |
|---|---|---|
| Break 0 | `social` | Source pool has ≥ 5 relevant papers; redirect if off-topic |
| Break 1 | `gaper` | Foundation is solid; gap map makes sense for your question |
| Break 2 | `synthesizer` | Coherence narrative is accurate; specify output format if needed |

### 8c. Final artifacts

```bash
ls ~/.cache/coscientist/runs/run-<id>/
# Expect: research_brief.md, understanding_map.md
wc -l ~/.cache/coscientist/runs/run-<id>/research_brief.md
```

**Expected**: `research_brief.md` > 500 lines, `understanding_map.md` present.

**Fail signals**:
- Sub-agent stream timeout → increase Claude Code timeout or reduce `--max-papers`.
- Sub-agent "no MCP access" → known constraint; sub-agents inherit tools from the
  outer session. Restart Claude Code with MCPs confirmed running before invoking
  `/deep-research`.
- `403` from Semantic Scholar → egress proxy still blocking; try with `SEMANTIC_SCHOLAR_API_KEY`
  set (authenticated requests may route differently).

---

## Phase 9 — Critical Judgment Subsystem (A5)

### 9a. Novelty check

```
/novelty-check <canonical_id_from_3a>
```

**Expected**: `novelty_assessment.json` in the paper artifact dir. Fields: `delta_scores`,
`prior_art[]`, `verdict` (one of: `novel`, `incremental`, `derivative`).

### 9b. Publishability check

Pick a manuscript from Phase 4:

```
/publishability-check <mid> --venue "NeurIPS"
```

**Expected**: `publishability_verdict.json` with `probability`, `up_factors[]`,
`down_factors[]`, and `kill_criterion`.

### 9c. Attack vectors

```
/attack-vectors <mid>
```

**Expected**: `attack_findings.json` with structured checklist (p-hacking, HARKing,
selective baselines, etc.), each with `severity: pass|minor|fatal` and a steelman.

---

## Validation Scorecard

Print this and tick off each phase as you go:

```
[ ] Phase 0  — Environment setup          (uv sync, claude mcp list: 7 MCPs)
[ ] Phase 1  — Local test suite            (327 tests pass)
[ ] Phase 2a — Semantic Scholar probe
[ ] Phase 2b — paper-search-mcp probe
[ ] Phase 2c — academic-mcp probe
[ ] Phase 2d — Consensus probe
[ ] Phase 2e — Playwright probe
[ ] Phase 2f — Zotero probe
[ ] Phase 2g — browser-use probe           (optional)
[ ] Phase 3a — paper-discovery
[ ] Phase 3b — paper-triage
[ ] Phase 3c — arxiv-to-markdown
[ ] Phase 3d — paper-acquire (OA path)
[ ] Phase 3e — pdf-extract
[ ] Phase 4a — manuscript ingest
[ ] Phase 4b — manuscript audit
[ ] Phase 4c — manuscript critique
[ ] Phase 4d — manuscript reflect
[ ] Phase 5  — reference-agent + Zotero
[ ] Phase 6  — personal knowledge layer
[ ] Phase 7  — tournament
[ ] Phase 8  — end-to-end deep-research
[ ] Phase 9  — critical judgment (A5)
```

**Minimum viable success**: Phases 0–4 all green = the core research loop is functional.
Phases 5–9 can be completed incrementally as you add keys and run real workloads.

---

## Known Environmental Constraints

Document any runtime constraints you discover here so they don't surprise you on the next run:

| Constraint | Symptoms | Workaround |
|---|---|---|
| Egress proxy blocks `api.semanticscholar.org` | `403 Forbidden` in S2 calls | Use `SEMANTIC_SCHOLAR_API_KEY`; authenticated calls may bypass |
| Sub-agents don't inherit MCP access | `claude mcp list` empty inside sub-agent | Start Claude Code with MCPs active before invoking `/deep-research` |
| Sub-agent stream-idle timeout | Agent dies mid-run with no output | Write output after each angle (social.md pattern); resume via `--resume` |
| Docling heavy install (~2GB) | Slow first extract | Pre-install: `uv add docling` before Phase 3e |
| Playwright needs headful display | No `DISPLAY` in SSH sessions | Run on desktop session or use `Xvfb` |
