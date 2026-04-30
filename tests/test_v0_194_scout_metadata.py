"""v0.194 — scout's merge.py persists abstract + tldr + IDs to metadata.json.

Closes dogfood finding #8: cartographer reported in-run paper artifacts had
NO abstracts / TLDRs, blocking Cite-What-You've-Read grounding. merge.py
must capture every metadata field MCPs expose, and idempotent re-runs must
NOT clobber filled fields with empty input.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    REPO_ROOT / ".claude" / "skills" / "paper-discovery"
    / "scripts" / "merge.py"
)


def _import_merge():
    """Load merge.py as a module (it's a CLI script)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_merge_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ScoutMetadataPersistenceTests(TestCase):
    def test_abstract_persisted_to_metadata(self):
        with isolated_cache():
            m = _import_merge()
            entries = [{
                "source": "openalex",
                "title": "Multi-Agent LLM Coordination",
                "authors": ["Smith, J."],
                "year": 2024,
                "abstract": "We study coordination protocols for LLM agents.",
            }]
            cids = m.write_stubs(m.rank(m.merge_entries(entries)), None)
            self.assertEqual(len(cids), 1)
            from lib.paper_artifact import PaperArtifact
            art = PaperArtifact(cids[0])
            md = art.load_metadata()
            self.assertIsNotNone(md)
            self.assertEqual(
                md.abstract,
                "We study coordination protocols for LLM agents.",
            )

    def test_tldr_persisted(self):
        with isolated_cache():
            m = _import_merge()
            entries = [{
                "source": "semantic-scholar",
                "title": "Context Isolation Effects",
                "authors": ["Doe, A."],
                "year": 2025,
                "tldr": "Isolation reduces task reliability by 32%.",
            }]
            cids = m.write_stubs(m.rank(m.merge_entries(entries)), None)
            from lib.paper_artifact import PaperArtifact
            md = PaperArtifact(cids[0]).load_metadata()
            self.assertEqual(
                md.tldr,
                "Isolation reduces task reliability by 32%.",
            )

    def test_rerun_does_not_overwrite_filled_fields(self):
        """Re-running with sparse harvest must preserve earlier-filled
        abstract. Otherwise idempotent re-discovery erases data."""
        with isolated_cache():
            m = _import_merge()
            # First run: rich harvest with abstract + tldr.
            rich = [{
                "source": "openalex",
                "title": "Same Paper",
                "authors": ["X, Y."],
                "year": 2024,
                "doi": "10.1/same",
                "abstract": "Original abstract.",
                "tldr": "Original tldr.",
            }]
            cids1 = m.write_stubs(m.rank(m.merge_entries(rich)), None)
            # Second run: same paper, no abstract/tldr.
            sparse = [{
                "source": "arxiv",
                "title": "Same Paper",
                "authors": ["X, Y."],
                "year": 2024,
                "doi": "10.1/same",
            }]
            cids2 = m.write_stubs(m.rank(m.merge_entries(sparse)), None)
            self.assertEqual(cids1, cids2)
            from lib.paper_artifact import PaperArtifact
            md = PaperArtifact(cids1[0]).load_metadata()
            self.assertEqual(md.abstract, "Original abstract.")
            self.assertEqual(md.tldr, "Original tldr.")

    def test_missing_abstract_no_fake_field(self):
        """When the harvest entry has no abstract, do NOT synthesize
        one — just leave the field None."""
        with isolated_cache():
            m = _import_merge()
            entries = [{
                "source": "consensus",
                "title": "Bare Stub",
                "authors": ["Z, W."],
                "year": 2023,
            }]
            cids = m.write_stubs(m.rank(m.merge_entries(entries)), None)
            from lib.paper_artifact import PaperArtifact
            md = PaperArtifact(cids[0]).load_metadata()
            self.assertIsNone(md.abstract)
            self.assertIsNone(md.tldr)

    def test_cross_source_merge(self):
        """Same paper from two sources — DOI from openalex, TLDR from
        S2. Both should land in artifact."""
        with isolated_cache():
            m = _import_merge()
            entries = [
                {
                    "source": "openalex",
                    "title": "Cross-Source Paper",
                    "authors": ["A, B."],
                    "year": 2024,
                    "doi": "10.1/cross",
                    "openalex_id": "W12345",
                },
                {
                    "source": "semantic-scholar",
                    "title": "Cross-Source Paper",
                    "authors": ["A, B."],
                    "year": 2024,
                    "doi": "10.1/cross",
                    "tldr": "Cross-source TLDR.",
                    "s2_id": "abc123",
                },
            ]
            cids = m.write_stubs(m.rank(m.merge_entries(entries)), None)
            self.assertEqual(len(cids), 1)  # deduped
            from lib.paper_artifact import PaperArtifact
            art = PaperArtifact(cids[0])
            mf = art.load_manifest()
            md = art.load_metadata()
            self.assertEqual(mf.doi, "10.1/cross")
            self.assertEqual(mf.openalex_id, "W12345")
            self.assertEqual(mf.s2_id, "abc123")
            self.assertEqual(md.tldr, "Cross-source TLDR.")

    def test_empty_input_is_clean_noop(self):
        with isolated_cache():
            m = _import_merge()
            cids = m.write_stubs(m.rank(m.merge_entries([])), None)
            self.assertEqual(cids, [])


if __name__ == "__main__":
    sys.exit(run_tests(ScoutMetadataPersistenceTests))
