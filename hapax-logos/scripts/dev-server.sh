#!/usr/bin/env bash
# Wrapper for vite dev server that ensures no orphan processes.
# Tauri's beforeDevCommand spawns this instead of `pnpm dev` directly.
# On exit (any cause: SIGTERM, SIGINT, parent death), the entire
# process group is killed — vite, esbuild, and any other children.
set -euo pipefail

# Run in a new process group so we can kill all children
set -m

cleanup() {
    # Kill all processes in our process group
    kill -- -$$ 2>/dev/null || true
    # Wait briefly, then force-kill survivors
    sleep 0.5
    kill -9 -- -$$ 2>/dev/null || true
}
trap cleanup EXIT INT TERM HUP

# Request SIGTERM on parent death (Linux-specific: PR_SET_PDEATHSIG)
# This fires if the Tauri cargo process dies unexpectedly.
python3 -c "import ctypes; ctypes.CDLL('libc.so.6').prctl(1, 15)" 2>/dev/null || true

# Run vite as a child (NOT exec) so the trap stays active
pnpm dev &
wait
