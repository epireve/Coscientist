#!/usr/bin/env python3
"""Run every test module in tests/ and report totals.

v0.65b: auto-discovers test classes via `pkgutil`. Any class in
`tests/test_*.py` whose name ends in `Tests` and is a `TestCase`
subclass gets registered automatically — no manual import + tuple
edit per new class.

Priority classes (gate + integration) run first for fail-fast.
"""

import importlib
import inspect
import pkgutil
import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, run_tests

# Run these first — fast structural checks that should fail loudly
# before slower per-skill tests run.
_PRIORITY_MODULES = (
    "tests.test_agents",
    "tests.test_gates",
    "tests.test_integration",
    "tests.test_db_state_machine",
)

# Run these LAST — they observe side effects from the rest of the
# suite (e.g. cache-leak detector compares end-of-session state to
# import-time snapshot).
_LATE_MODULES = (
    "tests.test_cache_leak_detector",
)


def _discover_test_classes() -> list[type]:
    """Walk tests/ and return every TestCase subclass whose name ends in
    'Tests'. Priority modules are returned first; the rest follow in
    module-name sort order."""
    tests_dir = Path(__file__).resolve().parent
    discovered: dict[str, list[type]] = {}
    seen_classes: set[type] = set()

    for info in pkgutil.iter_modules([str(tests_dir)]):
        if not info.name.startswith("test_"):
            continue
        mod_name = f"tests.{info.name}"
        try:
            mod = importlib.import_module(mod_name)
        except Exception as e:
            print(f"[WARN] failed to import {mod_name}: {e}", file=sys.stderr)
            continue
        classes: list[type] = []
        for attr_name, attr in inspect.getmembers(mod, inspect.isclass):
            if not attr_name.endswith("Tests"):
                continue
            if not issubclass(attr, TestCase):
                continue
            # Only collect classes defined in this module (not re-imports).
            if attr.__module__ != mod_name:
                continue
            if attr in seen_classes:
                continue
            seen_classes.add(attr)
            classes.append(attr)
        if classes:
            # Sort within a module by class name for deterministic order.
            classes.sort(key=lambda c: c.__name__)
            discovered[mod_name] = classes

    # Priority first (in declared order), then everything else
    # sorted, then late modules at the tail.
    late_classes: list[type] = []
    for mod_name in _LATE_MODULES:
        if mod_name in discovered:
            late_classes.extend(discovered.pop(mod_name))
    ordered: list[type] = []
    for mod_name in _PRIORITY_MODULES:
        if mod_name in discovered:
            ordered.extend(discovered.pop(mod_name))
    for mod_name in sorted(discovered):
        ordered.extend(discovered[mod_name])
    ordered.extend(late_classes)
    return ordered


def _maybe_warn_pre_commit_hook():
    """v0.140 — nudge if pre-commit hook isn't installed.

    Non-blocking — prints warning, doesn't fail the suite.
    Skipped in CI (no .git/hooks expected).
    """
    try:
        from lib.hook_check import check
        r = check()
        if not r["ok"] and "not a git repo" not in (
            r.get("message") or ""
        ):
            print(
                f"\n⚠️  [pre-commit] {r['message']}\n"
                f"   action: {r['action']}\n",
                flush=True,
            )
    except Exception:
        pass  # nudge must not break the test runner


def _profile_classes(classes: list[type]) -> None:
    """v0.141 — time each test class, print top-20 slowest."""
    import time
    timings: list[tuple[float, str]] = []
    for cls in classes:
        instance = cls()
        method_names = [
            name for name in dir(instance)
            if name.startswith("test_")
        ]
        start = time.perf_counter()
        for name in method_names:
            try:
                getattr(instance, name)()
            except Exception:
                pass  # we're profiling, not gating
        elapsed = time.perf_counter() - start
        timings.append((
            elapsed, f"{cls.__module__}.{cls.__name__}",
        ))
    timings.sort(reverse=True)
    print("\n[profile] top 20 slowest test classes (s):", flush=True)
    for elapsed, name in timings[:20]:
        print(f"  {elapsed:6.2f}s  {name}", flush=True)
    total = sum(t for t, _ in timings)
    print(f"\n[profile] total: {total:.1f}s across "
          f"{len(timings)} classes\n", flush=True)


if __name__ == "__main__":
    _maybe_warn_pre_commit_hook()
    classes = _discover_test_classes()
    print(f"[discover] {len(classes)} test classes "
          f"from {len({c.__module__ for c in classes})} modules", flush=True)
    if "--profile" in sys.argv:
        _profile_classes(classes)
        sys.exit(0)
    failures = run_tests(*classes)
    sys.exit(failures)
