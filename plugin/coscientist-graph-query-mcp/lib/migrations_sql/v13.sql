-- v0.148 — institution + funder graph node kinds.
--
-- graph_nodes.kind is TEXT, so no schema change needed for new kinds —
-- enforcement lives in lib.graph.VALID_KINDS. Same for graph_edges.relation.
-- This migration adds:
--   1. partial indexes on the new kinds for fast hub queries
--   2. partial indexes on the new relations
--   3. graph_nodes.external_ids_json — store_all_data_provided rule:
--      keep every ID a source emitted (openalex_id, ror_id, doi, arxiv_id,
--      pmid, orcid, s2_corpus_id, semanticscholar_id, mag_id, etc.)
--   4. graph_nodes.source — which source last wrote this node
--      (openalex|s2|consensus|paper-search|manual)
--
-- Idempotent: ALTER TABLE ADD COLUMN guarded in lib.migrations._ensure_v13_columns.

CREATE INDEX IF NOT EXISTS idx_graph_nodes_kind_institution
    ON graph_nodes(kind) WHERE kind = 'institution';

CREATE INDEX IF NOT EXISTS idx_graph_nodes_kind_funder
    ON graph_nodes(kind) WHERE kind = 'funder';

CREATE INDEX IF NOT EXISTS idx_graph_edges_relation_affiliated
    ON graph_edges(relation) WHERE relation = 'affiliated-with';

CREATE INDEX IF NOT EXISTS idx_graph_edges_relation_funded
    ON graph_edges(relation) WHERE relation = 'funded-by';
