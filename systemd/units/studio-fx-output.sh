#!/bin/bash
# studio-fx-output.sh — Feed GPU-effected raw frames to /dev/video50
# Uses shmsrc to read from compositor's shared memory (zero-copy, no JPEG encode/decode)

SOCKET="/tmp/hapax-fx-shm"
DEVICE="/dev/video50"

[ -e "$DEVICE" ] || { echo "Device $DEVICE not found"; exit 1; }

# Wait for the shared memory socket
while [ ! -e "$SOCKET" ]; do sleep 1; done

echo "Starting FX output via shmsrc → $DEVICE"

exec gst-launch-1.0 \
  shmsrc socket-path="$SOCKET" is-live=true do-timestamp=true \
  ! "video/x-raw,format=RGBA,width=1920,height=1080,framerate=15/1" \
  ! videoconvert \
  ! "video/x-raw,format=YUY2" \
  ! v4l2sink device="$DEVICE" sync=false

# Fallback (ffmpeg shim, if shmsrc path is unavailable):
# SNAPSHOT="/dev/shm/hapax-compositor/fx-snapshot.jpg"
# exec ffmpeg -y -re \
#   -f image2 -loop 1 -framerate 15 -i "$SNAPSHOT" \
#   -f v4l2 -pix_fmt yuyv422 -video_size 1920x1080 \
#   "$DEVICE"
