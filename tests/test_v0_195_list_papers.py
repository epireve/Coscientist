"""v0.195 — db.py list-papers + list-claims subcommands.

Closes dogfood finding #9. Cartographer should not be running raw
`sqlite3 ... SELECT canonical_id, title FROM papers_in_run` — provides
CLI primitives instead.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PY = (
    REPO_ROOT / ".claude" / "skills" / "deep-research"
    / "scripts" / "db.py"
)


def _run(cache: Path, *args: str, stdin: str | None = None
         ) -> subprocess.CompletedProcess:
    env = {
        "COSCIENTIST_CACHE_DIR": str(cache),
        "PATH": "/usr/bin:/bin",
    }
    return subprocess.run(
        [sys.executable, str(DB_PY), *args],
        env=env, capture_output=True, text=True, input=stdin,
    )


def _init_run(cache: Path) -> str:
    r = _run(cache, "init", "--question", "test")
    if r.returncode != 0:
        raise RuntimeError(f"init failed: {r.stderr!r}")
    return r.stdout.strip().splitlines()[-1]


def _seed_papers(cache: Path, run_id: str,
                  rows: list[tuple[str, str, str]]) -> None:
    """rows = [(canonical_id, role, added_in_phase), ...]"""
    db = cache / "runs" / f"run-{run_id}.db"
    con = sqlite3.connect(db)
    with con:
        for cid, role, phase in rows:
            con.execute(
                "INSERT INTO papers_in_run "
                "(run_id, canonical_id, role, added_in_phase, "
                " harvest_count) VALUES (?, ?, ?, ?, 1)",
                (run_id, cid, role, phase),
            )
    con.close()


class ListPapersTests(TestCase):
    def test_returns_rows_json(self):
        with isolated_cache() as cache:
            rid = _init_run(cache)
            _seed_papers(cache, rid, [
                ("smith_2024_a_aa1111", "seed", "scout"),
                ("doe_2023_b_bb2222", "supporting", "cartographer"),
            ])
            r = _run(cache, "list-papers", "--run-id", rid,
                      "--format", "json")
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            items = json.loads(r.stdout)
            self.assertEqual(len(items), 2)
            self.assertEqual(items[0]["added_in_phase"], "scout")
            self.assertEqual(items[1]["added_in_phase"], "cartographer")

    def test_phase_filter(self):
        with isolated_cache() as cache:
            rid = _init_run(cache)
            _seed_papers(cache, rid, [
                ("smith_2024_a_aa1111", "seed", "scout"),
                ("doe_2023_b_bb2222", "supporting", "cartographer"),
                ("kim_2025_c_cc3333", "supporting", "cartographer"),
            ])
            r = _run(cache, "list-papers", "--run-id", rid,
                      "--phase", "cartographer", "--format", "json")
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            items = json.loads(r.stdout)
            self.assertEqual(len(items), 2)
            for it in items:
                self.assertEqual(it["added_in_phase"], "cartographer")

    def test_text_format(self):
        with isolated_cache() as cache:
            rid = _init_run(cache)
            _seed_papers(cache, rid, [
                ("smith_2024_a_aa1111", "seed", "scout"),
            ])
            r = _run(cache, "list-papers", "--run-id", rid,
                      "--format", "text")
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertIn("scout", r.stdout)
            self.assertIn("smith_2024_a_aa1111", r.stdout)

    def test_empty_run_returns_empty_list(self):
        with isolated_cache() as cache:
            rid = _init_run(cache)
            r = _run(cache, "list-papers", "--run-id", rid,
                      "--format", "json")
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(json.loads(r.stdout), [])

    def test_unknown_run_id_errors(self):
        with isolated_cache() as cache:
            r = _run(cache, "list-papers",
                      "--run-id", "deadbeef", "--format", "json")
            self.assertTrue(r.returncode != 0)
            self.assertIn("deadbeef", r.stderr)

    def test_list_claims_parallel(self):
        with isolated_cache() as cache:
            rid = _init_run(cache)
            # Seed claims via record-claim (existing CLI).
            _run(cache, "record-claim", "--run-id", rid,
                  "--agent-name", "cartographer",
                  "--text", "Claim text one",
                  "--kind", "finding",
                  "--supporting-ids", "a_2024_x_111111,b_2023_y_222222")
            _run(cache, "record-claim", "--run-id", rid,
                  "--agent-name", "surveyor",
                  "--text", "Gap claim two",
                  "--kind", "gap",
                  "--supporting-ids", "")
            r = _run(cache, "list-claims", "--run-id", rid,
                      "--format", "json")
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            items = json.loads(r.stdout)
            self.assertEqual(len(items), 2)
            agents = sorted(it["agent_name"] for it in items)
            self.assertEqual(agents, ["cartographer", "surveyor"])
            # Filter by kind
            r = _run(cache, "list-claims", "--run-id", rid,
                      "--kind", "gap", "--format", "json")
            self.assertEqual(r.returncode, 0)
            items = json.loads(r.stdout)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["kind"], "gap")


if __name__ == "__main__":
    sys.exit(run_tests(ListPapersTests))
