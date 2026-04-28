"""v0.52.4 — cross-persona disagreement scoring tests."""

import json
import sqlite3
import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from lib.disagreement import (  # noqa: E402
    DisagreementScore,
    _personas_active,
    compute_disagreement,
    persist_to_run_db,
    render_summary,
)


def _write_shortlist(
    inputs_dir: Path, persona: str, phase: str,
    results: list[dict],
) -> None:
    inputs_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "run_id": "test",
        "persona": persona,
        "phase": phase,
        "query": "test",
        "results": results,
        "budget": None,
        "harvested_at": "2026-01-01T00:00:00Z",
        "harvested_by": "test",
        "notes": "",
    }
    (inputs_dir / f"{persona}-{phase}.json").write_text(
        json.dumps(payload)
    )


class PersonasActiveTests(TestCase):
    def test_returns_only_search_personas(self):
        with isolated_cache() as cache_dir:
            inputs = cache_dir / "inputs"
            _write_shortlist(inputs, "scout", "phase0", [])
            _write_shortlist(inputs, "cartographer", "phase1", [])
            _write_shortlist(inputs, "synthesist", "phase2", [])  # not search
            active = _personas_active("test", inputs)
            self.assertIn("scout", active)
            self.assertIn("cartographer", active)
            self.assertNotIn("synthesist", active)

    def test_empty_dir_returns_empty(self):
        with isolated_cache() as cache_dir:
            self.assertEqual(_personas_active("test", cache_dir / "x"),
                              set())


class ComputeDisagreementTests(TestCase):
    def test_full_consensus_low_score(self):
        # All 3 personas surface the same paper → score = 0
        with isolated_cache() as cache_dir:
            inputs = cache_dir / "inputs"
            paper = {"title": "Foundational Paper", "year": 2020,
                     "authors": ["Smith"], "doi": "10.1/x"}
            for persona in ("cartographer", "chronicler", "surveyor"):
                _write_shortlist(inputs, persona, "phase1", [paper])

            scores = compute_disagreement("test", cache_dir / "x.db", inputs)
            self.assertTrue(len(scores) >= 1)
            top = scores[0]
            self.assertEqual(top.score, 0.0)  # 3/3 = full agreement

    def test_partial_disagreement_higher_score(self):
        # 2 of 4 personas surface → ratio 0.5 → max bell-curve score 1.0
        with isolated_cache() as cache_dir:
            inputs = cache_dir / "inputs"
            paper = {"title": "Contested Paper", "year": 2020,
                     "authors": ["Jones"], "doi": "10.1/y"}
            other = {"title": "Other", "year": 2020,
                     "authors": ["X"], "doi": "10.1/z"}

            # cartographer + chronicler surface contested + other
            _write_shortlist(inputs, "cartographer", "phase1",
                             [paper, other])
            _write_shortlist(inputs, "chronicler", "phase1", [paper])
            # surveyor + architect only surface other (not paper)
            _write_shortlist(inputs, "surveyor", "phase1", [other])
            _write_shortlist(inputs, "architect", "phase2", [other])

            scores = compute_disagreement("test", cache_dir / "x.db", inputs)
            # Find contested paper's score
            contested_scores = [
                s for s in scores
                if "contested" in s.canonical_id.lower()
            ]
            self.assertEqual(len(contested_scores), 1)
            top = contested_scores[0]
            # 2/4 = 0.5 → 4*0.5*0.5 = 1.0
            self.assertEqual(top.score, 1.0)

    def test_single_persona_returns_empty(self):
        # <2 active personas → meaningless
        with isolated_cache() as cache_dir:
            inputs = cache_dir / "inputs"
            _write_shortlist(inputs, "scout", "phase0",
                              [{"title": "x", "year": 2020,
                                "authors": ["A"], "doi": "10.1/a"}])
            scores = compute_disagreement("test", cache_dir / "x.db",
                                            inputs)
            self.assertEqual(scores, [])


class PersistTests(TestCase):
    def _seed_run(self, cid: str) -> tuple[str, Path]:
        # Spin up a real run DB via db.py init then insert a paper
        import subprocess
        r = subprocess.run(
            [sys.executable,
             str(_ROOT / ".claude/skills/deep-research/scripts/db.py"),
             "init", "--question", "test"],
            capture_output=True, text=True,
        )
        run_id = r.stdout.strip()
        from lib.cache import run_db_path
        db = run_db_path(run_id)
        con = sqlite3.connect(db)
        with con:
            con.execute(
                "INSERT INTO papers_in_run (run_id, canonical_id, "
                " added_in_phase, role) VALUES (?, ?, 'phase0', 'seed')",
                (run_id, cid),
            )
        con.close()
        return run_id, db

    def test_persist_updates_papers_in_run(self):
        with isolated_cache():
            cid = "test_2020_paper_abc123"
            run_id, db = self._seed_run(cid)

            scores = [DisagreementScore(
                canonical_id=cid, score=0.75,
                surfacing_personas=["cartographer"],
                missing_personas=["chronicler"],
                role_conflict=None,
            )]
            n = persist_to_run_db(run_id, db, scores)
            self.assertEqual(n, 1)

            # Verify
            con = sqlite3.connect(db)
            row = con.execute(
                "SELECT disagreement_score FROM papers_in_run "
                "WHERE run_id=? AND canonical_id=?",
                (run_id, cid),
            ).fetchone()
            con.close()
            self.assertAlmostEqual(row[0], 0.75)

    def test_persist_skips_orphan_papers(self):
        # Score for paper not in papers_in_run → 0 rows updated, no error
        with isolated_cache():
            run_id, db = self._seed_run("real_paper")
            scores = [DisagreementScore(
                canonical_id="orphan_not_in_db", score=0.5,
                surfacing_personas=[], missing_personas=[],
                role_conflict=None,
            )]
            n = persist_to_run_db(run_id, db, scores)
            self.assertEqual(n, 0)


class RenderTests(TestCase):
    def test_empty(self):
        s = render_summary([])
        self.assertIn("No cross-persona", s)

    def test_with_scores(self):
        scores = [DisagreementScore(
            canonical_id="bannon_2006_forgetting",
            score=0.95, surfacing_personas=["cartographer", "chronicler"],
            missing_personas=["surveyor", "architect"],
            role_conflict=None,
        )]
        s = render_summary(scores)
        self.assertIn("0.950", s)
        self.assertIn("cartographer", s)
        self.assertIn("surveyor", s)


if __name__ == "__main__":
    sys.exit(run_tests(
        PersonasActiveTests, ComputeDisagreementTests, PersistTests, RenderTests,
    ))
