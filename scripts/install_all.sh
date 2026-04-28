#!/usr/bin/env bash
# v0.83 — one-shot Coscientist install via Claude Code's plugin marketplace.
#
# Usage:
#   ./scripts/install_all.sh
#
# What it does:
#   1. Adds the Coscientist marketplace.
#   2. Installs the deep-research plugin (skills + agents + slash command).
#   3. Installs each of the 3 MCP server plugins.
#   4. Optionally runs `claude mcp list` to confirm.
#
# Requires: `claude` CLI on PATH (Claude Code >= 2.0.0).
set -euo pipefail

PLUGINS=(
    coscientist-deep-research
    coscientist-retraction-mcp
    coscientist-manuscript-mcp
    coscientist-graph-query-mcp
)

if ! command -v claude >/dev/null 2>&1; then
    echo "[error] \`claude\` CLI not on PATH" >&2
    echo "        Install Claude Code first: https://claude.com/claude-code" >&2
    exit 1
fi

echo "==> Adding marketplace: epireve/coscientist"
claude plugin marketplace add epireve/coscientist

for plugin in "${PLUGINS[@]}"; do
    echo "==> Installing ${plugin}"
    claude plugin install "${plugin}@coscientist"
done

echo
echo "==> Installation complete."
echo
if command -v claude >/dev/null 2>&1; then
    echo "==> Verifying via \`claude mcp list\`:"
    claude mcp list || true
fi

echo
echo "Next steps:"
echo "  - See SKILLS.md for the 64 skills now available."
echo "  - See MCP_SERVERS.md for the 3 custom MCP servers + their tools."
echo "  - See EXTERNAL_MCPS.md for third-party MCPs you may also want."
