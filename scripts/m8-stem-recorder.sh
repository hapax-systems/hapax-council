#!/usr/bin/env bash
# m8-stem-recorder.sh — always-on M8 USB-audio capture to FLAC.
#
# Taps the M8's USB Audio Class source via parec (PipeWire's PulseAudio-
# compat client) and pipes raw signed 24-bit / 44.1 kHz / 2-channel PCM
# into sox, which encodes lossless FLAC into a per-day rotating file at
# /var/lib/hapax/m8-stems/YYYY-MM-DD.flac.
#
# Day rotation: at UTC midnight the script's parec/sox pipeline closes
# the current file and opens a new one. The systemd service restarts
# the script with `Restart=on-failure` so a failed pipeline (M8 unplug,
# transient PipeWire reconfigure) recovers cleanly.
#
# Why parec, not pw-cat: parec on PipeWire negotiates 24-bit signed LE
# transparently with the M8 source whose native USB UAC depth is
# 24-bit; pw-cat's --format=s24 path occasionally upsamples surprisingly
# on driver edge cases. parec is also tied to the existing
# wireplumber rule 54-hapax-m8-instrument.conf which holds the M8
# source's friendly name stable.
#
# Why not a pipewire-link sink: keeping the recorder side-by-side with
# the loudnorm consumer avoids any risk of the recorder back-pressuring
# the broadcast chain. parec is a parallel reader; it doesn't compete
# with the loopback that feeds hapax-m8-loudnorm.
#
# cc-task: m8-stem-archive-recorder

set -euo pipefail

readonly STEM_DIR="${HAPAX_M8_STEM_DIR:-/var/lib/hapax/m8-stems}"
readonly SOURCE_REGEX="${HAPAX_M8_SOURCE_REGEX:-alsa_input.usb-Dirtywave_M8_.*\.analog-stereo}"

mkdir -p "${STEM_DIR}"

# Resolve the M8 source via the regex (handles serial-suffixed names).
M8_SOURCE="$(pactl list short sources | awk '{print $2}' | grep -E "${SOURCE_REGEX}" | head -1 || true)"
if [ -z "${M8_SOURCE}" ]; then
    echo "m8-stem-recorder: no M8 USB audio source found matching ${SOURCE_REGEX}" >&2
    exit 1
fi

# Day-rotation: capture in 1h chunks aligned to UTC; sox concats trivially
# at retention sweep time if needed. Simpler implementation: spawn a sox
# encoder per UTC day, so each file is exactly one day. We use the
# `% --rotate` trick by re-spawning at midnight via a loop.
while true; do
    DATE_STAMP="$(date -u +%F)"
    OUT_FILE="${STEM_DIR}/${DATE_STAMP}.flac"
    SECONDS_TO_NEXT_DAY="$(( $(date -u -d 'tomorrow 00:00:00' +%s) - $(date -u +%s) ))"

    echo "m8-stem-recorder: writing ${OUT_FILE} for ${SECONDS_TO_NEXT_DAY}s" >&2

    # If the file exists (script restarted mid-day), append by re-encoding;
    # for simplicity we instead start a new file with a -mid suffix and
    # rely on the day-rolled chronicle event tracking the segments.
    if [ -e "${OUT_FILE}" ]; then
        OUT_FILE="${STEM_DIR}/${DATE_STAMP}-$(date -u +%H%M%S).flac"
    fi

    # parec → sox: raw signed 24-bit LE / 44.1k / stereo into FLAC.
    # `timeout` ensures the pipeline tears down at the day boundary,
    # the outer loop then opens the next file.
    timeout --preserve-status "${SECONDS_TO_NEXT_DAY}s" \
        parec --device="${M8_SOURCE}" \
              --format=s24le --rate=44100 --channels=2 \
              --raw \
        | sox -t raw -e signed -b 24 -r 44100 -c 2 - \
              -t flac -C 5 "${OUT_FILE}"

    # If the inner pipeline failed (non-day-boundary exit), surface it.
    rc=$?
    if [ "${rc}" -ne 0 ] && [ "${rc}" -ne 124 ]; then
        # 124 is timeout's clean kill; anything else is real failure.
        echo "m8-stem-recorder: pipeline exited rc=${rc}" >&2
        exit "${rc}"
    fi
done
