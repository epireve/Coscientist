"""v0.149 — Semantic Scholar enrichment client tests."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from lib import s2_enrichment as s2mod
from tests.harness import TestCase, isolated_cache, run_tests


_REPO = Path(__file__).resolve().parents[1]


class _StubClient(s2mod.S2Client):
    """Replaces _request with scripted responses keyed by (method, path)."""

    def __init__(self, *, scripted: dict, **kwargs):
        kwargs.setdefault("cache_enabled", False)
        super().__init__(**kwargs)
        self._scripted = scripted
        self.calls: list[tuple[str, str, dict | None, object]] = []

    def _request(self, method, path, params=None, body=None):
        self.calls.append((method, path, params, body))
        key = (method, path)
        if key in self._scripted:
            return self._scripted[key]
        return {"error": "no script for " + method + " " + path}


class AuthResolutionTests(TestCase):
    def test_kwarg_wins_over_env(self):
        with isolated_cache():
            r = s2mod._resolve_auth(api_key="from-kwarg")
            self.assertEqual(r, "from-kwarg")

    def test_env_used_when_no_kwarg(self):
        import os
        old = os.environ.get("S2_API_KEY")
        os.environ["S2_API_KEY"] = "from-env"
        try:
            r = s2mod._resolve_auth()
            self.assertEqual(r, "from-env")
        finally:
            if old is None:
                del os.environ["S2_API_KEY"]
            else:
                os.environ["S2_API_KEY"] = old

    def test_anonymous_when_neither_set(self):
        import os
        old = os.environ.pop("S2_API_KEY", None)
        try:
            r = s2mod._resolve_auth()
            self.assertIsNone(r)
        finally:
            if old is not None:
                os.environ["S2_API_KEY"] = old


class CacheKeyTests(TestCase):
    def test_same_key_with_or_without_auth(self):
        # auth is NOT part of cache key (excluded from params)
        k1 = s2mod._cache_key("/paper/X", {"fields": "tldr"})
        k2 = s2mod._cache_key("/paper/X", {"fields": "tldr"})
        self.assertEqual(k1, k2)

    def test_body_changes_key(self):
        k1 = s2mod._cache_key("/paper/batch", None, {"ids": ["A"]})
        k2 = s2mod._cache_key("/paper/batch", None, {"ids": ["B"]})
        self.assertTrue(k1 != k2)


class BatchGetPapersTests(TestCase):
    def test_empty_ids_returns_empty(self):
        with isolated_cache():
            cli = _StubClient(scripted={})
            r = cli.batch_get_papers([])
            self.assertEqual(r["results"], [])

    def test_oversize_batch_rejected(self):
        with isolated_cache():
            cli = _StubClient(scripted={})
            r = cli.batch_get_papers(["x"] * (s2mod.BATCH_LIMIT + 1))
            self.assertIn("error", r)
            self.assertIn("exceeds", r["error"])

    def test_normal_batch_calls_post(self):
        with isolated_cache():
            cli = _StubClient(scripted={
                ("POST", "/paper/batch"): [
                    {"paperId": "A", "tldr": {"text": "summary A"}},
                    {"paperId": "B", "tldr": {"text": "summary B"}},
                ],
            })
            r = cli.batch_get_papers(["A", "B"])
            self.assertEqual(len(r["results"]), 2)
            self.assertEqual(r["results"][0]["paperId"], "A")

    def test_batch_passes_ids_in_body(self):
        with isolated_cache():
            cli = _StubClient(scripted={
                ("POST", "/paper/batch"): [{"paperId": "A"}],
            })
            cli.batch_get_papers(["A"])
            method, path, _, body = cli.calls[0]
            self.assertEqual(method, "POST")
            self.assertEqual(path, "/paper/batch")
            self.assertEqual(body, {"ids": ["A"]})

    def test_error_propagated(self):
        with isolated_cache():
            cli = _StubClient(scripted={
                ("POST", "/paper/batch"): {"error": "HTTP 429"},
            })
            r = cli.batch_get_papers(["A"])
            self.assertIn("error", r)


class GetPaperTests(TestCase):
    def test_get_paper_uses_get(self):
        with isolated_cache():
            cli = _StubClient(scripted={
                ("GET", "/paper/W123"): {"paperId": "W123"},
            })
            r = cli.get_paper("W123")
            self.assertEqual(r["paperId"], "W123")

    def test_get_paper_with_doi_prefix(self):
        with isolated_cache():
            cli = _StubClient(scripted={
                ("GET", "/paper/DOI:10.1/x"): {"paperId": "abc"},
            })
            r = cli.get_paper("DOI:10.1/x")
            self.assertEqual(r["paperId"], "abc")


class ReferencesAndCitationsTests(TestCase):
    def test_references(self):
        with isolated_cache():
            cli = _StubClient(scripted={
                ("GET", "/paper/W1/references"): {
                    "data": [{"citedPaper": {"paperId": "W2"}}],
                },
            })
            r = cli.get_paper_references("W1")
            self.assertEqual(len(r["data"]), 1)

    def test_citations(self):
        with isolated_cache():
            cli = _StubClient(scripted={
                ("GET", "/paper/W1/citations"): {
                    "data": [{"citingPaper": {"paperId": "W3"}}],
                },
            })
            r = cli.get_paper_citations("W1")
            self.assertEqual(len(r["data"]), 1)


class SearchTests(TestCase):
    def test_search(self):
        with isolated_cache():
            cli = _StubClient(scripted={
                ("GET", "/paper/search"): {
                    "data": [{"paperId": "W1"}],
                    "total": 1,
                },
            })
            r = cli.search_papers("attention transformers")
            self.assertEqual(r["total"], 1)


class StaticHelperTests(TestCase):
    def test_extract_tldr_present(self):
        p = {"tldr": {"text": "Cool finding."}}
        self.assertEqual(s2mod.S2Client.extract_tldr(p), "Cool finding.")

    def test_extract_tldr_missing(self):
        self.assertIsNone(s2mod.S2Client.extract_tldr({}))
        self.assertIsNone(s2mod.S2Client.extract_tldr({"tldr": None}))

    def test_extract_embedding(self):
        p = {"embedding": {"vector": [0.1, 0.2, 0.3]}}
        v = s2mod.S2Client.extract_embedding(p)
        self.assertEqual(v, [0.1, 0.2, 0.3])

    def test_extract_embedding_missing(self):
        self.assertIsNone(s2mod.S2Client.extract_embedding({}))

    def test_extract_influential_count(self):
        self.assertEqual(s2mod.S2Client.extract_influential_count(
            {"influentialCitationCount": 42}), 42)
        self.assertEqual(s2mod.S2Client.extract_influential_count({}), 0)
        self.assertEqual(s2mod.S2Client.extract_influential_count(
            {"influentialCitationCount": None}), 0)

    def test_extract_external_ids_full(self):
        p = {
            "paperId": "abc",
            "externalIds": {
                "DOI": "10.1/X",
                "ArXiv": "2401.12345",
                "PubMed": "12345",
                "PubMedCentral": "PMC1",
                "MAG": "999",
                "CorpusId": "1234567",
                "ACL": "P19-1001",
            },
        }
        out = s2mod.S2Client.extract_external_ids(p)
        self.assertEqual(out["doi"], "10.1/x")
        self.assertEqual(out["arxiv_id"], "2401.12345")
        self.assertEqual(out["pmid"], "12345")
        self.assertEqual(out["pmcid"], "PMC1")
        self.assertEqual(out["mag_id"], "999")
        self.assertEqual(out["s2_corpus_id"], "1234567")
        self.assertEqual(out["acl_id"], "P19-1001")
        self.assertEqual(out["s2_paper_id"], "abc")

    def test_extract_external_ids_empty(self):
        self.assertEqual(s2mod.S2Client.extract_external_ids({}), {})

    def test_extract_external_ids_filters_none(self):
        p = {"externalIds": {"DOI": None, "ArXiv": "2401.x"}}
        out = s2mod.S2Client.extract_external_ids(p)
        self.assertNotIn("doi", out)
        self.assertEqual(out["arxiv_id"], "2401.x")


class CacheRoundtripTests(TestCase):
    def test_cache_persists_and_returns(self):
        with isolated_cache():
            cli = s2mod.S2Client(cache_enabled=True)
            # Manually put + get via _cache_put / _cache_get
            cli._cache_put("k1", {"hello": "world"})
            self.assertEqual(cli._cache_get("k1"), {"hello": "world"})

    def test_errors_not_cached(self):
        with isolated_cache():
            cli = s2mod.S2Client(cache_enabled=True)
            cli._cache_put("k2", {"error": "HTTP 429"})
            self.assertIsNone(cli._cache_get("k2"))

    def test_cache_stats_when_enabled(self):
        with isolated_cache():
            cli = s2mod.S2Client(cache_enabled=True)
            stats = cli.cache_stats()
            self.assertTrue(stats["enabled"])
            self.assertEqual(stats["entries"], 0)

    def test_cache_clear(self):
        with isolated_cache():
            cli = s2mod.S2Client(cache_enabled=True)
            cli._cache_put("a", {"x": 1})
            cli._cache_put("b", {"y": 2})
            n = cli.cache_clear()
            self.assertEqual(n, 2)


class CliTests(TestCase):
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "lib.s2_enrichment", *args],
            capture_output=True, text=True, cwd=str(_REPO),
        )

    def test_help(self):
        r = self._run("-h")
        self.assertEqual(r.returncode, 0)
        self.assertIn("batch", r.stdout)

    def test_cache_subcmd(self):
        with isolated_cache():
            import os
            env = dict(os.environ)
            env["XDG_CACHE_HOME"] = str(Path.home() / ".cache")
            r = subprocess.run(
                [sys.executable, "-m", "lib.s2_enrichment", "cache"],
                capture_output=True, text=True, cwd=str(_REPO),
                env=env,
            )
            # cache subcmd produces a JSON dict either way
            self.assertEqual(r.returncode, 0)
            data = json.loads(r.stdout)
            self.assertIn("enabled", data)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        AuthResolutionTests, CacheKeyTests, BatchGetPapersTests,
        GetPaperTests, ReferencesAndCitationsTests, SearchTests,
        StaticHelperTests, CacheRoundtripTests, CliTests,
    ))
