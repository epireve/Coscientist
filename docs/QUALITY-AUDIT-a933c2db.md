# Quality audit — run a933c2db

_Question: "Distributed consensus algorithms for byzantine fault tolerance in heterogeneous edge computing"_
_Audit date: 2026-04-27_

## Verdict

**Research-launchpad quality**, not **research-citable quality**.

Saves a researcher days of orientation. Identifies non-obvious tensions, generates testable hypotheses, costs killer experiments. **Cannot replace** the actual literature review for a publishable paper.

## What works

| Dimension | Strength | Evidence |
|---|---|---|
| Conceptual depth | Strong | Sharpened question identifies 3 specific load-bearing assumptions worth attacking. Implications i7 (1999 adversary outdated for 2024 threats), i3 (hierarchical SPOF), i6 (permissionless requires unstated oracle) are non-obvious + falsifiable |
| Hypothesis generation | Strong | 3 architect hypotheses (consistency-tier router, 5D role-typed quorums, EdgeAdv benchmark) + 4 visionary directions (TLA+ adversary, FoundationDB-style sim, model-guided fuzzing, CCF smart-casual). Each costed (n, weeks, $) |
| Adversarial loop | Strong | Inquisitor survival 3/4/4. Killer experiments named per hypothesis. hyp-th-001 weakest link (state-dependent commutativity) testable on YCSB-A + TPC-C + smart-contract trace in 1 week |
| Structure | Strong | Brief tight + dense, cite-per-claim. Map progresses pedagogically (territory → genealogy → curriculum → concepts → unresolved → self-assessment → audit) |
| Provenance | Strong | Audit Log makes search-strategy + plan-tier + source-priority verifiable. Cross-persona disagreement scores surface high-leverage papers (PBFT 0.96) |
| v0.52 enrichment | Validated | All 6 layers fired (framework auto-selected, critique verdict=revise with 3 blind spots, 2 era inflections, "edge" velocity +0.014) |

## What fails research-grade quality

### 1. DOI coverage = 0%, orphan papers = 23/23

`eval.md` flags it: every paper cited but no PDF acquired, no full-text extraction, no real verification. Claims rest on **abstracts only**. Quoting "HotStuff -45% latency vs PBFT" without reading the paper = unverified extrapolation.

### 2. Corpus too thin

Scout flagged `thin_harvest` (23 papers < 50-paper floor). Claims like "no paper measures joules/transaction across device classes" could be wrong if 50+ more papers existed in untouched literature (embedded-systems venues, IEEE Industrial Informatics, etc.).

### 3. Synthesist implications partly speculative

- i1 "HotStuff likely consumes more joules than batched-PBFT" — falsifier listed but no paper in corpus measures this. Educated guess, not synthesis.
- i7 "1999 adversary predates wireless side-channels + firmware-supply-chain" — true but no paper in corpus addresses this gap. Researcher-flavored speculation, not corpus-grounded.

### 4. Tier-2 + Tier-3 reading curriculum bloated

Frontier tier (10 papers) includes several low-citation + duplicative IoT-PBFT variants (zheng_2025 multiple, feng_2022, fan_2021, venkatesan_2026). Should prune to 4-5 distinctive papers; rest = redundant proof-of-concept clones.

### 5. Visionary depends on un-cited prior art

4 directions reference Kukharenko HotStuff TLA+, Howard CCF, Gulcan model-guided fuzzing, FoundationDB simulation. These papers in architect's harvest but **not in pivotal-papers table**. Brief's claims rest on papers user cannot see in the deliverable.

### 6. Self-assessment Q4 leading

"Name two evaluation axes that no paper reports" — answer fed in section 4. Not Socratic; fill-in-the-blank.

## Production-grade fix path

1. **Re-run with broader scout**: Pro Consensus → 20 papers/query × 5 queries = 100 candidates. Fix cross-section coverage.
2. **Auto-trigger paper-acquire** on Tier-1 + Tier-2 (acquire ~13 PDFs).
3. **Run pdf-extract**, verify quantitative claims against full text.
4. **Re-run cartographer** with `references.json` populated → mechanical seminal detection from citation in-degree, not heuristic.
5. **Add citation-network traversal**: forward + backward citations from top-Elo seminals. Catches papers user's keyword search missed.
6. **Pivotal papers table > 10 entries** including visionary's adjacent-field imports (Kukharenko, Howard, Gulcan, FoundationDB).

## Implications for toolkit

This audit motivates **Wide Research mode** (in flight) — fan-out parallel sub-agents handle:
- 100+ paper triage (current scout caps at 50)
- Per-paper full-text extraction in parallel
- Citation-graph traversal as parallel sub-task
- One sub-agent per Tier-1 seminal → deep-read + summarize

Single-agent deep-research saturates around 20-30 papers. Wide Research scales to 100-250 items.

Also motivates **citation-graph-aware harvest** (deferred): instead of keyword-only search, surface papers via in-degree from top-Elo seminals. Beats heuristic search at finding the actual lineage.

## TL;DR

**Excellent** as literature-survey starter / hypothesis generator. **Insufficient** as final research artifact. Path to research-citable: corpus expansion + PDF acquisition + citation-graph traversal + Wide Research mode.
