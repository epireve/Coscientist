"""v0.52.2 — search-strategy-critique gate tests."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
GATE = _ROOT / ".claude/skills/search-strategy-critique/scripts/gate.py"
DB = _ROOT / ".claude/skills/deep-research/scripts/db.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GATE), *args],
        capture_output=True, text=True,
    )


def _db(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(DB), *args],
        capture_output=True, text=True,
    )


VALID_CRITIQUE = {
    "blind_spots": [
        {"angle": "Founder rift between forgetting-as-feature vs deficit",
         "why_missed": "All sub-areas treat forgetting as one mechanism.",
         "severity": "high"}
    ],
    "missing_anti_coverage": [
        {"sub_area": "Memory aids: augment recall",
         "opposing_view": "Memory aids cause metamemory distortion",
         "why_needed": "Without it, corpus is pro-augmentation biased."}
    ],
    "redundant_sub_areas": [],
    "premature_commitments": [
        {"sub_area": "Core mechanism",
         "assumption": "Forgetting is one mechanism",
         "could_be_false_if": "ML-unlearning ≠ Ebbinghaus."}
    ],
    "coverage_asymmetry": [],
    "verdict": "revise",
    "recommendation": "Add anti-coverage sub-area covering forgetting-as-harm.",
    "confidence": 0.85
}


class ValidateTests(TestCase):
    def _write(self, cache_dir: Path, payload: dict) -> Path:
        p = cache_dir / "critique.json"
        p.write_text(json.dumps(payload))
        return p

    def test_valid_critique_passes(self):
        with isolated_cache() as cache_dir:
            p = self._write(cache_dir, VALID_CRITIQUE)
            r = _run("validate", "--input", str(p))
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertTrue(out["ok"])
            self.assertEqual(out["verdict"], "revise")

    def test_high_severity_with_accept_verdict_rejected(self):
        with isolated_cache() as cache_dir:
            bad = dict(VALID_CRITIQUE, verdict="accept")
            p = self._write(cache_dir, bad)
            r = _run("validate", "--input", str(p))
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertFalse(out["ok"])
            self.assertTrue(any("verdict 'accept'" in e for e in out["errors"]))

    def test_hedge_words_rejected(self):
        with isolated_cache() as cache_dir:
            bad = dict(VALID_CRITIQUE,
                       recommendation="Maybe consider adding a sub-area.")
            p = self._write(cache_dir, bad)
            r = _run("validate", "--input", str(p))
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertFalse(out["ok"])
            self.assertTrue(any("hedge" in e for e in out["errors"]))

    def test_missing_confidence_rejected(self):
        with isolated_cache() as cache_dir:
            bad = {k: v for k, v in VALID_CRITIQUE.items()
                    if k != "confidence"}
            p = self._write(cache_dir, bad)
            r = _run("validate", "--input", str(p))
            out = json.loads(r.stdout)
            self.assertFalse(out["ok"])
            self.assertTrue(any("confidence" in e for e in out["errors"]))

    def test_confidence_out_of_range_rejected(self):
        with isolated_cache() as cache_dir:
            bad = dict(VALID_CRITIQUE, confidence=1.5)
            p = self._write(cache_dir, bad)
            r = _run("validate", "--input", str(p))
            out = json.loads(r.stdout)
            self.assertFalse(out["ok"])
            self.assertTrue(any("range" in e for e in out["errors"]))

    def test_abstract_finding_rejected(self):
        with isolated_cache() as cache_dir:
            bad = dict(VALID_CRITIQUE,
                       missing_anti_coverage=[
                           {"opposing_view": "x", "why_needed": "y"}
                           # Missing sub_area / component / phrasing
                       ])
            p = self._write(cache_dir, bad)
            r = _run("validate", "--input", str(p))
            out = json.loads(r.stdout)
            self.assertFalse(out["ok"])
            self.assertTrue(any("abstract" in e or "specific" in e
                                 for e in out["errors"]))


class PersistTests(TestCase):
    def test_persist_writes_to_runs_strategy_critique_json(self):
        with isolated_cache() as cache_dir:
            r = _db("init", "--question", "test critique persist")
            self.assertEqual(r.returncode, 0, r.stderr)
            run_id = r.stdout.strip()

            p = cache_dir / "critique.json"
            p.write_text(json.dumps(VALID_CRITIQUE))

            r = _run("persist", "--run-id", run_id, "--input", str(p))
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertTrue(out["ok"])

            # Verify DB row
            from lib.cache import run_db_path
            con = sqlite3.connect(run_db_path(run_id))
            row = con.execute(
                "SELECT strategy_critique_json FROM runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            con.close()
            self.assertIsNotNone(row[0])
            persisted = json.loads(row[0])
            self.assertEqual(persisted["verdict"], "revise")
            self.assertEqual(persisted["confidence"], 0.85)

    def test_persist_refuses_invalid_without_force(self):
        with isolated_cache() as cache_dir:
            r = _db("init", "--question", "test")
            run_id = r.stdout.strip()
            bad = dict(VALID_CRITIQUE, verdict="accept")
            p = cache_dir / "critique.json"
            p.write_text(json.dumps(bad))
            r = _run("persist", "--run-id", run_id, "--input", str(p))
            self.assertTrue(r.returncode != 0)
            self.assertIn("validation failed", r.stderr)

    def test_persist_force_writes_with_warnings(self):
        with isolated_cache() as cache_dir:
            r = _db("init", "--question", "test")
            run_id = r.stdout.strip()
            bad = dict(VALID_CRITIQUE, verdict="accept")
            p = cache_dir / "critique.json"
            p.write_text(json.dumps(bad))
            r = _run("persist", "--run-id", run_id, "--input", str(p),
                      "--force")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertTrue(out["ok"])
            self.assertTrue(len(out["validation_warnings"]) > 0)


if __name__ == "__main__":
    sys.exit(run_tests(ValidateTests, PersistTests))
