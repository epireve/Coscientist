"""v0.12.1 hardening tests.

Covers the five low-cost fixes:
1. PDF magic-bytes integrity check in paper-acquire/record.py
4. Anchor uniqueness (5 distinct canonical_ids) in novelty-check gate
5. Hedge-word context awareness — skip quoted spans (5 gates)
6. Tournament K-factor decay by n_matches
10. Calibration-set hard-fail when present but unreferenced
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

ACQUIRE_RECORD = _ROOT / ".claude/skills/paper-acquire/scripts/record.py"
ACQUIRE_GATE = _ROOT / ".claude/skills/paper-acquire/scripts/gate.py"
TRIAGE_RECORD = _ROOT / ".claude/skills/paper-triage/scripts/record.py"
NOVELTY_GATE = _ROOT / ".claude/skills/novelty-check/scripts/gate.py"
PUB_GATE = _ROOT / ".claude/skills/publishability-check/scripts/gate.py"
AUDIT_GATE = _ROOT / ".claude/skills/manuscript-audit/scripts/gate.py"
CRITIQUE_GATE = _ROOT / ".claude/skills/manuscript-critique/scripts/gate.py"
REFLECT_GATE = _ROOT / ".claude/skills/manuscript-reflect/scripts/gate.py"
RECORD_HYP = _ROOT / ".claude/skills/tournament/scripts/record_hypothesis.py"
RECORD_MATCH = _ROOT / ".claude/skills/tournament/scripts/record_match.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True, text=True)


def _run_with_input(script: Path, input_json, *args: str) -> subprocess.CompletedProcess:
    tmp = _ROOT / "tests" / "_tmp_input.json"
    tmp.write_text(json.dumps(input_json))
    return _run(str(script), "--input", str(tmp), *args)


# ---------------- Fix 1: PDF integrity ----------------

class PdfIntegrityTests(TestCase):
    def _seed_paper(self, cache_dir: Path, cid: str = "test_paper_xyz") -> str:
        paper_dir = cache_dir / "papers" / cid
        paper_dir.mkdir(parents=True, exist_ok=True)
        for sub in ("figures", "tables", "raw"):
            (paper_dir / sub).mkdir(exist_ok=True)
        (paper_dir / "manifest.json").write_text(json.dumps({
            "canonical_id": cid, "state": "triaged",
            "triage": {"sufficient": False, "rationale": "need full text",
                       "at": "2026-04-24T00:00:00Z"},
            "sources_tried": [], "created_at": "2026-04-24T00:00:00Z",
            "updated_at": "2026-04-24T00:00:00Z",
        }))
        return cid

    def test_record_accepts_real_pdf(self):
        with isolated_cache() as cache_dir:
            cid = self._seed_paper(cache_dir)
            pdf = cache_dir / "fake.pdf"
            pdf.write_bytes(b"%PDF-1.4\n" + b"x" * 500)
            r = _run(str(ACQUIRE_RECORD),
                     "--canonical-id", cid, "--source", "arxiv",
                     "--pdf-path", str(pdf))
            assert r.returncode == 0, f"stderr={r.stderr}"
            entry = json.loads(r.stdout)
            self.assertIn("bytes", entry)

    def test_record_rejects_html_masquerading_as_pdf(self):
        with isolated_cache() as cache_dir:
            cid = self._seed_paper(cache_dir)
            html = cache_dir / "paywall.pdf"
            # Pad past the size threshold so we exercise the magic-bytes check
            html.write_text(
                "<html><body>"
                + "Subscription required to view this article. " * 20
                + "</body></html>"
            )
            r = _run(str(ACQUIRE_RECORD),
                     "--canonical-id", cid, "--source", "elsevier",
                     "--pdf-path", str(html))
            self.assertEqual(r.returncode, 1)
            self.assertIn("not a PDF", r.stderr)

    def test_record_rejects_too_small(self):
        with isolated_cache() as cache_dir:
            cid = self._seed_paper(cache_dir)
            tiny = cache_dir / "tiny.pdf"
            tiny.write_bytes(b"%PDF-1.4\n")  # valid magic but only 9 bytes
            r = _run(str(ACQUIRE_RECORD),
                     "--canonical-id", cid, "--source", "tier1",
                     "--pdf-path", str(tiny))
            self.assertEqual(r.returncode, 1)
            self.assertIn("too small", r.stderr)


# ---------------- Fix 4: Anchor uniqueness ----------------

class NoveltyAnchorUniquenessTests(TestCase):
    def _make_report(self, anchor_cids: list[str]) -> dict:
        return {
            "contributions": [{
                "id": "contrib-1",
                "claim": "X scales",
                "decomposition": {
                    "method": "M", "domain": "D",
                    "finding": "F", "metric": "score",
                },
                "anchors": [
                    {"canonical_id": cid, "closest_aspect": "method",
                     "delta": "different setup",
                     "delta_sufficient": True}
                    for cid in anchor_cids
                ],
                "verdict": "novel",
                "confidence": 0.7,
                "reasoning": "Method X applied to domain D with measurable delta.",
            }]
        }

    def test_five_distinct_anchors_pass(self):
        with isolated_cache():
            r = _run_with_input(NOVELTY_GATE, self._make_report(
                [f"paper_{i}" for i in range(5)]
            ), "--target-canonical-id", "t")
            assert r.returncode == 0, f"stderr={r.stderr}"

    def test_five_copies_of_same_anchor_rejected(self):
        with isolated_cache():
            r = _run_with_input(NOVELTY_GATE, self._make_report(
                ["same_paper"] * 5
            ), "--target-canonical-id", "t")
            self.assertEqual(r.returncode, 2)
            self.assertIn("unique canonical_ids", r.stderr)

    def test_three_distinct_two_dups_rejected(self):
        with isolated_cache():
            cids = ["a", "b", "c", "a", "b"]
            r = _run_with_input(NOVELTY_GATE, self._make_report(cids),
                                "--target-canonical-id", "t")
            self.assertEqual(r.returncode, 2)


# ---------------- Fix 5: Hedge-word quoted-context awareness ----------------

class HedgeQuotedContextTests(TestCase):
    """Hedge words inside quoted spans should not be flagged."""

    def test_novelty_gate_allows_quoted_hedge(self):
        with isolated_cache():
            report = {
                "contributions": [{
                    "id": "contrib-1",
                    "claim": "X works",
                    "decomposition": {
                        "method": "M", "domain": "D",
                        "finding": "F", "metric": "score",
                    },
                    "anchors": [
                        {"canonical_id": f"p{i}", "closest_aspect": "method",
                         "delta": "X", "delta_sufficient": True}
                        for i in range(5)
                    ],
                    "verdict": "novel",
                    "confidence": 0.7,
                    # Quoted hedge — not the auditor's hedge
                    "reasoning": 'The authors say it "might" work; we confirm it does.',
                }]
            }
            r = _run_with_input(NOVELTY_GATE, report,
                                "--target-canonical-id", "t")
            assert r.returncode == 0, f"stderr={r.stderr}"

    def test_novelty_gate_still_catches_bare_hedge(self):
        with isolated_cache():
            report = {
                "contributions": [{
                    "id": "contrib-1",
                    "claim": "X works",
                    "decomposition": {
                        "method": "M", "domain": "D",
                        "finding": "F", "metric": "score",
                    },
                    "anchors": [
                        {"canonical_id": f"p{i}", "closest_aspect": "method",
                         "delta": "X", "delta_sufficient": True}
                        for i in range(5)
                    ],
                    "verdict": "novel",
                    "confidence": 0.7,
                    "reasoning": "This might be novel without context.",
                }]
            }
            r = _run_with_input(NOVELTY_GATE, report,
                                "--target-canonical-id", "t")
            self.assertEqual(r.returncode, 2)
            self.assertIn("hedge word", r.stderr)

    def test_audit_gate_allows_quoted_hedge_in_evidence(self):
        with isolated_cache():
            report = {
                "manuscript_id": "ms",
                "claims": [{
                    "claim_id": "c-1",
                    "text": "We show X.",
                    "location": "§1",
                    "cited_sources": [],
                    "findings": [{
                        "kind": "uncited",
                        "severity": "minor",
                        # Quoted hedge — fine
                        "evidence": 'The cited paper says X "might" hold; manuscript states it as fact.',
                    }],
                }],
            }
            r = _run_with_input(AUDIT_GATE, report, "--manuscript-id", "ms")
            assert r.returncode == 0, f"stderr={r.stderr}"

    def test_critique_gate_allows_quoted_hedge_in_summary(self):
        with isolated_cache():
            report = {
                "manuscript_id": "ms",
                "reviewers": {
                    "methodological": {"findings": [],
                                       "summary": 'The methods are sound; reviewer 2 said they "may" disagree.'},
                    "theoretical": {"findings": [], "summary": "no issues."},
                    "big_picture": {"findings": [], "summary": "no issues."},
                    "nitpicky": {"findings": [], "summary": "no issues."},
                },
                "overall_verdict": "borderline",
                "confidence": 0.5,
            }
            r = _run_with_input(CRITIQUE_GATE, report, "--manuscript-id", "ms")
            assert r.returncode == 0, f"stderr={r.stderr}"

    def test_reflect_gate_allows_quoted_hedge(self):
        with isolated_cache():
            report = {
                "manuscript_id": "ms",
                "argument_structure": {
                    "thesis": 'Scale wins, despite reviewers who said it "might" not.',
                    "premises": ["a", "b"],
                    "evidence_chain": [{"claim": "x",
                                         "evidence": ["self"], "strength": 0.7}],
                    "conclusion": "Confirmed.",
                },
                "implicit_assumptions": [
                    {"assumption": "A", "fragility": "low",
                     "consequence_if_false": "X"},
                    {"assumption": "B", "fragility": "medium",
                     "consequence_if_false": "Y"},
                ],
                "weakest_link": {"what": "n=3 seeds",
                                 "why": "unstable estimates"},
                "one_experiment": {"description": "Run 10 seeds on dataset X",
                                   "expected_impact": "Stabilizes",
                                   "cost_estimate": "days"},
            }
            r = _run_with_input(REFLECT_GATE, report, "--manuscript-id", "ms")
            assert r.returncode == 0, f"stderr={r.stderr}"


# ---------------- Fix 6: K-factor decay ----------------

class KFactorDecayTests(TestCase):
    def _import_module(self):
        path = _ROOT / ".claude/skills/tournament/scripts/record_match.py"
        spec = importlib.util.spec_from_file_location("record_match_v121", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_k_factor_decay_levels(self):
        mod = self._import_module()
        self.assertEqual(mod.k_factor(0), 32.0)
        self.assertEqual(mod.k_factor(4), 32.0)
        self.assertEqual(mod.k_factor(5), 16.0)
        self.assertEqual(mod.k_factor(14), 16.0)
        self.assertEqual(mod.k_factor(15), 8.0)
        self.assertEqual(mod.k_factor(100), 8.0)

    def test_established_player_smaller_swing(self):
        """A win against an equal opponent moves a fresh player by 16,
        but an established player by only 4.
        """
        mod = self._import_module()
        # Fresh: K=32, equal ratings, win → +16
        new_a, new_b = mod.update_elo(1200, 1200, 1.0, k_a=32.0, k_b=32.0)
        self.assertAlmostEqual(new_a - 1200, 16.0, places=2)
        # Established: K=8, equal ratings, win → +4
        new_a2, new_b2 = mod.update_elo(1200, 1200, 1.0, k_a=8.0, k_b=8.0)
        self.assertAlmostEqual(new_a2 - 1200, 4.0, places=2)

    def test_record_match_uses_n_matches_for_k(self):
        with isolated_cache() as cache_dir:
            run_id = "ktest"
            run_db = cache_dir / "runs" / f"run-{run_id}.db"
            run_db.parent.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(run_db)
            con.executescript(SCHEMA)
            con.execute(
                "INSERT INTO runs (run_id, question, started_at) "
                "VALUES (?, 'q', '2026-04-24T00:00:00Z')", (run_id,)
            )
            # Two hypotheses: hyp-a is established (n_matches=20), hyp-b is fresh (0)
            con.execute(
                "INSERT INTO hypotheses "
                "(hyp_id, run_id, agent_name, statement, elo, n_matches, "
                "n_wins, n_losses, created_at) "
                "VALUES ('hyp-a', ?, 'theorist', 'A', 1200.0, 20, 10, 10, ?)",
                (run_id, "2026-04-24T00:00:00Z"),
            )
            con.execute(
                "INSERT INTO hypotheses "
                "(hyp_id, run_id, agent_name, statement, elo, n_matches, "
                "n_wins, n_losses, created_at) "
                "VALUES ('hyp-b', ?, 'theorist', 'B', 1200.0, 0, 0, 0, ?)",
                (run_id, "2026-04-24T00:00:00Z"),
            )
            con.commit()
            con.close()

            # hyp-a wins
            r = _run(str(RECORD_MATCH), "--run-id", run_id,
                     "--hyp-a", "hyp-a", "--hyp-b", "hyp-b",
                     "--winner", "hyp-a")
            assert r.returncode == 0, f"stderr={r.stderr}"
            result = json.loads(r.stdout)
            # hyp-a (established, K=8) gains less than hyp-b (fresh, K=32) loses
            self.assertAlmostEqual(result["delta_a"], 4.0, delta=0.5)
            self.assertAlmostEqual(result["delta_b"], -16.0, delta=0.5)


# ---------------- Fix 10: Calibration hard-fail ----------------

class CalibrationHardFailTests(TestCase):
    def _valid_report(self) -> dict:
        return {
            "venues": [{
                "venue": "NeurIPS 2026",
                "verdict": "borderline-with-revisions",
                "probability_of_acceptance": 0.45,
                "factors_up": [
                    {"factor": "Strong empirical results", "weight": 0.4},
                    {"factor": "Clear writing", "weight": 0.2},
                    {"factor": "Timely topic", "weight": 0.3},
                ],
                "factors_down": [
                    {"factor": "Limited baselines", "weight": -0.4},
                    {"factor": "No code release", "weight": -0.3},
                    {"factor": "Missing ablations", "weight": -0.2},
                ],
                "kill_criterion": "If the ablation table reveals collapse at 10% data, flip to reject.",
                "tier_up_requirements": "Full ablations + code release.",
                "reasoning": "Core contribution is tight but evaluation is thin.",
            }]
        }

    def test_no_calibration_dir_passes(self):
        with isolated_cache():
            r = _run_with_input(PUB_GATE, self._valid_report(),
                                "--target-manuscript-id", "ms")
            assert r.returncode == 0, f"stderr={r.stderr}"

    def test_calibration_present_but_unreferenced_fails(self):
        with isolated_cache() as cache_dir:
            # Create a calibration set
            cal_dir = cache_dir / "calibration" / "venues"
            cal_dir.mkdir(parents=True)
            (cal_dir / "neurips-2026.json").write_text(json.dumps({
                "venue": "NeurIPS 2026",
                "accepted": [{"title": "Some Real Paper",
                              "reasons_for_accept": []}],
                "rejected": [], "borderline": [],
            }))
            r = _run_with_input(PUB_GATE, self._valid_report(),
                                "--target-manuscript-id", "ms")
            self.assertEqual(r.returncode, 2)
            self.assertIn("calibration", r.stderr.lower())

    def test_allow_uncalibrated_flag_overrides(self):
        with isolated_cache() as cache_dir:
            cal_dir = cache_dir / "calibration" / "venues"
            cal_dir.mkdir(parents=True)
            (cal_dir / "neurips-2026.json").write_text(json.dumps({
                "venue": "NeurIPS 2026",
                "accepted": [{"title": "Some Real Paper",
                              "reasons_for_accept": []}],
                "rejected": [], "borderline": [],
            }))
            r = _run_with_input(PUB_GATE, self._valid_report(),
                                "--target-manuscript-id", "ms",
                                "--allow-uncalibrated")
            assert r.returncode == 0, f"stderr={r.stderr}"


if __name__ == "__main__":
    sys.exit(run_tests(
        PdfIntegrityTests,
        NoveltyAnchorUniquenessTests,
        HedgeQuotedContextTests,
        KFactorDecayTests,
        CalibrationHardFailTests,
    ))
