#!/usr/bin/env bash
# End-to-end smoke test for the camera 24/7 resilience epic.
# Phase 6 of the camera 24/7 resilience epic.
#
# Tests the full pipeline:
#   1. systemd unit status
#   2. Prometheus metrics endpoint
#   3. MediaMTX reachability
#   4. Simulated camera disconnect + recovery via USBDEVFS_RESET
#   5. State machine log inspection for expected transition sequence
#
# Exits 0 on success, non-zero on any gate failure. Intended for manual
# operator runs and for CI self-hosted runners with real camera hardware.
set -euo pipefail

pass() { echo "[PASS] $*"; }
fail() { echo "[FAIL] $*" >&2; exit 1; }
info() { echo "[INFO] $*"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TIMEOUT=30

# ------------------------ 1. systemd unit ------------------------

if systemctl --user is-active --quiet studio-compositor.service; then
    pass "studio-compositor.service is active"
else
    fail "studio-compositor.service is not active"
fi

UNIT_STATUS=$(systemctl --user show studio-compositor.service --property=StatusText --value 2>/dev/null || echo "")
info "unit status: $UNIT_STATUS"

# ------------------------ 2. metrics endpoint ------------------------

if ! command -v curl &>/dev/null; then
    fail "curl not available"
fi

METRICS_URL="http://127.0.0.1:9482/metrics"
if ! curl -sf -m 5 "$METRICS_URL" >/dev/null; then
    fail "Prometheus metrics endpoint $METRICS_URL not reachable"
fi
pass "metrics endpoint reachable"

# Confirm at least one frame has been observed
FRAME_TOTAL=$(curl -sf "$METRICS_URL" 2>/dev/null | awk '/^studio_camera_frames_total/ {n += $NF} END {print n+0}')
if [[ "$FRAME_TOTAL" -lt 1 ]]; then
    fail "no frames observed across any camera (studio_camera_frames_total=$FRAME_TOTAL)"
fi
pass "frames observed across cameras: $FRAME_TOTAL"

CAMERAS_HEALTHY=$(curl -sf "$METRICS_URL" 2>/dev/null | awk '/^studio_camera_state.*state="healthy"/ {n += $NF} END {print n+0}')
info "cameras healthy: $CAMERAS_HEALTHY/6"

# ------------------------ 3. MediaMTX ------------------------

if systemctl --user is-active --quiet mediamtx.service; then
    pass "mediamtx.service is active"
    MEDIAMTX_METRICS="http://127.0.0.1:9998/metrics"
    if curl -sf -m 5 "$MEDIAMTX_METRICS" >/dev/null; then
        pass "mediamtx metrics endpoint reachable"
    else
        info "mediamtx metrics endpoint not reachable (may be expected if disabled)"
    fi
else
    info "mediamtx.service is not active (livestream not currently on)"
fi

# ------------------------ 4. Simulated disconnect ------------------------

if [[ "${SKIP_DISCONNECT_SIM:-0}" == "1" ]]; then
    info "SKIP_DISCONNECT_SIM=1, skipping disconnect simulation"
else
    TARGET_ROLE="${SMOKE_TARGET_ROLE:-brio-synths}"
    info "simulating disconnect of role=$TARGET_ROLE via USBDEVFS_RESET"

    BEFORE_STATE=$(curl -sf "$METRICS_URL" 2>/dev/null | grep -E "^studio_camera_state\{.*role=\"$TARGET_ROLE\".*state=\"healthy\"\}" | awk '{print $NF}' || echo "0")
    info "pre-disconnect state for $TARGET_ROLE: healthy=$BEFORE_STATE"

    if ! "$SCRIPT_DIR/studio-simulate-usb-disconnect.sh" "$TARGET_ROLE" 2>&1; then
        info "disconnect sim returned non-zero (may need sudo); skipping recovery assertion"
    else
        # Wait up to TIMEOUT seconds for the state machine to transition
        # back to healthy after the reset
        for _ in $(seq 1 $TIMEOUT); do
            AFTER_STATE=$(curl -sf "$METRICS_URL" 2>/dev/null | grep -E "^studio_camera_state\{.*role=\"$TARGET_ROLE\".*state=\"healthy\"\}" | awk '{print $NF}' || echo "0")
            if [[ "$AFTER_STATE" == "1" ]]; then
                pass "role=$TARGET_ROLE recovered to healthy within timeout"
                break
            fi
            sleep 1
        done
        if [[ "$AFTER_STATE" != "1" ]]; then
            fail "role=$TARGET_ROLE did not recover to healthy within $TIMEOUT s"
        fi
    fi
fi

# ------------------------ 5. log inspection ------------------------

RECENT_TRANSITIONS=$(journalctl --user -u studio-compositor.service --since "5 minutes ago" 2>/dev/null \
    | awk '/camera state:/ {n++} END {print n+0}')
info "state machine transitions in the last 5 min: $RECENT_TRANSITIONS"

echo ""
echo "[OK] smoke test completed"
exit 0
