#!/usr/bin/env bash
# Publish the DarkPlaces X11 framebuffer as a low-latency OBS ffmpeg source.
set -euo pipefail

DISPLAY_NUM="${HAPAX_DARKPLACES_DISPLAY:-:82}"
WIDTH="${DARKPLACES_WIDTH:-1920}"
HEIGHT="${DARKPLACES_HEIGHT:-1080}"
FPS="${DARKPLACES_FPS:-30}"
OUTPUT_URL="${HAPAX_DARKPLACES_OBS_MEDIA_OUTPUT_URL:-udp://127.0.0.1:30552?pkt_size=1316}"
BITRATE="${HAPAX_DARKPLACES_OBS_MEDIA_BITRATE:-12000k}"
MAXRATE="${HAPAX_DARKPLACES_OBS_MEDIA_MAXRATE:-16000k}"
BUFSIZE="${HAPAX_DARKPLACES_OBS_MEDIA_BUFSIZE:-1000k}"
PRESET="${HAPAX_DARKPLACES_OBS_MEDIA_PRESET:-ultrafast}"
WAIT_SECONDS="${HAPAX_DARKPLACES_OBS_MEDIA_WAIT_SECONDS:-45}"

need_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "darkplaces-obs-media-stream: missing required command: $1" >&2
        exit 69
    fi
}

display_socket_path() {
    local display_number="${DISPLAY_NUM%%.*}"
    display_number="${display_number#:}"
    printf '/tmp/.X11-unix/X%s\n' "$display_number"
}

wait_for_display() {
    local socket_path
    socket_path="$(display_socket_path)"
    local deadline=$((SECONDS + WAIT_SECONDS))
    while [ "$SECONDS" -le "$deadline" ]; do
        if [ -S "$socket_path" ]; then
            return
        fi
        sleep 0.25
    done
    echo "darkplaces-obs-media-stream: timed out waiting for X11 display socket: $socket_path" >&2
    exit 1
}

need_cmd ffmpeg
wait_for_display

exec ffmpeg -hide_banner -loglevel warning -nostdin \
    -f x11grab \
    -draw_mouse 0 \
    -video_size "${WIDTH}x${HEIGHT}" \
    -framerate "$FPS" \
    -i "${DISPLAY_NUM}.0+0,0" \
    -vf "format=yuv420p" \
    -c:v libx264 \
    -preset "$PRESET" \
    -tune zerolatency \
    -g "$FPS" \
    -bf 0 \
    -b:v "$BITRATE" \
    -maxrate "$MAXRATE" \
    -bufsize "$BUFSIZE" \
    -x264-params "repeat-headers=1:keyint=${FPS}:min-keyint=${FPS}:scenecut=0" \
    -f mpegts \
    "$OUTPUT_URL"
