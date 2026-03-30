#!/usr/bin/env bash
# Reload all Logos/Reverie/API services after a new build lands.
# Triggered by hapax-build-reload.path (watches binaries + sentinel).
#
# Rules:
#   - logos-api: ALWAYS restart (Python code changes with every merge)
#   - hapax-imagination: ALWAYS restart (headless, renders to SHM)
#   - hapax-logos: restart ONLY if already running (don't spawn unsolicited windows)
#
# The path unit debounces (TriggerLimitIntervalSec=5), so rapid successive
# builds only trigger one reload cycle.
set -euo pipefail

LOG_TAG="hapax-build-reload"
NTFY_URL="${NTFY_BASE_URL:-http://localhost:8090}/hapax-build"

log() { logger -t "$LOG_TAG" "$*"; }

ntfy() {
    local title="$1" msg="$2" priority="${3:-default}" tags="${4:-}"
    curl -s -o /dev/null \
        -H "Title: $title" \
        -H "Priority: $priority" \
        ${tags:+-H "Tags: $tags"} \
        -d "$msg" \
        "$NTFY_URL" 2>/dev/null || true
}

RESTARTED=()

# logos-api — always restart (Python picks up code changes on restart)
if systemctl --user is-enabled logos-api.service &>/dev/null; then
    log "restarting logos-api"
    systemctl --user restart logos-api.service
    RESTARTED+=("logos-api")
fi

# hapax-imagination — has a winit window. Restarting pops a new window on the
# operator's workspace. The binary is already replaced atomically by `just install`,
# so the NEXT launch will use it. Only restart if already running via systemd.
if systemctl --user is-active hapax-imagination.service &>/dev/null; then
    log "restarting hapax-imagination (was running)"
    systemctl --user restart hapax-imagination.service
    RESTARTED+=("imagination")
else
    log "hapax-imagination not running — skipping (new binary will be used on next launch)"
fi

# hapax-logos — restart if running, start if enabled but dead
if systemctl --user is-active hapax-logos.service &>/dev/null; then
    log "restarting hapax-logos (was running)"
    systemctl --user restart hapax-logos.service
    RESTARTED+=("logos")
elif systemctl --user is-enabled hapax-logos.service &>/dev/null; then
    log "starting hapax-logos (was enabled but dead)"
    systemctl --user start hapax-logos.service
    RESTARTED+=("logos(started)")
fi

# Report
SHA=$( (strings "$HOME/.local/bin/hapax-logos" 2>/dev/null | grep -oP 'VERGEN_GIT_SHA.\K[a-f0-9]{9}' | head -1) || echo "unknown")
SUMMARY="${RESTARTED[*]:-nothing} @ ${SHA}"
log "reload complete: $SUMMARY"
ntfy "Build reloaded" "$SUMMARY" "default" "arrows_counterclockwise"
