#!/bin/bash
# Launch a dedicated terminal for stream coding + capture to v4l2 loopback
# The terminal has a unique app-id so wf-recorder always finds it

APPID="stream-code"
DEVICE="/dev/video10"
FPS=24
WORKSPACE=9  # dedicated workspace for stream coding

# Launch terminal with unique app-id on designated workspace
hyprctl dispatch workspace "$WORKSPACE"
foot --app-id="$APPID" --title="Legomena Code" &
TERM_PID=$!
sleep 1

# Move to designated workspace
hyprctl dispatch movetoworkspace "$WORKSPACE,class:$APPID"
sleep 0.5

# Get the window geometry
GEOM=$(hyprctl clients -j | jq -r ".[] | select(.class == \"$APPID\") | \"\(.at[0]),\(.at[1]) \(.size[0])x\(.size[1])\"" | head -1)

if [ -z "$GEOM" ]; then
    echo "Failed to find stream terminal window"
    kill $TERM_PID 2>/dev/null
    exit 1
fi

echo "Stream terminal: $APPID on workspace $WORKSPACE"
echo "Capturing: $GEOM → $DEVICE at ${FPS}fps"
echo "Stop: kill this script or Ctrl+C"

# Capture to v4l2 loopback
wf-recorder \
    --geometry "$GEOM" \
    --framerate "$FPS" \
    --codec rawvideo \
    --pixel-format yuv420p \
    --file "$DEVICE" \
    --no-dmabuf \
    -x yuv420p
