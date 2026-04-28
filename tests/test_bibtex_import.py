"""v0.48 tests for manuscript-bibtex-import."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
IMPORT = _ROOT / ".claude/skills/manuscript-bibtex-import/scripts/import_bib.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(IMPORT), *args],
        capture_output=True, text=True,
    )


SIMPLE_BIB = """
@article{smith2020transformer,
  title = {The Transformer: A Critical Look},
  author = {Smith, John and Doe, Jane},
  year = {2020},
  journal = {Journal of ML},
  doi = {10.1234/jml.2020.001},
  abstract = {We present a critical analysis of the Transformer.},
  keywords = {transformer, attention, ml},
}

@inproceedings{wong2024scaling,
  title = {Scaling laws for language models},
  author = {Wong, Alice},
  year = {2024},
  booktitle = {NeurIPS},
  url = {https://arxiv.org/abs/2401.12345},
}

@misc{anonymous2023null,
  title = {{Null result on diffusion}},
  author = {Anonymous},
  year = {2023},
}
"""


class ParseTests(TestCase):
    def _import_module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("ib", IMPORT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_parse_three_entries(self):
        m = self._import_module()
        entries = m.parse_bibtex(SIMPLE_BIB)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]["type"], "article")
        self.assertEqual(entries[0]["key"], "smith2020transformer")

    def test_parse_fields_unbraced(self):
        m = self._import_module()
        entries = m.parse_bibtex(SIMPLE_BIB)
        f = entries[0]["fields"]
        self.assertEqual(f["title"], "The Transformer: A Critical Look")
        self.assertEqual(f["year"], "2020")
        self.assertIn("transformer", f["keywords"])

    def test_parse_double_braced_title(self):
        m = self._import_module()
        entries = m.parse_bibtex(SIMPLE_BIB)
        # {{Null result on diffusion}} should reduce to plain text
        self.assertEqual(entries[2]["fields"]["title"],
                          "Null result on diffusion")

    def test_split_authors_lastfirst(self):
        m = self._import_module()
        authors = m._split_authors("Smith, John and Doe, Jane")
        self.assertEqual(authors, ["John Smith", "Jane Doe"])

    def test_split_authors_firstlast(self):
        m = self._import_module()
        authors = m._split_authors("John Smith and Alice Wong")
        self.assertEqual(authors, ["John Smith", "Alice Wong"])

    def test_unescape_handles_latex(self):
        m = self._import_module()
        self.assertEqual(m._unescape(r"AT\&T"), "AT&T")
        self.assertEqual(m._unescape(r"foo\textendash bar"), "foo– bar")


class ParseOnlyTests(TestCase):
    def test_parse_only_no_project_needed(self):
        with isolated_cache() as cache_dir:
            bib = cache_dir / "refs.bib"
            bib.write_text(SIMPLE_BIB)
            r = _run("--bib", str(bib), "--parse-only")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["count"], 3)


class DryRunTests(TestCase):
    def test_dry_run_writes_nothing(self):
        with isolated_cache() as cache_dir:
            bib = cache_dir / "refs.bib"
            bib.write_text(SIMPLE_BIB)
            r = _run("--bib", str(bib), "--project-id", "p_dry",
                       "--dry-run")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["imported"], 3)
            # No paper artifacts created
            from lib.cache import cache_root
            papers_dir = cache_root() / "papers"
            self.assertFalse(papers_dir.exists() and any(papers_dir.iterdir()))


class ImportTests(TestCase):
    def test_full_import_writes_artifacts(self):
        with isolated_cache() as cache_dir:
            from lib.project import create
            pid = create("p_imp", question="test")
            bib = cache_dir / "refs.bib"
            bib.write_text(SIMPLE_BIB)
            r = _run("--bib", str(bib), "--project-id", pid)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["imported"], 3)
            self.assertEqual(len(out["canonical_ids"]), 3)
            # Each canonical_id has a paper artifact on disk
            from lib.paper_artifact import PaperArtifact
            for cid in out["canonical_ids"]:
                art = PaperArtifact(cid)
                meta = art.load_metadata()
                self.assertIsNotNone(meta)
                self.assertIn("bibtex-import", meta.discovered_via)

    def test_doi_persisted_to_manifest(self):
        with isolated_cache() as cache_dir:
            from lib.paper_artifact import PaperArtifact
            from lib.project import create
            pid = create("p_doi", question="test")
            bib = cache_dir / "refs.bib"
            bib.write_text(SIMPLE_BIB)
            r = _run("--bib", str(bib), "--project-id", pid)
            out = json.loads(r.stdout)
            # First entry has doi field
            cid_with_doi = out["canonical_ids"][0]
            art = PaperArtifact(cid_with_doi)
            self.assertEqual(art.load_manifest().doi, "10.1234/jml.2020.001")

    def test_arxiv_extracted_from_url(self):
        with isolated_cache() as cache_dir:
            from lib.paper_artifact import PaperArtifact
            from lib.project import create
            pid = create("p_arxiv", question="test")
            bib = cache_dir / "refs.bib"
            bib.write_text(SIMPLE_BIB)
            r = _run("--bib", str(bib), "--project-id", pid)
            out = json.loads(r.stdout)
            # Second entry has arxiv URL
            cid = out["canonical_ids"][1]
            self.assertEqual(
                PaperArtifact(cid).load_manifest().arxiv_id, "2401.12345"
            )

    def test_registers_in_artifact_index(self):
        with isolated_cache() as cache_dir:
            from lib.project import create, project_db_path
            pid = create("p_reg", question="test")
            bib = cache_dir / "refs.bib"
            bib.write_text(SIMPLE_BIB)
            _run("--bib", str(bib), "--project-id", pid)
            con = sqlite3.connect(project_db_path(pid))
            count = con.execute(
                "SELECT COUNT(*) FROM artifact_index "
                "WHERE project_id=? AND kind='paper'", (pid,),
            ).fetchone()[0]
            con.close()
            self.assertEqual(count, 3)

    def test_writes_reading_state(self):
        with isolated_cache() as cache_dir:
            from lib.project import create, project_db_path
            pid = create("p_rs", question="test")
            bib = cache_dir / "refs.bib"
            bib.write_text(SIMPLE_BIB)
            _run("--bib", str(bib), "--project-id", pid,
                  "--reading-state", "to-read")
            con = sqlite3.connect(project_db_path(pid))
            states = [r[0] for r in con.execute(
                "SELECT state FROM reading_state WHERE project_id=?", (pid,),
            )]
            con.close()
            self.assertEqual(len(states), 3)
            self.assertTrue(all(s == "to-read" for s in states))

    def test_re_import_skips_duplicates(self):
        with isolated_cache() as cache_dir:
            from lib.project import create
            pid = create("p_dup", question="test")
            bib = cache_dir / "refs.bib"
            bib.write_text(SIMPLE_BIB)
            _run("--bib", str(bib), "--project-id", pid)
            # Re-run
            r = _run("--bib", str(bib), "--project-id", pid)
            out = json.loads(r.stdout)
            # Same DOIs / titles → all dedup
            self.assertEqual(out["skipped_duplicate"], 3)
            self.assertEqual(out["imported"], 0)

    def test_thin_entry_skipped(self):
        with isolated_cache() as cache_dir:
            from lib.project import create
            pid = create("p_thin", question="test")
            bib = cache_dir / "refs.bib"
            bib.write_text(
                "@article{empty, year = {2020}}\n"
            )
            r = _run("--bib", str(bib), "--project-id", pid)
            out = json.loads(r.stdout)
            self.assertEqual(out["skipped_thin"], 1)
            self.assertEqual(out["imported"], 0)


class CliTests(TestCase):
    def test_missing_bib_errors(self):
        r = _run("--project-id", "p")
        self.assertTrue(r.returncode != 0)

    def test_no_project_id_without_dry_run_errors(self):
        with isolated_cache() as cache_dir:
            bib = cache_dir / "refs.bib"
            bib.write_text(SIMPLE_BIB)
            r = _run("--bib", str(bib))
            self.assertTrue(r.returncode != 0)

    def test_missing_project_db_errors(self):
        with isolated_cache() as cache_dir:
            bib = cache_dir / "refs.bib"
            bib.write_text(SIMPLE_BIB)
            r = _run("--bib", str(bib), "--project-id", "nonexistent")
            self.assertTrue(r.returncode != 0)
            self.assertIn("no project DB", r.stderr)


if __name__ == "__main__":
    sys.exit(run_tests(
        ParseTests, ParseOnlyTests, DryRunTests, ImportTests, CliTests,
    ))
