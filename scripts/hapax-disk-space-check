#!/usr/bin/env bash
# Disk space monitor — alerts at 85% and 95%.
set -euo pipefail

USE_PCT=$(df --output=pcent / | tail -1 | tr -d " %")
AVAIL=$(df -h --output=avail / | tail -1 | tr -d " ")

if [ "$USE_PCT" -gt 95 ]; then
    notify-send -u critical "Disk CRITICAL" "Root at ${USE_PCT}% (${AVAIL} free) — immediate action needed" 2>/dev/null || true
    logger -t disk-space "CRITICAL: root at ${USE_PCT}% (${AVAIL} free)"
elif [ "$USE_PCT" -gt 85 ]; then
    notify-send -u normal "Disk Warning" "Root at ${USE_PCT}% (${AVAIL} free)" 2>/dev/null || true
    logger -t disk-space "WARNING: root at ${USE_PCT}% (${AVAIL} free)"
fi
