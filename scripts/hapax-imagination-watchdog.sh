#!/usr/bin/env bash
# hapax-imagination-watchdog.sh — restart hapax-imagination-loop when current.json goes stale.
#
# Operator-directed 2026-04-22 after a session-long observation that
# TabbyAPI was inactive but the imagination loop never recovered, leaving
# the visual surface frozen on a stale current.json. This watchdog kicks
# the loop after a configurable staleness window so the next 24/7 stretch
# does not silently lose hours of imagination output.
#
# Behavior:
#   - Read mtime of /dev/shm/hapax-imagination/current.json
#   - If file missing OR mtime age >= STALE_S, restart hapax-imagination-loop.service
#     only when restart cooldown/state permits. The watchdog must never create
#     a restart storm against a stale file that restart does not refresh.
#   - Otherwise no-op
#   - Always exit 0 so the timer keeps running; the watchdog itself
#     should never be the reason a timer falls over.
#
# Knobs (env-overridable so the timer can tune without code edits):
#   HAPAX_IMAG_WATCHDOG_FILE   — file to check (default current.json)
#   HAPAX_IMAG_WATCHDOG_STALE_S — staleness threshold in seconds (default 600)
#   HAPAX_IMAG_WATCHDOG_UNIT   — systemd unit to restart (default hapax-imagination-loop.service)
#   HAPAX_IMAG_WATCHDOG_COOLDOWN_S — minimum seconds between restart attempts (default 900)
#   HAPAX_IMAG_WATCHDOG_STATE_FILE — stores last restart-attempt epoch
#   HAPAX_IMAG_WATCHDOG_DRY_RUN — when "1", log the restart decision but do not restart

set -uo pipefail

WATCH_FILE="${HAPAX_IMAG_WATCHDOG_FILE:-/dev/shm/hapax-imagination/current.json}"
STALE_S="${HAPAX_IMAG_WATCHDOG_STALE_S:-600}"
UNIT="${HAPAX_IMAG_WATCHDOG_UNIT:-hapax-imagination-loop.service}"
COOLDOWN_S="${HAPAX_IMAG_WATCHDOG_COOLDOWN_S:-900}"
STATE_FILE="${HAPAX_IMAG_WATCHDOG_STATE_FILE:-${XDG_RUNTIME_DIR:-/tmp}/hapax/imagination-watchdog-last-restart}"
DRY_RUN="${HAPAX_IMAG_WATCHDOG_DRY_RUN:-0}"
SYSTEMCTL="${HAPAX_IMAG_WATCHDOG_SYSTEMCTL:-systemctl}"

log() {
  # Single-line journal-friendly format. systemd-cat tags via SyslogIdentifier.
  printf 'imagination-watchdog: %s\n' "$*"
}

now_s=$(date +%s)

last_restart_s() {
  if [ ! -e "$STATE_FILE" ]; then
    printf '0\n'
    return
  fi
  IFS= read -r value < "$STATE_FILE" || true
  case "$value" in
    ''|*[!0-9]*) printf '0\n' ;;
    *) printf '%s\n' "$value" ;;
  esac
}

write_restart_state() {
  state_dir=$(dirname "$STATE_FILE")
  mkdir -p "$state_dir" 2>/dev/null || return 0
  tmp="${STATE_FILE}.$$"
  printf '%s\n' "$now_s" > "$tmp" 2>/dev/null && mv "$tmp" "$STATE_FILE" 2>/dev/null || true
}

restart_allowed() {
  last_s=$(last_restart_s)
  elapsed_s=$(( now_s - last_s ))
  if [ "$COOLDOWN_S" -gt 0 ] && [ "$last_s" -gt 0 ] && [ "$elapsed_s" -lt "$COOLDOWN_S" ]; then
    log "restart suppressed by cooldown: elapsed=${elapsed_s}s threshold=${COOLDOWN_S}s"
    return 1
  fi
  return 0
}

unit_is_mid_transition() {
  if [ "$DRY_RUN" = "1" ]; then
    return 1
  fi
  active_state=$("$SYSTEMCTL" --user show "$UNIT" -p ActiveState --value 2>/dev/null || true)
  sub_state=$("$SYSTEMCTL" --user show "$UNIT" -p SubState --value 2>/dev/null || true)
  case "${active_state}:${sub_state}" in
    deactivating:*|activating:*)
      log "restart suppressed: $UNIT is already ${active_state}/${sub_state}"
      return 0
      ;;
  esac
  return 1
}

maybe_restart() {
  reason="$1"
  log "$reason — restarting $UNIT"
  if ! restart_allowed; then
    return 0
  fi
  if unit_is_mid_transition; then
    return 0
  fi
  if [ "$DRY_RUN" = "1" ]; then
    log "DRY RUN — skipping restart"
    return 0
  fi
  write_restart_state
  "$SYSTEMCTL" --user restart --no-block "$UNIT" || log "restart failed (exit $?)"
}

if [ ! -e "$WATCH_FILE" ]; then
  maybe_restart "watch file missing ($WATCH_FILE)"
  exit 0
fi

mtime_s=$(stat -c %Y "$WATCH_FILE" 2>/dev/null || echo 0)
age_s=$(( now_s - mtime_s ))

if [ "$age_s" -ge "$STALE_S" ]; then
  maybe_restart "stale: age=${age_s}s threshold=${STALE_S}s"
else
  # Quiet success — verbose journal noise was the original sin of the
  # waybar custom modules (see project_zram_evicts_idle_guis memory).
  # Log only at thresholds so steady-state checks are silent.
  if [ "$age_s" -gt $(( STALE_S / 2 )) ]; then
    log "approaching stale: age=${age_s}s threshold=${STALE_S}s"
  fi
fi

exit 0
