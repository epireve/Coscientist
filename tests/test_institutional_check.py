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
        # Current registry: 6 publishers
        for expected in ("acs", "elsevier", "ieee", "nature",
                         "springer", "wiley"):
            self.assertIn(expected, names)

    def test_check_all_adapter_signatures_valid(self):
        r = _run()
        out = json.loads(r.stdout)
        # Adapter contract regression: every adapter must pass signature check
        for a in out["adapters"]:
            self.assertTrue(a["ok"],
                            f"{a['name']} adapter failed: {a.get('errors')}")
            self.assertIn("domain", a)

    def test_check_registry_has_six_prefixes(self):
        r = _run()
        out = json.loads(r.stdout)
        self.assertEqual(out["registry"]["count"], 6)
        # DOI prefixes are stable
        for p in ("10.1002", "10.1007", "10.1016", "10.1021",
                  "10.1038", "10.1109"):
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


if __name__ == "__main__":
    sys.exit(run_tests(CheckCommandTests))
