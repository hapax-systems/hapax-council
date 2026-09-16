#!/usr/bin/env bash
# Launch MediaMTX with the YouTube stream key loaded from the FileStore at runtime.
# Used by systemd/units/mediamtx.service.
#
# Phase 5 of the camera 24/7 resilience epic.
# See docs/superpowers/specs/2026-04-12-native-rtmp-delivery-design.md
set -euo pipefail

# Secrets come from the FileStore through the one shared helper, never from pass.
# Operator ruling 2026-09-16: pass and gopass are not used to manage secrets going forward.
# Pure parameter expansion: resolving this with `dirname`/`cd` made sourcing depend on
# PATH, and a caller with a restricted PATH got `/lib/secret.sh: No such file`.
. "${BASH_SOURCE[0]%/*}/lib/secret.sh"

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_SRC="${REPO_DIR}/config/mediamtx.yml"

if [[ ! -f "$CONFIG_SRC" ]]; then
    echo "ERROR: config not found at $CONFIG_SRC" >&2
    exit 1
fi

# Verify mediamtx binary is present.
if ! command -v mediamtx &>/dev/null; then
    echo "ERROR: mediamtx binary not on PATH. Install mediamtx-bin from AUR." >&2
    exit 1
fi

# Verify ffmpeg is present (used by the runOnReady hook).
if ! command -v ffmpeg &>/dev/null; then
    echo "ERROR: ffmpeg not found — runOnReady hook will fail silently." >&2
    exit 1
fi

# Load the YouTube stream key from the FileStore.
if ! HAPAX_YOUTUBE_STREAM_KEY=$(hapax_secret_get streaming/youtube-stream-key); then
    echo "ERROR: could not read streaming/youtube-stream-key from the FileStore. Next action: put it with \`hapax-secret streaming/youtube-stream-key\`." >&2
    echo "       store with: hapax-secret streaming/youtube-stream-key" >&2
    exit 1
fi
export HAPAX_YOUTUBE_STREAM_KEY

# MediaMTX does not natively expand ${VAR} in runOnReady without environment
# loading. Template the config to a runtime location so ffmpeg in the hook
# reads the literal key.
RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp}/mediamtx"
mkdir -p "$RUNTIME_DIR"
RUNTIME_CONFIG="${RUNTIME_DIR}/mediamtx.yml"

# Substitute the key into the config once so MediaMTX reads a concrete value.
# Avoid leaking the key to `ps` or system logs by using a heredoc approach.
envsubst '${HAPAX_YOUTUBE_STREAM_KEY}' < "$CONFIG_SRC" > "$RUNTIME_CONFIG"
chmod 0600 "$RUNTIME_CONFIG"

exec mediamtx "$RUNTIME_CONFIG"
