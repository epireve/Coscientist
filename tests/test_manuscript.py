"""Manuscript subsystem tests: ingest + audit + critique + reflect gates."""

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


# ---------------- manuscript-ingest ----------------

INGEST = _ROOT / ".claude/skills/manuscript-ingest/scripts/ingest.py"


class IngestTests(TestCase):
    def _write_draft(self, tmp: Path, content: str = "# Draft\n\nBody text.") -> Path:
        p = tmp / "draft.md"
        p.write_text(content)
        return p

    def test_ingest_creates_artifact(self):
        with isolated_cache() as cache_dir:
            draft = self._write_draft(cache_dir)
            r = subprocess.run(
                [sys.executable, str(INGEST),
                 "--source", str(draft), "--title", "Test Paper"],
                capture_output=True, text=True,
            )
            assert r.returncode == 0, f"stderr={r.stderr}"
            mid = r.stdout.strip()
            self.assertTrue(mid)
            art_dir = cache_dir / "manuscripts" / mid
            self.assertTrue(art_dir.exists())
            self.assertEqual(
                (art_dir / "source.md").read_text(), draft.read_text()
            )
            manifest = json.loads((art_dir / "manifest.json").read_text())
            self.assertEqual(manifest["kind"], "manuscript")
            self.assertEqual(manifest["state"], "drafted")

    def test_ingest_deterministic_id(self):
        with isolated_cache() as cache_dir:
            draft = self._write_draft(cache_dir)
            r1 = subprocess.run(
                [sys.executable, str(INGEST),
                 "--source", str(draft), "--title", "Same"],
                capture_output=True, text=True,
            )
            r2 = subprocess.run(
                [sys.executable, str(INGEST),
                 "--source", str(draft), "--title", "Same"],
                capture_output=True, text=True,
            )
            self.assertEqual(r1.stdout.strip(), r2.stdout.strip())

    def test_ingest_rejects_non_markdown(self):
        with isolated_cache() as cache_dir:
            p = cache_dir / "file.pdf"
            p.write_bytes(b"%PDF-1.4")
            r = subprocess.run(
                [sys.executable, str(INGEST),
                 "--source", str(p), "--title", "T"],
                capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 1)

    def test_ingest_rejects_empty(self):
        with isolated_cache() as cache_dir:
            p = cache_dir / "empty.md"
            p.write_text("")
            r = subprocess.run(
                [sys.executable, str(INGEST),
                 "--source", str(p), "--title", "T"],
                capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 1)


# ---------------- manuscript-audit ----------------

AUDIT_GATE = _ROOT / ".claude/skills/manuscript-audit/scripts/gate.py"


def _valid_audit_report() -> dict:
    return {
        "manuscript_id": "ms_test",
        "claims": [
            {
                "claim_id": "c-1",
                "text": "Transformers outperform CNNs at scale [@vaswani2017].",
                "location": "§2 ¶1",
                "cited_sources": ["vaswani_2017_attn_abc123"],
                "findings": [
                    {
                        "kind": "overclaim",
                        "severity": "minor",
                        "evidence": "Vaswani 2017 §4.2 shows parity with CNNs at small scale, not outperformance."
                    }
                ]
            },
            {
                "claim_id": "c-2",
                "text": "Attention is all you need.",
                "location": "§1 ¶2",
                "cited_sources": [],
                "findings": []
            }
        ]
    }


class AuditGateTests(TestCase):
    def test_accepts_valid(self):
        with isolated_cache():
            r = _run(AUDIT_GATE, "--manuscript-id", "ms_test",
                     input_json=_valid_audit_report())
            assert r.returncode == 0, f"stderr={r.stderr}"

    def test_rejects_empty_claims(self):
        with isolated_cache():
            r = _run(AUDIT_GATE, "--manuscript-id", "m",
                     input_json={"claims": []})
            self.assertEqual(r.returncode, 2)

    def test_rejects_inline_citation_unresolved(self):
        report = _valid_audit_report()
        # Remove cited_sources even though the text has [@vaswani2017]
        report["claims"][0]["cited_sources"] = []
        with isolated_cache():
            r = _run(AUDIT_GATE, "--manuscript-id", "m", input_json=report)
            self.assertEqual(r.returncode, 2)
            self.assertIn("skipped resolution", r.stderr)

    def test_rejects_invalid_kind(self):
        report = _valid_audit_report()
        report["claims"][0]["findings"][0]["kind"] = "invented"
        with isolated_cache():
            r = _run(AUDIT_GATE, "--manuscript-id", "m", input_json=report)
            self.assertEqual(r.returncode, 2)

    def test_rejects_hedge_evidence(self):
        report = _valid_audit_report()
        report["claims"][0]["findings"][0]["evidence"] = "This seems to be wrong, maybe."
        with isolated_cache():
            r = _run(AUDIT_GATE, "--manuscript-id", "m", input_json=report)
            self.assertEqual(r.returncode, 2)


# ---------------- manuscript-critique ----------------

CRITIQUE_GATE = _ROOT / ".claude/skills/manuscript-critique/scripts/gate.py"


def _valid_critique_report() -> dict:
    return {
        "manuscript_id": "ms_test",
        "reviewers": {
            "methodological": {
                "findings": [{
                    "id": "m-1", "severity": "minor",
                    "location": "§4 Table 2",
                    "issue": "No Bonferroni correction across the 8 comparisons in Table 2",
                    "suggested_fix": "Apply FDR correction"
                }],
                "summary": "Sound methods with one multiple-comparisons concern."
            },
            "theoretical": {
                "findings": [],
                "summary": "No issues at this level — framework is internally consistent."
            },
            "big_picture": {
                "findings": [{
                    "id": "bp-1", "severity": "major",
                    "location": "Intro ¶3",
                    "issue": "Contribution framing doesn't distinguish from Smith 2024",
                    "suggested_fix": "Add explicit delta section",
                }],
                "summary": "Positioning needs sharpening."
            },
            "nitpicky": {
                "findings": [],
                "summary": "No issues at this level."
            }
        },
        "overall_verdict": "borderline",
        "confidence": 0.55,
        "strongest_finding_id": "bp-1"
    }


class CritiqueGateTests(TestCase):
    def test_accepts_valid(self):
        with isolated_cache():
            r = _run(CRITIQUE_GATE, "--manuscript-id", "m",
                     input_json=_valid_critique_report())
            assert r.returncode == 0, f"stderr={r.stderr}"

    def test_rejects_missing_reviewer(self):
        report = _valid_critique_report()
        del report["reviewers"]["theoretical"]
        with isolated_cache():
            r = _run(CRITIQUE_GATE, "--manuscript-id", "m", input_json=report)
            self.assertEqual(r.returncode, 2)
            self.assertIn("theoretical", r.stderr)

    def test_rejects_fatal_without_steelman(self):
        report = _valid_critique_report()
        report["reviewers"]["methodological"]["findings"][0]["severity"] = "fatal"
        # no steelman added
        with isolated_cache():
            r = _run(CRITIQUE_GATE, "--manuscript-id", "m", input_json=report)
            self.assertEqual(r.returncode, 2)
            self.assertIn("steelman", r.stderr)

    def test_rejects_verdict_confidence_mismatch(self):
        report = _valid_critique_report()
        report["overall_verdict"] = "accept"
        report["confidence"] = 0.2   # too low for accept
        with isolated_cache():
            r = _run(CRITIQUE_GATE, "--manuscript-id", "m", input_json=report)
            self.assertEqual(r.returncode, 2)

    def test_rejects_empty_reviewer_no_summary(self):
        report = _valid_critique_report()
        report["reviewers"]["nitpicky"]["summary"] = ""
        # findings empty AND summary empty
        with isolated_cache():
            r = _run(CRITIQUE_GATE, "--manuscript-id", "m", input_json=report)
            self.assertEqual(r.returncode, 2)

    def test_rejects_invalid_verdict(self):
        report = _valid_critique_report()
        report["overall_verdict"] = "maybe-accept"
        with isolated_cache():
            r = _run(CRITIQUE_GATE, "--manuscript-id", "m", input_json=report)
            self.assertEqual(r.returncode, 2)


# ---------------- manuscript-reflect ----------------

REFLECT_GATE = _ROOT / ".claude/skills/manuscript-reflect/scripts/gate.py"


def _valid_reflect_report() -> dict:
    return {
        "manuscript_id": "ms_test",
        "argument_structure": {
            "thesis": "Transformers generalize to protein structure prediction with fewer inductive biases than evoformer.",
            "premises": [
                "Evoformer uses MSA-specific architectures that bake in domain assumptions",
                "Vanilla transformers trained on sequence-structure pairs reach comparable TM-score",
            ],
            "evidence_chain": [
                {"claim": "Evoformer's inductive bias is unnecessary at scale",
                 "evidence": ["jumper_2021_alphafold_aaa"],
                 "strength": 0.6},
                {"claim": "Transformer matches evoformer on CASP14",
                 "evidence": ["self"],
                 "strength": 0.8},
            ],
            "conclusion": "Architectural simplicity wins at the scale tested."
        },
        "implicit_assumptions": [
            {
                "assumption": "CASP14 is representative of the broader structure-prediction space",
                "fragility": "medium",
                "consequence_if_false": "Generalization claim doesn't hold outside competition distribution"
            },
            {
                "assumption": "Training data coverage is comparable across architectures",
                "fragility": "high",
                "consequence_if_false": "The delta is about data, not architecture"
            }
        ],
        "weakest_link": {
            "what": "Evidence that the transformer matches on CASP14 is from one run",
            "why": "A single CASP14 point doesn't distinguish architectural capacity from seed variance; three seeds would."
        },
        "one_experiment": {
            "description": "Run the transformer three times with different seeds on CASP14 and report TM-score distribution vs evoformer baseline",
            "expected_impact": "Determines whether the single-run result is a seed artifact or a genuine architectural claim",
            "cost_estimate": "days"
        }
    }


class ReflectGateTests(TestCase):
    def test_accepts_valid(self):
        with isolated_cache():
            r = _run(REFLECT_GATE, "--manuscript-id", "m",
                     input_json=_valid_reflect_report())
            assert r.returncode == 0, f"stderr={r.stderr}"

    def test_rejects_too_few_premises(self):
        report = _valid_reflect_report()
        report["argument_structure"]["premises"] = ["only one"]
        with isolated_cache():
            r = _run(REFLECT_GATE, "--manuscript-id", "m", input_json=report)
            self.assertEqual(r.returncode, 2)

    def test_rejects_missing_weakest_link(self):
        report = _valid_reflect_report()
        report["weakest_link"] = {}
        with isolated_cache():
            r = _run(REFLECT_GATE, "--manuscript-id", "m", input_json=report)
            self.assertEqual(r.returncode, 2)

    def test_rejects_vague_experiment(self):
        report = _valid_reflect_report()
        report["one_experiment"]["description"] = "More research on protein structure"
        with isolated_cache():
            r = _run(REFLECT_GATE, "--manuscript-id", "m", input_json=report)
            self.assertEqual(r.returncode, 2)

    def test_rejects_strength_out_of_range(self):
        report = _valid_reflect_report()
        report["argument_structure"]["evidence_chain"][0]["strength"] = 1.5
        with isolated_cache():
            r = _run(REFLECT_GATE, "--manuscript-id", "m", input_json=report)
            self.assertEqual(r.returncode, 2)

    def test_rejects_hedge_in_thesis(self):
        report = _valid_reflect_report()
        report["argument_structure"]["thesis"] = "Transformers might potentially work for protein structure."
        with isolated_cache():
            r = _run(REFLECT_GATE, "--manuscript-id", "m", input_json=report)
            self.assertEqual(r.returncode, 2)

    def test_rejects_too_few_assumptions(self):
        report = _valid_reflect_report()
        report["implicit_assumptions"] = report["implicit_assumptions"][:1]
        with isolated_cache():
            r = _run(REFLECT_GATE, "--manuscript-id", "m", input_json=report)
            self.assertEqual(r.returncode, 2)


# ---------------- schema ----------------

class ManuscriptSchemaTests(TestCase):
    def test_manuscript_tables_present(self):
        import sqlite3
        con = sqlite3.connect(":memory:")
        con.executescript((_ROOT / "lib" / "sqlite_schema.sql").read_text())
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        for t in ["manuscript_claims", "manuscript_audit_findings",
                  "manuscript_critique_findings", "manuscript_reflections"]:
            self.assertIn(t, names)


if __name__ == "__main__":
    sys.exit(run_tests(
        IngestTests, AuditGateTests, CritiqueGateTests, ReflectGateTests,
        ManuscriptSchemaTests,
    ))
