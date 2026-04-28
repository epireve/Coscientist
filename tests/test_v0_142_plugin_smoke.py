"""v0.142 — per-plugin server smoke test.

Imports plugin/<X>/server/server.py directly + verifies tool
registry. Caught by v0.85 PluginChecksumsTests if files drift,
but byte-equal source could still hide runtime errors. This
test exercises the plugin path explicitly.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from tests.harness import TestCase, run_tests


_REPO = Path(__file__).resolve().parents[1]
_PLUGINS = (
    ("coscientist-graph-query-mcp", "graph-query-mcp"),
    ("coscientist-manuscript-mcp", "manuscript-mcp"),
    ("coscientist-retraction-mcp", "retraction-mcp"),
)


def _import_module_from_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class PluginServerImportsTests(TestCase):
    """Each plugin's server.py must import without error."""

    def test_graph_query_mcp_imports(self):
        path = (_REPO / "plugin" / "coscientist-graph-query-mcp"
                / "server" / "server.py")
        self.assertTrue(path.exists())
        mod = _import_module_from_path(
            "plugin_graph_query_server_test", path,
        )
        # FastMCP server attribute conventions
        self.assertTrue(hasattr(mod, "mcp") or hasattr(mod, "server"))

    def test_manuscript_mcp_imports(self):
        path = (_REPO / "plugin" / "coscientist-manuscript-mcp"
                / "server" / "server.py")
        self.assertTrue(path.exists())
        mod = _import_module_from_path(
            "plugin_manuscript_server_test", path,
        )
        self.assertTrue(
            hasattr(mod, "parse_manuscript")
            or hasattr(mod, "mcp"),
        )

    def test_retraction_mcp_imports(self):
        path = (_REPO / "plugin" / "coscientist-retraction-mcp"
                / "server" / "server.py")
        self.assertTrue(path.exists())
        mod = _import_module_from_path(
            "plugin_retraction_server_test", path,
        )
        self.assertTrue(
            hasattr(mod, "lookup_doi")
            or hasattr(mod, "mcp"),
        )


class PluginManuscriptDocxErrorTests(TestCase):
    """v0.130 fix — fmt=docx on missing path returns error."""

    def test_plugin_path_returns_error_when_file_missing(self):
        path = (_REPO / "plugin" / "coscientist-manuscript-mcp"
                / "server" / "server.py")
        mod = _import_module_from_path(
            "plugin_manuscript_docx_test", path,
        )
        out = mod.parse_manuscript("/nonexistent.docx", fmt="docx")
        self.assertIn("error", out)


class PluginConfigsValidTests(TestCase):
    """Each plugin has plugin.json + .mcp.json + CHECKSUMS.txt."""

    def test_each_plugin_has_required_files(self):
        for plugin_dir, _ in _PLUGINS:
            base = _REPO / "plugin" / plugin_dir
            for required in (
                ".mcp.json",
                ".claude-plugin/plugin.json",
                "CHECKSUMS.txt",
                "server/server.py",
            ):
                self.assertTrue(
                    (base / required).exists(),
                    f"{plugin_dir}/{required} missing",
                )


if __name__ == "__main__":
    raise SystemExit(run_tests(
        PluginServerImportsTests,
        PluginManuscriptDocxErrorTests,
        PluginConfigsValidTests,
    ))
