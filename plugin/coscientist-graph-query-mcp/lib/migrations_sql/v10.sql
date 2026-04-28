-- v0.63 — citation_resolutions: resolve-citation skill output ledger.
-- Mirrored verbatim into the canonical lib/sqlite_schema.sql.
-- v0.65a — single source of DDL.

CREATE TABLE IF NOT EXISTS citation_resolutions (
    resolution_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT,
    project_id      TEXT,
    input_text      TEXT NOT NULL,
    partial_json    TEXT NOT NULL,
    matched         INTEGER NOT NULL,
    score           REAL NOT NULL,
    threshold       REAL NOT NULL,
    canonical_id    TEXT,
    doi             TEXT,
    title           TEXT,
    year            INTEGER,
    candidate_json  TEXT,
    at              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_citres_run ON citation_resolutions(run_id);
CREATE INDEX IF NOT EXISTS idx_citres_project ON citation_resolutions(project_id);
CREATE INDEX IF NOT EXISTS idx_citres_canonical ON citation_resolutions(canonical_id);
