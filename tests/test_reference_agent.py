"""Reference-agent tests: Zotero sync, BibTeX export, reading state, retractions."""

from tests import _shim  # noqa: F401

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
SYNC = _ROOT / ".claude/skills/reference-agent/scripts/sync_from_zotero.py"
BIB = _ROOT / ".claude/skills/reference-agent/scripts/export_bibtex.py"
STATE = _ROOT / ".claude/skills/reference-agent/scripts/reading_state.py"
RETRACT = _ROOT / ".claude/skills/reference-agent/scripts/mark_retracted.py"


def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(script), *args],
                          capture_output=True, text=True)


def _seed_project(cache_dir: Path, pid: str = "test_project") -> str:
    """Init a minimal project DB directly (no slugify dependency)."""
    proj_root = cache_dir / "projects" / pid
    proj_root.mkdir(parents=True, exist_ok=True)
    db = proj_root / "project.db"
    schema = (_ROOT / "lib" / "sqlite_schema.sql").read_text()
    con = sqlite3.connect(db)
    con.executescript(schema)
    con.execute(
        "INSERT INTO projects (project_id, name, created_at) VALUES (?, ?, ?)",
        (pid, "Test", "2026-04-24T00:00:00Z"),
    )
    con.commit()
    con.close()
    return pid


def _sample_zotero_items() -> list[dict]:
    return [
        {
            "zotero_key": "ZOT1",
            "zotero_library": "user:1",
            "title": "Attention is all you need",
            "authors": ["Vaswani, A.", "Shazeer, N.", "Parmar, N."],
            "year": 2017,
            "doi": "10.48550/arXiv.1706.03762",
            "abstract": "The dominant sequence transduction models are based on complex...",
            "venue": "NeurIPS",
            "tags": ["transformers"],
        },
        {
            "zotero_key": "ZOT2",
            "zotero_library": "user:1",
            "title": "BERT Pre-training",
            "authors": ["Devlin, J."],
            "year": 2019,
            "doi": "10.18653/v1/n19-1423",
            "abstract": "We introduce BERT...",
            "venue": "NAACL",
        },
    ]


class SyncTests(TestCase):
    def test_sync_creates_artifacts_and_graph(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            input_path = cache_dir / "items.json"
            input_path.write_text(json.dumps(_sample_zotero_items()))

            r = _run(SYNC, "--input", str(input_path), "--project-id", pid)
            assert r.returncode == 0, f"stderr={r.stderr}"
            result = json.loads(r.stdout)
            self.assertEqual(result["added"], 2)
            self.assertEqual(result["linked_to_zotero"], 2)

            # Check DB state
            db = cache_dir / "projects" / pid / "project.db"
            con = sqlite3.connect(db)
            n_links = con.execute("SELECT COUNT(*) FROM zotero_links").fetchone()[0]
            n_graph = con.execute(
                "SELECT COUNT(*) FROM graph_nodes WHERE kind='paper'"
            ).fetchone()[0]
            n_authors = con.execute(
                "SELECT COUNT(*) FROM graph_nodes WHERE kind='author'"
            ).fetchone()[0]
            n_reading = con.execute(
                "SELECT COUNT(*) FROM reading_state WHERE state='to-read'"
            ).fetchone()[0]
            con.close()

            self.assertEqual(n_links, 2)
            self.assertEqual(n_graph, 2)
            self.assertTrue(n_authors >= 3)  # at least Vaswani + Devlin + Shazeer + Parmar
            self.assertEqual(n_reading, 2)

    def test_sync_idempotent_on_rerun(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            input_path = cache_dir / "items.json"
            input_path.write_text(json.dumps(_sample_zotero_items()))

            _run(SYNC, "--input", str(input_path), "--project-id", pid)
            r = _run(SYNC, "--input", str(input_path), "--project-id", pid)
            result = json.loads(r.stdout)
            # Re-running doesn't re-link
            self.assertEqual(result["linked_to_zotero"], 0)

    def test_sync_writes_paper_artifact_files(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            input_path = cache_dir / "items.json"
            input_path.write_text(json.dumps(_sample_zotero_items()))
            _run(SYNC, "--input", str(input_path), "--project-id", pid)

            papers_dir = cache_dir / "papers"
            dirs = list(papers_dir.iterdir())
            self.assertEqual(len(dirs), 2)
            for d in dirs:
                self.assertTrue((d / "manifest.json").exists())
                self.assertTrue((d / "metadata.json").exists())
                meta = json.loads((d / "metadata.json").read_text())
                self.assertIn("zotero", meta["discovered_via"])


class BibtexTests(TestCase):
    def _setup_with_run(self, cache_dir: Path) -> tuple[str, str]:
        """Return (run_id, canonical_id_seeded)."""
        # Init run DB
        run_db = cache_dir / "runs" / "run-testrun.db"
        run_db.parent.mkdir(parents=True, exist_ok=True)
        schema = (_ROOT / "lib" / "sqlite_schema.sql").read_text()
        con = sqlite3.connect(run_db)
        con.executescript(schema)

        # Create a paper artifact
        cid = "vaswani_2017_attention_abcdef"
        paper_dir = cache_dir / "papers" / cid
        paper_dir.mkdir(parents=True, exist_ok=True)
        (paper_dir / "manifest.json").write_text(json.dumps({
            "canonical_id": cid, "doi": "10.48550/arXiv.1706.03762",
            "arxiv_id": "1706.03762", "state": "read",
        }))
        (paper_dir / "metadata.json").write_text(json.dumps({
            "title": "Attention is all you need",
            "authors": ["Vaswani, A.", "Shazeer, N."],
            "year": 2017, "venue": "NeurIPS",
        }))

        # Register in papers_in_run
        con.execute(
            "INSERT INTO runs (run_id, question, started_at) VALUES ('testrun', 'q', ?)",
            ("2026-04-24T00:00:00Z",),
        )
        con.execute(
            "INSERT INTO papers_in_run (run_id, canonical_id, added_in_phase, role) "
            "VALUES ('testrun', ?, 'social', 'seed')", (cid,),
        )
        con.commit()
        con.close()
        return "testrun", cid

    def test_export_for_run(self):
        with isolated_cache() as cache_dir:
            run_id, cid = self._setup_with_run(cache_dir)
            out = cache_dir / "refs.bib"
            r = _run(BIB, "--run-id", run_id, "--out", str(out))
            assert r.returncode == 0, f"stderr={r.stderr}"
            content = out.read_text()
            self.assertIn("@article", content)
            self.assertIn("Vaswani", content)
            self.assertIn("canonical_id:", content)

    def test_errors_on_empty_source(self):
        with isolated_cache() as cache_dir:
            run_db = cache_dir / "runs" / "run-empty.db"
            run_db.parent.mkdir(parents=True, exist_ok=True)
            schema = (_ROOT / "lib" / "sqlite_schema.sql").read_text()
            con = sqlite3.connect(run_db)
            con.executescript(schema)
            con.execute(
                "INSERT INTO runs (run_id, question, started_at) "
                "VALUES ('empty', 'q', '2026-04-24T00:00:00Z')"
            )
            con.commit()
            con.close()
            r = _run(BIB, "--run-id", "empty", "--out", str(cache_dir / "out.bib"))
            self.assertEqual(r.returncode, 1)


class ReadingStateTests(TestCase):
    def test_set_and_get(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            r = _run(STATE, "--canonical-id", "cid1", "--project-id", pid,
                     "--state", "to-read")
            assert r.returncode == 0
            r = _run(STATE, "--canonical-id", "cid1", "--project-id", pid, "--get")
            self.assertEqual(r.stdout.strip(), "to-read")

    def test_state_transitions(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            for st in ["to-read", "reading", "read", "annotated", "cited"]:
                r = _run(STATE, "--canonical-id", "cid1", "--project-id", pid,
                         "--state", st)
                self.assertEqual(r.returncode, 0)
            r = _run(STATE, "--canonical-id", "cid1", "--project-id", pid, "--get")
            self.assertEqual(r.stdout.strip(), "cited")

    def test_invalid_state_rejected(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            r = _run(STATE, "--canonical-id", "cid1", "--project-id", pid,
                     "--state", "invented-state")
            self.assertEqual(r.returncode, 2)  # argparse choices

    def test_list_by_state(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            _run(STATE, "--canonical-id", "a", "--project-id", pid, "--state", "to-read")
            _run(STATE, "--canonical-id", "b", "--project-id", pid, "--state", "to-read")
            _run(STATE, "--canonical-id", "c", "--project-id", pid, "--state", "read")

            r = _run(STATE, "--project-id", pid, "--list-by-state", "to-read")
            items = json.loads(r.stdout)
            self.assertEqual(len(items), 2)

    def test_get_unknown(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            r = _run(STATE, "--canonical-id", "nonexistent",
                     "--project-id", pid, "--get")
            self.assertEqual(r.stdout.strip(), "unknown")


class RetractionTests(TestCase):
    def test_mark_retractions(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            inp = cache_dir / "retractions.json"
            inp.write_text(json.dumps([
                {"canonical_id": "bad_paper_1", "retracted": True,
                 "source": "semantic-scholar", "detail": "Fig 2 fabricated"},
                {"canonical_id": "good_paper_1", "retracted": False,
                 "source": "semantic-scholar"},
            ]))
            r = _run(RETRACT, "--input", str(inp), "--project-id", pid)
            assert r.returncode == 0, f"stderr={r.stderr}"
            result = json.loads(r.stdout)
            self.assertEqual(result["new"], 2)

            # Verify DB
            db = cache_dir / "projects" / pid / "project.db"
            con = sqlite3.connect(db)
            retracted = con.execute(
                "SELECT COUNT(*) FROM retraction_flags WHERE retracted=1"
            ).fetchone()[0]
            con.close()
            self.assertEqual(retracted, 1)

    def test_invalid_source_rejected(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            inp = cache_dir / "retractions.json"
            inp.write_text(json.dumps([
                {"canonical_id": "x", "retracted": True, "source": "rumor"}
            ]))
            r = _run(RETRACT, "--input", str(inp), "--project-id", pid)
            self.assertEqual(r.returncode, 2)

    def test_missing_canonical_id_rejected(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            inp = cache_dir / "retractions.json"
            inp.write_text(json.dumps([{"retracted": True, "source": "manual"}]))
            r = _run(RETRACT, "--input", str(inp), "--project-id", pid)
            self.assertEqual(r.returncode, 2)


class ReferenceAgentSchemaTests(TestCase):
    def test_tables_present(self):
        con = sqlite3.connect(":memory:")
        con.executescript((_ROOT / "lib" / "sqlite_schema.sql").read_text())
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        for t in ["reading_state", "retraction_flags", "zotero_links"]:
            self.assertIn(t, names)


if __name__ == "__main__":
    sys.exit(run_tests(
        SyncTests, BibtexTests, ReadingStateTests,
        RetractionTests, ReferenceAgentSchemaTests,
    ))
