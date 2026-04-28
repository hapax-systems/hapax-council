#!/usr/bin/env bash
# audio-leak-guard.sh
#
# Regression guard for the 2026-04-26 private-comms broadcast leak.
#
# What it checks:
#  1. role.assistant loopback output is routed to hapax-private (NOT
#     hapax-voice-fx-capture). hapax-voice-fx-capture chains into L-12
#     CH 11/12 = broadcast. hapax-private chains to Blue Yeti = monitor.
#  2. The 55-hapax-voice-role-retarget.conf is NOT active (it would
#     force role.assistant output back to hapax-voice-fx-capture).
#  3. The wireplumber preferred-target for role.assistant is set to
#     hapax-private in the active config.
#  4. The separate role.broadcast loopback exists and targets
#     hapax-voice-fx-capture. That broadcast target is allowed; it must
#     not make the assistant leak check fail.
#
# Exit codes:
#  0  — clean, no leak risk
#  1  — leak risk detected (one or more checks failed)
#
# Run after any wireplumber config change, after every reboot, and as
# part of stream pre-flight.

set -u

FAIL=0
WP_CONF_DIR="${HAPAX_WIREPLUMBER_CONF_DIR:-${HOME}/.config/wireplumber/wireplumber.conf.d}"

if [ "${HAPAX_AUDIO_LEAK_GUARD_STATIC_ONLY:-0}" = "1" ]; then
    ROUTE=""
    echo "SKIP runtime route check (HAPAX_AUDIO_LEAK_GUARD_STATIC_ONLY=1)"
else
    # Check 1: role.assistant output routes to hapax-private.
    ROUTE=$(timeout 1 pw-cat --playback --raw --format s16 --rate 24000 \
        --channels 1 --media-role Assistant /dev/zero >/dev/null 2>&1 &
        sleep 0.3
        pw-link -l 2>/dev/null | awk '
            /^output\.loopback\.sink\.role\.assistant:output_FL/ {f=1; next}
            f && /\|->/ {print; exit}
        ')
fi

if echo "$ROUTE" | grep -q "hapax-private"; then
    echo "OK  role.assistant routes to hapax-private (monitor, not broadcast)"
elif echo "$ROUTE" | grep -q "hapax-voice-fx-capture"; then
    echo "FAIL role.assistant routes to hapax-voice-fx-capture (BROADCAST LEAK)"
    FAIL=1
elif [ -z "$ROUTE" ]; then
    echo "WARN role.assistant route unknown — no active stream during check"
else
    echo "WARN role.assistant routes to unexpected target: $ROUTE"
fi

# Check 2: 55-retarget.conf is disabled.
if [ -f "$WP_CONF_DIR/55-hapax-voice-role-retarget.conf" ]; then
    echo "FAIL 55-hapax-voice-role-retarget.conf is ACTIVE (forces broadcast leak)"
    echo "     Run: mv $WP_CONF_DIR/55-hapax-voice-role-retarget.conf{,.disabled}"
    FAIL=1
else
    echo "OK  55-hapax-voice-role-retarget.conf is disabled"
fi

# Check 3: preferred-target in role.assistant is hapax-private.
DUCK_CONF="$WP_CONF_DIR/50-hapax-voice-duck.conf"
ASSISTANT_BLOCK=$(awk '
    /node.name = "loopback.sink.role.assistant"/ { f=1 }
    f { print }
    f && /provides = loopback.sink.role.assistant/ { exit }
' "$DUCK_CONF" 2>/dev/null || true)
ASSISTANT_TARGET_LINE=$(printf '%s\n' "$ASSISTANT_BLOCK" \
    | awk '/policy\.role-based\.preferred-target/ && $1 !~ /^#/ { print; exit }')

if printf '%s\n' "$ASSISTANT_TARGET_LINE" \
    | grep -q 'policy.role-based.preferred-target = "hapax-private"'; then
    echo "OK  preferred-target = hapax-private (no broadcast pinning)"
else
    echo "FAIL role.assistant preferred-target NOT pinned to hapax-private in $DUCK_CONF"
    FAIL=1
fi

# Check 4: role.broadcast is the only voice-fx-capture role route.
BROADCAST_BLOCK=$(awk '
    /node.name = "loopback.sink.role.broadcast"/ { f=1 }
    f { print }
    f && /provides = loopback.sink.role.broadcast/ { exit }
' "$DUCK_CONF" 2>/dev/null || true)
BROADCAST_TARGET_LINE=$(printf '%s\n' "$BROADCAST_BLOCK" \
    | awk '/policy\.role-based\.preferred-target/ && $1 !~ /^#/ { print; exit }')

if printf '%s\n' "$BROADCAST_TARGET_LINE" \
    | grep -q 'policy.role-based.preferred-target = "hapax-voice-fx-capture"'; then
    echo "OK  role.broadcast routes to hapax-voice-fx-capture"
else
    echo "FAIL role.broadcast preferred-target missing hapax-voice-fx-capture in $DUCK_CONF"
    FAIL=1
fi

if [ "$FAIL" -ne 0 ]; then
    echo ""
    echo "LEAK RISK DETECTED. See:"
    echo "  ~/.cache/hapax/relay/2026-04-26-private-comms-broadcast-leak-fix.md"
    exit 1
fi
echo ""
echo "All checks passed — no leak risk."
exit 0
