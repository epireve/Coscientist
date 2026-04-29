"""v0.180 — coauthor-network cliques-louvain (Louvain Phase-1 modularity).

Pure stdlib modularity-optimization community detection.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = (
    _REPO / ".claude" / "skills" / "coauthor-network"
    / "scripts" / "coauthor.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "coauthor_v180", _SCRIPT,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["coauthor_v180"] = mod
    spec.loader.exec_module(mod)
    return mod


def _seed_papers(papers: list[tuple[str, list[str]]]) -> str:
    """papers: list of (paper_id, [author_ids])."""
    from lib import graph, project
    pid = project.create("louvain-test")
    for cid, authors in papers:
        pnid = graph.add_node(pid, "paper", cid, cid)
        for a in authors:
            anid = graph.add_node(pid, "author", a, a)
            graph.add_edge(pid, pnid, anid, "authored-by")
    return pid


class V0180LouvainCliquesTests(TestCase):

    def test_single_4author_triangle_one_community(self):
        with isolated_cache():
            mod = _load_module()
            # 4 authors collaborating on shared papers — one community.
            pid = _seed_papers([
                ("p1", ["a", "b", "c", "d"]),
                ("p2", ["a", "b", "c"]),
                ("p3", ["a", "c", "d"]),
                ("p4", ["b", "c", "d"]),
            ])
            r = mod.cliques_louvain(pid)
            self.assertNotIn("error", r)
            # All 4 authors in same community.
            self.assertEqual(len(r["communities"]), 1)
            self.assertEqual(r["communities"][0]["size"], 4)

    def test_two_disjoint_triangles(self):
        with isolated_cache():
            mod = _load_module()
            pid = _seed_papers([
                ("p1", ["a", "b", "c"]),
                ("p2", ["a", "b", "c"]),
                ("p3", ["x", "y", "z"]),
                ("p4", ["x", "y", "z"]),
            ])
            r = mod.cliques_louvain(pid)
            self.assertEqual(len(r["communities"]), 2)
            sizes = sorted(c["size"] for c in r["communities"])
            self.assertEqual(sizes, [3, 3])

    def test_empty_graph(self):
        with isolated_cache():
            mod = _load_module()
            from lib import project
            pid = project.create("louvain-empty")
            r = mod.cliques_louvain(pid)
            self.assertEqual(r["communities"], [])

    def test_all_disconnected_each_own_community(self):
        with isolated_cache():
            mod = _load_module()
            # Every author on own paper, no overlaps.
            pid = _seed_papers([
                ("p1", ["a"]),
                ("p2", ["b"]),
                ("p3", ["c"]),
            ])
            r = mod.cliques_louvain(pid)
            self.assertEqual(len(r["communities"]), 3)
            for c in r["communities"]:
                self.assertEqual(c["size"], 1)

    def test_modularity_positive_for_clusters(self):
        with isolated_cache():
            mod = _load_module()
            pid = _seed_papers([
                ("p1", ["a", "b", "c"]),
                ("p2", ["a", "b", "c"]),
                ("p3", ["x", "y", "z"]),
                ("p4", ["x", "y", "z"]),
            ])
            r = mod.cliques_louvain(pid)
            self.assertGreater(r["modularity"], 0)

    def test_sorted_by_size_desc(self):
        with isolated_cache():
            mod = _load_module()
            # 4-author cluster + 2-author pair.
            pid = _seed_papers([
                ("p1", ["a", "b", "c", "d"]),
                ("p2", ["a", "b", "c", "d"]),
                ("p3", ["x", "y"]),
                ("p4", ["x", "y"]),
            ])
            r = mod.cliques_louvain(pid)
            sizes = [c["size"] for c in r["communities"]]
            self.assertEqual(sizes, sorted(sizes, reverse=True))

    def test_cli_format_json_text(self):
        with isolated_cache() as cache:
            pid = _seed_papers([
                ("p1", ["a", "b", "c"]),
                ("p2", ["a", "b", "c"]),
            ])
            env = {**os.environ, "COSCIENTIST_CACHE_DIR": str(cache)}
            rj = subprocess.run(
                [sys.executable, str(_SCRIPT), "cliques-louvain",
                 "--project-id", pid, "--format", "json"],
                capture_output=True, text=True, env=env, timeout=30,
            )
            self.assertEqual(rj.returncode, 0, rj.stderr)
            parsed = json.loads(rj.stdout)
            self.assertIn("communities", parsed)
            rt = subprocess.run(
                [sys.executable, str(_SCRIPT), "cliques-louvain",
                 "--project-id", pid, "--format", "text"],
                capture_output=True, text=True, env=env, timeout=30,
            )
            self.assertEqual(rt.returncode, 0, rt.stderr)
            self.assertIn("Louvain", rt.stdout)


if __name__ == "__main__":
    sys.exit(run_tests(V0180LouvainCliquesTests))
