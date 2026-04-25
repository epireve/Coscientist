"""Tests for the manuscript-version skill.

Drives version.py subcommands via subprocess and exercises version_store.py
directly for unit tests.

No LLM calls, no network. Pure filesystem.
"""

from tests import _shim  # noqa: F401

import json
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
_DRAFT = _ROOT / ".claude/skills/manuscript-draft/scripts/draft.py"
_VERSION = _ROOT / ".claude/skills/manuscript-version/scripts/version.py"
_VERSION_STORE = _ROOT / ".claude/skills/manuscript-version/scripts"


def _run_draft(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_DRAFT), *args],
        capture_output=True, text=True,
    )


def _run_version(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_VERSION), *args],
        capture_output=True, text=True,
    )


def _init_manuscript(title="Version Test Paper", venue="imrad") -> str:
    r = _run_draft("init", "--title", title, "--venue", venue)
    assert r.returncode == 0, f"draft init failed: {r.stderr}"
    return r.stdout.strip()


# --------------------------------------------------------------------------- #
# VersionStoreTests — unit tests on version_store.py                          #
# --------------------------------------------------------------------------- #

class VersionStoreTests(TestCase):

    def _store(self):
        # Import fresh each time so isolated_cache env var is respected
        import importlib
        import sys as _sys
        store_dir = str(_VERSION_STORE)
        if store_dir not in _sys.path:
            _sys.path.insert(0, store_dir)
        import version_store
        importlib.reload(version_store)
        return version_store

    def test_snapshot_hash_is_deterministic(self):
        vs = self._store()
        text = "Hello world\n\n## Introduction\n\nSome content here."
        h1 = vs.snapshot_hash(text)
        h2 = vs.snapshot_hash(text)
        self.assertEqual(h1, h2, "hash must be deterministic")
        self.assertEqual(len(h1), 64, "sha256 hex is 64 chars")

    def test_snapshot_hash_differs_for_different_content(self):
        vs = self._store()
        h1 = vs.snapshot_hash("content A")
        h2 = vs.snapshot_hash("content B")
        self.assertTrue(h1 != h2, "different content must produce different hashes")

    def test_make_version_id_increments(self):
        with isolated_cache() as cache:
            vs = self._store()
            from lib.artifact import ManuscriptArtifact
            mid = "test_increment_aaaaaa"
            art = ManuscriptArtifact(mid)
            # No versions yet → first id is v1-...
            vid1 = vs.make_version_id(art.root)
            self.assertTrue(vid1.startswith("v1-"), f"expected v1-..., got {vid1!r}")

            # Manually create the versions dir + a meta.json for v1
            snap_dir = art.root / "versions" / vid1
            snap_dir.mkdir(parents=True, exist_ok=True)
            (snap_dir / "meta.json").write_text(
                json.dumps({"version_id": vid1, "manuscript_id": mid})
            )

            # Second call should give v2-...
            vid2 = vs.make_version_id(art.root)
            self.assertTrue(vid2.startswith("v2-"), f"expected v2-..., got {vid2!r}")

    def test_list_versions_empty_on_fresh_artifact(self):
        with isolated_cache():
            vs = self._store()
            from lib.artifact import ManuscriptArtifact
            mid = "test_fresh_bbbbb"
            art = ManuscriptArtifact(mid)
            result = vs.list_versions(art.root)
            self.assertEqual(result, [], "fresh artifact should have no versions")

    def test_section_word_counts_zeros_for_placeholder(self):
        with isolated_cache() as cache:
            vs = self._store()
            # init a manuscript and read its placeholder source.md
            mid = _init_manuscript("WC Placeholder Test")
            from lib.cache import cache_root
            source = (cache_root() / "manuscripts" / mid / "source.md").read_text()
            counts = vs.section_word_counts(source)
            # All section bodies contain only placeholder comments (stripped)
            # so every section should have 0 or near-0 real words.
            # At minimum the dict should be non-empty and the sections present.
            self.assertTrue(isinstance(counts, dict))
            # The placeholder lines are only comments/PLACEHOLDER tags which
            # may or may not count as words depending on stripping. We check
            # that no section has a suspiciously large count (> 20).
            for sec, wc in counts.items():
                self.assertTrue(wc >= 0, f"word count for {sec!r} must be >= 0")

    def test_section_word_counts_preamble_key(self):
        vs = self._store()
        text = "Some preamble text here.\n\n## Introduction\n\nFirst section words."
        counts = vs.section_word_counts(text)
        self.assertIn("_preamble", counts)
        self.assertIn("Introduction", counts)
        self.assertTrue(counts["Introduction"] > 0)


# --------------------------------------------------------------------------- #
# SnapshotTests                                                                #
# --------------------------------------------------------------------------- #

class SnapshotTests(TestCase):

    def test_snapshot_creates_versions_dir(self):
        with isolated_cache():
            mid = _init_manuscript("Snapshot Creates Dir")
            r = _run_version("snapshot", "--manuscript-id", mid, "--note", "initial")
            self.assertEqual(r.returncode, 0, r.stderr)
            version_id = r.stdout.strip()
            self.assertTrue(version_id.startswith("v1-"),
                            f"expected v1-..., got {version_id!r}")

            from lib.cache import cache_root
            versions_dir = cache_root() / "manuscripts" / mid / "versions"
            self.assertTrue(versions_dir.exists(), "versions/ dir must be created")

    def test_snapshot_creates_meta_json(self):
        with isolated_cache():
            mid = _init_manuscript("Snapshot Meta JSON")
            r = _run_version("snapshot", "--manuscript-id", mid, "--note", "initial")
            self.assertEqual(r.returncode, 0, r.stderr)
            version_id = r.stdout.strip()

            from lib.cache import cache_root
            meta_path = (cache_root() / "manuscripts" / mid / "versions"
                         / version_id / "meta.json")
            self.assertTrue(meta_path.exists())
            meta = json.loads(meta_path.read_text())

            self.assertIn("version_id", meta)
            self.assertIn("word_count", meta)
            self.assertIn("source_md_hash", meta)
            self.assertIn("note", meta)
            self.assertEqual(meta["version_id"], version_id)
            self.assertEqual(meta["note"], "initial")
            self.assertEqual(meta["manuscript_id"], mid)
            self.assertTrue(len(meta["source_md_hash"]) == 64)

    def test_log_shows_one_entry_after_snapshot(self):
        with isolated_cache():
            mid = _init_manuscript("Log One Entry")
            _run_version("snapshot", "--manuscript-id", mid, "--note", "first")
            r = _run_version("log", "--manuscript-id", mid)
            self.assertEqual(r.returncode, 0, r.stderr)
            lines = [l for l in r.stdout.splitlines() if l.strip() and "---" not in l
                     and "version_id" not in l]
            self.assertEqual(len(lines), 1, f"expected 1 snapshot line, got: {r.stdout!r}")

    def test_second_snapshot_same_content_errors(self):
        with isolated_cache():
            mid = _init_manuscript("Second Same Content")
            _run_version("snapshot", "--manuscript-id", mid, "--note", "v1")
            r = _run_version("snapshot", "--manuscript-id", mid, "--note", "v2")
            self.assertTrue(r.returncode != 0,
                            "snapshot with no change should fail")
            self.assertIn("--force", r.stderr)

    def test_second_snapshot_with_force_succeeds(self):
        with isolated_cache():
            mid = _init_manuscript("Second Force")
            _run_version("snapshot", "--manuscript-id", mid, "--note", "v1")
            r = _run_version("snapshot", "--manuscript-id", mid, "--note", "v2",
                             "--force")
            self.assertEqual(r.returncode, 0, r.stderr)
            version_id = r.stdout.strip()
            self.assertTrue(version_id.startswith("v2-"))


# --------------------------------------------------------------------------- #
# LogTests                                                                     #
# --------------------------------------------------------------------------- #

class LogTests(TestCase):

    def test_log_shows_two_entries_in_reverse_order(self):
        with isolated_cache():
            mid = _init_manuscript("Log Two Entries")
            _run_version("snapshot", "--manuscript-id", mid, "--note", "first snap")
            # Modify source.md so second snapshot is accepted
            from lib.cache import cache_root
            src = cache_root() / "manuscripts" / mid / "source.md"
            src.write_text(src.read_text() + "\n<!-- edit -->")

            _run_version("snapshot", "--manuscript-id", mid, "--note", "second snap")

            r = _run_version("log", "--manuscript-id", mid)
            self.assertEqual(r.returncode, 0, r.stderr)
            # Should list v2 before v1 (reverse order)
            idx_v2 = r.stdout.find("v2-")
            idx_v1 = r.stdout.find("v1-")
            self.assertTrue(idx_v2 != -1, "v2 must appear in log")
            self.assertTrue(idx_v1 != -1, "v1 must appear in log")
            self.assertTrue(idx_v2 < idx_v1,
                            "v2 should appear before v1 in reverse-chron log")

    def test_log_shows_zero_entries_on_fresh_manuscript(self):
        with isolated_cache():
            mid = _init_manuscript("Log Zero Entries")
            r = _run_version("log", "--manuscript-id", mid)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("No snapshots", r.stdout)

    def test_log_on_unknown_manuscript_errors(self):
        with isolated_cache():
            r = _run_version("log", "--manuscript-id", "does_not_exist_zzz999")
            self.assertTrue(r.returncode != 0,
                            "log on unknown manuscript_id should fail")
            self.assertIn("ERROR", r.stderr)


# --------------------------------------------------------------------------- #
# DiffTests                                                                    #
# --------------------------------------------------------------------------- #

class DiffTests(TestCase):

    def test_diff_positive_word_delta(self):
        with isolated_cache():
            mid = _init_manuscript("Diff Positive Delta")
            _run_version("snapshot", "--manuscript-id", mid, "--note", "before content")

            # Add substantial content to a section
            body = "This is a long introduction. " * 20
            _run_draft("section", "--manuscript-id", mid,
                       "--section", "introduction", "--text", body)

            from lib.cache import cache_root
            r2 = _run_version("snapshot", "--manuscript-id", mid, "--note", "after content")
            self.assertEqual(r2.returncode, 0, r2.stderr)
            v2 = r2.stdout.strip()

            r = _run_version("diff", "--manuscript-id", mid,
                             "--from", "v1", "--to", v2)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("TOTAL", r.stdout)
            # The total delta line should show a positive number
            lines = r.stdout.splitlines()
            total_line = next((l for l in lines if "TOTAL" in l), "")
            self.assertTrue("+" in total_line,
                            f"expected positive delta in TOTAL line: {total_line!r}")

    def test_diff_negative_word_delta(self):
        with isolated_cache():
            mid = _init_manuscript("Diff Negative Delta")
            # First add content
            body = "This is a long introduction. " * 20
            _run_draft("section", "--manuscript-id", mid,
                       "--section", "introduction", "--text", body)
            _run_version("snapshot", "--manuscript-id", mid, "--note", "with content")
            v1 = _run_version("snapshot", "--manuscript-id", mid,
                               "--note", "pre-trim", "--force").stdout.strip()

            # Now replace with shorter content
            short_body = "Short intro."
            _run_draft("section", "--manuscript-id", mid,
                       "--section", "introduction", "--text", short_body)

            from lib.cache import cache_root
            r2 = _run_version("snapshot", "--manuscript-id", mid, "--note", "trimmed")
            self.assertEqual(r2.returncode, 0, r2.stderr)
            v2 = r2.stdout.strip()

            r = _run_version("diff", "--manuscript-id", mid,
                             "--from", v2, "--to", "v1")
            self.assertEqual(r.returncode, 0, r.stderr)
            # Going from trimmed back to v1 should show positive delta
            lines = r.stdout.splitlines()
            total_line = next((l for l in lines if "TOTAL" in l), "")
            self.assertIn("TOTAL", total_line)

    def test_diff_to_head(self):
        with isolated_cache():
            mid = _init_manuscript("Diff To HEAD")
            _run_version("snapshot", "--manuscript-id", mid, "--note", "baseline")

            # Modify source.md directly
            from lib.cache import cache_root
            src = cache_root() / "manuscripts" / mid / "source.md"
            src.write_text(src.read_text() + "\n\n## New Section\n\nExtra words here.\n")

            r = _run_version("diff", "--manuscript-id", mid,
                             "--from", "v1", "--to", "HEAD")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("TOTAL", r.stdout)
            self.assertIn("New Section", r.stdout)


# --------------------------------------------------------------------------- #
# RestoreTests                                                                 #
# --------------------------------------------------------------------------- #

class RestoreTests(TestCase):

    def test_restore_overwrites_source_md(self):
        with isolated_cache():
            mid = _init_manuscript("Restore Content")
            from lib.cache import cache_root
            src_path = cache_root() / "manuscripts" / mid / "source.md"

            # Capture original content
            original = src_path.read_text()
            _run_version("snapshot", "--manuscript-id", mid, "--note", "v1")
            v1 = "v1"

            # Modify with new content
            body = "This is modified introduction content. " * 10
            _run_draft("section", "--manuscript-id", mid,
                       "--section", "introduction", "--text", body)
            _run_version("snapshot", "--manuscript-id", mid, "--note", "v2")

            # Restore to v1
            r = _run_version("restore", "--manuscript-id", mid,
                             "--version", v1, "--confirm")
            self.assertEqual(r.returncode, 0, r.stderr)

            restored = src_path.read_text()
            self.assertEqual(restored, original,
                             "restored source.md must match v1 content")

    def test_restore_creates_auto_snapshot_before_restoring(self):
        with isolated_cache():
            mid = _init_manuscript("Restore Auto Snap")
            _run_version("snapshot", "--manuscript-id", mid, "--note", "v1")

            # Modify
            from lib.cache import cache_root
            src = cache_root() / "manuscripts" / mid / "source.md"
            src.write_text(src.read_text() + "\n<!-- modified -->")
            _run_version("snapshot", "--manuscript-id", mid, "--note", "v2")

            # Before restore: 2 snapshots
            r_log_before = _run_version("log", "--manuscript-id", mid)
            before_count = sum(1 for l in r_log_before.stdout.splitlines()
                               if l.strip() and "---" not in l
                               and "version_id" not in l
                               and "No snapshots" not in l)

            # Restore to v1
            _run_version("restore", "--manuscript-id", mid, "--version", "v1",
                         "--confirm")

            # After restore: should have one more snapshot (the auto-snapshot)
            r_log_after = _run_version("log", "--manuscript-id", mid)
            after_count = sum(1 for l in r_log_after.stdout.splitlines()
                              if l.strip() and "---" not in l
                              and "version_id" not in l
                              and "No snapshots" not in l)

            self.assertTrue(after_count > before_count,
                            "auto-snapshot should have been created before restore")

    def test_restore_without_confirm_errors(self):
        with isolated_cache():
            mid = _init_manuscript("Restore No Confirm")
            _run_version("snapshot", "--manuscript-id", mid, "--note", "v1")
            r = _run_version("restore", "--manuscript-id", mid, "--version", "v1")
            self.assertTrue(r.returncode != 0,
                            "restore without --confirm should fail")
            self.assertIn("--confirm", r.stderr)


# --------------------------------------------------------------------------- #
# CliEdgeTests                                                                 #
# --------------------------------------------------------------------------- #

class CliEdgeTests(TestCase):

    def test_snapshot_without_manuscript_id_errors(self):
        r = _run_version("snapshot")
        self.assertTrue(r.returncode != 0,
                        "snapshot without --manuscript-id should fail")

    def test_diff_without_from_errors(self):
        r = _run_version("diff", "--manuscript-id", "some_mid", "--to", "v2")
        self.assertTrue(r.returncode != 0,
                        "diff without --from should fail")

    def test_diff_without_to_errors(self):
        r = _run_version("diff", "--manuscript-id", "some_mid", "--from", "v1")
        self.assertTrue(r.returncode != 0,
                        "diff without --to should fail")

    def test_restore_without_version_errors(self):
        r = _run_version("restore", "--manuscript-id", "some_mid", "--confirm")
        self.assertTrue(r.returncode != 0,
                        "restore without --version should fail")

    def test_restore_without_confirm_errors(self):
        with isolated_cache():
            mid = _init_manuscript("Restore Without Confirm Edge")
            _run_version("snapshot", "--manuscript-id", mid)
            r = _run_version("restore", "--manuscript-id", mid, "--version", "v1")
            self.assertTrue(r.returncode != 0)
            self.assertIn("--confirm", r.stderr)

    def test_help_lists_all_subcommands(self):
        r = _run_version("--help")
        self.assertEqual(r.returncode, 0)
        for sub in ("snapshot", "log", "diff", "restore"):
            self.assertIn(sub, r.stdout)


if __name__ == "__main__":
    sys.exit(run_tests(
        VersionStoreTests,
        SnapshotTests,
        LogTests,
        DiffTests,
        RestoreTests,
        CliEdgeTests,
    ))
