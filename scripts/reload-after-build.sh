#!/usr/bin/env bash
# Reload Logos API and imagination after a new production build lands.
# Kept as a manual helper; the hapax-build-reload.path unit that previously
# called this automatically is decommissioned with the Tauri/WebKit runtime.
#
# Rules:
#   - logos-api: ALWAYS restart (Python code changes with every merge)
#   - hapax-imagination: restart only if its binary mtime is newer than the
#     running service — Python-only commits don't change the Rust binary
#     and shouldn't force a restart.
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

# Return 0 (true) iff ~/.local/bin/<binary> was modified after the named
# systemd unit most recently started. Python-only commits don't change
# the Rust binary mtime, so this gate skips the restart in that case.
# Conservative default: if the binary doesn't exist at the expected path,
# or the service-start time is unknown, fall through to "restart" so we
# never silently miss a legitimate rebuild.
_binary_newer_than_service() {
    local svc="$1"
    local bin_path="$HOME/.local/bin/$svc"
    if [[ ! -f "$bin_path" ]]; then
        return 0  # can't tell → err on the side of restart
    fi
    local svc_ts
    svc_ts=$(systemctl --user show "$svc" --property=ActiveEnterTimestamp --value 2>/dev/null || true)
    if [[ -z "$svc_ts" || "$svc_ts" == "n/a" ]]; then
        return 0  # unknown service state → restart
    fi
    local svc_epoch bin_epoch
    svc_epoch=$(date -d "$svc_ts" +%s 2>/dev/null || echo 0)
    bin_epoch=$(stat -c %Y "$bin_path" 2>/dev/null || echo 0)
    [[ "$bin_epoch" -gt "$svc_epoch" ]]
}

RESTARTED=()
SKIPPED=()

# logos-api — always restart (Python picks up code changes on restart)
if systemctl --user is-enabled logos-api.service &>/dev/null; then
    log "restarting logos-api"
    systemctl --user restart logos-api.service
    RESTARTED+=("logos-api")
fi

# hapax-imagination — Rust binary. Only restart if the binary is actually
# newer than the running process (Python-only commits leave it alone).
if systemctl --user is-active hapax-imagination.service &>/dev/null; then
    if _binary_newer_than_service hapax-imagination; then
        log "restarting hapax-imagination (binary newer than service)"
        systemctl --user restart hapax-imagination.service
        RESTARTED+=("imagination")
    else
        log "hapax-imagination binary unchanged — skipping restart"
        SKIPPED+=("imagination")
    fi
else
    log "hapax-imagination not running — skipping"
fi

# Report
SHA=$("$HOME/.local/bin/hapax-imagination" --version 2>/dev/null | grep -oE '[a-f0-9]{9,40}' | head -1 || true)
SHA="${SHA:-unknown}"
SUMMARY="restarted=${RESTARTED[*]:-none} skipped=${SKIPPED[*]:-none} @ ${SHA}"
log "reload complete: $SUMMARY"
ntfy "Build reloaded" "$SUMMARY" "default" "arrows_counterclockwise"
