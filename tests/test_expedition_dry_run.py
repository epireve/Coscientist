"""v0.50 — Full Expedition pipeline dry-run integration test (Plan 5 Stage 5 prep).

Drives the entire 10-phase pipeline end-to-end with synthetic data:
  1. Create project + run
  2. For each search-using persona (scout, cartographer, chronicler,
     surveyor, architect, visionary), feed mock MCP results through
     harvest.py write
  3. Verify shortlists land where db.py resume expects them
  4. Record start + complete on each of the 10 phases
  5. Record + resolve all 3 breaks at the right points
  6. Verify final state: 10 phases completed, 3 breaks resolved,
     6 shortlist files, run status updated

This proves Stage 1-4 glue holds without needing a real /deep-research
run with live MCPs. The remaining Stage 5 work — actually running a
sub-agent against a real shortlist and getting a real persona output —
still requires the user.
"""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
DB = _ROOT / ".claude/skills/deep-research/scripts/db.py"
HARVEST = _ROOT / ".claude/skills/deep-research/scripts/harvest.py"


def _db(*args: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(DB), *args],
        input=stdin, capture_output=True, text=True,
    )


def _harvest(*args: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HARVEST), *args],
        input=stdin, capture_output=True, text=True,
    )


def _mock_mcp_results(n: int = 3) -> list[dict]:
    return [
        {"source": "consensus",
         "title": f"Mock Paper {i}",
         "doi": f"10.9999/mock.{i}",
         "year": 2024,
         "authors": [f"Author {i}"],
         "abstract": f"Mock abstract {i}.",
         "citation_count": 10 - i}
        for i in range(n)
    ]


# Per-persona expected harvest phase mapping (matches db.py expected_harvests)
HARVEST_MAP = [
    ("scout", "phase0"),
    ("cartographer", "phase1"),
    ("chronicler", "phase1"),
    ("surveyor", "phase1"),
    ("architect", "phase2"),
    ("visionary", "phase3"),
]

# Full Expedition pipeline order (matches db.py PHASES_IN_ORDER)
PHASES = [
    "scout", "cartographer", "chronicler", "surveyor",
    "synthesist", "architect", "inquisitor", "weaver",
    "visionary", "steward",
]


class FullPipelineTests(TestCase):
    def test_init_returns_run_id_and_creates_phases(self):
        with isolated_cache():
            r = _db("init", "--question", "test question")
            self.assertEqual(r.returncode, 0, r.stderr)
            run_id = r.stdout.strip()
            self.assertTrue(len(run_id) > 0)

            from lib.cache import run_db_path
            con = sqlite3.connect(run_db_path(run_id))
            phases = [r[0] for r in con.execute(
                "SELECT name FROM phases WHERE run_id=? ORDER BY ordinal",
                (run_id,),
            )]
            con.close()
            self.assertEqual(phases, PHASES)

    def test_harvest_lands_at_expected_paths(self):
        with isolated_cache():
            run_id = _db("init", "--question", "q").stdout.strip()
            for persona, phase in HARVEST_MAP:
                r = _harvest(
                    "write", "--run-id", run_id,
                    "--persona", persona, "--phase", phase,
                    "--query", "q",
                    stdin=json.dumps(_mock_mcp_results()),
                )
                self.assertEqual(r.returncode, 0, r.stderr)

            from lib.persona_input import exists, list_for_run
            for persona, phase in HARVEST_MAP:
                self.assertTrue(exists(run_id, persona, phase),
                                f"shortlist missing for {persona}/{phase}")
            self.assertEqual(len(list_for_run(run_id)), 6)

    def test_resume_reports_harvest_status_correctly(self):
        with isolated_cache():
            run_id = _db("init", "--question", "q").stdout.strip()
            # Harvest only first 2 personas
            for persona, phase in HARVEST_MAP[:2]:
                _harvest(
                    "write", "--run-id", run_id,
                    "--persona", persona, "--phase", phase,
                    "--query", "q",
                    stdin=json.dumps(_mock_mcp_results()),
                )
            r = _db("resume", "--run-id", run_id)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            present = {h["persona"]: h["shortlist_present"]
                        for h in out["harvests"]}
            # First 2 harvested
            self.assertTrue(present["scout"])
            self.assertTrue(present["cartographer"])
            # Rest absent
            self.assertFalse(present["chronicler"])
            self.assertFalse(present["visionary"])

    def test_full_pipeline_records_all_10_phases_3_breaks(self):
        """End-to-end: harvest, record-phase start+complete on all 10
        phases, record-break prompt+resolve at break-points 0/1/2."""
        with isolated_cache():
            run_id = _db("init", "--question", "test").stdout.strip()

            # Stage 1: harvest for all 6 search-using personas
            for persona, phase in HARVEST_MAP:
                r = _harvest(
                    "write", "--run-id", run_id,
                    "--persona", persona, "--phase", phase,
                    "--query", "test",
                    stdin=json.dumps(_mock_mcp_results()),
                )
                self.assertEqual(r.returncode, 0, r.stderr)

            # Stage 2: walk all 10 phases, recording breaks at the right
            # points. BREAK_AFTER = {scout:0, surveyor:1, weaver:2}
            break_after = {"scout": 0, "surveyor": 1, "weaver": 2}
            for phase in PHASES:
                r = _db("record-phase", "--run-id", run_id,
                          "--phase", phase, "--start")
                self.assertEqual(r.returncode, 0, r.stderr)
                output = {"phase": phase, "result": "ok"}
                output_path = Path(f"/tmp/_exp_out_{phase}.json")
                output_path.write_text(json.dumps(output))
                r = _db("record-phase", "--run-id", run_id,
                          "--phase", phase, "--complete",
                          "--output-json", str(output_path))
                self.assertEqual(r.returncode, 0, r.stderr)
                output_path.unlink(missing_ok=True)

                if phase in break_after:
                    bn = break_after[phase]
                    r = _db("record-break", "--run-id", run_id,
                              "--break-number", str(bn), "--prompt")
                    self.assertEqual(r.returncode, 0, r.stderr)
                    r = _db("record-break", "--run-id", run_id,
                              "--break-number", str(bn), "--resolve",
                              "--user-input", "continue")
                    self.assertEqual(r.returncode, 0, r.stderr)

            # Stage 3: verify final state
            from lib.cache import run_db_path
            con = sqlite3.connect(run_db_path(run_id))
            n_completed = con.execute(
                "SELECT COUNT(*) FROM phases WHERE run_id=? "
                "AND completed_at IS NOT NULL", (run_id,),
            ).fetchone()[0]
            n_breaks_resolved = con.execute(
                "SELECT COUNT(*) FROM breaks WHERE run_id=? "
                "AND resolved_at IS NOT NULL", (run_id,),
            ).fetchone()[0]
            con.close()
            self.assertEqual(n_completed, 10,
                             "all 10 Expedition phases must complete")
            self.assertEqual(n_breaks_resolved, 3,
                             "all 3 break-points must resolve")

    def test_old_seeker_phase_alias_resolves(self):
        """In-flight runs from before v0.46.4 use old SEEKER names.
        record-phase with --phase social must silently rewrite to scout."""
        with isolated_cache():
            run_id = _db("init", "--question", "alias").stdout.strip()
            r = _db("record-phase", "--run-id", run_id,
                      "--phase", "social", "--start")
            self.assertEqual(r.returncode, 0, r.stderr)
            # Verify the underlying row is `scout`
            from lib.cache import run_db_path
            con = sqlite3.connect(run_db_path(run_id))
            row = con.execute(
                "SELECT started_at FROM phases "
                "WHERE run_id=? AND name='scout'", (run_id,),
            ).fetchone()
            con.close()
            self.assertIsNotNone(row[0],
                                  "alias 'social' should write to 'scout' row")

    def test_unknown_phase_rejected(self):
        with isolated_cache():
            run_id = _db("init", "--question", "q").stdout.strip()
            r = _db("record-phase", "--run-id", run_id,
                      "--phase", "nonexistent_phase", "--start")
            self.assertTrue(r.returncode != 0)
            self.assertIn("unknown phase", r.stderr)


if __name__ == "__main__":
    sys.exit(run_tests(FullPipelineTests))
