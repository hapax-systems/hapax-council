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
#   - Otherwise no-op
#   - Always exit 0 so the timer keeps running; the watchdog itself
#     should never be the reason a timer falls over.
#
# Knobs (env-overridable so the timer can tune without code edits):
#   HAPAX_IMAG_WATCHDOG_FILE   — file to check (default current.json)
#   HAPAX_IMAG_WATCHDOG_STALE_S — staleness threshold in seconds (default 600)
#   HAPAX_IMAG_WATCHDOG_UNIT   — systemd unit to restart (default hapax-imagination-loop.service)
#   HAPAX_IMAG_WATCHDOG_DRY_RUN — when "1", log the restart decision but do not restart

set -uo pipefail

WATCH_FILE="${HAPAX_IMAG_WATCHDOG_FILE:-/dev/shm/hapax-imagination/current.json}"
STALE_S="${HAPAX_IMAG_WATCHDOG_STALE_S:-600}"
UNIT="${HAPAX_IMAG_WATCHDOG_UNIT:-hapax-imagination-loop.service}"
DRY_RUN="${HAPAX_IMAG_WATCHDOG_DRY_RUN:-0}"

log() {
  # Single-line journal-friendly format. systemd-cat tags via SyslogIdentifier.
  printf 'imagination-watchdog: %s\n' "$*"
}

now_s=$(date +%s)

if [ ! -e "$WATCH_FILE" ]; then
  log "watch file missing ($WATCH_FILE) — restarting $UNIT"
  if [ "$DRY_RUN" = "1" ]; then
    log "DRY RUN — skipping restart"
    exit 0
  fi
  systemctl --user restart "$UNIT" || log "restart failed (exit $?)"
  exit 0
fi

mtime_s=$(stat -c %Y "$WATCH_FILE" 2>/dev/null || echo 0)
age_s=$(( now_s - mtime_s ))

if [ "$age_s" -ge "$STALE_S" ]; then
  log "stale: age=${age_s}s threshold=${STALE_S}s — restarting $UNIT"
  if [ "$DRY_RUN" = "1" ]; then
    log "DRY RUN — skipping restart"
    exit 0
  fi
  systemctl --user restart "$UNIT" || log "restart failed (exit $?)"
else
  # Quiet success — verbose journal noise was the original sin of the
  # waybar custom modules (see project_zram_evicts_idle_guis memory).
  # Log only at thresholds so steady-state checks are silent.
  if [ "$age_s" -gt $(( STALE_S / 2 )) ]; then
    log "approaching stale: age=${age_s}s threshold=${STALE_S}s"
  fi
fi

exit 0
