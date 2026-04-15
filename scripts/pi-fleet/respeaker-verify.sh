#!/usr/bin/env bash
# respeaker-verify.sh — smoke test for ReSpeaker USB Mic Array v2.0 on hapax-ai
# Run after Friday unbox + plug-in. Does not modify anything; pure verification.
# Pre-staged 2026-04-15 (epsilon) for Friday 2026-04-17 arrival.
#
# Usage: bash respeaker-verify.sh

set -euo pipefail

echo "=== ReSpeaker USB Mic Array v2.0 — smoke test ==="
date

echo
echo "--- 1. USB enumeration ---"
if lsusb | grep -i "2886:0018\|ReSpeaker\|Seeed"; then
    echo "OK: ReSpeaker visible on USB bus"
else
    echo "FAIL: ReSpeaker not enumerated. Check: cable, USB port (prefer USB 3.0), dmesg tail."
    exit 1
fi

echo
echo "--- 2. udev symlink ---"
if [ -e /dev/respeaker-mic-array ]; then
    ls -l /dev/respeaker-mic-array
    echo "OK: /dev/respeaker-mic-array symlink present"
else
    echo "WARN: /dev/respeaker-mic-array symlink missing. Did you install 99-respeaker.rules + udevadm reload?"
fi

echo
echo "--- 3. ALSA enumeration ---"
if arecord -l | grep -i -A2 "ReSpeaker\|Seeed"; then
    echo "OK: ALSA sees the ReSpeaker capture device"
else
    echo "FAIL: arecord -l does not list ReSpeaker"
    exit 1
fi

echo
echo "--- 4. PipeWire enumeration ---"
if pactl list sources short | grep -i "respeaker\|seeed"; then
    echo "OK: PipeWire sees the ReSpeaker source"
else
    echo "WARN: PipeWire source not enumerated. Check: pipewire user service running, user in audio group."
fi

echo
echo "--- 5. Capture 1-second test ---"
TMPFILE=$(mktemp --suffix=.wav)
trap 'rm -f "$TMPFILE"' EXIT

if arecord -D plughw:$(arecord -l | awk '/ReSpeaker|Seeed/{print $2,$7}' | head -1 | tr -d '[:alpha:] :,') \
           -f S16_LE -r 16000 -c 1 -d 1 "$TMPFILE" 2>&1 | tail -5; then
    size=$(stat -c%s "$TMPFILE")
    echo "OK: captured $size bytes to $TMPFILE"
    # Peak level check (sox required)
    if command -v sox &>/dev/null; then
        peak=$(sox "$TMPFILE" -n stat 2>&1 | grep "Maximum amplitude" | awk '{print $NF}')
        echo "Peak amplitude: $peak (0.0 = silence, 1.0 = clipping; expect something in 0.01..0.5)"
    fi
else
    echo "FAIL: arecord capture failed"
    exit 1
fi

echo
echo "--- 6. ReSpeaker DSP channel layout ---"
# The ReSpeaker v2.0 presents 6 channels on its raw USB audio:
#   ch0: processed mono (post DSP: AEC + beamforming + noise suppression)
#   ch1-4: raw mic signals
#   ch5: playback reference (for AEC)
# For production use, only ch0 is what you want; ignore the rest.
echo "ReSpeaker v2.0 presents 6 channels:"
echo "  ch0: processed mono (USE THIS)"
echo "  ch1-4: raw per-mic signals"
echo "  ch5: playback reference for AEC"
echo
echo "Verify ch0 has signal:"
if command -v sox &>/dev/null; then
    arecord -D plughw:$(arecord -l | awk '/ReSpeaker|Seeed/{print $2,$7}' | head -1 | tr -d '[:alpha:] :,') \
            -f S16_LE -r 16000 -c 6 -d 1 /tmp/respeaker-6ch.wav 2>/dev/null || true
    if [ -f /tmp/respeaker-6ch.wav ]; then
        for c in 0 1 2 3 4 5; do
            peak=$(sox /tmp/respeaker-6ch.wav -n remix $((c+1)) stat 2>&1 | grep "Maximum amplitude" | awk '{print $NF}')
            echo "  ch${c} peak: ${peak}"
        done
    fi
    rm -f /tmp/respeaker-6ch.wav
fi

echo
echo "=== done ==="
echo "If all sections show OK, the ReSpeaker is hardware-healthy."
echo "Next: install respeaker-pipewire.conf and restart PipeWire user services."
