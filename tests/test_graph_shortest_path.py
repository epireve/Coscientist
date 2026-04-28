"""v0.79 — lib.graph.shortest_path unit tests.

Promoted from graph-query-mcp v0.74. Same algorithm, lib-level API.
"""
from __future__ import annotations

from lib import graph, project
from tests.harness import TestCase, isolated_cache, run_tests


def _seed(pid: str):
    """A -cites-> B -cites-> C, A -cites-> D, A -about-> concept:t."""
    graph.add_node(pid, "paper", "A", "Paper A")
    graph.add_node(pid, "paper", "B", "Paper B")
    graph.add_node(pid, "paper", "C", "Paper C")
    graph.add_node(pid, "paper", "D", "Paper D")
    graph.add_node(pid, "concept", "t", "Transformers")
    graph.add_edge(pid, "paper:A", "paper:B", "cites")
    graph.add_edge(pid, "paper:B", "paper:C", "cites")
    graph.add_edge(pid, "paper:A", "paper:D", "cites")
    graph.add_edge(pid, "paper:A", "concept:t", "about")


class ShortestPathTests(TestCase):
    def test_self_path(self):
        with isolated_cache():
            pid = project.create("sp self")
            _seed(pid)
            path = graph.shortest_path(pid, "paper:A", "paper:A")
            self.assertEqual(path, ["paper:A"])

    def test_two_hops(self):
        with isolated_cache():
            pid = project.create("sp two")
            _seed(pid)
            path = graph.shortest_path(pid, "paper:A", "paper:C")
            self.assertEqual(path, ["paper:A", "paper:B", "paper:C"])

    def test_no_path(self):
        with isolated_cache():
            pid = project.create("sp none")
            _seed(pid)
            # paper:D has no outgoing edges.
            self.assertIsNone(
                graph.shortest_path(pid, "paper:D", "paper:C"))

    def test_max_hops_cutoff(self):
        with isolated_cache():
            pid = project.create("sp cut")
            _seed(pid)
            self.assertIsNone(
                graph.shortest_path(
                    pid, "paper:A", "paper:C", max_hops=1,
                ),
            )

    def test_relation_filter(self):
        with isolated_cache():
            pid = project.create("sp rel")
            _seed(pid)
            # `cites` does NOT reach concept:t.
            self.assertIsNone(graph.shortest_path(
                pid, "paper:A", "concept:t", relation="cites",
            ))
            # `about` does (1 hop).
            path = graph.shortest_path(
                pid, "paper:A", "concept:t", relation="about",
            )
            self.assertEqual(path, ["paper:A", "concept:t"])

    def test_one_hop_direct(self):
        with isolated_cache():
            pid = project.create("sp one")
            _seed(pid)
            path = graph.shortest_path(pid, "paper:A", "paper:B")
            self.assertEqual(path, ["paper:A", "paper:B"])


if __name__ == "__main__":
    raise SystemExit(run_tests(ShortestPathTests))
