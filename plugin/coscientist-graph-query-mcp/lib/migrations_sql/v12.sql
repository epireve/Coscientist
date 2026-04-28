-- v0.92 — agent quality scoring.
-- One row per (run, span, agent_name, judge) tuple. Same agent
-- can be scored by multiple judges (auto-rubric + llm-judge +
-- pairwise ranker); all rows are kept.

CREATE TABLE IF NOT EXISTS agent_quality (
    quality_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT,
    span_id        TEXT,
    agent_name     TEXT NOT NULL,
    rubric_version TEXT NOT NULL,
    score_total    REAL NOT NULL,
    criteria_json  TEXT NOT NULL,
    judge          TEXT NOT NULL,                -- auto-rubric | llm-judge | ranker | user
    artifact_path  TEXT,
    reasoning      TEXT,
    notes          TEXT,
    at             TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_aq_run ON agent_quality(run_id);
CREATE INDEX IF NOT EXISTS idx_aq_agent ON agent_quality(agent_name);
CREATE INDEX IF NOT EXISTS idx_aq_judge ON agent_quality(judge);
CREATE INDEX IF NOT EXISTS idx_aq_at ON agent_quality(at);
