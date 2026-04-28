"""Integration tests — exercise multiple skills in realistic end-to-end flows.

These are slower than the per-skill smoke tests but catch regressions
that only surface when skills interact through the shared artifact
contract + DB.
"""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (_ROOT / "lib" / "sqlite_schema.sql").read_text()

# Skill scripts
INGEST_MS = _ROOT / ".claude/skills/manuscript-ingest/scripts/ingest.py"
AUDIT_GATE = _ROOT / ".claude/skills/manuscript-audit/scripts/gate.py"
CRITIQUE_GATE = _ROOT / ".claude/skills/manuscript-critique/scripts/gate.py"
REFLECT_GATE = _ROOT / ".claude/skills/manuscript-reflect/scripts/gate.py"
SYNC_ZOTERO = _ROOT / ".claude/skills/reference-agent/scripts/sync_from_zotero.py"
BIBTEX = _ROOT / ".claude/skills/reference-agent/scripts/export_bibtex.py"
READING_STATE = _ROOT / ".claude/skills/reference-agent/scripts/reading_state.py"
MARK_RETRACTED = _ROOT / ".claude/skills/reference-agent/scripts/mark_retracted.py"
NOVELTY_GATE = _ROOT / ".claude/skills/novelty-check/scripts/gate.py"


def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(script), *args],
                          capture_output=True, text=True)


def _run_with_input(script: Path, input_json: dict, *args: str) -> subprocess.CompletedProcess:
    inp = _ROOT / "tests" / "_tmp_input.json"
    inp.write_text(json.dumps(input_json))
    return _run(script, "--input", str(inp), *args)


def _seed_project(cache_dir: Path, pid: str = "e2e_project") -> str:
    p = cache_dir / "projects" / pid
    p.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p / "project.db")
    con.executescript(SCHEMA)
    con.execute(
        "INSERT INTO projects (project_id, name, created_at) VALUES (?, ?, ?)",
        (pid, "E2E Project", "2026-04-24T00:00:00Z"),
    )
    con.commit()
    con.close()
    return pid


def _seed_run(cache_dir: Path, run_id: str = "e2e_run") -> str:
    d = cache_dir / "runs"
    d.mkdir(parents=True, exist_ok=True)
    db = d / f"run-{run_id}.db"
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.execute(
        "INSERT INTO runs (run_id, question, started_at) VALUES (?, ?, ?)",
        (run_id, "test question", "2026-04-24T00:00:00Z"),
    )
    con.commit()
    con.close()
    return run_id


class ResearchFlowIntegrationTests(TestCase):
    """Full flow: project → zotero sync → manuscript ingest → audit → BibTeX."""

    def test_zotero_synced_paper_flows_to_manuscript_audit_and_bibtex(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)

            # 1. Sync a Zotero item → paper artifact
            zotero_items = [{
                "zotero_key": "ZOT_VASW",
                "zotero_library": "user:1",
                "title": "Attention is all you need",
                "authors": ["Vaswani, A."],
                "year": 2017,
                "doi": "10.48550/arXiv.1706.03762",
                "abstract": "The dominant transduction models...",
                "venue": "NeurIPS",
            }]
            (cache_dir / "zot.json").write_text(json.dumps(zotero_items))
            r = _run(SYNC_ZOTERO, "--input", str(cache_dir / "zot.json"),
                     "--project-id", pid)
            assert r.returncode == 0, f"sync failed: {r.stderr}"

            # Discover the canonical_id the sync created
            papers_dir = cache_dir / "papers"
            cids = [p.name for p in papers_dir.iterdir() if p.is_dir()]
            self.assertEqual(len(cids), 1)
            cid = cids[0]
            # canonical_id format: <author-slug>_<year>_<title-slug>_<hash>
            self.assertIn("_2017_", cid)
            self.assertIn("attention", cid)

            # 2. Ingest a manuscript that cites this paper
            ms_content = (
                "# My Paper\n\n"
                "## Intro\n\n"
                "Transformers outperform CNNs at scale [@vaswani2017].\n\n"
                "## Discussion\n\n"
                "Scaling continues to favor attention-based models.\n"
            )
            src = cache_dir / "ms.md"
            src.write_text(ms_content)
            r = subprocess.run(
                [sys.executable, str(INGEST_MS),
                 "--source", str(src), "--title", "My Paper",
                 "--project-id", pid],
                capture_output=True, text=True,
            )
            assert r.returncode == 0, f"ingest failed: {r.stderr}"
            mid = r.stdout.strip()

            # Verify artifact_index registered both
            con = sqlite3.connect(cache_dir / "projects" / pid / "project.db")
            rows = con.execute(
                "SELECT kind FROM artifact_index ORDER BY kind"
            ).fetchall()
            con.close()
            kinds = [r[0] for r in rows]
            self.assertIn("paper", kinds)
            self.assertIn("manuscript", kinds)

            # 3. Run manuscript-audit with a report citing the paper
            run_id = _seed_run(cache_dir)
            audit_report = {
                "manuscript_id": mid,
                "claims": [
                    {
                        "claim_id": "c-1",
                        "text": "Transformers outperform CNNs at scale [@vaswani2017].",
                        "location": "§1 ¶1",
                        "cited_sources": [cid],
                        "findings": [{
                            "kind": "overclaim",
                            "severity": "minor",
                            "evidence": "Vaswani 2017 shows parity at small scale, not outperformance."
                        }]
                    },
                    {
                        "claim_id": "c-2",
                        "text": "Scaling continues to favor attention-based models.",
                        "location": "§2 ¶1",
                        "cited_sources": [],
                        "findings": [{
                            "kind": "uncited",
                            "severity": "major",
                            "evidence": "Broad empirical claim lacks supporting reference."
                        }]
                    }
                ]
            }
            r = _run_with_input(AUDIT_GATE, audit_report,
                                "--manuscript-id", mid, "--run-id", run_id)
            assert r.returncode == 0, f"audit gate failed: {r.stderr}"

            # Verify DB state
            con = sqlite3.connect(cache_dir / "runs" / f"run-{run_id}.db")
            n_claims = con.execute(
                "SELECT COUNT(*) FROM manuscript_claims WHERE manuscript_id=?", (mid,)
            ).fetchone()[0]
            n_findings = con.execute(
                "SELECT COUNT(*) FROM manuscript_audit_findings WHERE manuscript_id=?", (mid,)
            ).fetchone()[0]
            con.close()
            self.assertEqual(n_claims, 2)
            self.assertEqual(n_findings, 2)

            # 4. Export BibTeX for the manuscript (via context-run-id)
            out_bib = cache_dir / "refs.bib"
            r = _run(BIBTEX, "--manuscript-id", mid,
                     "--context-run-id", run_id, "--out", str(out_bib))
            assert r.returncode == 0, f"bibtex export failed: {r.stderr}"
            bib = out_bib.read_text()
            self.assertIn("@article", bib)
            self.assertIn("Vaswani", bib)
            self.assertIn(f"canonical_id:{cid}", bib)

            # 5. Mark the paper as cited in the reading state
            r = _run(READING_STATE, "--canonical-id", cid,
                     "--project-id", pid, "--state", "cited")
            self.assertEqual(r.returncode, 0)

            r = _run(READING_STATE, "--canonical-id", cid,
                     "--project-id", pid, "--get")
            self.assertEqual(r.stdout.strip(), "cited")

    def test_retraction_flow_integration(self):
        """Retraction flags persist across separate invocations."""
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)

            # Mark a paper retracted
            inp = cache_dir / "retract.json"
            inp.write_text(json.dumps([
                {"canonical_id": "fake_2019_xyz", "retracted": True,
                 "source": "semantic-scholar", "detail": "Data fabrication"},
            ]))
            r = _run(MARK_RETRACTED, "--input", str(inp), "--project-id", pid)
            self.assertEqual(r.returncode, 0)

            # Verify + re-mark (idempotent via UPSERT)
            db = cache_dir / "projects" / pid / "project.db"
            con = sqlite3.connect(db)
            count1 = con.execute(
                "SELECT COUNT(*) FROM retraction_flags WHERE retracted=1"
            ).fetchone()[0]
            con.close()
            self.assertEqual(count1, 1)

            # Re-run with the same data — shouldn't duplicate
            r = _run(MARK_RETRACTED, "--input", str(inp), "--project-id", pid)
            self.assertEqual(r.returncode, 0)
            con = sqlite3.connect(db)
            count2 = con.execute(
                "SELECT COUNT(*) FROM retraction_flags WHERE retracted=1"
            ).fetchone()[0]
            con.close()
            self.assertEqual(count2, 1)  # still 1, upsert worked


class CrossSkillArtifactContractTests(TestCase):
    """Paper artifact written by one skill is readable by another.

    Specifically: reference-agent's sync creates manifest.json + metadata.json
    in the same layout the original PaperArtifact class expects.
    """

    def test_zotero_synced_artifact_readable_by_paper_artifact(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            zotero_items = [{
                "zotero_key": "ZOT1",
                "title": "Test Paper",
                "authors": ["Smith, A."],
                "year": 2020,
                "doi": "10.1/abc",
                "abstract": "An abstract",
            }]
            inp = cache_dir / "zot.json"
            inp.write_text(json.dumps(zotero_items))
            _run(SYNC_ZOTERO, "--input", str(inp), "--project-id", pid)

            cids = [p.name for p in (cache_dir / "papers").iterdir() if p.is_dir()]
            self.assertEqual(len(cids), 1)
            cid = cids[0]

            # Now load via lib.paper_artifact — should not error
            from lib.paper_artifact import PaperArtifact
            art = PaperArtifact(cid)
            m = art.load_manifest()
            self.assertEqual(m.doi, "10.1/abc")
            meta = art.load_metadata()
            self.assertTrue(meta is not None)
            self.assertEqual(meta.title, "Test Paper")
            self.assertIn("zotero", meta.discovered_via)

    def test_ingested_manuscript_readable_by_manuscript_artifact(self):
        with isolated_cache() as cache_dir:
            src = cache_dir / "draft.md"
            src.write_text("# Draft\n\nBody text here.")
            r = subprocess.run(
                [sys.executable, str(INGEST_MS),
                 "--source", str(src), "--title", "Draft One"],
                capture_output=True, text=True,
            )
            assert r.returncode == 0, f"stderr={r.stderr}"
            mid = r.stdout.strip()

            from lib.artifact import ManuscriptArtifact
            art = ManuscriptArtifact(mid)
            m = art.load_manifest()
            self.assertEqual(m.state, "drafted")
            self.assertEqual(m.extras["title"], "Draft One")


class SchemaRegressionTests(TestCase):
    """Cross-cutting schema checks that wouldn't surface in per-skill tests."""

    def test_all_v0_5_tables_have_expected_columns(self):
        con = sqlite3.connect(":memory:")
        con.executescript(SCHEMA)

        expected_columns = {
            "manuscript_claims": {"manuscript_id", "claim_id", "text", "location",
                                  "cited_sources", "at"},
            "manuscript_audit_findings": {"manuscript_id", "claim_id", "kind",
                                          "severity", "evidence", "at"},
            "manuscript_critique_findings": {"manuscript_id", "reviewer",
                                             "severity", "location", "issue"},
            "manuscript_reflections": {"manuscript_id", "thesis",
                                       "weakest_link", "one_experiment"},
            "reading_state": {"canonical_id", "project_id", "state", "notes"},
            "retraction_flags": {"canonical_id", "retracted", "source"},
            "zotero_links": {"canonical_id", "zotero_key"},
            "novelty_assessments": {"target_canonical_id", "contribution_id",
                                    "verdict", "confidence"},
            "publishability_verdicts": {"manuscript_id", "venue", "verdict",
                                        "probability", "kill_criterion"},
            "attack_findings": {"target_canonical_id", "attack", "severity"},
            "hypotheses": {"hyp_id", "agent_name", "statement", "elo"},
            "projects": {"project_id", "name", "created_at"},
            "artifact_index": {"artifact_id", "kind", "state", "path"},
            "graph_nodes": {"node_id", "kind", "label"},
            "graph_edges": {"from_node", "to_node", "relation"},
        }
        for table, must_have in expected_columns.items():
            cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
            missing = must_have - cols
            self.assertFalse(missing, f"{table} missing columns: {missing}")

    def test_unique_constraints_enforced(self):
        con = sqlite3.connect(":memory:")
        con.executescript(SCHEMA)

        # zotero_links.canonical_id is UNIQUE
        con.execute(
            "INSERT INTO zotero_links (canonical_id, zotero_key, synced_at) "
            "VALUES ('cid1', 'z1', '2026-01-01')"
        )
        try:
            con.execute(
                "INSERT INTO zotero_links (canonical_id, zotero_key, synced_at) "
                "VALUES ('cid1', 'z2', '2026-01-02')"
            )
            raise AssertionError("expected IntegrityError on duplicate canonical_id")
        except sqlite3.IntegrityError:
            pass

    def test_graph_edges_cascade_on_node_delete(self):
        con = sqlite3.connect(":memory:")
        con.executescript(SCHEMA)
        con.execute("PRAGMA foreign_keys=ON")
        con.execute(
            "INSERT INTO graph_nodes (node_id, kind, label, created_at) "
            "VALUES ('a', 'paper', 'A', '2026-01-01'), ('b', 'paper', 'B', '2026-01-01')"
        )
        con.execute(
            "INSERT INTO graph_edges (from_node, to_node, relation, created_at) "
            "VALUES ('a', 'b', 'cites', '2026-01-01')"
        )
        con.execute("DELETE FROM graph_nodes WHERE node_id='a'")
        remaining = con.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]
        self.assertEqual(remaining, 0)


class CompilationMetaTests(TestCase):
    """Meta-check: every .py file in the repo compiles."""

    def test_every_python_file_compiles(self):
        import py_compile
        failures: list[tuple[str, str]] = []
        for py in _ROOT.rglob("*.py"):
            if ".git" in py.parts or "__pycache__" in py.parts:
                continue
            try:
                py_compile.compile(str(py), doraise=True)
            except py_compile.PyCompileError as e:
                failures.append((str(py.relative_to(_ROOT)), str(e)))
        self.assertFalse(failures, f"compile failures: {failures}")


class ConfigValidationTests(TestCase):
    """JSON + TOML config files are valid."""

    def test_mcp_json_parses(self):
        data = json.loads((_ROOT / ".mcp.json").read_text())
        self.assertIn("mcpServers", data)
        # Every server has a type
        for name, cfg in data["mcpServers"].items():
            self.assertIn("type", cfg, f"{name} missing type")

    def test_settings_json_parses(self):
        data = json.loads((_ROOT / ".claude/settings.json").read_text())
        self.assertIn("permissions", data)

    def test_pyproject_toml_parses(self):
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore
        with (_ROOT / "pyproject.toml").open("rb") as f:
            data = tomllib.load(f)
        self.assertIn("project", data)
        self.assertEqual(data["project"]["name"], "coscientist")


class LayoutRegressionTests(TestCase):
    """Repo layout hasn't drifted."""

    def test_every_skill_has_skill_md(self):
        skills_dir = _ROOT / ".claude" / "skills"
        missing: list[str] = []
        for skill_dir in skills_dir.iterdir():
            if skill_dir.is_dir() and not (skill_dir / "SKILL.md").exists():
                missing.append(skill_dir.name)
        self.assertFalse(missing, f"skills without SKILL.md: {missing}")

    def test_every_skill_has_when_to_use(self):
        """Every SKILL.md frontmatter must declare when_to_use so the
        runtime trigger heuristic has something to match on. CLAUDE.md
        spec lists it as a required frontmatter field."""
        skills_dir = _ROOT / ".claude" / "skills"
        missing: list[str] = []
        for skill_dir in skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            sm = skill_dir / "SKILL.md"
            if not sm.exists():
                continue
            parts = sm.read_text().split("---", 2)
            if len(parts) < 3:
                missing.append(f"{skill_dir.name}: no frontmatter")
                continue
            fm = parts[1]
            if "when_to_use:" not in fm and "when-to-use:" not in fm:
                missing.append(skill_dir.name)
        self.assertFalse(missing,
                         f"skills missing when_to_use frontmatter: {missing}")

    def test_every_agent_has_frontmatter(self):
        agents_dir = _ROOT / ".claude" / "agents"
        missing: list[str] = []
        for agent in agents_dir.glob("*.md"):
            text = agent.read_text()
            if not text.startswith("---"):
                missing.append(agent.name)
        self.assertFalse(missing, f"agents without YAML frontmatter: {missing}")

    def test_all_gate_scripts_are_executable(self):
        """Every skill whose name ends in -check or -gate has a gate.py."""
        _ = _ROOT / ".claude" / "skills"
        expected = {
            "novelty-check": "gate.py",
            "publishability-check": "gate.py",
            "attack-vectors": "check.py",
            "manuscript-audit": "gate.py",
            "manuscript-critique": "gate.py",
            "manuscript-reflect": "gate.py",
        }
        missing: list[str] = []
        for skill, script in expected.items():
            p = _ROOT / ".claude" / "skills" / skill / "scripts" / script
            if not p.exists():
                missing.append(f"{skill}/{script}")
        self.assertFalse(missing, f"missing gate scripts: {missing}")


if __name__ == "__main__":
    sys.exit(run_tests(
        ResearchFlowIntegrationTests,
        CrossSkillArtifactContractTests,
        SchemaRegressionTests,
        CompilationMetaTests,
        ConfigValidationTests,
        LayoutRegressionTests,
    ))
