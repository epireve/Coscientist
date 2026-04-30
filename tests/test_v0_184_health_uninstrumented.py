"""v0.184 — health surfaces uninstrumented (pre-v0.89) DBs."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from lib.health import collect, render_md
from tests.harness import TestCase, isolated_cache, run_tests


def _make_run_db(path: Path, with_traces: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    if with_traces:
        con.execute("CREATE TABLE traces (trace_id TEXT, run_id TEXT, "
                    "status TEXT, started_at TEXT)")
        con.execute("CREATE TABLE spans (trace_id TEXT, status TEXT, "
                    "ended_at TEXT, started_at TEXT)")
    else:
        # Old DB shape: has runs but no traces.
        con.execute("CREATE TABLE runs (run_id TEXT, status TEXT)")
    con.commit()
    con.close()


class HealthUninstrumentedTests(TestCase):
    def test_old_db_counted_as_uninstrumented(self):
        with isolated_cache() as cache:
            runs = cache / "runs"
            _make_run_db(runs / "run-old.db", with_traces=False)
            _make_run_db(runs / "run-new.db", with_traces=True)
            r = collect()
            self.assertEqual(r["n_runs"], 1)
            self.assertEqual(r["n_uninstrumented"], 1)
            self.assertEqual(len(r["uninstrumented_paths"]), 1)
            self.assertIn("run-old.db", r["uninstrumented_paths"][0])

    def test_render_md_surfaces_uninstrumented_when_present(self):
        with isolated_cache() as cache:
            runs = cache / "runs"
            _make_run_db(runs / "run-old.db", with_traces=False)
            r = collect()
            md = render_md(r)
            self.assertIn("Uninstrumented", md)

    def test_render_md_omits_line_when_zero(self):
        with isolated_cache() as cache:
            runs = cache / "runs"
            _make_run_db(runs / "run-new.db", with_traces=True)
            r = collect()
            md = render_md(r)
            self.assertTrue("Uninstrumented" not in md)

    def test_empty_cache_returns_zero(self):
        with isolated_cache():
            r = collect()
            self.assertEqual(r["n_uninstrumented"], 0)


if __name__ == "__main__":
    raise SystemExit(run_tests(HealthUninstrumentedTests))
