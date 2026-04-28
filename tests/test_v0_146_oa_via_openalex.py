"""v0.146 — paper-acquire OA via OpenAlex tests."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from lib.cache import paper_dir
from tests.harness import TestCase, isolated_cache, run_tests


_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = (_REPO / ".claude" / "skills" / "paper-acquire"
           / "scripts" / "oa_via_openalex.py")


def _load():
    spec = importlib.util.spec_from_file_location(
        "_oa_via_openalex_test", _SCRIPT,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_oa_via_openalex_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _setup_paper(cid: str, manifest: dict):
    pd = paper_dir(cid)
    pd.mkdir(parents=True, exist_ok=True)
    (pd / "manifest.json").write_text(json.dumps(manifest))


class FakeClient:
    """Mock OpenAlexClient for unit tests."""

    def __init__(self, *, get_work_response=None,
                 search_response=None):
        self._get = get_work_response or {}
        self._search = search_response or {"results": []}

    def get_work(self, x):
        if isinstance(self._get, dict):
            return self._get
        return self._get(x)

    def search_works(self, *a, **kw):
        if callable(self._search):
            return self._search(*a, **kw)
        return self._search


class ResolveByDoiTests(TestCase):
    def test_returns_oa_url_when_doi_lookup_succeeds(self):
        mod = _load()
        with isolated_cache():
            _setup_paper("p1", {"doi": "10.1/x", "title": "T"})
            client = FakeClient(get_work_response={
                "id": "https://openalex.org/W123",
                "open_access": {"oa_url": "https://oa.com/p.pdf"},
            })
            r = mod.resolve_oa_url("p1", client=client)
            self.assertTrue(r["ok"])
            self.assertEqual(r["oa_url"], "https://oa.com/p.pdf")
            self.assertEqual(r["lookup_via"], "doi")
            self.assertEqual(r["openalex_id"], "W123")

    def test_no_oa_url_returns_failure(self):
        mod = _load()
        with isolated_cache():
            _setup_paper("p2", {"doi": "10.1/x"})
            client = FakeClient(get_work_response={
                "id": "https://openalex.org/W2",
                "open_access": {"is_oa": False},
            })
            r = mod.resolve_oa_url("p2", client=client)
            self.assertFalse(r["ok"])
            self.assertIsNone(r["oa_url"])


class ResolveByArxivTests(TestCase):
    def test_arxiv_id_matches_landing_url(self):
        mod = _load()
        with isolated_cache():
            _setup_paper("p3", {"arxiv_id": "2401.12345"})
            client = FakeClient(search_response={
                "results": [
                    {"id": "https://openalex.org/W3",
                     "primary_location": {
                         "landing_page_url":
                             "https://arxiv.org/abs/2401.12345",
                     },
                     "open_access": {"oa_url": "https://arxiv.org/pdf/2401.12345.pdf"}},
                ],
            })
            r = mod.resolve_oa_url("p3", client=client)
            self.assertTrue(r["ok"])
            self.assertEqual(r["lookup_via"], "arxiv")


class ResolveByTitleTests(TestCase):
    def test_title_fallback_when_doi_missing(self):
        mod = _load()
        with isolated_cache():
            _setup_paper("p4", {"title": "Attention is all you need"})
            client = FakeClient(search_response={
                "results": [
                    {"id": "https://openalex.org/W4",
                     "open_access": {"oa_url": "https://oa.com/q.pdf"}},
                ],
            })
            r = mod.resolve_oa_url("p4", client=client)
            self.assertTrue(r["ok"])
            self.assertEqual(r["lookup_via"], "title")


class ErrorPathsTests(TestCase):
    def test_missing_manifest_returns_error(self):
        mod = _load()
        with isolated_cache():
            r = mod.resolve_oa_url("nonexistent")
            self.assertFalse(r["ok"])
            self.assertIn("no manifest", r["error"])

    def test_no_lookup_keys_returns_error(self):
        mod = _load()
        with isolated_cache():
            _setup_paper("p5", {})  # empty manifest
            client = FakeClient(search_response={"results": []})
            r = mod.resolve_oa_url("p5", client=client)
            self.assertFalse(r["ok"])

    def test_invalid_manifest_returns_error(self):
        mod = _load()
        with isolated_cache():
            pd = paper_dir("bad")
            pd.mkdir(parents=True, exist_ok=True)
            (pd / "manifest.json").write_text("not json {")
            r = mod.resolve_oa_url("bad")
            self.assertFalse(r["ok"])
            self.assertIn("invalid", r["error"])


class CliTests(TestCase):
    def test_help_works(self):
        import subprocess
        r = subprocess.run(
            [sys.executable, str(_SCRIPT), "-h"],
            capture_output=True, text=True, cwd=str(_REPO),
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("--canonical-id", r.stdout)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        ResolveByDoiTests, ResolveByArxivTests,
        ResolveByTitleTests, ErrorPathsTests, CliTests,
    ))
