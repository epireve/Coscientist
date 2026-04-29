"""v0.160 — replication-finder skill tests.

Heuristic, read-only. Stem matching + claim Jaccard over the project
graph. No LLM, pure stdlib.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = (
    _REPO / ".claude" / "skills" / "replication-finder"
    / "scripts" / "find_replications.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "find_replications_v160", _SCRIPT,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["find_replications_v160"] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_paper(cid: str, claims: list[str], content: str = "") -> None:
    """Create paper artifact metadata.json (+ optional content.md)."""
    from lib.cache import paper_dir
    d = paper_dir(cid)
    d.mkdir(parents=True, exist_ok=True)
    meta = {
        "title": cid,
        "authors": [],
        "claims": [{"text": c} for c in claims],
    }
    (d / "metadata.json").write_text(json.dumps(meta))
    if content:
        (d / "content.md").write_text(content)


def _setup_project(target_cid: str, citers: list[tuple[str, str]]) -> str:
    """Create a project with target + citers wired via cites edge.

    citers: list of (citer_cid, edge_type) — edge_type is always 'cites'
    here; supplied for clarity.
    """
    from lib import graph, project
    pid = project.create("repl-test")
    target_nid = graph.add_node(pid, "paper", target_cid, target_cid)
    for citer_cid, _ in citers:
        citer_nid = graph.add_node(pid, "paper", citer_cid, citer_cid)
        graph.add_edge(pid, citer_nid, target_nid, "cites")
    return pid


# -------------------------------------------------------------- tests

class V0160ReplicationFinderTests(TestCase):

    def test_detects_replicate_stem(self):
        with isolated_cache():
            mod = _load_module()
            _make_paper("target_x", ["effect of X on Y is large"])
            _make_paper(
                "citer_a",
                ["we replicate the X-on-Y effect in n=200"],
            )
            pid = _setup_project("target_x", [("citer_a", "cites")])
            rows = mod.find_replications(pid, "target_x")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["signal"], "replicates")
            self.assertGreater(rows[0]["score"], 0)

    def test_fail_to_replicate_overrides_replicate(self):
        with isolated_cache():
            mod = _load_module()
            _make_paper("target_y", ["X causes Y"])
            _make_paper(
                "citer_b",
                ["we fail to replicate the X causes Y claim"],
            )
            pid = _setup_project("target_y", [("citer_b", "cites")])
            rows = mod.find_replications(pid, "target_y")
            self.assertEqual(rows[0]["signal"], "refutes")
            # Refute weight (2.0) higher than naive replicate would be.
            self.assertGreaterEqual(rows[0]["score"], 2.0)

    def test_followup_stem(self):
        with isolated_cache():
            mod = _load_module()
            _make_paper("target_z", ["foundation result"])
            _make_paper(
                "citer_c",
                ["we extend prior work and build on the foundation"],
            )
            pid = _setup_project("target_z", [("citer_c", "cites")])
            rows = mod.find_replications(pid, "target_z")
            self.assertEqual(rows[0]["signal"], "follow-up")

    def test_jaccard_overlap_boosts_score(self):
        with isolated_cache():
            mod = _load_module()
            shared = "effect of caffeine on memory recall in adults"
            _make_paper("t1", [shared])
            # Citer 1: matching tokens + replicate
            _make_paper(
                "c_match",
                [f"we replicate the {shared} finding"],
            )
            # Citer 2: replicate stem but unrelated tokens
            _make_paper(
                "c_unrelated",
                ["we replicate something completely different about quasars"],
            )
            pid = _setup_project(
                "t1", [("c_match", "cites"), ("c_unrelated", "cites")],
            )
            # v0.181: explicit weighting='jaccard' to match v0.160 baseline.
            rows = mod.find_replications(pid, "t1", weighting="jaccard")
            by_cid = {r["cid"]: r for r in rows}
            self.assertGreater(
                by_cid["c_match"]["score"],
                by_cid["c_unrelated"]["score"],
            )
            self.assertGreater(by_cid["c_match"]["jaccard"], 0.4)

    def test_no_citers_returns_empty(self):
        with isolated_cache():
            mod = _load_module()
            _make_paper("lonely", ["a claim"])
            from lib import project, graph
            pid = project.create("empty-test")
            graph.add_node(pid, "paper", "lonely", "lonely")
            rows = mod.find_replications(pid, "lonely")
            self.assertEqual(rows, [])

    def test_missing_target_returns_error(self):
        with isolated_cache():
            mod = _load_module()
            from lib import project
            pid = project.create("no-target-test")
            result = mod.find_replications(pid, "ghost_paper")
            self.assertIsInstance(result, dict)
            self.assertIn("error", result)

    def test_sorts_by_score_desc(self):
        with isolated_cache():
            mod = _load_module()
            _make_paper("tt", ["a key result"])
            # Strong refute → high score
            _make_paper("strong", ["we did not replicate the key result"])
            # Weak replicate
            _make_paper("weak", ["we replicate vaguely"])
            # No stem
            _make_paper("noise", ["unrelated commentary"])
            pid = _setup_project(
                "tt",
                [("strong", "cites"), ("weak", "cites"), ("noise", "cites")],
            )
            rows = mod.find_replications(pid, "tt")
            scores = [r["score"] for r in rows]
            self.assertEqual(scores, sorted(scores, reverse=True))
            self.assertEqual(rows[0]["cid"], "strong")

    def test_top_n_caps_results(self):
        with isolated_cache():
            mod = _load_module()
            _make_paper("base", ["original"])
            citers = []
            for i in range(5):
                cid = f"c{i}"
                _make_paper(cid, [f"we replicate finding {i}"])
                citers.append((cid, "cites"))
            pid = _setup_project("base", citers)
            rows = mod.find_replications(pid, "base", top_n=2)
            self.assertEqual(len(rows), 2)

    def test_json_vs_text_output(self):
        with isolated_cache() as cache:
            _make_paper("tj", ["x"])
            _make_paper("cj", ["we replicate x"])
            pid = _setup_project("tj", [("cj", "cites")])
            env = {**os.environ, "COSCIENTIST_CACHE_DIR": str(cache)}
            r_json = subprocess.run(
                [sys.executable, str(_SCRIPT),
                 "--project-id", pid, "--canonical-id", "tj",
                 "--format", "json"],
                capture_output=True, text=True, env=env, timeout=30,
            )
            self.assertEqual(r_json.returncode, 0)
            parsed = json.loads(r_json.stdout)
            self.assertIsInstance(parsed, list)
            r_text = subprocess.run(
                [sys.executable, str(_SCRIPT),
                 "--project-id", pid, "--canonical-id", "tj",
                 "--format", "text"],
                capture_output=True, text=True, env=env, timeout=30,
            )
            self.assertEqual(r_text.returncode, 0)
            self.assertIn("replicates", r_text.stdout)

    def test_cli_help(self):
        r = subprocess.run(
            [sys.executable, str(_SCRIPT), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("--project-id", r.stdout)
        self.assertIn("--canonical-id", r.stdout)

    def test_case_insensitive_stems(self):
        with isolated_cache():
            mod = _load_module()
            _make_paper("ci", ["finding"])
            _make_paper(
                "uc",
                ["We REPLICATE the FINDING successfully"],
            )
            pid = _setup_project("ci", [("uc", "cites")])
            rows = mod.find_replications(pid, "ci")
            self.assertEqual(rows[0]["signal"], "replicates")

    def test_multiple_stems_combine(self):
        with isolated_cache():
            mod = _load_module()
            _make_paper("multi", ["claim"])
            _make_paper(
                "many",
                [
                    "we replicate and confirm and corroborate the claim",
                    "we also extend it",
                ],
            )
            _make_paper(
                "single",
                ["we replicate the claim"],
            )
            pid = _setup_project(
                "multi",
                [("many", "cites"), ("single", "cites")],
            )
            rows = mod.find_replications(pid, "multi")
            by_cid = {r["cid"]: r for r in rows}
            self.assertGreater(
                by_cid["many"]["score"],
                by_cid["single"]["score"],
            )

    def test_missing_metadata_skipped(self):
        with isolated_cache():
            mod = _load_module()
            _make_paper("tg", ["target claim"])
            # citer with no metadata.json — should be skipped, not crash
            from lib import project, graph
            pid = project.create("skip-test")
            tnid = graph.add_node(pid, "paper", "tg", "tg")
            cnid = graph.add_node(pid, "paper", "ghost", "ghost")
            graph.add_edge(pid, cnid, tnid, "cites")
            # Add one well-formed citer too
            _make_paper("real", ["we replicate target claim"])
            rnid = graph.add_node(pid, "paper", "real", "real")
            graph.add_edge(pid, rnid, tnid, "cites")
            rows = mod.find_replications(pid, "tg")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["cid"], "real")


if __name__ == "__main__":
    sys.exit(run_tests(V0160ReplicationFinderTests))
