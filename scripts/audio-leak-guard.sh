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
PW_CONF_DIR="${HAPAX_PIPEWIRE_CONF_DIR:-${HOME}/.config/pipewire/pipewire.conf.d}"
FORBIDDEN_PRIVATE_TARGET_RE='alsa_output\.usb-ZOOM_Corporation_L-12|alsa_output\.usb-Torso_Electronics_S-4|hapax-livestream|hapax-livestream-tap|hapax-voice-fx-capture|hapax-pc-loudnorm|input\.loopback\.sink\.role\.multimedia'
# HN private monitor audio routes through MPC Live III. S-4 is downstream/MIDI
# in this path and is not an approved host-side audio target.
PRIVATE_MONITOR_TARGET_RE='alsa_output\.usb-Akai_Professional_MPC_LIVE_III_.*\.multichannel-output'

active_conf() {
    sed '/^[[:space:]]*#/d' "$1" 2>/dev/null || true
}

node_block_from_active() {
    local active="$1"
    local node_name="$2"
    printf '%s\n' "$active" | awk -v node="$node_name" '
        index($0, "node.name = \"" node "\"") { f=1 }
        f { print }
        f && /^[[:space:]]*}/ { exit }
    '
}

require_bridge_prop() {
    local block="$1"
    local node_name="$2"
    local prop="$3"
    if printf '%s\n' "$block" | grep -Fq "$prop"; then
        return 0
    fi
    echo "FAIL $node_name missing fail-closed property: $prop"
    FAIL=1
}

if [ "${HAPAX_AUDIO_LEAK_GUARD_STATIC_ONLY:-0}" = "1" ]; then
    ROUTE=""
    echo "SKIP runtime route check (HAPAX_AUDIO_LEAK_GUARD_STATIC_ONLY=1)"
else
    # Check 1: role.assistant output routes to hapax-private.
    ROUTE=$(pw-link -l 2>/dev/null | awk '
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

# Check 1b: hapax-private itself must not have a downstream playback
# bridge into L-12 or another broadcast path. The safest posture when no
# private monitor hardware is present is no downstream playback bridge.
PRIVATE_RUNTIME_ROUTE=""
NOTIFICATION_ROUTE=""
NOTIFICATION_RUNTIME_ROUTE=""
if [ "${HAPAX_AUDIO_LEAK_GUARD_STATIC_ONLY:-0}" != "1" ]; then
    PRIVATE_RUNTIME_ROUTE=$(pw-link -l 2>/dev/null | awk '
        /^hapax-private-playback:output_/ {f=1; next}
        f && /\|->/ {print; f=0}
    ')
    NOTIFICATION_ROUTE=$(pw-link -l 2>/dev/null | awk '
        /^output\.loopback\.sink\.role\.notification:output/ {f=1; next}
        f && /\|->/ {print; exit}
    ')
    NOTIFICATION_RUNTIME_ROUTE=$(pw-link -l 2>/dev/null | awk '
        /^hapax-notification-private-playback:output_/ {f=1; next}
        f && /\|->/ {print; f=0}
    ')
fi

if printf '%s\n' "$PRIVATE_RUNTIME_ROUTE" | grep -Eq "$FORBIDDEN_PRIVATE_TARGET_RE"; then
    echo "FAIL hapax-private downstream route reaches broadcast/default path: $PRIVATE_RUNTIME_ROUTE"
    FAIL=1
elif [ -z "$PRIVATE_RUNTIME_ROUTE" ]; then
    echo "OK  hapax-private has no downstream playback bridge (fail-closed)"
else
    echo "OK  hapax-private downstream route stays off broadcast: $PRIVATE_RUNTIME_ROUTE"
fi

if [ -n "$NOTIFICATION_ROUTE" ]; then
    if printf '%s\n' "$NOTIFICATION_ROUTE" | grep -q "hapax-notification-private"; then
        echo "OK  role.notification routes to hapax-notification-private"
    else
        echo "WARN role.notification routes to unexpected target: $NOTIFICATION_ROUTE"
    fi
elif [ "${HAPAX_AUDIO_LEAK_GUARD_STATIC_ONLY:-0}" != "1" ]; then
    echo "WARN role.notification route unknown — no active stream during check"
fi

if printf '%s\n' "$NOTIFICATION_RUNTIME_ROUTE" | grep -Eq "$FORBIDDEN_PRIVATE_TARGET_RE"; then
    echo "FAIL hapax-notification-private downstream route reaches broadcast/default path: $NOTIFICATION_RUNTIME_ROUTE"
    FAIL=1
elif [ -z "$NOTIFICATION_RUNTIME_ROUTE" ]; then
    echo "OK  hapax-notification-private has no downstream playback bridge (fail-closed)"
else
    echo "OK  hapax-notification-private downstream route stays off broadcast: $NOTIFICATION_RUNTIME_ROUTE"
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

# Check 5: deployed PipeWire private sink configs must not encode a
# forbidden downstream target. This catches the class where the
# role-based WirePlumber target is correct but the target sink itself
# forwards into L-12/default broadcast.
STREAM_SPLIT_CONF="$PW_CONF_DIR/hapax-stream-split.conf"
STREAM_SPLIT_ACTIVE=$(active_conf "$STREAM_SPLIT_CONF")
if printf '%s\n' "$STREAM_SPLIT_ACTIVE" | grep -q 'node.name[[:space:]]*=[[:space:]]*"hapax-private-playback"'; then
    PRIVATE_STATIC_TARGET=$(printf '%s\n' "$STREAM_SPLIT_ACTIVE" \
        | awk '
            /node.name[[:space:]]*=[[:space:]]*"hapax-private-playback"/ {f=1}
            f && /(target\.object|node\.target)/ {print; exit}
            f && /^[[:space:]]*}/ {exit}
        ')
    if printf '%s\n' "$PRIVATE_STATIC_TARGET" | grep -Eq "$FORBIDDEN_PRIVATE_TARGET_RE"; then
        echo "FAIL hapax-private-playback static target is broadcast/default path: $PRIVATE_STATIC_TARGET"
        FAIL=1
    else
        echo "OK  hapax-private-playback static target stays off broadcast"
    fi
else
    echo "OK  hapax-private is fail-closed in PipeWire config (no playback target)"
fi

NOTIFY_CONF="$PW_CONF_DIR/hapax-notification-private.conf"
NOTIFY_ACTIVE=$(active_conf "$NOTIFY_CONF")
NOTIFY_STATIC_TARGET=$(printf '%s\n' "$NOTIFY_ACTIVE" \
    | awk '/(target\.object|node\.target)/ {print; exit}')
if printf '%s\n' "$NOTIFY_STATIC_TARGET" | grep -Eq "$FORBIDDEN_PRIVATE_TARGET_RE"; then
    echo "FAIL hapax-notification-private static target is broadcast/default path: $NOTIFY_STATIC_TARGET"
    FAIL=1
elif [ -z "$NOTIFY_STATIC_TARGET" ]; then
    echo "OK  hapax-notification-private is fail-closed in PipeWire config (no playback target)"
else
    echo "OK  hapax-notification-private static target stays off broadcast"
fi

# Check 6: an optional explicit private monitor bridge may make private
# audio audible, but it must target only the MPC Live III private monitor
# ingress and fail closed when that endpoint is absent. The null sinks above
# stay target-free; this separate file owns the guarded hardware edge.
PRIVATE_BRIDGE_CONF="$PW_CONF_DIR/hapax-private-monitor-bridge.conf"
PRIVATE_BRIDGE_ACTIVE=$(active_conf "$PRIVATE_BRIDGE_CONF")
if [ -z "$PRIVATE_BRIDGE_ACTIVE" ]; then
    echo "OK  no explicit private monitor bridge configured (silent fail-closed posture)"
else
    for pair in \
        "hapax-private-monitor-capture|hapax-private" \
        "hapax-notification-private-monitor-capture|hapax-notification-private"; do
        capture_node=${pair%%|*}
        capture_target=${pair#*|}
        capture_block=$(node_block_from_active "$PRIVATE_BRIDGE_ACTIVE" "$capture_node")
        if [ -z "$capture_block" ]; then
            echo "FAIL missing private monitor capture node: $capture_node"
            FAIL=1
            continue
        fi
        if printf '%s\n' "$capture_block" | grep -Fq 'stream.capture.sink = true' \
            && printf '%s\n' "$capture_block" \
                | grep -Fq "target.object = \"$capture_target\""; then
            echo "OK  $capture_node captures $capture_target monitor"
        else
            echo "FAIL $capture_node does not capture $capture_target as a sink monitor"
            FAIL=1
        fi
    done

    for playback_node in hapax-private-playback hapax-notification-private-playback; do
        playback_block=$(node_block_from_active "$PRIVATE_BRIDGE_ACTIVE" "$playback_node")
        if [ -z "$playback_block" ]; then
            echo "FAIL missing private monitor playback node: $playback_node"
            FAIL=1
            continue
        fi
        playback_target=$(printf '%s\n' "$playback_block" \
            | awk '/(target\.object|node\.target)/ {print; exit}')
        if printf '%s\n' "$playback_target" | grep -Eq "$FORBIDDEN_PRIVATE_TARGET_RE"; then
            echo "FAIL $playback_node static target is broadcast/default path: $playback_target"
            FAIL=1
        elif printf '%s\n' "$playback_target" | grep -Eq "$PRIVATE_MONITOR_TARGET_RE"; then
            echo "OK  $playback_node static target is MPC Live III private monitor"
        else
            echo "FAIL $playback_node static target is not the approved private monitor: $playback_target"
            FAIL=1
        fi
        require_bridge_prop "$playback_block" "$playback_node" "node.dont-fallback = true"
        require_bridge_prop "$playback_block" "$playback_node" "node.dont-reconnect = true"
        require_bridge_prop "$playback_block" "$playback_node" "node.dont-move = true"
        require_bridge_prop "$playback_block" "$playback_node" "node.linger = true"
        require_bridge_prop "$playback_block" "$playback_node" "state.restore = false"
    done
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
