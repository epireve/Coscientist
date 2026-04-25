"""Dry-run harness for the manuscript-draft skill.

Drives draft.py subcommands via subprocess and verifies:
- All 5 venue templates load and have the required fields
- init creates manifest + outline.json + source.md in state=drafted
- Idempotency: same title+venue → same manuscript_id
- section updates source.md body and outline.json stats
- status prints a readable table
- CLI edge cases (missing args, unknown venue, unknown section)
- source.md produced by init is valid pandoc-style markdown

No LLM calls, no network. Pure filesystem.
"""

from tests import _shim  # noqa: F401

import json
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
_DRAFT = _ROOT / ".claude/skills/manuscript-draft/scripts/draft.py"
_TEMPLATES = _ROOT / ".claude/skills/manuscript-draft/templates"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_DRAFT), *args],
        capture_output=True, text=True,
    )


# --------------------------------------------------------------------------- #
# Template sanity                                                              #
# --------------------------------------------------------------------------- #

class TemplateTests(TestCase):
    """All 5 venue template JSON files are well-formed."""

    REQUIRED_FIELDS = {"venue", "full_name", "style", "word_limit", "sections"}
    SECTION_FIELDS = {"name", "heading", "ordinal", "target_words", "required", "notes"}

    def _load(self, venue: str) -> dict:
        path = _TEMPLATES / f"{venue}.json"
        self.assertTrue(path.exists(), f"Template {venue}.json missing")
        return json.loads(path.read_text())

    def _check_venue(self, venue: str):
        tmpl = self._load(venue)
        for f in self.REQUIRED_FIELDS:
            self.assertIn(f, tmpl, f"{venue}: missing top-level field {f!r}")
        self.assertTrue(len(tmpl["sections"]) > 0, f"{venue}: no sections")
        for s in tmpl["sections"]:
            for f in self.SECTION_FIELDS:
                self.assertIn(f, s, f"{venue}: section missing field {f!r}")
        ordinals = [s["ordinal"] for s in tmpl["sections"]]
        self.assertEqual(ordinals, sorted(ordinals), f"{venue}: ordinals not sorted")
        self.assertTrue(tmpl["word_limit"] > 0, f"{venue}: word_limit must be > 0")

    def test_imrad(self):    self._check_venue("imrad")
    def test_neurips(self):  self._check_venue("neurips")
    def test_acl(self):      self._check_venue("acl")
    def test_nature(self):   self._check_venue("nature")
    def test_thesis(self):   self._check_venue("thesis")

    def test_venues_subcommand_lists_all_five(self):
        r = _run("venues")
        self.assertEqual(r.returncode, 0)
        for v in ("imrad", "neurips", "acl", "nature", "thesis"):
            self.assertIn(v, r.stdout)


# --------------------------------------------------------------------------- #
# init                                                                         #
# --------------------------------------------------------------------------- #

class DraftInitTests(TestCase):

    def test_init_creates_artifact_files(self):
        with isolated_cache():
            r = _run("init", "--title", "My Test Paper", "--venue", "neurips")
            self.assertEqual(r.returncode, 0, r.stderr)
            mid = r.stdout.strip()
            self.assertTrue(mid, "init must print manuscript_id")

            from lib.cache import cache_root
            art_dir = cache_root() / "manuscripts" / mid
            self.assertTrue((art_dir / "manifest.json").exists())
            self.assertTrue((art_dir / "outline.json").exists())
            self.assertTrue((art_dir / "source.md").exists())

    def test_init_manifest_state_is_drafted(self):
        with isolated_cache():
            r = _run("init", "--title", "State Test", "--venue", "imrad")
            mid = r.stdout.strip()
            from lib.cache import cache_root
            m = json.loads((cache_root() / "manuscripts" / mid / "manifest.json").read_text())
            self.assertEqual(m["state"], "drafted")
            self.assertEqual(m["kind"], "manuscript")

    def test_init_outline_has_correct_section_count(self):
        with isolated_cache():
            r = _run("init", "--title", "Outline Count", "--venue", "acl")
            mid = r.stdout.strip()
            from lib.cache import cache_root
            outline = json.loads((cache_root() / "manuscripts" / mid / "outline.json").read_text())
            tmpl = json.loads((_TEMPLATES / "acl.json").read_text())
            self.assertEqual(len(outline["sections"]), len(tmpl["sections"]))

    def test_init_all_sections_start_as_placeholder(self):
        with isolated_cache():
            r = _run("init", "--title", "All Placeholders", "--venue", "nature")
            mid = r.stdout.strip()
            from lib.cache import cache_root
            outline = json.loads((cache_root() / "manuscripts" / mid / "outline.json").read_text())
            for s in outline["sections"]:
                self.assertEqual(s["status"], "placeholder",
                                 f"section {s['name']} status should be placeholder")

    def test_init_source_md_contains_all_headings(self):
        with isolated_cache():
            r = _run("init", "--title", "Heading Check", "--venue", "imrad")
            mid = r.stdout.strip()
            from lib.cache import cache_root
            source = (cache_root() / "manuscripts" / mid / "source.md").read_text()
            tmpl = json.loads((_TEMPLATES / "imrad.json").read_text())
            for s in tmpl["sections"]:
                self.assertIn(f"## {s['heading']}", source,
                              f"source.md missing heading {s['heading']!r}")

    def test_init_source_md_has_yaml_frontmatter(self):
        with isolated_cache():
            r = _run("init", "--title", "YAML Test", "--venue", "thesis")
            mid = r.stdout.strip()
            from lib.cache import cache_root
            source = (cache_root() / "manuscripts" / mid / "source.md").read_text()
            self.assertTrue(source.startswith("---\n"), "source.md must start with YAML frontmatter")
            self.assertIn("manuscript_id:", source)
            self.assertIn("title:", source)


# --------------------------------------------------------------------------- #
# Idempotency                                                                  #
# --------------------------------------------------------------------------- #

class IdempotencyTests(TestCase):

    def test_same_title_venue_gives_same_id(self):
        with isolated_cache():
            r1 = _run("init", "--title", "Stable ID Paper", "--venue", "neurips")
            r2 = _run("init", "--title", "Stable ID Paper", "--venue", "neurips",
                      "--force")
            self.assertEqual(r1.stdout.strip(), r2.stdout.strip())

    def test_different_venue_gives_different_id(self):
        with isolated_cache():
            r1 = _run("init", "--title", "Same Title", "--venue", "neurips")
            r2 = _run("init", "--title", "Same Title", "--venue", "acl")
            self.assertTrue(r1.stdout.strip() != r2.stdout.strip(),
                            "different venues should give different manuscript_ids")

    def test_reinit_without_force_errors(self):
        with isolated_cache():
            _run("init", "--title", "Exists Already", "--venue", "imrad")
            r = _run("init", "--title", "Exists Already", "--venue", "imrad")
            self.assertTrue(r.returncode != 0, "re-init without --force should fail")
            self.assertIn("--force", r.stderr)


# --------------------------------------------------------------------------- #
# section                                                                      #
# --------------------------------------------------------------------------- #

class DraftSectionTests(TestCase):

    def _init(self, title="Section Test", venue="imrad") -> str:
        with isolated_cache() as _:
            pass
        with isolated_cache():
            r = _run("init", "--title", title, "--venue", venue)
            return r.stdout.strip()

    def test_section_updates_source_md(self):
        with isolated_cache():
            r = _run("init", "--title", "Section Update", "--venue", "imrad")
            mid = r.stdout.strip()
            body = "This is the introduction body. We show that X is true [@smith2020]."
            r2 = _run("section", "--manuscript-id", mid,
                      "--section", "introduction", "--text", body)
            self.assertEqual(r2.returncode, 0, r2.stderr)
            from lib.cache import cache_root
            source = (cache_root() / "manuscripts" / mid / "source.md").read_text()
            self.assertIn("We show that X is true", source)
            self.assertNotIn("[PLACEHOLDER", source.split("## Introduction")[1].split("##")[0])

    def test_section_updates_outline_stats(self):
        with isolated_cache():
            r = _run("init", "--title", "Outline Stats", "--venue", "imrad")
            mid = r.stdout.strip()
            body = "Word " * 50  # 50 words
            _run("section", "--manuscript-id", mid,
                 "--section", "introduction", "--text", body)
            from lib.cache import cache_root
            outline = json.loads(
                (cache_root() / "manuscripts" / mid / "outline.json").read_text()
            )
            intro = next(s for s in outline["sections"] if s["name"] == "introduction")
            self.assertTrue(intro["word_count"] > 0, "word_count must be > 0 after section draft")
            self.assertEqual(intro["status"], "drafted")

    def test_section_extracts_cite_keys(self):
        with isolated_cache():
            r = _run("init", "--title", "Cite Key Test", "--venue", "imrad")
            mid = r.stdout.strip()
            body = "See [@vaswani2017] and [@devlin2019bert] for details."
            _run("section", "--manuscript-id", mid,
                 "--section", "introduction", "--text", body)
            from lib.cache import cache_root
            outline = json.loads(
                (cache_root() / "manuscripts" / mid / "outline.json").read_text()
            )
            intro = next(s for s in outline["sections"] if s["name"] == "introduction")
            self.assertIn("vaswani2017", intro["cite_keys"])
            self.assertIn("devlin2019bert", intro["cite_keys"])

    def test_section_status_revised_flag(self):
        with isolated_cache():
            r = _run("init", "--title", "Status Flag", "--venue", "imrad")
            mid = r.stdout.strip()
            _run("section", "--manuscript-id", mid,
                 "--section", "introduction", "--text", "first draft")
            _run("section", "--manuscript-id", mid,
                 "--section", "introduction", "--text", "revised draft",
                 "--status", "revised")
            from lib.cache import cache_root
            outline = json.loads(
                (cache_root() / "manuscripts" / mid / "outline.json").read_text()
            )
            intro = next(s for s in outline["sections"] if s["name"] == "introduction")
            self.assertEqual(intro["status"], "revised")

    def test_section_unknown_section_errors(self):
        with isolated_cache():
            r = _run("init", "--title", "Bad Section", "--venue", "imrad")
            mid = r.stdout.strip()
            r2 = _run("section", "--manuscript-id", mid,
                      "--section", "nonexistent_section", "--text", "body")
            self.assertTrue(r2.returncode != 0, "unknown section should fail")

    def test_section_unknown_manuscript_errors(self):
        with isolated_cache():
            r = _run("section", "--manuscript-id", "does_not_exist_000000",
                     "--section", "introduction", "--text", "body")
            self.assertTrue(r.returncode != 0, "unknown manuscript_id should fail")


# --------------------------------------------------------------------------- #
# status                                                                       #
# --------------------------------------------------------------------------- #

class DraftStatusTests(TestCase):

    def test_status_prints_table_header(self):
        with isolated_cache():
            r = _run("init", "--title", "Status Print", "--venue", "neurips")
            mid = r.stdout.strip()
            r2 = _run("status", "--manuscript-id", mid)
            self.assertEqual(r2.returncode, 0, r2.stderr)
            self.assertIn("section", r2.stdout)
            self.assertIn("status", r2.stdout)
            self.assertIn("words", r2.stdout)

    def test_status_shows_section_names(self):
        with isolated_cache():
            r = _run("init", "--title", "Status Sections", "--venue", "acl")
            mid = r.stdout.strip()
            r2 = _run("status", "--manuscript-id", mid)
            self.assertIn("introduction", r2.stdout)
            self.assertIn("abstract", r2.stdout)

    def test_status_updates_after_section_draft(self):
        with isolated_cache():
            r = _run("init", "--title", "Status After Draft", "--venue", "imrad")
            mid = r.stdout.strip()
            _run("section", "--manuscript-id", mid,
                 "--section", "abstract", "--text", "Word " * 100)
            r2 = _run("status", "--manuscript-id", mid)
            self.assertIn("drafted", r2.stdout)

    def test_status_unknown_manuscript_errors(self):
        with isolated_cache():
            r = _run("status", "--manuscript-id", "ghost_000000")
            self.assertTrue(r.returncode != 0, "unknown manuscript_id should fail")


# --------------------------------------------------------------------------- #
# CLI edge cases                                                               #
# --------------------------------------------------------------------------- #

class CliEdgeTests(TestCase):

    def test_init_requires_title(self):
        r = _run("init", "--venue", "imrad")
        self.assertTrue(r.returncode != 0, "init without --title should fail")
        self.assertIn("--title", r.stderr)

    def test_init_requires_venue(self):
        r = _run("init", "--title", "No Venue")
        self.assertTrue(r.returncode != 0, "init without --venue should fail")

    def test_init_rejects_unknown_venue(self):
        r = _run("init", "--title", "Bad Venue", "--venue", "plos-one")
        self.assertTrue(r.returncode != 0, "unknown venue should fail")

    def test_section_requires_manuscript_id(self):
        r = _run("section", "--section", "introduction", "--text", "body")
        self.assertTrue(r.returncode != 0, "section without --manuscript-id should fail")

    def test_help_lists_subcommands(self):
        r = _run("--help")
        self.assertEqual(r.returncode, 0)
        for sub in ("init", "section", "status", "venues"):
            self.assertIn(sub, r.stdout)


if __name__ == "__main__":
    sys.exit(run_tests(
        TemplateTests,
        DraftInitTests,
        IdempotencyTests,
        DraftSectionTests,
        DraftStatusTests,
        CliEdgeTests,
    ))
