#!/usr/bin/env python3
"""Run every test module in tests/ and report totals.

v0.65b: auto-discovers test classes via `pkgutil`. Any class in
`tests/test_*.py` whose name ends in `Tests` and is a `TestCase`
subclass gets registered automatically — no manual import + tuple
edit per new class.

Priority classes (gate + integration) run first for fail-fast.
"""

from tests import _shim  # noqa: F401

import importlib
import inspect
import pkgutil
import sys
from pathlib import Path

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


if __name__ == "__main__":
    classes = _discover_test_classes()
    print(f"[discover] {len(classes)} test classes "
          f"from {len({c.__module__ for c in classes})} modules", flush=True)
    failures = run_tests(*classes)
    sys.exit(failures)
