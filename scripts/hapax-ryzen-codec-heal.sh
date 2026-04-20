#!/bin/bash
# Ryzen HDA codec pin-routing heal.
#
# After any PipeWire restart (typically triggered by a USB audio device
# joining the graph — Torso S-4, Rode WP, etc.), the Ryzen HD Audio
# codec can report every health check healthy while the physical rear
# line-out jack's pin multiplexer internally points at a disabled
# widget. Symptom: ALSA / pactl / mixer all say everything is fine,
# monitors are silent.
#
# Fix (known-good per memory ryzen_codec_pin_glitch): toggle the
# card profile off → on, which forces the codec to re-assert its
# pin routing.
#
# This script is invoked by the `pipewire.service` user unit
# drop-in at ~/.config/systemd/user/pipewire.service.d/ryzen-codec-heal.conf
# on every ExecStartPost. Safe to run standalone.
#
# Env overrides:
#   HAPAX_RYZEN_CARD       default alsa_card.pci-0000_73_00.6
#   HAPAX_RYZEN_PROFILE    default output:analog-stereo
#   HAPAX_RYZEN_TIMEOUT_S  seconds to wait for PipeWire / the card
#                          to appear (default 15)

set -euo pipefail

CARD="${HAPAX_RYZEN_CARD:-alsa_card.pci-0000_73_00.6}"
PROFILE="${HAPAX_RYZEN_PROFILE:-output:analog-stereo}"
TIMEOUT_S="${HAPAX_RYZEN_TIMEOUT_S:-15}"

log() { printf 'ryzen-codec-heal: %s\n' "$*" >&2; }

# Wait for PipeWire to accept pactl calls AND the card to be enumerated.
# Clean-exit 0 if either never shows up (host without that card or
# PipeWire not running as user).
for _ in $(seq 1 "$TIMEOUT_S"); do
    if pactl list cards short 2>/dev/null | awk '{print $2}' | grep -qxF "$CARD"; then
        break
    fi
    sleep 1
done
if ! pactl list cards short 2>/dev/null | awk '{print $2}' | grep -qxF "$CARD"; then
    log "card $CARD not enumerated after ${TIMEOUT_S}s — skipping (exit 0)"
    exit 0
fi

# Apply the toggle. Use `|| true` on the `off` leg because older PipeWire
# versions sometimes report a harmless error when profile is already off.
log "toggling $CARD off → $PROFILE"
pactl set-card-profile "$CARD" off 2>&1 | sed 's/^/ryzen-codec-heal: /' >&2 || true
sleep 0.4
pactl set-card-profile "$CARD" "$PROFILE" 2>&1 | sed 's/^/ryzen-codec-heal: /' >&2

# Confirm post-state. If the sink doesn't come back as RUNNING / IDLE,
# emit a loud warning — the operator needs to know the auto-heal failed.
sleep 0.5
SINK="alsa_output.$(echo "$CARD" | sed 's/^alsa_card\.//').$(echo "$PROFILE" | sed 's/^output://')"
STATE="$(pactl list short sinks 2>/dev/null | awk -v s="$SINK" '$2==s{print $5}' | head -1)"
if [ -z "$STATE" ]; then
    log "WARN: sink $SINK did not re-appear after toggle — pipewire may be in a bad state"
    exit 1
fi
log "done — $SINK state=$STATE"
