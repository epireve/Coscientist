#!/bin/sh
# scripts/test-like-ci.sh — emulate GitHub Actions tests.yml locally.
#
# Mirrors .github/workflows/tests.yml steps so failures surface
# before push. Catches gitignore / missing-file / pandoc-path /
# cache-state bugs that local-repo state can mask.
#
# Usage:
#   scripts/test-like-ci.sh             # run in current repo
#   scripts/test-like-ci.sh --fresh     # clone fresh into tmp dir
#                                       # (catches untracked-file bugs)
#
# Requires: uv, git. Optional: act (for full Docker emulation).

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"

if [ "$1" = "--fresh" ]; then
    TMPDIR=$(mktemp -d)
    echo "[ci-local] cloning fresh into $TMPDIR"
    git clone "$REPO_ROOT" "$TMPDIR/coscientist"
    cd "$TMPDIR/coscientist"
    trap 'rm -rf "$TMPDIR"' EXIT
else
    cd "$REPO_ROOT"
    echo "[ci-local] running in current repo"
fi

# Step 1: install deps (matches workflow)
echo "[ci-local] uv sync --extra dev --extra mcp"
uv sync --extra dev --extra mcp

# Step 2: stage .mcp.json from example (matches workflow)
if [ ! -f .mcp.json ] && [ -f .mcp.json.example ]; then
    echo "[ci-local] cp .mcp.json.example -> .mcp.json"
    cp .mcp.json.example .mcp.json
fi

# Step 3: full test suite (matches workflow)
echo "[ci-local] running test suite..."
COSCIENTIST_RUN_LIVE="" uv run python tests/run_all.py

# Step 4: lint (workflow has continue-on-error so don't fail here)
echo "[ci-local] lint..."
uv run ruff check lib/ tests/ .claude/skills/ || \
    echo "[ci-local] (lint failed — non-blocking, matches workflow)"

echo "[ci-local] DONE — same env as GitHub Actions tests.yml."
