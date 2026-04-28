"""v0.72 — retraction-mcp unit tests.

Pure-unit: imports the server module, exercises the parser + the
DOI normalizer. No live HTTP. Skips the FastMCP server bootstrap.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

from tests.harness import TestCase, run_tests


_REPO = Path(__file__).resolve().parents[1]
_SERVER = _REPO / "mcp" / "retraction-mcp" / "server.py"


def _import_server():
    """Import the server module without running its main(). Stubs the
    `mcp` package so the import doesn't fail when mcp isn't installed
    in the test environment."""
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
        "retraction_mcp_server", _SERVER,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class DoiNormalizerTests(TestCase):
    def setUp(self):
        self.mod = _import_server()

    def test_strips_doi_prefix(self):
        self.assertEqual(
            self.mod._normalize_doi("doi:10.1038/nature12373"),
            "10.1038/nature12373",
        )

    def test_strips_https_url(self):
        self.assertEqual(
            self.mod._normalize_doi("https://doi.org/10.1038/Nature12373"),
            "10.1038/nature12373",
        )

    def test_strips_dx_url(self):
        self.assertEqual(
            self.mod._normalize_doi("https://dx.doi.org/10.1038/X"),
            "10.1038/x",
        )

    def test_lowercases(self):
        self.assertEqual(
            self.mod._normalize_doi("10.1038/NATURE12373"),
            "10.1038/nature12373",
        )

    def test_strips_whitespace(self):
        self.assertEqual(
            self.mod._normalize_doi("  10.1038/x  "),
            "10.1038/x",
        )


class CrossrefMessageParserTests(TestCase):
    def setUp(self):
        self.mod = _import_server()

    def test_no_notices_means_not_retracted(self):
        msg = {
            "title": ["Some Paper"],
            "container-title": ["Nature"],
            "issued": {"date-parts": [[2020, 1, 1]]},
        }
        out = self.mod._parse_crossref_message(msg)
        self.assertFalse(out["is_retracted"])
        self.assertFalse(out["has_correction_or_eoc"])
        self.assertEqual(out["notices"], [])
        self.assertEqual(out["title"], "Some Paper")
        self.assertEqual(out["year"], 2020)

    def test_retraction_notice_detected(self):
        msg = {
            "title": ["Retracted Paper"],
            "update-to": [
                {"type": "retraction", "DOI": "10.1/r1",
                 "label": "Retraction notice"},
            ],
        }
        out = self.mod._parse_crossref_message(msg)
        self.assertTrue(out["is_retracted"])
        self.assertEqual(len(out["notices"]), 1)
        self.assertEqual(out["notices"][0]["type"], "retraction")

    def test_correction_separate_from_retraction(self):
        msg = {
            "update-to": [
                {"type": "correction", "DOI": "10.1/c1"},
            ],
        }
        out = self.mod._parse_crossref_message(msg)
        self.assertFalse(out["is_retracted"])
        self.assertTrue(out["has_correction_or_eoc"])

    def test_expression_of_concern_treated_as_correction(self):
        msg = {
            "update-to": [
                {"type": "expression-of-concern", "DOI": "10.1/e1"},
            ],
        }
        out = self.mod._parse_crossref_message(msg)
        self.assertFalse(out["is_retracted"])
        self.assertTrue(out["has_correction_or_eoc"])

    def test_uppercase_type_recognized(self):
        msg = {"update-to": [{"type": "Retraction"}]}
        out = self.mod._parse_crossref_message(msg)
        self.assertTrue(out["is_retracted"])

    def test_missing_fields_no_crash(self):
        msg = {}
        out = self.mod._parse_crossref_message(msg)
        self.assertIsNone(out["title"])
        self.assertIsNone(out["year"])
        self.assertFalse(out["is_retracted"])


class LookupDoiHttpMockTests(TestCase):
    """Patch _http_get_json to verify lookup_doi end-to-end without a network."""

    def setUp(self):
        self.mod = _import_server()

    def test_happy_path(self):
        fake = {
            "message": {
                "title": ["Mocked Paper"],
                "container-title": ["MockJournal"],
                "issued": {"date-parts": [[2021]]},
                "update-to": [{"type": "retraction", "DOI": "10.1/r"}],
            }
        }
        with patch.object(self.mod, "_http_get_json", return_value=fake):
            out = self.mod.lookup_doi("10.X/y")
        self.assertTrue(out["found"])
        self.assertTrue(out["is_retracted"])
        self.assertEqual(out["title"], "Mocked Paper")

    def test_404_returns_not_found(self):
        import urllib.error

        def raise_404(url):
            raise urllib.error.HTTPError(url, 404, "not found", {}, None)

        with patch.object(self.mod, "_http_get_json", side_effect=raise_404):
            out = self.mod.lookup_doi("10.X/missing")
        self.assertFalse(out["found"])
        self.assertIn("not in Crossref", out["error"])

    def test_empty_doi_short_circuits(self):
        out = self.mod.lookup_doi("")
        self.assertFalse(out["found"])

    def test_other_http_error(self):
        import urllib.error

        def raise_500(url):
            raise urllib.error.HTTPError(url, 500, "server error", {}, None)

        with patch.object(self.mod, "_http_get_json", side_effect=raise_500):
            out = self.mod.lookup_doi("10.X/y")
        self.assertFalse(out["found"])
        self.assertIn("HTTP 500", out["error"])


class BatchLookupTests(TestCase):
    def setUp(self):
        self.mod = _import_server()

    def test_batch_preserves_order(self):
        with patch.object(self.mod, "lookup_doi",
                           side_effect=lambda d: {"doi": d, "found": True}):
            out = self.mod.batch_lookup(["a", "b", "c"], delay_seconds=0)
        self.assertEqual([r["doi"] for r in out], ["a", "b", "c"])

    def test_batch_empty(self):
        out = self.mod.batch_lookup([], delay_seconds=0)
        self.assertEqual(out, [])


class PubPeerCommentsTests(TestCase):
    def setUp(self):
        self.mod = _import_server()

    def test_no_publications_means_zero_comments(self):
        with patch.object(self.mod, "_http_get_json",
                           return_value={"data": []}):
            out = self.mod.pubpeer_comments("10.X/y")
        self.assertFalse(out["found"])
        self.assertEqual(out["comment_count"], 0)

    def test_publication_with_comments(self):
        fake = {"data": [{
            "comments_count": 7,
            "url": "https://pubpeer.com/publications/abc",
        }]}
        with patch.object(self.mod, "_http_get_json", return_value=fake):
            out = self.mod.pubpeer_comments("10.X/y")
        self.assertTrue(out["found"])
        self.assertEqual(out["comment_count"], 7)
        self.assertIn("pubpeer.com", out["publication_url"])

    def test_alternative_field_name(self):
        # Some endpoints emit `total_comments` instead of `comments_count`.
        fake = {"publications": [{"total_comments": 3}]}
        with patch.object(self.mod, "_http_get_json", return_value=fake):
            out = self.mod.pubpeer_comments("10.X/y")
        self.assertEqual(out["comment_count"], 3)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        DoiNormalizerTests,
        CrossrefMessageParserTests,
        LookupDoiHttpMockTests,
        BatchLookupTests,
        PubPeerCommentsTests,
    ))
