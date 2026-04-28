"""Tests for the idea-attacker skill (gate.py)."""
from __future__ import annotations

import importlib.util as _ilu
import json
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from tests.harness import CoscientistTestCase, isolated_cache  # noqa


def _load_gate():
    spec = _ilu.spec_from_file_location(
        "gate",
        _REPO_ROOT / ".claude/skills/idea-attacker/scripts/gate.py",
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ALL_ATTACKS = [
    "untestable",
    "already-known",
    "confounded-by-design",
    "base-rate-neglect",
    "scope-too-broad",
    "implementation-wall",
    "incentive-problem",
    "measurement-gap",
    "wrong-level",
    "status-quo-survives",
]


def _make_attack(name: str, verdict: str = "pass", evidence: str = "N/A — not applicable",
                 steelman: str = "", killer_test: str = "") -> dict:
    a = {"attack": name, "verdict": verdict, "evidence": evidence}
    if steelman:
        a["steelman"] = steelman
    if killer_test:
        a["killer_test"] = killer_test
    return a


def _valid_report(**overrides) -> dict:
    base = {
        "hyp_id": "test-hyp",
        "statement": "Higher cortisol during stress impairs working memory consolidation.",
        "steelman": "Cortisol receptors are dense in hippocampal CA3 regions associated with encoding; acute elevation could disrupt LTP-dependent memory traces. This is mechanistically plausible and has at least two animal model analogues.",
        "attacks": [
            _make_attack("untestable", "pass", "Hypothesis is falsifiable via cortisol-injection + WM task design."),
            _make_attack("already-known", "minor",
                         "Lupien et al. 1994 showed stress impairs memory, but WM consolidation specifically is less studied.",
                         killer_test="Run cortisol challenge + n-back within 30min; compare to saline control."),
            _make_attack("confounded-by-design", "pass", "Cortisol can be administered exogenously; separable from emotional confounds."),
            _make_attack("base-rate-neglect", "pass", "Effect is expected to be large given density of MR/GR receptors in hippocampus."),
            _make_attack("scope-too-broad", "minor",
                         "Claim doesn't specify the WM sub-system; spatial vs. verbal WM may differ.",
                         killer_test="Run DSST + spatial span separately under stress vs. control."),
            _make_attack("implementation-wall", "pass", "Ethics approved in many existing HPA-axis stress labs."),
            _make_attack("incentive-problem", "pass", "Participants receive payment; no misaligned incentive."),
            _make_attack("measurement-gap", "pass", "Salivary cortisol is validated; WM tasks are standardized."),
            _make_attack("wrong-level", "pass", "Hypothesis is pitched at the systems neuroscience level, matching proposed measurement."),
            _make_attack("status-quo-survives", "pass", "Null: arousal improves performance (Yerkes-Dodson). Distinguishable via timing — cortisol peak is delayed vs. catecholamine spike."),
        ],
        "weakest_link": "already-known",
        "survival": 4,
        "survival_reasoning": "One minor scope issue and one prior-art overlap, both testable cheaply. No fatal flaws.",
    }
    base.update(overrides)
    return base


class GateValidationTests(CoscientistTestCase):
    def setUp(self):
        self.mod = _load_gate()

    def test_valid_report_passes(self):
        report = _valid_report()
        struct, content = self.mod.validate(report)
        self.assertEqual(struct, [])
        self.assertEqual(content, [])

    def test_missing_statement_fails(self):
        report = _valid_report(statement="")
        struct, _ = self.mod.validate(report)
        self.assertTrue(any("statement" in e for e in struct))

    def test_missing_steelman_fails(self):
        report = _valid_report(steelman="")
        struct, _ = self.mod.validate(report)
        self.assertTrue(any("steelman" in e for e in struct))

    def test_missing_weakest_link_fails(self):
        report = _valid_report(weakest_link="")
        struct, _ = self.mod.validate(report)
        self.assertTrue(any("weakest_link" in e for e in struct))

    def test_invalid_survival_fails(self):
        report = _valid_report(survival=7)
        struct, _ = self.mod.validate(report)
        self.assertTrue(any("survival" in e for e in struct))

    def test_survival_float_fails(self):
        report = _valid_report(survival=3.5)
        struct, _ = self.mod.validate(report)
        self.assertTrue(any("survival" in e for e in struct))

    def test_missing_survival_reasoning_fails(self):
        report = _valid_report(survival_reasoning="")
        struct, _ = self.mod.validate(report)
        self.assertTrue(any("survival_reasoning" in e for e in struct))

    def test_unknown_attack_name_fails(self):
        report = _valid_report()
        report["attacks"][0]["attack"] = "made-up-attack"
        struct, _ = self.mod.validate(report)
        self.assertTrue(any("unknown attack" in e for e in struct))

    def test_duplicate_attack_fails(self):
        report = _valid_report()
        report["attacks"].append(_make_attack("untestable", "pass", "duplicate"))
        struct, _ = self.mod.validate(report)
        self.assertTrue(any("duplicate" in e for e in struct))

    def test_missing_attack_fails(self):
        report = _valid_report()
        report["attacks"] = [a for a in report["attacks"] if a["attack"] != "untestable"]
        struct, _ = self.mod.validate(report)
        self.assertTrue(any("untestable" in e for e in struct))

    def test_fatal_without_steelman_fails(self):
        report = _valid_report()
        report["attacks"][0] = {
            "attack": "untestable",
            "verdict": "fatal",
            "evidence": "Cannot be tested because it requires measuring subjective experience directly.",
            "killer_test": "N/A",
        }
        struct, _ = self.mod.validate(report)
        self.assertTrue(any("steelman" in e for e in struct))

    def test_fatal_without_killer_test_fails(self):
        report = _valid_report()
        report["attacks"][0] = {
            "attack": "untestable",
            "verdict": "fatal",
            "evidence": "Cannot be tested because it requires measuring subjective experience directly.",
            "steelman": "One could argue behavioral proxies are sufficient.",
        }
        struct, _ = self.mod.validate(report)
        self.assertTrue(any("killer_test" in e for e in struct))

    def test_nonpass_without_evidence_fails(self):
        report = _valid_report()
        report["attacks"][1]["evidence"] = ""  # already-known, minor
        struct, _ = self.mod.validate(report)
        self.assertTrue(any("evidence" in e for e in struct))

    def test_generic_evidence_is_content_error(self):
        report = _valid_report()
        report["attacks"][1]["evidence"] = "needs more work"
        _, content = self.mod.validate(report)
        self.assertTrue(len(content) > 0)

    def test_weakest_link_must_be_known_attack(self):
        report = _valid_report(weakest_link="fake-attack")
        struct, _ = self.mod.validate(report)
        self.assertTrue(any("weakest_link" in e for e in struct))

    def test_invalid_verdict_fails(self):
        report = _valid_report()
        report["attacks"][0]["verdict"] = "uncertain"
        struct, _ = self.mod.validate(report)
        self.assertTrue(any("verdict" in e for e in struct))

    def test_all_ten_attacks_required(self):
        """Confirm all 10 named attacks must appear."""
        for attack in ALL_ATTACKS:
            report = _valid_report()
            report["attacks"] = [a for a in report["attacks"] if a["attack"] != attack]
            struct, _ = self.mod.validate(report)
            self.assertTrue(
                any(attack in e for e in struct),
                f"Expected error for missing attack {attack!r}, got: {struct}",
            )


class GatePersistTests(CoscientistTestCase):
    def test_persist_writes_file(self):
        with isolated_cache() as cache:
            mod = _load_gate()
            report = _valid_report()
            mod.persist(report, "proj_test")
            out = cache / "projects" / "proj_test" / "idea_attacks" / "test-hyp.json"
            self.assertTrue(out.exists())
            saved = json.loads(out.read_text())
            self.assertEqual(saved["hyp_id"], "test-hyp")

    def test_persist_unnamed_hyp(self):
        with isolated_cache() as cache:
            mod = _load_gate()
            report = _valid_report()
            del report["hyp_id"]
            mod.persist(report, "proj_test2")
            out = cache / "projects" / "proj_test2" / "idea_attacks" / "unnamed.json"
            self.assertTrue(out.exists())

    def test_persist_idempotent_overwrites(self):
        with isolated_cache() as cache:
            mod = _load_gate()
            report = _valid_report()
            mod.persist(report, "proj_idem")
            report["survival"] = 3
            mod.persist(report, "proj_idem")
            out = cache / "projects" / "proj_idem" / "idea_attacks" / "test-hyp.json"
            saved = json.loads(out.read_text())
            self.assertEqual(saved["survival"], 3)


class GateCliTests(CoscientistTestCase):
    def _write_report(self, tmp_dir: Path, report: dict) -> Path:
        p = tmp_dir / "report.json"
        p.write_text(json.dumps(report))
        return p

    def test_cli_valid_report_exits_zero(self):
        with isolated_cache() as cache:
            mod = _load_gate()
            import argparse
            import contextlib
            import io
            report = _valid_report()
            with tempfile.TemporaryDirectory() as td:
                p = self._write_report(Path(td), report)
                args = argparse.Namespace(input=str(p), project_id=None, hyp_id=None)
                buf = io.StringIO()
                try:
                    with contextlib.redirect_stdout(buf):
                        mod.main.__globals__["sys"].argv = ["gate.py", "--input", str(p)]
                except SystemExit as e:
                    self.assertEqual(e.code, 0)

    def test_missing_file_exits_nonzero(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, str(_REPO_ROOT / ".claude/skills/idea-attacker/scripts/gate.py"),
             "--input", "/nonexistent/path.json"],
            capture_output=True, text=True,
        )
        self.assertFalse(result.returncode == 0)
