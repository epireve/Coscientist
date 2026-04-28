"""v0.72 — marketplace + plugin manifest invariants.

Asserts:
  1. .claude-plugin/marketplace.json parses + has required fields.
  2. Every plugin entry has a matching .claude-plugin/plugin.json
     under the source path.
  3. Plugin name in marketplace.json matches plugin.json name.
  4. Plugin version in marketplace.json matches plugin.json version.
  5. Every plugin source path actually exists.
  6. retraction-mcp plugin's .mcp.json declares its server.
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.harness import TestCase, run_tests


_REPO = Path(__file__).resolve().parents[1]
_MARKETPLACE = _REPO / ".claude-plugin" / "marketplace.json"


def _load_marketplace() -> dict:
    return json.loads(_MARKETPLACE.read_text())


class MarketplaceManifestTests(TestCase):
    def test_marketplace_parses(self):
        data = _load_marketplace()
        self.assertIn("name", data)
        self.assertIn("owner", data)
        self.assertIn("plugins", data)
        self.assertIsInstance(data["plugins"], list)
        self.assertGreater(len(data["plugins"]), 0)

    def test_owner_block(self):
        data = _load_marketplace()
        self.assertIn("name", data["owner"])
        self.assertIn("url", data["owner"])

    def test_every_plugin_has_required_fields(self):
        for entry in _load_marketplace()["plugins"]:
            for field in ("name", "source", "description", "version"):
                self.assertIn(field, entry,
                              f"plugin {entry.get('name', '?')} missing {field}")


class PluginManifestParityTests(TestCase):
    def test_every_source_path_exists(self):
        for entry in _load_marketplace()["plugins"]:
            src = (_REPO / entry["source"]).resolve()
            self.assertTrue(
                src.exists(),
                f"plugin source missing: {entry['name']} -> {src}",
            )

    def test_every_plugin_has_plugin_json(self):
        for entry in _load_marketplace()["plugins"]:
            pj = _REPO / entry["source"] / ".claude-plugin" / "plugin.json"
            self.assertTrue(
                pj.exists(),
                f"plugin.json missing for {entry['name']}: {pj}",
            )

    def test_plugin_json_name_matches(self):
        for entry in _load_marketplace()["plugins"]:
            pj_path = _REPO / entry["source"] / ".claude-plugin" / "plugin.json"
            pj = json.loads(pj_path.read_text())
            self.assertEqual(
                entry["name"], pj["name"],
                f"name drift: marketplace={entry['name']!r} "
                f"plugin.json={pj['name']!r}",
            )

    def test_plugin_json_version_matches(self):
        for entry in _load_marketplace()["plugins"]:
            pj_path = _REPO / entry["source"] / ".claude-plugin" / "plugin.json"
            pj = json.loads(pj_path.read_text())
            self.assertEqual(
                entry["version"], pj["version"],
                f"version drift: marketplace={entry['version']!r} "
                f"plugin.json={pj['version']!r} for {entry['name']}",
            )


class RetractionMcpPluginTests(TestCase):
    """retraction-mcp plugin specifics."""

    PLUGIN = _REPO / "plugin" / "coscientist-retraction-mcp"

    def test_plugin_dir_exists(self):
        self.assertTrue(self.PLUGIN.exists())

    def test_server_script_present(self):
        srv = self.PLUGIN / "server" / "server.py"
        self.assertTrue(srv.exists(), f"missing {srv}")
        # Sanity: must define `mcp` and at least the lookup_doi tool.
        text = srv.read_text()
        self.assertIn("FastMCP", text)
        self.assertIn("def lookup_doi", text)
        self.assertIn("def batch_lookup", text)
        self.assertIn("def pubpeer_comments", text)

    def test_mcp_json_declares_server(self):
        cfg_path = self.PLUGIN / ".mcp.json"
        self.assertTrue(cfg_path.exists(), f"missing {cfg_path}")
        cfg = json.loads(cfg_path.read_text())
        self.assertIn("mcpServers", cfg)
        self.assertIn("retraction", cfg["mcpServers"])
        srv = cfg["mcpServers"]["retraction"]
        self.assertEqual(srv.get("type"), "stdio")
        # Args must reference the bundled server via CLAUDE_PLUGIN_ROOT.
        joined = " ".join(srv.get("args", []))
        self.assertIn("CLAUDE_PLUGIN_ROOT", joined)
        self.assertIn("server.py", joined)

    def test_readme_present(self):
        self.assertTrue((self.PLUGIN / "README.md").exists())

    def test_plugin_server_matches_source(self):
        """Plugin's server.py must be byte-identical to mcp/retraction-mcp/server.py.
        Drift here means the plugin ships stale code."""
        plugin_srv = (self.PLUGIN / "server" / "server.py").read_text()
        source_srv = (_REPO / "mcp" / "retraction-mcp" / "server.py").read_text()
        self.assertEqual(
            plugin_srv, source_srv,
            "plugin server.py drifted from mcp/retraction-mcp/server.py — "
            "regenerate via `cp mcp/retraction-mcp/server.py "
            "plugin/coscientist-retraction-mcp/server/server.py`",
        )


if __name__ == "__main__":
    raise SystemExit(run_tests(
        MarketplaceManifestTests,
        PluginManifestParityTests,
        RetractionMcpPluginTests,
    ))
