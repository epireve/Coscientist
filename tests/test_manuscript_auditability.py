"""v0.8 manuscript auditability tests.

Covers:
- Citation parser extracts keys from \\cite{}, [@key], [1], (Author Year)
- manuscript-ingest with --project-id writes manuscript_citations + graph nodes + cites edges
- manuscript-audit gate --project-id writes claims + findings + about edges
- manuscript-critique gate --project-id writes findings
- manuscript-reflect gate --project-id writes reflection
- resolve_citations merges unresolved → resolved in graph + updates table
"""

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (_ROOT / "lib" / "sqlite_schema.sql").read_text()

INGEST = _ROOT / ".claude/skills/manuscript-ingest/scripts/ingest.py"
RESOLVE = _ROOT / ".claude/skills/manuscript-ingest/scripts/resolve_citations.py"
AUDIT_GATE = _ROOT / ".claude/skills/manuscript-audit/scripts/gate.py"
CRITIQUE_GATE = _ROOT / ".claude/skills/manuscript-critique/scripts/gate.py"
REFLECT_GATE = _ROOT / ".claude/skills/manuscript-reflect/scripts/gate.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True, text=True)


def _run_with_input(script: Path, input_json: dict | list, *args: str) -> subprocess.CompletedProcess:
    tmp = _ROOT / "tests" / "_tmp_input.json"
    tmp.write_text(json.dumps(input_json))
    return _run(str(script), "--input", str(tmp), *args)


def _seed_project(cache_dir: Path, pid: str = "aud_project") -> str:
    p = cache_dir / "projects" / pid
    p.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p / "project.db")
    con.executescript(SCHEMA)
    con.execute(
        "INSERT INTO projects (project_id, name, created_at) VALUES (?, ?, ?)",
        (pid, "Audit Test", "2026-04-24T00:00:00Z"),
    )
    con.commit()
    con.close()
    return pid


# ---------------- citation parser ----------------

class CitationParserTests(TestCase):
    def _load(self):
        path = _ROOT / ".claude/skills/manuscript-ingest/scripts/ingest.py"
        spec = importlib.util.spec_from_file_location("ingest_mod", path)
        mod = importlib.util.module_from_spec(spec)
        # The module sits in a scripts subdir with a lazy lib import; loading
        # should not touch lib.project as long as we don't call main()
        spec.loader.exec_module(mod)
        return mod

    def test_latex_cite_extracted(self):
        mod = self._load()
        text = "# Intro\n\nTransformers \\cite{vaswani2017} beat RNNs."
        cites = mod.extract_citations(text)
        self.assertEqual(len(cites), 1)
        self.assertEqual(cites[0]["citation_key"], "vaswani2017")
        self.assertEqual(cites[0]["style"], "latex")

    def test_latex_multi_key(self):
        mod = self._load()
        text = "Attention \\cite{vaswani2017,devlin2019,brown2020} scales."
        cites = mod.extract_citations(text)
        keys = {c["citation_key"] for c in cites}
        self.assertEqual(keys, {"vaswani2017", "devlin2019", "brown2020"})

    def test_pandoc_cite_extracted(self):
        mod = self._load()
        text = "Prior work [@vaswani2017] showed attention."
        cites = mod.extract_citations(text)
        self.assertEqual(len(cites), 1)
        self.assertEqual(cites[0]["citation_key"], "vaswani2017")

    def test_numeric_cite_extracted(self):
        mod = self._load()
        text = "As shown in [1], [2,3], results hold."
        cites = mod.extract_citations(text)
        keys = {c["citation_key"] for c in cites}
        self.assertIn("[1]", keys)
        self.assertIn("[2]", keys)
        self.assertIn("[3]", keys)

    def test_author_year_cite_extracted(self):
        mod = self._load()
        text = "Prior work (Vaswani et al., 2017) introduced attention."
        cites = mod.extract_citations(text)
        self.assertTrue(any("2017" in c["citation_key"] for c in cites))

    def test_location_tracking_uses_sections(self):
        mod = self._load()
        text = (
            "# Intro\n\nFirst \\cite{a}.\n\n"
            "# Methods\n\nMore \\cite{b}.\n"
        )
        cites = mod.extract_citations(text)
        locs = {c["citation_key"]: c["location"] for c in cites}
        self.assertIn("Intro", locs["a"])
        self.assertIn("Methods", locs["b"])


# ---------------- ingest integration ----------------

class IngestGraphIntegrationTests(TestCase):
    def test_ingest_with_project_populates_graph_and_citations(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            src = cache_dir / "ms.md"
            src.write_text(
                "# Introduction\n\n"
                "Attention \\cite{vaswani2017} beats RNNs.\n\n"
                "# Methods\n\n"
                "We follow [@devlin2019] closely.\n"
            )
            r = _run(str(INGEST), "--source", str(src), "--title", "Test",
                     "--project-id", pid)
            assert r.returncode == 0, f"stderr={r.stderr}"
            mid = r.stdout.strip()

            db = cache_dir / "projects" / pid / "project.db"
            con = sqlite3.connect(db)

            # manuscript_citations table populated
            rows = con.execute(
                "SELECT citation_key, location FROM manuscript_citations "
                "WHERE manuscript_id=?", (mid,)
            ).fetchall()
            keys = {r[0] for r in rows}
            self.assertEqual(keys, {"vaswani2017", "devlin2019"})

            # manuscript node + placeholder paper nodes
            ms_node = con.execute(
                "SELECT COUNT(*) FROM graph_nodes WHERE kind='manuscript'"
            ).fetchone()[0]
            self.assertEqual(ms_node, 1)

            unresolved = con.execute(
                "SELECT COUNT(*) FROM graph_nodes "
                "WHERE kind='paper' AND node_id LIKE 'paper:unresolved:%'"
            ).fetchone()[0]
            self.assertEqual(unresolved, 2)

            # cites edges from manuscript to each placeholder
            cites = con.execute(
                "SELECT COUNT(*) FROM graph_edges WHERE relation='cites'"
            ).fetchone()[0]
            self.assertEqual(cites, 2)

            con.close()

    def test_ingest_without_project_no_graph_writes(self):
        """Non-project ingest still works but doesn't touch any graph."""
        with isolated_cache() as cache_dir:
            src = cache_dir / "ms.md"
            src.write_text("# Test\n\n\\cite{abc} body text.")
            r = _run(str(INGEST), "--source", str(src), "--title", "NP")
            assert r.returncode == 0, f"stderr={r.stderr}"
            # No project DB exists → no citation rows anywhere
            self.assertFalse((cache_dir / "projects").exists())


# ---------------- audit gate project-DB write ----------------

def _valid_audit_report(mid: str) -> dict:
    return {
        "manuscript_id": mid,
        "claims": [{
            "claim_id": "c-1",
            "text": "Transformers outperform CNNs [@vaswani2017].",
            "location": "§2 ¶1",
            "cited_sources": ["vaswani_2017_attention_abc"],
            "findings": [{
                "kind": "overclaim", "severity": "minor",
                "evidence": "Vaswani 2017 §4.2 shows parity, not outperformance."
            }]
        }]
    }


class AuditGateProjectDbTests(TestCase):
    def test_audit_with_project_id_writes_to_project_db(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            mid = "test_ms_aud"
            report = _valid_audit_report(mid)
            r = _run_with_input(AUDIT_GATE, report,
                                "--manuscript-id", mid, "--project-id", pid)
            assert r.returncode == 0, f"stderr={r.stderr}"

            db = cache_dir / "projects" / pid / "project.db"
            con = sqlite3.connect(db)
            n_claims = con.execute(
                "SELECT COUNT(*) FROM manuscript_claims WHERE manuscript_id=?", (mid,)
            ).fetchone()[0]
            n_findings = con.execute(
                "SELECT COUNT(*) FROM manuscript_audit_findings WHERE manuscript_id=?", (mid,)
            ).fetchone()[0]
            con.close()
            self.assertEqual(n_claims, 1)
            self.assertEqual(n_findings, 1)

    def test_audit_adds_about_edges_in_project_graph(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            mid = "test_ms_edges"
            report = _valid_audit_report(mid)
            _run_with_input(AUDIT_GATE, report,
                            "--manuscript-id", mid, "--project-id", pid)

            db = cache_dir / "projects" / pid / "project.db"
            con = sqlite3.connect(db)
            # Concept node for the claim
            n_concept = con.execute(
                "SELECT COUNT(*) FROM graph_nodes WHERE kind='concept'"
            ).fetchone()[0]
            # about edges: manuscript→concept + concept→paper = 2
            n_about = con.execute(
                "SELECT COUNT(*) FROM graph_edges WHERE relation='about'"
            ).fetchone()[0]
            con.close()
            self.assertEqual(n_concept, 1)
            self.assertEqual(n_about, 2)

    def test_audit_with_both_run_id_and_project_id_writes_both(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            # Seed a run DB
            run_id = "r1"
            run_db = cache_dir / "runs" / f"run-{run_id}.db"
            run_db.parent.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(run_db)
            con.executescript(SCHEMA)
            con.execute(
                "INSERT INTO runs (run_id, question, started_at) "
                "VALUES (?, 'q', '2026-04-24T00:00:00Z')", (run_id,))
            con.commit()
            con.close()

            mid = "test_ms_both"
            report = _valid_audit_report(mid)
            r = _run_with_input(AUDIT_GATE, report,
                                "--manuscript-id", mid,
                                "--run-id", run_id, "--project-id", pid)
            assert r.returncode == 0, f"stderr={r.stderr}"

            # Both DBs should have the claim
            for db in (run_db, cache_dir / "projects" / pid / "project.db"):
                con = sqlite3.connect(db)
                n = con.execute(
                    "SELECT COUNT(*) FROM manuscript_claims WHERE manuscript_id=?",
                    (mid,),
                ).fetchone()[0]
                con.close()
                self.assertEqual(n, 1, f"missing claim in {db}")


# ---------------- critique/reflect project DB ----------------

def _valid_critique_report(mid: str) -> dict:
    return {
        "manuscript_id": mid,
        "reviewers": {
            "methodological": {"findings": [{
                "id": "m-1", "severity": "minor", "location": "§4",
                "issue": "No correction", "suggested_fix": "FDR"
            }], "summary": "Single issue."},
            "theoretical": {"findings": [], "summary": "No issues."},
            "big_picture": {"findings": [], "summary": "No issues."},
            "nitpicky": {"findings": [], "summary": "No issues."},
        },
        "overall_verdict": "borderline",
        "confidence": 0.5,
    }


def _valid_reflect_report(mid: str) -> dict:
    return {
        "manuscript_id": mid,
        "argument_structure": {
            "thesis": "Scale wins over architecture.",
            "premises": ["Transformers scale well", "Inductive biases saturate"],
            "evidence_chain": [{"claim": "scaling dominates",
                                 "evidence": ["self"], "strength": 0.7}],
            "conclusion": "Go bigger."
        },
        "implicit_assumptions": [
            {"assumption": "Training data is IID",
             "fragility": "medium",
             "consequence_if_false": "Results may not transfer"},
            {"assumption": "Compute stays cheap",
             "fragility": "low",
             "consequence_if_false": "Economics break"},
        ],
        "weakest_link": {"what": "n=3 seeds only",
                          "why": "Too few for stable TM-score estimates."},
        "one_experiment": {"description": "Run 10 seeds per config on CASP14",
                            "expected_impact": "Stabilizes the comparison",
                            "cost_estimate": "weeks"},
    }


class CritiqueReflectProjectDbTests(TestCase):
    def test_critique_gate_project_id(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            mid = "ms_cr"
            r = _run_with_input(CRITIQUE_GATE, _valid_critique_report(mid),
                                "--manuscript-id", mid, "--project-id", pid)
            assert r.returncode == 0, f"stderr={r.stderr}"
            con = sqlite3.connect(cache_dir / "projects" / pid / "project.db")
            n = con.execute(
                "SELECT COUNT(*) FROM manuscript_critique_findings WHERE manuscript_id=?",
                (mid,),
            ).fetchone()[0]
            con.close()
            self.assertEqual(n, 1)

    def test_reflect_gate_project_id(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            mid = "ms_rf"
            r = _run_with_input(REFLECT_GATE, _valid_reflect_report(mid),
                                "--manuscript-id", mid, "--project-id", pid)
            assert r.returncode == 0, f"stderr={r.stderr}"
            con = sqlite3.connect(cache_dir / "projects" / pid / "project.db")
            n = con.execute(
                "SELECT COUNT(*) FROM manuscript_reflections WHERE manuscript_id=?",
                (mid,),
            ).fetchone()[0]
            con.close()
            self.assertEqual(n, 1)


# ---------------- resolve_citations ----------------

class ResolveCitationsTests(TestCase):
    def test_resolve_updates_table_and_graph(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            # Ingest with a citation so we have an unresolved row + edge
            src = cache_dir / "ms.md"
            src.write_text("# T\n\nCiting \\cite{vaswani2017}.\n")
            r = _run(str(INGEST), "--source", str(src), "--title", "X",
                     "--project-id", pid)
            mid = r.stdout.strip()

            # Resolve
            resolutions = [{
                "citation_key": "vaswani2017",
                "canonical_id": "vaswani_2017_attention_abc",
                "source": "manual",
            }]
            r = _run_with_input(RESOLVE, resolutions,
                                "--manuscript-id", mid, "--project-id", pid)
            assert r.returncode == 0, f"stderr={r.stderr}"
            result = json.loads(r.stdout)
            self.assertEqual(result["citation_rows_updated"], 1)
            self.assertEqual(result["graph_edges_migrated"], 1)

            # Verify final state
            db = cache_dir / "projects" / pid / "project.db"
            con = sqlite3.connect(db)
            row = con.execute(
                "SELECT resolved_canonical_id, resolution_source "
                "FROM manuscript_citations WHERE citation_key=?",
                ("vaswani2017",),
            ).fetchone()
            self.assertEqual(row[0], "vaswani_2017_attention_abc")
            self.assertEqual(row[1], "manual")

            # Unresolved placeholder should be gone
            n_unres = con.execute(
                "SELECT COUNT(*) FROM graph_nodes "
                "WHERE node_id LIKE 'paper:unresolved:%'"
            ).fetchone()[0]
            self.assertEqual(n_unres, 0)

            # Real paper node exists
            n_real = con.execute(
                "SELECT COUNT(*) FROM graph_nodes "
                "WHERE node_id='paper:vaswani_2017_attention_abc'"
            ).fetchone()[0]
            self.assertEqual(n_real, 1)

            # Cites edge points to real node
            n_cites = con.execute(
                "SELECT COUNT(*) FROM graph_edges "
                "WHERE relation='cites' AND to_node='paper:vaswani_2017_attention_abc'"
            ).fetchone()[0]
            self.assertEqual(n_cites, 1)
            con.close()

    def test_resolve_rejects_invalid_source(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            resolutions = [{"citation_key": "k1", "canonical_id": "c1", "source": "vibes"}]
            r = _run_with_input(RESOLVE, resolutions,
                                "--manuscript-id", "mid", "--project-id", pid)
            result = json.loads(r.stdout)
            self.assertEqual(result["errors"], 1)


# ---------------- schema ----------------

class ManuscriptCitationsSchemaTests(TestCase):
    def test_table_and_indexes_present(self):
        con = sqlite3.connect(":memory:")
        con.executescript(SCHEMA)
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        self.assertIn("manuscript_citations", names)
        idx = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )}
        for needed in ["idx_mscites_ms", "idx_mscites_key", "idx_mscites_res"]:
            self.assertIn(needed, idx)

    def test_unique_constraint_on_manuscript_key_location(self):
        con = sqlite3.connect(":memory:")
        con.executescript(SCHEMA)
        con.execute(
            "INSERT INTO manuscript_citations "
            "(manuscript_id, citation_key, location, at) VALUES "
            "('m1', 'k1', 'loc', '2026-01-01')"
        )
        # Same triple should fail
        try:
            con.execute(
                "INSERT INTO manuscript_citations "
                "(manuscript_id, citation_key, location, at) VALUES "
                "('m1', 'k1', 'loc', '2026-01-02')"
            )
            raise AssertionError("expected IntegrityError")
        except sqlite3.IntegrityError:
            pass


if __name__ == "__main__":
    sys.exit(run_tests(
        CitationParserTests,
        IngestGraphIntegrationTests,
        AuditGateProjectDbTests,
        CritiqueReflectProjectDbTests,
        ResolveCitationsTests,
        ManuscriptCitationsSchemaTests,
    ))
