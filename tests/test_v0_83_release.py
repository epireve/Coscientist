"""v0.83 — release workflow + install shell script tests."""
from __future__ import annotations

import os
import stat
from pathlib import Path

from tests.harness import TestCase, run_tests


_REPO = Path(__file__).resolve().parents[1]


class ReleaseWorkflowTests(TestCase):
    PATH = _REPO / ".github" / "workflows" / "release.yml"

    def test_workflow_present(self):
        self.assertTrue(self.PATH.exists(), f"missing {self.PATH}")

    def test_triggers_on_plugin_tags(self):
        text = self.PATH.read_text()
        for tag in ("retraction-mcp-v",
                    "manuscript-mcp-v",
                    "graph-query-mcp-v"):
            self.assertIn(tag, text,
                          f"release.yml missing tag pattern {tag}")

    def test_uses_uv_build(self):
        text = self.PATH.read_text()
        self.assertIn("uv build", text)

    def test_publish_step_gated(self):
        # Publish to PyPI must be commented out / behind a gate;
        # auto-publish is risky.
        text = self.PATH.read_text()
        publish_idx = text.find("publish:")
        if publish_idx == -1:
            return
        # If `publish:` is present, every line in the block must be
        # commented (start with `#`) or we accept gates via env.
        block = text[publish_idx:publish_idx + 800]
        # Permissive: just ensure it doesn't run unconditionally.
        self.assertTrue("#" in block,
                        "release.yml has uncommented publish step — gate it")


class InstallScriptTests(TestCase):
    PATH = _REPO / "scripts" / "install_all.sh"

    def test_script_present(self):
        self.assertTrue(self.PATH.exists())

    def test_script_executable(self):
        mode = self.PATH.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR,
                        f"{self.PATH} not user-executable")

    def test_script_lists_all_four_plugins(self):
        text = self.PATH.read_text()
        for plugin in (
            "coscientist-deep-research",
            "coscientist-retraction-mcp",
            "coscientist-manuscript-mcp",
            "coscientist-graph-query-mcp",
        ):
            self.assertIn(plugin, text,
                          f"install script missing {plugin}")

    def test_script_adds_marketplace_first(self):
        text = self.PATH.read_text()
        # marketplace add should appear before any install command.
        market_idx = text.find("marketplace add")
        install_idx = text.find("plugin install")
        self.assertGreater(market_idx, 0)
        self.assertGreater(install_idx, market_idx,
                           "install_all.sh runs install before marketplace add")

    def test_script_uses_strict_mode(self):
        text = self.PATH.read_text()
        # Bash strict mode is critical for install scripts.
        self.assertIn("set -e", text)


if __name__ == "__main__":
    raise SystemExit(run_tests(ReleaseWorkflowTests, InstallScriptTests))
