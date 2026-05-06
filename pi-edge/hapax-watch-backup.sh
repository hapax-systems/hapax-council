#!/usr/bin/env bash
# hapax-watch-backup — daily rsync of the workstation's watch state to this Pi.
#
# Pulls the workstation's wear-OS sensor data to a local backup dir so
# it has an off-machine copy.
set -euo pipefail

REMOTE_HOST="${HAPAX_BACKUP_REMOTE:-hapax-podium.local}"
REMOTE_PATH="${HAPAX_BACKUP_REMOTE_PATH:-hapax-state/watch/}"
LOCAL_DIR="${HOME}/backups/watch"

mkdir -p "$LOCAL_DIR"

echo "watch-backup: rsync ${REMOTE_HOST}:${REMOTE_PATH} -> ${LOCAL_DIR}"
rsync -a --timeout=30 --delete-after \
    "hapax@${REMOTE_HOST}:${REMOTE_PATH}" \
    "${LOCAL_DIR}/" 2>&1
echo "watch-backup: done at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
