"""v0.185 — universal SKILL.md drift detector tests.

Auto-discovers all skill scripts, audits flag mentions vs SKILL.md.
WARNING-only: asserts the audit runs without crashing on any single
broken script. Does NOT assert "0 drift" — that's separate work.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from lib import skill_drift
from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parents[1]


class V0185UniversalDriftTests(TestCase):
    def test_discover_finds_many_scripts(self):
        scripts = skill_drift.discover_skill_scripts()
        self.assertTrue(
            len(scripts) >= 50,
            msg=f"expected >=50 scripts, found {len(scripts)}",
        )
        # Each entry is (skill_name, Path)
        for skill, path in scripts:
            self.assertTrue(isinstance(skill, str))
            self.assertTrue(isinstance(path, Path))
            self.assertTrue(path.suffix == ".py")

    def test_extract_flags_known_skill(self):
        # field-trends-analyzer has subcommand-style CLI with --rank-by etc.
        script = _REPO / ".claude" / "skills" / "field-trends-analyzer" / "scripts" / "trends.py"
        if not script.is_file():
            return  # skill removed — skip cleanly
        flags = skill_drift.extract_argparse_flags(script)
        # Expect at least some flags surface
        self.assertTrue(
            len(flags) >= 1,
            msg=f"expected at least 1 flag for field-trends-analyzer, got {flags}",
        )
        # Trivial flags excluded
        self.assertTrue("--help" not in flags)
        self.assertTrue("-h" not in flags)
        self.assertTrue("--project-id" not in flags)
        self.assertTrue("--format" not in flags)

    def test_audit_skill_returns_expected_keys(self):
        script = _REPO / ".claude" / "skills" / "field-trends-analyzer" / "scripts" / "trends.py"
        skill_dir = script.parent.parent
        if not script.is_file():
            return
        result = skill_drift.audit_skill(skill_dir, script)
        for key in (
            "skill", "script", "flags_in_help", "flags_in_md",
            "missing_in_md", "missing_in_help", "ok",
        ):
            self.assertTrue(key in result, msg=f"missing key {key!r} in {result}")
        self.assertTrue(isinstance(result["ok"], bool))

    def test_allowlist_silences_flag(self):
        # Use a tempdir-based mock skill
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / "fake-skill"
            scripts = skill_dir / "scripts"
            scripts.mkdir(parents=True)
            script = scripts / "tool.py"
            script.write_text(
                "import argparse\n"
                "p = argparse.ArgumentParser()\n"
                "p.add_argument('--internal-debug')\n"
                "p.add_argument('--public-flag')\n"
                "p.parse_args()\n"
            )
            # SKILL.md mentions --public-flag only
            (skill_dir / "SKILL.md").write_text("Use --public-flag for X.\n")

            # Without allowlist: --internal-debug missing
            r = skill_drift.audit_skill(skill_dir, script)
            self.assertTrue("--internal-debug" in r["missing_in_md"])

            # With allowlist: --internal-debug silenced
            (skill_dir / ".drift-allowlist.json").write_text(
                json.dumps({"undocumented_flags": ["--internal-debug"]})
            )
            r2 = skill_drift.audit_skill(skill_dir, script)
            self.assertTrue("--internal-debug" not in r2["missing_in_md"])
            self.assertTrue(r2["ok"])

    def test_audit_all_runs_to_completion(self):
        # The big one: walk every skill, never crash.
        report = skill_drift.audit_all()
        self.assertTrue(len(report) >= 50)
        for r in report:
            self.assertTrue("skill" in r)
            self.assertTrue("ok" in r)

    def test_broken_script_does_not_crash(self):
        # Simulate a broken script
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / "broken-skill"
            scripts = skill_dir / "scripts"
            scripts.mkdir(parents=True)
            script = scripts / "broken.py"
            script.write_text("raise RuntimeError('boom')\n")
            (skill_dir / "SKILL.md").write_text("docs\n")
            r = skill_drift.audit_skill(skill_dir, script)
            # Empty flags (--help failed) → no drift recorded
            self.assertTrue(r["flags_in_help"] == [])
            self.assertTrue(r["ok"])


if __name__ == "__main__":
    raise SystemExit(run_tests(V0185UniversalDriftTests))
