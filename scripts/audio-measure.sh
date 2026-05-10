#!/usr/bin/env bash
# audio-measure.sh — operator-runnable broadcast loudness check.
#
# Taps the requested PipeWire source for a configurable duration, runs ffmpeg
# ebur128, and prints integrated LUFS-I, true-peak, and LRA. If the requested
# node is not itself a source, the script falls back to its `.monitor` source.
# Used to verify Phase 1 acceptance criteria and as a manual diagnostic tool
# until Phase 7 ships the live dashboard.
#
# Usage:
#   audio-measure.sh                  # default 30 s
#   audio-measure.sh 60               # 60 s window
#   audio-measure.sh 30 hapax-broadcast-master   # measure a different node
#
# Exit codes:
#   0 = measurement succeeded
#   1 = ffmpeg or pw-cat failed
#   2 = arguments invalid

set -euo pipefail

DURATION="${1:-30}"
NODE="${2:-hapax-broadcast-normalized}"

if ! [[ "$DURATION" =~ ^[0-9]+$ ]] || [ "$DURATION" -lt 1 ] || [ "$DURATION" -gt 600 ]; then
    echo "ERROR: duration must be an integer 1..600 (seconds). Got: $DURATION" >&2
    exit 2
fi

SAMPLE_RATE=48000
CHANNELS=2
PWCAT_SAMPLE_FMT=s16
FFMPEG_SAMPLE_FMT=s16le

pipewire_source_exists() {
    if command -v pw-cli >/dev/null 2>&1; then
        pw-cli ls Node 2>/dev/null | awk -v want="$1" '
            /^id / {
                if (name == want && class == "Audio/Source") {
                    found = 1
                }
                name = ""
                class = ""
            }
            /node.name = / {
                name = $0
                sub(/.*node.name = "/, "", name)
                sub(/".*/, "", name)
            }
            /media.class = / {
                class = $0
                sub(/.*media.class = "/, "", class)
                sub(/".*/, "", class)
            }
            END {
                if (name == want && class == "Audio/Source") {
                    found = 1
                }
                exit found ? 0 : 1
            }
        ' && return 0
    fi

    command -v pactl >/dev/null 2>&1 || return 1
    pactl list short sources 2>/dev/null | awk '{print $2}' | grep -Fxq "$1"
}

TARGET="$NODE"
if [[ "$NODE" != *.monitor ]] && ! pipewire_source_exists "$NODE"; then
    TARGET="${NODE}.monitor"
fi

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

CAPTURE="$TMPDIR/capture.raw"
EBUR128_LOG="$TMPDIR/ebur128.log"

echo "Capturing ${DURATION}s from ${TARGET}..." >&2
timeout "$((DURATION + 5))" pw-cat \
    --record "$CAPTURE" \
    --target "$TARGET" \
    --rate "$SAMPLE_RATE" \
    --format "$PWCAT_SAMPLE_FMT" \
    --channels "$CHANNELS" \
    --raw \
    &>/dev/null &
PWPID=$!
sleep "$DURATION"
kill "$PWPID" 2>/dev/null || true
PWCAT_RC=0
wait "$PWPID" 2>/dev/null || PWCAT_RC=$?

if [ ! -s "$CAPTURE" ]; then
    echo "ERROR: capture is empty (${TARGET} not producing audio? pw-cat rc=${PWCAT_RC})" >&2
    exit 1
fi

echo "Analyzing with ffmpeg ebur128..." >&2
if ! ffmpeg -hide_banner -nostats -loglevel info \
        -f "$FFMPEG_SAMPLE_FMT" -ar "$SAMPLE_RATE" -ac "$CHANNELS" -i "$CAPTURE" \
        -filter_complex "ebur128=peak=true:framelog=quiet" \
        -f null - 2>"$EBUR128_LOG"
then
    echo "ERROR: ffmpeg analysis failed" >&2
    cat "$EBUR128_LOG" >&2
    exit 1
fi

# Pull the summary block (between "Summary:" and EOF) from ffmpeg's log
SUMMARY_LINE=$(grep -n '^\[Parsed_ebur128' "$EBUR128_LOG" | tail -1 | cut -d: -f1)
if [ -z "$SUMMARY_LINE" ]; then
    echo "ERROR: ebur128 emitted no summary" >&2
    cat "$EBUR128_LOG" >&2
    exit 1
fi

echo
echo "═══════════════════════════════════════════════════════════════"
echo "  Hapax broadcast loudness measurement"
echo "  Source: ${TARGET}"
echo "  Window: ${DURATION}s"
echo "═══════════════════════════════════════════════════════════════"
sed -n "${SUMMARY_LINE},\$p" "$EBUR128_LOG" | grep -E '(I:|LRA:|Peak:|Threshold:)' | sed 's/^/  /'
echo "═══════════════════════════════════════════════════════════════"
echo
echo "Targets per shared/audio_loudness.py:"
echo "  EGRESS_TARGET_LUFS_I  = -14.0  (acceptable range -16..-12)"
echo "  EGRESS_TRUE_PEAK_DBTP = -1.0   (Phase 1: alert if Peak > -0.5)"
echo
