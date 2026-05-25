#!/usr/bin/env bash
# Run DarkPlaces headlessly under Xvfb and publish frames to v4l2loopback.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/darkplaces-runtime-guard.sh
source "$REPO_DIR/scripts/darkplaces-runtime-guard.sh"

DEVICE="${HAPAX_DARKPLACES_V4L2_DEVICE:-${DARKPLACES_V4L2_DEVICE:-/dev/video52}}"
WIDTH="${DARKPLACES_WIDTH:-1920}"
HEIGHT="${DARKPLACES_HEIGHT:-1080}"
FPS="${DARKPLACES_FPS:-60}"
DISPLAY_NUM="${HAPAX_DARKPLACES_DISPLAY:-:82}"
PORT="${DARKPLACES_PORT:-26001}"
JOY_INDEX="${HAPAX_DARKPLACES_JOY_INDEX:-1}"
PROBE_ONLY=0

usage() {
    cat <<'EOF'
Usage: scripts/darkplaces-v4l2-xvfb.sh [--probe-only]

Starts an Xvfb display, validates the DarkPlaces GL renderer on that display,
then launches DarkPlaces and x11grab -> v4l2. This fallback avoids root Xorg
and desktop DRM hotplug churn. It is not the GPU-pinned production route.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --probe-only)
            PROBE_ONLY=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "darkplaces-v4l2-xvfb: unknown argument: $1" >&2
            usage >&2
            exit 64
            ;;
    esac
    shift
done

need_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "darkplaces-v4l2-xvfb: missing required command: $1" >&2
        exit 69
    fi
}

need_cmd Xvfb
need_cmd darkplaces-sdl
need_cmd ffmpeg
need_cmd v4l2-ctl
if [ -n "${NOTIFY_SOCKET:-}" ]; then
    need_cmd systemd-notify
fi

if [ "$PROBE_ONLY" -ne 1 ] && [ ! -e "$DEVICE" ]; then
    echo "DarkPlaces v4l2loopback device not found: $DEVICE" >&2
    exit 1
fi

xvfb_pid=""
darkplaces_pid=""
ffmpeg_pid=""
watchdog_pid=""

notify_systemd() {
    if [ -n "${NOTIFY_SOCKET:-}" ] && command -v systemd-notify >/dev/null 2>&1; then
        systemd-notify "$@" >/dev/null 2>&1 || true
    fi
}

start_systemd_watchdog() {
    if [ -z "${NOTIFY_SOCKET:-}" ] || ! command -v systemd-notify >/dev/null 2>&1; then
        return
    fi
    (
        while true; do
            sleep "${HAPAX_DARKPLACES_WATCHDOG_INTERVAL_SECONDS:-10}"
            if [ -n "$darkplaces_pid" ] && kill -0 "$darkplaces_pid" 2>/dev/null &&
                [ -n "$ffmpeg_pid" ] && kill -0 "$ffmpeg_pid" 2>/dev/null; then
                systemd-notify \
                    "WATCHDOG=1" \
                    "STATUS=DarkPlaces v4l2 feed alive: ${DISPLAY_NUM}.0 -> ${DEVICE}" \
                    >/dev/null 2>&1 || true
            else
                break
            fi
        done
    ) &
    watchdog_pid="$!"
}

cleanup() {
    for pid in "$watchdog_pid" "$ffmpeg_pid" "$darkplaces_pid" "$xvfb_pid"; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
}
trap cleanup EXIT INT TERM

Xvfb "$DISPLAY_NUM" -screen 0 "${WIDTH}x${HEIGHT}x24" -nolisten tcp -s 0 -dpms &
xvfb_pid="$!"
sleep 1

if [ -z "${HAPAX_DARKPLACES_EXPECTED_GL_RENDERER:-}" ] &&
    [ -z "${HAPAX_DARKPLACES_EXPECTED_GPU_INDEX:-}" ]; then
    export HAPAX_DARKPLACES_EXPECTED_GPU_INDEX=0
fi
DISPLAY="$DISPLAY_NUM" "$REPO_DIR/scripts/darkplaces-gl-preflight.sh"

if [ "$PROBE_ONLY" -eq 1 ]; then
    echo "darkplaces-v4l2-xvfb: probe-only complete" >&2
    exit 0
fi

"$REPO_DIR/scripts/install-darkplaces-screwm-assets.sh"

DISPLAY="$DISPLAY_NUM" SDL_VIDEODRIVER=x11 darkplaces-sdl \
    -game screwm \
    -window \
    -width "$WIDTH" \
    -height "$HEIGHT" \
    +map screwm \
    +port "$PORT" \
    +crosshair 0 \
    +r_drawviewmodel 0 \
    +viewsize 120 \
    +scr_viewsize 120 \
    +cl_bob 0 \
    +scr_centertime 0 \
    +scr_sbaralpha 0 \
    +sbar_alpha_bg 0 \
    +sbar_alpha_fg 0 \
    +sbar_hudselector 0 \
    +sbar_x 10000 \
    +sbar_y 10000 \
    +scr_infobar_height 0 \
    +scr_infobartime_off 0 \
    +scr_showbrand 0 \
    +sv_cheats 1 \
    +gl_texturemode GL_NEAREST \
    +r_fog 1 \
    +cl_maxfps "$FPS" \
    +showfps 0 \
    +cl_showfps 0 \
    +cl_showtime 0 \
    +cl_showdate 0 \
    +cl_showspeed 0 \
    +cl_shownet 0 \
    +scr_showturtle 0 \
    +joy_enable 1 \
    +joy_index "$JOY_INDEX" \
    +joy_axisforward 1 \
    +joy_axisside 0 \
    +joy_axisyaw 3 \
    +joy_axispitch 4 \
    +joy_axisup -1 \
    +joy_sensitivityforward -1 \
    +joy_sensitivityside 1 \
    +joy_sensitivityyaw 1.15 \
    +joy_sensitivitypitch 0.90 \
    +joy_deadzoneforward 0.12 \
    +joy_deadzoneside 0.12 \
    +joy_deadzoneyaw 0.14 \
    +joy_deadzonepitch 0.14 \
    +cl_forwardspeed 360 \
    +cl_backspeed 360 \
    +cl_sidespeed 360 \
    +cl_upspeed 240 &
darkplaces_pid="$!"

sleep 3

v4l2-ctl -d "$DEVICE" --set-fmt-video="width=${WIDTH},height=${HEIGHT},pixelformat=YUYV" \
    >/dev/null 2>&1 || true

ffmpeg -hide_banner -loglevel warning -nostdin \
    -f x11grab \
    -video_size "${WIDTH}x${HEIGHT}" \
    -framerate "$FPS" \
    -i "${DISPLAY_NUM}.0+0,0" \
    -vf "format=yuyv422" \
    -f v4l2 \
    "$DEVICE" &
ffmpeg_pid="$!"

notify_systemd --ready --status="DarkPlaces v4l2 feed running: ${DISPLAY_NUM}.0 -> ${DEVICE}"
start_systemd_watchdog

wait -n "$darkplaces_pid" "$ffmpeg_pid"
