"""v0.45.4 tests for paper-discovery merge.py."""

from tests import _shim  # noqa: F401

import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
MERGE = _ROOT / ".claude/skills/paper-discovery/scripts/merge.py"
SCHEMA = _ROOT / "lib" / "sqlite_schema.sql"


def _import_merge():
    """Import merge.py so we can call merge_entries / rank as funcs."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pd_merge", MERGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MERGE), *args],
        capture_output=True, text=True,
    )


class MergeEntriesTests(TestCase):
    def test_doi_dedupes_across_sources(self):
        m = _import_merge()
        merged = m.merge_entries([
            {"source": "consensus", "title": "X", "doi": "10.1/x"},
            {"source": "semantic-scholar", "title": "X", "doi": "10.1/X"},
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(sorted(merged[0]["discovered_via"]),
                         ["consensus", "semantic-scholar"])

    def test_arxiv_dedupes_when_no_doi(self):
        m = _import_merge()
        merged = m.merge_entries([
            {"source": "paper-search", "title": "Y", "arxiv_id": "2401.0001"},
            {"source": "academic", "title": "Y", "arxiv_id": "2401.0001"},
        ])
        self.assertEqual(len(merged), 1)

    def test_title_dedup_falls_back_when_neither_id(self):
        m = _import_merge()
        merged = m.merge_entries([
            {"source": "consensus", "title": "Same Paper Title!"},
            {"source": "academic", "title": "same paper title"},
        ])
        self.assertEqual(len(merged), 1)

    def test_richer_fields_win(self):
        m = _import_merge()
        merged = m.merge_entries([
            {"source": "a", "title": "Z", "doi": "10.2/z"},
            {"source": "b", "title": "Z", "doi": "10.2/z",
             "abstract": "long abstract", "tldr": "tldr",
             "venue": "ICML", "citation_count": 50},
        ])
        e = merged[0]
        self.assertEqual(e["abstract"], "long abstract")
        self.assertEqual(e["tldr"], "tldr")
        self.assertEqual(e["venue"], "ICML")
        self.assertEqual(e["citation_count"], 50)

    def test_higher_citation_count_wins(self):
        m = _import_merge()
        merged = m.merge_entries([
            {"source": "a", "title": "Q", "doi": "10.3/q",
             "citation_count": 5},
            {"source": "b", "title": "Q", "doi": "10.3/q",
             "citation_count": 100},
        ])
        self.assertEqual(merged[0]["citation_count"], 100)

    def test_claims_concatenated(self):
        m = _import_merge()
        merged = m.merge_entries([
            {"source": "consensus", "title": "P", "doi": "10.4/p",
             "claims": [{"text": "c1"}]},
            {"source": "consensus2", "title": "P", "doi": "10.4/p",
             "claims": [{"text": "c2"}]},
        ])
        self.assertEqual(len(merged[0]["claims"]), 2)


class RankTests(TestCase):
    def test_more_sources_ranks_higher(self):
        m = _import_merge()
        ranked = m.rank([
            {"discovered_via": ["a"], "citation_count": 100, "year": 2020},
            {"discovered_via": ["a", "b", "c"], "citation_count": 5,
             "year": 2018},
        ])
        # 3 sources beats 1 source even with lower citation count
        self.assertEqual(len(ranked[0]["discovered_via"]), 3)

    def test_citation_count_breaks_ties_when_sources_equal(self):
        m = _import_merge()
        ranked = m.rank([
            {"discovered_via": ["a"], "citation_count": 5, "year": 2020},
            {"discovered_via": ["a"], "citation_count": 50, "year": 2018},
        ])
        self.assertEqual(ranked[0]["citation_count"], 50)

    def test_year_breaks_ties_when_sources_and_citations_equal(self):
        m = _import_merge()
        ranked = m.rank([
            {"discovered_via": ["a"], "citation_count": 5, "year": 2020},
            {"discovered_via": ["a"], "citation_count": 5, "year": 2024},
        ])
        # newer year wins
        self.assertEqual(ranked[0]["year"], 2024)


class CliTests(TestCase):
    def test_writes_shortlist_and_creates_artifacts(self):
        with isolated_cache() as cache_dir:
            input_file = cache_dir / "raw.json"
            out_file = cache_dir / "shortlist.json"
            input_file.write_text(json.dumps([
                {"source": "consensus", "title": "Paper One",
                 "authors": ["Alice"], "year": 2024,
                 "doi": "10.5/a", "abstract": "abs1",
                 "citation_count": 12},
                {"source": "academic", "title": "Paper One",
                 "authors": ["Alice"], "year": 2024,
                 "doi": "10.5/a"},
                {"source": "paper-search", "title": "Paper Two",
                 "authors": ["Bob"], "year": 2023,
                 "arxiv_id": "2301.0001"},
            ]))
            r = _run_cli(
                "--input", str(input_file),
                "--query", "test query",
                "--out", str(out_file),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            shortlist = json.loads(out_file.read_text())
            # 2 unique papers after merge
            self.assertEqual(len(shortlist), 2)
            # Higher-source-count paper ranks first
            self.assertEqual(shortlist[0]["title"], "Paper One")
            self.assertEqual(sorted(shortlist[0]["sources"]),
                             ["academic", "consensus"])
            # Artifact exists
            from lib.paper_artifact import PaperArtifact
            art = PaperArtifact(shortlist[0]["canonical_id"])
            meta = art.load_metadata()
            self.assertEqual(meta.title, "Paper One")
            self.assertEqual(meta.discovered_via,
                             ["consensus", "academic"])

    def test_run_id_inserts_into_papers_in_run(self):
        with isolated_cache() as cache_dir:
            from lib.cache import run_db_path
            from lib.migrations import ensure_current
            run_id = "rd_test"
            db = run_db_path(run_id)
            con = sqlite3.connect(db)
            con.executescript(SCHEMA.read_text())
            con.close()
            ensure_current(db)
            con = sqlite3.connect(db)
            with con:
                con.execute(
                    "INSERT INTO runs (run_id, question, started_at) "
                    "VALUES (?, 'q', ?)",
                    (run_id, datetime.now(UTC).isoformat()),
                )
            con.close()

            input_file = cache_dir / "raw.json"
            out_file = cache_dir / "shortlist.json"
            input_file.write_text(json.dumps([
                {"source": "consensus", "title": "Run Insert Paper",
                 "authors": ["Z"], "year": 2024, "doi": "10.6/r"},
            ]))
            r = _run_cli(
                "--input", str(input_file),
                "--query", "q",
                "--run-id", run_id,
                "--out", str(out_file),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            con = sqlite3.connect(db)
            rows = con.execute(
                "SELECT canonical_id FROM papers_in_run WHERE run_id=?",
                (run_id,),
            ).fetchall()
            con.close()
            self.assertEqual(len(rows), 1)

    def test_idempotent_re_merge(self):
        with isolated_cache() as cache_dir:
            input_file = cache_dir / "raw.json"
            out_file = cache_dir / "out.json"
            input_file.write_text(json.dumps([
                {"source": "consensus", "title": "Idem", "doi": "10.7/i",
                 "authors": ["X"], "year": 2024, "abstract": "first abs"},
            ]))
            _run_cli("--input", str(input_file), "--query", "q",
                      "--out", str(out_file))
            # Re-run with richer abstract — existing fields preserved,
            # new fields filled
            input_file.write_text(json.dumps([
                {"source": "academic", "title": "Idem", "doi": "10.7/i",
                 "authors": ["X"], "year": 2024,
                 "tldr": "added later"},
            ]))
            _run_cli("--input", str(input_file), "--query", "q",
                      "--out", str(out_file))
            shortlist = json.loads(out_file.read_text())
            from lib.paper_artifact import PaperArtifact
            art = PaperArtifact(shortlist[0]["canonical_id"])
            meta = art.load_metadata()
            # Original abstract retained, new tldr merged in
            self.assertEqual(meta.abstract, "first abs")
            self.assertEqual(meta.tldr, "added later")
            # Sources accumulated across runs
            self.assertIn("consensus", meta.discovered_via)
            self.assertIn("academic", meta.discovered_via)


if __name__ == "__main__":
    sys.exit(run_tests(MergeEntriesTests, RankTests, CliTests))
