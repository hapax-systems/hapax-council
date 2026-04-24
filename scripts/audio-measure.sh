#!/usr/bin/env bash
# audio-measure.sh — operator-runnable broadcast loudness check.
#
# Taps `hapax-broadcast-normalized.monitor` (the master output OBS reads)
# for a configurable duration, runs ffmpeg ebur128, and prints integrated
# LUFS-I, true-peak, and LRA. Used to verify Phase 1 acceptance criteria
# and as a manual diagnostic tool until Phase 7 ships the live dashboard.
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
SAMPLE_FMT=s16le

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

CAPTURE="$TMPDIR/capture.raw"
EBUR128_LOG="$TMPDIR/ebur128.log"

echo "Capturing ${DURATION}s from ${NODE}..." >&2
if ! timeout "$((DURATION + 5))" pw-cat \
        --record "$CAPTURE" \
        --target "${NODE}.monitor" \
        --rate "$SAMPLE_RATE" \
        --format "$SAMPLE_FMT" \
        --channels "$CHANNELS" \
        --raw \
        &>/dev/null &
then
    echo "ERROR: pw-cat failed to launch" >&2
    exit 1
fi
PWPID=$!
sleep "$DURATION"
kill "$PWPID" 2>/dev/null || true
wait "$PWPID" 2>/dev/null || true

if [ ! -s "$CAPTURE" ]; then
    echo "ERROR: capture is empty (${NODE}.monitor not producing audio?)" >&2
    exit 1
fi

echo "Analyzing with ffmpeg ebur128..." >&2
if ! ffmpeg -hide_banner -nostats -loglevel info \
        -f "$SAMPLE_FMT" -ar "$SAMPLE_RATE" -ac "$CHANNELS" -i "$CAPTURE" \
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
echo "  Source: ${NODE}.monitor"
echo "  Window: ${DURATION}s"
echo "═══════════════════════════════════════════════════════════════"
sed -n "${SUMMARY_LINE},\$p" "$EBUR128_LOG" | grep -E '(I:|LRA:|Peak:|Threshold:)' | sed 's/^/  /'
echo "═══════════════════════════════════════════════════════════════"
echo
echo "Targets per shared/audio_loudness.py:"
echo "  EGRESS_TARGET_LUFS_I  = -14.0  (acceptable range -16..-12)"
echo "  EGRESS_TRUE_PEAK_DBTP = -1.0   (Phase 1: alert if Peak > -0.5)"
echo
