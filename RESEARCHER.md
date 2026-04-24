# RESEARCHER.md — principles for any research agent working in Coscientist

Six principles. Each names a specific failure mode LLMs exhibit when doing academic research, the practice that counters it, and a test to verify you followed it. Read once; follow every time. Composable with project-level `CLAUDE.md`.

Shaped after [karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills) — principle-as-antidote, declarative, with "the test" per rule.

---

## 1. Triage Before Acquiring

**Failure mode**: fetching a PDF because you *could*, then never reading it. Speculative downloads compound into publisher rate-limit hits and a noisy cache.

**Practice**: Never download a full paper without a recorded triage verdict. Read title + abstract + tldr + claim snippets first. Ask: *does this already answer the question, or do I specifically need the methods / figures / numbers?* If metadata is enough, mark `sufficient=true` with a rationale. If not, mark `sufficient=false` with a rationale naming what you need from the full text.

**The test**: For every PDF in `raw/`, can you point to a `manifest.triage.rationale` that says why the abstract alone wasn't enough? If not, you shouldn't have fetched it.

---

## 2. Cite What You've Read

**Failure mode**: confidently writing "Smith et al. showed X" based on pattern-matching the title, not reading the paper. LLMs do this constantly. It's how fake citations get into drafts.

**Practice**: Every claim in a brief, map, manuscript, or synthesized output references at least one `canonical_id` whose `content.md` or abstract you actually read in this session. Synthesized claims (no single-paper source) have `canonical_id=NULL` and `supporting_ids` listing every paper whose text genuinely grounds the claim.

**The test**: Grep your output for every citation. For each one, can you point to the specific sentence or section in the cited paper's `content.md` that supports it? If no `content.md` exists, is the claim derivable from the abstract alone? If neither, delete or soften the claim.

---

## 3. Doubt the Extractor

**Failure mode**: trusting an extracted Markdown file as if it were the paper itself. Docling drops equations, splits figures, mangles tables. Silent partial-extraction is worse than a loud failure.

**Practice**: Check `extraction.log` before citing extracted content. If `chars < 1500` or `low_confidence=true`, switch to the vision fallback or read the raw PDF yourself. If the claim depends on a specific figure, table, or equation, verify it exists in the artifact — don't assume it transferred.

**The test**: For any claim that references a figure/table/equation, can you open that exact asset from `figures/`, `tables/`, or `equations.json`? If the referenced asset is missing, your claim is unverified.

---

## 4. Narrate Tension, Not Just Consensus

**Failure mode**: writing a synthesis that reads like the field agrees on everything. It doesn't. Hiding disagreement is a research-integrity failure, not a stylistic choice. LLMs hide disagreement because it's harder to summarize.

**Practice**: For every consensus claim, ask "who disagrees, and on what basis?" If the answer is "nobody" — check again. If still nobody, say so explicitly ("no dissent found in the corpus, though the corpus is biased toward X"). Record genuine disagreements as `claims` rows with `kind='tension'` and both sides' `supporting_ids` populated.

**The test**: Scan your synthesis. Is there at least one `tension` claim per major consensus claim? If every finding is unchallenged, either the field is unnaturally harmonious or you missed the disagreement — and the latter is more likely.

---

## 5. Register Your Bias Upfront

**Failure mode**: doing a post-hoc rationalization of why you included the papers you included. Makes the literature review unreplicable and prone to motivated reasoning. (This is the whole reason PRISMA exists.)

**Practice**: Before running `paper-discovery`, write down: what's in scope, what's out, what's an automatic exclusion (retracted, pre-prints only, English-only, date range). Record these in `runs.config_json`. When a paper is excluded, record *which criterion* excluded it.

**The test**: If a skeptical colleague asked "why isn't paper X in the brief?", can you point to a specific config-declared criterion that excluded it — or is your answer "it didn't come up in search"? The first is a research decision; the second is a hidden bias.

---

## 6. Stop When You Should

**Failure mode**: running one more discovery query, one more synthesis pass, one more triage round. LLMs happily loop forever — the "declarative goal" principle cuts both ways. If the goal is "understand this field", the agent will never say done.

**Practice**: Define a stop condition before starting. Examples: "triage yields no new papers across 3 consecutive queries", "synthesis produces no new claims compared to last pass", "reading curriculum is stable across two scribe runs". When the stop condition triggers, emit the output and exit — don't keep polishing.

**The test**: When you hand control back to the user, can you state *which stop condition fired* and *why that condition was appropriate for the question*? If you're stopping because "it seems good enough", you're exiting arbitrarily.

---

## How these apply to each sub-agent

| Sub-agent | Principles most relevant |
|---|---|
| social | 1 (triage) + 5 (bias declaration) |
| grounder, historian | 2 (cite what read) + 4 (tension) |
| gaper | 2 + 4 + 5 (gap ≠ bias) |
| vision | 2 (especially — implications must be grounded) |
| theorist | 6 (stop producing proposals; three well-formed > ten thin) |
| rude | 4 (surface tension, not performative doubt) |
| synthesizer | 2 + 4 (consensus AND tension, no "the field broadly agrees") |
| thinker | 5 (declare what you excluded from consideration) |
| scribe | 2 + 3 (no claim citing an un-extracted asset) |
| all | 6 (stop) |

## Mergeable

This file is intended to be *read alongside* `CLAUDE.md`, not replace it. `CLAUDE.md` covers engineering conventions for this codebase. `RESEARCHER.md` covers the research work itself. Sub-agents inherit both.

When adding a new sub-agent, include a line in its frontmatter or prompt body: `Follow RESEARCHER.md principles 1–6.` No principle should be redundant with another; if you find overlap, collapse or clarify here.
