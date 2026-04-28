#!/usr/bin/env bash
# v0.87 — restore a Coscientist cache backup.
#
# Reverse of scripts/backup_cache.sh. Extracts the archive into the
# parent of $COSCIENTIST_CACHE_DIR (default ~/.cache/).
#
# Refuses to overwrite an existing cache without --force.
#
# Usage:
#   ./scripts/restore_cache.sh <archive.tar.gz>
#   ./scripts/restore_cache.sh <archive.tar.gz> --force
set -euo pipefail

ARCHIVE=""
FORCE=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --force) FORCE=1; shift ;;
        -h|--help)
            sed -n '2,12p' "$0"
            exit 0
            ;;
        *)
            if [[ -z "${ARCHIVE}" ]]; then
                ARCHIVE="$1"
            else
                echo "[error] unexpected arg: $1" >&2; exit 2
            fi
            shift
            ;;
    esac
done

if [[ -z "${ARCHIVE}" ]]; then
    echo "[error] usage: restore_cache.sh <archive.tar.gz>" >&2
    exit 2
fi
if [[ ! -f "${ARCHIVE}" ]]; then
    echo "[error] archive not found: ${ARCHIVE}" >&2
    exit 1
fi

CACHE_ROOT="${COSCIENTIST_CACHE_DIR:-${HOME}/.cache/coscientist}"
parent="$(dirname "${CACHE_ROOT}")"

if [[ -d "${CACHE_ROOT}" ]]; then
    if [[ "${FORCE}" -ne 1 ]]; then
        echo "[error] cache dir already exists: ${CACHE_ROOT}" >&2
        echo "        Pass --force to overwrite (DESTRUCTIVE)" >&2
        exit 3
    fi
    echo "==> Removing existing ${CACHE_ROOT}"
    rm -rf "${CACHE_ROOT}"
fi

echo "==> Extracting ${ARCHIVE} -> ${parent}/"
mkdir -p "${parent}"
tar -xzf "${ARCHIVE}" -C "${parent}"

if [[ -d "${CACHE_ROOT}" ]]; then
    echo "==> Restored. Verify with:"
    echo "      uv run python -m lib.db_check"
    echo "      uv run python -m lib.install_check"
else
    echo "[error] expected ${CACHE_ROOT} after extract; archive may " \
         "be malformed" >&2
    exit 4
fi
