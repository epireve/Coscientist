"""Dry-run harness for the deep-research state machine.

Drives `.claude/skills/deep-research/scripts/db.py` end-to-end without
invoking any sub-agent or MCP. Catches mechanical bugs in the pipeline's
phase + break state machine — the boring stuff that would otherwise burn
real session time to surface.

Coverage:
- init writes 10 phases in the canonical order
- next-phase starts at `social`, advances correctly, fires BREAK_0/1/2
  in the right places, ends at DONE
- breaks: prompt-then-resolve gates phase advance; re-resolving is a no-op
- record-phase persists output_json + error
- record-claim persists with all optional fields
- resume reports run + phase state as JSON
- Migrations: opening a run DB applies migrations (calls ensure_current)
- Resume after partial phase: started_at set but completed_at NULL stays
  the current phase
"""

from tests import _shim  # noqa: F401

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
DB = _ROOT / ".claude/skills/deep-research/scripts/db.py"

PHASES = [
    "social", "grounder", "historian", "gaper", "vision",
    "theorist", "rude", "synthesizer", "thinker", "scribe",
]


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(DB), *args],
        capture_output=True, text=True,
    )


def _init(question: str = "Does scaling beat architecture for protein folding?") -> str:
    r = _run("init", "--question", question)
    assert r.returncode == 0, f"init failed: stderr={r.stderr}"
    return r.stdout.strip()


def _start(run_id: str, phase: str) -> None:
    r = _run("record-phase", "--run-id", run_id, "--phase", phase, "--start")
    assert r.returncode == 0, f"record-phase --start failed: {r.stderr}"


def _complete(run_id: str, phase: str, output: dict | None = None) -> None:
    args = ["record-phase", "--run-id", run_id, "--phase", phase, "--complete"]
    if output is not None:
        tmp = _ROOT / "tests" / f"_tmp_phase_{phase}.json"
        tmp.write_text(json.dumps(output))
        args += ["--output-json", str(tmp)]
    r = _run(*args)
    assert r.returncode == 0, f"record-phase --complete failed: {r.stderr}"


def _open_break(run_id: str, n: int) -> None:
    r = _run("record-break", "--run-id", run_id, "--break-number", str(n), "--prompt")
    assert r.returncode == 0, f"record-break --prompt failed: {r.stderr}"


def _resolve_break(run_id: str, n: int, user_input: str = "ok") -> None:
    r = _run("record-break", "--run-id", run_id, "--break-number", str(n),
             "--resolve", "--user-input", user_input)
    assert r.returncode == 0, f"record-break --resolve failed: {r.stderr}"


def _next_phase(run_id: str) -> str:
    r = _run("next-phase", "--run-id", run_id)
    assert r.returncode == 0, f"next-phase failed: {r.stderr}"
    return r.stdout.strip()


def _run_db(cache_dir: Path, run_id: str) -> Path:
    return cache_dir / "runs" / f"run-{run_id}.db"


# ---------------- init / schema ----------------

class InitTests(TestCase):
    def test_init_returns_run_id(self):
        with isolated_cache():
            run_id = _init()
            self.assertTrue(len(run_id) == 8,
                            f"expected 8-char hex run_id, got {run_id!r}")

    def test_init_writes_all_ten_phases_in_order(self):
        with isolated_cache() as cache_dir:
            run_id = _init()
            con = sqlite3.connect(_run_db(cache_dir, run_id))
            rows = con.execute(
                "SELECT name, ordinal FROM phases WHERE run_id=? ORDER BY ordinal",
                (run_id,),
            ).fetchall()
            con.close()
            self.assertEqual(len(rows), 10)
            self.assertEqual([r[0] for r in rows], PHASES)
            self.assertEqual([r[1] for r in rows], list(range(10)))

    def test_init_records_question_and_started_at(self):
        with isolated_cache() as cache_dir:
            run_id = _init("My research question")
            con = sqlite3.connect(_run_db(cache_dir, run_id))
            row = con.execute(
                "SELECT question, started_at FROM runs WHERE run_id=?", (run_id,),
            ).fetchone()
            con.close()
            self.assertEqual(row[0], "My research question")
            self.assertTrue(row[1] is not None and len(row[1]) > 0)

    def test_init_applies_migrations(self):
        """After init, the run DB should have schema_versions populated."""
        with isolated_cache() as cache_dir:
            run_id = _init()
            con = sqlite3.connect(_run_db(cache_dir, run_id))
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            self.assertIn("schema_versions", tables)
            applied = con.execute(
                "SELECT COUNT(*) FROM schema_versions"
            ).fetchone()[0]
            con.close()
            self.assertTrue(applied >= 1, f"no migrations applied; got {applied}")


# ---------------- next-phase state machine ----------------

class NextPhaseTests(TestCase):
    def test_fresh_run_returns_social(self):
        with isolated_cache():
            run_id = _init()
            self.assertEqual(_next_phase(run_id), "social")

    def test_in_progress_phase_still_returned(self):
        """started_at set but completed_at NULL should still report this phase."""
        with isolated_cache():
            run_id = _init()
            _start(run_id, "social")
            self.assertEqual(_next_phase(run_id), "social")

    def test_break_0_fires_after_social(self):
        with isolated_cache():
            run_id = _init()
            _start(run_id, "social")
            _complete(run_id, "social", {"papers": []})
            self.assertEqual(_next_phase(run_id), "BREAK_0")

    def test_break_0_unblocks_after_resolve(self):
        with isolated_cache():
            run_id = _init()
            _complete(run_id, "social")
            _open_break(run_id, 0)
            # Still BREAK_0 because not yet resolved
            self.assertEqual(_next_phase(run_id), "BREAK_0")
            _resolve_break(run_id, 0)
            self.assertEqual(_next_phase(run_id), "grounder")

    def test_break_1_fires_after_gaper(self):
        with isolated_cache():
            run_id = _init()
            for p in ("social",):
                _complete(run_id, p)
            _open_break(run_id, 0); _resolve_break(run_id, 0)
            for p in ("grounder", "historian", "gaper"):
                _complete(run_id, p)
            self.assertEqual(_next_phase(run_id), "BREAK_1")

    def test_break_2_fires_after_synthesizer(self):
        with isolated_cache():
            run_id = _init()
            for p in ("social",):
                _complete(run_id, p)
            _open_break(run_id, 0); _resolve_break(run_id, 0)
            for p in ("grounder", "historian", "gaper"):
                _complete(run_id, p)
            _open_break(run_id, 1); _resolve_break(run_id, 1)
            for p in ("vision", "theorist", "rude", "synthesizer"):
                _complete(run_id, p)
            self.assertEqual(_next_phase(run_id), "BREAK_2")

    def test_full_pipeline_reaches_done(self):
        """Drive every phase + every break in order; must end at DONE."""
        with isolated_cache():
            run_id = _init()
            _complete(run_id, "social")
            _open_break(run_id, 0); _resolve_break(run_id, 0)
            for p in ("grounder", "historian", "gaper"):
                _complete(run_id, p)
            _open_break(run_id, 1); _resolve_break(run_id, 1)
            for p in ("vision", "theorist", "rude", "synthesizer"):
                _complete(run_id, p)
            _open_break(run_id, 2); _resolve_break(run_id, 2)
            for p in ("thinker", "scribe"):
                _complete(run_id, p)
            self.assertEqual(_next_phase(run_id), "DONE")

    def test_break_implicit_when_never_opened(self):
        """If prev is completed and the break row was never created,
        next-phase should still report BREAK_<n>."""
        with isolated_cache():
            run_id = _init()
            _complete(run_id, "social")
            # Never call --prompt
            self.assertEqual(_next_phase(run_id), "BREAK_0")


# ---------------- record-phase output + errors ----------------

class PhaseOutputTests(TestCase):
    def test_complete_persists_output_json(self):
        with isolated_cache() as cache_dir:
            run_id = _init()
            payload = {"foundational_papers": ["a", "b"], "n": 2}
            _complete(run_id, "social", payload)

            con = sqlite3.connect(_run_db(cache_dir, run_id))
            row = con.execute(
                "SELECT output_json, completed_at FROM phases "
                "WHERE run_id=? AND name='social'", (run_id,),
            ).fetchone()
            con.close()
            self.assertTrue(row[1] is not None,
                            "completed_at should be set after --complete")
            self.assertEqual(json.loads(row[0]), payload)

    def test_error_persists(self):
        with isolated_cache() as cache_dir:
            run_id = _init()
            r = _run("record-phase", "--run-id", run_id, "--phase", "social",
                     "--error", "MCP timeout after 3 retries")
            assert r.returncode == 0, r.stderr
            con = sqlite3.connect(_run_db(cache_dir, run_id))
            err = con.execute(
                "SELECT error FROM phases WHERE run_id=? AND name='social'",
                (run_id,),
            ).fetchone()[0]
            con.close()
            self.assertEqual(err, "MCP timeout after 3 retries")

    def test_start_then_complete_records_both_timestamps(self):
        with isolated_cache() as cache_dir:
            run_id = _init()
            _start(run_id, "grounder")
            _complete(run_id, "grounder")
            con = sqlite3.connect(_run_db(cache_dir, run_id))
            row = con.execute(
                "SELECT started_at, completed_at FROM phases "
                "WHERE run_id=? AND name='grounder'", (run_id,),
            ).fetchone()
            con.close()
            self.assertTrue(row[0] is not None and len(row[0]) > 0,
                            "started_at not set")
            self.assertTrue(row[1] is not None and len(row[1]) > 0,
                            "completed_at not set")


# ---------------- record-claim ----------------

class ClaimTests(TestCase):
    def test_claim_with_full_args(self):
        with isolated_cache() as cache_dir:
            run_id = _init()
            r = _run(
                "record-claim", "--run-id", run_id,
                "--agent-name", "grounder",
                "--text", "Transformers scale well.",
                "--kind", "finding",
                "--canonical-id", "vaswani_2017_attn_a1b2c3",
                "--confidence", "0.85",
                "--supporting-ids", "vaswani_2017_attn_a1b2c3,kaplan_2020_scaling_d4e5f6",
            )
            assert r.returncode == 0, r.stderr

            con = sqlite3.connect(_run_db(cache_dir, run_id))
            row = con.execute(
                "SELECT agent_name, text, kind, confidence, supporting_ids, canonical_id "
                "FROM claims WHERE run_id=?", (run_id,),
            ).fetchone()
            con.close()
            self.assertEqual(row[0], "grounder")
            self.assertEqual(row[1], "Transformers scale well.")
            self.assertEqual(row[2], "finding")
            self.assertAlmostEqual(row[3], 0.85, places=5)
            supp = json.loads(row[4])
            self.assertEqual(len(supp), 2)
            self.assertEqual(row[5], "vaswani_2017_attn_a1b2c3")

    def test_claim_with_minimal_args(self):
        with isolated_cache() as cache_dir:
            run_id = _init()
            r = _run(
                "record-claim", "--run-id", run_id,
                "--agent-name", "social",
                "--text", "Bare minimum claim.",
            )
            assert r.returncode == 0, r.stderr
            con = sqlite3.connect(_run_db(cache_dir, run_id))
            row = con.execute(
                "SELECT agent_name, kind, confidence, supporting_ids, canonical_id "
                "FROM claims WHERE run_id=?", (run_id,),
            ).fetchone()
            con.close()
            self.assertEqual(row[0], "social")
            self.assertEqual(row[1], "finding")  # default
            self.assertTrue(row[2] is None)
            self.assertTrue(row[3] is None)
            self.assertTrue(row[4] is None)


# ---------------- resume ----------------

class ResumeTests(TestCase):
    def test_resume_returns_state_json(self):
        with isolated_cache():
            run_id = _init("Specific resume question")
            _complete(run_id, "social")
            r = _run("resume", "--run-id", run_id)
            assert r.returncode == 0, r.stderr
            state = json.loads(r.stdout)
            self.assertEqual(state["run_id"], run_id)
            self.assertEqual(state["question"], "Specific resume question")
            self.assertEqual(len(state["phases"]), 10)
            social = next(p for p in state["phases"] if p["name"] == "social")
            self.assertTrue(social["completed_at"] is not None)
            grounder = next(p for p in state["phases"] if p["name"] == "grounder")
            self.assertTrue(grounder["completed_at"] is None)

    def test_resume_unknown_run_id_errors(self):
        with isolated_cache():
            r = _run("resume", "--run-id", "deadbeef")
            self.assertTrue(r.returncode != 0)
            self.assertIn("no such run", r.stderr)

    def test_resume_after_started_but_uncompleted_phase(self):
        """A phase started but not completed (crash mid-phase) must remain
        the current phase under resume + next-phase."""
        with isolated_cache():
            run_id = _init()
            _complete(run_id, "social")
            _open_break(run_id, 0); _resolve_break(run_id, 0)
            _start(run_id, "grounder")
            # Crash here — grounder has started_at but not completed_at
            self.assertEqual(_next_phase(run_id), "grounder")
            r = _run("resume", "--run-id", run_id)
            state = json.loads(r.stdout)
            grounder = next(p for p in state["phases"] if p["name"] == "grounder")
            self.assertTrue(grounder["started_at"] is not None)
            self.assertTrue(grounder["completed_at"] is None)


# ---------------- break idempotency ----------------

class BreakIdempotencyTests(TestCase):
    def test_resolving_already_resolved_break_is_noop(self):
        """Re-resolving must not overwrite the original user_input."""
        with isolated_cache() as cache_dir:
            run_id = _init()
            _complete(run_id, "social")
            _open_break(run_id, 0)
            _resolve_break(run_id, 0, user_input="first answer")
            _resolve_break(run_id, 0, user_input="second answer")

            con = sqlite3.connect(_run_db(cache_dir, run_id))
            row = con.execute(
                "SELECT user_input FROM breaks WHERE run_id=? AND break_number=0",
                (run_id,),
            ).fetchone()
            con.close()
            self.assertEqual(row[0], "first answer",
                             "second --resolve must be a no-op once resolved")


# ---------------- edge cases (cracks the orchestrator can hit) ----------------

class EdgeCaseTests(TestCase):
    def test_unknown_phase_name_rejected(self):
        """An LLM-orchestrator typo (e.g. 'theroist' for 'theorist') must
        error rather than silently no-op the UPDATE — otherwise the run
        state diverges silently from what the orchestrator believes."""
        with isolated_cache():
            run_id = _init()
            r = _run("record-phase", "--run-id", run_id, "--phase", "theroist",
                     "--complete")
            self.assertTrue(r.returncode != 0,
                            "unknown phase name must be rejected")
            self.assertIn("unknown phase", r.stderr.lower())

    def test_double_complete_overwrites_silently(self):
        """Documents current behavior: second --complete overwrites the
        first's output_json + completed_at. Not a bug per se — but
        orchestrators should know that resume + re-complete is destructive
        to phase output. If this becomes a problem, switch to INSERT-only
        with a phase_run table."""
        with isolated_cache() as cache_dir:
            run_id = _init()
            _complete(run_id, "social", {"first": True})
            _complete(run_id, "social", {"second": True})
            con = sqlite3.connect(_run_db(cache_dir, run_id))
            out = con.execute(
                "SELECT output_json FROM phases "
                "WHERE run_id=? AND name='social'", (run_id,),
            ).fetchone()[0]
            con.close()
            self.assertEqual(json.loads(out), {"second": True},
                             "second --complete should overwrite output_json")

    def test_out_of_order_complete_does_not_skip_intermediate(self):
        """If the orchestrator completes 'theorist' before 'vision',
        next-phase must still return 'vision' — not jump ahead. Documents
        that next-phase scans for the first incomplete phase, not the
        highest completed one."""
        with isolated_cache():
            run_id = _init()
            _complete(run_id, "social")
            _open_break(run_id, 0); _resolve_break(run_id, 0)
            for p in ("grounder", "historian", "gaper"):
                _complete(run_id, p)
            _open_break(run_id, 1); _resolve_break(run_id, 1)
            # Skip vision, jump to theorist
            _complete(run_id, "theorist")
            self.assertEqual(_next_phase(run_id), "vision",
                             "vision was skipped — next-phase must still flag it")


if __name__ == "__main__":
    sys.exit(run_tests(
        InitTests,
        NextPhaseTests,
        PhaseOutputTests,
        ClaimTests,
        ResumeTests,
        BreakIdempotencyTests,
        EdgeCaseTests,
    ))
