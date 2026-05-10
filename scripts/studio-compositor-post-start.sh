#!/usr/bin/env bash
# Restore camera layout mode after compositor restart.
set -euo pipefail

PERSIST_FILE="${HOME}/.cache/hapax-compositor/layout-mode-persist.txt"
SHM_DIR="/dev/shm/hapax-compositor"
SHM_FILE="${SHM_DIR}/layout-mode.txt"
DEFAULT_MODE="${HAPAX_COMPOSITOR_DEFAULT_LAYOUT_MODE:-balanced}"

mkdir -p "${HOME}/.cache/hapax-compositor"

for _ in $(seq 1 30); do
    [ -d "${SHM_DIR}" ] && break
    sleep 0.5
done

if [ -f "${PERSIST_FILE}" ]; then
    mode="$(cat "${PERSIST_FILE}")"
else
    mode="${DEFAULT_MODE}"
    printf '%s\n' "${mode}" >"${PERSIST_FILE}"
fi

printf '%s\n' "${mode}" >"${SHM_FILE}"
printf '%s restored layout mode: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${mode}"
