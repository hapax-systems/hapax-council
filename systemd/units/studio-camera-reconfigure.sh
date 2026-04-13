#!/usr/bin/env bash
# Reconfigure a studio camera device after USB re-enumeration.
# Argument: kernel device name (e.g. "video0").
#
# Triggered by udev via the studio-camera-reconfigure@<name>.service template
# unit. Runs as the user who owns the systemd instance (via
# ENV{SYSTEMD_USER_WANTS} in 70-studio-cameras.rules). Applies camera-model-
# specific v4l2-ctl settings to the newly-enumerated device node so that
# when the compositor's PipelineManager supervisor thread rebuilds the
# producer pipeline, the device is already configured.
#
# Phase 3 of the camera 24/7 resilience epic.

set -euo pipefail

DEV="/dev/${1:-}"
if [[ -z "${1:-}" ]]; then
    logger -t studio-camera-reconfigure "no device name argument"
    exit 0
fi
if [[ ! -e "$DEV" ]]; then
    logger -t studio-camera-reconfigure "device $DEV does not exist; aborting"
    exit 0
fi

LOG="${XDG_RUNTIME_DIR:-/tmp}/studio-camera-reconfigure.log"
V4L2=/usr/bin/v4l2-ctl

# Shared baseline (same as studio-camera-setup.sh)
SHARED="auto_exposure=1,exposure_dynamic_framerate=0,power_line_frequency=2"
SHARED="$SHARED,white_balance_automatic=0,white_balance_temperature=4800"
SHARED="$SHARED,backlight_compensation=0,brightness=128,contrast=128,saturation=128"

# Identify camera model from the v4l2 info output
CARD=""
if CARD_RAW=$($V4L2 --device "$DEV" --info 2>>"$LOG"); then
    CARD=$(echo "$CARD_RAW" | awk -F: '/Card type/ {print $2}' | xargs)
fi

case "$CARD" in
    *BRIO*)
        logger -t studio-camera-reconfigure "reconfiguring BRIO at $DEV"
        $V4L2 -d "$DEV" --set-ctrl="$SHARED,gain=80,exposure_time_absolute=333,sharpness=128" >>"$LOG" 2>&1 || true
        $V4L2 -d "$DEV" --set-ctrl=focus_automatic_continuous=0,focus_absolute=0 >>"$LOG" 2>&1 || true
        ;;
    *C920*)
        logger -t studio-camera-reconfigure "reconfiguring C920 at $DEV"
        $V4L2 -d "$DEV" --set-ctrl="$SHARED,gain=140,exposure_time_absolute=333,sharpness=110" >>"$LOG" 2>&1 || true
        $V4L2 -d "$DEV" --set-ctrl=focus_automatic_continuous=0,focus_absolute=0 >>"$LOG" 2>&1 || true
        ;;
    "")
        logger -t studio-camera-reconfigure "no Card type from v4l2-ctl --info on $DEV"
        ;;
    *)
        logger -t studio-camera-reconfigure "unknown card at $DEV: $CARD"
        ;;
esac
