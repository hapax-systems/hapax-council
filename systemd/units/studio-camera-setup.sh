#!/bin/bash
# studio-camera-setup.sh — Apply optimized v4l2 settings to all studio cameras.
# Called by studio-compositor.service ExecStartPre before the pipeline starts.
# Settings persist only while USB devices are enumerated (reset on reboot/replug).

set -euo pipefail

V4L2=/usr/bin/v4l2-ctl
# Per-call timeout: a USB device in a bad state (kernel -110 / device
# descriptor read errors) can make v4l2-ctl block on the ioctl
# indefinitely, which hangs ExecStartPre and forces systemd to kill
# the entire compositor service after TimeoutStartSec. 5s is generous
# for a normally-responding camera.
V4L2_TIMEOUT=5

LOG="${XDG_RUNTIME_DIR:-/tmp}/studio-camera-setup.log"
: > "$LOG"  # truncate

# Non-fatal v4l2-ctl wrapper: logs failures to $LOG, continues on error,
# and bounds the call with a hard timeout so a wedged USB device cannot
# block compositor startup.
v4l2_soft() {
    local dev="$1"
    shift
    if ! timeout "$V4L2_TIMEOUT" "$V4L2" -d "$dev" "$@" 2>>"$LOG"; then
        echo "[$(date +%H:%M:%S)] WARNING: v4l2-ctl -d $dev $* returned non-zero" >>"$LOG"
    fi
}

# Shared: manual exposure, 60Hz flicker filter, manual WB at 4800K, no backlight comp
SHARED="auto_exposure=1,exposure_dynamic_framerate=0,power_line_frequency=2"
SHARED="$SHARED,white_balance_automatic=0,white_balance_temperature=4800"
SHARED="$SHARED,backlight_compensation=0,brightness=128,contrast=128,saturation=128"

# --- BRIO (hero/operator) — 720p MJPEG, larger sensor, low gain ---
DEV=/dev/v4l/by-id/usb-046d_Logitech_BRIO_5342C819-video-index0
if [ -e "$DEV" ]; then
  v4l2_soft "$DEV" --set-ctrl="$SHARED,gain=80,exposure_time_absolute=333,sharpness=128"
  v4l2_soft "$DEV" --set-ctrl=focus_automatic_continuous=0,focus_absolute=0
  echo "brio-operator: configured (sharpness=128, exposure=333)"
fi

# --- C920-desk (high angle monitors/desk) — lower gain, infinity focus ---
DEV=/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_2657DFCF-video-index0
if [ -e "$DEV" ]; then
  v4l2_soft "$DEV" --set-ctrl="$SHARED,gain=140,exposure_time_absolute=333,sharpness=110"
  v4l2_soft "$DEV" --set-ctrl=focus_automatic_continuous=0,focus_absolute=0
  echo "c920-desk: configured (gain=140, exposure=333, sharpness=110)"
fi

# --- C920-room (wide room view) ---
DEV=/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_86B6B75F-video-index0
if [ -e "$DEV" ]; then
  v4l2_soft "$DEV" --set-ctrl="$SHARED,gain=140,exposure_time_absolute=333,sharpness=110"
  v4l2_soft "$DEV" --set-ctrl=focus_automatic_continuous=0,focus_absolute=30
  echo "c920-room: configured (gain=140, exposure=333, sharpness=110)"
fi

# --- C920-overhead (top-down over operator) ---
DEV=/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_7B88C71F-video-index0
if [ -e "$DEV" ]; then
  v4l2_soft "$DEV" --set-ctrl="$SHARED,gain=140,exposure_time_absolute=333,sharpness=110"
  v4l2_soft "$DEV" --set-ctrl=focus_automatic_continuous=0,focus_absolute=30
  echo "c920-overhead: configured (gain=140, exposure=333, sharpness=110)"
fi

# --- BRIO-room (full room view, 720p MJPEG) ---
DEV=/dev/v4l/by-id/usb-046d_Logitech_BRIO_43B0576A-video-index0
if [ -e "$DEV" ]; then
  v4l2_soft "$DEV" --set-ctrl="$SHARED,gain=80,exposure_time_absolute=333,sharpness=128"
  v4l2_soft "$DEV" --set-ctrl=focus_automatic_continuous=0,focus_absolute=0
  echo "brio-room: configured (sharpness=128, exposure=333)"
fi

# --- BRIO-synths (overhead synth corner, 720p MJPEG) ---
DEV=/dev/v4l/by-id/usb-046d_Logitech_BRIO_9726C031-video-index0
if [ -e "$DEV" ]; then
  v4l2_soft "$DEV" --set-ctrl="$SHARED,gain=80,exposure_time_absolute=333,sharpness=128"
  v4l2_soft "$DEV" --set-ctrl=focus_automatic_continuous=0,focus_absolute=0
  echo "brio-synths: configured (sharpness=128, exposure=333)"
fi
