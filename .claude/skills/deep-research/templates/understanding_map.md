# Understanding Map — {{question}}

_Run `{{run_id}}` — generated {{generated_at}}_

A six-section learning document. Work through it in order; each section assumes the previous.

---

## 1. Territory at a Glance

_A one-page orientation: what this field is, what it claims, what it argues about._

{{territory_prose}}

---

## 2. Intellectual Genealogy

_Who begat whom. The chain of ideas from the founders to the current frontier._

{{genealogy_chronology}}

---

## 3. Reading Curriculum

Three tiers. Each tier has papers + a prompt to answer after reading them.

### Tier 1 — Seminal must-reads

{{tier_1_papers}}

**Prompt after reading Tier 1:** {{tier_1_prompt}}

### Tier 2 — Bridge papers (inflection points)

{{tier_2_papers}}

**Prompt after reading Tier 2:** {{tier_2_prompt}}

### Tier 3 — Frontier

{{tier_3_papers}}

**Prompt after reading Tier 3:** {{tier_3_prompt}}

---

## 4. Conceptual Map

_How the core ideas relate. Consensus as a graph of named concepts, not a list of papers._

{{concept_map_prose}}

---

## 5. Unresolved Core

_Where the field is genuinely stuck. Gaps, tensions, and underexplored directions._

### Gaps

{{gaps_detailed}}

### Tensions

{{tensions_detailed}}

### Underexplored directions

{{thinker_directions}}

---

## 6. Self-Assessment

Answer these eight Socratic questions from memory. If you can't, your map has a hole.

1. {{q1}}
2. {{q2}}
3. {{q3}}
4. {{q4}}
5. {{q5}}
6. {{q6}}
7. {{q7}}
8. {{q8}}

---

## 7. Audit Log

_What was searched, what came back, what made it into the brief. Inspired by Consensus's official skills (April 2026): trust requires the reader can verify exactly what produced this map._

### Search summary

| Persona | Phase | MCP source priority | Queries sent | Papers received | Papers cited |
|---|---|---|---|---|---|
{{audit_search_table}}

### Counters

- **Queries sent**: {{audit_queries_sent}}
- **Papers received** (post-dedup across all harvests): {{audit_papers_received}}
- **Papers cited** in this map + brief: {{audit_papers_cited}}
- **Repeat-hit papers** (surfaced by ≥2 personas, foundational signal): {{audit_repeat_hits}}

### Failed searches / coverage gaps

{{audit_failures}}

### Plan-tier disclosure

{{audit_plan_tier}}

### Source-priority log

Every harvest used Consensus first → Semantic Scholar second → Google Scholar (paper-search MCP) third, with rate-limit fall-through. See per-persona shortlist files at `~/.cache/coscientist/runs/run-{{run_id}}/inputs/`.

---

_Every factual claim above cites at least one `canonical_id` from this run's `papers_in_run`. See `eval.md` for reference + claim audit. Regenerate with `/deep-research --resume {{run_id}}` to update._
