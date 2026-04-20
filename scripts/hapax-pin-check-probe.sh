#!/usr/bin/env bash
# hapax-pin-check-probe.sh — B5 / unified-audio Phase 5 wiring.
#
# Live-probe wrapper for the hapax-audio-topology pin-check CLI. Reads
# the Ryzen analog sink's runtime state via pactl + computes the
# monitor RMS dB via a brief pw-cat capture, then hands the probe to
# the CLI's stateful detector.
#
# Designed for systemd-timer invocation (every 120s); each tick adds
# elapsed silence to the persisted state until the threshold fires
# PIN_GLITCH, at which point --auto-fix invokes the watchdog recovery
# (pactl set-card-profile off → output:analog-stereo).
#
# References:
# - CLI: scripts/hapax-audio-topology pin-check
# - Detector: shared/audio_pin_glitch.py
# - Memory: reference_ryzen_codec_pin_glitch (the underlying bug class)
# - Audit: docs/superpowers/audits/2026-04-20-3h-work-audit-remediation.md (B5)

set -euo pipefail

# Defaults — match the Ryzen card the operator runs. Override via env
# for non-Ryzen test environments.
SINK_NAME="${HAPAX_PIN_CHECK_SINK:-alsa_output.pci-0000_73_00.6.analog-stereo}"
SINK_LABEL="${HAPAX_PIN_CHECK_LABEL:-ryzen-analog-out}"
CARD="${HAPAX_PIN_CHECK_CARD:-alsa_card.pci-0000_73_00.6}"
PROFILE="${HAPAX_PIN_CHECK_PROFILE:-output:analog-stereo}"
STATE_FILE="${HAPAX_PIN_CHECK_STATE_FILE:-/run/user/$UID/hapax-pin-glitch-state.json}"
CAPTURE_S="${HAPAX_PIN_CHECK_CAPTURE_S:-0.5}"
AUTO_FIX="${HAPAX_PIN_CHECK_AUTO_FIX:-1}"

# CLI lives next to this script. Tests override via env var to point
# at a stub.
CLI="${HAPAX_AUDIO_TOPOLOGY_CLI:-$(dirname "$(readlink -f "$0")")/hapax-audio-topology}"

# 1) Sink state — parse `pactl list sinks` for the target sink's State.
sink_state="$(pactl list sinks 2>/dev/null \
    | awk -v name="$SINK_NAME" '
        /^\tName:/ { current = $2 }
        /^\tState:/ && current == name { print $2; exit }
      ')"
if [[ -z "$sink_state" ]]; then
    echo "pin-check probe: sink $SINK_NAME not found in pactl listing" >&2
    exit 0  # No sink → no diagnostic possible; not a failure.
fi

# 2) Active sink-input count for the target sink. Parse `pactl list short
#    sink-inputs` for entries whose Sink: column matches the target's id.
sink_id="$(pactl list short sinks 2>/dev/null | awk -v name="$SINK_NAME" '$2 == name {print $1; exit}')"
active_inputs=0
if [[ -n "$sink_id" ]]; then
    active_inputs="$(pactl list short sink-inputs 2>/dev/null \
        | awk -v sid="$sink_id" '$4 == sid {n++} END {print n+0}')"
fi
if [[ "$active_inputs" -gt 0 ]]; then
    has_input_flag="--has-active-input"
else
    has_input_flag="--no-active-input"
fi

# 3) Monitor RMS dB via brief pw-cat capture + ffmpeg's volumedetect.
#    A reliable RMS read requires ~500 ms of audio at 48 kHz; ffmpeg's
#    volumedetect filter prints "mean_volume: -X.X dB" we parse.
#    `timeout` runs pw-cat foreground with a hard cap so a hung capture
#    never wedges the timer; exit code 124 = timed-out (success for
#    our purpose), other non-zero = real failure → fall back to -inf.
tmpwav="$(mktemp --suffix=.wav)"
trap 'rm -f "$tmpwav"' EXIT
rms_db="-inf"
pwcat_rc=0
timeout --kill-after=1s "${CAPTURE_S}s" \
    pw-cat --record \
        --target "${SINK_NAME}.monitor" \
        --format s16 --rate 48000 --channels 2 --latency 1024 \
        "$tmpwav" >/dev/null 2>&1 || pwcat_rc=$?
# 124 = SIGTERM from timeout (expected); 137 = SIGKILL fallback.
if [[ "$pwcat_rc" == 0 || "$pwcat_rc" == 124 || "$pwcat_rc" == 137 ]]; then
    rms_db="$(ffmpeg -hide_banner -nostats -i "$tmpwav" \
        -af volumedetect -f null - 2>&1 \
        | awk '/mean_volume:/ {print $5; exit}')"
    rms_db="${rms_db:--inf}"
else
    echo "pin-check probe: pw-cat record failed (rc=$pwcat_rc); passing -inf dB" >&2
fi

# 4) Hand the probe to the stateful CLI detector.
extra_args=()
[[ "$AUTO_FIX" == "1" ]] && extra_args+=("--auto-fix" "--card" "$CARD" "--profile" "$PROFILE")

exec "$CLI" pin-check \
    --sink "$SINK_LABEL" \
    --state "$sink_state" \
    "$has_input_flag" \
    --rms-db "$rms_db" \
    --state-file "$STATE_FILE" \
    "${extra_args[@]}"
