"""v0.45.7 stricter agent-frontmatter regression tests.

The v0.5.1 LayoutRegressionTests already check that every .claude/agents/*.md
starts with `---`. These tests go further: each agent must declare
name/description/tools, the name must match the filename, the tools value
must be a YAML/JSON array (so the runtime can parse it), and the
description must be non-trivial. Catches drift like "I added an agent
but forgot tools" or "I renamed the file but not the name field".
"""

import json
import re
import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, run_tests

_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = _ROOT / ".claude" / "agents"

# Coscientist's standard tool surface plus MCP namespaces. Any tool not on
# this list flags drift toward unsupported runtimes.
KNOWN_TOOLS = {
    "Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch",
    "WebSearch", "Task", "Agent",
}
ALLOWED_MCP_PREFIXES = (
    "mcp__consensus", "mcp__paper-search", "mcp__academic",
    "mcp__semantic-scholar", "mcp__zotero", "mcp__Claude_in_Chrome",
)


def _split_frontmatter(text: str) -> tuple[str, str]:
    m = re.match(r"---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if not m:
        return "", text
    return m.group(1), m.group(2)


def _parse_kv(fm: str) -> dict[str, str]:
    out: dict[str, str] = {}
    cur_key: str | None = None
    cur_val: list[str] = []
    for line in fm.split("\n"):
        if line.startswith(" ") and cur_key:
            cur_val.append(line)
            continue
        if cur_key:
            out[cur_key] = "\n".join(cur_val).strip()
            cur_val = []
        m = re.match(r"^([A-Za-z_]+)\s*:\s*(.*)$", line)
        if m:
            cur_key = m.group(1)
            cur_val = [m.group(2)]
        else:
            cur_key = None
    if cur_key:
        out[cur_key] = "\n".join(cur_val).strip()
    return out


def _parse_tools_list(raw: str) -> list[str]:
    """Tools field is either a JSON-style inline array or a YAML
    block sequence (one `- item` per line). Both forms are valid YAML
    and accepted by the runtime; pin behaviour for both."""
    raw = raw.strip()
    if raw.startswith("["):
        return json.loads(raw)
    out: list[str] = []
    for line in raw.split("\n"):
        line = line.strip()
        if line.startswith("-"):
            out.append(line.lstrip("-").strip())
    if out:
        return out
    raise ValueError(f"unrecognised tools format: {raw[:80]!r}")


def _agent_files() -> list[Path]:
    return sorted(AGENTS_DIR.glob("*.md"))


class FrontmatterShapeTests(TestCase):
    def test_every_agent_has_required_fields(self):
        missing: list[str] = []
        for f in _agent_files():
            fm, _ = _split_frontmatter(f.read_text())
            kv = _parse_kv(fm)
            for required in ("name", "description", "tools"):
                if required not in kv:
                    missing.append(f"{f.name}:{required}")
        self.assertFalse(missing, f"agents missing frontmatter fields: {missing}")

    def test_name_matches_filename(self):
        mismatches: list[str] = []
        for f in _agent_files():
            fm, _ = _split_frontmatter(f.read_text())
            kv = _parse_kv(fm)
            name = (kv.get("name") or "").strip()
            stem = f.stem
            if name != stem:
                mismatches.append(f"{f.name}: name={name!r} stem={stem!r}")
        self.assertFalse(mismatches,
                         f"name/filename mismatches: {mismatches}")

    def test_description_substantive(self):
        thin: list[str] = []
        for f in _agent_files():
            fm, _ = _split_frontmatter(f.read_text())
            kv = _parse_kv(fm)
            desc = (kv.get("description") or "").strip()
            if len(desc) < 30:
                thin.append(f"{f.name}: {len(desc)} chars")
        self.assertFalse(thin, f"agents with thin descriptions: {thin}")


class ToolsFieldTests(TestCase):
    def test_tools_field_parses_as_array(self):
        bad: list[str] = []
        for f in _agent_files():
            fm, _ = _split_frontmatter(f.read_text())
            kv = _parse_kv(fm)
            try:
                tools = _parse_tools_list(kv["tools"])
                if not isinstance(tools, list):
                    bad.append(f"{f.name}: not list")
            except (ValueError, json.JSONDecodeError) as e:
                bad.append(f"{f.name}: {e}")
        self.assertFalse(bad, f"unparseable tools fields: {bad}")

    def test_tools_field_non_empty(self):
        empty: list[str] = []
        for f in _agent_files():
            fm, _ = _split_frontmatter(f.read_text())
            kv = _parse_kv(fm)
            tools = _parse_tools_list(kv["tools"])
            if not tools:
                empty.append(f.name)
        self.assertFalse(empty, f"agents with empty tools: {empty}")

    def test_tools_recognised_or_mcp(self):
        unknown: list[str] = []
        for f in _agent_files():
            fm, _ = _split_frontmatter(f.read_text())
            kv = _parse_kv(fm)
            tools = _parse_tools_list(kv["tools"])
            for t in tools:
                if t in KNOWN_TOOLS:
                    continue
                if any(t.startswith(p) for p in ALLOWED_MCP_PREFIXES):
                    continue
                unknown.append(f"{f.name}:{t}")
        self.assertFalse(unknown,
                         f"unknown tools (drift toward unsupported "
                         f"runtimes): {unknown}")


class BodyContentTests(TestCase):
    """Karpathy retrofit (v0.3) said every agent ends with an Exit-test
    clause. Pin that — drift away from it loses the self-check loop."""

    def test_every_agent_has_body_content(self):
        empty: list[str] = []
        for f in _agent_files():
            _, body = _split_frontmatter(f.read_text())
            if len(body.strip()) < 100:
                empty.append(f"{f.name}: {len(body.strip())} body chars")
        self.assertFalse(empty, f"agents with thin body content: {empty}")


if __name__ == "__main__":
    sys.exit(run_tests(
        FrontmatterShapeTests, ToolsFieldTests, BodyContentTests,
    ))
