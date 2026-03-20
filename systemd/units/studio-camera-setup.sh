#!/bin/bash
# studio-camera-setup.sh — Apply optimized v4l2 settings to all studio cameras.
# Called by studio-compositor.service ExecStartPre before the pipeline starts.
# Settings persist only while USB devices are enumerated (reset on reboot/replug).

set -euo pipefail

V4L2=/usr/bin/v4l2-ctl

# Shared: manual exposure, 60Hz flicker filter, manual WB at 4800K, no backlight comp
SHARED="auto_exposure=1,exposure_dynamic_framerate=0,power_line_frequency=2"
SHARED="$SHARED,white_balance_automatic=0,white_balance_temperature=4800"
SHARED="$SHARED,backlight_compensation=0,brightness=128,contrast=128,saturation=128"

# --- BRIO (hero/operator) — 1080p, larger sensor, low gain ---
DEV=/dev/v4l/by-id/usb-046d_Logitech_BRIO_5342C819-video-index0
if [ -e "$DEV" ]; then
  $V4L2 -d "$DEV" --set-ctrl="$SHARED,gain=80,exposure_time_absolute=333,sharpness=128"
  $V4L2 -d "$DEV" --set-ctrl=focus_automatic_continuous=0,focus_absolute=0
  echo "brio-operator: configured (sharpness=128, exposure=333)"
fi

# --- C920-hardware (faces monitors) — lower gain, infinity focus ---
DEV=/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_2657DFCF-video-index0
if [ -e "$DEV" ]; then
  $V4L2 -d "$DEV" --set-ctrl="$SHARED,gain=140,exposure_time_absolute=333,sharpness=110"
  $V4L2 -d "$DEV" --set-ctrl=focus_automatic_continuous=0,focus_absolute=0
  echo "c920-hardware: configured (gain=140, exposure=333, sharpness=110)"
fi

# --- C920-room (wide room view) ---
DEV=/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_86B6B75F-video-index0
if [ -e "$DEV" ]; then
  $V4L2 -d "$DEV" --set-ctrl="$SHARED,gain=140,exposure_time_absolute=333,sharpness=110"
  $V4L2 -d "$DEV" --set-ctrl=focus_automatic_continuous=0,focus_absolute=30
  echo "c920-room: configured (gain=140, exposure=333, sharpness=110)"
fi

# --- C920-aux (hardware close-up) ---
DEV=/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_7B88C71F-video-index0
if [ -e "$DEV" ]; then
  $V4L2 -d "$DEV" --set-ctrl="$SHARED,gain=140,exposure_time_absolute=333,sharpness=110"
  $V4L2 -d "$DEV" --set-ctrl=focus_automatic_continuous=0,focus_absolute=30
  echo "c920-aux: configured (gain=140, exposure=333, sharpness=110)"
fi
