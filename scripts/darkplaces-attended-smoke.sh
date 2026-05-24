#!/usr/bin/env bash
# Attended DarkPlaces smoke harness for the Screwm renderer migration.
#
# Default mode is read-only topology collection. Launch modes require
# HAPAX_DARKPLACES_SMOKE_ACK=1 and run through the runtime guard.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODE="collect"
DURATION_S="${DARKPLACES_SMOKE_DURATION_S:-30}"
WIDTH="${DARKPLACES_WIDTH:-1280}"
HEIGHT="${DARKPLACES_HEIGHT:-720}"
FPS="${DARKPLACES_FPS:-30}"
OUT_ROOT="${DARKPLACES_SMOKE_OUT_ROOT:-$HOME/hapax-state/hardware-validation}"
EXPECTED_GPU_INDEX="${HAPAX_DARKPLACES_EXPECTED_GPU_INDEX:-1}"
EXPECTED_GL_RENDERER="${HAPAX_DARKPLACES_EXPECTED_GL_RENDERER:-}"
SKIP_GL_RENDERER_ASSERT="${HAPAX_DARKPLACES_SKIP_GL_RENDERER_ASSERT:-0}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="${OUT_ROOT}/darkplaces-screwm-${TS}-$$"
START_WALL="$(date -Is)"

usage() {
    cat <<'EOF'
Usage: scripts/darkplaces-attended-smoke.sh [--collect-only|--window|--v4l2|--xvfb] [--duration-s N]

Modes:
  --collect-only   Read-only topology and recent-kernel evidence collection.
  --window         Launch the visible DarkPlaces Screwm renderer, then stop it.
  --v4l2           Launch dedicated Xorg -> DarkPlaces -> /dev/video52, then stop it.
  --xvfb           Launch Xvfb -> DarkPlaces -> /dev/video52, then stop it.

Launch modes require:
  HAPAX_DARKPLACES_SMOKE_ACK=1

Renderer assertion:
  By default launch modes expect OpenGL to report the NVIDIA GPU at
  HAPAX_DARKPLACES_EXPECTED_GPU_INDEX, default 1. Override with
  HAPAX_DARKPLACES_EXPECTED_GL_RENDERER. Set
  HAPAX_DARKPLACES_SKIP_GL_RENDERER_ASSERT=1 only when intentionally running a
  non-GPU capture experiment.

The harness writes evidence under:
  ~/hapax-state/hardware-validation/darkplaces-screwm-<timestamp>-<pid>/
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --collect-only)
            MODE="collect"
            ;;
        --window)
            MODE="window"
            ;;
        --v4l2)
            MODE="v4l2"
            ;;
        --xvfb)
            MODE="xvfb"
            ;;
        --duration-s)
            shift
            if [ "$#" -eq 0 ]; then
                echo "darkplaces-attended-smoke: --duration-s requires a value" >&2
                exit 64
            fi
            DURATION_S="$1"
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "darkplaces-attended-smoke: unknown argument: $1" >&2
            usage >&2
            exit 64
            ;;
    esac
    shift
done

case "$DURATION_S" in
    ''|*[!0-9]*)
        echo "darkplaces-attended-smoke: duration must be an integer second count" >&2
        exit 64
        ;;
esac

if [ "$MODE" = "xvfb" ] &&
    [ -z "${HAPAX_DARKPLACES_EXPECTED_GL_RENDERER:-}" ] &&
    [ -z "${HAPAX_DARKPLACES_EXPECTED_GPU_INDEX:-}" ]; then
    EXPECTED_GPU_INDEX=0
    export HAPAX_DARKPLACES_EXPECTED_GPU_INDEX=0
fi

mkdir -p "$OUT_DIR"

log() {
    printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$OUT_DIR/harness.log" >&2
}

capture() {
    local name="$1"
    shift
    {
        printf '$'
        printf ' %q' "$@"
        printf '\n\n'
        "$@"
    } >"$OUT_DIR/$name" 2>&1 || true
}

capture_shell() {
    local name="$1"
    shift
    {
        printf '$ %s\n\n' "$*"
        bash -lc "$*"
    } >"$OUT_DIR/$name" 2>&1 || true
}

kernel_filter='data fabric|sync flood|NVRM|Xid|pcie|AER|MCE|hardware error|fatal|GPU has fallen off'

resolve_expected_gl_renderer() {
    if [ "$SKIP_GL_RENDERER_ASSERT" = "1" ]; then
        return
    fi
    if [ -n "$EXPECTED_GL_RENDERER" ]; then
        printf '%s\n' "$EXPECTED_GL_RENDERER"
        return
    fi
    if ! command -v nvidia-smi >/dev/null 2>&1; then
        return
    fi
    nvidia-smi -i "$EXPECTED_GPU_INDEX" --query-gpu=name --format=csv,noheader,nounits 2>/dev/null |
        sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

EXPECTED_GL_RENDERER_RESOLVED="$(resolve_expected_gl_renderer || true)"

collect_static_evidence() {
    log "collecting static GPU and kernel evidence into $OUT_DIR"
    {
        printf 'expected_gpu_index=%s\n' "$EXPECTED_GPU_INDEX"
        printf 'expected_gl_renderer=%s\n' "$EXPECTED_GL_RENDERER_RESOLVED"
        printf 'skip_gl_renderer_assert=%s\n' "$SKIP_GL_RENDERER_ASSERT"
    } >"$OUT_DIR/expected-renderer.txt"
    capture uname.txt uname -a
    capture systemd-darkplaces.txt systemctl --user status \
        hapax-darkplaces hapax-darkplaces-bridge hapax-darkplaces-v4l2 --no-pager --lines=20
    # shellcheck disable=SC2016
    capture video-devices.txt bash -lc 'for d in /dev/video42 /dev/video52; do echo "== $d =="; [ -e "$d" ] && { v4l2-ctl -d "$d" --get-fmt-video 2>&1 || true; fuser "$d" 2>&1 || true; } || echo missing; done'
    capture nvidia-smi.txt nvidia-smi
    capture nvidia-gpus.csv nvidia-smi --query-gpu=index,name,pci.bus_id,display_active,persistence_mode,power.draw,temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv
    capture nvidia-pmon.txt nvidia-smi pmon -c 1
    # shellcheck disable=SC2016
    capture_shell nvidia-lspci.txt '
        nvidia-smi --query-gpu=pci.bus_id --format=csv,noheader,nounits 2>/dev/null |
        while read -r bus; do
            short="${bus#00000000:}"
            echo "== ${short} =="
            lspci -vv -s "$short" 2>&1 || true
        done
    '
    if command -v xrandr >/dev/null 2>&1; then
        capture xrandr-providers.txt xrandr --listproviders
    fi
    if command -v glxinfo >/dev/null 2>&1; then
        capture glxinfo-default.txt glxinfo -B
        capture glxinfo-dri-prime-1.txt env DRI_PRIME=1 glxinfo -B
        capture glxinfo-nvidia-offload.txt env __NV_PRIME_RENDER_OFFLOAD=1 \
            __GLX_VENDOR_LIBRARY_NAME=nvidia glxinfo -B
    fi
    if command -v eglinfo >/dev/null 2>&1; then
        capture eglinfo-brief.txt eglinfo -B
    fi
    capture recent-kernel-gpu.txt bash -lc "journalctl -b -k --since '30 min ago' --no-pager | rg -i '$kernel_filter' -C 2 || true"
}

require_launch_ack() {
    if [ "${HAPAX_DARKPLACES_SMOKE_ACK:-}" != "1" ]; then
        cat >&2 <<'EOF'
darkplaces-attended-smoke: launch mode refused.

Set HAPAX_DARKPLACES_SMOKE_ACK=1 for this command after confirming an
operator-attended hardware-validation window. DarkPlaces runtime remains
contained after the 2026-05-23 AMD data-fabric sync-flood reset.
EOF
        exit 78
    fi
}

validate_gl_preflight() {
    local preflight_log="$OUT_DIR/gl-preflight.log"
    local rc
    set +e
    "$REPO_DIR/scripts/darkplaces-gl-preflight.sh" >"$preflight_log" 2>&1
    rc="$?"
    set -e
    if [ "$rc" -eq 0 ]; then
        log "$(tail -1 "$preflight_log")"
        return 0
    fi
    log "$(tail -1 "$preflight_log")"
    return "$rc"
}

validate_darkplaces_renderer() {
    local launch_log="$1"
    local observed
    if [ -z "$EXPECTED_GL_RENDERER_RESOLVED" ]; then
        log "GL renderer assertion skipped: no expected renderer resolved"
        return 0
    fi
    observed="$(
        awk '
            /GL_RENDERER/ {
                line=$0
                sub(/^.*GL_RENDERER[[:space:]:=]+/, "", line)
                print line
                found=1
                exit
            }
            END {
                if (!found) {
                    exit 1
                }
            }
        ' "$launch_log" 2>/dev/null || true
    )"
    if [ -z "$observed" ]; then
        log "GL renderer assertion failed: DarkPlaces did not report GL_RENDERER"
        return 3
    fi
    if [[ "$observed" != *"$EXPECTED_GL_RENDERER_RESOLVED"* ]]; then
        log "GL renderer assertion failed: observed '$observed', expected '$EXPECTED_GL_RENDERER_RESOLVED'"
        return 3
    fi
    log "GL renderer assertion passed: $observed"
}

start_monitors() {
    journalctl -b -k --since "$START_WALL" -f --no-pager >"$OUT_DIR/kernel-follow.log" 2>&1 &
    kernel_pid="$!"
    nvidia-smi --query-gpu=timestamp,index,name,power.draw,temperature.gpu,utilization.gpu,memory.used,clocks_throttle_reasons.hw_power_brake_slowdown,clocks_throttle_reasons.sw_thermal_slowdown --format=csv -l 1 \
        >"$OUT_DIR/nvidia-smi-follow.csv" 2>&1 &
    nvidia_pid="$!"
}

stop_monitors() {
    for pid in "${nvidia_pid:-}" "${kernel_pid:-}"; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
    done
}

trap stop_monitors EXIT
trap 'stop_monitors; exit 130' INT TERM

run_launch_smoke() {
    local command_desc="$1"
    local launch_log="$OUT_DIR/darkplaces-launch.log"
    local preflight_rc
    shift
    require_launch_ack
    preflight_rc=0
    if [ "${DARKPLACES_SMOKE_PRELAUNCH_GL_PREFLIGHT:-1}" = "1" ]; then
        validate_gl_preflight || preflight_rc="$?"
        if [ "$preflight_rc" -ne 0 ]; then
            return "$preflight_rc"
        fi
    fi
    log "launching ${command_desc} for ${DURATION_S}s"
    {
        printf '$'
        printf ' %q' "$@"
        printf '\n\n'
    } >"$launch_log"
    start_monitors
    set +e
    HAPAX_DARKPLACES_RUNTIME_ACK=1 timeout "$DURATION_S" "$@" >>"$launch_log" 2>&1
    local rc="$?"
    set -e
    stop_monitors
    if [ "$rc" -eq 124 ]; then
        log "${command_desc} reached the bounded timeout"
        rc=0
    else
        log "${command_desc} exited rc=${rc}"
    fi
    if [ "$rc" -eq 0 ]; then
        validate_darkplaces_renderer "$launch_log" || rc="$?"
    fi
    return "$rc"
}

collect_static_evidence

case "$MODE" in
    collect)
        log "collect-only mode complete"
        ;;
    window)
        run_launch_smoke "visible DarkPlaces Screwm renderer" \
            env SCREWM_WIDTH="$WIDTH" SCREWM_HEIGHT="$HEIGHT" "$REPO_DIR/scripts/launch-darkplaces-screwm.sh"
        ;;
    v4l2)
        DARKPLACES_SMOKE_PRELAUNCH_GL_PREFLIGHT=0
        run_launch_smoke "headless DarkPlaces v4l2 renderer feed" \
            env HAPAX_DARKPLACES_V4L2_DEVICE="${HAPAX_DARKPLACES_V4L2_DEVICE:-/dev/video52}" \
                DARKPLACES_WIDTH="$WIDTH" DARKPLACES_HEIGHT="$HEIGHT" DARKPLACES_FPS="$FPS" \
                "$REPO_DIR/scripts/darkplaces-v4l2-xorg.sh"
        ;;
    xvfb)
        DARKPLACES_SMOKE_PRELAUNCH_GL_PREFLIGHT=0
        run_launch_smoke "display-safe Xvfb DarkPlaces v4l2 renderer feed" \
            env HAPAX_DARKPLACES_V4L2_DEVICE="${HAPAX_DARKPLACES_V4L2_DEVICE:-/dev/video52}" \
                DARKPLACES_WIDTH="$WIDTH" DARKPLACES_HEIGHT="$HEIGHT" DARKPLACES_FPS="$FPS" \
                "$REPO_DIR/scripts/darkplaces-v4l2-xvfb.sh"
        ;;
esac

capture post-kernel-gpu.txt bash -lc "journalctl -b -k --since '$START_WALL' --no-pager | rg -i '$kernel_filter' -C 2 || true"
capture post-nvidia-pmon.txt nvidia-smi pmon -c 1

if {
    tail -n +2 "$OUT_DIR/post-kernel-gpu.txt" 2>/dev/null || true
    cat "$OUT_DIR/kernel-follow.log" 2>/dev/null || true
} | rg -i 'data fabric|sync flood|NVRM: Xid|GPU has fallen off|hardware error|fatal' \
    >/dev/null 2>&1; then
    log "hardware-risk evidence found; inspect $OUT_DIR"
    exit 2
fi

log "complete: $OUT_DIR"
