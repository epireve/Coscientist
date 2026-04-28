"""v0.75 — MCP_SERVERS.md parity tests."""
from __future__ import annotations

from pathlib import Path

from lib.mcp_index import discover_mcps, render_index
from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parents[1]
_PLUGINS_ROOT = _REPO / "plugin"
_MCP_MD = _REPO / "MCP_SERVERS.md"


class McpIndexDiscoveryTests(TestCase):
    def test_discovers_at_least_three_mcps(self):
        entries = discover_mcps(_PLUGINS_ROOT)
        self.assertGreaterEqual(
            len(entries), 3,
            f"only {len(entries)} MCP plugins discovered — "
            "expected retraction-mcp, manuscript-mcp, graph-query-mcp",
        )

    def test_every_entry_has_name(self):
        for e in discover_mcps(_PLUGINS_ROOT):
            self.assertTrue(e.name)

    def test_every_entry_has_version(self):
        for e in discover_mcps(_PLUGINS_ROOT):
            self.assertTrue(e.version)

    def test_every_entry_has_description(self):
        empty = [e for e in discover_mcps(_PLUGINS_ROOT) if not e.description]
        self.assertEqual(empty, [], f"missing description: {empty}")

    def test_every_entry_has_server_name(self):
        empty = [
            e for e in discover_mcps(_PLUGINS_ROOT) if not e.server_name
        ]
        self.assertEqual(empty, [], f"missing server_name: {empty}")

    def test_every_entry_has_tools(self):
        empty = [e for e in discover_mcps(_PLUGINS_ROOT) if not e.tools]
        self.assertEqual(empty, [], f"missing tools: {[e.name for e in empty]}")

    def test_no_duplicate_names(self):
        names = [e.name for e in discover_mcps(_PLUGINS_ROOT)]
        self.assertEqual(len(names), len(set(names)))

    def test_known_mcps_present(self):
        names = {e.name for e in discover_mcps(_PLUGINS_ROOT)}
        for expected in (
            "coscientist-retraction-mcp",
            "coscientist-manuscript-mcp",
            "coscientist-graph-query-mcp",
        ):
            self.assertIn(expected, names)

    def test_tool_counts_match_expected(self):
        by_name = {e.name: e for e in discover_mcps(_PLUGINS_ROOT)}
        # retraction-mcp: lookup_doi, batch_lookup, pubpeer_comments
        self.assertEqual(len(by_name["coscientist-retraction-mcp"].tools), 3)
        # manuscript-mcp: detect_format, extract_sections,
        #                 extract_citations, parse_manuscript
        self.assertEqual(len(by_name["coscientist-manuscript-mcp"].tools), 4)
        # graph-query-mcp: neighbors, walk, in_degree, hubs,
        #                  node_info, shortest_path
        self.assertEqual(
            len(by_name["coscientist-graph-query-mcp"].tools), 6,
        )


class McpServersMdParityTests(TestCase):
    def test_md_exists(self):
        self.assertTrue(
            _MCP_MD.exists(),
            "MCP_SERVERS.md missing — regenerate via "
            "`uv run python -m lib.mcp_index > MCP_SERVERS.md`",
        )

    def test_md_matches_generator(self):
        if not _MCP_MD.exists():
            return
        actual = _MCP_MD.read_text()
        expected = render_index(discover_mcps(_PLUGINS_ROOT))
        if actual != expected:
            actual_lines = actual.splitlines()
            expected_lines = expected.splitlines()
            for i, (a, b) in enumerate(zip(actual_lines, expected_lines)):
                if a != b:
                    self.assertEqual(
                        a, b,
                        f"MCP_SERVERS.md drift at line {i+1}. "
                        f"Regenerate via `uv run python -m lib.mcp_index "
                        f"> MCP_SERVERS.md`",
                    )
                    break
            else:
                self.assertEqual(
                    len(actual_lines), len(expected_lines),
                    f"line count differs: actual={len(actual_lines)} "
                    f"expected={len(expected_lines)}",
                )


if __name__ == "__main__":
    raise SystemExit(run_tests(
        McpIndexDiscoveryTests,
        McpServersMdParityTests,
    ))
