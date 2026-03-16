#!/bin/bash
# studio-fx-output.sh — Feed GPU-effected snapshots to /dev/video50
SNAPSHOT="/dev/shm/hapax-compositor/fx-snapshot.jpg"
DEVICE="/dev/video50"

[ -e "$DEVICE" ] || { echo "Device $DEVICE not found"; exit 1; }
while [ ! -f "$SNAPSHOT" ]; do sleep 1; done

echo "Starting FX output to $DEVICE"
exec ffmpeg -y -re \
  -f image2 -loop 1 -framerate 15 -i "$SNAPSHOT" \
  -f v4l2 -pix_fmt yuyv422 -video_size 1920x1080 \
  "$DEVICE"
