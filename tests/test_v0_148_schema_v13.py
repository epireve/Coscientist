"""v0.148 — schema v13 + graph kinds + external_ids tests."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from lib import graph as graph_mod
from lib import migrations
from lib.cache import paper_dir
from lib.project import create as create_project, project_db_path
from tests.harness import TestCase, isolated_cache, run_tests


class ValidKindsTests(TestCase):
    def test_institution_kind_valid(self):
        self.assertIn("institution", graph_mod.VALID_KINDS)

    def test_funder_kind_valid(self):
        self.assertIn("funder", graph_mod.VALID_KINDS)

    def test_affiliated_with_relation_valid(self):
        self.assertIn("affiliated-with", graph_mod.VALID_RELATIONS)

    def test_funded_by_relation_valid(self):
        self.assertIn("funded-by", graph_mod.VALID_RELATIONS)

    def test_node_id_accepts_institution(self):
        nid = graph_mod.node_id("institution", "ror.org_05a28rw58")
        self.assertEqual(nid, "institution:ror.org_05a28rw58")

    def test_node_id_accepts_funder(self):
        nid = graph_mod.node_id("funder", "F4320332161")
        self.assertEqual(nid, "funder:F4320332161")


class MigrationV13Tests(TestCase):
    def test_v13_in_all_versions(self):
        self.assertIn(13, migrations.ALL_VERSIONS)

    def test_v13_sql_file_exists(self):
        sql_dir = Path(migrations.__file__).parent / "migrations_sql"
        self.assertTrue((sql_dir / "v13.sql").exists())

    def test_v13_applies_to_project_db(self):
        with isolated_cache():
            pid = create_project(name="t", question="q")
            db = project_db_path(pid)
            applied = migrations.applied_versions(db)
            self.assertIn(13, applied)

    def test_v13_skipped_for_db_without_graph_nodes(self):
        # Pass an empty migrations list so we only test the in-code v13
        # gate (graph_nodes existence). DB has no graph_nodes table.
        with isolated_cache():
            from lib.cache import cache_root
            tmp = cache_root() / "no_graph.db"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(tmp)
            con.execute(
                "CREATE TABLE projects (project_id TEXT PRIMARY KEY)"
            )
            con.commit()
            con.close()
            applied = migrations.ensure_current(tmp, migrations=[])
            self.assertNotIn(13, applied)

    def test_v13_columns_added(self):
        with isolated_cache():
            pid = create_project(name="t2", question="q2")
            db = project_db_path(pid)
            con = sqlite3.connect(db)
            cols = [r[1] for r in con.execute(
                "PRAGMA table_info(graph_nodes)"
            )]
            con.close()
            self.assertIn("external_ids_json", cols)
            self.assertIn("source", cols)


class AddNodeWithExternalIdsTests(TestCase):
    def test_add_node_persists_external_ids(self):
        with isolated_cache():
            pid = create_project(name="t3", question="q3")
            graph_mod.add_node(
                pid, "author", "A123", "Jane Doe",
                external_ids={
                    "openalex_id": "A5012345678",
                    "orcid": "0000-0001-2345-6789",
                    "s2_author_id": "12345",
                },
                source="openalex",
            )
            con = sqlite3.connect(project_db_path(pid))
            row = con.execute(
                "SELECT external_ids_json, source FROM graph_nodes "
                "WHERE node_id=?",
                ("author:A123",),
            ).fetchone()
            con.close()
            self.assertIsNotNone(row)
            ids = json.loads(row[0])
            self.assertEqual(ids["orcid"], "0000-0001-2345-6789")
            self.assertEqual(row[1], "openalex")

    def test_add_node_without_external_ids_still_works(self):
        with isolated_cache():
            pid = create_project(name="t4", question="q4")
            nid = graph_mod.add_node(pid, "paper", "p1", "Title")
            self.assertEqual(nid, "paper:p1")

    def test_add_institution_node(self):
        with isolated_cache():
            pid = create_project(name="t5", question="q5")
            nid = graph_mod.add_node(
                pid, "institution", "I27837315", "MIT",
                external_ids={"ror_id": "https://ror.org/042nb2s44"},
                source="openalex",
            )
            self.assertEqual(nid, "institution:I27837315")

    def test_add_funder_node(self):
        with isolated_cache():
            pid = create_project(name="t6", question="q6")
            nid = graph_mod.add_node(
                pid, "funder", "F4320332161", "NSF",
                external_ids={"crossref_funder_id": "100000001"},
                source="openalex",
            )
            self.assertEqual(nid, "funder:F4320332161")


class MergeExternalIdsTests(TestCase):
    def test_merge_adds_new_keys(self):
        with isolated_cache():
            pid = create_project(name="t7", question="q7")
            graph_mod.add_node(
                pid, "author", "A1", "X",
                external_ids={"openalex_id": "A1"},
                source="openalex",
            )
            graph_mod.merge_external_ids(
                pid, "author:A1",
                {"orcid": "0000-0001-0000-0001"},
                source="s2",
            )
            con = sqlite3.connect(project_db_path(pid))
            row = con.execute(
                "SELECT external_ids_json, source FROM graph_nodes "
                "WHERE node_id=?",
                ("author:A1",),
            ).fetchone()
            con.close()
            ids = json.loads(row[0])
            self.assertEqual(ids["openalex_id"], "A1")
            self.assertEqual(ids["orcid"], "0000-0001-0000-0001")
            self.assertEqual(row[1], "s2")

    def test_merge_preserves_existing_values(self):
        with isolated_cache():
            pid = create_project(name="t8", question="q8")
            graph_mod.add_node(
                pid, "author", "A2", "Y",
                external_ids={"orcid": "0000-0001-0000-0002"},
            )
            graph_mod.merge_external_ids(
                pid, "author:A2",
                {"orcid": "0000-9999-9999-9999"},  # different value
            )
            con = sqlite3.connect(project_db_path(pid))
            row = con.execute(
                "SELECT external_ids_json FROM graph_nodes WHERE node_id=?",
                ("author:A2",),
            ).fetchone()
            con.close()
            ids = json.loads(row[0])
            # existing wins
            self.assertEqual(ids["orcid"], "0000-0001-0000-0002")

    def test_merge_skips_none_values(self):
        with isolated_cache():
            pid = create_project(name="t9", question="q9")
            graph_mod.add_node(
                pid, "author", "A3", "Z",
                external_ids={"openalex_id": "A3"},
            )
            graph_mod.merge_external_ids(
                pid, "author:A3",
                {"orcid": None, "s2_author_id": "999"},
            )
            con = sqlite3.connect(project_db_path(pid))
            row = con.execute(
                "SELECT external_ids_json FROM graph_nodes WHERE node_id=?",
                ("author:A3",),
            ).fetchone()
            con.close()
            ids = json.loads(row[0])
            self.assertNotIn("orcid", ids)
            self.assertEqual(ids["s2_author_id"], "999")

    def test_merge_no_op_for_missing_node(self):
        with isolated_cache():
            pid = create_project(name="t10", question="q10")
            # Should not raise
            graph_mod.merge_external_ids(
                pid, "author:does-not-exist",
                {"orcid": "0000"},
            )


class EdgeRelationTests(TestCase):
    def test_affiliated_with_edge(self):
        with isolated_cache():
            pid = create_project(name="t11", question="q11")
            a = graph_mod.add_node(pid, "author", "A1", "Jane")
            i = graph_mod.add_node(pid, "institution", "I1", "MIT")
            graph_mod.add_edge(pid, a, i, "affiliated-with")
            con = sqlite3.connect(project_db_path(pid))
            row = con.execute(
                "SELECT relation FROM graph_edges WHERE from_node=? "
                "AND to_node=?",
                (a, i),
            ).fetchone()
            con.close()
            self.assertEqual(row[0], "affiliated-with")

    def test_funded_by_edge(self):
        with isolated_cache():
            pid = create_project(name="t12", question="q12")
            p = graph_mod.add_node(pid, "paper", "p1", "Paper")
            f = graph_mod.add_node(pid, "funder", "F1", "NSF")
            graph_mod.add_edge(pid, p, f, "funded-by",
                               data={"grant_id": "AB-12345"})
            con = sqlite3.connect(project_db_path(pid))
            row = con.execute(
                "SELECT relation, data_json FROM graph_edges "
                "WHERE from_node=? AND to_node=?",
                (p, f),
            ).fetchone()
            con.close()
            self.assertEqual(row[0], "funded-by")
            d = json.loads(row[1])
            self.assertEqual(d["grant_id"], "AB-12345")


if __name__ == "__main__":
    raise SystemExit(run_tests(
        ValidKindsTests, MigrationV13Tests,
        AddNodeWithExternalIdsTests, MergeExternalIdsTests,
        EdgeRelationTests,
    ))
