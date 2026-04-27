"""v0.59 tests for graph-viz mermaid renderer."""

from tests import _shim  # noqa: F401

import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
RENDER = _ROOT / ".claude/skills/graph-viz/scripts/render.py"


def _seed_simple(pid: str) -> None:
    """A→B cites, A about transformer concept."""
    from lib import graph
    graph.add_node(pid, "paper", "A", label="Paper A")
    graph.add_node(pid, "paper", "B", label="Paper B")
    graph.add_node(pid, "concept", "transformer", label="Transformer")
    graph.add_edge(pid, "paper:A", "paper:B", "cites")
    graph.add_edge(pid, "paper:A", "concept:transformer", "about")


class RenderMermaidTests(TestCase):
    def test_empty_graph_returns_minimal_block(self):
        from lib.graph_viz import render_mermaid
        out = render_mermaid([], [])
        self.assertIn("```mermaid", out)
        self.assertIn("graph TD", out)
        self.assertIn("```", out)

    def test_basic_three_node_two_edge_graph(self):
        from lib.graph_viz import render_mermaid
        nodes = [
            {"node_id": "paper:A", "kind": "paper", "label": "Paper A"},
            {"node_id": "paper:B", "kind": "paper", "label": "Paper B"},
            {"node_id": "concept:t", "kind": "concept", "label": "Transformers"},
        ]
        edges = [
            {"from_node": "paper:A", "to_node": "paper:B", "relation": "cites"},
            {"from_node": "paper:A", "to_node": "concept:t", "relation": "about"},
        ]
        out = render_mermaid(nodes, edges)
        self.assertIn("graph TD", out)
        self.assertIn("Paper A", out)
        self.assertIn("Transformers", out)
        self.assertIn("|cites|", out)
        self.assertIn("|about|", out)

    def test_kind_shapes_differ(self):
        from lib.graph_viz import render_mermaid
        nodes = [
            {"node_id": "paper:p", "kind": "paper", "label": "P"},
            {"node_id": "concept:c", "kind": "concept", "label": "C"},
            {"node_id": "author:a", "kind": "author", "label": "A"},
            {"node_id": "manuscript:m", "kind": "manuscript", "label": "M"},
        ]
        out = render_mermaid(nodes, [])
        # paper: rectangle
        self.assertIn('["P"]', out)
        # concept: circle
        self.assertIn('(("C"))', out)
        # author: asymmetric flag
        self.assertIn('>"A"]', out)
        # manuscript: hexagon
        self.assertIn('{{"M"}}', out)

    def test_special_chars_escaped(self):
        from lib.graph_viz import render_mermaid
        nodes = [
            {
                "node_id": "paper:weird",
                "kind": "paper",
                "label": 'Sm"art (Quotes) [and] |pipes| {a}',
            }
        ]
        out = render_mermaid(nodes, [])
        # raw special chars must NOT remain unescaped inside the label
        self.assertNotIn('"Sm"art', out)
        self.assertIn("&quot;", out)
        self.assertIn("&#40;", out)  # (
        self.assertIn("&#91;", out)  # [
        self.assertIn("&#124;", out)  # |

    def test_max_nodes_truncates(self):
        from lib.graph_viz import render_mermaid
        nodes = [
            {"node_id": f"paper:p{i}", "kind": "paper", "label": f"P{i}", "in_degree": i}
            for i in range(10)
        ]
        out = render_mermaid(nodes, [], max_nodes=3)
        # Highest-degree picks: P9, P8, P7
        self.assertIn('"P9"', out)
        self.assertIn('"P8"', out)
        self.assertIn('"P7"', out)
        self.assertNotIn('"P0"', out)
        self.assertNotIn('"P5"', out)

    def test_hide_labels_above_drops_text(self):
        from lib.graph_viz import render_mermaid
        nodes = [
            {"node_id": f"paper:p{i}", "kind": "paper", "label": f"VeryRealLabel{i}"}
            for i in range(5)
        ]
        out = render_mermaid(nodes, [], hide_labels_above=2)
        # 5 emitted > 2 → labels dropped
        self.assertNotIn("VeryRealLabel0", out)
        self.assertNotIn("VeryRealLabel4", out)

    def test_parallel_edges_collapse(self):
        from lib.graph_viz import render_mermaid
        nodes = [
            {"node_id": "paper:A", "kind": "paper", "label": "A"},
            {"node_id": "paper:B", "kind": "paper", "label": "B"},
        ]
        edges = [
            {"from_node": "paper:A", "to_node": "paper:B", "relation": "cites"},
            {"from_node": "paper:A", "to_node": "paper:B", "relation": "cites"},
            {"from_node": "paper:A", "to_node": "paper:B", "relation": "cites"},
        ]
        out = render_mermaid(nodes, edges)
        self.assertIn("×3", out)


class SubgraphTests(TestCase):
    def test_concept_subgraph_bfs(self):
        from lib.graph_viz import render_concept_subgraph
        nodes = [
            {"node_id": "concept:t", "kind": "concept", "label": "T"},
            {"node_id": "paper:A", "kind": "paper", "label": "A"},
            {"node_id": "paper:B", "kind": "paper", "label": "B"},
            {"node_id": "paper:Z", "kind": "paper", "label": "Z"},  # disconnected
        ]
        edges = [
            {"from_node": "paper:A", "to_node": "concept:t", "relation": "about"},
            {"from_node": "paper:B", "to_node": "concept:t", "relation": "about"},
        ]
        out = render_concept_subgraph(nodes, edges, "concept:t", depth=1)
        self.assertIn('"T"', out)
        self.assertIn('"A"', out)
        self.assertIn('"B"', out)
        # disconnected node Z must not be in the subgraph
        self.assertNotIn('"Z"', out)

    def test_paper_lineage_cites_direction(self):
        from lib.graph_viz import render_paper_lineage
        nodes = [
            {"node_id": "paper:root", "kind": "paper", "label": "Root"},
            {"node_id": "paper:cited1", "kind": "paper", "label": "Cited1"},
            {"node_id": "paper:cited2", "kind": "paper", "label": "Cited2"},
        ]
        edges = [
            {"from_node": "paper:root", "to_node": "paper:cited1", "relation": "cites"},
            {"from_node": "paper:cited1", "to_node": "paper:cited2", "relation": "cites"},
        ]
        out = render_paper_lineage(nodes, edges, "root", direction="cites", depth=2)
        self.assertIn("Root", out)
        self.assertIn("Cited1", out)
        self.assertIn("Cited2", out)


class CliTests(TestCase):
    def test_cli_empty_project(self):
        with isolated_cache():
            from lib.project import create
            pid = create("p_viz_empty", question="x")
            r = subprocess.run(
                [sys.executable, str(RENDER), "--project-id", pid],
                capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("```mermaid", r.stdout)
            self.assertIn("graph TD", r.stdout)

    def test_cli_with_seeded_graph(self):
        with isolated_cache():
            from lib.project import create
            pid = create("p_viz_seeded", question="x")
            _seed_simple(pid)
            r = subprocess.run(
                [sys.executable, str(RENDER), "--project-id", pid],
                capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Paper A", r.stdout)
            self.assertIn("Transformer", r.stdout)
            self.assertIn("|cites|", r.stdout)


if __name__ == "__main__":
    sys.exit(run_tests(RenderMermaidTests, SubgraphTests, CliTests))
