"""Structural-refactor tests: project + polymorphic artifact + graph."""

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests


class ProjectTests(TestCase):
    def test_create_idempotent(self):
        with isolated_cache():
            from lib.project import create, get
            pid = create("Scaling laws")
            self.assertEqual(create("Scaling laws"), pid)
            meta = get(pid)
            self.assertTrue(meta is not None)
            self.assertEqual(meta["name"], "Scaling laws")

    def test_project_id_deterministic(self):
        with isolated_cache():
            from lib.project import project_id_for
            self.assertEqual(
                project_id_for("Scaling laws"),
                project_id_for("Scaling laws"),
            )

    def test_list_all_returns_created(self):
        with isolated_cache():
            from lib.project import create, list_all
            create("Proj A")
            create("Proj B")
            ids = {p["project_id"] for p in list_all()}
            self.assertEqual(len(ids), 2)

    def test_register_artifact(self):
        with isolated_cache():
            from lib.artifact import ManuscriptArtifact
            from lib.project import create, register_artifact
            pid = create("Proj X")
            m = ManuscriptArtifact("test_ms")
            register_artifact(pid, "test_ms", "manuscript", "drafted", m.root)
            # second call with different state should update, not duplicate
            register_artifact(pid, "test_ms", "manuscript", "audited", m.root)


class ArtifactTests(TestCase):
    def test_manuscript_state_machine(self):
        with isolated_cache():
            from lib.artifact import ManuscriptArtifact
            m = ManuscriptArtifact("ms-1")
            self.assertEqual(m.load_manifest().state, "drafted")
            m.set_state("audited")
            self.assertEqual(m.load_manifest().state, "audited")
            m.set_state("revised")
            self.assertEqual(m.load_manifest().state, "revised")

    def test_experiment_state_machine(self):
        with isolated_cache():
            from lib.artifact import ExperimentArtifact
            e = ExperimentArtifact("exp-1")
            e.set_state("preregistered")
            e.set_state("running")

    def test_invalid_state_rejected(self):
        with isolated_cache():
            from lib.artifact import ManuscriptArtifact
            m = ManuscriptArtifact("ms-bad")
            with self.assertRaises(ValueError):
                m.set_state("not-a-state")

    def test_manifest_persisted(self):
        with isolated_cache():
            from lib.artifact import ManuscriptArtifact
            m = ManuscriptArtifact("ms-persist")
            m.set_state("audited")
            # re-open
            m2 = ManuscriptArtifact("ms-persist")
            self.assertEqual(m2.load_manifest().state, "audited")


class GraphTests(TestCase):
    def _setup_project(self):
        from lib.project import create
        return create("Graph test project")

    def test_add_and_find_neighbors(self):
        with isolated_cache():
            from lib import graph
            pid = self._setup_project()
            a = graph.add_node(pid, "paper", "a", "Paper A")
            b = graph.add_node(pid, "concept", "attn", "Attention")
            graph.add_edge(pid, a, b, "about")
            ns = graph.neighbors(pid, a, relation="about")
            self.assertEqual(len(ns), 1)
            self.assertEqual(ns[0]["node_id"], b)

    def test_walk_transitive(self):
        with isolated_cache():
            from lib import graph
            pid = self._setup_project()
            a = graph.add_node(pid, "paper", "a", "A")
            b = graph.add_node(pid, "paper", "b", "B")
            c = graph.add_node(pid, "paper", "c", "C")
            graph.add_edge(pid, a, b, "cites")
            graph.add_edge(pid, b, c, "cites")
            reached = graph.walk(pid, a, "cites", max_hops=2)
            ids = {n["node_id"] for n in reached}
            self.assertIn(b, ids)
            self.assertIn(c, ids)

    def test_hubs_ranking(self):
        with isolated_cache():
            from lib import graph
            pid = self._setup_project()
            hub = graph.add_node(pid, "paper", "hub", "Hub paper")
            for i in range(5):
                citer = graph.add_node(pid, "paper", f"c{i}", f"Citer {i}")
                graph.add_edge(pid, citer, hub, "cites")
            isolated = graph.add_node(pid, "paper", "iso", "Isolated")
            top = graph.hubs(pid, "paper", "cites", top_k=3)
            # hub should rank first
            self.assertEqual(top[0]["node_id"], hub)

    def test_in_degree(self):
        with isolated_cache():
            from lib import graph
            pid = self._setup_project()
            t = graph.add_node(pid, "paper", "t", "Target")
            for i in range(3):
                s = graph.add_node(pid, "paper", f"s{i}", f"S{i}")
                graph.add_edge(pid, s, t, "cites")
            self.assertEqual(graph.in_degree(pid, t, "cites"), 3)
            self.assertEqual(graph.in_degree(pid, t, "extends"), 0)

    def test_invalid_relation_rejected(self):
        with isolated_cache():
            from lib import graph
            pid = self._setup_project()
            a = graph.add_node(pid, "paper", "a", "A")
            b = graph.add_node(pid, "paper", "b", "B")
            with self.assertRaises(ValueError):
                graph.add_edge(pid, a, b, "not-a-relation")


if __name__ == "__main__":
    import sys
    sys.exit(run_tests(ProjectTests, ArtifactTests, GraphTests))
