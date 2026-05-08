#!/usr/bin/env bash
# hapax-v4l2-watchdog.sh — external v4l2 heartbeat watchdog.
#
# Scrapes the compositor Prometheus endpoint (:9482) for the v4l2sink
# frame counter. Detects stalled output when consecutive 10s intervals
# show zero frame progress and takes escalating action:
#
#   1st zero-delta (10s): log warning
#   2nd zero-delta (20s): SIGUSR1 → compositor (triggers v4l2 output rebuild)
#   3rd zero-delta (30s): full compositor restart + ntfy
#
# Grace period: no action within 30s of compositor boot.
#
# State file: $XDG_RUNTIME_DIR/hapax-v4l2-watchdog.state
#
# cc-task: v4l2-heartbeat-watchdog-gate

set -uo pipefail

METRICS_URL="${HAPAX_V4L2_WD_METRICS:-http://127.0.0.1:9482/metrics}"
STATE_FILE="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/hapax-v4l2-watchdog.state"
COMPOSITOR_UNIT="${HAPAX_V4L2_WD_UNIT:-studio-compositor.service}"
GRACE_PERIOD_S="${HAPAX_V4L2_WD_GRACE_S:-30}"
DRY_RUN="${HAPAX_V4L2_WD_DRY_RUN:-0}"

log() {
  printf 'v4l2-watchdog: %s\n' "$*"
}

# Bail if compositor is not active — nothing to watch.
if ! systemctl --user is-active "$COMPOSITOR_UNIT" >/dev/null 2>&1; then
  exit 0
fi

# Scrape the Prometheus endpoint (timeout 3s).
metrics=$(curl -sf --max-time 3 "$METRICS_URL" 2>/dev/null) || {
  log "metrics endpoint unreachable — skipping"
  exit 0
}

# Extract frame counter.
frames=$(echo "$metrics" | awk '/^studio_compositor_v4l2sink_frames_total[{ ]/{
  # Handle both bare metric and metric with labels
  sub(/.*studio_compositor_v4l2sink_frames_total[{ ]*[^}]*[}]? /, "")
  print int($1)
  found=1
}
END { if (!found) print "NONE" }' found=0)

if [ "$frames" = "NONE" ] || [ -z "$frames" ]; then
  log "frame counter metric not found — skipping"
  exit 0
fi

# Grace period: check compositor boot timestamp.
boot_ts=$(echo "$metrics" | awk '/^studio_compositor_boot_timestamp_seconds[{ ]/{
  sub(/.*studio_compositor_boot_timestamp_seconds[{ ]*[^}]*[}]? /, "")
  printf "%.0f", $1
}')
if [ -n "$boot_ts" ] && [ "$boot_ts" != "0" ]; then
  now_s=$(date +%s)
  age_s=$(( now_s - boot_ts ))
  if [ "$age_s" -lt "$GRACE_PERIOD_S" ]; then
    exit 0
  fi
fi

# Read previous state.
prev_frames=0
consecutive=0
if [ -f "$STATE_FILE" ]; then
  # Format: "frames consecutive"
  read -r prev_frames consecutive < "$STATE_FILE" 2>/dev/null || true
fi

# Compare.
if [ "$frames" -eq "$prev_frames" ]; then
  consecutive=$(( consecutive + 1 ))
else
  # Frames are flowing — reset.
  consecutive=0
fi

# Write state.
echo "$frames $consecutive" > "$STATE_FILE"

# No stall — exit silently.
if [ "$consecutive" -eq 0 ]; then
  exit 0
fi

# --- Escalation ---

compositor_pid=$(systemctl --user show -p MainPID --value "$COMPOSITOR_UNIT" 2>/dev/null)

if [ "$consecutive" -eq 1 ]; then
  log "WARN: v4l2sink stall detected — 0 frames in last 10s (total=$frames)"

elif [ "$consecutive" -eq 2 ]; then
  log "RECOVER: v4l2sink stalled 20s — sending SIGUSR1 to rebuild v4l2 output pipeline (pid=$compositor_pid)"
  if [ "$DRY_RUN" = "1" ]; then
    log "DRY RUN — skipping SIGUSR1"
  elif [ -n "$compositor_pid" ] && [ "$compositor_pid" != "0" ]; then
    kill -USR1 "$compositor_pid" 2>/dev/null || log "SIGUSR1 failed"
  fi

elif [ "$consecutive" -ge 3 ]; then
  log "ESCALATE: v4l2sink stalled ${consecutive}0s — restarting $COMPOSITOR_UNIT + ntfy"
  if [ "$DRY_RUN" = "1" ]; then
    log "DRY RUN — skipping restart + ntfy"
  else
    curl -sf -d "v4l2 watchdog: ${consecutive}0s stall — restarting compositor" \
      "http://127.0.0.1:9090/hapax-system" >/dev/null 2>&1 || true
    systemctl --user restart "$COMPOSITOR_UNIT" || log "restart failed (exit $?)"
    # Reset state after restart — grace period will suppress next ticks.
    echo "0 0" > "$STATE_FILE"
  fi
fi

exit 0
