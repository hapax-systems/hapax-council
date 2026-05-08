#!/usr/bin/env bash
# install-v4l2loopback-config.sh — deploy tracked v4l2loopback modprobe config
#
# Copies config/modprobe.d/v4l2loopback-hapax.conf to /etc/modprobe.d/
# and optionally reloads the kernel module. Module reload disconnects ALL
# v4l2loopback consumers (OBS, compositor, ffmpeg RTSP ingest), so it
# defaults to --no-reload. Pass --reload to force, or reboot instead.
#
# Usage:
#   scripts/install-v4l2loopback-config.sh [--reload]

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${REPO_DIR}/config/modprobe.d/v4l2loopback-hapax.conf"
DST="/etc/modprobe.d/v4l2loopback-hapax.conf"

if [[ ! -f "$SRC" ]]; then
    echo "error: source config not found: $SRC" >&2
    exit 1
fi

do_reload=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --reload) do_reload=true; shift ;;
        *) echo "usage: install-v4l2loopback-config.sh [--reload]" >&2; exit 2 ;;
    esac
done

echo "installing: $SRC → $DST"
sudo cp -f "$SRC" "$DST"
sudo chmod 644 "$DST"

diff -u "$DST" "$SRC" && echo "  config matches (no drift)" || echo "  warning: installed config differs from repo"

if $do_reload; then
    echo "reloading v4l2loopback module (this disconnects ALL consumers)..."
    refcount=$(awk '/^v4l2loopback/ {print $3}' /proc/modules 2>/dev/null || echo "?")
    if [[ "$refcount" != "0" && "$refcount" != "?" ]]; then
        echo "  module has $refcount active users — stopping services first"
        systemctl --user stop hapax-studio-compositor 2>/dev/null || true
        sleep 2
        refcount=$(awk '/^v4l2loopback/ {print $3}' /proc/modules 2>/dev/null || echo "?")
        if [[ "$refcount" != "0" ]]; then
            echo "  still $refcount users — module reload may fail (try reboot instead)" >&2
        fi
    fi
    sudo modprobe -r v4l2loopback && sudo modprobe v4l2loopback
    echo "  module reloaded"
    ls -la /dev/video42 /dev/video10 2>/dev/null
    cat /sys/module/v4l2loopback/parameters/exclusive_caps 2>/dev/null && echo "  ^ exclusive_caps parameter"
else
    echo "skipping module reload (pass --reload to force, or reboot)"
    echo "after reboot, verify: cat /sys/module/v4l2loopback/parameters/exclusive_caps"
fi
