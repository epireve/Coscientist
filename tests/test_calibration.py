"""Tests for v0.61 calibration set tooling — lib.calibration + manage.py CLI."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

from lib import calibration as cal


_REPO = Path(__file__).resolve().parents[1]
_CLI = _REPO / ".claude" / "skills" / "calibration" / "scripts" / "manage.py"


def _run_cli(*args, cache_root: Path) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(_CLI), "--cache-root", str(cache_root), *args]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(_REPO))


class CalibrationCaseTests(TestCase):
    def test_to_dict_accepted_includes_reasons(self):
        c = cal.CalibrationCase(
            title="A", canonical_id="cid1", year=2020,
            reasons=["novel", "rigorous"],
        )
        d = c.to_dict("accepted")
        self.assertEqual(d["title"], "A")
        self.assertEqual(d["reasons_for_accept"], ["novel", "rigorous"])
        self.assertNotIn("reasons_for_reject", d)
        self.assertNotIn("outcome", d)

    def test_to_dict_rejected_includes_reasons(self):
        c = cal.CalibrationCase(title="B", reasons=["weak"])
        d = c.to_dict("rejected")
        self.assertEqual(d["reasons_for_reject"], ["weak"])
        self.assertNotIn("reasons_for_accept", d)

    def test_to_dict_borderline_includes_outcome_notes(self):
        c = cal.CalibrationCase(title="C", outcome="reject", notes="too narrow")
        d = c.to_dict("borderline")
        self.assertEqual(d["outcome"], "reject")
        self.assertEqual(d["notes"], "too narrow")
        self.assertNotIn("reasons_for_accept", d)

    def test_from_dict_roundtrip(self):
        c1 = cal.CalibrationCase(title="X", canonical_id="cid", reasons=["r"])
        d = c1.to_dict("accepted")
        c2 = cal.CalibrationCase.from_dict(d, "accepted")
        self.assertEqual(c2.title, "X")
        self.assertEqual(c2.canonical_id, "cid")
        self.assertEqual(c2.reasons, ["r"])


class SlugifyTests(TestCase):
    def test_basic(self):
        self.assertEqual(cal.slugify_venue("NeurIPS 2024"), "neurips-2024")

    def test_strips_punctuation(self):
        self.assertEqual(cal.slugify_venue("Nature: Methods!"), "nature-methods")

    def test_strip_leading_trailing(self):
        self.assertEqual(cal.slugify_venue("  ICLR  "), "iclr")


class AddRemoveTests(TestCase):
    def test_add_case_assigns_added_at(self):
        cset = cal.CalibrationSet(venue="V")
        c = cal.CalibrationCase(title="T", reasons=["x"])
        cal.add_case(cset, "accepted", c)
        self.assertEqual(len(cset.accepted), 1)
        self.assertTrue(cset.accepted[0].added_at)

    def test_add_case_refuses_duplicate_canonical_id(self):
        cset = cal.CalibrationSet(venue="V")
        cal.add_case(cset, "accepted",
                     cal.CalibrationCase(title="T1", canonical_id="cid"))
        with self.assertRaises(ValueError):
            cal.add_case(cset, "accepted",
                         cal.CalibrationCase(title="T2", canonical_id="cid"))

    def test_add_case_refuses_duplicate_title_when_no_cid(self):
        cset = cal.CalibrationSet(venue="V")
        cal.add_case(cset, "rejected", cal.CalibrationCase(title="Same"))
        with self.assertRaises(ValueError):
            cal.add_case(cset, "rejected",
                         cal.CalibrationCase(title="same"))  # case-insensitive

    def test_add_case_invalid_bucket(self):
        cset = cal.CalibrationSet(venue="V")
        with self.assertRaises(ValueError):
            cal.add_case(cset, "bogus",
                         cal.CalibrationCase(title="T"))

    def test_remove_case_by_canonical_id(self):
        cset = cal.CalibrationSet(venue="V")
        cal.add_case(cset, "accepted",
                     cal.CalibrationCase(title="T", canonical_id="cid"))
        ok = cal.remove_case(cset, "accepted", canonical_id="cid")
        self.assertTrue(ok)
        self.assertEqual(len(cset.accepted), 0)

    def test_remove_case_by_title(self):
        cset = cal.CalibrationSet(venue="V")
        cal.add_case(cset, "rejected", cal.CalibrationCase(title="Foo"))
        ok = cal.remove_case(cset, "rejected", title="foo")
        self.assertTrue(ok)
        self.assertEqual(len(cset.rejected), 0)

    def test_remove_case_returns_false_when_absent(self):
        cset = cal.CalibrationSet(venue="V")
        self.assertFalse(cal.remove_case(cset, "accepted", canonical_id="x"))


class PersistenceTests(TestCase):
    def test_save_load_roundtrip(self):
        with isolated_cache() as root:
            cset = cal.CalibrationSet(venue="NeurIPS 2024")
            cal.add_case(cset, "accepted",
                         cal.CalibrationCase(title="A", reasons=["r1"]))
            path = cal.save(root, cset)
            self.assertTrue(path.exists())
            self.assertEqual(path.name, "neurips-2024.json")
            loaded = cal.load(root, "NeurIPS 2024")
            self.assertEqual(len(loaded.accepted), 1)
            self.assertEqual(loaded.accepted[0].title, "A")

    def test_load_missing_returns_empty(self):
        with isolated_cache() as root:
            cset = cal.load(root, "Unknown Venue")
            self.assertEqual(cset.n_total(), 0)


class RenderSummaryTests(TestCase):
    def test_summary_lists_buckets(self):
        cset = cal.CalibrationSet(venue="V")
        cal.add_case(cset, "accepted",
                     cal.CalibrationCase(title="Paper-A", year=2020,
                                         canonical_id="cid_a",
                                         reasons=["novel"]))
        cal.add_case(cset, "rejected",
                     cal.CalibrationCase(title="Paper-B"))
        s = cal.render_summary(cset)
        self.assertIn("Calibration set — V", s)
        self.assertIn("Paper-A", s)
        self.assertIn("Paper-B", s)
        self.assertIn("cid_a", s)


class CoverageCheckTests(TestCase):
    def test_empty_flags_all_missing(self):
        cset = cal.CalibrationSet(venue="V")
        out = cal.coverage_check(cset)
        self.assertEqual(out["n_total"], 0)
        self.assertEqual(set(out["missing_buckets"]),
                         {"accepted", "rejected", "borderline"})
        self.assertEqual(out["anchored_pct"], 0.0)

    def test_below_recommended_flagged(self):
        cset = cal.CalibrationSet(venue="V")
        cal.add_case(cset, "accepted",
                     cal.CalibrationCase(title="x", canonical_id="c1"))
        out = cal.coverage_check(cset)
        self.assertIn("accepted", out["below_recommended"])
        self.assertIn("rejected", out["missing_buckets"])
        self.assertEqual(out["n_with_canonical_id"], 1)
        self.assertEqual(out["anchored_pct"], 100.0)


class CliSmokeTests(TestCase):
    def test_init_then_add_then_show(self):
        with isolated_cache() as root:
            r = _run_cli("init", "--venue", "ICLR 2025", cache_root=root)
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(r.stdout)
            self.assertTrue(data["ok"])
            self.assertEqual(data["venue"], "ICLR 2025")

            r = _run_cli(
                "add", "--venue", "ICLR 2025", "--bucket", "accepted",
                "--title", "Attention Is All You Need",
                "--canonical-id", "vaswani_2017_attn", "--year", "2017",
                "--reasons", "novel", "strong empirical",
                cache_root=root,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(json.loads(r.stdout)["ok"])

            r = _run_cli("show", "--venue", "ICLR 2025", "--format", "json",
                         cache_root=root)
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(r.stdout)
            self.assertEqual(len(data["accepted"]), 1)
            self.assertEqual(data["accepted"][0]["canonical_id"],
                             "vaswani_2017_attn")

    def test_remove_cli(self):
        with isolated_cache() as root:
            _run_cli("init", "--venue", "V", cache_root=root)
            _run_cli("add", "--venue", "V", "--bucket", "rejected",
                     "--title", "Bad Paper", cache_root=root)
            r = _run_cli("remove", "--venue", "V", "--bucket", "rejected",
                         "--title", "Bad Paper", cache_root=root)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(json.loads(r.stdout)["removed"])

    def test_remove_missing_returns_nonzero(self):
        with isolated_cache() as root:
            _run_cli("init", "--venue", "V", cache_root=root)
            r = _run_cli("remove", "--venue", "V", "--bucket", "accepted",
                         "--title", "Nope", cache_root=root)
            self.assertEqual(r.returncode, 1)

    def test_check_cli(self):
        with isolated_cache() as root:
            _run_cli("init", "--venue", "V", cache_root=root)
            r = _run_cli("check", "--venue", "V", cache_root=root)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["n_total"], 0)

    def test_list_cli(self):
        with isolated_cache() as root:
            _run_cli("init", "--venue", "Alpha", cache_root=root)
            _run_cli("init", "--venue", "Beta", cache_root=root)
            r = _run_cli("list", cache_root=root)
            self.assertEqual(r.returncode, 0, r.stderr)
            venues = json.loads(r.stdout)
            slugs = {v["slug"] for v in venues}
            self.assertIn("alpha", slugs)
            self.assertIn("beta", slugs)

    def test_anchors_md(self):
        with isolated_cache() as root:
            _run_cli("init", "--venue", "V", cache_root=root)
            _run_cli("add", "--venue", "V", "--bucket", "accepted",
                     "--title", "GoodPaper", "--canonical-id", "good_2020",
                     "--year", "2020", "--reasons", "novel", "rigorous",
                     cache_root=root)
            _run_cli("add", "--venue", "V", "--bucket", "rejected",
                     "--title", "BadPaper", "--reasons", "weak baseline",
                     cache_root=root)
            r = _run_cli("anchors", "--venue", "V",
                         cache_root=root)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Calibration anchors — V", r.stdout)
            self.assertIn("GoodPaper", r.stdout)
            self.assertIn("good_2020", r.stdout)
            self.assertIn("novel; rigorous", r.stdout)
            self.assertIn("BadPaper", r.stdout)
            self.assertIn("weak baseline", r.stdout)

    def test_anchors_json(self):
        with isolated_cache() as root:
            _run_cli("init", "--venue", "V", cache_root=root)
            _run_cli("add", "--venue", "V", "--bucket", "borderline",
                     "--title", "Mid", "--outcome", "reject after rebuttal",
                     "--notes", "scope", cache_root=root)
            r = _run_cli("anchors", "--venue", "V", "--format", "json",
                         cache_root=root)
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(r.stdout)
            self.assertEqual(data["venue"], "V")
            self.assertEqual(len(data["borderline"]), 1)
            self.assertEqual(data["borderline"][0]["outcome"],
                             "reject after rebuttal")

    def test_anchors_missing_venue_returns_nonzero(self):
        with isolated_cache() as root:
            r = _run_cli("anchors", "--venue", "Nope", cache_root=root)
            self.assertEqual(r.returncode, 1)

    def test_anchors_max_per_bucket_caps(self):
        with isolated_cache() as root:
            _run_cli("init", "--venue", "V", cache_root=root)
            for i in range(5):
                _run_cli("add", "--venue", "V", "--bucket", "accepted",
                         "--title", f"Paper-{i}",
                         "--canonical-id", f"cid_{i}",
                         cache_root=root)
            r = _run_cli("anchors", "--venue", "V", "--format", "json",
                         "--max-per-bucket", "2", cache_root=root)
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(r.stdout)
            self.assertEqual(len(data["accepted"]), 2)

    def test_add_duplicate_canonical_id_fails(self):
        with isolated_cache() as root:
            _run_cli("init", "--venue", "V", cache_root=root)
            _run_cli("add", "--venue", "V", "--bucket", "accepted",
                     "--title", "T1", "--canonical-id", "cid",
                     cache_root=root)
            r = _run_cli("add", "--venue", "V", "--bucket", "accepted",
                         "--title", "T2", "--canonical-id", "cid",
                         cache_root=root)
            self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        CalibrationCaseTests,
        SlugifyTests,
        AddRemoveTests,
        PersistenceTests,
        RenderSummaryTests,
        CoverageCheckTests,
        CliSmokeTests,
    ))
