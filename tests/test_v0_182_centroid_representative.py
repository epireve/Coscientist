"""v0.182 — claim-cluster centroid-overlap representative.

Replaces longest-claim picker with centroid-similarity picker (ties
break on length).
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
        "cluster_claims_v182", _SCRIPT,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cluster_claims_v182"] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_paper(cid: str, claims: list[str]) -> Path:
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
    from lib import project
    pid = project.create("centroid-test")
    for cid, claims in papers:
        path = _make_paper(cid, claims)
        project.register_artifact(pid, cid, "paper", "extracted", path)
    return pid


class V0182CentroidRepresentativeTests(TestCase):

    def test_picks_central_not_outlier(self):
        with isolated_cache():
            mod = _load_module()
            # Cluster has tokens about caffeine memory recall; one claim is
            # an outlier with extra unrelated tokens; the more central claim
            # (full overlap with cluster centroid) wins even if shorter.
            central = "caffeine memory recall adults"
            outlier_long = (
                "caffeine memory recall adults "
                "tangential discussion about quasars and pulsars"
            )
            pid = _setup_project([
                ("a", [central]),
                ("b", [central]),
                ("c", [central]),
                ("d", [outlier_long]),
            ])
            r = mod.cluster_claims(pid)
            self.assertEqual(len(r["clusters"]), 1)
            rep = r["clusters"][0]["representative_claim"]
            # Centroid is dominated by central tokens (count 4 each: 3 from
            # the central-only papers + 1 from the outlier). The central
            # claim has higher centroid-score density per token; outlier
            # adds rare tokens that contribute little. With overlap-score
            # tie possible, length tiebreak picks outlier_long. So we test
            # that the rep is NOT the outlier — i.e. the algorithm prefers
            # the central one, OR if the outlier wins it's because it has
            # all tokens. The decisive case: 3 identical short claims +
            # 1 long outlier. The 3 short claims tie on score (same tokens)
            # AND on length, so any of them wins. Outlier's score can be
            # higher because it ALSO contains all centroid tokens plus
            # extras with low centroid weight.
            # Strict assertion: rep equals the central text (one of the
            # 3 identical claims) — outlier should NOT be picked when
            # rare tokens have count 1 and central tokens have count 4.
            self.assertEqual(rep, central)

    def test_all_equal_tiebreak_on_length(self):
        with isolated_cache():
            mod = _load_module()
            # Two claims with IDENTICAL tokens (same density/centroid
            # score) but different surface length → length tiebreak.
            short = "alpha beta gamma delta"
            longer = "alpha beta gamma delta " * 2  # repeated → longer text
            longer = longer.strip()
            pid = _setup_project([
                ("a", [short]),
                ("b", [longer]),
            ])
            r = mod.cluster_claims(pid, min_jaccard=0.3)
            self.assertEqual(len(r["clusters"]), 1)
            rep = r["clusters"][0]["representative_claim"]
            # Both claims share identical token set; centroid-density
            # score equal → longer surface text wins.
            self.assertEqual(rep, longer)

    def test_singleton_cluster_outlier(self):
        with isolated_cache():
            mod = _load_module()
            # A singleton paper goes to outliers; verify representative
            # logic handles a 2-paper cluster with one claim each.
            pid = _setup_project([
                ("a", ["alpha beta gamma delta"]),
                ("b", ["alpha beta gamma delta"]),
            ])
            r = mod.cluster_claims(pid)
            self.assertEqual(len(r["clusters"]), 1)
            self.assertEqual(
                r["clusters"][0]["representative_claim"],
                "alpha beta gamma delta",
            )

    def test_centroid_picks_higher_overlap(self):
        with isolated_cache():
            mod = _load_module()
            # 3 papers cluster on shared tokens A B C D. One paper has an
            # extra claim mentioning only some of those + filler. The full-
            # overlap claim wins.
            full = "alpha beta gamma delta"
            partial = "alpha xenon"
            pid = _setup_project([
                ("p1", [full, partial]),
                ("p2", [full]),
                ("p3", [full]),
            ])
            r = mod.cluster_claims(pid)
            self.assertEqual(len(r["clusters"]), 1)
            rep = r["clusters"][0]["representative_claim"]
            self.assertEqual(rep, full)

    def test_cli_emits_representative(self):
        with isolated_cache() as cache:
            pid = _setup_project([
                ("a", ["caffeine memory recall adults"]),
                ("b", ["caffeine memory recall adults"]),
            ])
            env = {**os.environ, "COSCIENTIST_CACHE_DIR": str(cache)}
            r = subprocess.run(
                [sys.executable, str(_SCRIPT),
                 "--project-id", pid, "--format", "json"],
                capture_output=True, text=True, env=env, timeout=30,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            parsed = json.loads(r.stdout)
            self.assertEqual(len(parsed["clusters"]), 1)
            self.assertEqual(
                parsed["clusters"][0]["representative_claim"],
                "caffeine memory recall adults",
            )


if __name__ == "__main__":
    sys.exit(run_tests(V0182CentroidRepresentativeTests))
