#!/usr/bin/env bash
# Build coscientist-cowork.zip for Cowork upload.
# Resolves symlinks (skills/, agents/, commands/) into real dirs in the zip.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
OUT="$REPO_ROOT/coscientist-cowork.zip"
STAGE="$(mktemp -d)/coscientist"

mkdir -p "$STAGE"

# Copy plugin manifest + mcp.json + readme
cp -R "$HERE/.claude-plugin" "$STAGE/"
cp "$HERE/.mcp.json" "$STAGE/"
cp "$HERE/README.md" "$STAGE/"

# Materialise symlinked tree as real files
cp -RL "$HERE/skills" "$STAGE/skills"
cp -RL "$HERE/agents" "$STAGE/agents"
cp -RL "$HERE/commands" "$STAGE/commands"

# Bundle lib/ — required by skill scripts via `from lib.X`
cp -R "$REPO_ROOT/lib" "$STAGE/lib"

# Strip caches + DS_Store
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$STAGE" -name '.DS_Store' -delete
find "$STAGE" -name '*.pyc' -delete

# Zip
rm -f "$OUT"
(cd "$(dirname "$STAGE")" && zip -rq "$OUT" "$(basename "$STAGE")")

echo "Built $OUT"
echo "Size: $(du -h "$OUT" | cut -f1)"
echo ""
echo "Install in Cowork: Customize -> Browse plugins -> Upload -> select $OUT"
