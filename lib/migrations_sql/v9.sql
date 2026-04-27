-- v0.57 — persistence for v0.51-v0.56 outputs (Wide Research, debate,
-- A5 trio, mode selector, db-notify). Mirrored verbatim into the
-- canonical lib/sqlite_schema.sql. v0.65a — single source of DDL.

CREATE TABLE IF NOT EXISTS wide_runs (
    wide_run_id     TEXT PRIMARY KEY,
    parent_run_id   TEXT,
    user_query      TEXT NOT NULL,
    task_type       TEXT NOT NULL,
    n_items         INTEGER NOT NULL,
    n_sub_agents    INTEGER NOT NULL,
    estimated_dollar_cost REAL,
    estimated_total_tokens INTEGER,
    concurrency_cap INTEGER,
    plan_path       TEXT NOT NULL,
    synthesis_path  TEXT,
    aborted         INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    completed_at    TEXT
);

CREATE TABLE IF NOT EXISTS wide_sub_agents (
    sub_agent_id    TEXT PRIMARY KEY,
    wide_run_id     TEXT NOT NULL REFERENCES wide_runs(wide_run_id) ON DELETE CASCADE,
    task_type       TEXT NOT NULL,
    state           TEXT NOT NULL,
    input_item_summary TEXT,
    workspace       TEXT NOT NULL,
    result_path     TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    n_tool_calls    INTEGER,
    duration_ms     INTEGER,
    n_errors        INTEGER,
    at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS debates (
    debate_id       TEXT PRIMARY KEY,
    run_id          TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
    topic           TEXT NOT NULL,
    target_id       TEXT NOT NULL,
    target_claim    TEXT NOT NULL,
    verdict         TEXT NOT NULL,
    delta           REAL NOT NULL,
    kill_criterion  TEXT NOT NULL,
    pro_mean        REAL,
    con_mean        REAL,
    transcript_path TEXT NOT NULL,
    at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gap_analyses (
    analysis_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
    gap_id          TEXT NOT NULL,
    kind            TEXT NOT NULL,
    real_or_artifact TEXT NOT NULL,
    addressable     INTEGER NOT NULL,
    publishability_tier TEXT NOT NULL,
    expected_difficulty TEXT NOT NULL,
    adjacent_field_analogues_json TEXT,
    reasoning       TEXT,
    at              TEXT NOT NULL,
    UNIQUE(run_id, gap_id)
);

CREATE TABLE IF NOT EXISTS venue_recommendations (
    rec_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    manuscript_id   TEXT,
    run_id          TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
    venue_name      TEXT NOT NULL,
    venue_type      TEXT NOT NULL,
    venue_tier      TEXT NOT NULL,
    score           REAL NOT NULL,
    rank            INTEGER NOT NULL,
    reasons_for_json TEXT,
    reasons_against_json TEXT,
    at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contribution_landscapes (
    landscape_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    manuscript_id   TEXT,
    run_id          TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
    contribution_label TEXT NOT NULL,
    method_distance REAL NOT NULL,
    domain_distance REAL NOT NULL,
    finding_distance REAL,
    closest_anchor_canonical_id TEXT,
    method_tokens_json TEXT,
    domain_tokens_json TEXT,
    finding_tokens_json TEXT,
    at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mode_selections (
    selection_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_query      TEXT NOT NULL,
    n_items         INTEGER NOT NULL,
    selected_mode   TEXT NOT NULL,
    confidence      REAL NOT NULL,
    explicit_override INTEGER NOT NULL DEFAULT 0,
    reasoning       TEXT,
    warnings_json   TEXT,
    at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS db_writes (
    write_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    target_table    TEXT NOT NULL,
    n_rows          INTEGER NOT NULL,
    skill_or_lib    TEXT NOT NULL,
    run_id          TEXT,
    detail          TEXT,
    at              TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_wide_sub_run ON wide_sub_agents(wide_run_id);
CREATE INDEX IF NOT EXISTS idx_debates_run ON debates(run_id);
CREATE INDEX IF NOT EXISTS idx_gaps_run ON gap_analyses(run_id);
CREATE INDEX IF NOT EXISTS idx_venue_recs_ms ON venue_recommendations(manuscript_id);
CREATE INDEX IF NOT EXISTS idx_landscapes_ms ON contribution_landscapes(manuscript_id);
CREATE INDEX IF NOT EXISTS idx_db_writes_at ON db_writes(at);
CREATE INDEX IF NOT EXISTS idx_db_writes_table ON db_writes(target_table);
