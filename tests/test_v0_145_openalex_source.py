"""v0.145 — OpenAlex paper-discovery adapter tests."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from tests.harness import TestCase, run_tests


_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = (_REPO / ".claude" / "skills" / "paper-discovery"
           / "scripts" / "openalex_source.py")


def _load():
    spec = importlib.util.spec_from_file_location(
        "_openalex_source_test", _SCRIPT,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_openalex_source_test"] = mod
    spec.loader.exec_module(mod)
    return mod


class MapWorkTests(TestCase):
    def test_minimal_work(self):
        mod = _load()
        out = mod._map_work({
            "id": "https://openalex.org/W123",
            "title": "Test paper",
            "publication_year": 2024,
        })
        self.assertEqual(out["source"], "openalex")
        self.assertEqual(out["title"], "Test paper")
        self.assertEqual(out["year"], 2024)
        self.assertEqual(out["openalex_id"], "W123")

    def test_doi_normalized(self):
        mod = _load()
        out = mod._map_work({
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.1/x",
            "title": "T",
        })
        self.assertEqual(out["doi"], "10.1/x")

    def test_authors_extracted(self):
        mod = _load()
        out = mod._map_work({
            "id": "W1",
            "title": "T",
            "authorships": [
                {"author": {"display_name": "Alice"}},
                {"author": {"display_name": "Bob"}},
                {"author": {}},  # malformed, skip
            ],
        })
        self.assertEqual(out["authors"], ["Alice", "Bob"])

    def test_abstract_reconstructed(self):
        mod = _load()
        out = mod._map_work({
            "id": "W1",
            "title": "T",
            "abstract_inverted_index": {
                "the": [0], "test": [1],
            },
        })
        self.assertEqual(out["abstract"], "the test")

    def test_oa_url_extracted(self):
        mod = _load()
        out = mod._map_work({
            "id": "W1",
            "title": "T",
            "open_access": {"oa_url": "https://oa.com/p.pdf"},
        })
        self.assertEqual(out["oa_url"], "https://oa.com/p.pdf")

    def test_arxiv_detected_from_landing(self):
        mod = _load()
        out = mod._map_work({
            "id": "W1",
            "title": "T",
            "primary_location": {
                "landing_page_url": "https://arxiv.org/abs/2401.12345",
            },
        })
        self.assertEqual(out["arxiv_id"], "2401.12345")

    def test_pmid_extracted(self):
        mod = _load()
        out = mod._map_work({
            "id": "W1",
            "title": "T",
            "ids": {
                "pmid": "https://pubmed.ncbi.nlm.nih.gov/pubmed/12345",
            },
        })
        self.assertEqual(out["pmid"], "12345")

    def test_venue_from_primary_location(self):
        mod = _load()
        out = mod._map_work({
            "id": "W1",
            "title": "T",
            "primary_location": {
                "source": {"display_name": "Nature"},
            },
        })
        self.assertEqual(out["venue"], "Nature")

    def test_topics_filtered_by_score(self):
        mod = _load()
        out = mod._map_work({
            "id": "W1",
            "title": "T",
            "topics": [
                {"id": "T1", "display_name": "ML",
                 "score": 0.9, "level": 1},
                {"id": "T2", "display_name": "Junk",
                 "score": 0.2, "level": 2},
            ],
        })
        self.assertEqual(len(out["topics"]), 1)
        self.assertEqual(out["topics"][0]["name"], "ML")

    def test_citation_count_default_zero(self):
        mod = _load()
        out = mod._map_work({
            "id": "W1", "title": "T",
        })
        self.assertEqual(out["citation_count"], 0)


class SearchToRecordsTests(TestCase):
    def test_error_returns_empty_list(self):
        """When client returns {error: ...}, search_to_records → []."""
        mod = _load()

        class FakeClient:
            def search_works(self, *a, **kw):
                return {"error": "down"}

        out = mod.search_to_records("x", client=FakeClient())
        self.assertEqual(out, [])

    def test_works_mapped(self):
        mod = _load()

        class FakeClient:
            def search_works(self, *a, **kw):
                return {
                    "results": [
                        {"id": "W1", "title": "A"},
                        {"id": "W2", "title": "B"},
                    ],
                }

        out = mod.search_to_records("x", client=FakeClient())
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["title"], "A")
        self.assertEqual(out[0]["source"], "openalex")


class CliTests(TestCase):
    def test_help_works(self):
        import subprocess
        r = subprocess.run(
            [sys.executable, str(_SCRIPT), "-h"],
            capture_output=True, text=True, cwd=str(_REPO),
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("--query", r.stdout)
        self.assertIn("--per-page", r.stdout)
        self.assertIn("--filter", r.stdout)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        MapWorkTests, SearchToRecordsTests, CliTests,
    ))
