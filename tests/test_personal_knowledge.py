"""v0.11 personal knowledge layer tests: journal, dashboard, cross-project memory."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (_ROOT / "lib" / "sqlite_schema.sql").read_text()

JOURNAL_ADD = _ROOT / ".claude/skills/research-journal/scripts/add_entry.py"
JOURNAL_LIST = _ROOT / ".claude/skills/research-journal/scripts/list_entries.py"
JOURNAL_SEARCH = _ROOT / ".claude/skills/research-journal/scripts/search.py"
DASHBOARD = _ROOT / ".claude/skills/project-dashboard/scripts/dashboard.py"
XPROJ_SEARCH = _ROOT / ".claude/skills/cross-project-memory/scripts/search.py"
XPROJ_FIND = _ROOT / ".claude/skills/cross-project-memory/scripts/find_paper.py"


def _run(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True,
                          text=True, input=stdin)


def _seed_project(cache_dir: Path, pid: str = "pk_proj",
                   name: str = "PK Test", question: str = "test q") -> str:
    p = cache_dir / "projects" / pid
    p.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p / "project.db")
    con.executescript(SCHEMA)
    con.execute(
        "INSERT INTO projects (project_id, name, question, created_at) "
        "VALUES (?, ?, ?, ?)",
        (pid, name, question, "2026-04-24T00:00:00Z"),
    )
    con.commit()
    con.close()
    return pid


# ---------------- research-journal ----------------

class JournalAddTests(TestCase):
    def test_add_writes_db_and_disk(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            r = _run(str(JOURNAL_ADD), "--project-id", pid,
                     "--text", "Discovered scaling law in Vaswani 2017")
            assert r.returncode == 0, f"stderr={r.stderr}"
            result = json.loads(r.stdout)
            self.assertTrue(result["entry_id"] >= 1)
            self.assertTrue(Path(result["path"]).exists())

            # DB has the row
            con = sqlite3.connect(cache_dir / "projects" / pid / "project.db")
            row = con.execute(
                "SELECT body FROM journal_entries WHERE entry_id=?",
                (result["entry_id"],),
            ).fetchone()
            con.close()
            self.assertIn("scaling law", row[0])

            # Disk file has the body verbatim
            disk = Path(result["path"]).read_text()
            self.assertIn("Discovered scaling law", disk)

    def test_add_via_stdin(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            r = _run(str(JOURNAL_ADD), "--project-id", pid,
                     stdin="Note from stdin")
            assert r.returncode == 0, f"stderr={r.stderr}"

    def test_add_with_tags_and_links(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            r = _run(str(JOURNAL_ADD), "--project-id", pid,
                     "--text", "Linked note",
                     "--tags", "transformers,scaling",
                     "--link-papers", "vaswani_2017_abc",
                     "--link-manuscripts", "ms_one,ms_two")
            assert r.returncode == 0
            eid = json.loads(r.stdout)["entry_id"]
            con = sqlite3.connect(cache_dir / "projects" / pid / "project.db")
            row = con.execute(
                "SELECT tags, links FROM journal_entries WHERE entry_id=?",
                (eid,),
            ).fetchone()
            con.close()
            self.assertEqual(json.loads(row[0]), ["transformers", "scaling"])
            links = json.loads(row[1])
            self.assertEqual(links["papers"], ["vaswani_2017_abc"])
            self.assertEqual(links["manuscripts"], ["ms_one", "ms_two"])

    def test_empty_body_rejected(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            r = _run(str(JOURNAL_ADD), "--project-id", pid, "--text", "   ")
            self.assertEqual(r.returncode, 1)


class JournalListTests(TestCase):
    def _add(self, cache_dir: Path, pid: str, body: str,
             tags: str = "", date: str | None = None,
             link_paper: str | None = None) -> int:
        cmd = [str(JOURNAL_ADD), "--project-id", pid, "--text", body]
        if tags:
            cmd += ["--tags", tags]
        if date:
            cmd += ["--date", date]
        if link_paper:
            cmd += ["--link-papers", link_paper]
        r = _run(*cmd)
        assert r.returncode == 0, f"stderr={r.stderr}"
        return json.loads(r.stdout)["entry_id"]

    def test_list_all(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            self._add(cache_dir, pid, "first")
            self._add(cache_dir, pid, "second")
            r = _run(str(JOURNAL_LIST), "--project-id", pid)
            entries = json.loads(r.stdout)
            self.assertEqual(len(entries), 2)

    def test_filter_by_tag(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            self._add(cache_dir, pid, "tagged note", tags="ml")
            self._add(cache_dir, pid, "untagged note")
            r = _run(str(JOURNAL_LIST), "--project-id", pid, "--tag", "ml")
            entries = json.loads(r.stdout)
            self.assertEqual(len(entries), 1)
            self.assertIn("tagged", entries[0]["body"])

    def test_filter_by_date_range(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            self._add(cache_dir, pid, "old note", date="2024-01-15")
            self._add(cache_dir, pid, "new note", date="2026-04-15")
            r = _run(str(JOURNAL_LIST), "--project-id", pid,
                     "--from", "2026-01-01")
            entries = json.loads(r.stdout)
            self.assertEqual(len(entries), 1)
            self.assertIn("new", entries[0]["body"])

    def test_filter_by_linked_paper(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            self._add(cache_dir, pid, "linked", link_paper="paper_a")
            self._add(cache_dir, pid, "unlinked")
            r = _run(str(JOURNAL_LIST), "--project-id", pid,
                     "--linked-paper", "paper_a")
            entries = json.loads(r.stdout)
            self.assertEqual(len(entries), 1)


class JournalSearchTests(TestCase):
    def test_search_finds_substring(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            _run(str(JOURNAL_ADD), "--project-id", pid,
                 "--text", "Found a scaling law in transformer models")
            _run(str(JOURNAL_ADD), "--project-id", pid,
                 "--text", "Unrelated note")
            r = _run(str(JOURNAL_SEARCH), "--project-id", pid,
                     "--query", "scaling")
            result = json.loads(r.stdout)
            self.assertEqual(result["matches"], 1)
            self.assertIn("snippet", result["results"][0])

    def test_empty_query_rejected(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            r = _run(str(JOURNAL_SEARCH), "--project-id", pid, "--query", "")
            self.assertEqual(r.returncode, 1)


# ---------------- project-dashboard ----------------

class DashboardTests(TestCase):
    def test_empty_dashboard(self):
        with isolated_cache():
            r = _run(str(DASHBOARD))
            assert r.returncode == 0, f"stderr={r.stderr}"
            report = json.loads(r.stdout)
            self.assertEqual(report["project_count"], 0)

    def test_dashboard_aggregates_one_project(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir, name="Vision project",
                                 question="How does ViT scale?")
            # Add some data: a journal entry, an audit finding, reading state
            _run(str(JOURNAL_ADD), "--project-id", pid,
                 "--text", "today's note")

            db = cache_dir / "projects" / pid / "project.db"
            con = sqlite3.connect(db)
            con.execute(
                "INSERT INTO reading_state "
                "(canonical_id, project_id, state, updated_at) "
                "VALUES ('p1', ?, 'to-read', '2026-04-24T00:00:00Z')",
                (pid,),
            )
            con.execute(
                "INSERT INTO reading_state "
                "(canonical_id, project_id, state, updated_at) "
                "VALUES ('p2', ?, 'cited', '2026-04-24T00:00:00Z')",
                (pid,),
            )
            con.execute(
                "INSERT INTO manuscript_audit_findings "
                "(manuscript_id, claim_id, kind, severity, evidence, at) "
                "VALUES ('ms', 'c-1', 'overclaim', 'minor', 'e', '2026-04-24T00:00:00Z')"
            )
            con.commit()
            con.close()

            r = _run(str(DASHBOARD), "--project-id", pid)
            report = json.loads(r.stdout)
            self.assertEqual(report["project_count"], 1)
            proj = report["projects"][0]
            self.assertEqual(proj["name"], "Vision project")
            self.assertEqual(proj["reading_state"].get("to-read"), 1)
            self.assertEqual(proj["reading_state"].get("cited"), 1)
            self.assertEqual(proj["open_audit_issues_by_kind"].get("overclaim"), 1)
            self.assertEqual(len(proj["recent_journal_entries"]), 1)

    def test_dashboard_markdown_format(self):
        with isolated_cache() as cache_dir:
            _seed_project(cache_dir, name="MD Project", question="md?")
            r = _run(str(DASHBOARD), "--format", "md")
            assert r.returncode == 0, f"stderr={r.stderr}"
            self.assertIn("# Coscientist dashboard", r.stdout)
            self.assertIn("MD Project", r.stdout)

    def test_dashboard_unknown_project(self):
        with isolated_cache():
            r = _run(str(DASHBOARD), "--project-id", "nonexistent")
            self.assertEqual(r.returncode, 1)


# ---------------- cross-project-memory ----------------

class CrossProjectSearchTests(TestCase):
    def _setup_two_projects_with_papers(self, cache_dir: Path) -> tuple[str, str]:
        # Two projects, each with one paper artifact
        for pid, paper_cid, paper_title in [
            ("proj_a", "vaswani_2017_attention_aaa", "Attention is all you need"),
            ("proj_b", "devlin_2019_bert_bbb", "BERT pre-training"),
        ]:
            _seed_project(cache_dir, pid=pid, name=f"Project {pid}",
                           question="q")
            paper_dir = cache_dir / "papers" / paper_cid
            paper_dir.mkdir(parents=True, exist_ok=True)
            (paper_dir / "manifest.json").write_text(json.dumps({
                "canonical_id": paper_cid, "doi": f"10.0000/{paper_cid}",
                "state": "discovered",
            }))
            (paper_dir / "metadata.json").write_text(json.dumps({
                "title": paper_title, "abstract": "An abstract about transformers.",
                "authors": ["Author"], "year": 2017,
            }))
            con = sqlite3.connect(cache_dir / "projects" / pid / "project.db")
            con.execute(
                "INSERT INTO artifact_index "
                "(artifact_id, kind, project_id, state, path, created_at, updated_at) "
                "VALUES (?, 'paper', ?, 'discovered', ?, ?, ?)",
                (paper_cid, pid, str(paper_dir),
                 "2026-04-24T00:00:00Z", "2026-04-24T00:00:00Z"),
            )
            con.commit()
            con.close()
        return ("proj_a", "proj_b")

    def test_search_finds_papers_across_projects(self):
        with isolated_cache() as cache_dir:
            self._setup_two_projects_with_papers(cache_dir)
            r = _run(str(XPROJ_SEARCH), "--query", "transformer")
            assert r.returncode == 0, f"stderr={r.stderr}"
            result = json.loads(r.stdout)
            # Both papers' abstracts mention "transformers"
            self.assertEqual(result["projects_searched"], 2)
            self.assertTrue(result["total_hits"] >= 2)

    def test_search_finds_journal_entries(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            _run(str(JOURNAL_ADD), "--project-id", pid,
                 "--text", "scaling law observation")
            r = _run(str(XPROJ_SEARCH), "--query", "scaling")
            result = json.loads(r.stdout)
            self.assertTrue(any(
                hit["kind"] == "journal-entry" for hit in result["results"].get("journal-entry", [])
            ))

    def test_search_kinds_filter(self):
        with isolated_cache() as cache_dir:
            self._setup_two_projects_with_papers(cache_dir)
            r = _run(str(XPROJ_SEARCH), "--query", "transformer",
                     "--kinds", "papers")
            result = json.loads(r.stdout)
            # Only paper hits should appear
            for kind in result["results"]:
                self.assertEqual(kind, "paper")

    def test_search_invalid_kind_rejected(self):
        with isolated_cache():
            r = _run(str(XPROJ_SEARCH), "--query", "x", "--kinds", "vibes")
            self.assertEqual(r.returncode, 1)


class FindPaperTests(TestCase):
    def _setup(self, cache_dir: Path) -> tuple[str, str]:
        cid = "vaswani_2017_attention_xyz"
        pid = _seed_project(cache_dir, pid="findproj")
        paper_dir = cache_dir / "papers" / cid
        paper_dir.mkdir(parents=True, exist_ok=True)
        (paper_dir / "manifest.json").write_text(json.dumps({
            "canonical_id": cid, "doi": "10.48550/arXiv.1706.03762",
            "state": "discovered",
        }))
        (paper_dir / "metadata.json").write_text(json.dumps({
            "title": "Attention is all you need", "year": 2017,
        }))
        con = sqlite3.connect(cache_dir / "projects" / pid / "project.db")
        con.execute(
            "INSERT INTO artifact_index "
            "(artifact_id, kind, project_id, state, path, created_at, updated_at) "
            "VALUES (?, 'paper', ?, 'discovered', ?, ?, ?)",
            (cid, pid, str(paper_dir), "2026-04-24T00:00:00Z", "2026-04-24T00:00:00Z"),
        )
        con.execute(
            "INSERT INTO reading_state "
            "(canonical_id, project_id, state, updated_at) "
            "VALUES (?, ?, 'cited', '2026-04-24T00:00:00Z')",
            (cid, pid),
        )
        con.commit()
        con.close()
        return pid, cid

    def test_find_by_canonical_id(self):
        with isolated_cache() as cache_dir:
            pid, cid = self._setup(cache_dir)
            r = _run(str(XPROJ_FIND), "--canonical-id", cid)
            assert r.returncode == 0, f"stderr={r.stderr}"
            result = json.loads(r.stdout)
            self.assertEqual(result["matches"], 1)
            paper = result["papers"][0]
            self.assertEqual(paper["canonical_id"], cid)
            self.assertEqual(len(paper["appearances"]), 1)
            self.assertEqual(paper["appearances"][0]["project_id"], pid)
            self.assertEqual(paper["appearances"][0]["reading_state"], "cited")

    def test_find_by_doi(self):
        with isolated_cache() as cache_dir:
            pid, cid = self._setup(cache_dir)
            r = _run(str(XPROJ_FIND), "--doi", "10.48550/arXiv.1706.03762")
            result = json.loads(r.stdout)
            self.assertEqual(result["matches"], 1)
            self.assertEqual(result["papers"][0]["canonical_id"], cid)

    def test_find_by_title_fragment(self):
        with isolated_cache() as cache_dir:
            pid, cid = self._setup(cache_dir)
            r = _run(str(XPROJ_FIND), "--title", "attention is all")
            result = json.loads(r.stdout)
            self.assertEqual(result["matches"], 1)

    def test_find_no_match(self):
        with isolated_cache() as cache_dir:
            self._setup(cache_dir)
            r = _run(str(XPROJ_FIND), "--canonical-id", "does_not_exist")
            result = json.loads(r.stdout)
            # canonical_id explicitly given → 1 candidate, but it has no
            # appearances anywhere
            self.assertEqual(result["matches"], 1)
            self.assertEqual(result["papers"][0]["appearances"], [])


# ---------------- schema ----------------

class JournalSchemaTests(TestCase):
    def test_table_present(self):
        con = sqlite3.connect(":memory:")
        con.executescript(SCHEMA)
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        self.assertIn("journal_entries", names)


if __name__ == "__main__":
    sys.exit(run_tests(
        JournalAddTests,
        JournalListTests,
        JournalSearchTests,
        DashboardTests,
        CrossProjectSearchTests,
        FindPaperTests,
        JournalSchemaTests,
    ))
