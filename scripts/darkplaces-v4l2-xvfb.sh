#!/usr/bin/env bash
# Run DarkPlaces headlessly under Xvfb and publish frames to v4l2loopback.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$REPO_DIR/scripts/darkplaces-runtime-guard.sh"

DEVICE="${HAPAX_DARKPLACES_V4L2_DEVICE:-${DARKPLACES_V4L2_DEVICE:-/dev/video52}}"
WIDTH="${DARKPLACES_WIDTH:-1280}"
HEIGHT="${DARKPLACES_HEIGHT:-720}"
FPS="${DARKPLACES_FPS:-30}"
DISPLAY_NUM="${HAPAX_DARKPLACES_DISPLAY:-:82}"
PORT="${DARKPLACES_PORT:-26001}"

if [ ! -e "$DEVICE" ]; then
    echo "DarkPlaces v4l2loopback device not found: $DEVICE" >&2
    exit 1
fi

"$REPO_DIR/scripts/install-darkplaces-screwm-assets.sh"

xvfb_pid=""
darkplaces_pid=""
ffmpeg_pid=""

cleanup() {
    for pid in "$ffmpeg_pid" "$darkplaces_pid" "$xvfb_pid"; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
}
trap cleanup EXIT INT TERM

Xvfb "$DISPLAY_NUM" -screen 0 "${WIDTH}x${HEIGHT}x24" -nolisten tcp &
xvfb_pid="$!"
sleep 1

DISPLAY="$DISPLAY_NUM" SDL_VIDEODRIVER=x11 darkplaces-sdl \
    -game screwm \
    -window \
    -width "$WIDTH" \
    -height "$HEIGHT" \
    +map screwm \
    +port "$PORT" \
    +crosshair 0 \
    +r_drawviewmodel 0 \
    +cl_bob 0 \
    +sbar_alpha 0 \
    +sv_cheats 1 \
    +gl_texturemode GL_NEAREST \
    +r_fog 1 \
    +cl_maxfps "$FPS" \
    +showfps 0 \
    +scr_showturtle 0 &
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

wait -n "$darkplaces_pid" "$ffmpeg_pid"
