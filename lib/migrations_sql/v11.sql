-- v0.89 — execution traces.
-- OpenTelemetry-style span model in pure SQLite. One trace per run,
-- nested spans, attributes + events as JSON blobs.

CREATE TABLE IF NOT EXISTS traces (
    trace_id     TEXT PRIMARY KEY,
    run_id       TEXT,                                -- nullable; not every trace ties to a run
    started_at   TEXT NOT NULL,
    completed_at TEXT,
    status       TEXT NOT NULL DEFAULT 'running'     -- running | ok | error
);

CREATE TABLE IF NOT EXISTS spans (
    span_id        TEXT PRIMARY KEY,
    trace_id       TEXT NOT NULL REFERENCES traces(trace_id) ON DELETE CASCADE,
    parent_span_id TEXT,
    kind           TEXT NOT NULL,                     -- phase | sub-agent | tool-call | gate | persist | other
    name           TEXT NOT NULL,
    started_at     TEXT NOT NULL,
    ended_at       TEXT,
    duration_ms    INTEGER,
    status         TEXT NOT NULL DEFAULT 'running',   -- running | ok | error | timeout
    error_kind     TEXT,
    error_msg      TEXT,
    attrs_json     TEXT
);

CREATE TABLE IF NOT EXISTS span_events (
    event_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    span_id      TEXT NOT NULL REFERENCES spans(span_id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    payload_json TEXT,
    at           TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_parent ON spans(parent_span_id);
CREATE INDEX IF NOT EXISTS idx_span_events_span ON span_events(span_id);
CREATE INDEX IF NOT EXISTS idx_traces_run ON traces(run_id);
