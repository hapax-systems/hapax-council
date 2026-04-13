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

# Find the USB bus/dev via udevadm — more reliable than walking sysfs.
BUSNUM=$(udevadm info --query=property --name="$VIDEO_NODE" 2>/dev/null | awk -F= '/^BUSNUM=/ {print $2}')
DEVNUM=$(udevadm info --query=property --name="$VIDEO_NODE" 2>/dev/null | awk -F= '/^DEVNUM=/ {print $2}')

if [[ -z "$BUSNUM" || -z "$DEVNUM" ]]; then
    echo "ERROR: could not resolve USB bus/dev for $VIDEO_NODE" >&2
    exit 1
fi

USB_NODE="/dev/bus/usb/$BUSNUM/$DEVNUM"
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
