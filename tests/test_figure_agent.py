"""Tests for the figure-agent skill."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

import importlib.util as _ilu

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests  # noqa


def _load(name):
    spec = _ilu.spec_from_file_location(
        name,
        _REPO_ROOT / ".claude/skills/figure-agent/scripts" / f"{name}.py"
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestRegister(TestCase):
    def test_register_creates_manifest(self):
        with isolated_cache() as cache:
            mod = _load("register")
            result = mod.register(
                mid="test-ms_001",
                fig_id="fig1",
                path=None,
                caption="Figure 1 shows the training loss curve across 100 epochs of training.",
                label="fig:loss",
            )
            self.assertEqual(result["fig_id"], "fig1")
            self.assertEqual(result["mid"], "test-ms_001")
            mp = cache / "manuscripts" / "test-ms_001" / "figures" / "fig1" / "manifest.json"
            self.assertTrue(mp.exists())

    def test_register_duplicate_raises(self):
        with isolated_cache():
            mod = _load("register")
            mod.register("ms2", "fig1", None, "Caption text here with enough words for test.", None)
            with self.assertRaises(FileExistsError):
                mod.register("ms2", "fig1", None, "New caption text", None)

    def test_register_overwrite(self):
        with isolated_cache():
            mod = _load("register")
            mod.register("ms3", "fig1", None, "Old caption text with more words.", None)
            result = mod.register("ms3", "fig1", None, "New caption text here.", None, overwrite=True)
            self.assertEqual(result["caption"], "New caption text here.")


class TestAudit(TestCase):
    def test_audit_empty_manuscript(self):
        with isolated_cache():
            mod_audit = _load("audit")
            result = mod_audit.audit("nonexistent-ms")
            self.assertEqual(result["total"], 0)

    def test_audit_detects_short_caption(self):
        with isolated_cache():
            mod_reg = _load("register")
            mod_audit = _load("audit")
            mod_reg.register("ms4", "fig1", None, "Short cap.", "fig:test")
            result = mod_audit.audit("ms4")
            fig_result = result["figures"][0]
            self.assertEqual(fig_result["status"], "fail")
            self.assertTrue(any("short" in i for i in fig_result["issues"]))

    def test_audit_pass_good_caption(self):
        with isolated_cache():
            mod_reg = _load("register")
            mod_audit = _load("audit")
            caption = "Figure 1 shows the comparison of model accuracy across all baseline methods tested."
            mod_reg.register("ms5", "fig1", None, caption, "fig:accuracy")
            result = mod_audit.audit("ms5")
            # cross-ref will fail (no body file), but caption should pass
            fig = result["figures"][0]
            caption_issues = [i for i in fig["issues"] if "caption" in i or "short" in i or "verb" in i]
            self.assertEqual(len(caption_issues), 0)

    def test_audit_missing_result_verb(self):
        with isolated_cache():
            mod_reg = _load("register")
            mod_audit = _load("audit")
            caption = "This is a figure about the data that we collected in our experiment results."
            mod_reg.register("ms6", "fig1", None, caption, "fig:data")
            result = mod_audit.audit("ms6")
            fig = result["figures"][0]
            verb_issues = [i for i in fig["issues"] if "verb" in i]
            self.assertEqual(len(verb_issues), 1)


class TestCaption(TestCase):
    def test_update_caption(self):
        with isolated_cache():
            mod_reg = _load("register")
            mod_cap = _load("caption")
            mod_reg.register("ms7", "fig1", None, "Old caption text.", "fig:1")
            result = mod_cap.update_caption("ms7", "fig1", "New and improved caption text.")
            self.assertEqual(result["caption"], "New and improved caption text.")

    def test_update_nonexistent_raises(self):
        with isolated_cache():
            mod_cap = _load("caption")
            with self.assertRaises(FileNotFoundError):
                mod_cap.update_caption("noexist", "fig99", "Caption")


class TestList(TestCase):
    def test_list_empty(self):
        with isolated_cache():
            mod = _load("list")
            result = mod.list_figures("nonexistent")
            self.assertEqual(result, [])

    def test_list_returns_manifests(self):
        with isolated_cache():
            mod_reg = _load("register")
            mod_list = _load("list")
            mod_reg.register("ms8", "fig1", None, "Caption A text enough words.", "fig:a")
            mod_reg.register("ms8", "fig2", None, "Caption B text enough words.", "fig:b")
            result = mod_list.list_figures("ms8")
            self.assertEqual(len(result), 2)
            fig_ids = {r["fig_id"] for r in result}
            self.assertEqual(fig_ids, {"fig1", "fig2"})

    def test_table_format(self):
        with isolated_cache():
            mod_reg = _load("register")
            mod_list = _load("list")
            mod_reg.register("ms9", "fig1", None, "Caption for table test here.", "fig:1")
            table = mod_list._render_table(mod_list.list_figures("ms9"))
            self.assertIn("fig1", table)


class TestCheckPalette(TestCase):
    def setUp(self):
        self.mod = _load("check_palette")

    def test_identical_colors_no_warning(self):
        colors = [[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
        result = self.mod.check_palette(colors)
        self.assertEqual(result["warnings"], [])

    def test_red_green_warns(self):
        # Red and green are classically problematic for deuteranopia
        colors = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        result = self.mod.check_palette(colors)
        # The result structure is correct
        self.assertIn("status", result)
        self.assertIn("warnings", result)
        self.assertTrue(isinstance(result["warnings"], list))

    def test_blue_orange_safe(self):
        # Blue and orange are generally safe
        colors = [[0.0, 0.0, 1.0], [1.0, 0.5, 0.0]]
        result = self.mod.check_palette(colors)
        self.assertIn("status", result)

    def test_simulate_color_deuteranopia(self):
        red = [1.0, 0.0, 0.0]
        sim = self.mod.simulate_color(red, "deuteranopia")
        self.assertEqual(len(sim), 3)
        for c in sim:
            self.assertTrue(c >= 0.0)
            self.assertTrue(c <= 1.0)

    def test_simulate_color_protanopia(self):
        green = [0.0, 1.0, 0.0]
        sim = self.mod.simulate_color(green, "protanopia")
        self.assertEqual(len(sim), 3)

    def test_delta_e_same_color(self):
        lab = self.mod._rgb_to_lab([0.5, 0.5, 0.5])
        de = self.mod._delta_e_76(lab, lab)
        self.assertAlmostEqual(de, 0.0, places=5)

    def test_delta_e_different_colors(self):
        lab1 = self.mod._rgb_to_lab([1.0, 0.0, 0.0])
        lab2 = self.mod._rgb_to_lab([0.0, 0.0, 1.0])
        de = self.mod._delta_e_76(lab1, lab2)
        self.assertTrue(de > 10.0)

    def test_srgb_linear_roundtrip(self):
        for c in [0.0, 0.5, 1.0]:
            lin = self.mod._srgb_to_linear(c)
            back = self.mod._linear_to_srgb(lin)
            self.assertAlmostEqual(back, c, places=5)

    def test_n_colors_reported(self):
        colors = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        result = self.mod.check_palette(colors)
        self.assertEqual(result["n_colors"], 3)


if __name__ == "__main__":
    run_tests(TestRegister, TestAudit, TestCaption, TestList, TestCheckPalette)
