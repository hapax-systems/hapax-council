#!/usr/bin/env bash
# audio-routing-check.sh — validate PipeWire audio routing invariants
#
# Run before AND after any audio config change. Exits non-zero if any
# invariant is violated. Designed to be called by:
#   - git pre-commit hook (when PipeWire configs change)
#   - systemd health timer (hapax-audio-health.timer)
#   - any AI agent before/after touching audio
#   - the operator manually: ./scripts/audio-routing-check.sh
#
# INVARIANTS (2026-05-05 golden state):
#
#   1. TTS voice chain: role.broadcast → voice-fx-capture → voice-fx-playback
#      → loudnorm-capture → loudnorm-playback → MPC AUX2/3
#
#   2. NO direct TTS bypass to livestream-tap. hapax-tts-broadcast-playback
#      must NOT exist or be connected to hapax-livestream-tap.
#
#   3. Livestream tap inputs: ONLY l12-evilpet-playback and l12-usb-return-playback
#      feed into hapax-livestream-tap. Nothing else.
#
#   4. OBS chain: broadcast-normalized → obs-broadcast-remap → OBS
#
#   5. MPC receives audio on AUX0-9 from the various loudnorm playback nodes.
#
# Exit codes: 0 = all good, 1 = invariant violation, 2 = PipeWire not running

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

GRAPH=$(pw-link -l 2>&1) || { echo -e "${RED}FAIL: PipeWire not running${NC}"; exit 2; }
FAILURES=0

check() {
    local desc="$1"
    local result="$2"
    if [[ "$result" == PASS* ]]; then
        echo -e "  ${GREEN}✓${NC} $desc ${result#PASS}"
    else
        echo -e "  ${RED}✗ FAIL: $desc — $result${NC}"
        FAILURES=$((FAILURES + 1))
    fi
}

echo "=== Hapax Audio Routing Invariant Check ==="
echo ""

# ── Invariant 1: TTS voice chain exists ──
echo "Chain 1: TTS Voice Path"

if echo "$GRAPH" | grep -q "output.loopback.sink.role.broadcast:output_FL" &&
   echo "$GRAPH" | grep -q "hapax-voice-fx-capture:playback_FL"; then
    check "role.broadcast → voice-fx-capture" "PASS"
else
    check "role.broadcast → voice-fx-capture" "link missing"
fi

if echo "$GRAPH" | grep -q "hapax-voice-fx-playback:output_FL" &&
   echo "$GRAPH" | grep -q "hapax-loudnorm-capture:playback_FL"; then
    check "voice-fx-playback → loudnorm-capture" "PASS"
else
    check "voice-fx-playback → loudnorm-capture" "link missing"
fi

if echo "$GRAPH" | grep -q "hapax-loudnorm-playback:output_FL" &&
   echo "$GRAPH" | grep "hapax-loudnorm-playback:output_FL" -A1 | grep -q "MPC.*playback_AUX2"; then
    check "loudnorm-playback → MPC AUX2" "PASS"
else
    check "loudnorm-playback → MPC AUX2" "link missing — TTS not reaching MPC"
fi

echo ""

# ── Invariant 2: NO direct TTS bypass ──
echo "Chain 2: TTS Bypass Guard"

if echo "$GRAPH" | grep -q "hapax-tts-broadcast-playback"; then
    if echo "$GRAPH" | grep "hapax-tts-broadcast-playback" | grep -q "hapax-livestream-tap"; then
        check "no TTS bypass to livestream-tap" "BYPASS DETECTED — tts-broadcast-playback → livestream-tap"
    else
        check "no TTS bypass to livestream-tap" "PASS (node exists but not connected to tap)"
    fi
else
    check "no TTS bypass to livestream-tap" "PASS"
fi

echo ""

# ── Invariant 3: Livestream tap inputs are clean ──
echo "Chain 3: Livestream Tap Inputs"

TAP_INPUTS=$(echo "$GRAPH" | grep "hapax-livestream-tap:playback" -B1 | grep "|->" | grep -v "hapax-livestream-tap" || true)
ALLOWED_SOURCES="hapax-l12-evilpet-playback|hapax-l12-usb-return-playback|input\.loopback"
UNEXPECTED=$(echo "$TAP_INPUTS" | grep -vE "$ALLOWED_SOURCES" | grep -v "^$" | grep -v "^--$" || true)

if [ -z "$UNEXPECTED" ]; then
    check "livestream-tap has only L12 inputs" "PASS"
else
    check "livestream-tap has only L12 inputs" "unexpected source(s): $UNEXPECTED"
fi

echo ""

# ── Invariant 4: OBS chain intact ──
echo "Chain 4: OBS Broadcast Chain"

if echo "$GRAPH" | grep -q "hapax-obs-broadcast-remap:capture_FL" &&
   echo "$GRAPH" | grep "hapax-obs-broadcast-remap:capture_FL" -A1 | grep -q "OBS:input_FL"; then
    check "obs-broadcast-remap → OBS" "PASS"
else
    check "obs-broadcast-remap → OBS" "link missing — OBS not receiving broadcast"
fi

if echo "$GRAPH" | grep -q "hapax-broadcast-normalized:capture_FL" &&
   echo "$GRAPH" | grep "hapax-broadcast-normalized:capture_FL" -A1 | grep -q "hapax-obs-broadcast-remap-capture"; then
    check "broadcast-normalized → obs-remap" "PASS"
else
    check "broadcast-normalized → obs-remap" "link missing"
fi

echo ""

# ── Invariant 5: MPC receiving all sources ──
echo "Chain 5: MPC Input Assignments"

MPC_INPUTS=$(echo "$GRAPH" | grep -c "Akai.*MPC.*playback_AUX" || true)
if [ "$MPC_INPUTS" -ge 10 ]; then
    check "MPC has ≥10 AUX channel references" "PASS ($MPC_INPUTS found)"
else
    check "MPC has ≥10 AUX channel references" "only $MPC_INPUTS (expected ≥10)"
fi

# ── Invariant 6: No .conf files that create bypass paths ──
echo ""
echo "Chain 6: Config File Guard"

BYPASS_CONFS=$(ls ~/.config/pipewire/pipewire.conf.d/*tts-broadcast-tap*.conf 2>/dev/null || true)
if [ -z "$BYPASS_CONFS" ]; then
    check "no active TTS bypass configs" "PASS"
else
    check "no active TTS bypass configs" "found: $BYPASS_CONFS"
fi

# Check for any .conf that creates a PLAYBACK node targeting livestream-tap
# that is NOT one of the legitimate L12/S4 sources.
# Legitimate: hapax-l12-evilpet-capture, hapax-l12-usb-return-capture,
#             hapax-s4-loopback (these ARE the sources that feed the tap).
# Bypass:     anything else creating a playback→livestream-tap path.
LEGIT_TAP_SOURCES="hapax-l12-evilpet|hapax-l12-usb-return|hapax-s4-loopback|hapax-broadcast-master"
SUSPECT=$(grep -rl "target.object.*livestream-tap" ~/.config/pipewire/pipewire.conf.d/*.conf 2>/dev/null | while read f; do
    bn=$(basename "$f")
    if ! echo "$bn" | grep -qE "$LEGIT_TAP_SOURCES"; then
        if grep -A5 'playback.props' "$f" | grep -q 'target.object.*livestream-tap'; then
            echo "$f"
        fi
    fi
done || true)
if [ -z "$SUSPECT" ]; then
    check "no unauthorized playback into livestream-tap" "PASS"
else
    check "no unauthorized playback into livestream-tap" "bypass config: $SUSPECT"
fi

# ── Invariant 7: Critical nodes not muted ──
echo ""
echo "Chain 7: Mute State Guard"

# The broadcast loopback being muted silently kills ALL TTS-to-livestream
# audio despite every PipeWire link showing connected. This is the single
# most insidious failure mode — the graph looks perfect but no signal flows.
BROADCAST_MUTE=$(wpctl get-volume "$(pw-cli ls Node 2>/dev/null | grep -B5 'input.loopback.sink.role.broadcast' | head -1 | awk '{print $2}' | tr -d ',')" 2>/dev/null || echo "UNKNOWN")
if echo "$BROADCAST_MUTE" | grep -qi "muted"; then
    check "broadcast loopback not muted" "MUTED — unmute with: wpctl set-mute <id> 0"
elif echo "$BROADCAST_MUTE" | grep -qi "volume"; then
    check "broadcast loopback not muted" "PASS"
else
    check "broadcast loopback not muted" "could not read mute state: $BROADCAST_MUTE"
fi

# Also check the voice-fx and loudnorm chain nodes
for NODE_NAME in hapax-voice-fx-capture hapax-loudnorm-capture; do
    NODE_ID=$(pw-cli ls Node 2>/dev/null | grep -B5 "$NODE_NAME" | head -1 | awk '{print $2}' | tr -d ',' 2>/dev/null || echo "")
    if [ -n "$NODE_ID" ]; then
        MUTE_STATE=$(wpctl get-volume "$NODE_ID" 2>/dev/null || echo "UNKNOWN")
        if echo "$MUTE_STATE" | grep -qi "muted"; then
            check "$NODE_NAME not muted" "MUTED"
        elif echo "$MUTE_STATE" | grep -qi "volume"; then
            check "$NODE_NAME not muted" "PASS"
        else
            check "$NODE_NAME not muted" "could not read: $MUTE_STATE"
        fi
    fi
done


# ── Invariant 8: .conf safety pattern (room-mic-hijack regression) ──
echo ""
echo "Chain 8: PipeWire .conf Safety Pattern"

# Filter-chains targeting specific ALSA hardware MUST set either
# node.passive=true OR node.dont-reconnect=true. Without this, when the
# target ALSA device is missing, WirePlumber's auto-link policy binds
# the filter-chain to the default source (typically a webcam mic), causing
# a class of leak documented in 10-contact-mic.conf as "the whole
# room-mic-hijack class of bugs".
#
# Incident 2026-05-06: hapax-l12-usb-return-capture had dont-reconnect=false
# and no node.passive=true; when L-12 USB was detached, C920 webcam mic
# leaked into broadcast.

UNSAFE_CONFS=""
for conf in ~/.config/pipewire/pipewire.conf.d/*.conf; do
    [ -f "$conf" ] || continue
    if grep -qE 'target\.object\s*=\s*"alsa_|node\.target\s*=\s*"alsa_' "$conf" 2>/dev/null; then
        if ! grep -qE 'node\.passive\s*=\s*true' "$conf" && ! grep -qE 'node\.dont-reconnect\s*=\s*true' "$conf"; then
            UNSAFE_CONFS="$UNSAFE_CONFS $(basename $conf)"
        fi
    fi
done
if [ -n "$UNSAFE_CONFS" ]; then
    check ".conf safety pattern (passive=true OR dont-reconnect=true)" "UNSAFE:$UNSAFE_CONFS"
else
    check ".conf safety pattern (passive=true OR dont-reconnect=true)" "PASS"
fi


# ── Invariant 9: webcam mic NEVER feeds broadcast filter-chains ──
echo ""
echo "Chain 9: Webcam Mic Broadcast Leak Guard"

# Per 2026-05-06 incident: C920 webcam mic leaked into broadcast via
# hapax-l12-usb-return-capture filter-chain when L-12 USB was missing.
# Regression check: NO webcam (C920/Brio) capture pad should be linked
# into hapax-l12-usb-return-capture, hapax-l12-evilpet-capture,
# hapax-m8-instrument-capture, or directly into livestream-feeding chains.

WEBCAM_LEAK=$(pw-link -l 2>/dev/null | grep -B 1 -E "hapax-(l12-usb-return-capture|l12-evilpet-capture|m8-instrument-capture):input_AUX" 2>/dev/null | grep -E "C920|Brio|Logitech" 2>/dev/null || true)
if [ -n "$WEBCAM_LEAK" ]; then
    check "no webcam mic in L-12/M-8 capture filter-chains" "LEAK:${WEBCAM_LEAK:0:80}..."
else
    check "no webcam mic in L-12/M-8 capture filter-chains" "PASS"
fi

echo ""
echo "=== Result ==="
if [ "$FAILURES" -eq 0 ]; then
    echo -e "${GREEN}ALL INVARIANTS PASSED${NC}"
    exit 0
else
    echo -e "${RED}$FAILURES INVARIANT(S) VIOLATED${NC}"
    exit 1
fi
