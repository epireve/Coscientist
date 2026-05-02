# SKILL.md drift report

Audited: 117 (skill, script) pairs
With drift: 43

## Top offenders

- **debate** (`.claude/skills/debate/scripts/debate.py`): 4 undocumented — --drift-threshold, --n-rounds, --persist-db, --valid-cids
- **tournament** (`.claude/skills/tournament/scripts/tree_ranker.py`): 4 undocumented — --min-matches, --run-db, --threshold, --tree-id
- **tournament** (`.claude/skills/tournament/scripts/record_match.py`): 3 undocumented — --auto-prune, --prune-min-matches, --prune-threshold
- **audit-rotate** (`.claude/skills/audit-rotate/scripts/rotate.py`): 2 undocumented — --confirm, --older-than-days
- **calibration** (`.claude/skills/calibration/scripts/manage.py`): 2 undocumented — --cache-root, --doi
- **experiment-reproduce** (`.claude/skills/experiment-reproduce/scripts/reproduce.py`): 2 undocumented — --cpus, --image
- **field-trends-analyzer** (`.claude/skills/field-trends-analyzer/scripts/trends.py`): 2 undocumented — --buckets, --window-days
- **health** (`.claude/skills/health/scripts/health.py`): 2 undocumented — --no-alerts, --show-thresholds
- **paper-discovery** (`.claude/skills/paper-discovery/scripts/openalex_source.py`): 2 undocumented — --filter, --page
- **peer-review** (`.claude/skills/peer-review/scripts/decide.py`): 2 undocumented — --decision, --rationale
- **reference-agent** (`.claude/skills/reference-agent/scripts/enrich_authors.py`): 2 undocumented — --author-nid, --source
- **reference-agent** (`.claude/skills/reference-agent/scripts/populate_concepts.py`): 2 undocumented — --min-score, --source
- **research-journal** (`.claude/skills/research-journal/scripts/list_entries.py`): 2 undocumented — --limit, --linked-run
- **search-strategy-critique** (`.claude/skills/search-strategy-critique/scripts/gate.py`): 2 undocumented — --force, --input
- **tournament** (`.claude/skills/tournament/scripts/record_hypothesis.py`): 2 undocumented — --branch-index, --tree-root
- **venue-match** (`.claude/skills/venue-match/scripts/recommend.py`): 2 undocumented — --audience, --persist-db
- **contribution-mapper** (`.claude/skills/contribution-mapper/scripts/map.py`): 1 undocumented — --persist-db
- **dmp-generator** (`.claude/skills/dmp-generator/scripts/dmp.py`): 1 undocumented — --force
- **ethics-irb** (`.claude/skills/ethics-irb/scripts/ethics.py`): 1 undocumented — --force
- **figure-agent** (`.claude/skills/figure-agent/scripts/check_palette.py`): 1 undocumented — --colors
- **figure-agent** (`.claude/skills/figure-agent/scripts/register.py`): 1 undocumented — --overwrite
- **gap-analyzer** (`.claude/skills/gap-analyzer/scripts/analyze.py`): 1 undocumented — --persist-db
- **grant-draft** (`.claude/skills/grant-draft/scripts/draft.py`): 1 undocumented — --force
- **manuscript-ingest** (`.claude/skills/manuscript-ingest/scripts/resolve_citations.py`): 1 undocumented — --input
- **negative-results-logger** (`.claude/skills/negative-results-logger/scripts/log.py`): 1 undocumented — --force
- **paper-acquire** (`.claude/skills/paper-acquire/scripts/record.py`): 1 undocumented — --detail
- **paper-triage** (`.claude/skills/paper-triage/scripts/record.py`): 1 undocumented — --force
- **preprint-alerts** (`.claude/skills/preprint-alerts/scripts/subscribe.py`): 1 undocumented — --replace
- **publishability-check** (`.claude/skills/publishability-check/scripts/gate.py`): 1 undocumented — --allow-uncalibrated
- **reference-agent** (`.claude/skills/reference-agent/scripts/export_bibtex.py`): 1 undocumented — --context-run-id
- **reference-agent** (`.claude/skills/reference-agent/scripts/populate_citations.py`): 1 undocumented — --source
- **reference-agent** (`.claude/skills/reference-agent/scripts/reading_state.py`): 1 undocumented — --list-all
- **reproducibility-mcp** (`.claude/skills/reproducibility-mcp/scripts/sandbox.py`): 1 undocumented — --lock-timeout
- **research-journal** (`.claude/skills/research-journal/scripts/search.py`): 1 undocumented — --limit
- **resolve-citation** (`.claude/skills/resolve-citation/scripts/resolve.py`): 1 undocumented — --threshold
- **retraction-watch** (`.claude/skills/retraction-watch/scripts/alert.py`): 1 undocumented — --no-journal
- **retraction-watch** (`.claude/skills/retraction-watch/scripts/scan.py`): 1 undocumented — --input
- **reviewer-assistant** (`.claude/skills/reviewer-assistant/scripts/review.py`): 1 undocumented — --force
- **tournament** (`.claude/skills/tournament/scripts/evolve_loop.py`): 1 undocumented — --top-roots
- **tournament** (`.claude/skills/tournament/scripts/pairwise.py`): 1 undocumented — --exclude-played
- **writing-style** (`.claude/skills/writing-style/scripts/apply.py`): 1 undocumented — --text
- **writing-style** (`.claude/skills/writing-style/scripts/audit.py`): 1 undocumented — --out
- **writing-style** (`.claude/skills/writing-style/scripts/fingerprint.py`): 1 undocumented — --out

## All audits

- arxiv-to-markdown / fetch.py: OK
- attack-vectors / check.py: OK
- audit-query / query.py: OK
- audit-rotate / rotate.py: DRIFT (2)
    missing-in-md: --confirm, --older-than-days
- calibration / manage.py: DRIFT (2)
    missing-in-md: --cache-root, --doi
- citation-alerts / track.py: OK
- citation-decay / citation_decay.py: OK
- citation-format-converter / convert.py: OK
- claim-cluster / cluster_claims.py: OK
- coauthor-network / coauthor.py: OK
- contribution-mapper / map.py: DRIFT (1)
    missing-in-md: --persist-db
- credit-tracker / track.py: OK
- cross-project-memory / find_paper.py: OK
- cross-project-memory / search.py: OK
- dataset-agent / register.py: OK
- debate / debate.py: DRIFT (4)
    missing-in-md: --drift-threshold, --n-rounds, --persist-db, --valid-cids
- deep-research / db.py: OK
- deep-research / harvest.py: OK
- deep-research / overnight.py: OK
- dmp-generator / dmp.py: DRIFT (1)
    missing-in-md: --force
- ethics-irb / ethics.py: DRIFT (1)
    missing-in-md: --force
- experiment-design / design.py: OK
- experiment-reproduce / reproduce.py: DRIFT (2)
    missing-in-md: --cpus, --image
- field-trends-analyzer / trends.py: DRIFT (2)
    missing-in-md: --buckets, --window-days
- figure-agent / audit.py: OK
- figure-agent / caption.py: OK
- figure-agent / check_palette.py: DRIFT (1)
    missing-in-md: --colors
- figure-agent / list.py: OK
- figure-agent / register.py: DRIFT (1)
    missing-in-md: --overwrite
- funding-graph / funding.py: OK
- gap-analyzer / analyze.py: DRIFT (1)
    missing-in-md: --persist-db
- grant-draft / draft.py: DRIFT (1)
    missing-in-md: --force
- grant-draft / outline.py: OK
- graph-query / query.py: OK
- graph-viz / render.py: OK
- health / health.py: DRIFT (2)
    missing-in-md: --no-alerts, --show-thresholds
- idea-attacker / gate.py: OK
- institutional-access / chrome_fetch.py: OK
- manuscript-audit / gate.py: OK
- manuscript-bibtex-import / import_bib.py: OK
- manuscript-critique / gate.py: OK
- manuscript-draft / draft.py: OK
- manuscript-draft / outline.py: OK
- manuscript-draft / section.py: OK
- manuscript-format / format.py: OK
- manuscript-format / pandoc_utils.py: OK
- manuscript-ingest / ingest.py: OK
- manuscript-ingest / resolve_citations.py: DRIFT (1)
    missing-in-md: --input
- manuscript-ingest / validate_citations.py: OK
- manuscript-reflect / gate.py: OK
- manuscript-revise / review_parser.py: OK
- manuscript-revise / revise.py: OK
- manuscript-version / version.py: OK
- manuscript-version / version_store.py: OK
- meta-research / meta.py: OK
- negative-results-logger / log.py: DRIFT (1)
    missing-in-md: --force
- novelty-check / gate.py: OK
- paper-acquire / gate.py: OK
- paper-acquire / oa_via_openalex.py: OK
- paper-acquire / record.py: DRIFT (1)
    missing-in-md: --detail
- paper-discovery / merge.py: OK
- paper-discovery / openalex_source.py: DRIFT (2)
    missing-in-md: --filter, --page
- paper-triage / record.py: DRIFT (1)
    missing-in-md: --force
- pdf-extract / extract.py: OK
- pdf-extract / vision_fallback.py: OK
- peer-review / decide.py: DRIFT (2)
    missing-in-md: --decision, --rationale
- peer-review / respond.py: OK
- peer-review / review.py: OK
- peer-review / status.py: OK
- preprint-alerts / digest.py: OK
- preprint-alerts / history.py: OK
- preprint-alerts / list_subs.py: OK
- preprint-alerts / subscribe.py: DRIFT (1)
    missing-in-md: --replace
- project-dashboard / dashboard.py: OK
- project-manager / manage.py: OK
- publishability-check / gate.py: DRIFT (1)
    missing-in-md: --allow-uncalibrated
- reading-pace-analytics / pace.py: OK
- reference-agent / enrich_authors.py: DRIFT (2)
    missing-in-md: --author-nid, --source
- reference-agent / export_bibtex.py: DRIFT (1)
    missing-in-md: --context-run-id
- reference-agent / mark_retracted.py: OK
- reference-agent / populate_citations.py: DRIFT (1)
    missing-in-md: --source
- reference-agent / populate_concepts.py: DRIFT (2)
    missing-in-md: --min-score, --source
- reference-agent / reading_state.py: DRIFT (1)
    missing-in-md: --list-all
- reference-agent / sync_from_zotero.py: OK
- registered-reports / rr.py: OK
- replication-finder / find_replications.py: OK
- reproducibility-mcp / sandbox.py: DRIFT (1)
    missing-in-md: --lock-timeout
- research-eval / eval_claims.py: OK
- research-eval / eval_references.py: OK
- research-journal / add_entry.py: OK
- research-journal / list_entries.py: DRIFT (2)
    missing-in-md: --limit, --linked-run
- research-journal / search.py: DRIFT (1)
    missing-in-md: --limit
- resolve-citation / resolve.py: DRIFT (1)
    missing-in-md: --threshold
- retraction-watch / alert.py: DRIFT (1)
    missing-in-md: --no-journal
- retraction-watch / scan.py: DRIFT (1)
    missing-in-md: --input
- retraction-watch / status.py: OK
- reviewer-assistant / review.py: DRIFT (1)
    missing-in-md: --force
- search-strategy-critique / gate.py: DRIFT (2)
    missing-in-md: --force, --input
- slide-draft / slide.py: OK
- statistics / assumption_check.py: OK
- statistics / effect_size.py: OK
- statistics / meta_analysis.py: OK
- statistics / power.py: OK
- statistics / test_select.py: OK
- systematic-review / review.py: OK
- tournament / evolve_loop.py: DRIFT (1)
    missing-in-md: --top-roots
- tournament / leaderboard.py: OK
- tournament / pairwise.py: DRIFT (1)
    missing-in-md: --exclude-played
- tournament / record_hypothesis.py: DRIFT (2)
    missing-in-md: --branch-index, --tree-root
- tournament / record_match.py: DRIFT (3)
    missing-in-md: --auto-prune, --prune-min-matches, --prune-threshold
- tournament / tree_ranker.py: DRIFT (4)
    missing-in-md: --min-matches, --run-db, --threshold, --tree-id
- venue-match / recommend.py: DRIFT (2)
    missing-in-md: --audience, --persist-db
- wide-research / wide.py: OK
- writing-style / apply.py: DRIFT (1)
    missing-in-md: --text
- writing-style / audit.py: DRIFT (1)
    missing-in-md: --out
- writing-style / fingerprint.py: DRIFT (1)
    missing-in-md: --out
- zenodo-deposit / deposit.py: OK
