#!/usr/bin/env bash
# Attended 1-hour DarkPlaces/Screwm renderer SOAK — the suitability gate that
# must PASS before the renderer may be promoted behind the persistent
# ~/.config/hapax/enable-darkplaces-runtime gate.
#
# This is the long-duration sibling of darkplaces-attended-smoke.sh. It runs the
# renderer under a single-command HAPAX_DARKPLACES_RUNTIME_ACK=1 (so containment
# stays intact if the soak aborts), streams kernel + nvidia-smi evidence, and
# hands per-second samples to scripts/darkplaces-soak.py monitor, whose tested
# core (shared/darkplaces_soak.py) fails CLOSED on the first hardware-risk signal.
#
# ATTENDED ONLY. The 2026-05-23 AMD data-fabric sync-flood hard-reset is the
# safety predicate (docs/audits/2026-05-23-screwm-quake-runtime-reset-containment.md).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODE="xvfb"
DURATION_S="${DARKPLACES_SOAK_DURATION_S:-3600}"
WIDTH="${DARKPLACES_WIDTH:-1280}"
HEIGHT="${DARKPLACES_HEIGHT:-720}"
FPS="${DARKPLACES_FPS:-30}"
GPU_INDEX="${HAPAX_DARKPLACES_EXPECTED_GPU_INDEX:-1}"
VIDEO_DEVICE="${HAPAX_DARKPLACES_V4L2_DEVICE:-/dev/video52}"
OUT_ROOT="${DARKPLACES_SOAK_OUT_ROOT:-$HOME/hapax-state/hardware-validation}"
GATE_FILE="$HOME/.config/hapax/enable-darkplaces-runtime"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="${OUT_ROOT}/darkplaces-soak-${TS}-$$"
START_WALL="$(date -Is)"

usage() {
    cat <<'EOF'
Usage: scripts/darkplaces-soak.sh [--xvfb|--v4l2] [--duration-s N]

  --xvfb       Xvfb -> DarkPlaces -> /dev/video52 (default; display-safe).
  --v4l2       Dedicated Xorg -> DarkPlaces -> /dev/video52.
  --duration-s Soak length in seconds (default 3600 = 1h).

Requires HAPAX_DARKPLACES_SMOKE_ACK=1 (attended hardware-validation window).
On PASS, promote with: scripts/darkplaces-promote.sh
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --xvfb) MODE="xvfb" ;;
        --v4l2) MODE="v4l2" ;;
        --duration-s)
            shift
            [ "$#" -gt 0 ] || { echo "darkplaces-soak: --duration-s requires a value" >&2; exit 64; }
            DURATION_S="$1" ;;
        -h|--help) usage; exit 0 ;;
        *) echo "darkplaces-soak: unknown argument: $1" >&2; usage >&2; exit 64 ;;
    esac
    shift
done

case "$DURATION_S" in
    ''|*[!0-9]*) echo "darkplaces-soak: duration must be an integer second count" >&2; exit 64 ;;
esac

if [ "${HAPAX_DARKPLACES_SMOKE_ACK:-}" != "1" ]; then
    cat >&2 <<'EOF'
darkplaces-soak: refused. Set HAPAX_DARKPLACES_SMOKE_ACK=1 for this command
after confirming an operator-attended hardware-validation window. The renderer
remains contained after the 2026-05-23 AMD data-fabric sync-flood reset.
EOF
    exit 78
fi

# The soak MUST run under the single-command ACK with the persistent gate ABSENT,
# so containment is intact if it aborts. Refuse if the gate already exists.
if [ -e "$GATE_FILE" ]; then
    echo "darkplaces-soak: refused — persistent gate $GATE_FILE already exists." >&2
    echo "  Remove it first; the soak must run contained (ACK only), not gated-on." >&2
    exit 78
fi

mkdir -p "$OUT_DIR"

log() { printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$OUT_DIR/harness.log" >&2; }

renderer_pid=""
kernel_pid=""
nvidia_pid=""

stop_all() {
    for pid in "$renderer_pid" "$nvidia_pid" "$kernel_pid"; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    # Belt-and-suspenders: ensure GL is off the GPU.
    [ -n "$renderer_pid" ] && kill -9 "$renderer_pid" 2>/dev/null || true
}
trap stop_all EXIT
trap 'stop_all; exit 130' INT TERM

log "soak start: mode=$MODE duration=${DURATION_S}s gpu_index=$GPU_INDEX out=$OUT_DIR"

# GL preflight (fail-closed: correct GPU on the GL path).
if ! "$REPO_DIR/scripts/darkplaces-gl-preflight.sh" >"$OUT_DIR/gl-preflight.log" 2>&1; then
    log "gl-preflight FAILED — aborting (see gl-preflight.log)"
    exit 1
fi
log "gl-preflight: $(tail -1 "$OUT_DIR/gl-preflight.log")"

# Static evidence snapshot.
nvidia-smi >"$OUT_DIR/nvidia-smi.txt" 2>&1 || true
uname -a >"$OUT_DIR/uname.txt" 2>&1 || true

# Start streaming monitors (same shape as the attended smoke).
journalctl -b -k --since "$START_WALL" -f --no-pager >"$OUT_DIR/kernel-follow.log" 2>&1 &
kernel_pid="$!"
nvidia-smi --query-gpu=timestamp,index,name,power.draw,temperature.gpu,utilization.gpu,memory.used,clocks_throttle_reasons.hw_power_brake_slowdown,clocks_throttle_reasons.sw_thermal_slowdown \
    --format=csv -l 1 >"$OUT_DIR/nvidia-smi-follow.csv" 2>&1 &
nvidia_pid="$!"

# Launch the renderer in the background under the single-command ACK, bounded a
# little beyond the soak so it does not exit before the monitor declares PASS.
LAUNCH_LOG="$OUT_DIR/darkplaces-launch.log"
RENDER_TIMEOUT=$((DURATION_S + 60))
case "$MODE" in
    v4l2) LAUNCHER="$REPO_DIR/scripts/darkplaces-v4l2-xorg.sh" ;;
    xvfb) LAUNCHER="$REPO_DIR/scripts/darkplaces-v4l2-xvfb.sh" ;;
esac
log "launching renderer ($MODE) for up to ${RENDER_TIMEOUT}s -> $VIDEO_DEVICE"
HAPAX_DARKPLACES_RUNTIME_ACK=1 timeout "$RENDER_TIMEOUT" \
    env HAPAX_DARKPLACES_V4L2_DEVICE="$VIDEO_DEVICE" \
        DARKPLACES_WIDTH="$WIDTH" DARKPLACES_HEIGHT="$HEIGHT" DARKPLACES_FPS="$FPS" \
        "$LAUNCHER" >"$LAUNCH_LOG" 2>&1 &
renderer_pid="$!"
log "renderer pid=$renderer_pid"

# Run the soak monitor (tested core). Exit 0 = PASS, 2 = FAIL.
set +e
python3 "$REPO_DIR/scripts/darkplaces-soak.py" monitor \
    --run-dir "$OUT_DIR" \
    --duration-s "$DURATION_S" \
    --gpu-index "$GPU_INDEX" \
    --renderer-pid "$renderer_pid" \
    --launch-log "$LAUNCH_LOG" \
    --kernel-log "$OUT_DIR/kernel-follow.log" \
    --video-device "$VIDEO_DEVICE"
soak_rc="$?"
set -e

stop_all

# Final post-run hardware-risk scan (mirrors the attended smoke exit-2 check).
if { cat "$OUT_DIR/kernel-follow.log" 2>/dev/null || true; } \
    | rg -i 'data fabric|sync flood|NVRM: Xid|GPU has fallen off|hardware error|fatal' \
    >/dev/null 2>&1; then
    log "hardware-risk evidence in kernel log; inspect $OUT_DIR"
    soak_rc=2
fi

if [ "$soak_rc" -eq 0 ]; then
    log "SOAK PASS — promote with: scripts/darkplaces-promote.sh (run dir: $OUT_DIR)"
else
    log "SOAK did not pass (rc=$soak_rc); renderer stays contained. Evidence: $OUT_DIR"
fi
exit "$soak_rc"
