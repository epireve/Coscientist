"""v0.162 — funding-graph skill tests."""
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
    _REPO / ".claude" / "skills" / "funding-graph"
    / "scripts" / "funding.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("funding_v162", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["funding_v162"] = mod
    spec.loader.exec_module(mod)
    return mod


def _setup_project(name: str = "funding tests") -> str:
    from lib import project as project_mod
    return project_mod.create(name)


def _add_paper(pid: str, cid: str, title: str = "") -> str:
    from lib import graph as graph_mod
    return graph_mod.add_node(pid, "paper", cid, title or cid)


def _add_author(pid: str, ref: str, label: str) -> str:
    from lib import graph as graph_mod
    return graph_mod.add_node(pid, "author", ref, label)


def _add_funder(pid: str, ref: str, label: str) -> str:
    from lib import graph as graph_mod
    return graph_mod.add_node(pid, "funder", ref, label)


def _add_institution(pid: str, ref: str, label: str) -> str:
    from lib import graph as graph_mod
    return graph_mod.add_node(pid, "institution", ref, label)


def _edge(pid: str, frm: str, to: str, rel: str) -> None:
    from lib import graph as graph_mod
    graph_mod.add_edge(pid, frm, to, rel)


def _row_counts(pid: str) -> tuple[int, int]:
    from lib.cache import cache_root
    db = cache_root() / "projects" / pid / "project.db"
    con = sqlite3.connect(db)
    try:
        n = con.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0]
        e = con.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]
    finally:
        con.close()
    return n, e


def _scaffold(pid: str) -> dict:
    """Two funders, two institutions, three authors, four papers.

    P1: Alice (MIT), funded NIH
    P2: Alice (MIT), funded NIH
    P3: Bob (Stanford), funded NSF
    P4: Carol (MIT), funded NIH + NSF
    """
    nih = _add_funder(pid, "nih", "NIH")
    nsf = _add_funder(pid, "nsf", "NSF")
    mit = _add_institution(pid, "mit", "MIT")
    stan = _add_institution(pid, "stanford", "Stanford")
    alice = _add_author(pid, "alice", "Alice")
    bob = _add_author(pid, "bob", "Bob")
    carol = _add_author(pid, "carol", "Carol")
    p1 = _add_paper(pid, "p1", "Paper 1")
    p2 = _add_paper(pid, "p2", "Paper 2")
    p3 = _add_paper(pid, "p3", "Paper 3")
    p4 = _add_paper(pid, "p4", "Paper 4")

    _edge(pid, alice, mit, "affiliated-with")
    _edge(pid, bob, stan, "affiliated-with")
    _edge(pid, carol, mit, "affiliated-with")

    _edge(pid, p1, alice, "authored-by")
    _edge(pid, p2, alice, "authored-by")
    _edge(pid, p3, bob, "authored-by")
    _edge(pid, p4, carol, "authored-by")

    _edge(pid, p1, nih, "funded-by")
    _edge(pid, p2, nih, "funded-by")
    _edge(pid, p3, nsf, "funded-by")
    _edge(pid, p4, nih, "funded-by")
    _edge(pid, p4, nsf, "funded-by")

    return {
        "nih": nih, "nsf": nsf, "mit": mit, "stanford": stan,
        "alice": alice, "bob": bob, "carol": carol,
        "p1": p1, "p2": p2, "p3": p3, "p4": p4,
    }


class PapersByFunderTests(TestCase):
    def test_counts_correctly_sorted_desc(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            _scaffold(pid)
            res = mod.papers_by_funder(pid)
            self.assertTrue("error" not in res, msg=str(res))
            funders = res["funders"]
            # NIH funded p1,p2,p4 = 3 ; NSF funded p3,p4 = 2
            self.assertEqual(len(funders), 2)
            self.assertEqual(funders[0]["label"], "NIH")
            self.assertEqual(funders[0]["paper_count"], 3)
            self.assertEqual(funders[1]["label"], "NSF")
            self.assertEqual(funders[1]["paper_count"], 2)

    def test_empty_graph_returns_empty(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            res = mod.papers_by_funder(pid)
            self.assertTrue("error" not in res)
            self.assertEqual(res["funders"], [])


class PapersByInstitutionTests(TestCase):
    def test_counts_correctly_sorted_desc(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            _scaffold(pid)
            res = mod.papers_by_institution(pid)
            self.assertTrue("error" not in res, msg=str(res))
            insts = res["institutions"]
            # MIT: Alice (p1,p2) + Carol (p4) = 3
            # Stanford: Bob (p3) = 1
            self.assertEqual(len(insts), 2)
            self.assertEqual(insts[0]["label"], "MIT")
            self.assertEqual(insts[0]["paper_count"], 3)
            self.assertEqual(insts[1]["label"], "Stanford")
            self.assertEqual(insts[1]["paper_count"], 1)

    def test_concept_only_graph_returns_empty(self):
        """Graph with only concept nodes (no funders/institutions)."""
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            from lib import graph as graph_mod
            graph_mod.add_node(pid, "concept", "ml", "ML")
            graph_mod.add_node(pid, "concept", "nlp", "NLP")
            r1 = mod.papers_by_funder(pid)
            r2 = mod.papers_by_institution(pid)
            self.assertEqual(r1["funders"], [])
            self.assertEqual(r2["institutions"], [])


class ForFunderTests(TestCase):
    def test_returns_papers_and_authors(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            ids = _scaffold(pid)
            res = mod.for_funder(pid, ids["nih"])
            self.assertTrue("error" not in res, msg=str(res))
            self.assertEqual(res["paper_count"], 3)
            paper_nids = {p["paper_nid"] for p in res["papers"]}
            self.assertEqual(paper_nids, {ids["p1"], ids["p2"], ids["p4"]})
            author_nids = {a["author_nid"] for a in res["authors"]}
            # Alice (p1,p2) + Carol (p4) — Bob never NIH-funded
            self.assertEqual(author_nids, {ids["alice"], ids["carol"]})

    def test_missing_returns_error(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            res = mod.for_funder(pid, "funder:nonexistent")
            self.assertTrue("error" in res)


class ForInstitutionTests(TestCase):
    def test_returns_authors_and_papers(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            ids = _scaffold(pid)
            res = mod.for_institution(pid, ids["mit"])
            self.assertTrue("error" not in res, msg=str(res))
            author_nids = {a["author_nid"] for a in res["authors"]}
            self.assertEqual(author_nids, {ids["alice"], ids["carol"]})
            paper_nids = {p["paper_nid"] for p in res["papers"]}
            self.assertEqual(paper_nids, {ids["p1"], ids["p2"], ids["p4"]})

    def test_missing_returns_error(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            res = mod.for_institution(pid, "institution:nope")
            self.assertTrue("error" in res)


class DominantFundersTests(TestCase):
    def test_detects_single_funder_author(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            # Author with 5 papers all funded by one funder
            nih = _add_funder(pid, "nih", "NIH")
            a = _add_author(pid, "a", "Alpha")
            for i in range(5):
                p = _add_paper(pid, f"p{i}")
                _edge(pid, p, a, "authored-by")
                _edge(pid, p, nih, "funded-by")
            res = mod.dominant_funders(pid, min_papers=5, threshold=0.6)
            self.assertTrue("error" not in res)
            flagged = res["flagged"]
            self.assertEqual(len(flagged), 1)
            self.assertEqual(flagged[0]["author_nid"], a)
            self.assertEqual(flagged[0]["ratio"], 1.0)
            self.assertEqual(flagged[0]["dominant_funder_nid"], nih)

    def test_skips_below_min_papers(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            nih = _add_funder(pid, "nih", "NIH")
            a = _add_author(pid, "a", "Alpha")
            # only 3 papers — below default min_papers=5
            for i in range(3):
                p = _add_paper(pid, f"p{i}")
                _edge(pid, p, a, "authored-by")
                _edge(pid, p, nih, "funded-by")
            res = mod.dominant_funders(pid, min_papers=5, threshold=0.6)
            self.assertEqual(res["flagged"], [])

    def test_ignores_diverse_funding(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            nih = _add_funder(pid, "nih", "NIH")
            nsf = _add_funder(pid, "nsf", "NSF")
            erc = _add_funder(pid, "erc", "ERC")
            a = _add_author(pid, "a", "Alpha")
            funders = [nih, nih, nsf, nsf, erc]
            for i, f in enumerate(funders):
                p = _add_paper(pid, f"p{i}")
                _edge(pid, p, a, "authored-by")
                _edge(pid, p, f, "funded-by")
            # 5 papers, top funder = 2/5 = 0.4 < 0.6 threshold
            res = mod.dominant_funders(pid, min_papers=5, threshold=0.6)
            self.assertEqual(res["flagged"], [])


class FormatTests(TestCase):
    def test_json_vs_text_for_papers_by_funder(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            _scaffold(pid)
            payload = mod.papers_by_funder(pid)
            txt = mod._format_text(payload)
            self.assertIn("NIH", txt)
            self.assertIn("NSF", txt)
            self.assertTrue(isinstance(payload, dict))


class CLITests(TestCase):
    def test_cli_help_top_level(self):
        out = subprocess.run(
            [sys.executable, str(_SCRIPT), "--help"],
            capture_output=True, text=True,
        )
        self.assertEqual(out.returncode, 0)
        for sub in ("papers-by-funder", "papers-by-institution",
                    "for-funder", "for-institution", "dominant-funders"):
            self.assertIn(sub, out.stdout)

    def test_cli_help_subcommands(self):
        for sub in ("papers-by-funder", "papers-by-institution",
                    "for-funder", "for-institution", "dominant-funders"):
            out = subprocess.run(
                [sys.executable, str(_SCRIPT), sub, "--help"],
                capture_output=True, text=True,
            )
            self.assertEqual(out.returncode, 0,
                             msg=f"{sub} --help failed: {out.stderr}")
            self.assertIn("--project-id", out.stdout)


class ReadOnlyTests(TestCase):
    def test_no_writes_during_aggregation(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            ids = _scaffold(pid)
            n0, e0 = _row_counts(pid)
            mod.papers_by_funder(pid)
            mod.papers_by_institution(pid)
            mod.for_funder(pid, ids["nih"])
            mod.for_institution(pid, ids["mit"])
            mod.dominant_funders(pid, min_papers=1, threshold=0.5)
            n1, e1 = _row_counts(pid)
            self.assertEqual(n0, n1)
            self.assertEqual(e0, e1)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        PapersByFunderTests,
        PapersByInstitutionTests,
        ForFunderTests,
        ForInstitutionTests,
        DominantFundersTests,
        FormatTests,
        CLITests,
        ReadOnlyTests,
    ))
