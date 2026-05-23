#!/usr/bin/env bash
# Capture DarkPlaces window output to v4l2loopback device.
# Uses wf-recorder on Wayland or ffmpeg x11grab on X11.
set -euo pipefail

DEVICE="${DARKPLACES_V4L2_DEVICE:-/dev/video70}"
WIDTH="${DARKPLACES_WIDTH:-1280}"
HEIGHT="${DARKPLACES_HEIGHT:-720}"
FPS="${DARKPLACES_FPS:-30}"

if [ "$XDG_SESSION_TYPE" = "wayland" ]; then
    # Wayland: use wf-recorder to capture a specific window
    # First find the DarkPlaces window
    WINDOW_ID=$(swaymsg -t get_tree 2>/dev/null | jq -r '.. | select(.name? // "" | test("DarkPlaces|darkplaces"; "i")) | .id' | head -1 || true)

    if command -v wf-recorder &>/dev/null; then
        echo "Using wf-recorder for Wayland capture → $DEVICE"
        exec wf-recorder \
            --muxer=v4l2 \
            --file="$DEVICE" \
            --pixel-format yuv420p \
            -r "$FPS" \
            --geometry "0,0 ${WIDTH}x${HEIGHT}" \
            -c rawvideo
    else
        echo "wf-recorder not found. Falling back to ffmpeg pipewire capture."
        exec ffmpeg -hide_banner -loglevel warning \
            -f pipewire -framerate "$FPS" -video_size "${WIDTH}x${HEIGHT}" \
            -i "default" \
            -f v4l2 -pix_fmt yuv420p \
            "$DEVICE"
    fi
else
    # X11: use ffmpeg x11grab
    echo "Using ffmpeg x11grab → $DEVICE"
    exec ffmpeg -hide_banner -loglevel warning \
        -f x11grab -framerate "$FPS" -video_size "${WIDTH}x${HEIGHT}" \
        -i "${DISPLAY}+0,0" \
        -f v4l2 -pix_fmt yuv420p \
        "$DEVICE"
fi
