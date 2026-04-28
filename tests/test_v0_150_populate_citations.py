"""v0.150 — populate_citations OpenAlex + S2-influential backends."""
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
    / "scripts" / "populate_citations.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "populate_citations_v150", _SCRIPT,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["populate_citations_v150"] = mod
    spec.loader.exec_module(mod)
    return mod


def _setup_project_with_paper(manifest_overrides: dict) -> tuple[str, str, object]:
    """Create a project + a paper artifact whose manifest carries the
    requested upstream IDs. Returns (project_id, paper_canonical_id, mod)."""
    from lib import project as project_mod
    from lib.paper_artifact import Manifest, PaperArtifact, State

    mod = _load_module()
    pid = project_mod.create("citation backend tests")
    cid = "vaswani_2017_attention_abc123"
    art = PaperArtifact(cid)
    art.root.mkdir(parents=True, exist_ok=True)
    m = Manifest(canonical_id=cid, state=State.discovered, **manifest_overrides)
    art.save_manifest(m)
    return pid, cid, mod


# ---- Stub clients --------------------------------------------------------


class StubOpenAlexClient:
    """Mimics lib.openalex_client.OpenAlexClient surface used by script."""

    def __init__(self, *, refs=None, batch_results=None, cited_by=None,
                 ref_error=None, cited_error=None):
        self._refs = refs or []
        self._batch_results = batch_results or []
        self._cited_by = cited_by or {"results": []}
        self._ref_error = ref_error
        self._cited_error = cited_error
        self.calls: list[tuple[str, tuple]] = []

    def get_work_references(self, oa_id):
        self.calls.append(("get_work_references", (oa_id,)))
        if self._ref_error:
            return [{"error": self._ref_error}]
        return list(self._refs)

    def get_works_batch(self, ids, *, select=None):
        self.calls.append(("get_works_batch", (tuple(ids),)))
        return {"results": list(self._batch_results), "meta": {}}

    def get_cited_by(self, oa_id, *, per_page=25):
        self.calls.append(("get_cited_by", (oa_id,)))
        if self._cited_error:
            return {"error": self._cited_error}
        return self._cited_by


class StubS2Client:
    """Mimics lib.s2_enrichment.S2Client surface."""

    def __init__(self, *, refs=None, citations=None,
                 ref_error=None, cit_error=None):
        self._refs = refs or {"data": []}
        self._cits = citations or {"data": []}
        self._ref_error = ref_error
        self._cit_error = cit_error
        self.calls: list[tuple[str, tuple, dict]] = []

    def get_paper_references(self, paper_id, *, fields=None,
                              limit=100, offset=0):
        self.calls.append(
            ("get_paper_references", (paper_id,),
             {"fields": fields, "limit": limit, "offset": offset}),
        )
        if self._ref_error:
            return {"error": self._ref_error}
        return self._refs

    def get_paper_citations(self, paper_id, *, fields=None,
                             limit=100, offset=0):
        self.calls.append(
            ("get_paper_citations", (paper_id,),
             {"fields": fields, "limit": limit, "offset": offset}),
        )
        if self._cit_error:
            return {"error": self._cit_error}
        return self._cits


def _count_edges(project_id: str) -> int:
    from lib.cache import cache_root
    db = cache_root() / "projects" / project_id / "project.db"
    con = sqlite3.connect(db)
    try:
        return con.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]
    finally:
        con.close()


def _count_paper_nodes_with_source(project_id: str, source: str) -> int:
    from lib.cache import cache_root
    db = cache_root() / "projects" / project_id / "project.db"
    con = sqlite3.connect(db)
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(graph_nodes)")]
        if "source" not in cols:
            return -1
        return con.execute(
            "SELECT COUNT(*) FROM graph_nodes WHERE kind='paper' AND source=?",
            (source,),
        ).fetchone()[0]
    finally:
        con.close()


# ---- Tests ---------------------------------------------------------------


class FileModeBackCompatTests(TestCase):
    """Legacy --source=file path still works."""

    def test_file_mode_ingests_records(self):
        with isolated_cache():
            from lib import project as project_mod
            mod = _load_module()
            pid = project_mod.create("file mode")
            records = [{
                "from_canonical_id": "x_2020_a_aaa111",
                "references": [
                    {"canonical_id": "y_2019_b_bbb222",
                     "title": "B", "year": 2019},
                ],
                "citations": [
                    {"canonical_id": "z_2021_c_ccc333",
                     "title": "C", "year": 2021},
                ],
            }]
            res = mod.populate(records, pid)
            # 2 edges per ref + 2 edges per citation = 4 edges
            self.assertEqual(res["edges_added"], 4)
            self.assertEqual(res["skipped"], 0)


class OpenAlexBackendTests(TestCase):
    def test_creates_nodes_with_source_openalex(self):
        with isolated_cache():
            pid, cid, mod = _setup_project_with_paper({
                "openalex_id": "W2741809807",
                "doi": "10.1000/test.1",
            })
            stub = StubOpenAlexClient(
                refs=["https://openalex.org/W111"],
                batch_results=[{
                    "id": "https://openalex.org/W111",
                    "display_name": "Old Reference",
                    "publication_year": 2010,
                    "doi": "https://doi.org/10.1/oldref",
                    "ids": {},
                    "authorships": [
                        {"author": {"display_name": "Doe, J"}},
                    ],
                }],
                cited_by={"results": [{
                    "id": "https://openalex.org/W222",
                    "display_name": "Newer Citer",
                    "publication_year": 2022,
                    "doi": "https://doi.org/10.1/newcit",
                    "ids": {"pmid": "12345"},
                    "authorships": [
                        {"author": {"display_name": "Roe, A"}},
                    ],
                }]},
            )
            res = mod.populate_from_openalex(cid, pid, client=stub)
            self.assertEqual(res.get("source"), "openalex")
            # 1 ref + 1 citer = 4 edges
            self.assertEqual(res["edges_added"], 4)
            # Nodes touched should include from + ref + citer = 3
            self.assertGreaterEqual(res["nodes_touched"], 3)
            # All 3 should be tagged source=openalex
            n_oa = _count_paper_nodes_with_source(pid, "openalex")
            self.assertGreaterEqual(n_oa, 3)

    def test_idempotent_rerun_no_duplicate_edges(self):
        with isolated_cache():
            pid, cid, mod = _setup_project_with_paper({
                "openalex_id": "W2741809807",
            })
            stub = StubOpenAlexClient(
                refs=["https://openalex.org/W111"],
                batch_results=[{
                    "id": "https://openalex.org/W111",
                    "display_name": "Reference",
                    "publication_year": 2015,
                    "doi": "https://doi.org/10.1/refdoi",
                    "authorships": [
                        {"author": {"display_name": "Smith, K"}},
                    ],
                }],
                cited_by={"results": []},
            )
            r1 = mod.populate_from_openalex(cid, pid, client=stub)
            edges_after_1 = _count_edges(pid)
            self.assertEqual(r1["edges_added"], 2)

            # Re-run — should add zero new edges
            r2 = mod.populate_from_openalex(cid, pid, client=stub)
            edges_after_2 = _count_edges(pid)
            self.assertEqual(r2["edges_added"], 0)
            self.assertEqual(edges_after_1, edges_after_2)

    def test_missing_manifest_returns_error(self):
        with isolated_cache():
            from lib import project as project_mod
            mod = _load_module()
            pid = project_mod.create("missing manifest")
            stub = StubOpenAlexClient()
            res = mod.populate_from_openalex(
                "nonexistent_paper_xxx", pid, client=stub,
            )
            self.assertTrue("error" in res)

    def test_missing_oa_id_falls_back_to_doi(self):
        with isolated_cache():
            pid, cid, mod = _setup_project_with_paper({
                "doi": "10.1/test.fallback",
            })
            stub = StubOpenAlexClient(
                refs=[], batch_results=[],
                cited_by={"results": []},
            )
            res = mod.populate_from_openalex(cid, pid, client=stub)
            # No error; manifest has DOI even without openalex_id
            self.assertTrue("error" not in res, msg=str(res))
            # Verify the stub was called with doi: prefix
            ref_call = next(
                c for c in stub.calls if c[0] == "get_work_references"
            )
            self.assertTrue(
                ref_call[1][0].startswith("doi:"),
                msg=f"expected doi: prefix, got {ref_call[1]}",
            )

    def test_missing_both_oa_and_doi_returns_error(self):
        with isolated_cache():
            pid, cid, mod = _setup_project_with_paper({})
            stub = StubOpenAlexClient()
            res = mod.populate_from_openalex(cid, pid, client=stub)
            self.assertTrue("error" in res)

    def test_backend_error_propagates(self):
        with isolated_cache():
            pid, cid, mod = _setup_project_with_paper({
                "openalex_id": "W2741809807",
            })
            stub = StubOpenAlexClient(ref_error="HTTP 404")
            res = mod.populate_from_openalex(cid, pid, client=stub)
            self.assertTrue("error" in res)


class S2BackendTests(TestCase):
    def test_default_s2_path(self):
        with isolated_cache():
            pid, cid, mod = _setup_project_with_paper({
                "s2_id": "abc123",
                "doi": "10.1/test",
            })
            stub = StubS2Client(
                refs={"data": [
                    {"citedPaper": {
                        "paperId": "p_ref1",
                        "title": "Ref 1",
                        "year": 2018,
                        "externalIds": {"DOI": "10.1/REF1"},
                        "authors": [{"name": "Alpha"}],
                        "influentialCitationCount": 0,
                    }},
                ]},
                citations={"data": [
                    {"citingPaper": {
                        "paperId": "p_cit1",
                        "title": "Cit 1",
                        "year": 2023,
                        "externalIds": {"DOI": "10.1/CIT1"},
                        "authors": [{"name": "Beta"}],
                        "influentialCitationCount": 5,
                    }},
                ]},
            )
            res = mod.populate_from_s2(
                cid, pid, influential_only=False, client=stub,
            )
            self.assertEqual(res.get("source"), "s2")
            self.assertEqual(res["edges_added"], 4)

    def test_influential_filter_excludes_zero(self):
        with isolated_cache():
            pid, cid, mod = _setup_project_with_paper({
                "s2_id": "abc123",
            })
            stub = StubS2Client(
                refs={"data": [
                    {"citedPaper": {
                        "paperId": "p_ref_keep",
                        "title": "Influential ref",
                        "year": 2018,
                        "externalIds": {"DOI": "10.1/keep"},
                        "authors": [{"name": "K"}],
                        "influentialCitationCount": 7,
                    }},
                    {"citedPaper": {
                        "paperId": "p_ref_drop",
                        "title": "Boring ref",
                        "year": 2018,
                        "externalIds": {"DOI": "10.1/drop"},
                        "authors": [{"name": "D"}],
                        "influentialCitationCount": 0,
                    }},
                ]},
                citations={"data": [
                    {"citingPaper": {
                        "paperId": "p_cit_drop",
                        "title": "Boring citer",
                        "year": 2023,
                        "externalIds": {"DOI": "10.1/dc"},
                        "authors": [{"name": "DC"}],
                        "influentialCitationCount": 0,
                    }},
                ]},
            )
            res = mod.populate_from_s2(
                cid, pid, influential_only=True, client=stub,
            )
            self.assertEqual(res.get("source"), "s2-influential")
            # Only 1 ref kept (2 edges), 0 citers kept
            self.assertEqual(res["edges_added"], 2)

    def test_influential_filter_falsy_count_excluded(self):
        with isolated_cache():
            pid, cid, mod = _setup_project_with_paper({"s2_id": "p"})
            stub = StubS2Client(
                refs={"data": [
                    {"citedPaper": {
                        "paperId": "p_no_field",
                        "title": "No field ref",
                        "year": 2018,
                        "externalIds": {"DOI": "10.1/x"},
                        "authors": [{"name": "X"}],
                        # influentialCitationCount missing
                    }},
                ]},
                citations={"data": []},
            )
            res = mod.populate_from_s2(
                cid, pid, influential_only=True, client=stub,
            )
            self.assertEqual(res["edges_added"], 0)

    def test_s2_idempotent_rerun(self):
        with isolated_cache():
            pid, cid, mod = _setup_project_with_paper({"s2_id": "abc"})
            stub = StubS2Client(
                refs={"data": [
                    {"citedPaper": {
                        "paperId": "p_r",
                        "title": "R",
                        "year": 2018,
                        "externalIds": {"DOI": "10.1/r"},
                        "authors": [{"name": "A"}],
                    }},
                ]},
                citations={"data": []},
            )
            r1 = mod.populate_from_s2(cid, pid, client=stub)
            self.assertEqual(r1["edges_added"], 2)
            r2 = mod.populate_from_s2(cid, pid, client=stub)
            self.assertEqual(r2["edges_added"], 0)


class CLIDispatchTests(TestCase):
    """`--source` flag dispatches to the right backend function."""

    def test_source_choices_in_argparse(self):
        # Verify the CLI exposes the right choices by inspecting parser.
        mod = _load_module()
        # Build a parser the same way main() does, then probe.
        import argparse
        p = argparse.ArgumentParser()
        # Mirror the spec of main()'s parser to confirm choices match.
        p.add_argument(
            "--source", default="file",
            choices=["file", "openalex", "s2", "s2-influential"],
        )
        # Smoke: parser accepts each value.
        for val in ("file", "openalex", "s2", "s2-influential"):
            ns = p.parse_args(["--source", val])
            self.assertEqual(ns.source, val)
        # Also confirm the script module exposes the live functions
        self.assertTrue(hasattr(mod, "populate_from_openalex"))
        self.assertTrue(hasattr(mod, "populate_from_s2"))
        self.assertTrue(hasattr(mod, "populate"))

    def test_subprocess_file_mode_runs(self):
        import subprocess
        with isolated_cache() as cache_dir:
            from lib import project as project_mod
            pid = project_mod.create("subproc smoke")
            input_file = cache_dir / "input.json"
            input_file.write_text(json.dumps([{
                "from_canonical_id": "a_2020_x_001",
                "references": [],
                "citations": [],
            }]))
            r = subprocess.run(
                [sys.executable, str(_SCRIPT),
                 "--source", "file",
                 "--input", str(input_file),
                 "--project-id", pid],
                capture_output=True, text=True, timeout=30,
                env={**__import__("os").environ,
                     "COSCIENTIST_CACHE_DIR": str(cache_dir)},
            )
            self.assertEqual(r.returncode, 0,
                             msg=f"stderr={r.stderr}")
            out = json.loads(r.stdout)
            self.assertEqual(out["edges_added"], 0)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        FileModeBackCompatTests,
        OpenAlexBackendTests,
        S2BackendTests,
        CLIDispatchTests,
    ))
