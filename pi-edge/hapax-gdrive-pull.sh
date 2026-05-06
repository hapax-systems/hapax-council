#!/usr/bin/env bash
# hapax-gdrive-pull — pull workstation gdrive-drop into local rag-staging.
#
# The workstation runs the actual rclone gdrive sync into ~/gdrive-drop/.
# This script just rsyncs from there into our staging dir so
# hapax-rag-edge can preprocess the files. Idempotent.
set -euo pipefail

REMOTE_HOST="${HAPAX_GDRIVE_REMOTE:-hapax-podium.local}"
REMOTE_PATH="${HAPAX_GDRIVE_REMOTE_PATH:-gdrive-drop/}"
LOCAL_DIR="${HAPAX_GDRIVE_LOCAL:-${HOME}/rag-staging}"

mkdir -p "$LOCAL_DIR"

echo "gdrive-pull: rsync ${REMOTE_HOST}:${REMOTE_PATH} -> ${LOCAL_DIR}"
rsync -a --timeout=20 --ignore-existing \
    "hapax@${REMOTE_HOST}:${REMOTE_PATH}" \
    "${LOCAL_DIR}/" 2>&1
echo "gdrive-pull: done at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
