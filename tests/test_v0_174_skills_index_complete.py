"""v0.174 — SKILLS.md regression: new C-section graph-analytics skills.

Asserts the 5 skills shipped through v0.173 in the C-section
(replication-finder, coauthor-network, funding-graph, claim-cluster,
citation-decay) are auto-discovered and surfaced in SKILLS.md.
"""
from __future__ import annotations

from pathlib import Path

from lib.skill_index import discover_skills, render_index
from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parents[1]
_SKILLS_ROOT = _REPO / ".claude" / "skills"
_SKILLS_MD = _REPO / "SKILLS.md"

_NEW_SKILLS = (
    "replication-finder",
    "coauthor-network",
    "funding-graph",
    "claim-cluster",
    "citation-decay",
)


class V0174NewSkillsPresentTests(TestCase):
    def test_all_five_new_skills_in_skills_md(self):
        text = _SKILLS_MD.read_text()
        for name in _NEW_SKILLS:
            self.assertIn(
                f"`{name}`", text,
                f"new skill {name!r} missing from SKILLS.md — "
                "regenerate via `uv run python -m lib.skill_index "
                "generate > SKILLS.md`",
            )

    def test_total_skill_count_at_least_60(self):
        entries = discover_skills(_SKILLS_ROOT)
        self.assertGreaterEqual(
            len(entries), 60,
            f"only {len(entries)} skills discovered",
        )

    def test_skills_md_no_broken_markdown(self):
        text = _SKILLS_MD.read_text()
        # Basic format — heading + table header present.
        self.assertIn("# Skills index", text)
        self.assertIn("| # | Skill | Description |", text)

    def test_each_new_skill_has_description_and_when_to_use(self):
        entries = {e.name: e for e in discover_skills(_SKILLS_ROOT)}
        for name in _NEW_SKILLS:
            self.assertIn(name, entries, f"{name} not discovered")
            e = entries[name]
            self.assertTrue(e.description, f"{name} missing description")
            self.assertTrue(e.when_to_use, f"{name} missing when_to_use")

    def test_skill_index_idempotent(self):
        entries = discover_skills(_SKILLS_ROOT)
        a = render_index(entries)
        b = render_index(entries)
        self.assertEqual(a, b, "render_index not idempotent")

    def test_new_skills_auto_discovered_no_manual_registration(self):
        # Verify the discovery path — each new skill has SKILL.md
        # under .claude/skills/<name>/ and is picked up by walking
        # the directory, not by any registry file.
        for name in _NEW_SKILLS:
            skill_md = _SKILLS_ROOT / name / "SKILL.md"
            self.assertTrue(
                skill_md.exists(),
                f"{name}/SKILL.md missing — auto-discovery requires it",
            )


if __name__ == "__main__":
    run_tests(V0174NewSkillsPresentTests)
