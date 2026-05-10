#!/usr/bin/env bash
# Persist camera layout mode on compositor shutdown.
set -euo pipefail

SHM_FILE="/dev/shm/hapax-compositor/layout-mode.txt"
PERSIST_FILE="${HOME}/.cache/hapax-compositor/layout-mode-persist.txt"

mkdir -p "${HOME}/.cache/hapax-compositor"

if [ -f "${SHM_FILE}" ]; then
    cp "${SHM_FILE}" "${PERSIST_FILE}"
    printf '%s persisted layout mode: %s\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        "$(cat "${PERSIST_FILE}")"
fi
