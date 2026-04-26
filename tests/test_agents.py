"""Sub-agent markdown sanity tests.

No YAML dependency — parses the frontmatter by hand.
"""

from tests import _shim  # noqa: F401

import re
from pathlib import Path

from tests.harness import TestCase, run_tests

AGENT_DIR = Path(__file__).resolve().parent.parent / ".claude" / "agents"

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

EXPECTED_AGENTS = {
    # Deep-research pipeline
    "social", "grounder", "historian", "gaper",
    "vision", "theorist", "rude", "synthesizer",
    "thinker", "scribe",
    # A5 critical-judgment
    "novelty-auditor", "publishability-judge", "red-team",
    # A1 manuscript subsystem
    "manuscript-auditor", "manuscript-critic", "manuscript-reflector",
    "manuscript-drafter", "manuscript-formatter", "manuscript-reviser",
    # A2 reference agent
    "reference-agent",
    # A3 writing style
    "writing-style",
    # A4 personal knowledge layer
    "research-journal", "project-dashboard", "cross-project-memory",
    # Tier B tournament + evolution
    "ranker", "evolver",
    # Tier B standalone adversarial
    "idea-attacker",
}


def _parse_frontmatter(text: str) -> dict:
    """Lightweight YAML-ish parser sufficient for our simple frontmatter."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    body = m.group(1)
    out: dict[str, object] = {}
    current_key: str | None = None
    for line in body.splitlines():
        if not line.strip():
            continue
        if line.startswith(" ") or line.startswith("\t"):
            # continuation (list-ish), skip for smoke purposes
            continue
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val.startswith("[") and val.endswith("]"):
                items = [i.strip().strip('"\'') for i in val[1:-1].split(",") if i.strip()]
                out[key] = items
            else:
                out[key] = val.strip('"\'') if val else ""
            current_key = key
    return out


class AgentFrontmatterTests(TestCase):
    def test_all_expected_agents_present(self):
        found = {p.stem for p in AGENT_DIR.glob("*.md")}
        for name in EXPECTED_AGENTS:
            self.assertIn(name, found, f"agent {name} missing")

    def test_each_agent_has_name_and_description(self):
        for p in AGENT_DIR.glob("*.md"):
            text = p.read_text()
            fm = _parse_frontmatter(text)
            self.assertTrue(fm, f"{p.name}: no frontmatter parsed")
            self.assertIn("name", fm, f"{p.name}: missing name")
            self.assertIn("description", fm, f"{p.name}: missing description")

    def test_name_matches_filename(self):
        for p in AGENT_DIR.glob("*.md"):
            fm = _parse_frontmatter(p.read_text())
            self.assertEqual(
                fm.get("name"), p.stem,
                f"{p.name}: frontmatter name != filename stem",
            )

    def test_body_references_researcher_md(self):
        # Every agent should reference the shared principles doc somehow
        for p in AGENT_DIR.glob("*.md"):
            body = p.read_text()
            self.assertIn("RESEARCHER.md", body,
                          f"{p.name}: no reference to RESEARCHER.md")

    def test_body_has_exit_test(self):
        # Karpathy-style exit-test clause
        for p in AGENT_DIR.glob("*.md"):
            body = p.read_text().lower()
            has_test = ("exit test" in body) or ("## what \"done\" looks like" in body)
            self.assertTrue(has_test, f"{p.name}: no exit test / done clause")

    def test_no_agents_outside_expected(self):
        found = {p.stem for p in AGENT_DIR.glob("*.md")}
        unexpected = found - EXPECTED_AGENTS
        self.assertFalse(unexpected, f"unexpected agents: {unexpected}")


if __name__ == "__main__":
    import sys
    sys.exit(run_tests(AgentFrontmatterTests))
