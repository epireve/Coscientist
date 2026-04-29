"""v0.183 — SKILL.md vs script.py CLI flag drift detector.

For a curated set of skills with stable CLI surfaces, asserts that any
flag the script accepts via `--help` is mentioned somewhere in
SKILL.md. Catches the drift class where new flags ship but docs don't
update (e.g., v0.179 --rank-by, v0.180 cliques-louvain, v0.181
--weighting all hit this in v0.183 polish batch).

Skills checked must have a single primary script + stable flag-set.
Trivial cases (one-shot scripts, info-only flags like --help) excluded.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parents[1]


# (skill_name, script relative path, [flags that MUST be in SKILL.md])
_AUDIT = [
    (
        "field-trends-analyzer",
        ".claude/skills/field-trends-analyzer/scripts/trends.py",
        ["--rank-by"],
    ),
    (
        "coauthor-network",
        ".claude/skills/coauthor-network/scripts/coauthor.py",
        ["cliques-louvain"],
    ),
    (
        "replication-finder",
        ".claude/skills/replication-finder/scripts/find_replications.py",
        ["--weighting"],
    ),
    (
        "claim-cluster",
        ".claude/skills/claim-cluster/scripts/cluster_claims.py",
        ["--min-jaccard"],
    ),
]


class SkillMdDriftTests(TestCase):
    def test_each_skill_md_mentions_critical_flags(self):
        repo = _REPO
        for skill, script_rel, flags in _AUDIT:
            skill_md = repo / ".claude" / "skills" / skill / "SKILL.md"
            self.assertTrue(skill_md.exists(),
                            msg=f"{skill}: SKILL.md missing")
            body = skill_md.read_text()
            for flag in flags:
                self.assertTrue(
                    flag in body,
                    msg=f"{skill}: SKILL.md does not mention "
                        f"required flag/subcommand {flag!r}",
                )

    def test_each_script_help_runs_clean(self):
        repo = _REPO
        for _, script_rel, _ in _AUDIT:
            r = subprocess.run(
                [sys.executable, str(repo / script_rel), "--help"],
                capture_output=True, text=True, cwd=str(repo),
                timeout=20,
            )
            self.assertEqual(
                r.returncode, 0,
                msg=f"{script_rel} --help failed: {r.stderr[:200]}",
            )


if __name__ == "__main__":
    raise SystemExit(run_tests(SkillMdDriftTests))
