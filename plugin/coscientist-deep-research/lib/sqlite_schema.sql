-- Deep-research run log. One SQLite DB per run at ~/.cache/coscientist/runs/run-<id>.db.
-- Modeled on SEEKER's 11-table audit trail. Resumable: replay phases where completed_at IS NULL.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS runs (
    run_id         TEXT PRIMARY KEY,
    question       TEXT NOT NULL,
    started_at     TEXT NOT NULL,
    completed_at   TEXT,
    status         TEXT NOT NULL DEFAULT 'running',  -- running|paused|completed|failed
    config_json    TEXT,
    final_brief    TEXT,
    understanding_map TEXT,
    search_strategy_json TEXT,  -- v0.52.1 — framework + sub-area decomposition (lib/search_framework.py)
    strategy_critique_json TEXT  -- v0.52.2 — adversarial critique of search strategy (search-strategy-critique skill)
);

CREATE TABLE IF NOT EXISTS phases (
    phase_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    name           TEXT NOT NULL,                      -- social|grounder|... |scribe
    ordinal        INTEGER NOT NULL,
    started_at     TEXT,
    completed_at   TEXT,
    output_json    TEXT,
    error          TEXT,
    UNIQUE(run_id, ordinal)
);

CREATE TABLE IF NOT EXISTS agents (
    agent_run_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id       INTEGER NOT NULL REFERENCES phases(phase_id) ON DELETE CASCADE,
    agent_name     TEXT NOT NULL,
    prompt         TEXT,
    response       TEXT,
    tokens_in      INTEGER,
    tokens_out     INTEGER,
    started_at     TEXT,
    completed_at   TEXT
);

CREATE TABLE IF NOT EXISTS queries (
    query_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id       INTEGER NOT NULL REFERENCES phases(phase_id) ON DELETE CASCADE,
    mcp            TEXT NOT NULL,                      -- consensus|paper_search|academic|s2
    query          TEXT NOT NULL,
    filters_json   TEXT,
    result_count   INTEGER,
    at             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS papers_in_run (
    run_id         TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    canonical_id   TEXT NOT NULL,
    added_in_phase TEXT NOT NULL,
    role           TEXT,                                -- seed|seminal|supporting|novel|rebuttal
    notes          TEXT,
    harvest_count  INTEGER NOT NULL DEFAULT 1,          -- v0.50.4 — repeat-hit signal across personas
    cites_per_year REAL,                                -- v0.50.4 — cheap importance heuristic
    PRIMARY KEY (run_id, canonical_id)
);

CREATE TABLE IF NOT EXISTS claims (
    claim_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    canonical_id   TEXT,                                -- NULL = agent-synthesized, not attributed
    agent_name     TEXT,
    text           TEXT NOT NULL,
    kind           TEXT,                                -- finding|hypothesis|gap|tension|dead_end
    confidence     REAL,
    supporting_ids TEXT                                 -- JSON array of canonical_ids
);

CREATE TABLE IF NOT EXISTS citations (
    citation_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    from_canonical TEXT,
    to_canonical   TEXT,
    context        TEXT
);

CREATE TABLE IF NOT EXISTS breaks (
    break_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    break_number   INTEGER NOT NULL,                    -- 0, 1, 2
    prompted_at    TEXT NOT NULL,
    resolved_at    TEXT,
    user_input     TEXT
);

CREATE TABLE IF NOT EXISTS notes (
    note_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    phase_id       INTEGER REFERENCES phases(phase_id) ON DELETE SET NULL,
    author         TEXT NOT NULL,                       -- agent name or 'user'
    text           TEXT NOT NULL,
    at             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    kind           TEXT NOT NULL,                       -- brief|map|export|log
    path           TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
    audit_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
    at             TEXT NOT NULL,
    action         TEXT NOT NULL,                       -- fetch|download|extract|error
    canonical_id   TEXT,
    tier           TEXT,                                -- oa|institutional|tier2|...
    detail         TEXT
);

CREATE INDEX IF NOT EXISTS idx_phases_run    ON phases(run_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_papers_run    ON papers_in_run(run_id);
CREATE INDEX IF NOT EXISTS idx_claims_run    ON claims(run_id);
CREATE INDEX IF NOT EXISTS idx_audit_run     ON audit(run_id, at);

-- -----------------------------------------------------------------------
-- Tier A5: critical-judgment tables
-- -----------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS novelty_assessments (
    assessment_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
    target_canonical_id TEXT NOT NULL,        -- paper or manuscript ID being assessed
    contribution_id     TEXT NOT NULL,        -- contrib-1, contrib-2, ...
    verdict             TEXT NOT NULL,        -- novel|incremental|not-novel
    confidence          REAL NOT NULL,
    anchor_count        INTEGER NOT NULL,
    report_json         TEXT NOT NULL,        -- full per-contribution structure
    at                  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS publishability_verdicts (
    verdict_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
    manuscript_id       TEXT NOT NULL,
    venue               TEXT NOT NULL,
    verdict             TEXT NOT NULL,        -- accept|borderline-with-revisions|reject
    probability         REAL NOT NULL,
    kill_criterion      TEXT NOT NULL,
    report_json         TEXT NOT NULL,        -- full per-venue structure incl factors
    at                  TEXT NOT NULL,
    UNIQUE(manuscript_id, venue, at)
);

CREATE TABLE IF NOT EXISTS attack_findings (
    finding_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
    target_canonical_id TEXT NOT NULL,
    attack              TEXT NOT NULL,        -- p-hacking|harking|...
    severity            TEXT NOT NULL,        -- pass|minor|fatal
    evidence            TEXT,
    steelman            TEXT,                 -- required for fatal
    at                  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hypotheses (
    hyp_id              TEXT PRIMARY KEY,     -- e.g. hyp-<short-uuid>
    run_id              TEXT REFERENCES runs(run_id) ON DELETE CASCADE,
    agent_name          TEXT NOT NULL,        -- theorist|thinker|evolver
    gap_ref             TEXT,                 -- id of a gap this addresses
    parent_hyp_id       TEXT REFERENCES hypotheses(hyp_id) ON DELETE SET NULL,
    statement           TEXT NOT NULL,
    method_sketch       TEXT,
    predicted_observables TEXT,               -- JSON array
    falsifiers          TEXT,                 -- JSON array
    supporting_ids      TEXT,                 -- JSON array of canonical_ids
    elo                 REAL DEFAULT 1200.0,
    n_matches           INTEGER DEFAULT 0,
    n_wins              INTEGER DEFAULT 0,
    n_losses            INTEGER DEFAULT 0,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tournament_matches (
    match_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT REFERENCES runs(run_id) ON DELETE CASCADE,
    hyp_a               TEXT NOT NULL REFERENCES hypotheses(hyp_id),
    hyp_b               TEXT NOT NULL REFERENCES hypotheses(hyp_id),
    winner              TEXT NOT NULL,        -- hyp_id of winner, or 'draw'
    judge_reasoning     TEXT,
    at                  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_novelty_target   ON novelty_assessments(target_canonical_id);
CREATE INDEX IF NOT EXISTS idx_publish_ms       ON publishability_verdicts(manuscript_id);
CREATE INDEX IF NOT EXISTS idx_attack_target    ON attack_findings(target_canonical_id);
CREATE INDEX IF NOT EXISTS idx_hyp_run          ON hypotheses(run_id);
CREATE INDEX IF NOT EXISTS idx_hyp_elo          ON hypotheses(elo DESC);

-- v0.38: tournament evolve-loop round ledger
CREATE TABLE IF NOT EXISTS evolution_rounds (
    round_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    round_index     INTEGER NOT NULL,
    top_hyp_id      TEXT,
    top_elo         REAL,
    n_hypotheses    INTEGER NOT NULL,
    n_matches       INTEGER NOT NULL,
    n_new_children  INTEGER NOT NULL DEFAULT 0,
    plateau_count   INTEGER NOT NULL DEFAULT 0,
    started_at      TEXT NOT NULL,
    closed_at       TEXT,
    UNIQUE(run_id, round_index)
);
CREATE INDEX IF NOT EXISTS idx_evo_rounds_run    ON evolution_rounds(run_id);

-- -----------------------------------------------------------------------
-- Structural refactor: project container + polymorphic artifacts + graph
-- -----------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS projects (
    project_id          TEXT PRIMARY KEY,     -- slugified name + short hash
    name                TEXT NOT NULL,
    question            TEXT,                 -- overarching research question
    description         TEXT,
    style_profile_path  TEXT,                 -- writing-style fingerprint file
    calibration_path    TEXT,                 -- calibration set location
    zotero_collection   TEXT,                 -- Zotero collection key
    created_at          TEXT NOT NULL,
    archived_at         TEXT
);

-- Projects → runs. A run optionally belongs to a project (nullable).
ALTER TABLE runs ADD COLUMN project_id TEXT REFERENCES projects(project_id) ON DELETE SET NULL;

-- Polymorphic artifact index. The paper-artifact directory contract stays
-- on disk at ~/.cache/coscientist/<kind>/<id>/. This table indexes every
-- known artifact regardless of kind for cross-project queries.
CREATE TABLE IF NOT EXISTS artifact_index (
    artifact_id         TEXT PRIMARY KEY,     -- canonical_id or manuscript_id or experiment_id
    kind                TEXT NOT NULL,        -- paper|manuscript|experiment|dataset|figure|review|grant|journal-entry|protocol
    project_id          TEXT REFERENCES projects(project_id) ON DELETE SET NULL,
    state               TEXT NOT NULL,        -- kind-specific state machine value
    path                TEXT NOT NULL,        -- filesystem path to artifact root
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

-- Graph adjacency layer. Nodes reference artifacts (or free-standing
-- concepts / authors). Edges have a label that identifies the semantics.
CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id             TEXT PRIMARY KEY,     -- typed: paper:<cid> | concept:<slug> | author:<s2_id> | manuscript:<mid>
    kind                TEXT NOT NULL,        -- paper|concept|author|manuscript|experiment|topic
    label               TEXT NOT NULL,        -- human-readable
    data_json           TEXT,                 -- optional structured payload
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS graph_edges (
    edge_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    from_node           TEXT NOT NULL REFERENCES graph_nodes(node_id) ON DELETE CASCADE,
    to_node             TEXT NOT NULL REFERENCES graph_nodes(node_id) ON DELETE CASCADE,
    relation            TEXT NOT NULL,        -- cites|cited-by|extends|refutes|uses|depends-on|coauthored|about|authored-by|in-project
    weight              REAL DEFAULT 1.0,
    data_json           TEXT,                 -- context snippet, quote, etc.
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_artifact_kind    ON artifact_index(kind);
CREATE INDEX IF NOT EXISTS idx_artifact_project ON artifact_index(project_id);
CREATE INDEX IF NOT EXISTS idx_edges_from       ON graph_edges(from_node, relation);
CREATE INDEX IF NOT EXISTS idx_edges_to         ON graph_edges(to_node, relation);

-- -----------------------------------------------------------------------
-- Tier A1: manuscript subsystem
-- -----------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS manuscript_claims (
    mclaim_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    manuscript_id   TEXT NOT NULL,
    claim_id        TEXT NOT NULL,          -- stable within manuscript (c-1, c-2, ...)
    text            TEXT NOT NULL,          -- verbatim from source
    location        TEXT NOT NULL,          -- e.g. "§3.2 ¶2" or line number
    cited_sources   TEXT NOT NULL,          -- JSON array of canonical_ids (may be [])
    at              TEXT NOT NULL,
    UNIQUE(manuscript_id, claim_id)
);

CREATE TABLE IF NOT EXISTS manuscript_audit_findings (
    finding_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    manuscript_id   TEXT NOT NULL,
    claim_id        TEXT NOT NULL,          -- FK-ish: matches manuscript_claims.claim_id
    kind            TEXT NOT NULL,          -- overclaim|uncited|unsupported|outdated|retracted
    severity        TEXT NOT NULL,          -- info|minor|major
    evidence        TEXT NOT NULL,
    at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS manuscript_critique_findings (
    finding_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    manuscript_id   TEXT NOT NULL,
    reviewer        TEXT NOT NULL,          -- methodological|theoretical|big_picture|nitpicky
    severity        TEXT NOT NULL,          -- fatal|major|minor
    location        TEXT NOT NULL,
    issue           TEXT NOT NULL,
    suggested_fix   TEXT,
    steelman        TEXT,                   -- required when severity=fatal
    at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS manuscript_reflections (
    reflection_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    manuscript_id   TEXT NOT NULL,
    thesis          TEXT NOT NULL,
    weakest_link    TEXT NOT NULL,
    one_experiment  TEXT NOT NULL,
    report_json     TEXT NOT NULL,          -- full nested structure
    at              TEXT NOT NULL,
    UNIQUE(manuscript_id, at)
);

CREATE INDEX IF NOT EXISTS idx_mclaim_ms         ON manuscript_claims(manuscript_id);
CREATE INDEX IF NOT EXISTS idx_maudit_ms         ON manuscript_audit_findings(manuscript_id);
CREATE INDEX IF NOT EXISTS idx_mcritique_ms      ON manuscript_critique_findings(manuscript_id, reviewer);
CREATE INDEX IF NOT EXISTS idx_mreflect_ms       ON manuscript_reflections(manuscript_id);

-- -----------------------------------------------------------------------
-- Tier A2: reference agent (Zotero sync + reading state + retraction flags)
-- -----------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS reading_state (
    state_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_id    TEXT NOT NULL,
    project_id      TEXT REFERENCES projects(project_id) ON DELETE SET NULL,
    state           TEXT NOT NULL,   -- to-read|reading|read|annotated|cited|skipped
    notes           TEXT,
    updated_at      TEXT NOT NULL,
    UNIQUE(canonical_id, project_id)
);

CREATE TABLE IF NOT EXISTS retraction_flags (
    flag_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_id    TEXT NOT NULL UNIQUE,
    retracted       INTEGER NOT NULL,  -- 0|1
    source          TEXT NOT NULL,     -- semantic-scholar|retraction-watch|manual
    detail          TEXT,
    checked_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS zotero_links (
    link_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_id    TEXT NOT NULL UNIQUE,
    zotero_key      TEXT NOT NULL,
    zotero_library  TEXT,              -- library identifier
    synced_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_readstate_project  ON reading_state(project_id, state);
CREATE INDEX IF NOT EXISTS idx_readstate_cid      ON reading_state(canonical_id);
CREATE INDEX IF NOT EXISTS idx_zotero_key         ON zotero_links(zotero_key);

-- -----------------------------------------------------------------------
-- v0.8: manuscript citation tracking for full auditability
-- -----------------------------------------------------------------------

-- Every raw citation key found in a manuscript's source, with its location
-- and optional resolution to a canonical paper. Populated at manuscript-ingest
-- time; resolved_canonical_id filled in later by resolve_citations.py or by
-- manuscript-audit when the agent matches keys to canonical_ids.
CREATE TABLE IF NOT EXISTS manuscript_citations (
    citation_row_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    manuscript_id         TEXT NOT NULL,
    citation_key          TEXT NOT NULL,        -- raw key as written, e.g. "vaswani2017"
    location              TEXT,                 -- §3 ¶2 or line number
    resolved_canonical_id TEXT,                 -- NULL until resolved
    resolution_source     TEXT,                 -- audit|semantic-scholar|manual
    at                    TEXT NOT NULL,
    UNIQUE(manuscript_id, citation_key, location)
);

CREATE INDEX IF NOT EXISTS idx_mscites_ms   ON manuscript_citations(manuscript_id);
CREATE INDEX IF NOT EXISTS idx_mscites_key  ON manuscript_citations(citation_key);
CREATE INDEX IF NOT EXISTS idx_mscites_res  ON manuscript_citations(resolved_canonical_id);

-- v0.9: bibliography entries parsed from the manuscript's reference list.
-- Used by validate_citations.py to cross-check in-text vs bib and catch
-- dangling/orphan references.
CREATE TABLE IF NOT EXISTS manuscript_references (
    ref_row_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    manuscript_id         TEXT NOT NULL,
    entry_key             TEXT,                  -- BibTeX-style key when inferrable (e.g. "vaswani2017")
    disambiguated_key     TEXT,                  -- v0.10: entry_key + a/b/c suffix when collisions exist (e.g. "wang2020a")
    raw_text              TEXT NOT NULL,         -- verbatim bib entry (may span multiple lines)
    ordinal               INTEGER NOT NULL,      -- [1], [2], ... (numeric bib order)
    doi                   TEXT,                  -- extracted if present
    title                 TEXT,                  -- extracted if inferrable
    year                  INTEGER,               -- extracted if inferrable
    resolved_canonical_id TEXT,
    at                    TEXT NOT NULL,
    UNIQUE(manuscript_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_msrefs_ms      ON manuscript_references(manuscript_id);
CREATE INDEX IF NOT EXISTS idx_msrefs_key     ON manuscript_references(entry_key);
CREATE INDEX IF NOT EXISTS idx_msrefs_disamb  ON manuscript_references(disambiguated_key);

-- -----------------------------------------------------------------------
-- Tier A4: personal knowledge layer (journal + cross-project memory)
-- -----------------------------------------------------------------------

-- Daily lab-notebook entries. Per-project but cross-project search joins
-- across projects is handled in cross-project-memory by union.
CREATE TABLE IF NOT EXISTS journal_entries (
    entry_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      TEXT REFERENCES projects(project_id) ON DELETE SET NULL,
    entry_date      TEXT NOT NULL,            -- YYYY-MM-DD (local date)
    body            TEXT NOT NULL,
    tags            TEXT,                     -- JSON array
    links           TEXT,                     -- JSON: {papers: [cid], manuscripts: [mid], runs: [rid], experiments: [eid]}
    at              TEXT NOT NULL             -- ISO timestamp
);

CREATE INDEX IF NOT EXISTS idx_journal_project ON journal_entries(project_id, entry_date);
CREATE INDEX IF NOT EXISTS idx_journal_date    ON journal_entries(entry_date);

-- -----------------------------------------------------------------------
-- Systematic review tables (v0.28)
-- -----------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS review_protocols (
    protocol_id    TEXT PRIMARY KEY,   -- slug from title
    run_id         TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
    title          TEXT NOT NULL,
    question       TEXT NOT NULL,      -- PICO or equivalent
    inclusion      TEXT NOT NULL,      -- JSON array of criteria strings
    exclusion      TEXT NOT NULL,      -- JSON array of criteria strings
    search_strings TEXT NOT NULL,      -- JSON array of query strings run
    date_range     TEXT,               -- e.g. "2015-2025"
    languages      TEXT DEFAULT '["en"]',
    created_at     TEXT NOT NULL,
    frozen_at      TEXT                -- set when screening begins; protocol immutable after
);

CREATE TABLE IF NOT EXISTS screening_decisions (
    decision_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    protocol_id    TEXT NOT NULL REFERENCES review_protocols(protocol_id) ON DELETE CASCADE,
    paper_id       TEXT NOT NULL,      -- canonical_id from paper artifact
    stage          TEXT NOT NULL CHECK(stage IN ('title_abstract','full_text')),
    decision       TEXT NOT NULL CHECK(decision IN ('include','exclude','uncertain')),
    reason         TEXT,               -- which exclusion criterion, or note
    decided_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extraction_rows (
    row_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    protocol_id    TEXT NOT NULL REFERENCES review_protocols(protocol_id) ON DELETE CASCADE,
    paper_id       TEXT NOT NULL,
    field          TEXT NOT NULL,      -- e.g. "sample_size", "effect_size", "outcome"
    value          TEXT,
    unit           TEXT,
    notes          TEXT,
    extracted_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bias_assessments (
    assessment_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    protocol_id    TEXT NOT NULL REFERENCES review_protocols(protocol_id) ON DELETE CASCADE,
    paper_id       TEXT NOT NULL,
    domain         TEXT NOT NULL,      -- e.g. "selection", "performance", "detection", "attrition", "reporting"
    rating         TEXT NOT NULL CHECK(rating IN ('low','unclear','high')),
    justification  TEXT,
    assessed_at    TEXT NOT NULL
);

-- -----------------------------------------------------------------------
-- v0.28 overnight mode
-- Migration: ALTER TABLE runs ADD COLUMN overnight INTEGER NOT NULL DEFAULT 0;
-- (applied by db.py on first use via IF NOT EXISTS check)
-- -----------------------------------------------------------------------
