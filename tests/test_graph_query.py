"""v0.47 tests for graph-query skill."""

from tests import _shim  # noqa: F401

import json
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
QUERY = _ROOT / ".claude/skills/graph-query/scripts/query.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(QUERY), *args],
        capture_output=True, text=True,
    )


def _setup_and_seed(name: str = "p1") -> str:
    """Create project, seed graph, return project_id."""
    from lib.project import create
    pid = create(name, question="test")
    _seed_graph(pid)
    return pid


def _seed_graph(pid: str) -> None:
    """Seed: A→B→C cites chain + author with two papers."""
    from lib import graph
    graph.add_node(pid, "paper", "A", label="Paper A")
    graph.add_node(pid, "paper", "B", label="Paper B")
    graph.add_node(pid, "paper", "C", label="Paper C")
    graph.add_node(pid, "concept", "transformer", label="Transformer")
    graph.add_node(pid, "author", "auth1", label="Alice")
    graph.add_node(pid, "author", "auth2", label="Bob")

    graph.add_edge(pid, "paper:A", "paper:B", "cites")
    graph.add_edge(pid, "paper:B", "paper:C", "cites")
    graph.add_edge(pid, "paper:A", "paper:C", "cites")  # also A→C
    graph.add_edge(pid, "paper:A", "concept:transformer", "about")
    graph.add_edge(pid, "paper:A", "author:auth1", "authored-by")
    graph.add_edge(pid, "paper:A", "author:auth2", "authored-by")
    graph.add_edge(pid, "paper:B", "author:auth1", "authored-by")


class ExpandCitationsTests(TestCase):
    def test_walks_one_hop(self):
        with isolated_cache():
            pid = _setup_and_seed("p_e1")
            r = _run("expand-citations", "--project-id", pid,
                       "--canonical-id", "A", "--depth", "1")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            ids = {n["node_id"] for n in out["nodes"]}
            # B and C reachable in 1 hop (A→B, A→C)
            self.assertIn("paper:B", ids)
            self.assertIn("paper:C", ids)

    def test_walks_two_hops_includes_transitive(self):
        with isolated_cache():
            pid = _setup_and_seed("p_e2")
            r = _run("expand-citations", "--project-id", pid,
                       "--canonical-id", "A", "--depth", "2")
            out = json.loads(r.stdout)
            ids = {n["node_id"] for n in out["nodes"]}
            # B + C still in (depth 1 + 2 transitively)
            self.assertIn("paper:B", ids)
            self.assertIn("paper:C", ids)


class InDegreeTests(TestCase):
    def test_counts_inbound_cites(self):
        with isolated_cache():
            pid = _setup_and_seed("p_d1")
            r = _run("in-degree", "--project-id", pid,
                       "--canonical-id", "C")
            out = json.loads(r.stdout)
            # B→C and A→C → in_degree=2
            self.assertEqual(out["in_degree"], 2)

    def test_isolated_paper_returns_zero(self):
        with isolated_cache():
            pid = _setup_and_seed("p_d2")
            r = _run("in-degree", "--project-id", pid,
                       "--canonical-id", "A")
            out = json.loads(r.stdout)
            # Nothing cites A
            self.assertEqual(out["in_degree"], 0)


class HubsTests(TestCase):
    def test_hubs_ranks_by_in_degree(self):
        with isolated_cache():
            pid = _setup_and_seed("p_h1")
            r = _run("hubs", "--project-id", pid,
                       "--kind", "paper", "--top", "5")
            out = json.loads(r.stdout)
            top = out["hubs"][0]
            # C has in-degree 2 (highest)
            self.assertEqual(top["node_id"], "paper:C")


class NeighborsTests(TestCase):
    def test_outgoing_neighbors_filtered(self):
        with isolated_cache():
            pid = _setup_and_seed("p_n1")
            r = _run("neighbors", "--project-id", pid,
                       "--node-id", "paper:A", "--relation", "cites",
                       "--direction", "out")
            out = json.loads(r.stdout)
            ids = {n["node_id"] for n in out["neighbors"]}
            self.assertEqual(ids, {"paper:B", "paper:C"})

    def test_no_relation_filter_returns_all(self):
        with isolated_cache():
            pid = _setup_and_seed("p_n2")
            r = _run("neighbors", "--project-id", pid,
                       "--node-id", "paper:A", "--direction", "out")
            out = json.loads(r.stdout)
            # paper:A has 2 cites + 1 about + 2 authored-by → 5 outbound
            self.assertEqual(out["count"], 5)


class ConceptPathTests(TestCase):
    def test_path_found_within_max_hops(self):
        with isolated_cache():
            pid = _setup_and_seed("p_p1")
            r = _run("concept-path", "--project-id", pid,
                       "--from", "A", "--to", "C", "--max-hops", "3")
            out = json.loads(r.stdout)
            self.assertTrue(out["found"])
            self.assertGreater(out["length"], 0)

    def test_same_node_returns_zero_length(self):
        with isolated_cache():
            pid = _setup_and_seed("p_p2")
            r = _run("concept-path", "--project-id", pid,
                       "--from", "A", "--to", "A")
            out = json.loads(r.stdout)
            self.assertTrue(out["found"])
            self.assertEqual(out["length"], 0)


class AuthorClusterTests(TestCase):
    def test_cluster_finds_co_authors(self):
        with isolated_cache():
            pid = _setup_and_seed("p_a1")
            r = _run("author-cluster", "--project-id", pid,
                       "--s2-id", "auth1")
            out = json.loads(r.stdout)
            ids = {a["node_id"] for a in out["co_authors"]}
            # auth1 is on A + B; auth2 is also on A → co-author
            self.assertIn("author:auth2", ids)


class CliTests(TestCase):
    def test_no_subcommand_errors(self):
        r = _run()
        self.assertTrue(r.returncode != 0)

    def test_missing_project_db_errors(self):
        with isolated_cache():
            r = _run("hubs", "--project-id", "nonexistent",
                       "--kind", "paper")
            self.assertTrue(r.returncode != 0)
            self.assertIn("no project DB", r.stderr)

    def test_md_format_renders(self):
        with isolated_cache():
            pid = _setup_and_seed("p_md")
            r = _run("--format", "md", "hubs",
                       "--project-id", pid, "--kind", "paper")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("# graph-query hubs", r.stdout)


if __name__ == "__main__":
    sys.exit(run_tests(
        ExpandCitationsTests, InDegreeTests, HubsTests, NeighborsTests,
        ConceptPathTests, AuthorClusterTests, CliTests,
    ))
