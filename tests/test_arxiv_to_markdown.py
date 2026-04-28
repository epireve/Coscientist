"""v0.45.5 tests for arxiv-to-markdown fetch.py.

arxiv2md (the upstream HTML extractor) is mocked via a fake module
injected into sys.modules. The skill's job is to take the extractor's
output and write it correctly into a paper artifact — that contract
is what we pin here.
"""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
FETCH = _ROOT / ".claude/skills/arxiv-to-markdown/scripts/fetch.py"


def _import_fetch():
    """Import fetch.py as a module so we can call run() directly."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("a2m_fetch", FETCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _install_fake_arxiv2md(content: str, meta: dict):
    """Stub the arxiv2md module so fetch.run() doesn't hit the network."""
    import types
    fake = types.ModuleType("arxiv2md")

    async def ingest_paper(**kwargs):
        return (
            SimpleNamespace(content=content),
            meta,
        )

    fake.ingest_paper = ingest_paper
    sys.modules["arxiv2md"] = fake
    return fake


def _uninstall_fake_arxiv2md():
    sys.modules.pop("arxiv2md", None)


# ---------------- normalize_arxiv_id ----------------

class NormalizeArxivIdTests(TestCase):
    def test_bare_id_passes_through(self):
        m = _import_fetch()
        self.assertEqual(m.normalize_arxiv_id("2401.12345"), "2401.12345")

    def test_url_extracts_id(self):
        m = _import_fetch()
        self.assertEqual(
            m.normalize_arxiv_id("https://arxiv.org/abs/2401.12345"),
            "2401.12345",
        )

    def test_unparseable_errors(self):
        m = _import_fetch()
        try:
            m.normalize_arxiv_id("not-an-arxiv-id")
        except SystemExit as e:
            self.assertIn("could not parse", str(e))
            return
        raise AssertionError("expected SystemExit")


# ---------------- run() integration ----------------

class RunFunctionTests(TestCase):
    def test_writes_content_md_and_advances_state(self):
        with isolated_cache():
            _install_fake_arxiv2md(
                content="# Section\n\nbody text\n",
                meta={"title": "Test Paper",
                      "authors": ["Alice", "Bob"],
                      "year": 2024,
                      "doi": "10.48550/arXiv.2401.12345",
                      "abstract": "an abstract",
                      "venue": "arXiv"},
            )
            try:
                m = _import_fetch()
                from lib.paper_artifact import PaperArtifact, State
                cid = m.run(
                    arxiv_input="2401.12345", cid=None,
                    remove_refs=False, remove_toc=False,
                    remove_citations=False, sections=None,
                )
                art = PaperArtifact(cid)
                self.assertEqual(art.content_path.read_text(),
                                 "# Section\n\nbody text\n")
                manifest = art.load_manifest()
                self.assertEqual(manifest.state, State.extracted)
                self.assertEqual(manifest.arxiv_id, "2401.12345")
                self.assertEqual(manifest.doi,
                                 "10.48550/arXiv.2401.12345")
                meta = art.load_metadata()
                self.assertEqual(meta.title, "Test Paper")
                self.assertIn("arxiv-to-markdown", meta.discovered_via)
            finally:
                _uninstall_fake_arxiv2md()

    def test_frontmatter_yaml_emitted(self):
        with isolated_cache():
            _install_fake_arxiv2md(
                content="body",
                meta={"title": "Y", "authors": ["A"], "year": 2024},
            )
            try:
                m = _import_fetch()
                from lib.paper_artifact import PaperArtifact
                cid = m.run("2401.99999", None, False, False, False, None)
                fm = PaperArtifact(cid).frontmatter_path.read_text()
                self.assertIn("arxiv_id: 2401.99999", fm)
                self.assertIn('title: "Y"', fm)
                self.assertIn("- A", fm)
            finally:
                _uninstall_fake_arxiv2md()

    def test_empty_content_errors(self):
        with isolated_cache():
            _install_fake_arxiv2md(content="   \n\n",
                                     meta={"title": "X"})
            try:
                m = _import_fetch()
                try:
                    m.run("2401.00000", None, False, False, False, None)
                except SystemExit as e:
                    self.assertIn("empty", str(e).lower())
                    return
                raise AssertionError("expected SystemExit on empty content")
            finally:
                _uninstall_fake_arxiv2md()

    def test_extraction_log_written(self):
        with isolated_cache():
            _install_fake_arxiv2md(
                content="# Intro\n\nshort body\n",
                meta={"title": "L", "authors": ["A"], "year": 2024},
            )
            try:
                m = _import_fetch()
                from lib.paper_artifact import PaperArtifact
                cid = m.run("2401.11111", None, False, False, False, None)
                log = json.loads(
                    PaperArtifact(cid).extraction_log.read_text()
                )
                self.assertEqual(log["extractor"], "arxiv2markdown")
                self.assertEqual(log["arxiv_id"], "2401.11111")
                self.assertGreater(log["chars"], 0)
            finally:
                _uninstall_fake_arxiv2md()

    def test_re_run_preserves_existing_metadata_fields(self):
        with isolated_cache():
            _install_fake_arxiv2md(
                content="first body\n",
                meta={"title": "Same", "authors": ["A"], "year": 2024,
                      "abstract": "first abstract"},
            )
            try:
                m = _import_fetch()
                from lib.paper_artifact import PaperArtifact
                cid = m.run("2401.22222", None, False, False, False, None)
                # Pre-seed a tldr that arxiv2md doesn't provide
                art = PaperArtifact(cid)
                meta = art.load_metadata()
                meta.tldr = "human tldr"
                art.save_metadata(meta)

                # Re-run with new content
                _uninstall_fake_arxiv2md()
                _install_fake_arxiv2md(
                    content="second body\n",
                    meta={"title": "Same", "authors": ["A"], "year": 2024,
                          "abstract": "first abstract"},
                )
                m.run("2401.22222", None, False, False, False, None)
                meta = art.load_metadata()
                # tldr survives the re-run (existing fallback)
                self.assertEqual(meta.tldr, "human tldr")
                # discovered_via accumulates
                self.assertEqual(
                    meta.discovered_via.count("arxiv-to-markdown"), 2,
                )
            finally:
                _uninstall_fake_arxiv2md()


# ---------------- CLI surface ----------------

class CliTests(TestCase):
    def test_no_args_errors(self):
        r = subprocess.run(
            [sys.executable, str(FETCH)],
            capture_output=True, text=True,
        )
        self.assertTrue(r.returncode != 0)
        self.assertIn("--arxiv-id", r.stderr)

    def test_help_lists_flags(self):
        r = subprocess.run(
            [sys.executable, str(FETCH), "--help"],
            capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--remove-refs", r.stdout)
        self.assertIn("--sections", r.stdout)


if __name__ == "__main__":
    sys.exit(run_tests(NormalizeArxivIdTests, RunFunctionTests, CliTests))
