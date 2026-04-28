"""v0.87 — backup/restore scripts + cleanup invariants."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parents[1]


class BackupRestoreScriptsTests(TestCase):
    BACKUP = _REPO / "scripts" / "backup_cache.sh"
    RESTORE = _REPO / "scripts" / "restore_cache.sh"

    def test_scripts_present(self):
        self.assertTrue(self.BACKUP.exists())
        self.assertTrue(self.RESTORE.exists())

    def test_scripts_executable(self):
        for path in (self.BACKUP, self.RESTORE):
            mode = path.stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR, f"{path} not executable")

    def test_backup_round_trip(self):
        """End-to-end: create fake cache, backup, wipe, restore, verify."""
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "coscientist"
            cache_dir.mkdir()
            (cache_dir / "papers").mkdir()
            (cache_dir / "papers" / "x.txt").write_text("hello")

            archive_dir = Path(tmp) / "out"
            archive_dir.mkdir()

            env = os.environ.copy()
            env["COSCIENTIST_CACHE_DIR"] = str(cache_dir)
            r = subprocess.run(
                [str(self.BACKUP), "--out", str(archive_dir),
                 "--name", "test.tar.gz"],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            archive = archive_dir / "test.tar.gz"
            self.assertTrue(archive.exists())

            # Wipe the cache, then restore.
            shutil.rmtree(cache_dir)
            r = subprocess.run(
                [str(self.RESTORE), str(archive)],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((cache_dir / "papers" / "x.txt").exists())
            self.assertEqual(
                (cache_dir / "papers" / "x.txt").read_text(), "hello",
            )

    def test_restore_refuses_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "coscientist"
            cache_dir.mkdir()
            (cache_dir / "marker.txt").write_text("preexisting")

            archive_dir = Path(tmp) / "out"
            archive_dir.mkdir()

            env = os.environ.copy()
            env["COSCIENTIST_CACHE_DIR"] = str(cache_dir)
            subprocess.run(
                [str(self.BACKUP), "--out", str(archive_dir),
                 "--name", "test.tar.gz"],
                capture_output=True, text=True, env=env, check=True,
            )
            archive = archive_dir / "test.tar.gz"

            # Without --force, should refuse.
            r = subprocess.run(
                [str(self.RESTORE), str(archive)],
                capture_output=True, text=True, env=env,
            )
            self.assertTrue(r.returncode != 0,
                            f"expected nonzero, got {r.returncode}")
            self.assertIn("already exists", r.stderr)
            # Original file untouched.
            self.assertEqual(
                (cache_dir / "marker.txt").read_text(), "preexisting",
            )

    def test_backup_uses_strict_mode(self):
        text = self.BACKUP.read_text()
        self.assertIn("set -e", text)


class ScriptsDirTests(TestCase):
    def test_install_script_present(self):
        self.assertTrue((_REPO / "scripts" / "install_all.sh").exists())

    def test_all_shell_scripts_executable(self):
        for sh in (_REPO / "scripts").glob("*.sh"):
            mode = sh.stat().st_mode
            self.assertTrue(
                mode & stat.S_IXUSR, f"{sh.name} not executable",
            )


class TmpFilesNotTrackedTests(TestCase):
    def test_tmp_files_gitignored(self):
        # Tracked-status check via git ls-files.
        r = subprocess.run(
            ["git", "ls-files", "tests/_tmp_*.json"],
            capture_output=True, text=True, cwd=str(_REPO),
        )
        # Exit 0 with empty stdout = none tracked.
        self.assertEqual(r.stdout.strip(), "",
                         f"_tmp files unexpectedly tracked: {r.stdout}")


if __name__ == "__main__":
    raise SystemExit(run_tests(
        BackupRestoreScriptsTests,
        ScriptsDirTests,
        TmpFilesNotTrackedTests,
    ))
