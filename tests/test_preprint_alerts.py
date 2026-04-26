"""Tests for the preprint-alerts skill."""
from __future__ import annotations
import importlib.util as _ilu, json, sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from tests.harness import CoscientistTestCase, isolated_cache  # noqa


def _load(name):
    spec = _ilu.spec_from_file_location(
        name, _REPO_ROOT / ".claude/skills/preprint-alerts/scripts" / f"{name}.py"
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SAMPLE_PAPERS = [
    {"title": "Attention is All You Need", "abstract": "We propose the transformer architecture.",
     "authors": ["Vaswani", "Shazeer"], "source": "arxiv", "arxiv_id": "1706.03762"},
    {"title": "BERT Pre-training", "abstract": "Bidirectional encoder representations.",
     "authors": ["Devlin", "Chang"], "source": "arxiv", "arxiv_id": "1810.04805"},
    {"title": "Protein Folding with AlphaFold", "abstract": "Deep learning for biology.",
     "authors": ["Jumper", "Hassabis"], "source": "biorxiv", "arxiv_id": None},
    {"title": "Climate Modeling", "abstract": "Atmospheric simulation methods.",
     "authors": ["Smith", "Jones"], "source": "arxiv", "arxiv_id": None},
]


class SubscribeTests(CoscientistTestCase):
    def test_subscribe_creates_file(self):
        with isolated_cache() as cache:
            mod = _load("subscribe")
            result = mod.subscribe("proj1", ["transformer"], ["Vaswani"], ["arxiv"])
            p = cache / "projects/proj1/preprint_alerts/subscription.json"
            self.assertTrue(p.exists())
            self.assertIn("transformer", result["topics"])

    def test_subscribe_merges_by_default(self):
        with isolated_cache():
            mod = _load("subscribe")
            mod.subscribe("proj2", ["transformer"], ["Vaswani"], ["arxiv"])
            mod.subscribe("proj2", ["bert"], ["Devlin"], ["arxiv"])
            sub = mod.load_subscription("proj2")
            self.assertIn("transformer", sub["topics"])
            self.assertIn("bert", sub["topics"])
            self.assertIn("Vaswani", sub["authors"])
            self.assertIn("Devlin", sub["authors"])

    def test_subscribe_replace_clears_existing(self):
        with isolated_cache():
            mod = _load("subscribe")
            mod.subscribe("proj3", ["transformer"], ["Vaswani"], ["arxiv"])
            mod.subscribe("proj3", ["bert"], [], ["arxiv"], merge=False)
            sub = mod.load_subscription("proj3")
            self.assertNotIn("transformer", sub["topics"])
            self.assertIn("bert", sub["topics"])

    def test_invalid_source_raises(self):
        with isolated_cache():
            mod = _load("subscribe")
            with self.assertRaises(ValueError):
                mod.subscribe("proj4", [], [], ["bogus"])

    def test_empty_subscription(self):
        with isolated_cache():
            mod = _load("subscribe")
            result = mod.subscribe("proj5", [], [], ["arxiv"])
            self.assertEqual(result["topics"], [])
            self.assertEqual(result["authors"], [])

    def test_load_subscription_missing_returns_default(self):
        with isolated_cache():
            mod = _load("subscribe")
            sub = mod.load_subscription("proj_noexist")
            self.assertEqual(sub["topics"], [])


class DigestTests(CoscientistTestCase):
    def _sub(self, project_id, topics, authors, sources=None):
        mod = _load("subscribe")
        mod.subscribe(project_id, topics, authors, sources or ["arxiv", "biorxiv"])

    def test_matches_by_topic_in_title(self):
        with isolated_cache():
            self._sub("d1", ["transformer"], [])
            mod = _load("digest")
            result = mod.write_digest("d1", SAMPLE_PAPERS, "2026-04-26")
            self.assertEqual(result["n_matched"], 1)
            self.assertEqual(result["matches"][0]["title"], "Attention is All You Need")

    def test_matches_by_topic_in_abstract(self):
        with isolated_cache():
            self._sub("d2", ["bidirectional"], [])
            mod = _load("digest")
            result = mod.write_digest("d2", SAMPLE_PAPERS, "2026-04-26")
            self.assertEqual(result["n_matched"], 1)

    def test_matches_by_author(self):
        with isolated_cache():
            self._sub("d3", [], ["Jumper"])
            mod = _load("digest")
            result = mod.write_digest("d3", SAMPLE_PAPERS, "2026-04-26")
            self.assertEqual(result["n_matched"], 1)
            self.assertIn("Jumper", result["matches"][0]["matched_authors"])

    def test_source_filter(self):
        with isolated_cache():
            mod_sub = _load("subscribe")
            mod_sub.subscribe("d4", ["deep"], [], ["arxiv"])  # no biorxiv
            mod = _load("digest")
            result = mod.write_digest("d4", SAMPLE_PAPERS, "2026-04-26")
            # AlphaFold is biorxiv — should be excluded
            sources = [m["source"] for m in result["matches"]]
            self.assertNotIn("biorxiv", sources)

    def test_no_match(self):
        with isolated_cache():
            self._sub("d5", ["quantum"], ["Einstein"])
            mod = _load("digest")
            result = mod.write_digest("d5", SAMPLE_PAPERS, "2026-04-26")
            self.assertEqual(result["n_matched"], 0)

    def test_digest_file_written(self):
        with isolated_cache() as cache:
            self._sub("d6", ["transformer"], [])
            mod = _load("digest")
            mod.write_digest("d6", SAMPLE_PAPERS, "2026-04-26")
            p = cache / "projects/d6/preprint_alerts/digest_2026-04-26.json"
            self.assertTrue(p.exists())

    def test_n_candidates_correct(self):
        with isolated_cache():
            self._sub("d7", ["transformer"], [])
            mod = _load("digest")
            result = mod.write_digest("d7", SAMPLE_PAPERS, "2026-04-26")
            self.assertEqual(result["n_candidates"], len(SAMPLE_PAPERS))

    def test_matched_topics_recorded(self):
        with isolated_cache():
            self._sub("d8", ["transformer", "encoder"], [])
            mod = _load("digest")
            result = mod.write_digest("d8", SAMPLE_PAPERS, "2026-04-26")
            for m in result["matches"]:
                self.assertIsInstance(m["matched_topics"], list)


class ListSubsTests(CoscientistTestCase):
    def test_no_subscription_returns_empty(self):
        with isolated_cache():
            mod = _load("list_subs")
            result = mod.get_subscription("noexist")
            self.assertEqual(result["status"], "no_subscription")

    def test_active_subscription(self):
        with isolated_cache():
            mod_sub = _load("subscribe")
            mod_sub.subscribe("ls1", ["transformer"], [], ["arxiv"])
            mod = _load("list_subs")
            result = mod.get_subscription("ls1")
            self.assertEqual(result["status"], "active")
            self.assertIn("transformer", result["topics"])

    def test_table_format(self):
        with isolated_cache():
            mod_sub = _load("subscribe")
            mod_sub.subscribe("ls2", ["bert"], ["Devlin"], ["arxiv"])
            mod = _load("list_subs")
            sub = mod.get_subscription("ls2")
            table = mod._render_table(sub)
            self.assertIn("bert", table)
            self.assertIn("Devlin", table)


class HistoryTests(CoscientistTestCase):
    def test_no_digests_returns_empty(self):
        with isolated_cache():
            mod = _load("history")
            result = mod.list_history("noexist")
            self.assertEqual(result, [])

    def test_history_lists_digests(self):
        with isolated_cache():
            mod_sub = _load("subscribe")
            mod_sub.subscribe("h1", ["transformer"], [], ["arxiv"])
            mod_d = _load("digest")
            mod_d.write_digest("h1", SAMPLE_PAPERS, "2026-04-24")
            mod_d.write_digest("h1", SAMPLE_PAPERS, "2026-04-25")
            mod_h = _load("history")
            result = mod_h.list_history("h1")
            self.assertEqual(len(result), 2)
            dates = [r["date"] for r in result]
            self.assertIn("2026-04-24", dates)

    def test_history_limit(self):
        with isolated_cache():
            mod_sub = _load("subscribe")
            mod_sub.subscribe("h2", ["transformer"], [], ["arxiv"])
            mod_d = _load("digest")
            for d in range(1, 6):
                mod_d.write_digest("h2", SAMPLE_PAPERS, f"2026-04-{d:02d}")
            mod_h = _load("history")
            result = mod_h.list_history("h2", limit=3)
            self.assertEqual(len(result), 3)

    def test_history_sorted_newest_first(self):
        with isolated_cache():
            mod_sub = _load("subscribe")
            mod_sub.subscribe("h3", ["transformer"], [], ["arxiv"])
            mod_d = _load("digest")
            mod_d.write_digest("h3", SAMPLE_PAPERS, "2026-04-01")
            mod_d.write_digest("h3", SAMPLE_PAPERS, "2026-04-10")
            mod_h = _load("history")
            result = mod_h.list_history("h3")
            self.assertGreater(result[0]["date"], result[1]["date"])
