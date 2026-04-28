"""Tests for the statistics skill."""
from __future__ import annotations

import math
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from tests.harness import CoscientistTestCase  # noqa
import importlib.util as _ilu


def _load(name: str):
    spec = _ilu.spec_from_file_location(
        name, _REPO_ROOT / ".claude/skills/statistics/scripts" / f"{name}.py"
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_mathutils():
    return _load("_mathutils")


class TestMathUtils(CoscientistTestCase):
    def setUp(self):
        self.mu = _load_mathutils()

    def test_norm_cdf_midpoint(self):
        self.assertAlmostEqual(self.mu._norm_cdf(0.0), 0.5, places=5)

    def test_norm_cdf_positive(self):
        self.assertAlmostEqual(self.mu._norm_cdf(1.96), 0.975, places=2)

    def test_norm_cdf_negative(self):
        self.assertAlmostEqual(self.mu._norm_cdf(-1.96), 0.025, places=2)

    def test_norm_ppf_roundtrip(self):
        for p in [0.025, 0.1, 0.5, 0.9, 0.975]:
            self.assertAlmostEqual(
                self.mu._norm_cdf(self.mu._norm_ppf(p)), p, places=4
            )

    def test_chi2_cdf_wh_zero(self):
        self.assertEqual(self.mu._chi2_cdf_wh(0.0, 1), 0.0)

    def test_chi2_cdf_wh_reasonable(self):
        v = self.mu._chi2_cdf_wh(3.84, 1)
        self.assertGreater(v, 0.9)
        self.assertLess(v, 1.0)


class TestEffectSize(CoscientistTestCase):
    def setUp(self):
        self.es = _load("effect_size")

    def test_cohen_d_zero(self):
        r = self.es.cohen_d(10.0, 10.0, 2.0, 2.0, 20, 20)
        self.assertAlmostEqual(r["value"], 0.0, places=5)

    def test_cohen_d_medium(self):
        r = self.es.cohen_d(10.5, 10.0, 1.0, 1.0, 30, 30)
        self.assertAlmostEqual(r["value"], 0.5, places=3)
        self.assertEqual(r["interpretation"], "medium")

    def test_hedges_g_close_to_cohen_d(self):
        r_d = self.es.cohen_d(12.0, 10.0, 2.0, 2.0, 30, 30)
        r_g = self.es.hedges_g(12.0, 10.0, 2.0, 2.0, 30, 30)
        self.assertAlmostEqual(r_d["value"], r_g["value"], places=1)

    def test_glass_delta(self):
        r = self.es.glass_delta(12.0, 10.0, 2.0)
        self.assertAlmostEqual(r["value"], 1.0, places=5)

    def test_eta_squared(self):
        r = self.es.eta_squared(10.0, 100.0)
        self.assertAlmostEqual(r["value"], 0.1, places=5)

    def test_cramers_v(self):
        r = self.es.cramers_v(chi2=10.0, n=100, min_dim=2)
        self.assertAlmostEqual(r["value"], math.sqrt(10.0 / (100 * 1)), places=5)

    def test_interpretation_large(self):
        r = self.es.cohen_d(18.0, 10.0, 2.0, 2.0, 50, 50)
        self.assertEqual(r["interpretation"], "large")

    def test_interpretation_small(self):
        # d = 0.3 is clearly in small range (0.2 to 0.5)
        r = self.es.cohen_d(10.3, 10.0, 1.0, 1.0, 50, 50)
        self.assertEqual(r["interpretation"], "small")


class TestPower(CoscientistTestCase):
    def setUp(self):
        self.pw = _load("power")

    def test_solve_n_t_benchmark(self):
        """Cohen (1988): d=0.5, alpha=0.05, power=0.8 -> n approx 64 per group."""
        r = self.pw.solve_n("t", effect_size=0.5, alpha=0.05, power=0.8)
        self.assertIn("n", r)
        self.assertGreater(r["n"], 50)
        self.assertLess(r["n"], 80)

    def test_solve_power_increases_with_n(self):
        p1 = self.pw.solve_power("t", n=30, effect_size=0.5, alpha=0.05)
        p2 = self.pw.solve_power("t", n=100, effect_size=0.5, alpha=0.05)
        self.assertGreater(p2["power"], p1["power"])

    def test_solve_n_z(self):
        r = self.pw.solve_n("z", effect_size=0.5, alpha=0.05, power=0.8)
        self.assertIn("n", r)
        self.assertGreater(r["n"], 20)

    def test_solve_n_chi2(self):
        r = self.pw.solve_n("chi2", effect_size=0.3, alpha=0.05, power=0.8)
        self.assertIn("n", r)

    def test_solve_power_anova(self):
        r = self.pw.solve_power("anova", n=30, effect_size=0.25, alpha=0.05, k=3)
        self.assertGreater(r["power"], 0)
        self.assertLess(r["power"], 1.0)

    def test_solve_alpha(self):
        r = self.pw.solve_alpha("t", n=64, effect_size=0.5, power=0.8)
        self.assertIn("alpha", r)
        self.assertAlmostEqual(r["alpha"], 0.05, places=1)


class TestMetaAnalysis(CoscientistTestCase):
    def setUp(self):
        self.ma = _load("meta_analysis")

    def _studies(self):
        return [
            {"effect": 0.5, "variance": 0.04, "label": "A"},
            {"effect": 0.6, "variance": 0.05, "label": "B"},
            {"effect": 0.4, "variance": 0.03, "label": "C"},
        ]

    def test_fixed_pooled_within_range(self):
        r = self.ma.fixed_effects(self._studies())
        self.assertGreater(r["pooled_effect"], 0.3)
        self.assertLess(r["pooled_effect"], 0.7)

    def test_random_pooled_within_range(self):
        r = self.ma.random_effects(self._studies())
        self.assertGreater(r["pooled_effect"], 0.3)
        self.assertLess(r["pooled_effect"], 0.7)

    def test_i2_bounded(self):
        r = self.ma.random_effects(self._studies())
        self.assertGreaterEqual(r["I2"], 0.0)
        self.assertLessEqual(r["I2"], 1.0)

    def test_tau2_nonneg(self):
        r = self.ma.random_effects(self._studies())
        self.assertGreaterEqual(r["tau2"], 0.0)

    def test_heterogeneity_label(self):
        high_var = [
            {"effect": 0.1, "variance": 0.04},
            {"effect": 0.9, "variance": 0.04},
            {"effect": 0.5, "variance": 0.04},
        ]
        r = self.ma.random_effects(high_var)
        self.assertIn(r["heterogeneity"], ["low", "moderate", "high"])

    def test_ci_contains_estimate(self):
        r = self.ma.fixed_effects(self._studies())
        self.assertLess(r["ci_95"][0], r["pooled_effect"])
        self.assertGreater(r["ci_95"][1], r["pooled_effect"])

    def test_k_count(self):
        r = self.ma.fixed_effects(self._studies())
        self.assertEqual(r["k"], 3)


class TestTestSelect(CoscientistTestCase):
    def setUp(self):
        self.ts = _load("test_select")

    def test_continuous_two_groups(self):
        r = self.ts.recommend(n=50, groups=2, paired=False, outcome="continuous")
        self.assertEqual(r["recommended_test"], "independent_t")

    def test_small_n_nonparametric(self):
        r = self.ts.recommend(n=10, groups=2, paired=False, outcome="continuous")
        self.assertEqual(r["recommended_test"], "mann_whitney")

    def test_paired_t(self):
        r = self.ts.recommend(n=50, groups=2, paired=True, outcome="continuous")
        self.assertEqual(r["recommended_test"], "paired_t")

    def test_binary_outcome(self):
        r = self.ts.recommend(n=100, groups=2, paired=False, outcome="binary")
        self.assertEqual(r["recommended_test"], "chi_squared")

    def test_anova(self):
        r = self.ts.recommend(n=60, groups=3, paired=False, outcome="continuous")
        self.assertEqual(r["recommended_test"], "one_way_anova")

    def test_assumptions_present(self):
        r = self.ts.recommend(n=50, groups=2, paired=False, outcome="continuous")
        self.assertIsInstance(r["assumptions"], list)
        self.assertGreater(len(r["assumptions"]), 0)


class TestAssumptionCheck(CoscientistTestCase):
    def setUp(self):
        self.ac = _load("assumption_check")

    def test_normality_pass(self):
        import random
        random.seed(42)
        data = [random.gauss(0, 1) for _ in range(50)]
        r = self.ac.check_normality(data)
        self.assertIn(r["status"], ["pass", "fail"])
        self.assertIn("skewness", r)

    def test_normality_fail_skewed(self):
        data = [0.01] * 45 + [100.0] * 5
        r = self.ac.check_normality(data)
        self.assertEqual(r["status"], "fail")

    def test_variance_two_groups(self):
        g1 = [1.0, 2.0, 1.5, 1.8, 2.1]
        g2 = [10.0, 20.0, 15.0, 18.0, 21.0]
        r = self.ac.check_variance([g1, g2])
        self.assertIn(r["status"], ["pass", "fail"])

    def test_independence_no_autocorr(self):
        import random
        random.seed(0)
        data = [random.random() for _ in range(30)]
        r = self.ac.check_independence(data)
        self.assertIn("durbin_watson", r)
        self.assertAlmostEqual(r["durbin_watson"], 2.0, delta=0.8)

    def test_independence_insufficient(self):
        r = self.ac.check_independence([1.0, 2.0])
        self.assertEqual(r["status"], "insufficient_data")
