"""Tiny test harness — no pytest dependency.

Usage:
    from tests.harness import TestCase, run_tests

    class X(TestCase):
        def test_foo(self):
            self.assertEqual(1, 1)

    if __name__ == "__main__":
        run_tests()
"""

from __future__ import annotations

import os
import shutil
import tempfile
import traceback
from pathlib import Path


class TestCase:
    def setUp(self) -> None: ...
    def tearDown(self) -> None: ...

    def assertEqual(self, a, b, msg: str = ""):
        if a != b:
            raise AssertionError(f"{msg}: {a!r} != {b!r}")

    def assertIn(self, needle, haystack, msg: str = ""):
        if needle not in haystack:
            raise AssertionError(f"{msg}: {needle!r} not in {haystack!r}")

    def assertNotIn(self, needle, haystack, msg: str = ""):
        if needle in haystack:
            raise AssertionError(f"{msg}: {needle!r} unexpectedly in {haystack!r}")

    def assertTrue(self, x, msg: str = ""):
        if not x:
            raise AssertionError(f"{msg}: {x!r} is not truthy")

    def assertFalse(self, x, msg: str = ""):
        if x:
            raise AssertionError(f"{msg}: {x!r} is truthy")

    def assertRaises(self, exc_type):
        class _Ctx:
            def __enter__(self): return self
            def __exit__(self, t, v, tb):
                if t is None:
                    raise AssertionError(f"expected {exc_type.__name__}, nothing raised")
                return issubclass(t, exc_type)
        return _Ctx()


def run_tests(*classes) -> int:
    """Run all test_* methods of the given TestCase classes. Returns failure count."""
    passed = 0
    failed = 0
    for cls in classes:
        for name in sorted(dir(cls)):
            if not name.startswith("test_"):
                continue
            instance = cls()
            label = f"{cls.__name__}.{name}"
            try:
                instance.setUp()
                getattr(instance, name)()
                instance.tearDown()
                print(f"[PASS] {label}")
                passed += 1
            except Exception as e:
                print(f"[FAIL] {label}")
                print(f"       {type(e).__name__}: {e}")
                tb = traceback.format_exc().splitlines()
                for line in tb[-8:]:
                    print(f"       {line}")
                failed += 1
    print("-" * 60)
    print(f"{passed} passed, {failed} failed")
    return failed


class _CacheScope:
    """Context manager that sets COSCIENTIST_CACHE_DIR to a temp dir and cleans up."""
    def __init__(self):
        self.prev: str | None = None
        self.path: Path | None = None

    def __enter__(self) -> Path:
        self.prev = os.environ.get("COSCIENTIST_CACHE_DIR")
        self.path = Path(tempfile.mkdtemp(prefix="coscientist-test-"))
        os.environ["COSCIENTIST_CACHE_DIR"] = str(self.path)
        return self.path

    def __exit__(self, *exc):
        if self.path and self.path.exists():
            shutil.rmtree(self.path, ignore_errors=True)
        if self.prev is None:
            os.environ.pop("COSCIENTIST_CACHE_DIR", None)
        else:
            os.environ["COSCIENTIST_CACHE_DIR"] = self.prev


def isolated_cache() -> _CacheScope:
    return _CacheScope()
