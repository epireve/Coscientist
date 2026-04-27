"""Tests for v0.58 resolve-citation skill — lib.citation_resolver + CLI."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from tests.harness import TestCase

from lib.citation_resolver import (
    PartialCitation,
    parse_partial,
    pick_best,
    score_match,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_RESOLVE_PY = (
    _REPO_ROOT / ".claude" / "skills" / "resolve-citation" / "scripts" / "resolve.py"
)


class CitationResolverParserTests(TestCase):
    """Parser handles each example shape from the spec."""

    def test_smith_2020(self):
        p = parse_partial("Smith 2020")
        self.assertEqual(p.year, 2020)
        self.assertIn("smith", p.authors)
        self.assertEqual(len(p.title_tokens), 0)

    def test_vaswani_etal_2017(self):
        p = parse_partial("Vaswani et al., 2017")
        self.assertEqual(p.year, 2017)
        self.assertIn("vaswani", p.authors)
        # "et al" must not leak through as an author.
        self.assertNotIn("et", p.authors)
        self.assertNotIn("al", p.authors)

    def test_vaswani_with_title(self):
        p = parse_partial("Vaswani 2017 Attention is all you need")
        self.assertEqual(p.year, 2017)
        self.assertIn("vaswani", p.authors)
        self.assertIn("attention", p.title_tokens)
        self.assertIn("all", p.title_tokens)
        self.assertIn("need", p.title_tokens)

    def test_multi_author_with_emdash(self):
        p = parse_partial("He, Zhang, Ren, Sun (2016) — Deep Residual Learning")
        self.assertEqual(p.year, 2016)
        for ln in ("zhang", "ren", "sun"):
            self.assertIn(ln, p.authors)
        # "He" is a stop-ish lastname; tolerate if missing, but the other 3 must be there.
        self.assertGreaterEqual(len(p.authors), 3)
        self.assertIn("deep", p.title_tokens)
        self.assertIn("residual", p.title_tokens)
        self.assertIn("learning", p.title_tokens)

    def test_keywords_only_with_year(self):
        p = parse_partial("transformer attention all you need 2017")
        self.assertEqual(p.year, 2017)
        # No clear author signal — fine for it to be empty.
        self.assertIn("transformer", p.title_tokens)
        self.assertIn("attention", p.title_tokens)
        self.assertIn("need", p.title_tokens)

    def test_returns_partial_citation_dataclass(self):
        p = parse_partial("Smith 2020")
        self.assertIsInstance(p, PartialCitation)
        # frozen — should not allow mutation.
        with self.assertRaises(Exception):
            p.year = 2021  # type: ignore[misc]


class CitationResolverScoreTests(TestCase):
    """Scoring rewards alignment, punishes mismatch."""

    def test_high_score_when_aligned(self):
        partial = parse_partial("Vaswani 2017 Attention is all you need")
        candidate = {
            "title": "Attention is all you need",
            "authors": ["Ashish Vaswani", "Noam Shazeer"],
            "year": 2017,
            "doi": "10.48550/arXiv.1706.03762",
        }
        s = score_match(partial, candidate)
        self.assertGreater(s, 0.85)

    def test_low_when_authors_mismatch(self):
        partial = parse_partial("Vaswani 2017 Attention")
        candidate = {
            "title": "Attention is all you need",
            "authors": ["Someone Else", "Another Person"],
            "year": 2017,
        }
        s = score_match(partial, candidate)
        # Year + title match but author component is 0.
        self.assertLess(s, 0.6)

    def test_zero_when_nothing_aligns(self):
        partial = parse_partial("Smith 2020 Galactic Pancakes")
        candidate = {
            "title": "Quantum Cryptography Foundations",
            "authors": ["Bob Jones"],
            "year": 1999,
        }
        s = score_match(partial, candidate)
        self.assertLess(s, 0.1)

    def test_year_mismatch_penalized(self):
        partial = parse_partial("Vaswani 2017 Attention is all you need")
        wrong_year = {
            "title": "Attention is all you need",
            "authors": ["Ashish Vaswani"],
            "year": 1999,
        }
        right_year = {**wrong_year, "year": 2017}
        self.assertGreater(
            score_match(partial, right_year),
            score_match(partial, wrong_year),
        )

    def test_candidate_author_dict_shape(self):
        partial = parse_partial("Smith 2020 Widgets")
        cand = {
            "title": "Widgets",
            "authors": [{"name": "Jane Smith"}],
            "year": 2020,
        }
        s = score_match(partial, cand)
        self.assertGreater(s, 0.6)


class CitationResolverPickBestTests(TestCase):
    def test_returns_none_below_threshold(self):
        partial = parse_partial("Smith 2020 Galactic Pancakes")
        candidates = [
            {"title": "Something Else", "authors": ["Different"], "year": 1999},
        ]
        best, score = pick_best(partial, candidates)
        self.assertIsNone(best)
        self.assertEqual(score, 0.0)

    def test_picks_highest_above_threshold(self):
        partial = parse_partial("Vaswani 2017 Attention is all you need")
        candidates = [
            {"title": "Unrelated paper", "authors": ["Other"], "year": 2017},
            {
                "title": "Attention is all you need",
                "authors": ["Ashish Vaswani", "Noam Shazeer"],
                "year": 2017,
                "doi": "10.48550/arXiv.1706.03762",
            },
        ]
        best, score = pick_best(partial, candidates)
        self.assertIsNotNone(best)
        self.assertEqual(best["doi"], "10.48550/arXiv.1706.03762")
        self.assertGreaterEqual(score, 0.5)

    def test_empty_candidates(self):
        partial = parse_partial("anything")
        best, score = pick_best(partial, [])
        self.assertIsNone(best)
        self.assertEqual(score, 0.0)


class CitationResolverCLITests(TestCase):
    """End-to-end smoke test of the CLI."""

    def test_interactive_emits_partial(self):
        proc = subprocess.run(
            [sys.executable, str(_RESOLVE_PY), "--text",
             "Vaswani 2017 Attention", "--interactive"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["year"], 2017)
        self.assertIn("vaswani", out["authors"])
        self.assertIn("attention", out["title_tokens"])

    def test_candidates_file_match(self):
        candidates = [
            {
                "title": "Attention is all you need",
                "authors": ["Ashish Vaswani", "Noam Shazeer"],
                "year": 2017,
                "doi": "10.48550/arXiv.1706.03762",
            },
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8",
        ) as f:
            json.dump(candidates, f)
            cand_path = f.name

        proc = subprocess.run(
            [sys.executable, str(_RESOLVE_PY), "--text",
             "Vaswani 2017 Attention is all you need",
             "--candidates", cand_path],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        out = json.loads(proc.stdout)
        self.assertTrue(out["matched"])
        self.assertEqual(out["doi"], "10.48550/arXiv.1706.03762")
        self.assertIn("vaswani", out["canonical_id"])
        self.assertIn("2017", out["canonical_id"])

    def test_candidates_file_empty_returns_unmatched(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8",
        ) as f:
            json.dump([], f)
            cand_path = f.name

        proc = subprocess.run(
            [sys.executable, str(_RESOLVE_PY), "--text",
             "Vaswani 2017 Attention", "--candidates", cand_path],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        out = json.loads(proc.stdout)
        self.assertFalse(out["matched"])
        self.assertEqual(out["score"], 0.0)
