#!/usr/bin/env bash
# v0.87 — back up the Coscientist cache.
#
# Tarballs ~/.cache/coscientist/ (or $COSCIENTIST_CACHE_DIR if set)
# minus generated/transient files. Output: timestamped .tar.gz in
# the current directory unless --out specified.
#
# Usage:
#   ./scripts/backup_cache.sh
#   ./scripts/backup_cache.sh --out /path/to/backups/
#   COSCIENTIST_CACHE_DIR=/tmp/foo ./scripts/backup_cache.sh
#
# Excludes (already gitignored or transient):
#   - **/__pycache__/
#   - **/*.pyc
#   - audit.log.tmp / *.json.tmp
#   - WAL sidecar files (*-wal, *-shm) — re-created on first open
set -euo pipefail

CACHE_ROOT="${COSCIENTIST_CACHE_DIR:-${HOME}/.cache/coscientist}"
OUT_DIR="."
NAME=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --out) OUT_DIR="$2"; shift 2 ;;
        --name) NAME="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,18p' "$0"
            exit 0
            ;;
        *) echo "[error] unknown arg: $1" >&2; exit 2 ;;
    esac
done

if [[ ! -d "${CACHE_ROOT}" ]]; then
    echo "[error] cache dir does not exist: ${CACHE_ROOT}" >&2
    exit 1
fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
if [[ -z "${NAME}" ]]; then
    NAME="coscientist-cache-${stamp}.tar.gz"
fi
mkdir -p "${OUT_DIR}"
out_path="${OUT_DIR}/${NAME}"

echo "==> Backing up ${CACHE_ROOT} -> ${out_path}"

# Use tar with explicit exclude patterns. Run from cache parent so
# the archive expands cleanly via 'tar xzf <archive>'.
parent="$(dirname "${CACHE_ROOT}")"
basename="$(basename "${CACHE_ROOT}")"

tar \
    --exclude="*.pyc" \
    --exclude="__pycache__" \
    --exclude="*.json.tmp" \
    --exclude="*.tmp" \
    --exclude="*-wal" \
    --exclude="*-shm" \
    -czf "${out_path}" \
    -C "${parent}" \
    "${basename}"

size=$(du -h "${out_path}" | cut -f1)
echo "==> Backup complete: ${out_path} (${size})"
echo
echo "Restore with:"
echo "  ./scripts/restore_cache.sh ${out_path}"
