"""v0.53.1 — Wide Research POC tests."""

from tests import _shim  # noqa: F401

import json
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from lib.wide_research import (  # noqa: E402
    HARD_DOLLAR_CEILING, TASK_TYPE_DEFAULTS, TaskSpec, WIDE_MAX_ITEMS,
    WIDE_THRESHOLD_ITEMS, WideRunPlan, _estimate_cost, collect_results,
    decompose, write_workspace,
)


def _items(n: int) -> list[dict]:
    return [
        {"canonical_id": f"paper_{i:04d}", "title": f"Paper {i}",
         "year": 2020 + (i % 5)}
        for i in range(n)
    ]


class TaskSpecTests(TestCase):
    def test_round_trip(self):
        s = TaskSpec(
            sub_agent_id="wide-test-item-0001",
            task_type="triage",
            objective="Read abstract; score relevance.",
            input_item={"title": "X", "year": 2024},
            output_schema={"fields": ["score"], "format": "json"},
            tools_allowed=["paper-discovery"],
            scope_exclusions="other agents covering Y",
        )
        d = s.to_dict()
        s2 = TaskSpec.from_dict(d)
        self.assertEqual(s2.sub_agent_id, s.sub_agent_id)
        self.assertEqual(s2.task_type, "triage")
        self.assertEqual(s2.objective, s.objective)
        self.assertEqual(s2.input_item, s.input_item)
        self.assertEqual(s2.tools_allowed, ["paper-discovery"])

    def test_to_prompt_stable_no_timestamp(self):
        # KV-cache stability: prompt must not contain timestamps
        s = TaskSpec(
            sub_agent_id="wide-x", task_type="triage",
            objective="x", input_item={"a": 1},
            output_schema={"fields": ["a"]},
            tools_allowed=["Read"],
        )
        prompt = s.to_prompt()
        # No common timestamp patterns
        self.assertNotIn("2026-", prompt)
        self.assertNotIn("12:", prompt)
        self.assertNotIn("00Z", prompt)
        # Spec content present
        self.assertIn("wide-x", prompt)
        self.assertIn("triage", prompt)

    def test_to_prompt_deterministic(self):
        # Same TaskSpec produces same prompt — KV-cache hit
        s = TaskSpec(
            sub_agent_id="wide-x", task_type="triage",
            objective="x", input_item={"a": 1, "b": 2},
            output_schema={"fields": ["a"]},
            tools_allowed=["Read"],
        )
        self.assertEqual(s.to_prompt(), s.to_prompt())


class DecomposeTests(TestCase):
    def test_decompose_triage(self):
        plan = decompose(
            run_id="testrun",
            user_query="Triage 15 papers on BFT",
            items=_items(15),
            task_type="triage",
        )
        self.assertEqual(plan.run_id, "testrun")
        self.assertEqual(plan.task_type, "triage")
        self.assertEqual(len(plan.sub_specs), 15)
        self.assertEqual(len(plan.items), 15)
        # Each sub-agent gets unique workspace
        ws = {s.filesystem_workspace for s in plan.sub_specs}
        self.assertEqual(len(ws), 15)
        # Cost in plausible range — 15 sub-agents × 15K tokens triage
        self.assertGreater(plan.estimated_dollar_cost, 0.0)

    def test_decompose_below_threshold_rejected(self):
        with self.assertRaises(ValueError):
            decompose(
                run_id="r", user_query="q",
                items=_items(WIDE_THRESHOLD_ITEMS - 1),
                task_type="triage",
            )

    def test_decompose_above_max_rejected(self):
        with self.assertRaises(ValueError):
            decompose(
                run_id="r", user_query="q",
                items=_items(WIDE_MAX_ITEMS + 1),
                task_type="triage",
            )

    def test_decompose_unknown_type_rejected(self):
        with self.assertRaises(ValueError):
            decompose(
                run_id="r", user_query="q",
                items=_items(15), task_type="frobnicate",
            )

    def test_decompose_includes_scope_exclusions(self):
        plan = decompose(
            run_id="r", user_query="q",
            items=_items(15), task_type="triage",
        )
        for spec in plan.sub_specs:
            self.assertIn("Other", spec.scope_exclusions)
            self.assertIn("do not search for or synthesize", spec.scope_exclusions)

    def test_decompose_unique_sub_agent_ids(self):
        plan = decompose(
            run_id="abc", user_query="q",
            items=_items(20), task_type="triage",
        )
        ids = [s.sub_agent_id for s in plan.sub_specs]
        self.assertEqual(len(ids), len(set(ids)))
        for sid in ids:
            self.assertTrue(sid.startswith("wide-abc-item-"))

    def test_decompose_read_tooling(self):
        plan = decompose(
            run_id="r", user_query="q",
            items=_items(10), task_type="read",
        )
        spec = plan.sub_specs[0]
        self.assertIn("paper-acquire", spec.tools_allowed)
        self.assertIn("pdf-extract", spec.tools_allowed)
        # Read tasks get bigger budget
        self.assertGreater(spec.max_tokens_budget, 50_000)


class CostEstimateTests(TestCase):
    def test_cost_scales_with_tokens(self):
        c1 = _estimate_cost(10_000, 100)
        c2 = _estimate_cost(100_000, 1_000)
        self.assertLess(c1, c2)

    def test_cost_nonzero(self):
        self.assertGreater(_estimate_cost(50_000, 500), 0.0)

    def test_hard_ceiling_warning_renders(self):
        # 250 sub-agents × 80K read = ~20M tokens → hits ceiling
        plan = decompose(
            run_id="r", user_query="q",
            items=_items(250), task_type="read",
        )
        md = plan.render_decomposition_table()
        if plan.estimated_dollar_cost > HARD_DOLLAR_CEILING:
            self.assertIn("hard ceiling", md)
            self.assertIn("--allow-expensive", md)


class WorkspaceTests(TestCase):
    def test_write_workspace_creates_files(self):
        with isolated_cache() as cache_dir:
            spec = TaskSpec(
                sub_agent_id="wide-r-item-0000",
                task_type="triage",
                objective="x",
                input_item={"title": "X"},
                output_schema={"fields": ["a"]},
                tools_allowed=["Read"],
                filesystem_workspace=str(cache_dir / "ws"),
            )
            ws = write_workspace(spec)
            self.assertTrue((ws / "taskspec.json").exists())
            self.assertTrue((ws / "task_progress.md").exists())
            self.assertTrue((ws / "findings").is_dir())
            # taskspec round-trips
            persisted = json.loads((ws / "taskspec.json").read_text())
            self.assertEqual(persisted["sub_agent_id"], spec.sub_agent_id)


class CollectResultsTests(TestCase):
    def test_collect_missing_results(self):
        with isolated_cache() as cache_dir:
            plan = decompose(
                run_id="r", user_query="q",
                items=_items(10), task_type="triage",
                workspace_root=cache_dir,
            )
            results = collect_results(plan)
            self.assertEqual(len(results), 10)
            for r in results:
                self.assertEqual(r["status"], "missing")

    def test_collect_with_partial_results(self):
        with isolated_cache() as cache_dir:
            plan = decompose(
                run_id="r", user_query="q",
                items=_items(10), task_type="triage",
                workspace_root=cache_dir,
            )
            # Simulate one sub-agent completing
            spec = plan.sub_specs[3]
            ws = Path(spec.filesystem_workspace)
            ws.mkdir(parents=True, exist_ok=True)
            (ws / "result.json").write_text(json.dumps({
                "canonical_id": spec.input_item["canonical_id"],
                "relevance_score": 0.85,
                "recommend": "include",
                "reason": "Highly relevant abstract.",
            }))

            results = collect_results(plan)
            statuses = [r["status"] for r in results]
            self.assertEqual(statuses.count("complete"), 1)
            self.assertEqual(statuses.count("missing"), 9)

            done = [r for r in results if r["status"] == "complete"][0]
            self.assertEqual(done["result"]["recommend"], "include")


class TaskTypeDefaultsTests(TestCase):
    def test_all_types_have_defaults(self):
        for ttype in ("triage", "read", "rank", "compare",
                       "survey", "screen"):
            self.assertIn(ttype, TASK_TYPE_DEFAULTS)
            d = TASK_TYPE_DEFAULTS[ttype]
            self.assertIn("tools_allowed", d)
            self.assertIn("output_schema", d)
            self.assertIn("max_tool_calls", d)
            self.assertIn("max_tokens_budget", d)


if __name__ == "__main__":
    sys.exit(run_tests(
        TaskSpecTests, DecomposeTests, CostEstimateTests, WorkspaceTests,
        CollectResultsTests, TaskTypeDefaultsTests,
    ))
