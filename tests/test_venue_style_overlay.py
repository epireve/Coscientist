"""Tests for v0.60 — writing-style venue overlays."""

from tests import _shim  # noqa: F401

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

from lib.venue_style_overlay import (
    OVERLAYS,
    VenueStyleOverlay,
    audit_text_against_overlay,
    get_overlay,
    list_overlays,
    render_audit_brief,
)

_ROOT = Path(__file__).resolve().parent.parent
AUDIT = _ROOT / ".claude/skills/writing-style/scripts/audit.py"


def _seed_project(cache_dir: Path, pid: str = "vso_project") -> str:
    p = cache_dir / "projects" / pid
    p.mkdir(parents=True, exist_ok=True)
    schema = (_ROOT / "lib" / "sqlite_schema.sql").read_text()
    con = sqlite3.connect(p / "project.db")
    con.executescript(schema)
    con.execute(
        "INSERT INTO projects (project_id, name, created_at) VALUES (?, ?, ?)",
        (pid, "VSO", "2026-04-27T00:00:00Z"),
    )
    con.commit()
    con.close()
    return pid


# -----------------------------------------------------------------
# Registry
# -----------------------------------------------------------------

class RegistryTests(TestCase):
    def test_registry_has_at_least_ten_venues(self):
        self.assertGreaterEqual(len(OVERLAYS), 10)
        # Sanity: the listed venues we promised in the SKILL.md
        for name in ("NeurIPS", "ICLR", "ICML", "Nature", "Science",
                     "eLife", "NEJM", "JAMA", "PLOS ONE", "arXiv"):
            self.assertIn(name, OVERLAYS)

    def test_get_overlay_case_insensitive(self):
        o = get_overlay("neurips")
        self.assertEqual(o.venue_name, "NeurIPS")

    def test_get_overlay_unknown_raises(self):
        with self.assertRaises(KeyError):
            get_overlay("FakeVenue")

    def test_list_overlays_returns_sorted(self):
        names = list_overlays()
        self.assertEqual(names, sorted(names))
        self.assertGreaterEqual(len(names), 10)


# -----------------------------------------------------------------
# Voice / tense / pronoun / hedge detection
# -----------------------------------------------------------------

class VoiceDetectionTests(TestCase):
    def test_clinical_passive_text_flagged_for_neurips(self):
        # Heavily passive — NEJM-style methods write-up.
        text = (
            "The samples were collected from 200 participants. "
            "Outcomes were measured at baseline and follow-up. "
            "Statistical tests were performed using R. "
            "Differences were observed between treatment groups. "
            "Results were analyzed by trained coders."
        )
        overlay = get_overlay("NeurIPS")
        findings = audit_text_against_overlay(text, overlay)
        kinds = [f.kind for f in findings]
        self.assertIn("voice", kinds)
        voice_finding = next(f for f in findings if f.kind == "voice")
        self.assertIn(voice_finding.severity, ("minor", "major"))

    def test_active_we_text_passes_neurips_voice_check(self):
        text = (
            "We propose a new attention mechanism. "
            "We show that it improves perplexity by 12%. "
            "We train models on standard benchmarks. "
            "We find consistent gains across scales. "
            "We provide ablations to isolate the cause."
        )
        overlay = get_overlay("NeurIPS")
        findings = audit_text_against_overlay(text, overlay)
        voice_findings = [f for f in findings if f.kind == "voice"]
        self.assertEqual(len(voice_findings), 0)

    def test_active_text_flagged_for_passive_venue(self):
        text = (
            "We propose a new method. "
            "We show that it works well. "
            "We train models on benchmarks. "
            "We find improvements throughout. "
            "We provide thorough ablations."
        )
        overlay = get_overlay("NEJM")
        findings = audit_text_against_overlay(text, overlay)
        kinds = [f.kind for f in findings]
        self.assertIn("voice", kinds)


class TenseDetectionTests(TestCase):
    def test_past_tense_flagged_for_present_venue(self):
        # Lots of past markers, no present — should fail NeurIPS present pref.
        text = (
            "We trained 10 models on the dataset. "
            "We measured accuracy on the held-out set. "
            "We observed improvements on three benchmarks. "
            "We compared against four baselines. "
            "We evaluated each configuration with three seeds."
        )
        overlay = get_overlay("NeurIPS")
        findings = audit_text_against_overlay(text, overlay)
        kinds = [f.kind for f in findings]
        self.assertIn("tense", kinds)

    def test_present_tense_flagged_for_past_venue(self):
        text = (
            "We propose a clinical trial. "
            "We show improvements in outcomes. "
            "We find no adverse events. "
            "We report results from 500 patients. "
            "We demonstrate the protocol's safety."
        )
        overlay = get_overlay("NEJM")
        findings = audit_text_against_overlay(text, overlay)
        kinds = [f.kind for f in findings]
        self.assertIn("tense", kinds)


class PronounDetectionTests(TestCase):
    def test_we_flagged_for_authors_venue(self):
        text = (
            "We conducted a randomized trial. "
            "Our results show clear effects. "
            "We measured baseline outcomes. "
            "We analyzed the data with mixed models. "
            "Our findings support the hypothesis."
        )
        overlay = get_overlay("NEJM")
        findings = audit_text_against_overlay(text, overlay)
        kinds = [f.kind for f in findings]
        self.assertIn("pronoun", kinds)


class HedgeDensityTests(TestCase):
    def test_hedge_density_flagged_when_over_threshold(self):
        # ~10 hedges in ~50 words → 20 per 100 words >> 1.5 (NeurIPS low)
        text = (
            "We may possibly find that perhaps the model could potentially "
            "show somewhat improved performance, although it might be that "
            "results may appear to suggest broadly similar effects, and "
            "possibly arguably the gains could be relatively modest."
        )
        overlay = get_overlay("NeurIPS")
        findings = audit_text_against_overlay(text, overlay)
        hedge_findings = [f for f in findings if f.kind == "hedge"]
        self.assertEqual(len(hedge_findings), 1)
        self.assertIn(hedge_findings[0].severity, ("minor", "major", "info"))

    def test_no_hedge_finding_under_threshold(self):
        text = (
            "We propose a method for scaling transformers. "
            "We show measurable gains on standard benchmarks. "
            "We provide careful ablations of every design choice. "
            "We release code and trained checkpoints. "
            "We evaluate across three independent seeds."
        )
        overlay = get_overlay("NeurIPS")
        findings = audit_text_against_overlay(text, overlay)
        hedge_findings = [f for f in findings if f.kind == "hedge"]
        self.assertEqual(len(hedge_findings), 0)


# -----------------------------------------------------------------
# Edge cases + render
# -----------------------------------------------------------------

class EdgeCaseTests(TestCase):
    def test_empty_text_yields_no_findings(self):
        overlay = get_overlay("NeurIPS")
        self.assertEqual(audit_text_against_overlay("", overlay), [])
        self.assertEqual(audit_text_against_overlay("   \n  ", overlay), [])

    def test_render_brief_includes_venue_and_count(self):
        overlay = get_overlay("NeurIPS")
        text = (
            "The samples were collected. The data were analyzed. "
            "Results were tabulated. Conclusions were drawn."
        )
        findings = audit_text_against_overlay(text, overlay)
        brief = render_audit_brief(findings, overlay)
        self.assertIn("NeurIPS", brief)
        self.assertIn(f"Findings: {len(findings)}", brief)

    def test_render_brief_zero_findings_message(self):
        overlay = get_overlay("arXiv")
        brief = render_audit_brief([], overlay)
        self.assertIn("arXiv", brief)
        self.assertIn("Findings: 0", brief)
        self.assertIn("no overlay-level deviations", brief)


# -----------------------------------------------------------------
# CLI smoke
# -----------------------------------------------------------------

class CliTests(TestCase):
    def test_cli_venue_only_runs(self):
        with isolated_cache() as cache_dir:
            mid = "vso-cli-mid"
            ms_dir = cache_dir / "manuscripts" / mid
            ms_dir.mkdir(parents=True)
            (ms_dir / "source.md").write_text(
                "# Title\n\n"
                "We propose a method. We show it works. "
                "We train on standard data. We find gains. "
                "We release code.\n"
            )

            r = subprocess.run(
                [sys.executable, str(AUDIT),
                 "--manuscript-id", mid,
                 "--venue-only", "--venue", "NeurIPS"],
                capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0,
                             msg=f"stderr={r.stderr}\nstdout={r.stdout}")
            out_path = ms_dir / "style_audit.json"
            self.assertTrue(out_path.exists())
            report = json.loads(out_path.read_text())
            self.assertEqual(report["venue"], "NeurIPS")
            self.assertIn("venue_findings", report)
            brief_path = ms_dir / "style_audit_venue.md"
            self.assertTrue(brief_path.exists())
            self.assertIn("NeurIPS", brief_path.read_text())

    def test_cli_unknown_venue_errors(self):
        with isolated_cache() as cache_dir:
            mid = "vso-cli-mid2"
            ms_dir = cache_dir / "manuscripts" / mid
            ms_dir.mkdir(parents=True)
            (ms_dir / "source.md").write_text("We do things. We show stuff.\n")

            r = subprocess.run(
                [sys.executable, str(AUDIT),
                 "--manuscript-id", mid,
                 "--venue-only", "--venue", "FakeVenue"],
                capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 1)
            self.assertIn("unknown venue", r.stderr.lower() + r.stdout.lower())


if __name__ == "__main__":
    sys.exit(run_tests(
        RegistryTests,
        VoiceDetectionTests,
        TenseDetectionTests,
        PronounDetectionTests,
        HedgeDensityTests,
        EdgeCaseTests,
        CliTests,
    ))
