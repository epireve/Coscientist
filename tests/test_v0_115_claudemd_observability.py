"""v0.115 — CLAUDE.md observability stack documentation tests."""
from __future__ import annotations

from pathlib import Path

from tests.harness import TestCase, run_tests


_REPO = Path(__file__).resolve().parents[1]
_CLAUDE_MD = _REPO / "CLAUDE.md"


class ObservabilityDocsTests(TestCase):
    def test_claude_md_exists(self):
        self.assertTrue(_CLAUDE_MD.exists())

    def test_recent_landings_includes_v0_93_through_v0_114(self):
        text = _CLAUDE_MD.read_text()
        for marker in ("v0.89", "v0.93", "v0.97",
                        "v0.106", "v0.110", "v0.114"):
            self.assertIn(marker, text,
                           f"recent-landings missing {marker}")

    def test_observability_section_exists(self):
        text = _CLAUDE_MD.read_text()
        self.assertIn("## Observability stack", text)

    def test_observability_lists_three_tables(self):
        text = _CLAUDE_MD.read_text()
        for table in ("traces", "spans", "span_events",
                       "agent_quality"):
            self.assertIn(f"`{table}`", text)

    def test_observability_lists_span_kinds(self):
        text = _CLAUDE_MD.read_text()
        # Must include the seven span kinds
        for kind in ("phase", "sub-agent", "tool-call", "gate",
                     "persist", "harvest", "other"):
            self.assertIn(f"`{kind}`", text)

    def test_observability_mentions_key_modules(self):
        text = _CLAUDE_MD.read_text()
        # Either dotted (lib.X) or path (lib/X.py) form acceptable
        for mod_short in ("health", "trace_render",
                           "trace_status", "agent_quality",
                           "persona_schema", "gate_trace"):
            self.assertTrue(
                f"lib.{mod_short}" in text
                or f"lib/{mod_short}.py" in text
                or f"lib/{mod_short}`" in text,
                f"missing reference to lib/{mod_short}",
            )

    def test_observability_mentions_env_vars(self):
        text = _CLAUDE_MD.read_text()
        self.assertIn("COSCIENTIST_TRACE_DB", text)
        self.assertIn("COSCIENTIST_TRACE_ID", text)

    def test_invariants_listed(self):
        text = _CLAUDE_MD.read_text()
        # Best-effort + pure stdlib + WAL mode are the invariants
        self.assertIn("Best-effort", text)
        self.assertIn("stdlib", text)
        self.assertIn("WAL mode", text)

    def test_runbook_referenced(self):
        text = _CLAUDE_MD.read_text()
        self.assertIn("SMOKE-TEST-RUNBOOK", text)


if __name__ == "__main__":
    raise SystemExit(run_tests(ObservabilityDocsTests))
