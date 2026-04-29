"""v0.181 — replication-finder TF-IDF claim weighting.

IDF-weighted Jaccard: rare-token co-occurrences score higher.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = (
    _REPO / ".claude" / "skills" / "replication-finder"
    / "scripts" / "find_replications.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "find_replications_v181", _SCRIPT,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["find_replications_v181"] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_paper(cid: str, claims: list[str]) -> None:
    from lib.cache import paper_dir
    d = paper_dir(cid)
    d.mkdir(parents=True, exist_ok=True)
    meta = {
        "title": cid,
        "authors": [],
        "claims": [{"text": c} for c in claims],
    }
    (d / "metadata.json").write_text(json.dumps(meta))


def _setup_project(target: str, citers: list[str]) -> str:
    from lib import graph, project
    pid = project.create("repl-tfidf")
    tnid = graph.add_node(pid, "paper", target, target)
    for cid in citers:
        cnid = graph.add_node(pid, "paper", cid, cid)
        graph.add_edge(pid, cnid, tnid, "cites")
    return pid


class V0181ReplicationTfidfTests(TestCase):

    def test_idf_demotes_common_tokens(self):
        with isolated_cache():
            mod = _load_module()
            # Build corpus where "common" appears in every doc, "rare" in one.
            corpus = [
                {"common", "alpha", "rare1"},
                {"common", "beta"},
                {"common", "gamma"},
                {"common", "delta"},
            ]
            idf = mod._build_idf(corpus)
            self.assertLess(idf["common"], idf["rare1"])
            # common appears in 4/4, idf = log(4/(1+4)) < 0
            # rare1 appears in 1/4, idf = log(4/(1+1)) > 0
            self.assertGreater(idf["rare1"], 0)

    def test_tfidf_promotes_rare_overlap(self):
        with isolated_cache():
            mod = _load_module()
            # target has rare distinctive token
            _make_paper("tgt", ["quasar magnetar pulsar"])
            # rare-overlap citer: shares the rare tokens
            _make_paper("rare_match", ["we replicate the quasar magnetar pulsar finding"])
            # common-overlap citer: shares only filler words ("the", "we")
            # but those are filtered (len>2) — make them share something else
            # Use long shared filler tokens.
            _make_paper("common_match", ["replicate study analysis result conclusion"])
            # Add several other papers using the common-style tokens to build a
            # corpus where common tokens have high df, rare ones low df.
            for i in range(5):
                _make_paper(
                    f"filler{i}",
                    [f"replicate study analysis result conclusion paper{i}"],
                )
            pid = _setup_project(
                "tgt",
                ["rare_match", "common_match"]
                + [f"filler{i}" for i in range(5)],
            )
            rows = mod.find_replications(pid, "tgt", weighting="tfidf")
            by_cid = {r["cid"]: r for r in rows}
            # rare_match should score higher than common_match because its
            # overlap is on rare tokens.
            self.assertGreater(
                by_cid["rare_match"]["jaccard"],
                by_cid["common_match"]["jaccard"],
            )

    def test_jaccard_fallback_unchanged(self):
        with isolated_cache():
            mod = _load_module()
            shared = "effect of caffeine on memory recall in adults"
            _make_paper("t", [shared])
            _make_paper("c1", [f"we replicate the {shared} finding"])
            pid = _setup_project("t", ["c1"])
            rows = mod.find_replications(pid, "t", weighting="jaccard")
            self.assertEqual(rows[0]["signal"], "replicates")
            self.assertGreater(rows[0]["jaccard"], 0.4)

    def test_idf_scales_under_50_papers(self):
        with isolated_cache():
            mod = _load_module()
            # Synthetic 50-paper corpus performance check.
            _make_paper("base", ["foundational discovery in widget science"])
            citers = []
            for i in range(50):
                cid = f"p{i}"
                _make_paper(
                    cid,
                    [f"we replicate widget science finding number {i}"],
                )
                citers.append(cid)
            pid = _setup_project("base", citers)
            t0 = time.time()
            rows = mod.find_replications(pid, "base", weighting="tfidf")
            elapsed = time.time() - t0
            self.assertEqual(len(rows), 50)
            self.assertLess(elapsed, 2.0)

    def test_cli_weighting_flag_accepted(self):
        with isolated_cache() as cache:
            _make_paper("tg", ["x"])
            _make_paper("cg", ["we replicate x"])
            pid = _setup_project("tg", ["cg"])
            env = {**os.environ, "COSCIENTIST_CACHE_DIR": str(cache)}
            for w in ("tfidf", "jaccard"):
                r = subprocess.run(
                    [sys.executable, str(_SCRIPT),
                     "--project-id", pid, "--canonical-id", "tg",
                     "--weighting", w, "--format", "json"],
                    capture_output=True, text=True, env=env, timeout=30,
                )
                self.assertEqual(r.returncode, 0, r.stderr)
                parsed = json.loads(r.stdout)
                self.assertIsInstance(parsed, list)

    def test_jaccard_baseline_compat(self):
        with isolated_cache():
            mod = _load_module()
            # v0.160 baseline scenario — passing weighting='jaccard' must
            # reproduce the unweighted Jaccard semantics.
            _make_paper("tt", ["a key result"])
            _make_paper("strong", ["we did not replicate the key result"])
            _make_paper("weak", ["we replicate vaguely"])
            pid = _setup_project("tt", ["strong", "weak"])
            rows = mod.find_replications(pid, "tt", weighting="jaccard")
            scores = [r["score"] for r in rows]
            self.assertEqual(scores, sorted(scores, reverse=True))
            self.assertEqual(rows[0]["cid"], "strong")


if __name__ == "__main__":
    sys.exit(run_tests(V0181ReplicationTfidfTests))
