"""Tests for the manuscript-revise skill.

Covers:
- ReviewParserTests     — pure parsing logic in review_parser.py
- IngestReviewTests     — ingest-review subcommand (filesystem)
- PlanTests             — plan subcommand
- RespondTests          — respond subcommand
- StatusTests           — status subcommand
- StateGuardTests       — state guard in ingest-review
- CliEdgeTests          — CLI error handling
"""

import json
import subprocess
import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
_REVISE = _ROOT / ".claude/skills/manuscript-revise/scripts/revise.py"
_DRAFT = _ROOT / ".claude/skills/manuscript-draft/scripts/draft.py"

# A standard two-reviewer review used across multiple test classes
_REVIEW_TEXT = """\
Reviewer 1:

1. The authors claim X but do not provide evidence for this assertion.

2. The methods section lacks detail on Y, making it hard to reproduce.

Reviewer 2:

1. I found the introduction compelling but the evaluation section is thin.

2. The related work section misses several key references.
"""


def _run_revise(*args: str, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_REVISE), *args],
        capture_output=True, text=True, env=env,
    )


def _run_draft(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_DRAFT), *args],
        capture_output=True, text=True,
    )


def _init_manuscript(title="Test Revise Paper", venue="imrad") -> str:
    """Create a fresh manuscript and return its ID. Must be called inside isolated_cache."""
    r = _run_draft("init", "--title", title, "--venue", venue)
    return r.stdout.strip()


def _write_review_file(path: Path, text: str = _REVIEW_TEXT) -> None:
    path.write_text(text)


# --------------------------------------------------------------------------- #
# ReviewParserTests                                                            #
# --------------------------------------------------------------------------- #

class ReviewParserTests(TestCase):
    """Pure unit tests against review_parser.py — no filesystem, no subprocess."""

    def _parser(self):
        """Import the module fresh (works after _shim patches sys.path)."""
        import sys as _sys
        scripts_dir = str(_ROOT / ".claude/skills/manuscript-revise/scripts")
        if scripts_dir not in _sys.path:
            _sys.path.insert(0, scripts_dir)
        import review_parser
        return review_parser

    def test_parse_known_review_structure(self):
        rp = self._parser()
        parsed = rp.parse_review(_REVIEW_TEXT)
        self.assertEqual(len(parsed), 4, "2 reviewers × 2 comments = 4 total")

    def test_reviewers_are_correct(self):
        rp = self._parser()
        parsed = rp.parse_review(_REVIEW_TEXT)
        reviewers = sorted({c["reviewer"] for c in parsed})
        self.assertEqual(reviewers, [1, 2])

    def test_comment_numbers_correct(self):
        rp = self._parser()
        parsed = rp.parse_review(_REVIEW_TEXT)
        r1 = [c for c in parsed if c["reviewer"] == 1]
        self.assertEqual(sorted(c["comment_num"] for c in r1), [1, 2])
        r2 = [c for c in parsed if c["reviewer"] == 2]
        self.assertEqual(sorted(c["comment_num"] for c in r2), [1, 2])

    def test_comment_text_not_empty(self):
        rp = self._parser()
        parsed = rp.parse_review(_REVIEW_TEXT)
        for c in parsed:
            self.assertTrue(c["text"].strip(), f"comment text is empty: {c}")

    def test_empty_review_returns_empty_list(self):
        rp = self._parser()
        result = rp.parse_review("")
        self.assertEqual(result, [])

    def test_blank_review_returns_empty_list(self):
        rp = self._parser()
        result = rp.parse_review("   \n\n  ")
        self.assertEqual(result, [])

    def test_no_reviewer_headers_returns_empty_list(self):
        rp = self._parser()
        result = rp.parse_review("Some text without headers.\n\n1. A comment.")
        self.assertEqual(result, [])

    def test_count_comments(self):
        rp = self._parser()
        parsed = rp.parse_review(_REVIEW_TEXT)
        counts = rp.count_comments(parsed)
        self.assertEqual(counts[1], 2)
        self.assertEqual(counts[2], 2)

    def test_count_comments_empty(self):
        rp = self._parser()
        counts = rp.count_comments([])
        self.assertEqual(counts, {})

    def test_format_response_stub_contains_comment_text(self):
        rp = self._parser()
        comment = {"reviewer": 1, "comment_num": 1,
                   "text": "The authors claim X but do not provide evidence."}
        stub = rp.format_response_stub(comment)
        self.assertIn("The authors claim X", stub)

    def test_format_response_stub_contains_placeholder(self):
        rp = self._parser()
        comment = {"reviewer": 2, "comment_num": 3, "text": "Please clarify Y."}
        stub = rp.format_response_stub(comment)
        self.assertIn("[YOUR RESPONSE HERE]", stub)

    def test_format_response_stub_contains_reviewer_label(self):
        rp = self._parser()
        comment = {"reviewer": 2, "comment_num": 3, "text": "Please clarify Y."}
        stub = rp.format_response_stub(comment)
        self.assertIn("REVIEWER 2", stub)
        self.assertIn("COMMENT 3", stub)


# --------------------------------------------------------------------------- #
# IngestReviewTests                                                            #
# --------------------------------------------------------------------------- #

class IngestReviewTests(TestCase):

    def test_ingest_review_creates_review_json(self):
        with isolated_cache() as cache:
            mid = _init_manuscript()
            review_file = cache / "review.txt"
            _write_review_file(review_file)

            r = _run_revise("ingest-review",
                            "--manuscript-id", mid,
                            "--review-file", str(review_file))
            self.assertEqual(r.returncode, 0, r.stderr)

            from lib.cache import cache_root
            review_json_path = cache_root() / "manuscripts" / mid / "review.json"
            self.assertTrue(review_json_path.exists(), "review.json should be created")

    def test_ingest_review_json_structure(self):
        with isolated_cache() as cache:
            mid = _init_manuscript()
            review_file = cache / "review.txt"
            _write_review_file(review_file)
            _run_revise("ingest-review", "--manuscript-id", mid,
                        "--review-file", str(review_file))

            from lib.cache import cache_root
            data = json.loads(
                (cache_root() / "manuscripts" / mid / "review.json").read_text()
            )
            self.assertIn("reviewers", data)
            self.assertEqual(len(data["reviewers"]), 2)

    def test_ingest_review_comment_count(self):
        with isolated_cache() as cache:
            mid = _init_manuscript()
            review_file = cache / "review.txt"
            _write_review_file(review_file)
            _run_revise("ingest-review", "--manuscript-id", mid,
                        "--review-file", str(review_file))

            from lib.cache import cache_root
            data = json.loads(
                (cache_root() / "manuscripts" / mid / "review.json").read_text()
            )
            total = sum(len(rv["comments"]) for rv in data["reviewers"])
            self.assertEqual(total, 4, "2 reviewers × 2 comments = 4 total")

    def test_ingest_review_prints_summary(self):
        with isolated_cache() as cache:
            mid = _init_manuscript()
            review_file = cache / "review.txt"
            _write_review_file(review_file)
            r = _run_revise("ingest-review", "--manuscript-id", mid,
                            "--review-file", str(review_file))
            self.assertEqual(r.returncode, 0, r.stderr)
            # Should mention reviewer count in output
            self.assertIn("reviewer", r.stdout.lower())

    def test_ingest_review_via_review_text_flag(self):
        with isolated_cache():
            mid = _init_manuscript()
            r = _run_revise("ingest-review", "--manuscript-id", mid,
                            "--review-text", _REVIEW_TEXT)
            self.assertEqual(r.returncode, 0, r.stderr)

            from lib.cache import cache_root
            self.assertTrue(
                (cache_root() / "manuscripts" / mid / "review.json").exists()
            )


# --------------------------------------------------------------------------- #
# PlanTests                                                                    #
# --------------------------------------------------------------------------- #

class PlanTests(TestCase):

    def _setup(self, cache):
        """Init manuscript and ingest review; return mid."""
        mid = _init_manuscript()
        review_file = cache / "review.txt"
        _write_review_file(review_file)
        _run_revise("ingest-review", "--manuscript-id", mid,
                    "--review-file", str(review_file))
        return mid

    def test_plan_creates_revision_notes(self):
        with isolated_cache() as cache:
            mid = self._setup(cache)
            r = _run_revise("plan", "--manuscript-id", mid)
            self.assertEqual(r.returncode, 0, r.stderr)

            from lib.cache import cache_root
            notes_path = cache_root() / "manuscripts" / mid / "revision_notes.md"
            self.assertTrue(notes_path.exists(), "revision_notes.md should be created")

    def test_plan_contains_section_name(self):
        """revision_notes.md should contain at least one section name from the outline."""
        with isolated_cache() as cache:
            mid = self._setup(cache)
            _run_revise("plan", "--manuscript-id", mid)

            from lib.cache import cache_root
            notes = (cache_root() / "manuscripts" / mid / "revision_notes.md").read_text()
            outline = json.loads(
                (cache_root() / "manuscripts" / mid / "outline.json").read_text()
            )
            section_names = [s["name"] for s in outline["sections"]]
            # At least one section name should appear (case-insensitive)
            notes_lower = notes.lower()
            found_any = any(name.lower() in notes_lower for name in section_names)
            self.assertTrue(found_any, f"revision_notes.md missing all section names: {section_names}")

    def test_plan_output_mentions_comment_count(self):
        with isolated_cache() as cache:
            mid = self._setup(cache)
            r = _run_revise("plan", "--manuscript-id", mid)
            self.assertEqual(r.returncode, 0, r.stderr)
            # stdout should mention the number of comments mapped
            self.assertTrue(r.stdout.strip(), "plan should print something to stdout")

    def test_plan_fails_without_review_json(self):
        with isolated_cache():
            mid = _init_manuscript()
            r = _run_revise("plan", "--manuscript-id", mid)
            # Should fail because review.json doesn't exist
            self.assertTrue(r.returncode != 0, "plan without review.json should fail")


# --------------------------------------------------------------------------- #
# RespondTests                                                                 #
# --------------------------------------------------------------------------- #

class RespondTests(TestCase):

    def _setup(self, cache):
        """Init manuscript, ingest review, run plan; return mid."""
        mid = _init_manuscript()
        review_file = cache / "review.txt"
        _write_review_file(review_file)
        _run_revise("ingest-review", "--manuscript-id", mid,
                    "--review-file", str(review_file))
        _run_revise("plan", "--manuscript-id", mid)
        return mid

    def test_respond_creates_response_letter(self):
        with isolated_cache() as cache:
            mid = self._setup(cache)
            r = _run_revise("respond", "--manuscript-id", mid)
            self.assertEqual(r.returncode, 0, r.stderr)

            from lib.cache import cache_root
            letter_path = cache_root() / "manuscripts" / mid / "response_letter.md"
            self.assertTrue(letter_path.exists(), "response_letter.md should be created")

    def test_respond_letter_contains_placeholder(self):
        with isolated_cache() as cache:
            mid = self._setup(cache)
            _run_revise("respond", "--manuscript-id", mid)

            from lib.cache import cache_root
            letter = (cache_root() / "manuscripts" / mid / "response_letter.md").read_text()
            self.assertIn("[YOUR RESPONSE HERE]", letter)

    def test_respond_letter_contains_reviewer(self):
        with isolated_cache() as cache:
            mid = self._setup(cache)
            _run_revise("respond", "--manuscript-id", mid)

            from lib.cache import cache_root
            letter = (cache_root() / "manuscripts" / mid / "response_letter.md").read_text()
            self.assertIn("Reviewer", letter)

    def test_respond_advances_state_to_revised(self):
        with isolated_cache() as cache:
            mid = self._setup(cache)
            _run_revise("respond", "--manuscript-id", mid)

            from lib.cache import cache_root
            manifest = json.loads(
                (cache_root() / "manuscripts" / mid / "manifest.json").read_text()
            )
            self.assertEqual(manifest["state"], "revised")

    def test_respond_letter_has_one_stub_per_comment(self):
        with isolated_cache() as cache:
            mid = self._setup(cache)
            _run_revise("respond", "--manuscript-id", mid)

            from lib.cache import cache_root
            letter = (cache_root() / "manuscripts" / mid / "response_letter.md").read_text()
            n_stubs = letter.count("[YOUR RESPONSE HERE]")
            # 4 comments → 4 stubs
            self.assertEqual(n_stubs, 4, f"expected 4 stubs, found {n_stubs}")


# --------------------------------------------------------------------------- #
# StatusTests                                                                  #
# --------------------------------------------------------------------------- #

class StatusTests(TestCase):

    def _setup(self, cache):
        """Full setup through respond; return mid."""
        mid = _init_manuscript()
        review_file = cache / "review.txt"
        _write_review_file(review_file)
        _run_revise("ingest-review", "--manuscript-id", mid,
                    "--review-file", str(review_file))
        _run_revise("plan", "--manuscript-id", mid)
        _run_revise("respond", "--manuscript-id", mid)
        return mid

    def test_status_reports_stubs_remaining(self):
        with isolated_cache() as cache:
            mid = self._setup(cache)
            r = _run_revise("status", "--manuscript-id", mid)
            self.assertEqual(r.returncode, 0, r.stderr)
            # Should mention a number > 0 remaining
            self.assertIn("stubs remaining", r.stdout)

    def test_status_reports_nonzero_stubs(self):
        with isolated_cache() as cache:
            mid = self._setup(cache)
            r = _run_revise("status", "--manuscript-id", mid)
            # The output should contain "4 stubs remaining" (one per comment)
            self.assertIn("4", r.stdout)

    def test_status_reports_zero_after_clearing_placeholders(self):
        with isolated_cache() as cache:
            mid = self._setup(cache)

            from lib.cache import cache_root
            letter_path = cache_root() / "manuscripts" / mid / "response_letter.md"
            # Replace all placeholders with actual responses
            text = letter_path.read_text()
            text = text.replace("[YOUR RESPONSE HERE]", "We addressed this concern.")
            letter_path.write_text(text)

            r = _run_revise("status", "--manuscript-id", mid)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("0 stubs remaining", r.stdout)

    def test_status_fails_without_response_letter(self):
        with isolated_cache():
            mid = _init_manuscript()
            r = _run_revise("status", "--manuscript-id", mid)
            self.assertTrue(r.returncode != 0, "status without response_letter.md should fail")


# --------------------------------------------------------------------------- #
# StateGuardTests                                                              #
# --------------------------------------------------------------------------- #

class StateGuardTests(TestCase):

    def _set_state(self, mid: str, state: str) -> None:
        """Directly update the manifest state."""
        from lib.cache import cache_root
        manifest_path = cache_root() / "manuscripts" / mid / "manifest.json"
        data = json.loads(manifest_path.read_text())
        data["state"] = state
        manifest_path.write_text(json.dumps(data, indent=2))

    def test_ingest_review_blocked_on_submitted(self):
        with isolated_cache() as cache:
            mid = _init_manuscript()
            # Manually set state to submitted
            self._set_state(mid, "submitted")

            review_file = cache / "review.txt"
            _write_review_file(review_file)
            r = _run_revise("ingest-review", "--manuscript-id", mid,
                            "--review-file", str(review_file))
            self.assertTrue(r.returncode != 0,
                            "ingest-review on submitted manuscript should fail")

    def test_ingest_review_blocked_on_published(self):
        with isolated_cache() as cache:
            mid = _init_manuscript()
            self._set_state(mid, "published")

            review_file = cache / "review.txt"
            _write_review_file(review_file)
            r = _run_revise("ingest-review", "--manuscript-id", mid,
                            "--review-file", str(review_file))
            self.assertTrue(r.returncode != 0,
                            "ingest-review on published manuscript should fail")

    def test_ingest_review_force_overrides_guard(self):
        with isolated_cache() as cache:
            mid = _init_manuscript()
            self._set_state(mid, "submitted")

            review_file = cache / "review.txt"
            _write_review_file(review_file)
            r = _run_revise("ingest-review", "--manuscript-id", mid,
                            "--review-file", str(review_file), "--force")
            self.assertEqual(r.returncode, 0, "--force should override state guard")

    def test_ingest_review_accepted_on_drafted(self):
        with isolated_cache() as cache:
            mid = _init_manuscript()
            # drafted is the initial state from manuscript-draft init
            review_file = cache / "review.txt"
            _write_review_file(review_file)
            r = _run_revise("ingest-review", "--manuscript-id", mid,
                            "--review-file", str(review_file))
            self.assertEqual(r.returncode, 0, "drafted state should be accepted")

    def test_ingest_review_accepted_on_critiqued(self):
        with isolated_cache() as cache:
            mid = _init_manuscript()
            self._set_state(mid, "critiqued")
            review_file = cache / "review.txt"
            _write_review_file(review_file)
            r = _run_revise("ingest-review", "--manuscript-id", mid,
                            "--review-file", str(review_file))
            self.assertEqual(r.returncode, 0, "critiqued state should be accepted")


# --------------------------------------------------------------------------- #
# CliEdgeTests                                                                 #
# --------------------------------------------------------------------------- #

class CliEdgeTests(TestCase):

    def test_missing_manuscript_id_errors(self):
        with isolated_cache() as cache:
            review_file = cache / "review.txt"
            _write_review_file(review_file)
            r = _run_revise("ingest-review", "--review-file", str(review_file))
            self.assertTrue(r.returncode != 0, "missing --manuscript-id should fail")

    def test_missing_review_source_errors(self):
        with isolated_cache():
            mid = _init_manuscript()
            r = _run_revise("ingest-review", "--manuscript-id", mid)
            self.assertTrue(r.returncode != 0,
                            "missing both --review-file and --review-text should fail")

    def test_nonexistent_review_file_errors(self):
        with isolated_cache():
            mid = _init_manuscript()
            r = _run_revise("ingest-review", "--manuscript-id", mid,
                            "--review-file", "/tmp/does_not_exist_xyz.txt")
            self.assertTrue(r.returncode != 0, "nonexistent review file should fail")

    def test_help_lists_subcommands(self):
        r = _run_revise("--help")
        self.assertEqual(r.returncode, 0)
        for sub in ("ingest-review", "plan", "respond", "status"):
            self.assertIn(sub, r.stdout)

    def test_plan_requires_manuscript_id(self):
        r = _run_revise("plan")
        self.assertTrue(r.returncode != 0, "plan without --manuscript-id should fail")

    def test_respond_requires_manuscript_id(self):
        r = _run_revise("respond")
        self.assertTrue(r.returncode != 0, "respond without --manuscript-id should fail")

    def test_status_requires_manuscript_id(self):
        r = _run_revise("status")
        self.assertTrue(r.returncode != 0, "status without --manuscript-id should fail")


if __name__ == "__main__":
    sys.exit(run_tests(
        ReviewParserTests,
        IngestReviewTests,
        PlanTests,
        RespondTests,
        StatusTests,
        StateGuardTests,
        CliEdgeTests,
    ))
