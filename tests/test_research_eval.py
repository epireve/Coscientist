"""v0.45.3 tests for research-eval scripts."""

import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
EVAL_REFS = _ROOT / ".claude/skills/research-eval/scripts/eval_references.py"
EVAL_CLAIMS = _ROOT / ".claude/skills/research-eval/scripts/eval_claims.py"
SCHEMA = _ROOT / "lib" / "sqlite_schema.sql"


def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True,
    )


def _seed_run(run_id: str, papers: list[str],
              citations: list[tuple[str, str]] | None = None,
              claims: list[dict] | None = None) -> Path:
    """Create a run DB with the rows research-eval expects."""
    from lib.cache import run_db_path
    from lib.migrations import ensure_current
    db = run_db_path(run_id)
    con = sqlite3.connect(db)
    con.executescript(SCHEMA.read_text())
    con.close()
    ensure_current(db)
    con = sqlite3.connect(db)
    now = datetime.now(UTC).isoformat()
    with con:
        con.execute(
            "INSERT INTO runs (run_id, question, started_at, status) "
            "VALUES (?, 'q', ?, 'running')", (run_id, now),
        )
        for cid in papers:
            con.execute(
                "INSERT INTO papers_in_run (run_id, canonical_id, "
                "added_in_phase, role) VALUES (?, ?, 'social', 'seed')",
                (run_id, cid),
            )
        for fr, to in (citations or []):
            con.execute(
                "INSERT INTO citations (run_id, from_canonical, to_canonical) "
                "VALUES (?, ?, ?)", (run_id, fr, to),
            )
        for c in (claims or []):
            con.execute(
                "INSERT INTO claims (run_id, canonical_id, agent_name, text, "
                "kind, confidence, supporting_ids) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, c.get("canonical_id"), c.get("agent_name", "x"),
                 c["text"], c.get("kind"), c.get("confidence"),
                 json.dumps(c.get("supporting_ids", []))),
            )
    con.close()
    return db


def _seed_paper_artifact(cid: str, doi: str | None = None,
                         discovered_via: list[str] | None = None):
    from lib.paper_artifact import Metadata, PaperArtifact
    art = PaperArtifact(cid)
    m = art.load_manifest()
    m.doi = doi
    art.save_manifest(m)
    art.save_metadata(Metadata(
        title=f"t-{cid}",
        discovered_via=discovered_via or [],
    ))


# ---------------- eval_references ----------------

class EvalReferencesTests(TestCase):
    def test_no_db_errors(self):
        with isolated_cache():
            r = _run(EVAL_REFS, "--run-id", "missing", "--format", "json")
            self.assertTrue(r.returncode != 0)
            self.assertIn("no run db", r.stderr)

    def test_clean_run_zero_dangling(self):
        with isolated_cache():
            _seed_paper_artifact("p1", doi="10.1/x", discovered_via=["arxiv"])
            _seed_paper_artifact("p2", doi="10.2/y", discovered_via=["arxiv"])
            _seed_run("r1", papers=["p1", "p2"],
                       citations=[("p1", "p2")])
            r = _run(EVAL_REFS, "--run-id", "r1", "--format", "json")
            # zero dangling, full DOI coverage → exit 0
            self.assertEqual(r.returncode, 0, r.stderr)
            report = json.loads(r.stdout)
            self.assertEqual(report["papers_total"], 2)
            self.assertEqual(report["doi_coverage"], 1.0)
            self.assertEqual(report["dangling_refs"], [])

    def test_dangling_refs_flagged_and_exit_2(self):
        with isolated_cache():
            _seed_paper_artifact("p1", doi="10.1/x", discovered_via=["arxiv"])
            _seed_run("r2", papers=["p1"],
                       citations=[("p1", "p_ghost")])
            r = _run(EVAL_REFS, "--run-id", "r2", "--format", "json")
            self.assertEqual(r.returncode, 2)
            report = json.loads(r.stdout)
            self.assertIn("p_ghost", report["dangling_refs"])

    def test_low_doi_coverage_exit_2(self):
        with isolated_cache():
            _seed_paper_artifact("p1", doi=None, discovered_via=["arxiv"])
            _seed_paper_artifact("p2", doi=None, discovered_via=["arxiv"])
            _seed_run("r3", papers=["p1", "p2"])
            r = _run(EVAL_REFS, "--run-id", "r3", "--format", "json")
            self.assertEqual(r.returncode, 2)
            report = json.loads(r.stdout)
            self.assertEqual(report["doi_coverage"], 0.0)

    def test_orphan_papers_listed(self):
        with isolated_cache():
            _seed_paper_artifact("p1", doi="10.1/x", discovered_via=["arxiv"])
            _seed_paper_artifact("p2", doi="10.2/y", discovered_via=["arxiv"])
            _seed_run("r4", papers=["p1", "p2"],
                       citations=[("p1", "p2")])
            r = _run(EVAL_REFS, "--run-id", "r4", "--format", "json")
            report = json.loads(r.stdout)
            # p1 was never cited-to → orphan
            self.assertIn("p1", report["orphans"])

    def test_md_report_written_to_disk(self):
        with isolated_cache():
            from lib.cache import cache_root
            _seed_paper_artifact("p1", doi="10.1/x", discovered_via=["arxiv"])
            _seed_paper_artifact("p2", doi="10.2/y", discovered_via=["s2"])
            _seed_run("r5", papers=["p1", "p2"],
                       citations=[("p1", "p2")])
            _run(EVAL_REFS, "--run-id", "r5", "--format", "md")
            out_md = cache_root() / "runs" / "run-r5-eval.md"
            self.assertTrue(out_md.exists())
            self.assertIn("Reference audit", out_md.read_text())


# ---------------- eval_claims ----------------

class EvalClaimsTests(TestCase):
    def test_no_db_errors(self):
        with isolated_cache():
            r = _run(EVAL_CLAIMS, "--run-id", "nope", "--format", "json")
            self.assertTrue(r.returncode != 0)
            self.assertIn("no run db", r.stderr)

    def test_attributed_claims_pass(self):
        with isolated_cache():
            _seed_run("c1", papers=["p1", "p2"], claims=[
                {"text": "claim A", "canonical_id": "p1",
                 "kind": "finding", "agent_name": "grounder"},
                {"text": "claim B", "canonical_id": "p2",
                 "kind": "finding", "agent_name": "grounder"},
            ])
            r = _run(EVAL_CLAIMS, "--run-id", "c1", "--format", "json")
            self.assertEqual(r.returncode, 0, r.stderr)
            report = json.loads(r.stdout)
            self.assertEqual(report["claims_total"], 2)
            self.assertEqual(len(report["unattributed"]), 0)
            self.assertEqual(report["unattributed_ratio"], 0.0)

    def test_unattributed_claims_flagged(self):
        with isolated_cache():
            _seed_run("c2", papers=["p1"], claims=[
                {"text": "synth claim", "canonical_id": None,
                 "agent_name": "theorist"},
                {"text": "real claim", "canonical_id": "p1",
                 "agent_name": "grounder"},
            ])
            r = _run(EVAL_CLAIMS, "--run-id", "c2", "--format", "json")
            report = json.loads(r.stdout)
            self.assertEqual(len(report["unattributed"]), 1)
            self.assertEqual(report["unattributed_ratio"], 0.5)
            # 50% < 30% threshold → exit 2
            self.assertEqual(r.returncode, 2)

    def test_bad_supporting_id_flagged(self):
        with isolated_cache():
            _seed_run("c3", papers=["p1"], claims=[
                {"text": "missing-cite claim", "canonical_id": "p1",
                 "supporting_ids": ["p_ghost"], "agent_name": "x"},
            ])
            r = _run(EVAL_CLAIMS, "--run-id", "c3", "--format", "json")
            report = json.loads(r.stdout)
            self.assertEqual(len(report["bad_support"]), 1)
            self.assertIn("p_ghost", report["bad_support"][0]["missing"])

    def test_by_kind_breakdown(self):
        with isolated_cache():
            _seed_run("c4", papers=["p1"], claims=[
                {"text": "f", "canonical_id": "p1", "kind": "finding"},
                {"text": "h", "canonical_id": "p1", "kind": "hypothesis"},
                {"text": "g", "canonical_id": "p1", "kind": "gap"},
            ])
            r = _run(EVAL_CLAIMS, "--run-id", "c4", "--format", "json")
            report = json.loads(r.stdout)
            self.assertEqual(report["by_kind"],
                             {"finding": 1, "hypothesis": 1, "gap": 1})


if __name__ == "__main__":
    sys.exit(run_tests(EvalReferencesTests, EvalClaimsTests))
