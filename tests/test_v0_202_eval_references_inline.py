"""v0.202 — eval_references inline-prose citation extractor.

Closes #16: false-positive orphans for canonical_ids cited inline in
brief.md prose. Previous behaviour matched only naked-line bullets,
producing 10 false orphans on the dogfood run.
"""

import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, run_tests

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
_SCRIPT_DIR = (
    _ROOT / ".claude" / "skills" / "research-eval" / "scripts"
)
sys.path.insert(0, str(_SCRIPT_DIR))

from eval_references import extract_cited_from_brief  # noqa: E402


class V0202InlineCitationTests(TestCase):
    def test_inline_mid_prose_recognised(self):
        # Inline citation embedded in prose.
        md = (
            "## Where the field disagrees\n\n"
            "Smith and colleagues argue X, citing `smith_2020_xyz_a1b2c3` "
            "as the foundational result.\n"
        )
        cids = extract_cited_from_brief(md)
        self.assertIn("smith_2020_xyz_a1b2c3", cids)

    def test_naked_line_recognised_back_compat(self):
        md = (
            "## Pivotal papers\n\n"
            "- `jones_2021_foo-bar_deadbe`\n"
            "- `kim_2019_baz_cafe01`\n"
        )
        cids = extract_cited_from_brief(md)
        self.assertIn("jones_2021_foo-bar_deadbe", cids)
        self.assertIn("kim_2019_baz_cafe01", cids)

    def test_both_forms_de_duped(self):
        md = (
            "Inline reference to `smith_2020_xyz_a1b2c3` here.\n"
            "\n"
            "And as a bullet:\n"
            "- `smith_2020_xyz_a1b2c3`\n"
        )
        cids = extract_cited_from_brief(md)
        self.assertEqual(len(cids), 1)
        self.assertIn("smith_2020_xyz_a1b2c3", cids)

    def test_unbacked_id_NOT_matched(self):
        # Defensive against false positives. A cid-shaped string
        # outside backticks (e.g. in a URL fragment or URL slug) must
        # NOT be matched.
        md = (
            "See https://example.org/papers/smith_2020_xyz_a1b2c3 "
            "for context.\n"
            "Also smith_2020_xyz_a1b2c3 written without backticks.\n"
        )
        cids = extract_cited_from_brief(md)
        self.assertEqual(len(cids), 0)

    def test_dogfood_shape_zero_orphans(self):
        # Simulate the dogfood failure: 10 cids cited inline in prose,
        # zero in naked-line bullets. Previously: 10 false orphans.
        # Now: all 10 recognised.
        cids_in = [
            f"author{chr(ord('a') + i)}_2024_topic_{i:06x}"
            for i in range(10)
        ]
        prose = "Recent work in this area "
        prose += " and ".join(f"`{c}`" for c in cids_in)
        prose += " converges on a common framework.\n"
        found = extract_cited_from_brief(prose)
        for c in cids_in:
            self.assertIn(c, found)
        self.assertEqual(len(found), 10)


if __name__ == "__main__":
    sys.exit(run_tests(V0202InlineCitationTests))
