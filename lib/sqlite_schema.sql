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
    understanding_map TEXT
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
