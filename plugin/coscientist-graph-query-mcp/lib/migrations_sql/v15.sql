-- v0.154 — thinking-trace persistence on verdict-producing tables.
--
-- Adds `thinking_log_json TEXT` to four tables that record verdicts:
--   hypotheses, attack_findings, novelty_assessments,
--   publishability_verdicts.
--
-- Plus a partial index on hypotheses for efficient "rows that have
-- thinking" lookups.
--
-- Idempotent: ALTER TABLE ADD COLUMN guarded in
-- lib.migrations._ensure_v15_columns (SQLite has no IF NOT EXISTS for
-- ALTER). Index uses IF NOT EXISTS.

CREATE INDEX IF NOT EXISTS idx_hypotheses_has_thinking
    ON hypotheses(hyp_id) WHERE thinking_log_json IS NOT NULL;
