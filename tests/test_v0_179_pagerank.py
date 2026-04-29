"""v0.179 — PageRank in lib.graph_advanced + field-trends --rank-by.

Pure stdlib power-iteration. Sanity tests on small fixtures.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = (
    _REPO / ".claude" / "skills" / "field-trends-analyzer"
    / "scripts" / "trends.py"
)


def _setup(papers: list[str], cites: list[tuple[str, str]]) -> str:
    """Build a project with paper nodes + cites edges (from→to)."""
    from lib import graph, project
    pid = project.create("pagerank-test")
    nids: dict[str, str] = {}
    for cid in papers:
        nids[cid] = graph.add_node(pid, "paper", cid, cid)
    for fr, to in cites:
        graph.add_edge(pid, nids[fr], nids[to], "cites")
    return pid


class V0179PagerankTests(TestCase):

    def test_empty_graph(self):
        with isolated_cache():
            from lib import project
            from lib.graph_advanced import pagerank
            pid = project.create("empty-pr")
            self.assertEqual(pagerank(pid), {})

    def test_single_isolated_node(self):
        with isolated_cache():
            from lib.graph_advanced import pagerank
            pid = _setup(["solo"], [])
            r = pagerank(pid)
            self.assertEqual(len(r), 1)
            self.assertAlmostEqual(r["paper:solo"], 1.0, places=6)

    def test_two_cycle_equal_scores(self):
        with isolated_cache():
            from lib.graph_advanced import pagerank
            pid = _setup(["a", "b"], [("a", "b"), ("b", "a")])
            r = pagerank(pid)
            self.assertAlmostEqual(r["paper:a"], r["paper:b"], places=4)
            self.assertAlmostEqual(
                r["paper:a"] + r["paper:b"], 1.0, places=4,
            )

    def test_linear_chain_terminal_highest(self):
        with isolated_cache():
            from lib.graph_advanced import pagerank
            # a → b → c (c gets all the rank flowing in)
            pid = _setup(["a", "b", "c"], [("a", "b"), ("b", "c")])
            r = pagerank(pid)
            self.assertGreater(r["paper:c"], r["paper:b"])
            self.assertGreater(r["paper:c"], r["paper:a"])

    def test_self_loop_no_recursion(self):
        with isolated_cache():
            from lib.graph_advanced import pagerank
            # x → x self-loop must terminate in finite iterations
            pid = _setup(["x", "y"], [("x", "x"), ("y", "x")])
            r = pagerank(pid)
            self.assertEqual(len(r), 2)
            # All scores finite + sum to ~1
            for v in r.values():
                self.assertTrue(v == v)  # not NaN
                self.assertGreaterEqual(v, 0.0)
            self.assertAlmostEqual(sum(r.values()), 1.0, places=4)

    def test_convergence_100_node_graph(self):
        with isolated_cache():
            from lib.graph_advanced import pagerank
            # Chain of 100 nodes — must converge well under 50 iters.
            papers = [f"p{i}" for i in range(100)]
            cites = [(f"p{i}", f"p{i+1}") for i in range(99)]
            t0 = time.time()
            pid = _setup(papers, cites)
            r = pagerank(pid, iterations=50)
            elapsed = time.time() - t0
            self.assertEqual(len(r), 100)
            self.assertAlmostEqual(sum(r.values()), 1.0, places=3)
            # Generous bound — we just want to make sure it doesn't hang.
            self.assertLess(elapsed, 30.0)

    def test_cli_accepts_rank_by_pagerank(self):
        with isolated_cache() as cache:
            pid = _setup(
                ["a", "b", "c"],
                [("a", "b"), ("b", "c"), ("a", "c")],
            )
            env = {**os.environ, "COSCIENTIST_CACHE_DIR": str(cache)}
            r = subprocess.run(
                [sys.executable, str(_SCRIPT), "papers",
                 "--project-id", pid,
                 "--rank-by", "pagerank",
                 "--top", "10"],
                capture_output=True, text=True, env=env, timeout=30,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(r.stdout)
            self.assertEqual(data["rank_by"], "pagerank")
            self.assertTrue(len(data["papers"]) > 0)
            # Each entry has pagerank field.
            self.assertIn("pagerank", data["papers"][0])


if __name__ == "__main__":
    sys.exit(run_tests(V0179PagerankTests))
