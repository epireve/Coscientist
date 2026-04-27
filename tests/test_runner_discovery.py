"""Tests for v0.65b auto-discovery in tests/run_all.py.

Asserts the discovery walk finds at least N test classes and never
loses classes silently as the suite grows. The ratchet number is
updated alongside intentional class additions.
"""
from __future__ import annotations

from tests.harness import TestCase, run_tests
from tests.run_all import _discover_test_classes


# Ratchet: discovery must surface at least this many classes. Bump
# when adding a new test class is intentional. Drift below this
# means a class went missing.
_MIN_DISCOVERED_CLASSES = 360


class DiscoveryTests(TestCase):
    def test_discovery_returns_list(self):
        classes = _discover_test_classes()
        self.assertIsInstance(classes, list)
        self.assertGreater(len(classes), 0)

    def test_discovery_meets_ratchet(self):
        classes = _discover_test_classes()
        self.assertGreaterEqual(
            len(classes), _MIN_DISCOVERED_CLASSES,
            f"test class count regressed: {len(classes)} < "
            f"{_MIN_DISCOVERED_CLASSES} — likely orphaned class",
        )

    def test_no_duplicate_classes(self):
        classes = _discover_test_classes()
        self.assertEqual(len(classes), len(set(classes)),
                         "duplicate test classes in discovery")

    def test_priority_modules_run_first(self):
        classes = _discover_test_classes()
        # First N classes should all come from priority modules.
        priority = {
            "tests.test_agents", "tests.test_gates",
            "tests.test_integration", "tests.test_db_state_machine",
        }
        head = classes[:6]  # at least a few priority classes up front
        head_modules = {c.__module__ for c in head}
        self.assertTrue(head_modules & priority,
                        f"expected priority modules in head, got "
                        f"{head_modules}")

    def test_all_classes_subclass_TestCase(self):
        classes = _discover_test_classes()
        for c in classes:
            self.assertTrue(issubclass(c, TestCase),
                            f"{c.__name__} is not a TestCase subclass")

    def test_all_classes_end_in_Tests(self):
        classes = _discover_test_classes()
        for c in classes:
            self.assertTrue(c.__name__.endswith("Tests"),
                            f"{c.__name__} does not end in 'Tests'")


if __name__ == "__main__":
    raise SystemExit(run_tests(DiscoveryTests))
