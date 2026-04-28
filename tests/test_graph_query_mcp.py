"""v0.74 — graph-query-mcp tests using a real project DB."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]
_SERVER = _REPO / "mcp" / "graph-query-mcp" / "server.py"


def _import_server():
    if "mcp" not in sys.modules:
        import types
        mcp_pkg = types.ModuleType("mcp")
        mcp_server = types.ModuleType("mcp.server")
        mcp_fastmcp = types.ModuleType("mcp.server.fastmcp")

        class _StubMCP:
            def __init__(self, name): self.name = name
            def tool(self):
                def deco(fn): return fn
                return deco
            def run(self): pass

        mcp_fastmcp.FastMCP = _StubMCP
        sys.modules["mcp"] = mcp_pkg
        sys.modules["mcp.server"] = mcp_server
        sys.modules["mcp.server.fastmcp"] = mcp_fastmcp

    spec = importlib.util.spec_from_file_location(
        "graph_query_mcp_server", _SERVER,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed_graph(project_id: str):
    """Build a small graph: A -cites-> B -cites-> C, A -cites-> D."""
    from lib import graph
    graph.add_node(project_id, "paper", "A", "Paper A")
    graph.add_node(project_id, "paper", "B", "Paper B")
    graph.add_node(project_id, "paper", "C", "Paper C")
    graph.add_node(project_id, "paper", "D", "Paper D")
    graph.add_node(project_id, "concept", "transformers", "Transformers")
    graph.add_edge(project_id, "paper:A", "paper:B", "cites")
    graph.add_edge(project_id, "paper:B", "paper:C", "cites")
    graph.add_edge(project_id, "paper:A", "paper:D", "cites")
    graph.add_edge(project_id, "paper:A", "concept:transformers", "about")
    graph.add_edge(project_id, "paper:B", "concept:transformers", "about")


class NeighborsTests(TestCase):
    def setUp(self):
        self.mod = _import_server()

    def test_neighbors_out(self):
        with isolated_cache():
            from lib import project
            pid = project.create("Graph test")
            _seed_graph(pid)
            out = self.mod.neighbors(pid, "paper:A")
            self.assertEqual(out["n_neighbors"], 3)
            ids = {n["node_id"] for n in out["neighbors"]}
            self.assertEqual(
                ids, {"paper:B", "paper:D", "concept:transformers"})

    def test_neighbors_with_relation_filter(self):
        with isolated_cache():
            from lib import project
            pid = project.create("Graph filter")
            _seed_graph(pid)
            out = self.mod.neighbors(pid, "paper:A", relation="cites")
            ids = {n["node_id"] for n in out["neighbors"]}
            self.assertEqual(ids, {"paper:B", "paper:D"})

    def test_neighbors_in_direction(self):
        with isolated_cache():
            from lib import project
            pid = project.create("Graph indir")
            _seed_graph(pid)
            out = self.mod.neighbors(pid, "concept:transformers",
                                      direction="in")
            ids = {n["node_id"] for n in out["neighbors"]}
            self.assertEqual(ids, {"paper:A", "paper:B"})


class WalkTests(TestCase):
    def setUp(self):
        self.mod = _import_server()

    def test_walk_two_hops(self):
        with isolated_cache():
            from lib import project
            pid = project.create("Walk test")
            _seed_graph(pid)
            out = self.mod.walk(pid, "paper:A", "cites", max_hops=2)
            ids = {n["node_id"] for n in out["reached"]}
            self.assertEqual(ids, {"paper:B", "paper:C", "paper:D"})

    def test_walk_one_hop(self):
        with isolated_cache():
            from lib import project
            pid = project.create("Walk one hop")
            _seed_graph(pid)
            out = self.mod.walk(pid, "paper:A", "cites", max_hops=1)
            ids = {n["node_id"] for n in out["reached"]}
            self.assertEqual(ids, {"paper:B", "paper:D"})


class InDegreeTests(TestCase):
    def setUp(self):
        self.mod = _import_server()

    def test_in_degree_all_relations(self):
        with isolated_cache():
            from lib import project
            pid = project.create("Indeg test")
            _seed_graph(pid)
            out = self.mod.in_degree(pid, "concept:transformers")
            self.assertEqual(out["in_degree"], 2)

    def test_in_degree_filtered(self):
        with isolated_cache():
            from lib import project
            pid = project.create("Indeg filter")
            _seed_graph(pid)
            out = self.mod.in_degree(pid, "paper:C", relation="cites")
            self.assertEqual(out["in_degree"], 1)

    def test_in_degree_zero(self):
        with isolated_cache():
            from lib import project
            pid = project.create("Indeg zero")
            _seed_graph(pid)
            out = self.mod.in_degree(pid, "paper:A")
            self.assertEqual(out["in_degree"], 0)


class HubsTests(TestCase):
    def setUp(self):
        self.mod = _import_server()

    def test_hubs_papers(self):
        with isolated_cache():
            from lib import project
            pid = project.create("Hubs test")
            _seed_graph(pid)
            out = self.mod.hubs(pid, "paper", relation="cites", top_k=5)
            ids = [h["node_id"] for h in out["hubs"]]
            # B and D each get cited once; C also cited once. A cited zero.
            self.assertIn("paper:B", ids)
            # paper:A cited zero times; should not appear in citations top
            top_ids_with_indegree = {
                h["node_id"] for h in out["hubs"]
                if h.get("in_degree", 0) > 0
            }
            self.assertNotIn("paper:A", top_ids_with_indegree)


class NodeInfoTests(TestCase):
    def setUp(self):
        self.mod = _import_server()

    def test_existing_node(self):
        with isolated_cache():
            from lib import project
            pid = project.create("Info test")
            _seed_graph(pid)
            out = self.mod.node_info(pid, "paper:A")
            self.assertTrue(out["found"])
            self.assertEqual(out["node"]["label"], "Paper A")

    def test_missing_node(self):
        with isolated_cache():
            from lib import project
            pid = project.create("Missing node")
            _seed_graph(pid)
            out = self.mod.node_info(pid, "paper:nonexistent")
            self.assertFalse(out["found"])


class ShortestPathTests(TestCase):
    def setUp(self):
        self.mod = _import_server()

    def test_self_path(self):
        with isolated_cache():
            from lib import project
            pid = project.create("Self path")
            _seed_graph(pid)
            out = self.mod.shortest_path(pid, "paper:A", "paper:A")
            self.assertTrue(out["found"])
            self.assertEqual(out["length"], 0)
            self.assertEqual(out["path"], ["paper:A"])

    def test_two_hop_path(self):
        with isolated_cache():
            from lib import project
            pid = project.create("Two hop")
            _seed_graph(pid)
            out = self.mod.shortest_path(pid, "paper:A", "paper:C")
            self.assertTrue(out["found"])
            self.assertEqual(out["length"], 2)
            self.assertEqual(out["path"], ["paper:A", "paper:B", "paper:C"])

    def test_no_path_within_hops(self):
        with isolated_cache():
            from lib import project
            pid = project.create("No path")
            _seed_graph(pid)
            out = self.mod.shortest_path(pid, "paper:A", "paper:C", max_hops=1)
            self.assertFalse(out["found"])

    def test_no_path_disconnected(self):
        with isolated_cache():
            from lib import project
            pid = project.create("Disconnected")
            _seed_graph(pid)
            # paper:D has no outgoing edges.
            out = self.mod.shortest_path(pid, "paper:D", "paper:C")
            self.assertFalse(out["found"])

    def test_relation_filter(self):
        with isolated_cache():
            from lib import project
            pid = project.create("Rel filter")
            _seed_graph(pid)
            # A -about-> concept:transformers exists; A -cites-> doesn't reach it.
            out = self.mod.shortest_path(
                pid, "paper:A", "concept:transformers",
                relation="cites",
            )
            self.assertFalse(out["found"])
            out2 = self.mod.shortest_path(
                pid, "paper:A", "concept:transformers",
                relation="about",
            )
            self.assertTrue(out2["found"])
            self.assertEqual(out2["length"], 1)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        NeighborsTests,
        WalkTests,
        InDegreeTests,
        HubsTests,
        NodeInfoTests,
        ShortestPathTests,
    ))
