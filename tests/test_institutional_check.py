"""v0.39 tests for institutional-access check.py."""

from tests import _shim  # noqa: F401

import json
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, run_tests

_ROOT = Path(__file__).resolve().parent.parent
CHECK = _ROOT / ".claude/skills/institutional-access/scripts/check.py"


def _run() -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CHECK), "check"],
                          capture_output=True, text=True)


class CheckCommandTests(TestCase):
    def test_check_emits_json_with_required_fields(self):
        r = _run()
        # exit code may be 0 or 1 depending on env (playwright + state file)
        out = json.loads(r.stdout)
        for key in ("ready", "playwright", "storage_state", "registry",
                    "adapters", "summary"):
            self.assertIn(key, out)

    def test_check_validates_all_known_adapters(self):
        r = _run()
        out = json.loads(r.stdout)
        names = {a["name"] for a in out["adapters"]}
        # Current registry: 9 specific publishers + generic fallback
        for expected in ("acm", "acs", "elsevier", "emerald", "generic",
                         "ieee", "nature", "sage", "springer", "wiley"):
            self.assertIn(expected, names)

    def test_check_all_adapter_signatures_valid(self):
        r = _run()
        out = json.loads(r.stdout)
        # Adapter contract regression: every adapter must pass signature check
        for a in out["adapters"]:
            self.assertTrue(a["ok"],
                            f"{a['name']} adapter failed: {a.get('errors')}")
            self.assertIn("domain", a)

    def test_check_registry_has_nine_prefixes(self):
        r = _run()
        out = json.loads(r.stdout)
        self.assertEqual(out["registry"]["count"], 9)
        # DOI prefixes covering UM's A-Z core subscriptions + extras
        for p in ("10.1002", "10.1007", "10.1016", "10.1021",
                  "10.1038", "10.1108", "10.1109", "10.1145",
                  "10.1177"):
            self.assertIn(p, out["registry"]["prefixes"])

    def test_check_summary_counts_match(self):
        r = _run()
        out = json.loads(r.stdout)
        self.assertEqual(out["summary"]["adapter_count"],
                         len(out["adapters"]))
        ok_count = sum(1 for a in out["adapters"] if a["ok"])
        self.assertEqual(out["summary"]["adapters_ok"], ok_count)

    def test_check_storage_state_reports_present_field(self):
        r = _run()
        out = json.loads(r.stdout)
        self.assertIn("present", out["storage_state"])

    def test_check_playwright_reports_installed_field(self):
        r = _run()
        out = json.loads(r.stdout)
        self.assertIn("installed", out["playwright"])


IDP_UM = _ROOT / ".claude/skills/institutional-access/scripts/idp_um.py"


class IdpUmTests(TestCase):
    def test_publishers_command_emits_known_entries(self):
        r = subprocess.run(
            [sys.executable, str(IDP_UM), "publishers"],
            capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["entityID"], "https://idp.um.edu.my/entity")
        self.assertEqual(out["openathens_org"], "80252862")
        for key in ("elsevier", "acm", "openathens"):
            self.assertIn(key, out["publishers"])

    def test_login_requires_credentials(self):
        # With no env / .env credentials, login must fail loud
        import os
        env = {k: v for k, v in os.environ.items()
               if k not in ("UM_USERNAME", "UM_PASSWORD")}
        # Point script at a non-repo cwd so its .env loader sees nothing
        r = subprocess.run(
            [sys.executable, str(IDP_UM), "login", "--publisher", "openathens"],
            capture_output=True, text=True, env=env, cwd="/tmp",
        )
        # Either credentials missing (expected) or playwright missing —
        # both are SystemExit non-zero. We just want the exit-loud guarantee.
        self.assertFalse(r.returncode == 0)


if __name__ == "__main__":
    sys.exit(run_tests(CheckCommandTests, IdpUmTests))
