#!/usr/bin/env bash
# hapax-imagination-watchdog.sh — contain imagination liveness stalls.
#
# current.json remains the legacy fragment diagnostic written by the
# imagination daemon, but it is no longer sufficient by itself to decide that
# restarting the loop is useful. The live visual chain also proves liveness via
# uniforms.json (Reverie writes it every visual tick), fresh source-protocol
# frames, and the upstream DMN/sensor traces that feed the loop. A stale
# current.json with those surfaces fresh is reported but must not churn the
# service every timer tick.
#
# Behavior:
#   - Read mtime of /dev/shm/hapax-imagination/current.json.
#   - If current.json is fresh, no-op (with the existing half-threshold warning).
#   - If current.json is stale/missing, inspect the composite liveness surface:
#       * /dev/shm/hapax-imagination/uniforms.json
#       * /dev/shm/hapax-dmn/observations.json
#       * /dev/shm/hapax-sensors/snapshot.json
#       * /dev/shm/hapax-imagination/sources/*/frame.rgba
#   - If any composite surface is fresh, log the stale primary and do not
#     restart. This preserves evidence without masking a live visual chain.
#   - If all surfaces are stale/missing, restart the loop only when cooldown
#     state permits. The watchdog must never create a restart storm against a
#     stale file that restart does not refresh.
#   - Always exit 0 so the timer keeps running; the watchdog itself should
#     never be the reason a timer falls over.
#
# Knobs (env-overridable so the timer can tune without code edits):
#   HAPAX_IMAG_WATCHDOG_FILE            — legacy primary file (default current.json)
#   HAPAX_IMAG_WATCHDOG_STALE_S         — staleness threshold in seconds (default 600)
#   HAPAX_IMAG_WATCHDOG_FRESH_PATHS     — space-separated additional liveness files
#   HAPAX_IMAG_WATCHDOG_SOURCE_DIR      — source-protocol directory to scan
#   HAPAX_IMAG_WATCHDOG_SOURCE_STALE_S  — source-frame threshold (default STALE_S)
#   HAPAX_IMAG_WATCHDOG_RESTART_COOLDOWN_S — minimum seconds between restarts (default 1800)
#   HAPAX_IMAG_WATCHDOG_COOLDOWN_S      — legacy alias for restart cooldown
#   HAPAX_IMAG_WATCHDOG_STATE_FILE      — explicit last restart-attempt epoch file
#   HAPAX_IMAG_WATCHDOG_STATE_DIR       — default state directory when STATE_FILE is unset
#   HAPAX_IMAG_WATCHDOG_UNIT            — systemd unit to restart
#   HAPAX_IMAG_WATCHDOG_DRY_RUN         — when "1", log restart decision but do not restart
#   HAPAX_IMAG_WATCHDOG_ALERT_ONLY      — when "1", never restart, only log
#   HAPAX_IMAG_WATCHDOG_SYSTEMCTL       — systemctl binary override for tests

set -uo pipefail

WATCH_FILE="${HAPAX_IMAG_WATCHDOG_FILE:-/dev/shm/hapax-imagination/current.json}"
STALE_S="${HAPAX_IMAG_WATCHDOG_STALE_S:-600}"
UNIT="${HAPAX_IMAG_WATCHDOG_UNIT:-hapax-imagination-loop.service}"
DRY_RUN="${HAPAX_IMAG_WATCHDOG_DRY_RUN:-0}"
ALERT_ONLY="${HAPAX_IMAG_WATCHDOG_ALERT_ONLY:-0}"
DEFAULT_FRESH_PATHS="/dev/shm/hapax-imagination/uniforms.json /dev/shm/hapax-dmn/observations.json /dev/shm/hapax-sensors/snapshot.json"
FRESH_PATHS="${HAPAX_IMAG_WATCHDOG_FRESH_PATHS-$DEFAULT_FRESH_PATHS}"
SOURCE_DIR="${HAPAX_IMAG_WATCHDOG_SOURCE_DIR:-/dev/shm/hapax-imagination/sources}"
SOURCE_STALE_S="${HAPAX_IMAG_WATCHDOG_SOURCE_STALE_S:-$STALE_S}"
RESTART_COOLDOWN_S="${HAPAX_IMAG_WATCHDOG_RESTART_COOLDOWN_S:-${HAPAX_IMAG_WATCHDOG_COOLDOWN_S:-1800}}"
STATE_DIR="${HAPAX_IMAG_WATCHDOG_STATE_DIR:-${XDG_RUNTIME_DIR:-/tmp}/hapax-imagination-watchdog}"
STATE_FILE="${HAPAX_IMAG_WATCHDOG_STATE_FILE:-}"
SYSTEMCTL="${HAPAX_IMAG_WATCHDOG_SYSTEMCTL:-systemctl}"

log() {
  # Single-line journal-friendly format. systemd-cat tags via SyslogIdentifier.
  printf 'imagination-watchdog: %s\n' "$*"
}

is_uint() {
  case "${1:-}" in
    '' | *[!0-9]*) return 1 ;;
    *) return 0 ;;
  esac
}

if ! is_uint "$STALE_S"; then
  log "invalid HAPAX_IMAG_WATCHDOG_STALE_S=${STALE_S}; skipping"
  exit 0
fi

if ! is_uint "$SOURCE_STALE_S"; then
  log "invalid HAPAX_IMAG_WATCHDOG_SOURCE_STALE_S=${SOURCE_STALE_S}; skipping"
  exit 0
fi

if ! is_uint "$RESTART_COOLDOWN_S"; then
  log "invalid watchdog restart cooldown=${RESTART_COOLDOWN_S}; skipping"
  exit 0
fi

now_s=$(date +%s)

path_age_s() {
  local path="$1"
  local mtime_s
  local age_s

  [ -e "$path" ] || return 1
  mtime_s=$(stat -c %Y "$path" 2>/dev/null) || return 1
  is_uint "$mtime_s" || return 1
  age_s=$((now_s - mtime_s))
  if [ "$age_s" -lt 0 ]; then
    age_s=0
  fi
  printf '%s\n' "$age_s"
}

state_file_for_unit() {
  local unit_key
  if [ -n "$STATE_FILE" ]; then
    printf '%s\n' "$STATE_FILE"
    return
  fi
  unit_key=$(printf '%s' "$UNIT" | tr -c 'A-Za-z0-9_.-' '_')
  printf '%s/%s.last_restart\n' "$STATE_DIR" "$unit_key"
}

last_restart_s() {
  local state_file="$1"
  local value

  if [ ! -e "$state_file" ]; then
    printf '0\n'
    return
  fi
  IFS= read -r value <"$state_file" || true
  case "$value" in
    '' | *[!0-9]*) printf '0\n' ;;
    *) printf '%s\n' "$value" ;;
  esac
}

write_restart_state() {
  local state_file="$1"
  local state_dir
  local tmp

  state_dir=$(dirname "$state_file")
  mkdir -p "$state_dir" 2>/dev/null || return 0
  tmp="${state_file}.$$"
  printf '%s\n' "$now_s" >"$tmp" 2>/dev/null && mv "$tmp" "$state_file" 2>/dev/null || true
}

unit_is_mid_transition() {
  local active_state
  local sub_state

  if [ "$DRY_RUN" = "1" ]; then
    return 1
  fi
  active_state=$("$SYSTEMCTL" --user show "$UNIT" -p ActiveState --value 2>/dev/null || true)
  sub_state=$("$SYSTEMCTL" --user show "$UNIT" -p SubState --value 2>/dev/null || true)
  case "${active_state}:${sub_state}" in
    deactivating:* | activating:*)
      log "restart suppressed: $UNIT is already ${active_state}/${sub_state}"
      return 0
      ;;
  esac
  return 1
}

restart_with_backoff() {
  local reason="$1"
  local state_file
  local last_restart
  local elapsed

  if [ "$ALERT_ONLY" = "1" ]; then
    log "$reason; ALERT ONLY — skipping restart of $UNIT"
    return
  fi

  state_file=$(state_file_for_unit)
  last_restart=$(last_restart_s "$state_file")
  elapsed=$((now_s - last_restart))
  if [ "$last_restart" -gt 0 ] &&
    [ "$RESTART_COOLDOWN_S" -gt 0 ] &&
    [ "$elapsed" -lt "$RESTART_COOLDOWN_S" ]; then
    log "$reason; restart suppressed by cooldown: elapsed=${elapsed}s threshold=${RESTART_COOLDOWN_S}s"
    return
  fi

  if unit_is_mid_transition; then
    return
  fi

  if [ "$DRY_RUN" = "1" ]; then
    log "$reason; DRY RUN — would restart $UNIT"
    log "DRY RUN — skipping restart"
    return
  fi

  write_restart_state "$state_file"
  log "$reason; no fresh composite liveness — restarting $UNIT (cooldown=${RESTART_COOLDOWN_S}s)"
  "$SYSTEMCTL" --user restart --no-block "$UNIT" || log "restart failed (exit $?)"
}

collect_composite_liveness() {
  FRESH_DETAILS=()
  STALE_DETAILS=()
  local path
  local age_s
  local frame
  local fresh_source_count=0
  local freshest_source_age=""

  if [ -n "$FRESH_PATHS" ]; then
    # Paths are controlled by the systemd unit/env and intentionally
    # space-separated for shell/systemd compatibility.
    for path in $FRESH_PATHS; do
      if age_s=$(path_age_s "$path"); then
        if [ "$age_s" -lt "$STALE_S" ]; then
          FRESH_DETAILS+=("$path age=${age_s}s")
        else
          STALE_DETAILS+=("$path age=${age_s}s")
        fi
      else
        STALE_DETAILS+=("$path missing")
      fi
    done
  fi

  if [ -n "$SOURCE_DIR" ] && [ -d "$SOURCE_DIR" ]; then
    while IFS= read -r -d '' frame; do
      if age_s=$(path_age_s "$frame"); then
        if [ "$age_s" -lt "$SOURCE_STALE_S" ]; then
          fresh_source_count=$((fresh_source_count + 1))
          if [ -z "$freshest_source_age" ] || [ "$age_s" -lt "$freshest_source_age" ]; then
            freshest_source_age="$age_s"
          fi
        fi
      fi
    done < <(find "$SOURCE_DIR" -mindepth 2 -maxdepth 2 -type f -name frame.rgba -print0 2>/dev/null)
  fi

  if [ "$fresh_source_count" -gt 0 ]; then
    FRESH_DETAILS+=("$SOURCE_DIR/*/frame.rgba fresh_count=${fresh_source_count} freshest_age=${freshest_source_age}s")
  else
    STALE_DETAILS+=("$SOURCE_DIR/*/frame.rgba fresh_count=0")
  fi
}

primary_reason=""
if watch_age_s=$(path_age_s "$WATCH_FILE"); then
  if [ "$watch_age_s" -lt "$STALE_S" ]; then
    # Quiet success — verbose journal noise was the original sin of the
    # waybar custom modules (see project_zram_evicts_idle_guis memory).
    # Log only at thresholds so steady-state checks are silent.
    if [ "$STALE_S" -gt 0 ] && [ "$watch_age_s" -gt $((STALE_S / 2)) ]; then
      log "approaching stale: age=${watch_age_s}s threshold=${STALE_S}s"
    fi
    exit 0
  fi
  primary_reason="primary stale: $WATCH_FILE age=${watch_age_s}s threshold=${STALE_S}s"
else
  primary_reason="primary missing: $WATCH_FILE threshold=${STALE_S}s"
fi

collect_composite_liveness

if [ "${#FRESH_DETAILS[@]}" -gt 0 ]; then
  log "$primary_reason; composite liveness fresh (${FRESH_DETAILS[*]}) — not restarting $UNIT"
  exit 0
fi

restart_with_backoff "$primary_reason; composite liveness stale (${STALE_DETAILS[*]})"

exit 0
