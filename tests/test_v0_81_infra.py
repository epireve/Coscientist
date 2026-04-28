"""v0.81 — marketplace + infra + latent-risk tests."""
from __future__ import annotations

from pathlib import Path

from lib.install_check import run_checks
from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parents[1]


class CiWorkflowTests(TestCase):
    def test_workflow_file_present(self):
        path = _REPO / ".github" / "workflows" / "tests.yml"
        self.assertTrue(path.exists(), f"missing CI workflow at {path}")

    def test_workflow_runs_run_all(self):
        path = _REPO / ".github" / "workflows" / "tests.yml"
        text = path.read_text()
        self.assertIn("tests/run_all.py", text)
        self.assertIn("uv sync", text)


class McpDepTests(TestCase):
    def test_pyproject_declares_mcp_extra(self):
        pp = (_REPO / "pyproject.toml").read_text()
        self.assertIn("[project.optional-dependencies]", pp)
        # The `mcp` extra group must be declared.
        self.assertIn("mcp = [", pp)
        self.assertIn("mcp>=1.0", pp)


class InstallCheckTests(TestCase):
    def test_run_checks_returns_dict(self):
        result = run_checks()
        self.assertIsInstance(result, dict)
        self.assertIn("ok", result)
        self.assertIn("n_plugins", result)
        self.assertIn("results", result)

    def test_all_known_plugins_healthy(self):
        result = run_checks()
        unhealthy = [
            r for r in result["results"] if not r["healthy"]
        ]
        self.assertEqual(
            unhealthy, [],
            f"unhealthy plugins: "
            f"{[(r['plugin'], r['issues']) for r in unhealthy]}",
        )

    def test_at_least_four_plugins(self):
        result = run_checks()
        self.assertGreaterEqual(result["n_plugins"], 4)

    def test_mcp_plugins_have_servers(self):
        result = run_checks()
        for r in result["results"]:
            if r["plugin"].endswith("-mcp"):
                self.assertTrue(
                    r["server_present"],
                    f"{r['plugin']} missing server",
                )
                self.assertTrue(
                    r["server_compiles"],
                    f"{r['plugin']} server.py has syntax error",
                )
                self.assertTrue(
                    r["mcp_json_ok"],
                    f"{r['plugin']} .mcp.json invalid",
                )


class ReadmeTroubleshootingTests(TestCase):
    def test_readme_has_troubleshooting_section(self):
        readme = (_REPO / "README.md").read_text()
        self.assertIn("Install troubleshooting", readme)
        # Common topics:
        self.assertIn("marketplace", readme.lower())
        self.assertIn("install_check", readme)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        CiWorkflowTests,
        McpDepTests,
        InstallCheckTests,
        ReadmeTroubleshootingTests,
    ))
