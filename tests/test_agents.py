"""Sub-agent markdown sanity tests.

No YAML dependency — parses the frontmatter by hand.
"""

import re
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, run_tests

AGENT_DIR = Path(__file__).resolve().parent.parent / ".claude" / "agents"

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

EXPECTED_AGENTS = {
    # v0.46.4: SEEKER → Expedition rebrand. All 31 personas grouped into
    # 6 narrative phases (A-F). See README.md "The Expedition" section.

    # Phase A — The Expedition (deep-research pipeline)
    "scout", "cartographer", "chronicler", "surveyor",
    "synthesist", "architect", "inquisitor", "weaver",
    "visionary", "steward",
    # Phase B — The Workshop (manuscript subsystem)
    "verifier", "panel", "diviner",
    "drafter", "compositor", "reviser",
    # Phase C — The Tribunal (critical judgment). The community-facing
    # names are kept verbatim for these five — they're already idiomatic
    # in academic literature.
    "novelty-auditor", "publishability-judge", "red-team",
    "advocate", "peer-reviewer",
    # Phase D — The Laboratory (experimentation)
    "experimentalist", "curator", "funder",
    # Phase E — The Tournament (hypothesis evolution).
    # `ranker` kept (idiomatic Elo-tournament term).
    "ranker", "mutator",
    # Phase F — The Archive (knowledge layer)
    "librarian", "stylist",
    "diarist", "watchman", "indexer",
    # Phase G — Wide Research sub-agents (v0.53.6, one per task type).
    # Dispatched by wide.py to process N items in parallel.
    "wide-triage", "wide-read", "wide-rank",
    "wide-compare", "wide-survey", "wide-screen",
    # Phase H — Self-play debate (v0.56). PRO + CON + JUDGE for
    # high-stakes verdict sharpening.
    "debate-pro", "debate-con", "debate-judge",
    # Phase I — Quality judging (v0.92). One sub-agent that scores
    # another persona's output against its rubric.
    "quality-judge",
    # Phase J — Idea-tree generation (v0.153). Builds rooted hypothesis
    # trees the tournament's tree-aware ranker (v0.154/v0.155) consumes.
    "idea-tree-generator",
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

    def test_idea_tree_generator_cites_name_five(self):
        # v0.165 — defensive: idea-tree-generator MUST reference both
        # RESEARCHER.md and the "Name Five" principle (#6) so the
        # cross-ref doesn't silently rot away on future edits.
        body = (AGENT_DIR / "idea-tree-generator.md").read_text()
        self.assertIn("RESEARCHER.md", body,
                      "idea-tree-generator: missing RESEARCHER.md reference")
        self.assertIn("Name Five", body,
                      "idea-tree-generator: missing 'Name Five' principle ref")


if __name__ == "__main__":
    import sys
    sys.exit(run_tests(AgentFrontmatterTests))
