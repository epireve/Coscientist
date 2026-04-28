"""v0.76 — opt-in live integration tests for retraction-mcp.

Skipped by default (no network in CI). Run manually with:

    COSCIENTIST_RUN_LIVE=1 uv run python tests/test_retraction_mcp_live.py

Tests hit real Crossref + PubPeer. Slow (~5-10s). Designed to catch
upstream API shape drift; pure-unit tests already cover parser logic.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parents[1]
_SERVER = _REPO / "mcp" / "retraction-mcp" / "server.py"
_LIVE = os.environ.get("COSCIENTIST_RUN_LIVE") == "1"


def _import_server():
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
        "retraction_mcp_server_live", _SERVER,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# A famous-but-real DOI: Vaswani et al. 2017 "Attention Is All You Need".
# Not retracted; lookup should succeed.
_REAL_DOI = "10.48550/arXiv.1706.03762"

# A widely-known retraction (Wakefield's 1998 MMR-autism paper, Lancet).
_RETRACTED_DOI = "10.1016/s0140-6736(97)11096-0"


class CrossrefLiveTests(TestCase):
    def setUp(self):
        if not _LIVE:
            return
        self.mod = _import_server()

    def test_real_doi_resolves(self):
        if not _LIVE:
            return  # skipped — set COSCIENTIST_RUN_LIVE=1
        out = self.mod.lookup_doi(_REAL_DOI)
        self.assertTrue(
            out["found"],
            f"Crossref couldn't resolve a known DOI: {out}",
        )
        self.assertEqual(out["source"], "crossref")
        self.assertIsNotNone(out["title"])

    def test_known_retraction_flagged(self):
        if not _LIVE:
            return
        out = self.mod.lookup_doi(_RETRACTED_DOI)
        self.assertTrue(out["found"])
        self.assertTrue(
            out["is_retracted"],
            f"Wakefield 1998 should be flagged as retracted: {out}",
        )

    def test_nonsense_doi_returns_not_found(self):
        if not _LIVE:
            return
        out = self.mod.lookup_doi("10.9999/this-doi-does-not-exist-zzz")
        self.assertFalse(out["found"])

    def test_batch_lookup_three_dois(self):
        if not _LIVE:
            return
        out = self.mod.batch_lookup(
            [_REAL_DOI, _RETRACTED_DOI,
             "10.9999/missing"], delay_seconds=0.1,
        )
        self.assertEqual(len(out), 3)
        self.assertTrue(out[0]["found"])
        self.assertTrue(out[1]["is_retracted"])
        self.assertFalse(out[2]["found"])


class PubPeerLiveTests(TestCase):
    def setUp(self):
        if not _LIVE:
            return
        self.mod = _import_server()

    def test_pubpeer_lookup_returns_dict(self):
        if not _LIVE:
            return
        out = self.mod.pubpeer_comments(_REAL_DOI)
        # PubPeer returns either found=True with comment_count, or
        # found=False if the DOI isn't tracked. Either is acceptable.
        self.assertIn("doi", out)
        self.assertEqual(out["source"], "pubpeer")


if __name__ == "__main__":
    if not _LIVE:
        print(
            "[SKIP] live tests require COSCIENTIST_RUN_LIVE=1 in env",
            file=sys.stderr,
        )
    raise SystemExit(run_tests(CrossrefLiveTests, PubPeerLiveTests))
