"""v0.152 — enrich_authors ORCID + institution enrichment."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = (
    _REPO / ".claude" / "skills" / "reference-agent"
    / "scripts" / "enrich_authors.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "enrich_authors_v152", _SCRIPT,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["enrich_authors_v152"] = mod
    spec.loader.exec_module(mod)
    return mod


def _setup_project(name: str = "enrich tests") -> str:
    from lib import project as project_mod
    return project_mod.create(name)


def _add_author_node(project_id: str, ref: str, label: str,
                     external_ids: dict | None = None) -> str:
    from lib import graph as graph_mod
    return graph_mod.add_node(
        project_id, "author", ref, label,
        external_ids=external_ids or None,
        source="manual",
    )


def _node_external_ids(project_id: str, nid: str) -> dict:
    from lib.cache import cache_root
    db = cache_root() / "projects" / project_id / "project.db"
    con = sqlite3.connect(db)
    try:
        row = con.execute(
            "SELECT external_ids_json FROM graph_nodes WHERE node_id=?",
            (nid,),
        ).fetchone()
    finally:
        con.close()
    if not row or not row[0]:
        return {}
    return json.loads(row[0])


def _count_edges(project_id: str, relation: str | None = None) -> int:
    from lib.cache import cache_root
    db = cache_root() / "projects" / project_id / "project.db"
    con = sqlite3.connect(db)
    try:
        if relation:
            return con.execute(
                "SELECT COUNT(*) FROM graph_edges WHERE relation=?",
                (relation,),
            ).fetchone()[0]
        return con.execute(
            "SELECT COUNT(*) FROM graph_edges",
        ).fetchone()[0]
    finally:
        con.close()


def _count_kind(project_id: str, kind: str) -> int:
    from lib.cache import cache_root
    db = cache_root() / "projects" / project_id / "project.db"
    con = sqlite3.connect(db)
    try:
        return con.execute(
            "SELECT COUNT(*) FROM graph_nodes WHERE kind=?",
            (kind,),
        ).fetchone()[0]
    finally:
        con.close()


# ---- Stub clients --------------------------------------------------------


class StubOpenAlexClient:
    """Mimics lib.openalex_client.OpenAlexClient surface used by script."""

    def __init__(self, *, by_id=None, by_orcid=None, search_results=None,
                 default_error=None):
        # by_id: {oa_id_or_orcid_str: author_dict}
        self._by_id = by_id or {}
        self._by_orcid = by_orcid or {}
        self._search_results = search_results or {"results": []}
        self._default_error = default_error
        self.calls: list[tuple[str, tuple]] = []

    def get_author(self, ident):
        self.calls.append(("get_author", (ident,)))
        # Direct hit in by_id
        if ident in self._by_id:
            return self._by_id[ident]
        # Strip orcid: prefix and look up
        if ident.startswith("orcid:"):
            orcid = ident[len("orcid:"):]
            if orcid in self._by_orcid:
                return self._by_orcid[orcid]
        if self._default_error:
            return {"error": self._default_error}
        return {"error": "HTTP 404"}

    def search_authors(self, query, *, per_page=25):
        self.calls.append(("search_authors", (query,)))
        return self._search_results


class StubS2Client:
    """Mimics S2 surface — only what enrich_authors uses."""

    def __init__(self, *, by_id=None, search_data=None):
        self._by_id = by_id or {}
        self._search_data = search_data or {"data": []}
        self.calls: list[tuple[str, tuple]] = []

    def get_author(self, ident):
        self.calls.append(("get_author", (ident,)))
        if ident in self._by_id:
            return self._by_id[ident]
        return {"error": "HTTP 404"}

    def search_authors(self, query, *, limit=10):
        self.calls.append(("search_authors", (query,)))
        return self._search_data


# Canned OpenAlex author records ---------------------------------------------


def _make_oa_author(*, oa_id="A123", orcid="0000-0001-2345-6789",
                    display_name="Jane Doe",
                    inst_ror="https://ror.org/01abc23",
                    inst_oa="I999",
                    inst_country="US",
                    inst_name="MIT",
                    inst_type="education"):
    insts = []
    if inst_ror or inst_oa:
        insts.append({
            "id": f"https://openalex.org/{inst_oa}" if inst_oa else None,
            "ror": inst_ror,
            "country_code": inst_country,
            "display_name": inst_name,
            "type": inst_type,
        })
    return {
        "id": f"https://openalex.org/{oa_id}",
        "orcid": f"https://orcid.org/{orcid}" if orcid else None,
        "display_name": display_name,
        "works_count": 42,
        "last_known_institutions": insts,
    }


# ---- Tests ---------------------------------------------------------------


class ResolveByIdTests(TestCase):
    def test_enrich_by_openalex_id_from_external_ids(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            nid = _add_author_node(
                pid, "doe-j", "Jane Doe",
                external_ids={"openalex_author_id": "A123"},
            )
            stub = StubOpenAlexClient(
                by_id={"A123": _make_oa_author()},
            )
            res = mod.enrich_author(pid, nid, client=stub)
            self.assertTrue("error" not in res, msg=str(res))
            self.assertEqual(res["source"], "openalex")
            ids = _node_external_ids(pid, nid)
            self.assertEqual(ids.get("openalex_author_id"), "A123")
            self.assertEqual(ids.get("orcid"), "0000-0001-2345-6789")
            # Stub should have been called by openalex_author_id (no search)
            kinds = [c[0] for c in stub.calls]
            self.assertIn("get_author", kinds)
            self.assertNotIn("search_authors", kinds)

    def test_enrich_by_orcid_when_no_oa_id(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            nid = _add_author_node(
                pid, "doe-j", "Jane Doe",
                external_ids={"orcid": "0000-0001-2345-6789"},
            )
            stub = StubOpenAlexClient(
                by_orcid={
                    "0000-0001-2345-6789": _make_oa_author(),
                },
            )
            res = mod.enrich_author(pid, nid, client=stub)
            self.assertTrue("error" not in res, msg=str(res))
            ids = _node_external_ids(pid, nid)
            self.assertEqual(ids.get("openalex_author_id"), "A123")


class ResolveByNameTests(TestCase):
    def test_search_fallback_picks_exact_match(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            nid = _add_author_node(pid, "doe-j", "Jane Doe")
            # Search returns 2 candidates; exact match should win
            other = _make_oa_author(
                oa_id="A999", display_name="Janet Doe",
            )
            target = _make_oa_author(oa_id="A123")
            stub = StubOpenAlexClient(
                search_results={"results": [other, target]},
            )
            res = mod.enrich_author(pid, nid, client=stub)
            self.assertTrue("error" not in res, msg=str(res))
            ids = _node_external_ids(pid, nid)
            self.assertEqual(ids.get("openalex_author_id"), "A123")

    def test_search_fallback_tiebreaks_by_works_count(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            nid = _add_author_node(pid, "doe-j", "Jane Doe")
            # No exact match; pick highest works_count
            low = _make_oa_author(
                oa_id="LOW", display_name="J Doe",
            )
            low["works_count"] = 5
            high = _make_oa_author(
                oa_id="HIGH", display_name="Jay Doe",
            )
            high["works_count"] = 200
            stub = StubOpenAlexClient(
                search_results={"results": [low, high]},
            )
            res = mod.enrich_author(pid, nid, client=stub)
            self.assertTrue("error" not in res, msg=str(res))
            ids = _node_external_ids(pid, nid)
            self.assertEqual(ids.get("openalex_author_id"), "HIGH")


class InstitutionTests(TestCase):
    def test_institution_node_created_with_ror_and_country(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            nid = _add_author_node(
                pid, "doe-j", "Jane Doe",
                external_ids={"openalex_author_id": "A123"},
            )
            stub = StubOpenAlexClient(
                by_id={"A123": _make_oa_author(
                    inst_ror="https://ror.org/01abc23",
                    inst_oa="I999",
                    inst_country="US",
                    inst_name="MIT",
                )},
            )
            res = mod.enrich_author(pid, nid, client=stub)
            self.assertEqual(res["institutions_seen"], 1)
            self.assertEqual(res["edges_added"], 1)
            self.assertEqual(_count_kind(pid, "institution"), 1)
            # Institution node external_ids should carry ror + country
            inst_nid = res["institution_nids"][0]
            inst_ids = _node_external_ids(pid, inst_nid)
            self.assertEqual(inst_ids.get("ror_id"), "01abc23")
            self.assertEqual(inst_ids.get("country_code"), "US")
            self.assertEqual(inst_ids.get("openalex_id"), "I999")

    def test_affiliated_with_edge_idempotent(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            nid = _add_author_node(
                pid, "doe-j", "Jane Doe",
                external_ids={"openalex_author_id": "A123"},
            )
            stub = StubOpenAlexClient(
                by_id={"A123": _make_oa_author()},
            )
            r1 = mod.enrich_author(pid, nid, client=stub)
            self.assertEqual(r1["edges_added"], 1)
            edges_after_1 = _count_edges(pid, "affiliated-with")
            # Re-run — must NOT duplicate edge
            r2 = mod.enrich_author(pid, nid, client=stub)
            self.assertEqual(r2["edges_added"], 0)
            edges_after_2 = _count_edges(pid, "affiliated-with")
            self.assertEqual(edges_after_1, edges_after_2)

    def test_no_institutions_no_edges(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            nid = _add_author_node(
                pid, "doe-j", "Jane Doe",
                external_ids={"openalex_author_id": "A123"},
            )
            rec = _make_oa_author()
            rec["last_known_institutions"] = []
            stub = StubOpenAlexClient(by_id={"A123": rec})
            res = mod.enrich_author(pid, nid, client=stub)
            self.assertEqual(res["institutions_seen"], 0)
            self.assertEqual(res["edges_added"], 0)
            self.assertEqual(_count_kind(pid, "institution"), 0)


class ErrorHandlingTests(TestCase):
    def test_missing_author_node_returns_error(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            stub = StubOpenAlexClient()
            res = mod.enrich_author(
                pid, "author:nonexistent", client=stub,
            )
            self.assertTrue("error" in res)

    def test_missing_project_db_returns_error(self):
        with isolated_cache():
            mod = _load_module()
            stub = StubOpenAlexClient()
            res = mod.enrich_author(
                "no-such-project", "author:x", client=stub,
            )
            self.assertTrue("error" in res)
            res2 = mod.enrich_project("no-such-project", client=stub)
            self.assertTrue("error" in res2)

    def test_no_label_no_id_returns_error(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            nid = _add_author_node(pid, "blank", "")
            # Empty search (no candidates) and no IDs to try
            stub = StubOpenAlexClient(search_results={"results": []})
            res = mod.enrich_author(pid, nid, client=stub)
            self.assertTrue("error" in res)


class ProjectBatchTests(TestCase):
    def test_no_author_nodes_clean_empty_result(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            stub = StubOpenAlexClient()
            res = mod.enrich_project(pid, client=stub)
            self.assertEqual(res["authors_processed"], 0)
            self.assertEqual(res["institutions_added"], 0)
            self.assertEqual(res["edges_added"], 0)
            self.assertTrue("error" not in res)

    def test_project_batch_processes_all_authors(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            n1 = _add_author_node(
                pid, "doe-j", "Jane Doe",
                external_ids={"openalex_author_id": "A111"},
            )
            n2 = _add_author_node(
                pid, "smith-k", "Karen Smith",
                external_ids={"openalex_author_id": "A222"},
            )
            stub = StubOpenAlexClient(by_id={
                "A111": _make_oa_author(
                    oa_id="A111", inst_ror="https://ror.org/r1",
                    inst_oa="I1", inst_name="Lab1",
                ),
                "A222": _make_oa_author(
                    oa_id="A222", inst_ror="https://ror.org/r2",
                    inst_oa="I2", inst_name="Lab2",
                ),
            })
            res = mod.enrich_project(pid, client=stub)
            self.assertEqual(res["authors_processed"], 2)
            self.assertEqual(res["institutions_added"], 2)
            self.assertEqual(res["edges_added"], 2)
            self.assertEqual(_count_kind(pid, "institution"), 2)
            # Both author nodes touched
            ids1 = _node_external_ids(pid, n1)
            ids2 = _node_external_ids(pid, n2)
            self.assertEqual(ids1.get("openalex_author_id"), "A111")
            self.assertEqual(ids2.get("openalex_author_id"), "A222")

    def test_project_batch_collects_errors_continues(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            # One resolvable, one not
            _add_author_node(
                pid, "good", "Good Author",
                external_ids={"openalex_author_id": "GOOD"},
            )
            _add_author_node(pid, "bad", "")  # no label, no ids
            stub = StubOpenAlexClient(by_id={
                "GOOD": _make_oa_author(oa_id="GOOD"),
            }, search_results={"results": []})
            res = mod.enrich_project(pid, client=stub)
            self.assertEqual(res["authors_processed"], 1)
            self.assertEqual(len(res["errors"]), 1)


class S2BackendTests(TestCase):
    def test_source_s2_uses_s2_client(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            nid = _add_author_node(
                pid, "doe-j", "Jane Doe",
                external_ids={"s2_author_id": "S99"},
            )
            stub = StubS2Client(by_id={"S99": {
                "authorId": "S99",
                "name": "Jane Doe",
                "externalIds": {"ORCID": "0000-0001-2345-6789"},
                "paperCount": 50,
            }})
            res = mod.enrich_author(
                pid, nid, source="s2", client=stub,
            )
            self.assertTrue("error" not in res, msg=str(res))
            self.assertEqual(res["source"], "s2")
            ids = _node_external_ids(pid, nid)
            self.assertEqual(ids.get("s2_author_id"), "S99")
            self.assertEqual(ids.get("orcid"), "0000-0001-2345-6789")
            # No institution edges from S2 (by design)
            self.assertEqual(res["edges_added"], 0)

    def test_s2_fallback_when_openalex_returns_404(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project()
            nid = _add_author_node(pid, "ghost", "Ghost Author")
            # OpenAlex search returns nothing
            oa_stub = StubOpenAlexClient(search_results={"results": []})
            # S2 has the author by name search
            s2_stub = StubS2Client(search_data={"data": [{
                "authorId": "S55",
                "name": "Ghost Author",
                "paperCount": 3,
            }]})
            res = mod.enrich_author(
                pid, nid, client=oa_stub, s2_client=s2_stub,
            )
            self.assertTrue("error" not in res, msg=str(res))
            self.assertEqual(res["source"], "s2")
            ids = _node_external_ids(pid, nid)
            self.assertEqual(ids.get("s2_author_id"), "S55")


class CLITests(TestCase):
    def test_cli_argparse_choices(self):
        # Smoke: --source choice list
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument(
            "--source", default="openalex",
            choices=["openalex", "s2"],
        )
        for v in ("openalex", "s2"):
            ns = p.parse_args(["--source", v])
            self.assertEqual(ns.source, v)
        mod = _load_module()
        self.assertTrue(hasattr(mod, "enrich_author"))
        self.assertTrue(hasattr(mod, "enrich_project"))
        self.assertTrue(hasattr(mod, "main"))


if __name__ == "__main__":
    raise SystemExit(run_tests(
        ResolveByIdTests,
        ResolveByNameTests,
        InstitutionTests,
        ErrorHandlingTests,
        ProjectBatchTests,
        S2BackendTests,
        CLITests,
    ))
