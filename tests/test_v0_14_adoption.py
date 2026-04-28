"""v0.14 adoption tests.

Verifies that v0.13 primitives are actually wired into the skills that
need them — not just that they pass standalone unit tests in
test_v0_13_infrastructure.py.

Coverage:
- lib.project._connect calls migrations.ensure_current() (so old DBs
  pick up new migrations on open).
- deep-research/db.py _connect calls migrations.ensure_current().
- paper-acquire/record.py acquires artifact_lock before mutating manifest.
- paper-triage/record.py acquires artifact_lock before mutating manifest.
- institutional-access/fetch.py uses aretry_with_backoff around adapter calls.
- manuscript-{audit,critique,reflect}/gate.py use multi_db_tx for the
  dual run-DB + project-DB write — when the project-side write fails,
  the run-DB write rolls back too.
"""

import json
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (_ROOT / "lib" / "sqlite_schema.sql").read_text()

ACQUIRE_RECORD = _ROOT / ".claude/skills/paper-acquire/scripts/record.py"
TRIAGE_RECORD = _ROOT / ".claude/skills/paper-triage/scripts/record.py"
INSTITUTIONAL_FETCH = _ROOT / ".claude/skills/institutional-access/scripts/fetch.py"
AUDIT_GATE = _ROOT / ".claude/skills/manuscript-audit/scripts/gate.py"
CRITIQUE_GATE = _ROOT / ".claude/skills/manuscript-critique/scripts/gate.py"
REFLECT_GATE = _ROOT / ".claude/skills/manuscript-reflect/scripts/gate.py"

PROJECT_PY = _ROOT / "lib" / "project.py"
DEEP_DB_PY = _ROOT / ".claude/skills/deep-research/scripts/db.py"


# ---------------- migrations wired ----------------

class MigrationsAdoptionTests(TestCase):
    def test_lib_project_connect_imports_ensure_current(self):
        src = PROJECT_PY.read_text()
        self.assertIn("ensure_current", src,
                      "lib/project.py should import ensure_current()")
        self.assertIn("from lib.migrations", src)

    def test_deep_research_db_imports_ensure_current(self):
        src = DEEP_DB_PY.read_text()
        self.assertIn("ensure_current", src,
                      "deep-research/db.py should call ensure_current()")

    def test_project_open_records_a_schema_version(self):
        """Opening a project DB must populate schema_versions via migrations."""
        with isolated_cache() as cache_dir:
            from lib import project as project_mod
            pid = project_mod.create("v14 mig test", "v0.14 migration test")

            con = sqlite3.connect(
                cache_dir / "projects" / pid / "project.db"
            )
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            self.assertIn("schema_versions", tables,
                          "ensure_current should have created schema_versions")
            applied = con.execute(
                "SELECT COUNT(*) FROM schema_versions"
            ).fetchone()[0]
            con.close()
            self.assertTrue(applied >= 1,
                            f"expected ≥1 applied migration, got {applied}")


# ---------------- artifact_lock wired ----------------

class ArtifactLockAdoptionTests(TestCase):
    def test_paper_acquire_imports_artifact_lock(self):
        src = ACQUIRE_RECORD.read_text()
        self.assertIn("artifact_lock", src)
        self.assertIn("with artifact_lock", src,
                      "paper-acquire must use artifact_lock as a context manager")

    def test_paper_triage_imports_artifact_lock(self):
        src = TRIAGE_RECORD.read_text()
        self.assertIn("artifact_lock", src)
        self.assertIn("with artifact_lock", src)

    def test_concurrent_record_calls_serialize(self):
        """Two threads calling record_one against the same paper must serialize."""
        with isolated_cache() as cache_dir:
            from lib.paper_artifact import PaperArtifact

            cid = "test_2026_paper_abc123"
            art = PaperArtifact(cid)
            art.save_manifest(art.load_manifest())  # initialize manifest
            # Seed minimal metadata so triage can mark sufficient=true
            from lib.paper_artifact import Metadata
            meta = art.load_metadata() or Metadata(title="Concurrent test paper")
            meta.abstract = "x" * 20
            art.save_metadata(meta)

            # Import the triage record_one to drive concurrent writers
            sys.path.insert(
                0, str(_ROOT / ".claude/skills/paper-triage/scripts"),
            )
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location(
                    "triage_record", TRIAGE_RECORD,
                )
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            finally:
                sys.path.pop(0)

            errors: list[BaseException] = []

            def worker(rationale: str) -> None:
                try:
                    mod.record_one(cid, True, rationale)
                except BaseException as e:
                    errors.append(e)

            threads = [
                threading.Thread(target=worker, args=(f"r{i}",))
                for i in range(4)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(errors, [],
                             f"concurrent record_one raised: {errors!r}")
            # Manifest should still be readable + valid (no corruption)
            final = PaperArtifact(cid).load_manifest()
            self.assertTrue(final.triage is not None)


# ---------------- aretry wired in institutional-access ----------------

class RetryAdoptionTests(TestCase):
    def test_institutional_fetch_imports_aretry(self):
        src = INSTITUTIONAL_FETCH.read_text()
        self.assertIn("aretry_with_backoff", src,
                      "institutional-access fetch.py must use the async retry")
        self.assertIn("from lib.retry", src)

    def test_aretry_retries_and_succeeds(self):
        """Smoke-test the async retry primitive itself for institutional usage."""
        import asyncio

        from lib.retry import aretry_with_backoff

        calls = [0]

        async def attempt():
            calls[0] += 1
            if calls[0] < 3:
                raise TimeoutError("flaky publisher")
            return "pdf-ok"

        result = asyncio.run(aretry_with_backoff(
            attempt, max_attempts=4, base_delay=0.01,
        ))
        self.assertEqual(result, "pdf-ok")
        self.assertEqual(calls[0], 3)

    def test_aretry_gives_up_after_max_attempts(self):
        import asyncio

        from lib.retry import aretry_with_backoff

        calls = [0]

        async def attempt():
            calls[0] += 1
            raise TimeoutError("never recovers")

        try:
            asyncio.run(aretry_with_backoff(
                attempt, max_attempts=3, base_delay=0.01,
            ))
            self.assertTrue(False, "should have raised")
        except TimeoutError:
            pass
        self.assertEqual(calls[0], 3)


# ---------------- multi_db_tx wired in manuscript gates ----------------

def _seed_project(cache_dir: Path, pid: str) -> str:
    p = cache_dir / "projects" / pid
    p.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p / "project.db")
    con.executescript(SCHEMA)
    con.execute(
        "INSERT INTO projects (project_id, name, created_at) VALUES (?, ?, ?)",
        (pid, "Tx Test", "2026-04-25T00:00:00Z"),
    )
    con.commit()
    con.close()
    return pid


def _seed_run(cache_dir: Path, run_id: str) -> Path:
    rdb = cache_dir / "runs" / f"run-{run_id}.db"
    rdb.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(rdb)
    con.executescript(SCHEMA)
    con.execute(
        "INSERT INTO runs (run_id, question, started_at) "
        "VALUES (?, 'q', '2026-04-25T00:00:00Z')",
        (run_id,),
    )
    con.commit()
    con.close()
    return rdb


def _run_with_input(script: Path, input_json: dict | list,
                    *args: str) -> subprocess.CompletedProcess:
    tmp = _ROOT / "tests" / "_tmp_input.json"
    tmp.write_text(json.dumps(input_json))
    return subprocess.run(
        [sys.executable, str(script), "--input", str(tmp), *args],
        capture_output=True, text=True,
    )


def _valid_audit_report(mid: str) -> dict:
    return {
        "manuscript_id": mid,
        "claims": [{
            "claim_id": "c1", "text": "Adam beats SGD here.",
            "location": "§3.2", "cited_sources": ["smith2024"],
            "findings": [{
                "kind": "unsupported", "severity": "minor",
                "evidence": "No baseline ablation provided."
            }]
        }]
    }


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
                          "why": "Too few for stable estimates."},
        "one_experiment": {"description": "Run 10 seeds per config on CASP14",
                            "expected_impact": "Stabilizes the comparison",
                            "cost_estimate": "weeks"},
    }


class MultiDbTxAdoptionTests(TestCase):
    def test_audit_gate_imports_multi_db_tx(self):
        src = AUDIT_GATE.read_text()
        self.assertIn("multi_db_tx", src)
        self.assertIn("from lib.transaction", src)

    def test_critique_gate_imports_multi_db_tx(self):
        src = CRITIQUE_GATE.read_text()
        self.assertIn("multi_db_tx", src)

    def test_reflect_gate_imports_multi_db_tx(self):
        src = REFLECT_GATE.read_text()
        self.assertIn("multi_db_tx", src)

    def test_audit_dual_write_atomicity_via_corrupt_project_db(self):
        """If the project DB write fails mid-tx, the run DB row must roll back too."""
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir, "tx_test")
            run_id = "tx1"
            run_db = _seed_run(cache_dir, run_id)

            # Drop a critical project-side table to force a SQL failure
            # during the second leg of multi_db_tx.
            pdb = cache_dir / "projects" / pid / "project.db"
            con = sqlite3.connect(pdb)
            con.execute("DROP TABLE manuscript_claims")
            con.commit()
            con.close()

            mid = "rollback_ms"
            r = _run_with_input(
                AUDIT_GATE, _valid_audit_report(mid),
                "--manuscript-id", mid,
                "--run-id", run_id, "--project-id", pid,
            )
            # Gate should fail (non-zero) because project-side INSERT errors
            self.assertTrue(r.returncode != 0,
                            f"expected failure; got rc=0 stderr={r.stderr}")

            # Run DB must NOT contain the row — multi_db_tx rolled it back
            con = sqlite3.connect(run_db)
            n = con.execute(
                "SELECT COUNT(*) FROM manuscript_claims WHERE manuscript_id=?",
                (mid,),
            ).fetchone()[0]
            con.close()
            self.assertEqual(
                n, 0,
                "run DB row must roll back when project DB write fails",
            )

    def test_critique_dual_write_atomicity(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir, "tx_crit")
            run_id = "tx_crit_run"
            run_db = _seed_run(cache_dir, run_id)

            pdb = cache_dir / "projects" / pid / "project.db"
            con = sqlite3.connect(pdb)
            con.execute("DROP TABLE manuscript_critique_findings")
            con.commit()
            con.close()

            mid = "rollback_crit"
            r = _run_with_input(
                CRITIQUE_GATE, _valid_critique_report(mid),
                "--manuscript-id", mid,
                "--run-id", run_id, "--project-id", pid,
            )
            self.assertTrue(r.returncode != 0)

            con = sqlite3.connect(run_db)
            n = con.execute(
                "SELECT COUNT(*) FROM manuscript_critique_findings "
                "WHERE manuscript_id=?", (mid,),
            ).fetchone()[0]
            con.close()
            self.assertEqual(n, 0)

    def test_reflect_dual_write_atomicity(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir, "tx_refl")
            run_id = "tx_refl_run"
            run_db = _seed_run(cache_dir, run_id)

            pdb = cache_dir / "projects" / pid / "project.db"
            con = sqlite3.connect(pdb)
            con.execute("DROP TABLE manuscript_reflections")
            con.commit()
            con.close()

            mid = "rollback_refl"
            r = _run_with_input(
                REFLECT_GATE, _valid_reflect_report(mid),
                "--manuscript-id", mid,
                "--run-id", run_id, "--project-id", pid,
            )
            self.assertTrue(r.returncode != 0)

            con = sqlite3.connect(run_db)
            n = con.execute(
                "SELECT COUNT(*) FROM manuscript_reflections "
                "WHERE manuscript_id=?", (mid,),
            ).fetchone()[0]
            con.close()
            self.assertEqual(n, 0)

    def test_audit_clean_dual_write_still_works(self):
        """Sanity: with both DBs intact, the dual-write succeeds end-to-end."""
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir, "tx_ok")
            run_id = "tx_ok_run"
            run_db = _seed_run(cache_dir, run_id)

            mid = "ok_ms"
            r = _run_with_input(
                AUDIT_GATE, _valid_audit_report(mid),
                "--manuscript-id", mid,
                "--run-id", run_id, "--project-id", pid,
            )
            self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")

            for db in (run_db, cache_dir / "projects" / pid / "project.db"):
                con = sqlite3.connect(db)
                n = con.execute(
                    "SELECT COUNT(*) FROM manuscript_claims "
                    "WHERE manuscript_id=?", (mid,),
                ).fetchone()[0]
                con.close()
                self.assertEqual(n, 1, f"missing claim in {db}")


if __name__ == "__main__":
    sys.exit(run_tests(
        MigrationsAdoptionTests,
        ArtifactLockAdoptionTests,
        RetryAdoptionTests,
        MultiDbTxAdoptionTests,
    ))
