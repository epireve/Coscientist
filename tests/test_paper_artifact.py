"""Paper artifact regression tests — ensure the refactor didn't break it."""

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests


class PaperArtifactTests(TestCase):
    def test_canonical_id_is_deterministic(self):
        with isolated_cache():
            from lib.paper_artifact import canonical_id
            a = canonical_id(title="Attention is all you need", year=2017,
                             first_author="Vaswani", doi="10.1/abc")
            b = canonical_id(title="Attention is all you need", year=2017,
                             first_author="Vaswani", doi="10.1/abc")
            self.assertEqual(a, b)

    def test_state_machine(self):
        with isolated_cache():
            from lib.paper_artifact import PaperArtifact, State, canonical_id
            cid = canonical_id(title="Test", year=2020, first_author="Smith")
            art = PaperArtifact(cid)
            self.assertEqual(art.load_manifest().state, State.discovered)
            art.set_state(State.triaged)
            self.assertEqual(art.load_manifest().state, State.triaged)

    def test_record_source_attempt_append(self):
        with isolated_cache():
            from lib.paper_artifact import PaperArtifact, canonical_id
            cid = canonical_id(title="T", year=2020, first_author="S")
            art = PaperArtifact(cid)
            art.record_source_attempt("arxiv", "ok", {"chars": 1000})
            art.record_source_attempt("unpaywall", "failed")
            m = art.load_manifest()
            self.assertEqual(len(m.sources_tried), 2)
            self.assertEqual(m.sources_tried[0]["source"], "arxiv")

    def test_metadata_save_load_round_trip(self):
        with isolated_cache():
            from lib.paper_artifact import Metadata, PaperArtifact, canonical_id
            cid = canonical_id(title="T", year=2020, first_author="S")
            art = PaperArtifact(cid)
            art.save_metadata(Metadata(title="T", authors=["S"], year=2020, abstract="hi"))
            m = art.load_metadata()
            self.assertEqual(m.title, "T")
            self.assertEqual(m.year, 2020)

    def test_paths_under_cache(self):
        with isolated_cache() as cache_dir:
            from lib.paper_artifact import PaperArtifact, canonical_id
            cid = canonical_id(title="T", year=2020, first_author="S")
            art = PaperArtifact(cid)
            self.assertTrue(str(art.root).startswith(str(cache_dir)))
            self.assertTrue(art.figures_dir.exists())
            self.assertTrue(art.tables_dir.exists())
            self.assertTrue(art.raw_dir.exists())


if __name__ == "__main__":
    import sys
    sys.exit(run_tests(PaperArtifactTests))
