"""v0.159 — populate_citations + populate_concepts gain --source auto.

`auto` (new default) delegates source choice to lib.source_selector.
For phase=ingestion, selector returns 'openalex' deterministically.
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
_CITATIONS_SCRIPT = (
    _REPO / ".claude" / "skills" / "reference-agent"
    / "scripts" / "populate_citations.py"
)
_CONCEPTS_SCRIPT = (
    _REPO / ".claude" / "skills" / "reference-agent"
    / "scripts" / "populate_concepts.py"
)


def _load_citations_module():
    spec = importlib.util.spec_from_file_location(
        "populate_citations_v159", _CITATIONS_SCRIPT,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["populate_citations_v159"] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_concepts_module():
    spec = importlib.util.spec_from_file_location(
        "populate_concepts_v159", _CONCEPTS_SCRIPT,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["populate_concepts_v159"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- helpers

def _run_citations(args: list[str], cache_dir: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "COSCIENTIST_CACHE_DIR": str(cache_dir)}
    return subprocess.run(
        [sys.executable, str(_CITATIONS_SCRIPT), *args],
        capture_output=True, text=True, timeout=30, env=env,
    )


def _run_concepts(args: list[str], cache_dir: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "COSCIENTIST_CACHE_DIR": str(cache_dir)}
    return subprocess.run(
        [sys.executable, str(_CONCEPTS_SCRIPT), *args],
        capture_output=True, text=True, timeout=30, env=env,
    )


# ---------------------------------------------------------------- citations


class CitationsAutoResolverTests(TestCase):
    def test_resolver_returns_openalex_for_ingestion(self):
        mod = _load_citations_module()
        chosen, reason = mod._resolve_auto_source()
        self.assertEqual(chosen, "openalex")
        self.assertTrue(isinstance(reason, str) and len(reason) > 0)

    def test_argparse_accepts_auto(self):
        # Calling with --source auto + missing --paper-id should fail
        # cleanly (auto resolves to openalex live mode), not bail at argparse.
        with isolated_cache() as cache_dir:
            from lib import project as project_mod
            pid = project_mod.create("auto-no-paper")
            r = _run_citations(
                ["--source", "auto", "--project-id", pid], cache_dir,
            )
            # Stderr should carry the resolver log line.
            self.assertIn(
                "[source-selector] populate_citations resolved auto -> openalex",
                r.stderr,
            )
            # Non-zero exit because no --paper-id (live mode requires it).
            self.assertTrue(r.returncode != 0)

    def test_argparse_rejects_unknown_source(self):
        with isolated_cache() as cache_dir:
            from lib import project as project_mod
            pid = project_mod.create("bad-source")
            r = _run_citations(
                ["--source", "bogus", "--project-id", pid], cache_dir,
            )
            # argparse exits 2 on invalid choice
            self.assertEqual(r.returncode, 2)
            self.assertIn("invalid choice", r.stderr)

    def test_explicit_openalex_unchanged(self):
        # subprocess flow: --source openalex still works and does not
        # emit resolver log line.
        with isolated_cache() as cache_dir:
            from lib import project as project_mod
            pid = project_mod.create("explicit-oa")
            r = _run_citations(
                ["--source", "openalex", "--project-id", pid], cache_dir,
            )
            self.assertNotIn("[source-selector]", r.stderr)
            # No --paper-id, so non-zero exit with structured error JSON.
            self.assertTrue(r.returncode != 0)
            self.assertIn("paper-id", r.stdout)

    def test_explicit_s2_unchanged(self):
        with isolated_cache() as cache_dir:
            from lib import project as project_mod
            pid = project_mod.create("explicit-s2")
            r = _run_citations(
                ["--source", "s2", "--project-id", pid], cache_dir,
            )
            self.assertNotIn("[source-selector]", r.stderr)
            self.assertTrue(r.returncode != 0)
            self.assertIn("paper-id", r.stdout)

    def test_explicit_file_unchanged(self):
        # File-mode happy path with empty list.
        with isolated_cache() as cache_dir:
            from lib import project as project_mod
            pid = project_mod.create("explicit-file")
            input_file = cache_dir / "in.json"
            input_file.write_text("[]")
            r = _run_citations(
                ["--source", "file", "--input", str(input_file),
                 "--project-id", pid], cache_dir,
            )
            self.assertNotIn("[source-selector]", r.stderr)
            self.assertEqual(r.returncode, 0, msg=f"stderr={r.stderr}")
            out = json.loads(r.stdout)
            self.assertEqual(out["edges_added"], 0)


class CitationsAutoIntegrationTests(TestCase):
    """--source auto end-to-end: resolves to openalex, then runs the
    same ingestion path covered by v0.150 happy-path tests."""

    def test_auto_with_paper_id_runs_openalex_path(self):
        # Reuse the v0.150 stub pattern: monkey-patch the script's
        # OpenAlexClient import so populate_from_openalex sees a stub.
        from tests.test_v0_150_populate_citations import (
            StubOpenAlexClient, _setup_project_with_paper,
        )

        with isolated_cache():
            pid, cid, mod = _setup_project_with_paper({
                "openalex_id": "W42", "doi": "10.1/auto",
            })
            stub = StubOpenAlexClient(
                refs=["https://openalex.org/W101"],
                batch_results=[{
                    "id": "https://openalex.org/W101",
                    "display_name": "Earlier Work",
                    "publication_year": 2010,
                    "doi": "https://doi.org/10.1/early",
                    "authorships": [
                        {"author": {"display_name": "Foo, B"}},
                    ],
                }],
                cited_by={"results": []},
            )
            # Direct in-process call mirrors what main() ends up doing
            # after auto resolves to openalex.
            chosen, _ = mod._resolve_auto_source()
            self.assertEqual(chosen, "openalex")
            res = mod.populate_from_openalex(cid, pid, client=stub)
            self.assertEqual(res.get("source"), "openalex")
            self.assertEqual(res["edges_added"], 2)


# ---------------------------------------------------------------- concepts


class ConceptsAutoResolverTests(TestCase):
    def test_resolver_returns_openalex_for_ingestion(self):
        mod = _load_concepts_module()
        chosen, reason = mod._resolve_auto_source()
        self.assertEqual(chosen, "openalex")
        self.assertTrue(isinstance(reason, str) and len(reason) > 0)

    def test_argparse_accepts_auto(self):
        with isolated_cache() as cache_dir:
            from lib import project as project_mod
            pid = project_mod.create("concepts-auto")
            # No --paper-id → batch all project papers (zero papers
            # registered, so it should run cleanly).
            r = _run_concepts(
                ["--source", "auto", "--project-id", pid], cache_dir,
            )
            self.assertIn(
                "[source-selector] populate_concepts resolved auto -> openalex",
                r.stderr,
            )
            self.assertEqual(r.returncode, 0, msg=f"stderr={r.stderr}")
            out = json.loads(r.stdout)
            self.assertEqual(out["papers_processed"], 0)

    def test_argparse_rejects_unknown_source(self):
        with isolated_cache() as cache_dir:
            from lib import project as project_mod
            pid = project_mod.create("concepts-bad")
            r = _run_concepts(
                ["--source", "consensus", "--project-id", pid], cache_dir,
            )
            self.assertEqual(r.returncode, 2)
            self.assertIn("invalid choice", r.stderr)

    def test_explicit_claims_unchanged(self):
        with isolated_cache() as cache_dir:
            from lib import project as project_mod
            pid = project_mod.create("concepts-claims")
            r = _run_concepts(
                ["--source", "claims", "--run-id", "no-such-run",
                 "--project-id", pid],
                cache_dir,
            )
            self.assertNotIn("[source-selector]", r.stderr)
            # Missing run DB → returns error, exit 1
            self.assertEqual(r.returncode, 1)
            out = json.loads(r.stdout)
            self.assertIn("error", out)


class ConceptsAutoIntegrationTests(TestCase):
    def test_auto_runs_openalex_topics_path(self):
        # Reuse v0.151 stub pattern.
        from tests.test_v0_151_populate_concepts_openalex import (
            _StubClient, _make_work, _topic, _write_manifest,
            _register_paper,
        )
        from lib import project as project_mod

        with isolated_cache():
            mod = _load_concepts_module()
            chosen, _ = mod._resolve_auto_source()
            self.assertEqual(chosen, "openalex")

            pid = project_mod.create("concepts-auto-int")
            cid = "auto_2024_topic_zzzzzz"
            _write_manifest(cid, openalex_id="WAUTO")
            _register_paper(pid, cid)
            work = _make_work([
                _topic("Auto Topic", 0.9, subfield="SF",
                       field="F", domain="D"),
            ])
            client = _StubClient({"WAUTO": work})
            res = mod.populate_from_openalex(
                pid, paper_id=cid, client=client,
            )
            self.assertEqual(res["papers_processed"], 1)
            self.assertEqual(res["concepts_added"], 4)
            self.assertEqual(res["edges_added"], 4)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        CitationsAutoResolverTests,
        CitationsAutoIntegrationTests,
        ConceptsAutoResolverTests,
        ConceptsAutoIntegrationTests,
    ))
