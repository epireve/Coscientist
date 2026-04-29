"""v0.161 — coauthor-network skill tests."""
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
    _REPO / ".claude" / "skills" / "coauthor-network"
    / "scripts" / "coauthor.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "coauthor_v161", _SCRIPT,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["coauthor_v161"] = mod
    spec.loader.exec_module(mod)
    return mod


def _setup_project(name: str = "coauthor tests") -> str:
    from lib import project as project_mod
    return project_mod.create(name)


def _add_paper(pid: str, cid: str, title: str = "", year: int | None = None):
    """Insert paper node + write metadata.json with year if given."""
    from lib import graph as graph_mod
    from lib.cache import paper_dir
    nid = graph_mod.add_node(pid, "paper", cid, title or cid)
    if year is not None:
        d = paper_dir(cid)
        (d / "metadata.json").write_text(json.dumps({"year": year}))
    return nid


def _add_author(pid: str, ref: str, label: str) -> str:
    from lib import graph as graph_mod
    return graph_mod.add_node(pid, "author", ref, label)


def _add_authored_by(pid: str, paper_nid: str, author_nid: str) -> None:
    from lib import graph as graph_mod
    graph_mod.add_edge(pid, paper_nid, author_nid, "authored-by")


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


def _scaffold_basic(pid: str) -> dict:
    """Three authors, three papers:
        P1: Alice + Bob (2020)
        P2: Alice + Bob (2021)
        P3: Alice + Carol (2022)
    => Alice's coauthors: Bob (2 papers, 2020-2021), Carol (1, 2022)
    """
    a_alice = _add_author(pid, "alice", "Alice")
    a_bob = _add_author(pid, "bob", "Bob")
    a_carol = _add_author(pid, "carol", "Carol")
    p1 = _add_paper(pid, "p1", "Paper 1", year=2020)
    p2 = _add_paper(pid, "p2", "Paper 2", year=2021)
    p3 = _add_paper(pid, "p3", "Paper 3", year=2022)
    for p, authors in (
        (p1, [a_alice, a_bob]),
        (p2, [a_alice, a_bob]),
        (p3, [a_alice, a_carol]),
    ):
        for a in authors:
            _add_authored_by(pid, p, a)
    return {
        "alice": a_alice, "bob": a_bob, "carol": a_carol,
        "p1": p1, "p2": p2, "p3": p3,
    }


# ---- Tests ---------------------------------------------------------------


class ForAuthorTests(TestCase):
    def test_returns_coauthors_with_correct_shared_count(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            ids = _scaffold_basic(pid)
            res = mod.for_author(pid, ids["alice"])
            self.assertTrue("error" not in res, msg=str(res))
            self.assertEqual(res["paper_count"], 3)
            cs = res["coauthors"]
            self.assertEqual(len(cs), 2)
            # Bob first (2 shared)
            self.assertEqual(cs[0]["author_nid"], ids["bob"])
            self.assertEqual(cs[0]["shared_papers"], 2)
            # Carol second (1 shared)
            self.assertEqual(cs[1]["author_nid"], ids["carol"])
            self.assertEqual(cs[1]["shared_papers"], 1)

    def test_solo_paper_zero_coauthors(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            a = _add_author(pid, "solo", "Solo Author")
            p = _add_paper(pid, "solo-p", year=2021)
            _add_authored_by(pid, p, a)
            res = mod.for_author(pid, a)
            self.assertTrue("error" not in res, msg=str(res))
            self.assertEqual(res["paper_count"], 1)
            self.assertEqual(res["coauthors"], [])

    def test_missing_author_returns_error(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            res = mod.for_author(pid, "author:nonexistent")
            self.assertTrue("error" in res)

    def test_year_range_computed(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            ids = _scaffold_basic(pid)
            res = mod.for_author(pid, ids["alice"])
            cs = {c["author_nid"]: c for c in res["coauthors"]}
            self.assertEqual(cs[ids["bob"]]["year_min"], 2020)
            self.assertEqual(cs[ids["bob"]]["year_max"], 2021)
            self.assertEqual(cs[ids["carol"]]["year_min"], 2022)
            self.assertEqual(cs[ids["carol"]]["year_max"], 2022)

    def test_sort_order_shared_desc_then_label_asc(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            # Alice + 3 coauthors with varying shared counts
            a = _add_author(pid, "alice", "Alice")
            zoe = _add_author(pid, "zoe", "Zoe")
            adam = _add_author(pid, "adam", "Adam")
            bob = _add_author(pid, "bob", "Bob")
            # Zoe shares 1 paper, Adam 1, Bob 2
            p1 = _add_paper(pid, "p1")
            p2 = _add_paper(pid, "p2")
            p3 = _add_paper(pid, "p3")
            _add_authored_by(pid, p1, a)
            _add_authored_by(pid, p1, bob)
            _add_authored_by(pid, p2, a)
            _add_authored_by(pid, p2, bob)
            _add_authored_by(pid, p2, zoe)
            _add_authored_by(pid, p3, a)
            _add_authored_by(pid, p3, adam)
            res = mod.for_author(pid, a)
            cs = res["coauthors"]
            self.assertEqual(cs[0]["label"], "Bob")  # 2 shared
            # Adam vs Zoe both 1 — Adam first by label asc
            self.assertEqual(cs[1]["label"], "Adam")
            self.assertEqual(cs[2]["label"], "Zoe")


class ForPaperTests(TestCase):
    def test_returns_coauthor_map(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            ids = _scaffold_basic(pid)
            res = mod.for_paper(pid, "p1")
            self.assertTrue("error" not in res, msg=str(res))
            self.assertEqual(set(res["authors"]),
                             {ids["alice"], ids["bob"]})
            self.assertIn(ids["alice"], res["by_author"])
            self.assertIn(ids["bob"], res["by_author"])
            # Alice's coauthors include Bob and Carol (1-hop expand)
            alice_coauthors = res["by_author"][ids["alice"]]["coauthors"]
            nids = {c["author_nid"] for c in alice_coauthors}
            self.assertIn(ids["bob"], nids)
            self.assertIn(ids["carol"], nids)

    def test_missing_paper_returns_error(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            res = mod.for_paper(pid, "no-such-paper")
            self.assertTrue("error" in res)


class CliquesTests(TestCase):
    def test_detects_3_author_triangle(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            # Triangle: A,B,C all share min 2 papers pairwise
            a = _add_author(pid, "a", "Aname")
            b = _add_author(pid, "b", "Bname")
            c = _add_author(pid, "c", "Cname")
            # Two papers, all 3 authors on each
            for cid in ("p1", "p2"):
                p = _add_paper(pid, cid)
                _add_authored_by(pid, p, a)
                _add_authored_by(pid, p, b)
                _add_authored_by(pid, p, c)
            res = mod.cliques(pid, min_shared=2)
            self.assertTrue("error" not in res)
            tris = res["triangles"]
            self.assertEqual(len(tris), 1)
            self.assertEqual(set(tris[0]["authors"]), {a, b, c})
            self.assertEqual(tris[0]["shared_papers"], 2)

    def test_skips_pairs_below_threshold(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            a = _add_author(pid, "a", "Aname")
            b = _add_author(pid, "b", "Bname")
            # Only 1 shared paper
            p = _add_paper(pid, "p1")
            _add_authored_by(pid, p, a)
            _add_authored_by(pid, p, b)
            res = mod.cliques(pid, min_shared=2)
            self.assertEqual(res["pairs"], [])
            self.assertEqual(res["triangles"], [])

    def test_empty_graph_returns_empty(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            res = mod.cliques(pid, min_shared=2)
            self.assertTrue("error" not in res)
            self.assertEqual(res["pairs"], [])
            self.assertEqual(res["triangles"], [])


class FormatTests(TestCase):
    def test_json_vs_text_output_for_author(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            ids = _scaffold_basic(pid)
            payload = mod.for_author(pid, ids["alice"])
            txt = mod._format_text(payload)
            self.assertIn("Bob", txt)
            self.assertIn("Carol", txt)
            # JSON is just the dict
            self.assertTrue(isinstance(payload, dict))


class CLITests(TestCase):
    def test_cli_help_top_level(self):
        out = subprocess.run(
            [sys.executable, str(_SCRIPT), "--help"],
            capture_output=True, text=True,
        )
        self.assertEqual(out.returncode, 0)
        self.assertIn("for-author", out.stdout)
        self.assertIn("for-paper", out.stdout)
        self.assertIn("cliques", out.stdout)

    def test_cli_help_subcommands(self):
        for sub in ("for-author", "for-paper", "cliques"):
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
            _scaffold_basic(pid)
            n_before, e_before = _row_counts(pid)
            ids_before = mod.for_author(pid, "author:alice")
            self.assertTrue("error" not in ids_before)
            mod.for_paper(pid, "p1")
            mod.cliques(pid, min_shared=2)
            n_after, e_after = _row_counts(pid)
            self.assertEqual(n_before, n_after)
            self.assertEqual(e_before, e_after)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        ForAuthorTests,
        ForPaperTests,
        CliquesTests,
        FormatTests,
        CLITests,
        ReadOnlyTests,
    ))
