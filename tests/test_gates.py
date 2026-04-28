"""Gate-script tests for A5 critical-judgment skills.

Each gate has two flavors of test:
- accept a well-formed report (exit 0)
- reject each specific violation (exit 2 with message)
"""

import json
import subprocess
import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent


def _run(script: Path, *args: str, input_json: dict | None = None) -> subprocess.CompletedProcess:
    input_path = None
    if input_json is not None:
        input_path = _ROOT / "tests" / "_tmp_input.json"
        input_path.write_text(json.dumps(input_json))
    cmd = [sys.executable, str(script)] + list(args)
    if input_path:
        cmd += ["--input", str(input_path)]
    return subprocess.run(cmd, capture_output=True, text=True)


# ---------------- novelty-check ----------------

NOVELTY_GATE = _ROOT / ".claude/skills/novelty-check/scripts/gate.py"


def _valid_novelty_report() -> dict:
    return {
        "contributions": [
            {
                "id": "contrib-1",
                "claim": "ViT scales to protein structure",
                "decomposition": {
                    "method": "Vision transformer",
                    "domain": "Protein structure prediction",
                    "finding": "Beats CNN baselines at scale",
                    "metric": "TM-score",
                },
                "anchors": [
                    {"canonical_id": "dosovitskiy_2020_vit_aaaaaa",
                     "closest_aspect": "method",
                     "delta": "Protein vs image",
                     "delta_sufficient": True},
                    {"canonical_id": "jumper_2021_alphafold_bbbbbb",
                     "closest_aspect": "domain",
                     "delta": "Transformer vs attention+evoformer",
                     "delta_sufficient": True},
                    {"canonical_id": "rives_2021_esm_cccccc",
                     "closest_aspect": "method",
                     "delta": "Transformer on sequences not structures",
                     "delta_sufficient": False},
                    {"canonical_id": "vaswani_2017_attn_dddddd",
                     "closest_aspect": "method",
                     "delta": "Pure transformer on text",
                     "delta_sufficient": True},
                    {"canonical_id": "chowdhury_2022_openfold_eeeeee",
                     "closest_aspect": "domain",
                     "delta": "Different architecture",
                     "delta_sufficient": False},
                ],
                "verdict": "novel",
                "confidence": 0.72,
                "reasoning": "Transformer-only architecture achieves competitive TM-score without evoformer module.",
            }
        ]
    }


class NoveltyGateTests(TestCase):
    def test_accepts_valid(self):
        with isolated_cache():
            r = _run(NOVELTY_GATE, "--target-canonical-id", "target_x",
                     input_json=_valid_novelty_report())
            assert r.returncode == 0, f"expected 0, got {r.returncode}; stderr={r.stderr}"

    def test_rejects_under_five_anchors(self):
        report = _valid_novelty_report()
        report["contributions"][0]["anchors"] = report["contributions"][0]["anchors"][:3]
        with isolated_cache():
            r = _run(NOVELTY_GATE, "--target-canonical-id", "t", input_json=report)
            self.assertEqual(r.returncode, 2)
            self.assertIn("need ≥5", r.stderr)

    def test_rejects_hedge_word(self):
        report = _valid_novelty_report()
        report["contributions"][0]["reasoning"] = "This might be novel, perhaps."
        with isolated_cache():
            r = _run(NOVELTY_GATE, "--target-canonical-id", "t", input_json=report)
            self.assertEqual(r.returncode, 2)
            self.assertIn("hedge", r.stderr)

    def test_rejects_novel_without_sufficient_delta(self):
        report = _valid_novelty_report()
        for a in report["contributions"][0]["anchors"]:
            a["delta_sufficient"] = False
        with isolated_cache():
            r = _run(NOVELTY_GATE, "--target-canonical-id", "t", input_json=report)
            self.assertEqual(r.returncode, 2)

    def test_rejects_missing_confidence(self):
        report = _valid_novelty_report()
        del report["contributions"][0]["confidence"]
        with isolated_cache():
            r = _run(NOVELTY_GATE, "--target-canonical-id", "t", input_json=report)
            self.assertEqual(r.returncode, 2)

    def test_rejects_invalid_verdict(self):
        report = _valid_novelty_report()
        report["contributions"][0]["verdict"] = "kinda-novel"
        with isolated_cache():
            r = _run(NOVELTY_GATE, "--target-canonical-id", "t", input_json=report)
            self.assertEqual(r.returncode, 2)


# ---------------- publishability-check ----------------

PUB_GATE = _ROOT / ".claude/skills/publishability-check/scripts/gate.py"


def _valid_pub_report() -> dict:
    return {
        "venues": [
            {
                "venue": "NeurIPS 2026",
                "verdict": "borderline-with-revisions",
                "probability_of_acceptance": 0.42,
                "factors_up": [
                    {"factor": "Strong empirical results", "weight": 0.4},
                    {"factor": "Clear writing", "weight": 0.2},
                    {"factor": "Timely topic", "weight": 0.3},
                ],
                "factors_down": [
                    {"factor": "Limited baseline comparison", "weight": -0.4},
                    {"factor": "No code released", "weight": -0.3},
                    {"factor": "Missing ablation on training data", "weight": -0.2},
                ],
                "kill_criterion": "If the ablation table reveals results collapse at 10% data, verdict flips to reject.",
                "tier_up_requirements": "Full ablation suite + code release + one additional dataset.",
                "reasoning": "Core contribution is tight but evaluation is thin relative to NeurIPS 2026 empirical standards.",
            }
        ]
    }


class PublishabilityGateTests(TestCase):
    def test_accepts_valid(self):
        with isolated_cache():
            r = _run(PUB_GATE, "--target-manuscript-id", "ms_1",
                     input_json=_valid_pub_report())
            assert r.returncode == 0, f"expected 0, got {r.returncode}; stderr={r.stderr}"

    def test_rejects_missing_probability(self):
        report = _valid_pub_report()
        del report["venues"][0]["probability_of_acceptance"]
        with isolated_cache():
            r = _run(PUB_GATE, "--target-manuscript-id", "m", input_json=report)
            self.assertEqual(r.returncode, 2)

    def test_rejects_insufficient_factors(self):
        report = _valid_pub_report()
        report["venues"][0]["factors_up"] = report["venues"][0]["factors_up"][:2]
        with isolated_cache():
            r = _run(PUB_GATE, "--target-manuscript-id", "m", input_json=report)
            self.assertEqual(r.returncode, 2)

    def test_rejects_vague_kill_criterion(self):
        report = _valid_pub_report()
        report["venues"][0]["kill_criterion"] = "depends on reviewers"
        with isolated_cache():
            r = _run(PUB_GATE, "--target-manuscript-id", "m", input_json=report)
            self.assertEqual(r.returncode, 2)

    def test_rejects_verdict_probability_mismatch(self):
        report = _valid_pub_report()
        report["venues"][0]["verdict"] = "accept"
        report["venues"][0]["probability_of_acceptance"] = 0.3
        with isolated_cache():
            r = _run(PUB_GATE, "--target-manuscript-id", "m", input_json=report)
            self.assertEqual(r.returncode, 2)

    def test_rejects_hedge_in_reasoning(self):
        report = _valid_pub_report()
        report["venues"][0]["reasoning"] = "This might be a strong paper, potentially."
        with isolated_cache():
            r = _run(PUB_GATE, "--target-manuscript-id", "m", input_json=report)
            self.assertEqual(r.returncode, 2)


# ---------------- attack-vectors ----------------

ATTACK_CHECK = _ROOT / ".claude/skills/attack-vectors/scripts/check.py"


def _valid_attack_report() -> dict:
    return {
        "findings": [
            {"attack": "p-hacking", "severity": "pass",
             "evidence": "Bonferroni correction reported"},
            {"attack": "underpowered", "severity": "fatal",
             "evidence": "n=12, claimed effect d=0.3 requires n=175",
             "steelman": "Authors treat this as preliminary; claims are scoped."},
            {"attack": "selective-baselines", "severity": "minor",
             "evidence": "Omits Smith 2023 baseline"},
        ]
    }


class AttackVectorsTests(TestCase):
    def test_accepts_valid(self):
        with isolated_cache():
            r = _run(ATTACK_CHECK, "--target-canonical-id", "x",
                     input_json=_valid_attack_report())
            assert r.returncode == 0, f"expected 0, got {r.returncode}; stderr={r.stderr}"

    def test_rejects_unknown_attack(self):
        report = _valid_attack_report()
        report["findings"][0]["attack"] = "vibes"
        with isolated_cache():
            r = _run(ATTACK_CHECK, "--target-canonical-id", "x", input_json=report)
            self.assertEqual(r.returncode, 2)
            self.assertIn("unknown attack", r.stderr)

    def test_rejects_fatal_without_steelman(self):
        report = _valid_attack_report()
        del report["findings"][1]["steelman"]
        with isolated_cache():
            r = _run(ATTACK_CHECK, "--target-canonical-id", "x", input_json=report)
            self.assertEqual(r.returncode, 2)
            self.assertIn("steelman", r.stderr)

    def test_rejects_missing_evidence(self):
        report = _valid_attack_report()
        report["findings"][0]["evidence"] = ""
        with isolated_cache():
            r = _run(ATTACK_CHECK, "--target-canonical-id", "x", input_json=report)
            self.assertEqual(r.returncode, 2)

    def test_rejects_duplicate_attacks(self):
        report = {"findings": [
            {"attack": "p-hacking", "severity": "pass", "evidence": "ok"},
            {"attack": "p-hacking", "severity": "pass", "evidence": "ok"},
        ]}
        with isolated_cache():
            r = _run(ATTACK_CHECK, "--target-canonical-id", "x", input_json=report)
            self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    import sys
    sys.exit(run_tests(NoveltyGateTests, PublishabilityGateTests, AttackVectorsTests))
