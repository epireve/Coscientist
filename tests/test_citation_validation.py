"""v0.9 citation-validation tests.

Covers:
- Bibliography parser handles numbered, bullet, and BibTeX styles
- manuscript-ingest populates manuscript_references with --project-id
- validate_citations.py detects all four failure modes
- audit gate accepts new finding kinds (dangling-citation etc.)
"""

from tests import _shim  # noqa: F401

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (_ROOT / "lib" / "sqlite_schema.sql").read_text()

INGEST = _ROOT / ".claude/skills/manuscript-ingest/scripts/ingest.py"
VALIDATE = _ROOT / ".claude/skills/manuscript-ingest/scripts/validate_citations.py"
AUDIT_GATE = _ROOT / ".claude/skills/manuscript-audit/scripts/gate.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True, text=True)


def _run_with_input(script: Path, input_json, *args: str) -> subprocess.CompletedProcess:
    tmp = _ROOT / "tests" / "_tmp_input.json"
    tmp.write_text(json.dumps(input_json))
    return _run(str(script), "--input", str(tmp), *args)


def _seed_project(cache_dir: Path, pid: str = "v09_project") -> str:
    p = cache_dir / "projects" / pid
    p.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p / "project.db")
    con.executescript(SCHEMA)
    con.execute(
        "INSERT INTO projects (project_id, name, created_at) VALUES (?, ?, ?)",
        (pid, "Validation test", "2026-04-24T00:00:00Z"),
    )
    con.commit()
    con.close()
    return pid


def _load_ingest_mod():
    path = _ROOT / ".claude/skills/manuscript-ingest/scripts/ingest.py"
    spec = importlib.util.spec_from_file_location("ingest_mod_v09", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------- bibliography parser ----------------

class BibParserTests(TestCase):
    def test_numbered_bib(self):
        mod = _load_ingest_mod()
        text = (
            "# Body\n\nCite \\cite{a}.\n\n"
            "# References\n\n"
            "[1] Smith, J. (2020). A paper. Journal, 10(2). doi:10.1234/example.abc\n"
            "[2] Jones, K. (2019). Another paper. Conf.\n"
        )
        entries = mod.extract_bibliography(text)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["ordinal"], 1)
        self.assertEqual(entries[0]["doi"], "10.1234/example.abc")
        self.assertEqual(entries[0]["year"], 2020)

    def test_bullet_bib(self):
        mod = _load_ingest_mod()
        text = (
            "# Body\n\nContent.\n\n"
            "## Bibliography\n\n"
            "- Vaswani, A. et al. (2017). Attention. NeurIPS.\n"
            "- Devlin, J. (2019). BERT. NAACL.\n"
        )
        entries = mod.extract_bibliography(text)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["ordinal"], 1)
        self.assertIn("Vaswani", entries[0]["raw_text"])

    def test_bibtex_blocks(self):
        mod = _load_ingest_mod()
        text = (
            "# Body\n\nContent.\n\n"
            "## References\n\n"
            "@article{vaswani2017,\n"
            "  title = {Attention is all you need},\n"
            "  year = {2017},\n"
            "  doi = {10.48550/arXiv.1706.03762}\n"
            "}\n\n"
            "@article{devlin2019,\n"
            "  title = {BERT},\n"
            "  year = {2019}\n"
            "}\n"
        )
        entries = mod.extract_bibliography(text)
        self.assertEqual(len(entries), 2)
        keys = {e["entry_key"] for e in entries}
        self.assertEqual(keys, {"vaswani2017", "devlin2019"})
        titles = {e["title"] for e in entries}
        self.assertIn("Attention is all you need", titles)

    def test_no_bib_section(self):
        mod = _load_ingest_mod()
        entries = mod.extract_bibliography("# Just body\n\nNo refs here.")
        self.assertEqual(entries, [])

    def test_infer_entry_key_from_bullet(self):
        mod = _load_ingest_mod()
        text = (
            "# Body\n\n"
            "## References\n\n"
            "- Smith, J. (2020). A paper. Journal.\n"
        )
        entries = mod.extract_bibliography(text)
        self.assertEqual(entries[0]["entry_key"], "smith2020")


# ---------------- ingest populates references ----------------

class IngestReferencesTests(TestCase):
    def test_ingest_writes_manuscript_references(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            src = cache_dir / "ms.md"
            src.write_text(
                "# Intro\n\n"
                "We cite \\cite{vaswani2017} and \\cite{devlin2019}.\n\n"
                "# References\n\n"
                "- Vaswani, A. et al. (2017). Attention. NeurIPS.\n"
                "- Devlin, J. (2019). BERT. NAACL.\n"
            )
            r = _run(str(INGEST), "--source", str(src), "--title", "T",
                     "--project-id", pid)
            assert r.returncode == 0, f"stderr={r.stderr}"
            mid = r.stdout.strip()

            db = cache_dir / "projects" / pid / "project.db"
            con = sqlite3.connect(db)
            rows = con.execute(
                "SELECT ordinal, entry_key, year FROM manuscript_references "
                "WHERE manuscript_id=? ORDER BY ordinal", (mid,)
            ).fetchall()
            con.close()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][2], 2017)  # Vaswani 2017
            self.assertEqual(rows[1][2], 2019)  # Devlin 2019


# ---------------- validate_citations ----------------

def _setup_ingested(cache_dir: Path, md_source: str,
                     pid: str = "val_proj") -> tuple[str, str]:
    _seed_project(cache_dir, pid)
    src = cache_dir / "ms.md"
    src.write_text(md_source)
    r = _run(str(INGEST), "--source", str(src), "--title", "V",
             "--project-id", pid)
    assert r.returncode == 0, f"stderr={r.stderr}"
    return r.stdout.strip(), pid


class ValidateCitationsTests(TestCase):
    def test_clean_manuscript(self):
        """All citations have matching bib entries → no dangling/orphan."""
        with isolated_cache() as cache_dir:
            mid, pid = _setup_ingested(cache_dir, (
                "# Intro\n\nCite \\cite{vaswani2017} here.\n\n"
                "# References\n\n"
                "- Vaswani, A. (2017). Attention. NeurIPS.\n"
            ))
            r = _run(str(VALIDATE), "--manuscript-id", mid, "--project-id", pid)
            assert r.returncode == 0, f"stderr={r.stderr}"
            report = json.loads(
                (cache_dir / "manuscripts" / mid / "validation_report.json").read_text()
            )
            s = report["summary"]
            self.assertEqual(s["dangling_citations"], 0)
            self.assertEqual(s["orphan_references"], 0)

    def test_dangling_citation(self):
        """In-text [@smith2020] but smith2020 not in bib → flagged."""
        with isolated_cache() as cache_dir:
            mid, pid = _setup_ingested(cache_dir, (
                "# Intro\n\nCite \\cite{smith2020}.\n\n"
                "# References\n\n"
                "- Jones, K. (2019). Unrelated. Journal.\n"
            ))
            _run(str(VALIDATE), "--manuscript-id", mid, "--project-id", pid)
            report = json.loads(
                (cache_dir / "manuscripts" / mid / "validation_report.json").read_text()
            )
            self.assertTrue(report["summary"]["dangling_citations"] >= 1)
            kinds = {f["kind"] for f in report["findings"]}
            self.assertIn("dangling-citation", kinds)

    def test_orphan_reference(self):
        """Bib entry present but never cited → orphan."""
        with isolated_cache() as cache_dir:
            mid, pid = _setup_ingested(cache_dir, (
                "# Intro\n\nCite \\cite{vaswani2017}.\n\n"
                "# References\n\n"
                "- Vaswani, A. (2017). Attention. NeurIPS.\n"
                "- Smith, J. (2020). Unused paper. Journal.\n"
            ))
            _run(str(VALIDATE), "--manuscript-id", mid, "--project-id", pid)
            report = json.loads(
                (cache_dir / "manuscripts" / mid / "validation_report.json").read_text()
            )
            self.assertTrue(report["summary"]["orphan_references"] >= 1)
            self.assertTrue(any(f["kind"] == "orphan-reference"
                                for f in report["findings"]))

    def test_unresolved_citation(self):
        """Citation never resolved → unresolved finding."""
        with isolated_cache() as cache_dir:
            mid, pid = _setup_ingested(cache_dir, (
                "# Intro\n\nCite \\cite{vaswani2017}.\n\n"
                "# References\n\n"
                "- Vaswani, A. (2017). Attention. NeurIPS.\n"
            ))
            _run(str(VALIDATE), "--manuscript-id", mid, "--project-id", pid)
            report = json.loads(
                (cache_dir / "manuscripts" / mid / "validation_report.json").read_text()
            )
            # At ingest, resolved_canonical_id is NULL, so this is unresolved
            self.assertTrue(report["summary"]["unresolved_citations"] >= 1)

    def test_broken_reference(self):
        """Mapped canonical_id exists but paper artifact is missing → broken."""
        with isolated_cache() as cache_dir:
            mid, pid = _setup_ingested(cache_dir, (
                "# Intro\n\nCite \\cite{vaswani2017}.\n\n"
                "# References\n\n"
                "- Vaswani, A. (2017). Attention. NeurIPS.\n"
            ))
            # Manually set a resolved_canonical_id pointing to non-existent paper
            db = cache_dir / "projects" / pid / "project.db"
            con = sqlite3.connect(db)
            con.execute(
                "UPDATE manuscript_citations "
                "SET resolved_canonical_id='paper_that_does_not_exist_xyz' "
                "WHERE manuscript_id=?", (mid,)
            )
            con.commit()
            con.close()

            _run(str(VALIDATE), "--manuscript-id", mid, "--project-id", pid)
            report = json.loads(
                (cache_dir / "manuscripts" / mid / "validation_report.json").read_text()
            )
            self.assertTrue(report["summary"]["broken_references"] >= 1)
            kinds = {f["kind"] for f in report["findings"]}
            self.assertIn("broken-reference", kinds)

    def test_fail_on_major_exits_nonzero(self):
        with isolated_cache() as cache_dir:
            mid, pid = _setup_ingested(cache_dir, (
                "# Intro\n\nCite \\cite{smith2020}.\n\n"
                "# References\n\n"
                "- Jones, K. (2019). Unrelated. Journal.\n"
            ))
            r = _run(str(VALIDATE), "--manuscript-id", mid, "--project-id", pid,
                     "--fail-on-major")
            self.assertEqual(r.returncode, 2)

    def test_findings_land_in_audit_table(self):
        with isolated_cache() as cache_dir:
            mid, pid = _setup_ingested(cache_dir, (
                "# Intro\n\nCite \\cite{smith2020}.\n\n"
                "# References\n\n"
                "- Jones, K. (2019). Paper. Journal.\n"
            ))
            _run(str(VALIDATE), "--manuscript-id", mid, "--project-id", pid)
            db = cache_dir / "projects" / pid / "project.db"
            con = sqlite3.connect(db)
            rows = con.execute(
                "SELECT kind, severity FROM manuscript_audit_findings "
                "WHERE manuscript_id=? AND claim_id LIKE 'citation-validator:%'",
                (mid,),
            ).fetchall()
            con.close()
            kinds = {r[0] for r in rows}
            # Should include dangling-citation AND orphan-reference AND unresolved-citation
            self.assertIn("dangling-citation", kinds)
            self.assertIn("orphan-reference", kinds)
            self.assertIn("unresolved-citation", kinds)


# ---------------- audit gate accepts new kinds ----------------

class AuditGateNewKindsTests(TestCase):
    def test_audit_gate_accepts_dangling_citation_kind(self):
        with isolated_cache() as cache_dir:
            report = {
                "manuscript_id": "ms_new",
                "claims": [{
                    "claim_id": "c-1",
                    "text": "Transformers rule [@smith2020].",
                    "location": "§1",
                    "cited_sources": ["smith_2020_abc"],
                    "findings": [{
                        "kind": "dangling-citation",  # new v0.9 kind
                        "severity": "major",
                        "evidence": "smith2020 not in reference list.",
                    }],
                }],
            }
            r = _run_with_input(AUDIT_GATE, report, "--manuscript-id", "ms_new")
            assert r.returncode == 0, f"stderr={r.stderr}"

    def test_audit_gate_accepts_broken_reference_kind(self):
        with isolated_cache() as cache_dir:
            report = {
                "manuscript_id": "ms_new",
                "claims": [{
                    "claim_id": "c-1",
                    "text": "Claim text [@smith2020].",
                    "location": "§1",
                    "cited_sources": ["nonexistent"],
                    "findings": [{
                        "kind": "broken-reference",
                        "severity": "major",
                        "evidence": "Paper artifact missing for nonexistent.",
                    }],
                }],
            }
            r = _run_with_input(AUDIT_GATE, report, "--manuscript-id", "ms_new")
            assert r.returncode == 0, f"stderr={r.stderr}"


# ---------------- schema ----------------

class ManuscriptReferencesSchemaTests(TestCase):
    def test_table_present(self):
        con = sqlite3.connect(":memory:")
        con.executescript(SCHEMA)
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        self.assertIn("manuscript_references", names)

    def test_unique_on_manuscript_and_ordinal(self):
        con = sqlite3.connect(":memory:")
        con.executescript(SCHEMA)
        con.execute(
            "INSERT INTO manuscript_references "
            "(manuscript_id, entry_key, raw_text, ordinal, at) "
            "VALUES ('m1', 'k1', 'raw', 1, '2026-01-01')"
        )
        try:
            con.execute(
                "INSERT INTO manuscript_references "
                "(manuscript_id, entry_key, raw_text, ordinal, at) "
                "VALUES ('m1', 'k2', 'raw2', 1, '2026-01-02')"
            )
            raise AssertionError("expected IntegrityError")
        except sqlite3.IntegrityError:
            pass


if __name__ == "__main__":
    sys.exit(run_tests(
        BibParserTests,
        IngestReferencesTests,
        ValidateCitationsTests,
        AuditGateNewKindsTests,
        ManuscriptReferencesSchemaTests,
    ))
