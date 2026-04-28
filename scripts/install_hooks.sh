#!/bin/sh
# Install Coscientist git hooks (v0.128).
#
# Symlinks .git/hooks/* to scripts/<hook-name>. Idempotent.
# Re-run any time scripts/<hook> changes — symlink re-points
# automatically next commit.
#
# Why symlink: hooks live in repo, get version-controlled,
# everyone gets same behavior. .git/hooks/ is local-only so
# pre-commit.sample stays put.

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

HOOKS_DIR=".git/hooks"
SOURCE_DIR="scripts"

for hook in pre-commit; do
    src="$SOURCE_DIR/$hook"
    dst="$HOOKS_DIR/$hook"
    if [ ! -f "$src" ]; then
        echo "[install_hooks] skip $hook (no source at $src)"
        continue
    fi
    chmod +x "$src"
    if [ -L "$dst" ] || [ -e "$dst" ]; then
        rm "$dst"
    fi
    ln -s "../../$src" "$dst"
    echo "[install_hooks] $hook → $src"
done

echo "[install_hooks] done. To bypass a hook: git commit --no-verify"
