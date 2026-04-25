"""v0.12 tournament + evolution tests.

Covers:
- record_hypothesis seeds Elo=1200, rejects duplicate hyp_id
- record_match Elo math correct, win/loss/draw, increments counters
- pairwise strategies: round-robin, top-k-vs-rest, top-k-internal
- pairwise --exclude-played skips matches already in tournament_matches
- leaderboard sorts by Elo desc, includes ancestor chain
- evolver lineage via parent_hyp_id walks correctly
"""

from tests import _shim  # noqa: F401

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (_ROOT / "lib" / "sqlite_schema.sql").read_text()

REC_HYP = _ROOT / ".claude/skills/tournament/scripts/record_hypothesis.py"
REC_MATCH = _ROOT / ".claude/skills/tournament/scripts/record_match.py"
PAIRWISE = _ROOT / ".claude/skills/tournament/scripts/pairwise.py"
LEADERBOARD = _ROOT / ".claude/skills/tournament/scripts/leaderboard.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True, text=True)


def _seed_run(cache_dir: Path, run_id: str = "tourn_run") -> str:
    d = cache_dir / "runs"
    d.mkdir(parents=True, exist_ok=True)
    db = d / f"run-{run_id}.db"
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.execute(
        "INSERT INTO runs (run_id, question, started_at) VALUES (?, ?, ?)",
        (run_id, "test q", "2026-04-24T00:00:00Z"),
    )
    con.commit()
    con.close()
    return run_id


def _add_hyp(run_id: str, hyp_id: str, statement: str = "test statement",
             agent: str = "theorist", parent: str | None = None) -> None:
    cmd = [
        str(REC_HYP), "--run-id", run_id, "--agent-name", agent,
        "--hyp-id", hyp_id, "--statement", statement,
        "--falsifiers", '["if X then fail"]',
    ]
    if parent:
        cmd += ["--parent-hyp-id", parent]
    r = _run(*cmd)
    assert r.returncode == 0, f"failed to add {hyp_id}: {r.stderr}"


def _hyp_row(cache_dir: Path, run_id: str, hyp_id: str) -> dict:
    db = cache_dir / "runs" / f"run-{run_id}.db"
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT * FROM hypotheses WHERE hyp_id=?", (hyp_id,),
    ).fetchone()
    con.close()
    return dict(row) if row else {}


# ---------------- record_hypothesis ----------------

class RecordHypothesisTests(TestCase):
    def test_seeds_default_elo(self):
        with isolated_cache() as cache_dir:
            run_id = _seed_run(cache_dir)
            _add_hyp(run_id, "hyp-1")
            row = _hyp_row(cache_dir, run_id, "hyp-1")
            self.assertEqual(row["elo"], 1200.0)
            self.assertEqual(row["n_matches"], 0)
            self.assertEqual(row["n_wins"], 0)
            self.assertEqual(row["n_losses"], 0)

    def test_rejects_duplicate_hyp_id(self):
        with isolated_cache() as cache_dir:
            run_id = _seed_run(cache_dir)
            _add_hyp(run_id, "hyp-1")
            r = _run(str(REC_HYP), "--run-id", run_id,
                     "--agent-name", "theorist", "--hyp-id", "hyp-1",
                     "--statement", "dup", "--falsifiers", '["x"]')
            self.assertEqual(r.returncode, 1)

    def test_parent_hyp_id_recorded(self):
        with isolated_cache() as cache_dir:
            run_id = _seed_run(cache_dir)
            _add_hyp(run_id, "hyp-parent")
            _add_hyp(run_id, "hyp-child", agent="evolver", parent="hyp-parent")
            child = _hyp_row(cache_dir, run_id, "hyp-child")
            self.assertEqual(child["parent_hyp_id"], "hyp-parent")

    def test_invalid_agent_rejected(self):
        with isolated_cache() as cache_dir:
            run_id = _seed_run(cache_dir)
            r = _run(str(REC_HYP), "--run-id", run_id,
                     "--agent-name", "made-up-agent", "--hyp-id", "h",
                     "--statement", "x", "--falsifiers", '["y"]')
            self.assertEqual(r.returncode, 2)


# ---------------- record_match Elo math ----------------

class RecordMatchTests(TestCase):
    def test_winner_gains_loser_loses_equal_initial(self):
        with isolated_cache() as cache_dir:
            run_id = _seed_run(cache_dir)
            _add_hyp(run_id, "hyp-a")
            _add_hyp(run_id, "hyp-b")
            r = _run(str(REC_MATCH), "--run-id", run_id,
                     "--hyp-a", "hyp-a", "--hyp-b", "hyp-b",
                     "--winner", "hyp-a")
            assert r.returncode == 0, f"stderr={r.stderr}"
            result = json.loads(r.stdout)
            # K=32, equal initial → winner +16, loser -16
            self.assertEqual(result["delta_a"], 16.0)
            self.assertEqual(result["delta_b"], -16.0)
            self.assertEqual(result["elo_a"], 1216.0)
            self.assertEqual(result["elo_b"], 1184.0)

    def test_match_counters_updated(self):
        with isolated_cache() as cache_dir:
            run_id = _seed_run(cache_dir)
            _add_hyp(run_id, "hyp-a")
            _add_hyp(run_id, "hyp-b")
            _run(str(REC_MATCH), "--run-id", run_id,
                 "--hyp-a", "hyp-a", "--hyp-b", "hyp-b",
                 "--winner", "hyp-a")
            a = _hyp_row(cache_dir, run_id, "hyp-a")
            b = _hyp_row(cache_dir, run_id, "hyp-b")
            self.assertEqual(a["n_matches"], 1)
            self.assertEqual(a["n_wins"], 1)
            self.assertEqual(a["n_losses"], 0)
            self.assertEqual(b["n_matches"], 1)
            self.assertEqual(b["n_wins"], 0)
            self.assertEqual(b["n_losses"], 1)

    def test_draw_no_movement_when_equal(self):
        with isolated_cache() as cache_dir:
            run_id = _seed_run(cache_dir)
            _add_hyp(run_id, "hyp-a")
            _add_hyp(run_id, "hyp-b")
            r = _run(str(REC_MATCH), "--run-id", run_id,
                     "--hyp-a", "hyp-a", "--hyp-b", "hyp-b",
                     "--winner", "draw")
            result = json.loads(r.stdout)
            self.assertEqual(result["delta_a"], 0.0)
            self.assertEqual(result["delta_b"], 0.0)

    def test_underdog_win_gains_more_than_favorite(self):
        with isolated_cache() as cache_dir:
            run_id = _seed_run(cache_dir)
            _add_hyp(run_id, "hyp-strong")
            _add_hyp(run_id, "hyp-weak")
            # Boost strong artificially via a few wins so Elo diverges
            db = cache_dir / "runs" / f"run-{run_id}.db"
            con = sqlite3.connect(db)
            con.execute("UPDATE hypotheses SET elo=1400 WHERE hyp_id='hyp-strong'")
            con.execute("UPDATE hypotheses SET elo=1100 WHERE hyp_id='hyp-weak'")
            con.commit()
            con.close()
            # Underdog wins
            r = _run(str(REC_MATCH), "--run-id", run_id,
                     "--hyp-a", "hyp-weak", "--hyp-b", "hyp-strong",
                     "--winner", "hyp-weak")
            result = json.loads(r.stdout)
            # Underdog (delta_a) gain should be > what favorite would gain
            # in symmetric win (16). Specifically, K * (1 - E_weak)
            self.assertTrue(result["delta_a"] > 16.0,
                            f"underdog gain {result['delta_a']} not > 16")

    def test_match_row_persisted(self):
        with isolated_cache() as cache_dir:
            run_id = _seed_run(cache_dir)
            _add_hyp(run_id, "hyp-a")
            _add_hyp(run_id, "hyp-b")
            _run(str(REC_MATCH), "--run-id", run_id,
                 "--hyp-a", "hyp-a", "--hyp-b", "hyp-b",
                 "--winner", "hyp-a", "--judge-reasoning", "because")
            db = cache_dir / "runs" / f"run-{run_id}.db"
            con = sqlite3.connect(db)
            n = con.execute("SELECT COUNT(*) FROM tournament_matches").fetchone()[0]
            row = con.execute(
                "SELECT winner, judge_reasoning FROM tournament_matches"
            ).fetchone()
            con.close()
            self.assertEqual(n, 1)
            self.assertEqual(row[0], "hyp-a")
            self.assertEqual(row[1], "because")

    def test_invalid_winner_rejected(self):
        with isolated_cache() as cache_dir:
            run_id = _seed_run(cache_dir)
            _add_hyp(run_id, "hyp-a")
            _add_hyp(run_id, "hyp-b")
            r = _run(str(REC_MATCH), "--run-id", run_id,
                     "--hyp-a", "hyp-a", "--hyp-b", "hyp-b",
                     "--winner", "hyp-c")
            self.assertEqual(r.returncode, 1)

    def test_self_match_rejected(self):
        with isolated_cache() as cache_dir:
            run_id = _seed_run(cache_dir)
            _add_hyp(run_id, "hyp-a")
            r = _run(str(REC_MATCH), "--run-id", run_id,
                     "--hyp-a", "hyp-a", "--hyp-b", "hyp-a",
                     "--winner", "hyp-a")
            self.assertEqual(r.returncode, 1)


# ---------------- pairwise pairings ----------------

class PairwiseTests(TestCase):
    def _seed_5(self, cache_dir: Path) -> str:
        run_id = _seed_run(cache_dir)
        for i in range(1, 6):
            _add_hyp(run_id, f"hyp-{i}")
        # Set distinct Elo so ordering is deterministic
        db = cache_dir / "runs" / f"run-{run_id}.db"
        con = sqlite3.connect(db)
        for i in range(1, 6):
            con.execute("UPDATE hypotheses SET elo=? WHERE hyp_id=?",
                        (1500 - i * 50, f"hyp-{i}"))
        con.commit()
        con.close()
        return run_id

    def test_round_robin_count(self):
        with isolated_cache() as cache_dir:
            run_id = self._seed_5(cache_dir)
            r = _run(str(PAIRWISE), "--run-id", run_id, "--strategy", "round-robin")
            result = json.loads(r.stdout)
            # 5 choose 2 = 10
            self.assertEqual(result["n_pairs"], 10)

    def test_top_k_vs_rest(self):
        with isolated_cache() as cache_dir:
            run_id = self._seed_5(cache_dir)
            r = _run(str(PAIRWISE), "--run-id", run_id,
                     "--strategy", "top-k-vs-rest", "--top-k", "2")
            result = json.loads(r.stdout)
            # 2 top × 3 rest = 6
            self.assertEqual(result["n_pairs"], 6)

    def test_top_k_internal(self):
        with isolated_cache() as cache_dir:
            run_id = self._seed_5(cache_dir)
            r = _run(str(PAIRWISE), "--run-id", run_id,
                     "--strategy", "top-k-internal", "--top-k", "3")
            result = json.loads(r.stdout)
            # 3 choose 2 = 3
            self.assertEqual(result["n_pairs"], 3)

    def test_exclude_played(self):
        with isolated_cache() as cache_dir:
            run_id = self._seed_5(cache_dir)
            # Play hyp-1 vs hyp-2
            _run(str(REC_MATCH), "--run-id", run_id,
                 "--hyp-a", "hyp-1", "--hyp-b", "hyp-2", "--winner", "hyp-1")
            r = _run(str(PAIRWISE), "--run-id", run_id,
                     "--strategy", "round-robin", "--exclude-played")
            result = json.loads(r.stdout)
            # 10 - 1 played = 9
            self.assertEqual(result["n_pairs"], 9)

    def test_too_few_hypotheses(self):
        with isolated_cache() as cache_dir:
            run_id = _seed_run(cache_dir)
            _add_hyp(run_id, "only-one")
            r = _run(str(PAIRWISE), "--run-id", run_id, "--strategy", "round-robin")
            self.assertEqual(r.returncode, 1)


# ---------------- leaderboard ----------------

class LeaderboardTests(TestCase):
    def test_sorted_by_elo_desc(self):
        with isolated_cache() as cache_dir:
            run_id = _seed_run(cache_dir)
            for i in range(1, 4):
                _add_hyp(run_id, f"hyp-{i}")
            db = cache_dir / "runs" / f"run-{run_id}.db"
            con = sqlite3.connect(db)
            con.execute("UPDATE hypotheses SET elo=1300 WHERE hyp_id='hyp-1'")
            con.execute("UPDATE hypotheses SET elo=1500 WHERE hyp_id='hyp-2'")
            con.execute("UPDATE hypotheses SET elo=1100 WHERE hyp_id='hyp-3'")
            con.commit()
            con.close()
            r = _run(str(LEADERBOARD), "--run-id", run_id)
            result = json.loads(r.stdout)
            ids = [h["hyp_id"] for h in result["top"]]
            self.assertEqual(ids, ["hyp-2", "hyp-1", "hyp-3"])

    def test_ancestor_chain(self):
        with isolated_cache() as cache_dir:
            run_id = _seed_run(cache_dir)
            _add_hyp(run_id, "hyp-grandparent")
            _add_hyp(run_id, "hyp-parent", agent="evolver", parent="hyp-grandparent")
            _add_hyp(run_id, "hyp-child", agent="evolver", parent="hyp-parent")
            r = _run(str(LEADERBOARD), "--run-id", run_id)
            result = json.loads(r.stdout)
            child = next(h for h in result["top"] if h["hyp_id"] == "hyp-child")
            # Should walk: grandparent → parent (root → direct)
            self.assertEqual(child["ancestors"], ["hyp-grandparent", "hyp-parent"])

    def test_markdown_format(self):
        with isolated_cache() as cache_dir:
            run_id = _seed_run(cache_dir)
            _add_hyp(run_id, "hyp-1")
            r = _run(str(LEADERBOARD), "--run-id", run_id, "--format", "md")
            self.assertIn("# Tournament leaderboard", r.stdout)
            self.assertIn("hyp-1", r.stdout)


# ---------------- Elo math unit ----------------

class EloMathTests(TestCase):
    def _import_match_mod(self):
        path = _ROOT / ".claude/skills/tournament/scripts/record_match.py"
        spec = importlib.util.spec_from_file_location("rm_mod", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_expected_score_symmetric(self):
        mod = self._import_match_mod()
        e = mod.expected_score(1200, 1200)
        self.assertEqual(round(e, 6), 0.5)

    def test_expected_score_400_diff_is_10x(self):
        mod = self._import_match_mod()
        # 400 Elo difference → expected 10/11 ≈ 0.909
        e = mod.expected_score(1600, 1200)
        self.assertEqual(round(e, 3), 0.909)

    def test_update_elo_zero_sum(self):
        mod = self._import_match_mod()
        new_a, new_b = mod.update_elo(1300, 1300, 1.0)
        # Same initial → win = +16 / -16
        self.assertEqual(round(new_a, 4), 1316.0)
        self.assertEqual(round(new_b, 4), 1284.0)
        # Symmetric
        self.assertEqual(round((new_a - 1300) + (new_b - 1300), 6), 0.0)


if __name__ == "__main__":
    sys.exit(run_tests(
        RecordHypothesisTests,
        RecordMatchTests,
        PairwiseTests,
        LeaderboardTests,
        EloMathTests,
    ))
