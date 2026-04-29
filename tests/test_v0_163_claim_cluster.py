"""v0.163 — claim-cluster skill tests.

Read-only Jaccard clustering of claims across project papers. Pure
stdlib heuristic.
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
    _REPO / ".claude" / "skills" / "claim-cluster"
    / "scripts" / "cluster_claims.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "cluster_claims_v163", _SCRIPT,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cluster_claims_v163"] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_paper(cid: str, claims: list[str]) -> Path:
    """Create paper artifact metadata.json with given claims."""
    from lib.cache import paper_dir
    d = paper_dir(cid)
    d.mkdir(parents=True, exist_ok=True)
    meta = {
        "title": cid,
        "authors": [],
        "claims": [{"text": c} for c in claims],
    }
    (d / "metadata.json").write_text(json.dumps(meta))
    return d


def _setup_project(papers: list[tuple[str, list[str]]]) -> str:
    """Create a project with paper artifacts registered in artifact_index."""
    from lib import project
    pid = project.create("clust-test")
    for cid, claims in papers:
        path = _make_paper(cid, claims)
        project.register_artifact(pid, cid, "paper", "extracted", path)
    return pid


# -------------------------------------------------------------- tests

class ClaimClusterTests(TestCase):

    def test_two_overlapping_papers_form_cluster(self):
        with isolated_cache():
            mod = _load_module()
            shared = "caffeine improves memory recall in healthy adults"
            pid = _setup_project([
                ("p1", [shared]),
                ("p2", [f"caffeine improves memory recall significantly"]),
            ])
            r = mod.cluster_claims(pid)
            self.assertEqual(len(r["clusters"]), 1)
            self.assertEqual(r["clusters"][0]["size"], 2)
            self.assertEqual(
                sorted(r["clusters"][0]["papers"]), ["p1", "p2"],
            )

    def test_singleton_paper_is_outlier(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project([
                ("solo", ["unique claim about gravity wells"]),
            ])
            r = mod.cluster_claims(pid)
            self.assertEqual(r["clusters"], [])
            self.assertEqual(r["outliers"], ["solo"])

    def test_three_papers_one_cluster(self):
        with isolated_cache():
            mod = _load_module()
            base = "caffeine improves memory recall adults"
            pid = _setup_project([
                ("a", [base]),
                ("b", [base + " replicated"]),
                ("c", [base + " confirmed broadly"]),
            ])
            r = mod.cluster_claims(pid)
            self.assertEqual(len(r["clusters"]), 1)
            self.assertEqual(r["clusters"][0]["size"], 3)

    def test_min_jaccard_filters_weak(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project([
                ("p1", ["alpha beta gamma delta epsilon"]),
                ("p2", ["alpha zeta eta theta iota"]),  # ~0.11 overlap
            ])
            # default 0.4 threshold — should NOT cluster
            r = mod.cluster_claims(pid)
            self.assertEqual(r["clusters"], [])
            # very low threshold — should cluster
            r2 = mod.cluster_claims(pid, min_jaccard=0.05)
            self.assertEqual(len(r2["clusters"]), 1)

    def test_min_cluster_size_filters_singletons(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project([
                ("p1", ["alpha beta gamma delta"]),
                ("p2", ["alpha beta gamma delta"]),
                ("solo", ["completely separate quasars"]),
            ])
            r = mod.cluster_claims(pid, min_cluster_size=2)
            self.assertEqual(len(r["clusters"]), 1)
            self.assertIn("solo", r["outliers"])
            # Bump min_cluster_size — even the pair becomes outliers.
            r3 = mod.cluster_claims(pid, min_cluster_size=3)
            self.assertEqual(r3["clusters"], [])
            self.assertEqual(
                sorted(r3["outliers"]), ["p1", "p2", "solo"],
            )

    def test_empty_project_returns_clean(self):
        with isolated_cache():
            mod = _load_module()
            from lib import project
            pid = project.create("empty")
            r = mod.cluster_claims(pid)
            self.assertEqual(r, {"clusters": [], "outliers": []})

    def test_too_many_papers_returns_error(self):
        with isolated_cache():
            mod = _load_module()
            papers = [
                (f"p{i}", [f"claim {i}"]) for i in range(mod.MAX_PAPERS + 1)
            ]
            pid = _setup_project(papers)
            r = mod.cluster_claims(pid)
            self.assertIsInstance(r, dict)
            self.assertIn("error", r)
            self.assertIn(str(mod.MAX_PAPERS), r["error"])

    def test_top_tokens_most_common(self):
        with isolated_cache():
            mod = _load_module()
            pid = _setup_project([
                ("a", ["caffeine memory caffeine recall"]),
                ("b", ["caffeine memory recall adults"]),
            ])
            r = mod.cluster_claims(pid)
            self.assertEqual(len(r["clusters"]), 1)
            tokens = {t["token"]: t["count"] for t in r["clusters"][0]["top_tokens"]}
            # caffeine appears most across the cluster
            self.assertIn("caffeine", tokens)
            self.assertGreaterEqual(tokens["caffeine"], 1)

    def test_representative_claim_is_longest(self):
        with isolated_cache():
            mod = _load_module()
            # v0.182 — representative now picked by centroid-density.
            # Use claims with IDENTICAL token sets but different surface
            # length so length tiebreak still applies (centroid scores tie).
            short = "caffeine improves memory recall adults"
            long_ = short + " " + short  # repeated tokens — same set, longer
            pid = _setup_project([
                ("a", [short]),
                ("b", [long_]),
            ])
            r = mod.cluster_claims(pid, min_jaccard=0.3)
            self.assertEqual(len(r["clusters"]), 1)
            self.assertEqual(r["clusters"][0]["representative_claim"], long_)

    def test_json_vs_text_output(self):
        with isolated_cache() as cache:
            pid = _setup_project([
                ("p1", ["alpha beta gamma delta"]),
                ("p2", ["alpha beta gamma delta"]),
            ])
            env = {**os.environ, "COSCIENTIST_CACHE_DIR": str(cache)}
            rj = subprocess.run(
                [sys.executable, str(_SCRIPT),
                 "--project-id", pid, "--format", "json"],
                capture_output=True, text=True, env=env, timeout=30,
            )
            self.assertEqual(rj.returncode, 0)
            parsed = json.loads(rj.stdout)
            self.assertIn("clusters", parsed)
            self.assertIn("outliers", parsed)
            rt = subprocess.run(
                [sys.executable, str(_SCRIPT),
                 "--project-id", pid, "--format", "text"],
                capture_output=True, text=True, env=env, timeout=30,
            )
            self.assertEqual(rt.returncode, 0)
            self.assertIn("cluster", rt.stdout)

    def test_cli_help(self):
        r = subprocess.run(
            [sys.executable, str(_SCRIPT), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("--project-id", r.stdout)
        self.assertIn("--min-jaccard", r.stdout)
        self.assertIn("--min-cluster-size", r.stdout)

    def test_top_n_caps_cluster_list(self):
        with isolated_cache():
            mod = _load_module()
            # 3 disjoint pairs → 3 clusters; top_n=2 → 2 returned.
            pid = _setup_project([
                ("a1", ["alpha beta gamma delta"]),
                ("a2", ["alpha beta gamma delta"]),
                ("b1", ["foxtrot golf hotel india"]),
                ("b2", ["foxtrot golf hotel india"]),
                ("c1", ["november oscar papa quebec"]),
                ("c2", ["november oscar papa quebec"]),
            ])
            r = mod.cluster_claims(pid, top_n=2)
            self.assertEqual(len(r["clusters"]), 2)

    def test_stop_words_excluded(self):
        with isolated_cache():
            mod = _load_module()
            # "the is of and" all stop-words; no content tokens overlap.
            pid = _setup_project([
                ("p1", ["the is of and"]),
                ("p2", ["the is of and"]),
            ])
            r = mod.cluster_claims(pid)
            # Both have empty token bags → no cluster, both outliers.
            self.assertEqual(r["clusters"], [])
            self.assertEqual(sorted(r["outliers"]), ["p1", "p2"])

    def test_read_only_no_writes(self):
        with isolated_cache():
            mod = _load_module()
            from lib.project import project_db_path
            pid = _setup_project([
                ("a", ["alpha beta gamma delta"]),
                ("b", ["alpha beta gamma delta"]),
            ])
            db = project_db_path(pid)
            mtime_before = db.stat().st_mtime
            # paper artifact mtimes
            from lib.cache import paper_dir
            ma = (paper_dir("a") / "metadata.json").stat().st_mtime
            mb = (paper_dir("b") / "metadata.json").stat().st_mtime
            r = mod.cluster_claims(pid)
            self.assertEqual(len(r["clusters"]), 1)
            self.assertEqual(db.stat().st_mtime, mtime_before)
            self.assertEqual(
                (paper_dir("a") / "metadata.json").stat().st_mtime, ma,
            )
            self.assertEqual(
                (paper_dir("b") / "metadata.json").stat().st_mtime, mb,
            )


if __name__ == "__main__":
    sys.exit(run_tests(ClaimClusterTests))
