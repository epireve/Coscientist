# RESEARCHER Cross-Reference

Map RESEARCHER.md principles → agent personas that name them. Built by grepping `.claude/agents/*.md` for principle-name mentions. Surfaces coverage gaps — principles no agent invokes are candidates for retrofit.

## Cross-reference table

| # | Principle | Agents that reference it |
|---|---|---|
| 1 | Triage Before Acquiring | librarian, scout |
| 2 | Cite What You've Read | cartographer, chronicler, curator, diarist, drafter, indexer, librarian, steward, surveyor, synthesist, verifier, weaver |
| 3 | Doubt the Extractor | compositor, steward |
| 4 | Narrate Tension, Not Just Consensus | advocate, cartographer, chronicler, inquisitor, panel, peer-reviewer, red-team, weaver |
| 5 | Register Your Bias Upfront | curator, diarist, experimentalist, funder, scout, surveyor, visionary, wide-compare, wide-rank, wide-read, wide-screen, wide-survey, wide-triage |
| 6 | Name Five or Shut Up | architect, cartographer, debate-con, debate-pro, idea-tree-generator, mutator, novelty-auditor, peer-reviewer |
| 7 | Commit to a Number | debate-con, debate-judge, debate-pro, diviner, experimentalist, funder, mutator, novelty-auditor, panel, peer-reviewer, publishability-judge, ranker, steward, stylist, synthesist (sharpened question), verifier, watchman, weaver |
| 8 | Steelman Before You Attack | advocate, debate-con, debate-pro, inquisitor, novelty-auditor, panel, peer-reviewer, publishability-judge, ranker, red-team, reviser, wide-rank |
| 9 | Premortem Before You Commit | architect, debate-judge, diviner, experimentalist, funder, novelty-auditor, publishability-judge, surveyor, synthesist, verifier |
| 10 | State Kill Criteria in Advance | advocate, architect, debate-judge, experimentalist, novelty-auditor, publishability-judge, red-team, verifier |
| 11 | Stop When You Should | architect, cartographer, chronicler, debate-con, debate-judge, debate-pro, diviner, mutator, scout, visionary, wide-compare, wide-rank, wide-read, wide-screen, wide-survey, wide-triage |
| 12 | Draft to Communicate, Not to Sound Impressive | drafter, experimentalist, funder, peer-reviewer, reviser |

## Coverage analysis

**Well-covered.** Principles 2 (Cite), 5 (Bias), 7 (Commit), 8 (Steelman), 11 (Stop) — invoked across many personas. Reflects the workflow: every output cites, every match commits, every wide-* sub-agent registers bias and stops on quota. Healthy.

**Decently covered.** Principles 4 (Tension), 6 (Name Five), 9 (Premortem), 10 (Kill Criteria) — each cited by 8–10 personas. Cluster around critique + judgment personas. Expected.

**Sparse.** Principles 1 (Triage), 3 (Doubt Extractor), 12 (Draft) — each named by 2–5 personas only.

- **1 (Triage Before Acquiring)** — only librarian + scout. Reasonable: triage gate lives in `paper-acquire` skill, not in personas. But `paper-triage`-adjacent personas (none currently) could reference it.
- **3 (Doubt the Extractor)** — compositor + steward. Anyone reading `content.md` should reference this. **Gap candidates**: cartographer, chronicler, surveyor, synthesist all read extracted markdown but don't currently flag their dependence on it. Retrofit candidates.
- **12 (Draft to Communicate)** — 5 personas (drafter, experimentalist, funder, peer-reviewer, reviser). Strong concentration in writing personas. **Gap candidate**: weaver (synthesizes prose at end of pipeline) and steward (final-output personas) could reference it.

## Suggested retrofits

| Principle | Currently | Should also reference |
|---|---|---|
| 1 Triage | librarian, scout | paper-discovery driver agents (none named); explicit reminder in scout that triage happens later |
| 3 Doubt Extractor | compositor, steward | cartographer, chronicler, surveyor, synthesist (all consume extracted content) |
| 12 Draft | drafter, experimentalist, funder, peer-reviewer, reviser | weaver, steward (final-output personas); panel (reviewer voice) |

These are non-binding suggestions — the test is whether the principle materially changes the persona's behavior. Adding "Follow principle 12" to a persona that doesn't draft prose is noise.

## Principle source

`RESEARCHER.md` — read it for full text. Principles 1–5 are research hygiene; 6–10 are research judgment; 11 is stop-condition; 12 is communication. Numbering follows file order.
