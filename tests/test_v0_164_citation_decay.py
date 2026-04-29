"""v0.164 — citation-decay skill tests."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = (
    _REPO / ".claude" / "skills" / "citation-decay"
    / "scripts" / "citation_decay.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "citation_decay_v164", _SCRIPT,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["citation_decay_v164"] = mod
    spec.loader.exec_module(mod)
    return mod


def _setup_project(name: str = "decay tests") -> str:
    from lib import project as project_mod
    return project_mod.create(name)


def _add_paper(pid: str, cid: str, title: str = "", year: int | None = None):
    from lib import graph as graph_mod
    from lib.cache import paper_dir
    nid = graph_mod.add_node(pid, "paper", cid, title or cid)
    if year is not None:
        d = paper_dir(cid)
        d.mkdir(parents=True, exist_ok=True)
        (d / "metadata.json").write_text(json.dumps({"year": year}))
    return nid


def _add_cite(pid: str, citer_nid: str, target_nid: str) -> None:
    from lib import graph as graph_mod
    graph_mod.add_edge(pid, citer_nid, target_nid, "cites")


def _row_counts(pid: str) -> tuple[int, int]:
    from lib.cache import cache_root
    db = cache_root() / "projects" / pid / "project.db"
    con = sqlite3.connect(db)
    try:
        nodes = con.execute(
            "SELECT COUNT(*) FROM graph_nodes"
        ).fetchone()[0]
        edges = con.execute(
            "SELECT COUNT(*) FROM graph_edges"
        ).fetchone()[0]
    finally:
        con.close()
    return nodes, edges


def _scaffold(pid: str) -> dict:
    """Target paper T (2010); citers spread across years 2012/2015/2020/2024."""
    t = _add_paper(pid, "target", "Target", year=2010)
    c1 = _add_paper(pid, "c1", "Citer 1", year=2012)
    c2 = _add_paper(pid, "c2", "Citer 2", year=2015)
    c3 = _add_paper(pid, "c3", "Citer 3", year=2015)
    c4 = _add_paper(pid, "c4", "Citer 4", year=2020)
    c5 = _add_paper(pid, "c5", "Citer 5", year=2024)
    for c in (c1, c2, c3, c4, c5):
        _add_cite(pid, c, t)
    return {"target": t, "c1": c1, "c2": c2, "c3": c3, "c4": c4, "c5": c5}


# ---- Tests ---------------------------------------------------------------


class ForPaperTests(TestCase):
    def test_year_buckets_aggregated(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            _scaffold(pid)
            res = mod.for_paper(pid, "target", current_year=2026)
            self.assertTrue("error" not in res, msg=str(res))
            self.assertEqual(res["year_buckets"][2012], 1)
            self.assertEqual(res["year_buckets"][2015], 2)
            self.assertEqual(res["year_buckets"][2020], 1)
            self.assertEqual(res["year_buckets"][2024], 1)
            self.assertEqual(res["total_citations"], 5)

    def test_most_recent_citer_year(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            _scaffold(pid)
            res = mod.for_paper(pid, "target", current_year=2026)
            self.assertEqual(res["most_recent_citer_year"], 2024)

    def test_recent_window_count(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            _scaffold(pid)
            # current=2026, decay=5 → cutoff=2021; 2024 only (1 citer)
            res = mod.for_paper(pid, "target", decay_years=5,
                                current_year=2026)
            self.assertEqual(res["recent_window_count"], 1)
            # decay=15 → cutoff=2011; 5 citers
            res2 = mod.for_paper(pid, "target", decay_years=15,
                                 current_year=2026)
            self.assertEqual(res2["recent_window_count"], 5)

    def test_missing_paper_returns_error(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            res = mod.for_paper(pid, "no-such")
            self.assertTrue("error" in res)

    def test_paper_without_year_returns_error(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            _add_paper(pid, "no-year", "No Year", year=None)
            res = mod.for_paper(pid, "no-year")
            self.assertTrue("error" in res)

    def test_zero_citations(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            _add_paper(pid, "lonely", "Lonely", year=2015)
            res = mod.for_paper(pid, "lonely", current_year=2026)
            self.assertTrue("error" not in res)
            self.assertEqual(res["total_citations"], 0)
            self.assertEqual(res["year_buckets"], {})
            self.assertTrue(res["most_recent_citer_year"] is None)


class VelocityTests(TestCase):
    def test_ranks_by_citations_per_year(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            # Hot paper: 2024, 2 cites in 2025 → 2 / max(1, 2) = 1.0
            hot = _add_paper(pid, "hot", "Hot", year=2024)
            ch1 = _add_paper(pid, "ch1", "ch1", year=2025)
            ch2 = _add_paper(pid, "ch2", "ch2", year=2025)
            _add_cite(pid, ch1, hot)
            _add_cite(pid, ch2, hot)
            # Slow paper: 2000, 2 cites total → 2 / 26 ≈ 0.077
            slow = _add_paper(pid, "slow", "Slow", year=2000)
            cs1 = _add_paper(pid, "cs1", "cs1", year=2010)
            cs2 = _add_paper(pid, "cs2", "cs2", year=2015)
            _add_cite(pid, cs1, slow)
            _add_cite(pid, cs2, slow)
            res = mod.velocity(pid, top_n=20, current_year=2026)
            self.assertTrue("error" not in res)
            cids = [r["canonical_id"] for r in res["papers"]]
            self.assertEqual(cids[0], "hot")
            self.assertTrue(cids.index("hot") < cids.index("slow"))

    def test_skips_papers_without_year(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            _add_paper(pid, "with-year", "With", year=2020)
            _add_paper(pid, "no-year", "No", year=None)
            res = mod.velocity(pid, current_year=2026)
            cids = [r["canonical_id"] for r in res["papers"]]
            self.assertIn("with-year", cids)
            self.assertNotIn("no-year", cids)

    def test_top_n_caps(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            for i in range(5):
                _add_paper(pid, f"p{i}", f"P{i}", year=2020)
            res = mod.velocity(pid, top_n=2, current_year=2026)
            self.assertEqual(len(res["papers"]), 2)


class StaleTests(TestCase):
    def test_detects_high_cite_no_recent(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            # 6 citers all from 2010 (oldest = newest = 2010)
            t = _add_paper(pid, "classic", "Classic", year=2000)
            for i in range(6):
                c = _add_paper(pid, f"old{i}", f"Old{i}", year=2010)
                _add_cite(pid, c, t)
            res = mod.stale(pid, min_citations=5, decay_years=5,
                            current_year=2026)
            self.assertTrue("error" not in res)
            cids = [r["canonical_id"] for r in res["stale"]]
            self.assertIn("classic", cids)

    def test_skips_below_min_citations(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            t = _add_paper(pid, "few", "Few", year=2000)
            for i in range(2):
                c = _add_paper(pid, f"old{i}", f"Old{i}", year=2010)
                _add_cite(pid, c, t)
            res = mod.stale(pid, min_citations=5, current_year=2026)
            cids = [r["canonical_id"] for r in res["stale"]]
            self.assertNotIn("few", cids)

    def test_skips_papers_with_recent_citers(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            t = _add_paper(pid, "live", "Live", year=2000)
            # 5 citers, one in 2025 (recent)
            for i, y in enumerate([2010, 2010, 2010, 2010, 2025]):
                c = _add_paper(pid, f"c{i}", f"C{i}", year=y)
                _add_cite(pid, c, t)
            res = mod.stale(pid, min_citations=5, decay_years=5,
                            current_year=2026)
            cids = [r["canonical_id"] for r in res["stale"]]
            self.assertNotIn("live", cids)


class FormatTests(TestCase):
    def test_json_vs_text_for_paper(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            _scaffold(pid)
            payload = mod.for_paper(pid, "target", current_year=2026)
            txt = mod._format_text(payload)
            self.assertIn("Citations of target", txt)
            self.assertTrue(isinstance(payload, dict))


class CurrentYearTests(TestCase):
    def test_current_year_override(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            _scaffold(pid)
            # current=2018, decay=2 → cutoff=2016; only 2020(1)+2024(1)=2
            res = mod.for_paper(pid, "target", decay_years=2,
                                current_year=2018)
            self.assertEqual(res["current_year"], 2018)
            self.assertEqual(res["recent_window_count"], 2)


class CLITests(TestCase):
    def test_cli_help_top_level(self):
        out = subprocess.run(
            [sys.executable, str(_SCRIPT), "--help"],
            capture_output=True, text=True,
        )
        self.assertEqual(out.returncode, 0)
        self.assertIn("for-paper", out.stdout)
        self.assertIn("velocity", out.stdout)
        self.assertIn("stale", out.stdout)

    def test_cli_help_subcommands(self):
        for sub in ("for-paper", "velocity", "stale"):
            out = subprocess.run(
                [sys.executable, str(_SCRIPT), sub, "--help"],
                capture_output=True, text=True,
            )
            self.assertEqual(out.returncode, 0,
                             msg=f"{sub} --help: {out.stderr}")
            self.assertIn("--project-id", out.stdout)


class ReadOnlyTests(TestCase):
    def test_no_writes_during_aggregation(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            _scaffold(pid)
            n_before, e_before = _row_counts(pid)
            mod.for_paper(pid, "target", current_year=2026)
            mod.velocity(pid, current_year=2026)
            mod.stale(pid, min_citations=5, current_year=2026)
            n_after, e_after = _row_counts(pid)
            self.assertEqual(n_before, n_after)
            self.assertEqual(e_before, e_after)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        ForPaperTests,
        VelocityTests,
        StaleTests,
        FormatTests,
        CurrentYearTests,
        CLITests,
        ReadOnlyTests,
    ))
