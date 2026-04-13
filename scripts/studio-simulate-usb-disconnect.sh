#!/usr/bin/env bash
# Simulate a USB camera disconnect via USBDEVFS_RESET.
# Phase 6 of the camera 24/7 resilience epic.
#
# Usage:
#   studio-simulate-usb-disconnect.sh <role>
#   studio-simulate-usb-disconnect.sh brio-operator
#
# Looks up the /dev/v4l/by-id/ symlink for the given role, resolves it to
# the underlying USB bus/dev, and runs a `usbreset` ioctl via a small Python
# helper. This simulates most but not all USB failure modes (VBUS cut
# requires physical hardware; USBDEVFS_RESET covers link-level stalls and
# uvcvideo hangs).
#
# See docs/superpowers/specs/2026-04-12-camera-recovery-state-machine-design.md
set -euo pipefail

ROLE="${1:-}"
if [[ -z "$ROLE" ]]; then
    echo "usage: $0 <role>" >&2
    echo "  roles: brio-operator brio-room brio-synths c920-desk c920-room c920-overhead" >&2
    exit 1
fi

# Map role to by-id path (mirrors studio_compositor/config.py)
case "$ROLE" in
    brio-operator) DEV=/dev/v4l/by-id/usb-046d_Logitech_BRIO_5342C819-video-index0 ;;
    brio-room)     DEV=/dev/v4l/by-id/usb-046d_Logitech_BRIO_43B0576A-video-index0 ;;
    brio-synths)   DEV=/dev/v4l/by-id/usb-046d_Logitech_BRIO_9726C031-video-index0 ;;
    c920-desk)     DEV=/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_2657DFCF-video-index0 ;;
    c920-room)     DEV=/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_86B6B75F-video-index0 ;;
    c920-overhead) DEV=/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_7B88C71F-video-index0 ;;
    *)
        echo "unknown role: $ROLE" >&2
        exit 1
        ;;
esac

if [[ ! -e "$DEV" ]]; then
    echo "ERROR: $DEV not present (camera offline already?)" >&2
    exit 1
fi

# Resolve the symlink to a /dev/videoN
VIDEO_NODE=$(readlink -f "$DEV")
echo "device node: $VIDEO_NODE"

# Find the USB bus/dev via sysfs parent walk.
#
# `udevadm info --query=property --name=/dev/videoN` does NOT expose
# BUSNUM / DEVNUM on a video4linux node — those live on the parent USB
# device (.../usbN/N-P/), not on the child v4l interface
# (.../usbN/N-P/N-P:1.0/video4linux/videoN/). Walk up the sysfs path
# until we hit the first directory carrying busnum + devnum files —
# that's the USB device node the USBDEVFS_RESET ioctl targets.
SYSFS_SUBPATH=$(udevadm info --query=path --name="$VIDEO_NODE" 2>/dev/null)
if [[ -z "$SYSFS_SUBPATH" ]]; then
    echo "ERROR: could not resolve sysfs path for $VIDEO_NODE" >&2
    exit 1
fi

BUSNUM=""
DEVNUM=""
usb_sysfs="/sys$SYSFS_SUBPATH"
while [[ -n "$usb_sysfs" && "$usb_sysfs" != "/sys" && "$usb_sysfs" != "/" ]]; do
    if [[ -f "$usb_sysfs/busnum" && -f "$usb_sysfs/devnum" ]]; then
        BUSNUM=$(cat "$usb_sysfs/busnum")
        DEVNUM=$(cat "$usb_sysfs/devnum")
        break
    fi
    usb_sysfs=$(dirname "$usb_sysfs")
done

if [[ -z "$BUSNUM" || -z "$DEVNUM" ]]; then
    echo "ERROR: could not locate parent USB device in sysfs for $VIDEO_NODE" >&2
    exit 1
fi
echo "usb sysfs: $usb_sysfs"

# /dev/bus/usb/ uses zero-padded 3-digit bus + device numbers
# (e.g. /dev/bus/usb/008/002), but the sysfs `busnum` / `devnum`
# files carry the raw integers. Pad explicitly.
USB_NODE=$(printf "/dev/bus/usb/%03d/%03d" "$BUSNUM" "$DEVNUM")
echo "USB node: $USB_NODE"

if [[ ! -e "$USB_NODE" ]]; then
    echo "ERROR: $USB_NODE not present" >&2
    exit 1
fi

# Run the USBDEVFS_RESET ioctl via a Python one-liner.
# USBDEVFS_RESET = _IO('U', 20) = 0x5514
python3 <<PYEOF
import fcntl, sys
USBDEVFS_RESET = 0x5514
try:
    with open("$USB_NODE", "wb") as fd:
        fcntl.ioctl(fd.fileno(), USBDEVFS_RESET, 0)
    print("USBDEVFS_RESET ioctl: ok")
except PermissionError:
    print("USBDEVFS_RESET ioctl: need root (try: sudo $0 $ROLE)", file=sys.stderr)
    sys.exit(2)
except OSError as exc:
    print(f"USBDEVFS_RESET ioctl: {exc}", file=sys.stderr)
    sys.exit(3)
PYEOF

echo "reset issued for role=$ROLE (node=$VIDEO_NODE usb=$USB_NODE)"
