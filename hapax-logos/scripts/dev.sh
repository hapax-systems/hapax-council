#!/usr/bin/env bash
# Launch `pnpm tauri dev` inside a systemd transient scope.
# When this script exits (any cause), systemd kills ALL processes
# in the scope — no orphaned vite, esbuild, or hapax-logos.
#
# Usage: ./scripts/dev.sh
# Instead of: pnpm tauri dev
set -euo pipefail

cd "$(dirname "$0")/.."

SCOPE="hapax-logos-dev-$$"

# Export Wayland/NVIDIA workarounds
export __NV_DISABLE_EXPLICIT_SYNC=1
export RUST_LOG="${RUST_LOG:-info}"

# Run inside a transient systemd scope with KillMode=control-group.
# On scope stop (or script exit), systemd sends SIGTERM to every
# process in the cgroup, then SIGKILL after TimeoutStopSec.
exec systemd-run --user --scope \
    --unit="$SCOPE" \
    --property=KillMode=control-group \
    --property=TimeoutStopSec=3 \
    pnpm tauri dev
