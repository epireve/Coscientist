#!/usr/bin/env python3
"""Wrapper around lib.health for skill-script invocation.

Forwards args to lib.health.main; identical behavior. Exists so
the skill has a script path that orchestrators can call directly
without importing lib.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))


if __name__ == "__main__":
    from lib.health import main
    raise SystemExit(main())
