"""Test shim — injects lightweight stubs for deps that may not be installed.

Keeps smoke tests runnable without `uv sync`. Each test module imports
`_shim` as its first import.
"""

from __future__ import annotations

import re
import sys
import types


def _stub_slugify() -> None:
    if "slugify" in sys.modules:
        return
    try:
        import slugify  # noqa: F401
        return
    except ImportError:
        pass
    mod = types.ModuleType("slugify")
    mod.slugify = lambda s: re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    sys.modules["slugify"] = mod


_stub_slugify()

# Make the repo root importable (`from lib...`) regardless of CWD
from pathlib import Path  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
