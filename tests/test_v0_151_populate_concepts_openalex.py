"""v0.151 — populate_concepts OpenAlex topics ingestion."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Make the script importable as a module so we can call its functions.
_SCRIPT_DIR = _REPO_ROOT / ".claude/skills/reference-agent/scripts"
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import populate_concepts  # noqa: E402

from lib import project as project_mod  # noqa: E402
from lib.cache import paper_dir  # noqa: E402
from lib.project import (  # noqa: E402
    create as create_project,
    project_db_path,
    register_artifact,
)
from tests.harness import TestCase, isolated_cache, run_tests  # noqa: E402


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _write_manifest(cid: str, *, doi: str | None = None,
                    openalex_id: str | None = None) -> Path:
    p = paper_dir(cid)
    manifest = {
        "canonical_id": cid,
        "state": "triaged",
        "doi": doi,
        "openalex_id": openalex_id,
    }
    (p / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return p


def _register_paper(pid: str, cid: str) -> None:
    register_artifact(pid, cid, "paper", "triaged", paper_dir(cid))


def _make_work(topics):
    return {"id": "https://openalex.org/W12345", "topics": topics}


def _topic(name, score, subfield=None, field=None, domain=None,
           tid="T1", wikidata_id=None):
    t: dict = {
        "id": f"https://openalex.org/{tid}",
        "display_name": name,
        "score": score,
    }
    if wikidata_id:
        t["wikidata_id"] = wikidata_id
    if subfield:
        t["subfield"] = {
            "id": f"https://openalex.org/SF_{subfield}",
            "display_name": subfield,
        }
    if field:
        t["field"] = {
            "id": f"https://openalex.org/F_{field}",
            "display_name": field,
        }
    if domain:
        t["domain"] = {
            "id": f"https://openalex.org/D_{domain}",
            "display_name": domain,
        }
    return t


class _StubClient:
    """Stub OpenAlexClient — get_work returns whatever the test queues."""

    def __init__(self, by_lookup: dict):
        self.by_lookup = by_lookup
        self.calls: list[str] = []

    def get_work(self, lookup: str) -> dict:
        self.calls.append(lookup)
        if lookup in self.by_lookup:
            return self.by_lookup[lookup]
        # OpenAlex client normalizes raw DOIs by prefixing "doi:"
        for k, v in self.by_lookup.items():
            if k.endswith(lookup) or lookup.endswith(k):
                return v
        return {"error": f"not found: {lookup}"}


# ---------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------

class IngestTopicsTests(TestCase):
    def test_basic_topic_ingest_with_score_filter(self):
        with isolated_cache():
            pid = create_project(name="t", question="q")
            cid = "smith_2024_paper_abc123"
            _write_manifest(cid, openalex_id="W777")
            _register_paper(pid, cid)
            work = _make_work([
                _topic("Transformer Architectures", 0.95,
                       subfield="Machine Learning",
                       field="Computer Science",
                       domain="Physical Sciences",
                       tid="T11636"),
                _topic("Cooking Recipes", 0.20,
                       subfield="Food Science",
                       field="Agriculture",
                       domain="Life Sciences",
                       tid="T999"),
            ])
            client = _StubClient({"W777": work})
            res = populate_concepts.populate_from_openalex(
                pid, paper_id=cid, min_score=0.5, client=client,
            )
            self.assertEqual(res["papers_processed"], 1)
            self.assertEqual(res["topics_seen"], 1)
            # Topic + 3 hierarchy levels = 4 concept nodes
            self.assertEqual(res["concepts_added"], 4)
            # paper->topic about + 3 depends-on edges = 4 edges
            self.assertEqual(res["edges_added"], 4)

            con = sqlite3.connect(project_db_path(pid))
            nodes = {
                r[0]: r[1] for r in con.execute(
                    "SELECT node_id, label FROM graph_nodes WHERE kind='concept'"
                )
            }
            self.assertIn("concept:transformer-architectures", nodes)
            self.assertIn("concept:machine-learning", nodes)
            self.assertIn("concept:computer-science", nodes)
            self.assertIn("concept:physical-sciences", nodes)
            self.assertNotIn("concept:cooking-recipes", nodes)

            # Validate paper->topic edge weight
            row = con.execute(
                "SELECT relation, weight FROM graph_edges "
                "WHERE from_node=? AND to_node=?",
                (f"paper:{cid}", "concept:transformer-architectures"),
            ).fetchone()
            con.close()
            self.assertEqual(row[0], "about")
            self.assertTrue(abs(row[1] - 0.95) < 1e-6)

    def test_hierarchy_edges_are_depends_on(self):
        with isolated_cache():
            pid = create_project(name="t2", question="q")
            cid = "doe_2023_x_xxxxxx"
            _write_manifest(cid, openalex_id="W001")
            _register_paper(pid, cid)
            work = _make_work([
                _topic("Topic A", 0.9, subfield="SF", field="F", domain="D"),
            ])
            client = _StubClient({"W001": work})
            populate_concepts.populate_from_openalex(
                pid, paper_id=cid, client=client,
            )
            con = sqlite3.connect(project_db_path(pid))
            # topic depends-on subfield
            r1 = con.execute(
                "SELECT 1 FROM graph_edges WHERE from_node=? AND to_node=? "
                "AND relation='depends-on'",
                ("concept:topic-a", "concept:sf"),
            ).fetchone()
            r2 = con.execute(
                "SELECT 1 FROM graph_edges WHERE from_node=? AND to_node=? "
                "AND relation='depends-on'",
                ("concept:sf", "concept:f"),
            ).fetchone()
            r3 = con.execute(
                "SELECT 1 FROM graph_edges WHERE from_node=? AND to_node=? "
                "AND relation='depends-on'",
                ("concept:f", "concept:d"),
            ).fetchone()
            con.close()
            self.assertIsNotNone(r1)
            self.assertIsNotNone(r2)
            self.assertIsNotNone(r3)

    def test_idempotent_rerun(self):
        with isolated_cache():
            pid = create_project(name="t3", question="q")
            cid = "y_2024_z_aaaaaa"
            _write_manifest(cid, openalex_id="W42")
            _register_paper(pid, cid)
            work = _make_work([
                _topic("Foo Bar", 0.8, subfield="SF1",
                       field="F1", domain="D1"),
            ])
            client = _StubClient({"W42": work})
            r1 = populate_concepts.populate_from_openalex(
                pid, paper_id=cid, client=client,
            )
            r2 = populate_concepts.populate_from_openalex(
                pid, paper_id=cid, client=client,
            )
            self.assertEqual(r1["concepts_added"], 4)
            self.assertEqual(r1["edges_added"], 4)
            # Second run: nothing new
            self.assertEqual(r2["concepts_added"], 0)
            self.assertEqual(r2["edges_added"], 0)
            # Topics still seen
            self.assertEqual(r2["topics_seen"], 1)

            con = sqlite3.connect(project_db_path(pid))
            n_concept = con.execute(
                "SELECT COUNT(*) FROM graph_nodes WHERE kind='concept'"
            ).fetchone()[0]
            n_edges = con.execute(
                "SELECT COUNT(*) FROM graph_edges"
            ).fetchone()[0]
            con.close()
            self.assertEqual(n_concept, 4)
            self.assertEqual(n_edges, 4)

    def test_min_score_override(self):
        with isolated_cache():
            pid = create_project(name="t4", question="q")
            cid = "p_2022_q_bbbbbb"
            _write_manifest(cid, openalex_id="W7")
            _register_paper(pid, cid)
            work = _make_work([
                _topic("HighScore", 0.9, subfield="A",
                       field="B", domain="C"),
                _topic("MidScore", 0.4, subfield="A",
                       field="B", domain="C"),
                _topic("LowScore", 0.1, subfield="A",
                       field="B", domain="C"),
            ])
            client = _StubClient({"W7": work})
            # Default min_score=0.5 keeps only HighScore
            r1 = populate_concepts.populate_from_openalex(
                pid, paper_id=cid, client=client,
            )
            self.assertEqual(r1["topics_seen"], 1)

        with isolated_cache():
            pid = create_project(name="t4b", question="q")
            cid = "p_2022_q_bbbbbb"
            _write_manifest(cid, openalex_id="W7")
            _register_paper(pid, cid)
            work = _make_work([
                _topic("HighScore", 0.9, subfield="A",
                       field="B", domain="C"),
                _topic("MidScore", 0.4, subfield="A",
                       field="B", domain="C"),
                _topic("LowScore", 0.1, subfield="A",
                       field="B", domain="C"),
            ])
            client = _StubClient({"W7": work})
            # Lower threshold pulls MidScore in too
            r2 = populate_concepts.populate_from_openalex(
                pid, paper_id=cid, min_score=0.3, client=client,
            )
            self.assertEqual(r2["topics_seen"], 2)

    def test_missing_manifest_skipped(self):
        with isolated_cache():
            pid = create_project(name="t5", question="q")
            # Note: do NOT write manifest
            cid = "ghost_1999_x_cccccc"
            res = populate_concepts.populate_from_openalex(
                pid, paper_id=cid, client=_StubClient({}),
            )
            self.assertEqual(res["papers_processed"], 0)
            self.assertEqual(len(res["papers_skipped"]), 1)
            self.assertEqual(
                res["papers_skipped"][0]["reason"], "missing manifest",
            )

    def test_missing_project_returns_error(self):
        with isolated_cache():
            res = populate_concepts.populate_from_openalex(
                "no-such-project", paper_id="x", client=_StubClient({}),
            )
            self.assertIn("error", res)

    def test_external_ids_persisted(self):
        with isolated_cache():
            pid = create_project(name="t6", question="q")
            cid = "x_2024_y_dddddd"
            _write_manifest(cid, openalex_id="W101")
            _register_paper(pid, cid)
            work = _make_work([
                _topic("Quantum Foo", 0.9, subfield="QM",
                       field="Physics", domain="Sciences",
                       tid="T11636"),
            ])
            client = _StubClient({"W101": work})
            populate_concepts.populate_from_openalex(
                pid, paper_id=cid, client=client,
            )
            con = sqlite3.connect(project_db_path(pid))
            row = con.execute(
                "SELECT external_ids_json, source FROM graph_nodes "
                "WHERE node_id=?",
                ("concept:quantum-foo",),
            ).fetchone()
            con.close()
            self.assertIsNotNone(row)
            ext = json.loads(row[0])
            self.assertEqual(ext["openalex_id"], "T11636")
            self.assertEqual(row[1], "openalex")

    def test_batch_all_papers_in_project(self):
        with isolated_cache():
            pid = create_project(name="t7", question="q")
            for n, oa in [("a_2024_t1_eeeee1", "W1"),
                          ("b_2024_t2_eeeee2", "W2")]:
                _write_manifest(n, openalex_id=oa)
                _register_paper(pid, n)
            client = _StubClient({
                "W1": _make_work([_topic(
                    "T One", 0.9, subfield="SF", field="F", domain="D",
                )]),
                "W2": _make_work([_topic(
                    "T Two", 0.9, subfield="SF", field="F", domain="D",
                )]),
            })
            res = populate_concepts.populate_from_openalex(
                pid, paper_id=None, client=client,
            )
            self.assertEqual(res["papers_processed"], 2)
            # T One + T Two both share same SF/F/D hierarchy
            # → 2 unique topics + 3 shared hierarchy = 5 concepts
            self.assertEqual(res["concepts_added"], 5)

    def test_no_openalex_or_doi_in_manifest_skipped(self):
        with isolated_cache():
            pid = create_project(name="t8", question="q")
            cid = "z_2024_t_ffffff"
            # Manifest with neither openalex_id nor doi
            p = paper_dir(cid)
            (p / "manifest.json").write_text(json.dumps({
                "canonical_id": cid, "state": "triaged",
            }))
            _register_paper(pid, cid)
            res = populate_concepts.populate_from_openalex(
                pid, paper_id=cid, client=_StubClient({}),
            )
            self.assertEqual(res["papers_processed"], 0)
            self.assertEqual(
                res["papers_skipped"][0]["reason"],
                "no openalex_id or doi",
            )

    def test_doi_lookup_fallback(self):
        with isolated_cache():
            pid = create_project(name="t9", question="q")
            cid = "d_2024_t_gggggg"
            _write_manifest(cid, doi="10.1234/foo")
            _register_paper(pid, cid)
            work = _make_work([
                _topic("DoiTopic", 0.9, subfield="A",
                       field="B", domain="C"),
            ])
            # Stub returns work for the DOI lookup string
            client = _StubClient({"10.1234/foo": work})
            res = populate_concepts.populate_from_openalex(
                pid, paper_id=cid, client=client,
            )
            self.assertEqual(res["papers_processed"], 1)
            self.assertEqual(client.calls, ["10.1234/foo"])


class ClaimsBackcompatTests(TestCase):
    """v0.151 must preserve the original claims-source behavior."""

    def test_populate_alias_still_works(self):
        # populate() is the legacy entry point; should still exist
        self.assertTrue(callable(populate_concepts.populate))

    def test_claims_source_handles_missing_run_db(self):
        with isolated_cache():
            pid = create_project(name="bc1", question="q")
            res = populate_concepts.populate_from_claims("no-run", pid)
            self.assertIn("error", res)


class CLITests(TestCase):
    def test_help_shows_source_flag(self):
        import subprocess
        result = subprocess.run(
            [sys.executable,
             str(_SCRIPT_DIR / "populate_concepts.py"), "--help"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--source", result.stdout)
        self.assertIn("openalex", result.stdout)
        self.assertIn("--min-score", result.stdout)
        self.assertIn("--paper-id", result.stdout)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        IngestTopicsTests, ClaimsBackcompatTests, CLITests,
    ))
