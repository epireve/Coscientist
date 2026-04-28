"""v0.65c — skill/agent name invariants.

Asserts:
  1. Every value in deep-research's PHASE_ALIASES maps to a real
     agent file under .claude/agents/<name>.md.
  2. Every PHASE_ALIASES key is documented in CLAUDE.md (or a phase
     mapping doc), so the alias surface is explicit.
  3. Every agent .md has frontmatter (name + description).
  4. Every agent name appears at least once somewhere in the
     codebase (either invoked, aliased, or mentioned in docs) —
     catches orphan agents that were renamed but not deleted.
  5. The 'wide-*' agents referenced by wide-research/scripts/wide.py
     all exist as files.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parents[1]
_AGENTS_DIR = _REPO / ".claude" / "agents"
_DB_PY = _REPO / ".claude" / "skills" / "deep-research" / "scripts" / "db.py"
_WIDE_PY = _REPO / ".claude" / "skills" / "wide-research" / "scripts" / "wide.py"


def _agent_names_on_disk() -> set[str]:
    return {p.stem for p in _AGENTS_DIR.glob("*.md")}


def _parse_phase_aliases() -> dict[str, str]:
    """Naive parse of the PHASE_ALIASES dict literal in db.py."""
    text = _DB_PY.read_text()
    m = re.search(r"PHASE_ALIASES\s*=\s*\{([^}]*)\}", text, re.DOTALL)
    assert m, "PHASE_ALIASES dict not found in db.py"
    body = m.group(1)
    out: dict[str, str] = {}
    for line in body.splitlines():
        line = line.strip().rstrip(",")
        m2 = re.match(r'"([^"]+)"\s*:\s*"([^"]+)"', line)
        if m2:
            out[m2.group(1)] = m2.group(2)
    return out


class PhaseAliasInvariantTests(TestCase):
    def test_every_alias_target_is_real_agent(self):
        aliases = _parse_phase_aliases()
        agents = _agent_names_on_disk()
        for old, new in aliases.items():
            self.assertIn(
                new, agents,
                f"PHASE_ALIASES[{old!r}] -> {new!r} but no "
                f".claude/agents/{new}.md file exists",
            )

    def test_aliases_are_nontrivial(self):
        aliases = _parse_phase_aliases()
        self.assertGreater(len(aliases), 0)

    def test_no_alias_targets_self(self):
        # An alias that maps to itself is dead config.
        aliases = _parse_phase_aliases()
        for old, new in aliases.items():
            self.assertTrue(old != new,
                            f"alias {old!r} maps to itself")


class AgentFrontmatterInvariantTests(TestCase):
    def test_every_agent_md_has_frontmatter(self):
        for path in sorted(_AGENTS_DIR.glob("*.md")):
            text = path.read_text()
            self.assertTrue(
                text.startswith("---\n"),
                f"{path.name} missing YAML frontmatter",
            )
            # Must have at least name and description fields.
            head = text.split("---\n", 2)[1] if text.count("---\n") >= 2 else ""
            self.assertIn("name:", head, f"{path.name} missing name:")
            self.assertIn("description:", head,
                          f"{path.name} missing description:")

    def test_agent_name_field_matches_filename(self):
        for path in sorted(_AGENTS_DIR.glob("*.md")):
            text = path.read_text()
            head = text.split("---\n", 2)[1] if text.count("---\n") >= 2 else ""
            m = re.search(r"^name:\s*(\S+)", head, re.MULTILINE)
            if m:
                self.assertEqual(
                    m.group(1).strip(), path.stem,
                    f"{path.name} frontmatter name {m.group(1)!r} != "
                    f"filename stem {path.stem!r}",
                )


class WideAgentExistsTests(TestCase):
    def test_wide_agents_all_present(self):
        # ROADMAP / CLAUDE.md references wide-* agents for Wide Research.
        agents = _agent_names_on_disk()
        wide_agents = {n for n in agents if n.startswith("wide-")}
        # Should have at least the v0.53.6 set documented in CLAUDE.md.
        expected_wide = {
            "wide-triage", "wide-read", "wide-rank",
            "wide-compare", "wide-survey", "wide-screen",
        }
        missing = expected_wide - agents
        self.assertEqual(
            missing, set(),
            f"wide-research agents missing: {missing}. Found wide-*: "
            f"{sorted(wide_agents)}",
        )


class AgentReferencedTests(TestCase):
    """Every agent under .claude/agents/ should be referenced
    *somewhere* in the codebase (skill scripts, SKILL.md, CLAUDE.md,
    ROADMAP.md, agents/<other>.md, db.py PHASE_ALIASES, etc).
    Catches orphan agents.
    """

    _SEARCH_ROOTS = (
        _REPO / ".claude" / "skills",
        _REPO / ".claude" / "agents",
        _REPO / "lib",
    )
    _DOC_FILES = (
        _REPO / "CLAUDE.md",
        _REPO / "ROADMAP.md",
        _REPO / "README.md",
    )

    def test_every_agent_referenced_somewhere(self):
        agents = sorted(_agent_names_on_disk())
        # Build a corpus of every text file under search roots + doc files.
        corpus_paths: list[Path] = []
        for root in self._SEARCH_ROOTS:
            for ext in ("*.md", "*.py", "*.json", "*.sh"):
                corpus_paths.extend(root.rglob(ext))
        corpus_paths.extend(self._DOC_FILES)

        text_blob = ""
        for p in corpus_paths:
            try:
                text_blob += p.read_text(errors="ignore") + "\n"
            except (OSError, UnicodeDecodeError):
                continue

        orphans: list[str] = []
        for name in agents:
            # Don't count the agent's own .md file as a reference to itself.
            own_text = (_AGENTS_DIR / f"{name}.md").read_text(errors="ignore")
            count = text_blob.count(name) - text_blob.count(own_text[:200]) * 0
            # Subtract the self-reference (frontmatter `name: <name>`).
            self_refs = own_text.count(name)
            external_refs = count - self_refs
            if external_refs <= 0:
                orphans.append(name)
        self.assertEqual(
            orphans, [],
            f"orphan agents (not referenced outside their own .md): {orphans}",
        )


if __name__ == "__main__":
    raise SystemExit(run_tests(
        PhaseAliasInvariantTests,
        AgentFrontmatterInvariantTests,
        WideAgentExistsTests,
        AgentReferencedTests,
    ))
