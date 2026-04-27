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


class CLITests(TestCase):
    """v0.53.2 — gate1, dispatch-manifest, status CLI subcommands."""

    def _cli(self, *args: str) -> tuple[int, str, str]:
        import subprocess
        cli = (_ROOT / ".claude/skills/wide-research/scripts/wide.py")
        r = subprocess.run(
            [sys.executable, str(cli), *args],
            capture_output=True, text=True,
        )
        return r.returncode, r.stdout, r.stderr

    def test_dispatch_refused_before_gate1(self):
        with isolated_cache() as cache_dir:
            items = cache_dir / "items.json"
            items.write_text(json.dumps([
                {"canonical_id": f"p{i}", "title": f"P{i}",
                 "year": 2020 + i % 5} for i in range(10)
            ]))
            rc, out, err = self._cli(
                "init", "--query", "test", "--items", str(items),
                "--type", "triage",
            )
            self.assertEqual(rc, 0, err)
            run_id = json.loads(out)["run_id"]

            # Dispatch without gate1 → fail
            rc, out, err = self._cli(
                "dispatch-manifest", "--run-id", run_id,
            )
            self.assertTrue(rc != 0)
            self.assertIn("Gate 1 not approved", err)

    def test_gate1_approve_unblocks_dispatch(self):
        with isolated_cache() as cache_dir:
            items = cache_dir / "items.json"
            items.write_text(json.dumps([
                {"canonical_id": f"p{i}", "title": f"P{i}",
                 "year": 2020} for i in range(10)
            ]))
            rc, out, _ = self._cli(
                "init", "--query", "test", "--items", str(items),
                "--type", "triage",
            )
            run_id = json.loads(out)["run_id"]

            # Approve
            rc, out, err = self._cli(
                "gate1", "--run-id", run_id, "--verdict", "approve",
            )
            self.assertEqual(rc, 0, err)

            # Dispatch should work now
            rc, out, err = self._cli(
                "dispatch-manifest", "--run-id", run_id,
            )
            self.assertEqual(rc, 0, err)
            d = json.loads(out)
            self.assertEqual(d["n_total"], 10)
            self.assertEqual(d["n_pending"], 10)
            self.assertEqual(d["n_already_complete"], 0)
            self.assertEqual(d["n_batches"], 1)
            # Each batch entry has prompt + workspace + subagent_type
            entry = d["batches"][0][0]
            self.assertIn("prompt", entry)
            self.assertIn("workspace", entry)
            self.assertEqual(entry["subagent_type"], "general-purpose")

    def test_dispatch_skips_complete_subagents(self):
        with isolated_cache() as cache_dir:
            items = cache_dir / "items.json"
            items.write_text(json.dumps([
                {"canonical_id": f"p{i}", "title": f"P{i}",
                 "year": 2020} for i in range(10)
            ]))
            rc, out, _ = self._cli(
                "init", "--query", "test", "--items", str(items),
                "--type", "triage",
            )
            run_id = json.loads(out)["run_id"]
            self._cli("gate1", "--run-id", run_id,
                       "--verdict", "approve")

            # Simulate one sub-agent complete
            from lib.cache import cache_root
            plan_path = (
                cache_root() / "runs" / f"run-{run_id}" / "plan.json"
            )
            plan = json.loads(plan_path.read_text())
            ws = Path(plan["sub_specs"][0]["filesystem_workspace"])
            (ws / "result.json").write_text(json.dumps({"ok": True}))

            rc, out, err = self._cli(
                "dispatch-manifest", "--run-id", run_id,
            )
            self.assertEqual(rc, 0, err)
            d = json.loads(out)
            self.assertEqual(d["n_already_complete"], 1)
            self.assertEqual(d["n_pending"], 9)

    def test_status_state_transitions(self):
        with isolated_cache() as cache_dir:
            items = cache_dir / "items.json"
            items.write_text(json.dumps([
                {"canonical_id": f"p{i}", "title": f"P{i}",
                 "year": 2020} for i in range(10)
            ]))
            rc, out, _ = self._cli(
                "init", "--query", "test", "--items", str(items),
                "--type", "triage",
            )
            run_id = json.loads(out)["run_id"]

            # Initial state — all INITIALIZED
            rc, out, _ = self._cli("status", "--run-id", run_id)
            d = json.loads(out)
            self.assertEqual(d["by_state"]["INITIALIZED"], 10)

            # Add finding to one workspace → IN_PROGRESS
            from lib.cache import cache_root
            plan_path = (
                cache_root() / "runs" / f"run-{run_id}" / "plan.json"
            )
            plan = json.loads(plan_path.read_text())
            ws = Path(plan["sub_specs"][0]["filesystem_workspace"])
            (ws / "findings" / "tmp.txt").write_text("partial")

            rc, out, _ = self._cli("status", "--run-id", run_id)
            d = json.loads(out)
            self.assertEqual(d["by_state"]["IN_PROGRESS"], 1)
            self.assertEqual(d["by_state"]["INITIALIZED"], 9)

            # Add result.json → COMPLETE
            (ws / "result.json").write_text(json.dumps({"ok": True}))
            rc, out, _ = self._cli("status", "--run-id", run_id)
            d = json.loads(out)
            self.assertEqual(d["by_state"]["COMPLETE"], 1)
            self.assertEqual(d["by_state"]["IN_PROGRESS"], 0)

            # Malformed result.json → ERROR
            ws2 = Path(plan["sub_specs"][1]["filesystem_workspace"])
            (ws2 / "result.json").write_text("not valid json {{{")
            rc, out, _ = self._cli("status", "--run-id", run_id)
            d = json.loads(out)
            self.assertEqual(d["by_state"]["ERROR"], 1)

    def test_gate1_reject_marks_aborted(self):
        with isolated_cache() as cache_dir:
            items = cache_dir / "items.json"
            items.write_text(json.dumps([
                {"canonical_id": f"p{i}", "title": f"P{i}",
                 "year": 2020} for i in range(10)
            ]))
            rc, out, _ = self._cli(
                "init", "--query", "test", "--items", str(items),
                "--type", "triage",
            )
            run_id = json.loads(out)["run_id"]
            rc, out, err = self._cli(
                "gate1", "--run-id", run_id, "--verdict", "reject",
                "--user-input", "scope wrong",
            )
            self.assertEqual(rc, 0, err)
            d = json.loads(out)
            self.assertEqual(d["verdict"], "reject")
            self.assertIn("aborted", d["next_step"].lower())

            # Dispatch still refused
            rc, out, err = self._cli(
                "dispatch-manifest", "--run-id", run_id,
            )
            self.assertTrue(rc != 0)


class Gate23ObserveTests(TestCase):
    """v0.53.3 — gate2 (preview/adjust/abort), gate3 (flag re-runs), observe."""

    def _cli(self, *args: str) -> tuple[int, str, str]:
        import subprocess
        cli = (_ROOT / ".claude/skills/wide-research/scripts/wide.py")
        r = subprocess.run(
            [sys.executable, str(cli), *args],
            capture_output=True, text=True,
        )
        return r.returncode, r.stdout, r.stderr

    def _bootstrap(self, cache_dir: Path, n: int = 10) -> tuple[str, dict]:
        items = cache_dir / "items.json"
        items.write_text(json.dumps([
            {"canonical_id": f"p{i}", "title": f"P{i}", "year": 2020}
            for i in range(n)
        ]))
        rc, out, err = self._cli(
            "init", "--query", "test", "--items", str(items),
            "--type", "triage",
        )
        self.assertEqual(rc, 0, err)
        run_id = json.loads(out)["run_id"]
        self._cli("gate1", "--run-id", run_id, "--verdict", "approve")
        from lib.cache import cache_root
        plan_path = cache_root() / "runs" / f"run-{run_id}" / "plan.json"
        plan = json.loads(plan_path.read_text())
        return run_id, plan

    def _mark_complete(self, plan: dict, idx: int, payload: dict) -> Path:
        ws = Path(plan["sub_specs"][idx]["filesystem_workspace"])
        (ws / "result.json").write_text(json.dumps(payload))
        return ws

    def test_gate2_preview_returns_completed_only(self):
        with isolated_cache() as cache_dir:
            run_id, plan = self._bootstrap(cache_dir)
            self._mark_complete(plan, 0, {"score": 0.8})
            self._mark_complete(plan, 1, {"score": 0.4})
            rc, out, err = self._cli(
                "gate2", "--run-id", run_id, "--verdict", "preview",
            )
            self.assertEqual(rc, 0, err)
            d = json.loads(out)
            self.assertEqual(d["n_complete"], 2)
            self.assertEqual(d["n_total"], 10)
            self.assertEqual(len(d["preview_results"]), 2)

    def test_gate2_adjust_marks_skipped(self):
        with isolated_cache() as cache_dir:
            run_id, plan = self._bootstrap(cache_dir)
            self._mark_complete(plan, 0, {"score": 0.8})
            rc, out, err = self._cli(
                "gate2", "--run-id", run_id,
                "--verdict", "adjust_remaining",
            )
            self.assertEqual(rc, 0, err)
            d = json.loads(out)
            # 9 remaining flagged skipped
            self.assertEqual(d["n_skipped"], 9)
            from lib.cache import cache_root
            plan_path = cache_root() / "runs" / f"run-{run_id}" / "plan.json"
            persisted = json.loads(plan_path.read_text())
            self.assertTrue(persisted.get("adjust_remaining_at_gate2"))
            self.assertEqual(len(persisted["skipped_sub_agent_ids"]), 9)

    def test_gate2_abort_sets_aborted(self):
        with isolated_cache() as cache_dir:
            run_id, _ = self._bootstrap(cache_dir)
            rc, out, err = self._cli(
                "gate2", "--run-id", run_id, "--verdict", "abort",
            )
            self.assertEqual(rc, 0, err)
            from lib.cache import cache_root
            plan_path = cache_root() / "runs" / f"run-{run_id}" / "plan.json"
            self.assertTrue(json.loads(plan_path.read_text())["aborted"])

    def test_gate3_list_results(self):
        with isolated_cache() as cache_dir:
            run_id, plan = self._bootstrap(cache_dir)
            self._mark_complete(plan, 0, {"score": 0.8})
            rc, out, err = self._cli(
                "gate3", "--run-id", run_id, "--list-results",
            )
            self.assertEqual(rc, 0, err)
            d = json.loads(out)
            self.assertEqual(len(d["results"]), 10)

    def test_gate3_flag_archives_and_records(self):
        with isolated_cache() as cache_dir:
            run_id, plan = self._bootstrap(cache_dir)
            ws0 = self._mark_complete(plan, 0, {"score": 0.1})
            sub_id_0 = plan["sub_specs"][0]["sub_agent_id"]
            rc, out, err = self._cli(
                "gate3", "--run-id", run_id,
                "--flag-ids", sub_id_0,
                "--guidance", "look harder at venue",
            )
            self.assertEqual(rc, 0, err)
            d = json.loads(out)
            self.assertEqual(d["flagged_count"], 1)
            self.assertEqual(d["results_archived"], 1)
            self.assertFalse((ws0 / "result.json").exists())
            self.assertTrue((ws0 / "result.previous.json").exists())
            from lib.cache import cache_root
            plan_path = cache_root() / "runs" / f"run-{run_id}" / "plan.json"
            persisted = json.loads(plan_path.read_text())
            flags = persisted["gate3_rerun_flags"]
            self.assertEqual(flags[0]["sub_agent_id"], sub_id_0)
            self.assertEqual(flags[0]["rerun_guidance"], "look harder at venue")

    def test_gate3_unknown_id_rejected(self):
        with isolated_cache() as cache_dir:
            run_id, _ = self._bootstrap(cache_dir)
            rc, out, err = self._cli(
                "gate3", "--run-id", run_id, "--flag-ids", "does-not-exist",
            )
            self.assertTrue(rc != 0)
            self.assertIn("unknown sub_agent_id", err)

    def test_gate3_requires_flag_ids_or_list(self):
        with isolated_cache() as cache_dir:
            run_id, _ = self._bootstrap(cache_dir)
            rc, out, err = self._cli("gate3", "--run-id", run_id)
            self.assertTrue(rc != 0)

    def test_observe_no_telemetry_returns_zeros(self):
        with isolated_cache() as cache_dir:
            run_id, _ = self._bootstrap(cache_dir)
            rc, out, err = self._cli("observe", "--run-id", run_id)
            self.assertEqual(rc, 0, err)
            d = json.loads(out)
            self.assertEqual(d["totals"]["n_with_telemetry"], 0)
            self.assertEqual(d["totals"]["input_tokens"], 0)
            self.assertEqual(d["actual_cost"], 0.0)

    def test_observe_aggregates_telemetry(self):
        with isolated_cache() as cache_dir:
            run_id, plan = self._bootstrap(cache_dir)
            for i in range(3):
                ws = Path(plan["sub_specs"][i]["filesystem_workspace"])
                (ws / "telemetry.json").write_text(json.dumps({
                    "input_tokens": 1000, "output_tokens": 200,
                    "n_tool_calls": 4, "duration_ms": 5000,
                    "errors": [],
                }))
            rc, out, err = self._cli("observe", "--run-id", run_id)
            self.assertEqual(rc, 0, err)
            d = json.loads(out)
            self.assertEqual(d["totals"]["n_with_telemetry"], 3)
            self.assertEqual(d["totals"]["input_tokens"], 3000)
            self.assertEqual(d["totals"]["output_tokens"], 600)
            self.assertEqual(d["totals"]["n_tool_calls"], 12)
            self.assertTrue(d["actual_cost"] > 0)

    def test_observe_overrun_alert(self):
        with isolated_cache() as cache_dir:
            run_id, plan = self._bootstrap(cache_dir)
            # Massive token usage to force overrun >20%
            for i in range(len(plan["sub_specs"])):
                ws = Path(plan["sub_specs"][i]["filesystem_workspace"])
                (ws / "telemetry.json").write_text(json.dumps({
                    "input_tokens": 1_000_000, "output_tokens": 200_000,
                    "n_tool_calls": 0, "duration_ms": 0, "errors": [],
                }))
            rc, out, err = self._cli("observe", "--run-id", run_id)
            self.assertEqual(rc, 0, err)
            d = json.loads(out)
            self.assertEqual(d["alert"], "OVERRUN")
            self.assertTrue(d["overrun_pct"] > 20.0)


class SynthesisTests(TestCase):
    """v0.53.4 — per-type synthesizer roll-ups."""

    def test_triage_synthesis_buckets_and_shortlist(self):
        from lib.wide_synthesis import synthesize
        results = [
            {"sub_agent_id": "s1", "status": "complete",
             "result": {"canonical_id": "p1", "title": "A",
                        "relevance_score": 0.9, "recommend": "include"}},
            {"sub_agent_id": "s2", "status": "complete",
             "result": {"canonical_id": "p2", "title": "B",
                        "relevance_score": 0.5, "recommend": "review"}},
            {"sub_agent_id": "s3", "status": "complete",
             "result": {"canonical_id": "p3", "title": "C",
                        "relevance_score": 0.1, "recommend": "exclude"}},
            {"sub_agent_id": "s4", "status": "missing"},
        ]
        s = synthesize("triage", results, user_query="Q")
        self.assertEqual(s["n_total"], 4)
        self.assertEqual(s["n_complete"], 3)
        self.assertEqual(s["n_missing"], 1)
        self.assertEqual(s["by_recommend"]["include"], 1)
        self.assertEqual(s["by_recommend"]["review"], 1)
        self.assertEqual(s["by_recommend"]["exclude"], 1)
        # Shortlist sorted desc by relevance_score
        self.assertEqual(s["top_shortlist"][0]["canonical_id"], "p1")
        self.assertEqual(s["top_shortlist"][-1]["canonical_id"], "p3")

    def test_read_synthesis_digests(self):
        from lib.wide_synthesis import synthesize
        results = [
            {"sub_agent_id": "s1", "status": "complete",
             "result": {"canonical_id": "p1", "method": "transformer",
                        "dataset": "ImageNet", "results": "98%",
                        "limitations": "compute", "claims": ["a", "b"]}},
        ]
        s = synthesize("read", results)
        self.assertEqual(len(s["digests"]), 1)
        self.assertEqual(s["digests"][0]["method"], "transformer")
        self.assertEqual(s["digests"][0]["claims"], ["a", "b"])

    def test_rank_synthesis_leaderboard(self):
        from lib.wide_synthesis import synthesize
        results = [
            {"sub_agent_id": "s1", "status": "complete",
             "result": {"item_a": "X", "item_b": "Y", "winner": "X"}},
            {"sub_agent_id": "s2", "status": "complete",
             "result": {"item_a": "Y", "item_b": "Z", "winner": "Z"}},
            {"sub_agent_id": "s3", "status": "complete",
             "result": {"item_a": "X", "item_b": "Z", "winner": "X"}},
        ]
        s = synthesize("rank", results)
        # X wins 2/2 → top
        top = s["leaderboard"][0]
        self.assertEqual(top["item"], "X")
        self.assertEqual(top["wins"], 2)
        self.assertEqual(top["appearances"], 2)
        self.assertEqual(top["win_rate"], 1.0)

    def test_compare_synthesis_matrix(self):
        from lib.wide_synthesis import synthesize
        results = [
            {"sub_agent_id": "s1", "status": "complete",
             "result": {"founded": 2018, "headcount": 50, "tier": "A"}},
            {"sub_agent_id": "s2", "status": "complete",
             "result": {"founded": 2020, "headcount": 12, "tier": "B"}},
        ]
        s = synthesize("compare", results)
        self.assertEqual(set(s["schema"]),
                         {"founded", "headcount", "tier"})
        self.assertEqual(len(s["matrix"]), 2)

    def test_survey_synthesis_sorted_by_h(self):
        from lib.wide_synthesis import synthesize
        results = [
            {"sub_agent_id": "s1", "status": "complete",
             "result": {"author": "Alice", "h_index": 30,
                        "recent_venues": [], "top_papers": []}},
            {"sub_agent_id": "s2", "status": "complete",
             "result": {"author": "Bob", "h_index": 75,
                        "recent_venues": [], "top_papers": []}},
        ]
        s = synthesize("survey", results)
        self.assertEqual(s["authors"][0]["author"], "Bob")
        self.assertEqual(s["authors"][1]["author"], "Alice")

    def test_screen_synthesis_tally_and_histogram(self):
        from lib.wide_synthesis import synthesize
        results = [
            {"sub_agent_id": "s1", "status": "complete",
             "result": {"canonical_id": "p1", "include": True,
                        "criteria_failed": []}},
            {"sub_agent_id": "s2", "status": "complete",
             "result": {"canonical_id": "p2", "include": False,
                        "criteria_failed": ["language", "year"]}},
            {"sub_agent_id": "s3", "status": "complete",
             "result": {"canonical_id": "p3", "include": False,
                        "criteria_failed": ["year"]}},
        ]
        s = synthesize("screen", results)
        self.assertEqual(s["n_include"], 1)
        self.assertEqual(s["n_exclude"], 2)
        self.assertEqual(s["criteria_failed_histogram"]["year"], 2)
        self.assertEqual(s["criteria_failed_histogram"]["language"], 1)

    def test_render_brief_triage(self):
        from lib.wide_synthesis import render_brief, synthesize
        results = [
            {"sub_agent_id": "s1", "status": "complete",
             "result": {"canonical_id": "p1", "title": "A",
                        "relevance_score": 0.9, "recommend": "include"}},
        ]
        s = synthesize("triage", results)
        md = render_brief(s)
        self.assertIn("Wide Research synthesis — triage", md)
        self.assertIn("Top shortlist", md)


class SynthesizeCLITests(TestCase):
    """v0.53.4 — CLI synthesize + --compare-schema."""

    def _cli(self, *args: str) -> tuple[int, str, str]:
        import subprocess
        cli = (_ROOT / ".claude/skills/wide-research/scripts/wide.py")
        r = subprocess.run(
            [sys.executable, str(cli), *args],
            capture_output=True, text=True,
        )
        return r.returncode, r.stdout, r.stderr

    def test_synthesize_writes_outputs(self):
        with isolated_cache() as cache_dir:
            items_path = cache_dir / "items.json"
            items_path.write_text(json.dumps([
                {"canonical_id": f"p{i}", "title": f"P{i}",
                 "year": 2020} for i in range(10)
            ]))
            rc, out, _ = self._cli(
                "init", "--query", "Q", "--items", str(items_path),
                "--type", "triage",
            )
            run_id = json.loads(out)["run_id"]
            self._cli("gate1", "--run-id", run_id, "--verdict", "approve")

            from lib.cache import cache_root
            plan = json.loads(
                (cache_root() / "runs" / f"run-{run_id}" / "plan.json")
                .read_text()
            )
            for i, spec in enumerate(plan["sub_specs"]):
                ws = Path(spec["filesystem_workspace"])
                (ws / "result.json").write_text(json.dumps({
                    "canonical_id": f"p{i}",
                    "title": f"P{i}",
                    "relevance_score": 1.0 - 0.1 * i,
                    "recommend": "include" if i < 3 else "exclude",
                }))

            rc, out, err = self._cli(
                "synthesize", "--run-id", run_id, "--write-outputs",
            )
            self.assertEqual(rc, 0, err)
            d = json.loads(out)
            self.assertEqual(d["n_complete"], 10)
            self.assertTrue(Path(d["synthesis_json_path"]).exists())
            self.assertTrue(Path(d["synthesis_md_path"]).exists())
            synth = json.loads(
                Path(d["synthesis_json_path"]).read_text()
            )
            self.assertEqual(synth["by_recommend"]["include"], 3)
            self.assertEqual(synth["by_recommend"]["exclude"], 7)

    def test_compare_schema_override(self):
        with isolated_cache() as cache_dir:
            items_path = cache_dir / "items.json"
            items_path.write_text(json.dumps([
                {"name": f"co{i}"} for i in range(10)
            ]))
            rc, out, err = self._cli(
                "init", "--query", "company features",
                "--items", str(items_path),
                "--type", "compare",
                "--compare-schema", "founded,headcount,tier",
            )
            self.assertEqual(rc, 0, err)
            run_id = json.loads(out)["run_id"]

            from lib.cache import cache_root
            plan = json.loads(
                (cache_root() / "runs" / f"run-{run_id}" / "plan.json")
                .read_text()
            )
            for spec in plan["sub_specs"]:
                self.assertEqual(
                    spec["output_schema"]["fields"],
                    ["founded", "headcount", "tier"],
                )

    def test_compare_schema_rejected_for_non_compare_type(self):
        with isolated_cache() as cache_dir:
            items_path = cache_dir / "items.json"
            items_path.write_text(json.dumps([
                {"canonical_id": f"p{i}", "title": f"P{i}",
                 "year": 2020} for i in range(10)
            ]))
            rc, out, err = self._cli(
                "init", "--query", "Q", "--items", str(items_path),
                "--type", "triage",
                "--compare-schema", "a,b",
            )
            self.assertTrue(rc != 0)
            self.assertIn("compare", err.lower())


class WideToDeepHandoffTests(TestCase):
    """v0.53.5 — Wide → Deep handoff via db.py init --seed-from-wide."""

    def _wide_cli(self, *args: str) -> tuple[int, str, str]:
        import subprocess
        cli = (_ROOT / ".claude/skills/wide-research/scripts/wide.py")
        r = subprocess.run(
            [sys.executable, str(cli), *args],
            capture_output=True, text=True,
        )
        return r.returncode, r.stdout, r.stderr

    def _deep_cli(self, *args: str) -> tuple[int, str, str]:
        import subprocess
        cli = (_ROOT / ".claude/skills/deep-research/scripts/db.py")
        r = subprocess.run(
            [sys.executable, str(cli), *args],
            capture_output=True, text=True,
        )
        return r.returncode, r.stdout, r.stderr

    def _build_wide_synthesis(self, run_id: str, mode: str = "triage"):
        """Run a Wide triage end-to-end so synthesis.json exists."""
        from lib.cache import cache_root
        plan = json.loads(
            (cache_root() / "runs" / f"run-{run_id}" / "plan.json")
            .read_text()
        )
        for i, spec in enumerate(plan["sub_specs"]):
            ws = Path(spec["filesystem_workspace"])
            (ws / "result.json").write_text(json.dumps({
                "canonical_id": f"p{i:03d}",
                "title": f"P{i}",
                "year": 2020,
                "relevance_score": 1.0 - 0.05 * i,
                "recommend": "include" if i < 5 else "exclude",
            }))
        rc, out, err = self._wide_cli(
            "synthesize", "--run-id", run_id, "--write-outputs",
        )
        self.assertEqual(rc, 0, err)

    def test_seed_from_wide_seeds_papers_in_run(self):
        with isolated_cache() as cache_dir:
            items_path = cache_dir / "items.json"
            items_path.write_text(json.dumps([
                {"canonical_id": f"p{i:03d}", "title": f"P{i}",
                 "year": 2020} for i in range(10)
            ]))
            rc, out, _ = self._wide_cli(
                "init", "--query", "Q", "--items", str(items_path),
                "--type", "triage",
            )
            wide_id = json.loads(out)["run_id"]
            self._wide_cli("gate1", "--run-id", wide_id,
                           "--verdict", "approve")
            self._build_wide_synthesis(wide_id)

            rc, out, err = self._deep_cli(
                "init", "--question", "Refined Q",
                "--seed-from-wide", wide_id,
                "--seed-mode", "abstract",
                "--seed-top-k", "3",
            )
            self.assertEqual(rc, 0, err)
            deep_id = out.strip()
            self.assertTrue(deep_id)

            from lib.cache import cache_root
            import sqlite3
            db = cache_root() / "runs" / f"run-{deep_id}.db"
            con = sqlite3.connect(db)
            row = con.execute(
                "SELECT parent_run_id, seed_mode FROM runs WHERE run_id=?",
                (deep_id,),
            ).fetchone()
            self.assertEqual(row[0], wide_id)
            self.assertEqual(row[1], "abstract")
            seeded = con.execute(
                "SELECT canonical_id, role, added_in_phase "
                "FROM papers_in_run WHERE run_id=?",
                (deep_id,),
            ).fetchall()
            con.close()
            # Top 3 by relevance — p000, p001, p002
            self.assertEqual(len(seeded), 3)
            cids = sorted(r[0] for r in seeded)
            self.assertEqual(cids, ["p000", "p001", "p002"])
            for _, role, phase in seeded:
                self.assertEqual(role, "seed")
                self.assertEqual(phase, "seed-from-wide")

    def test_seed_mode_defaults_to_abstract(self):
        with isolated_cache() as cache_dir:
            items_path = cache_dir / "items.json"
            items_path.write_text(json.dumps([
                {"canonical_id": f"p{i:03d}", "title": f"P{i}",
                 "year": 2020} for i in range(10)
            ]))
            rc, out, _ = self._wide_cli(
                "init", "--query", "Q", "--items", str(items_path),
                "--type", "triage",
            )
            wide_id = json.loads(out)["run_id"]
            self._wide_cli("gate1", "--run-id", wide_id,
                           "--verdict", "approve")
            self._build_wide_synthesis(wide_id)

            rc, out, err = self._deep_cli(
                "init", "--question", "Q",
                "--seed-from-wide", wide_id,
            )
            self.assertEqual(rc, 0, err)
            deep_id = out.strip()
            from lib.cache import cache_root
            import sqlite3
            db = cache_root() / "runs" / f"run-{deep_id}.db"
            con = sqlite3.connect(db)
            row = con.execute(
                "SELECT seed_mode FROM runs WHERE run_id=?", (deep_id,),
            ).fetchone()
            con.close()
            self.assertEqual(row[0], "abstract")

    def test_seed_missing_synthesis_rejected(self):
        with isolated_cache() as cache_dir:
            rc, out, err = self._deep_cli(
                "init", "--question", "Q",
                "--seed-from-wide", "deadbeef",
                "--seed-mode", "abstract",
            )
            self.assertTrue(rc != 0)
            self.assertIn("no seed papers", err)

    def test_seed_invalid_mode_rejected(self):
        with isolated_cache() as cache_dir:
            rc, out, err = self._deep_cli(
                "init", "--question", "Q",
                "--seed-from-wide", "deadbeef",
                "--seed-mode", "garbage",
            )
            self.assertTrue(rc != 0)

    def test_init_without_seed_works(self):
        with isolated_cache():
            rc, out, err = self._deep_cli(
                "init", "--question", "vanilla deep",
            )
            self.assertEqual(rc, 0, err)
            deep_id = out.strip()
            from lib.cache import cache_root
            import sqlite3
            db = cache_root() / "runs" / f"run-{deep_id}.db"
            con = sqlite3.connect(db)
            row = con.execute(
                "SELECT parent_run_id, seed_mode FROM runs WHERE run_id=?",
                (deep_id,),
            ).fetchone()
            con.close()
            self.assertIsNone(row[0])
            self.assertIsNone(row[1])


if __name__ == "__main__":
    sys.exit(run_tests(
        TaskSpecTests, DecomposeTests, CostEstimateTests, WorkspaceTests,
        CollectResultsTests, TaskTypeDefaultsTests, CLITests,
        Gate23ObserveTests, SynthesisTests, SynthesizeCLITests,
        WideToDeepHandoffTests,
    ))
