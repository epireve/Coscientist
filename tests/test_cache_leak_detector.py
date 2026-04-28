"""v0.65e — cache-leak detector.

Snapshots the real ~/.cache/coscientist/ tree at module import time
(before any test in the suite runs) and asserts at test-run time
that no test polluted the real cache.

When tests need to write to a cache, they MUST use
`tests.harness.isolated_cache()` which sets `COSCIENTIST_CACHE_DIR`
to a temp dir. Any test that bypasses that and writes to the
default `~/.cache/coscientist/` path will be caught here.

Behavior:
  - If COSCIENTIST_CACHE_DIR is already set when this module imports,
    skip the snapshot (we're in a sandboxed run).
  - If the real cache dir doesn't exist (clean machine, CI), skip.
  - Otherwise, record the set of files + their mtimes; the test
    asserts the set is unchanged.
"""
from __future__ import annotations

import os
from pathlib import Path

from tests.harness import TestCase, run_tests


_REAL_CACHE = Path.home() / ".cache" / "coscientist"
_SANDBOXED_AT_IMPORT = "COSCIENTIST_CACHE_DIR" in os.environ


def _snapshot(root: Path) -> dict[str, float]:
    """Returns {relative_path: mtime} for every file under root."""
    out: dict[str, float] = {}
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if p.is_file():
            try:
                out[str(p.relative_to(root))] = p.stat().st_mtime
            except OSError:
                continue
    return out


# Snapshot at import time, before any other test runs.
_BASELINE: dict[str, float] | None
if _SANDBOXED_AT_IMPORT or not _REAL_CACHE.exists():
    _BASELINE = None
else:
    _BASELINE = _snapshot(_REAL_CACHE)


class CacheLeakDetectorTests(TestCase):
    def test_no_pollution_to_real_cache(self):
        if _BASELINE is None:
            # Either sandboxed or no real cache exists — nothing to check.
            return
        current = _snapshot(_REAL_CACHE)
        # New files that appeared mid-suite.
        new_paths = set(current) - set(_BASELINE)
        # Existing files whose mtime changed.
        modified = {
            p for p in (set(current) & set(_BASELINE))
            if current[p] != _BASELINE[p]
        }
        # Ignore audit.log + sandbox_audit.log: these may legitimately
        # be appended to by intentional integration runs outside tests.
        # If the user wants strict mode they can tighten this list.
        ignore_prefixes = ("audit.log", "sandbox_audit.log")
        new_paths = {
            p for p in new_paths
            if not any(p.startswith(prefix) for prefix in ignore_prefixes)
        }
        modified = {
            p for p in modified
            if not any(p.startswith(prefix) for prefix in ignore_prefixes)
        }
        msg_parts = []
        if new_paths:
            msg_parts.append(
                f"new files in real cache (probably test pollution): "
                f"{sorted(new_paths)[:5]}"
            )
        if modified:
            msg_parts.append(
                f"modified files in real cache: {sorted(modified)[:5]}"
            )
        self.assertEqual(
            len(new_paths) + len(modified), 0,
            "; ".join(msg_parts) or "cache leak detected",
        )

    def test_baseline_captured_when_cache_exists(self):
        # Documents the contract: if real cache exists and we're not
        # already sandboxed, _BASELINE must be populated.
        if _SANDBOXED_AT_IMPORT or not _REAL_CACHE.exists():
            return
        self.assertIsNotNone(_BASELINE)


if __name__ == "__main__":
    raise SystemExit(run_tests(CacheLeakDetectorTests))
