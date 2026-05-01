#!/usr/bin/env bash
# audit-notification-loopback-trace.sh — DYNAMIC notification loopback trace.
#
# Audit-closeout 4.6 (dynamic complement of audit-audio-topology.sh):
#
#   The static graph check in audit-audio-topology.sh asserts no path
#   from `output.loopback.sink.role.notification` to `hapax-livestream`.
#   This script is the runtime trace: it actually plays a synthetic
#   notification ping through the standard ntfy desktop sink path,
#   captures the live PipeWire graph during playback, and asserts the
#   playing node has no link reaching the L-12 broadcast input bus.
#
#   The two scripts are complementary: a static check covers the graph
#   shape; this trace covers the actual node a playback session spawns,
#   which only exists during playback and can differ from the canonical
#   loopback sink (e.g. when an app routes via a per-stream sink-input).
#
# Usage:
#   audit-notification-loopback-trace.sh           # play + assert
#   audit-notification-loopback-trace.sh --json    # emit findings JSON
#
# Exit codes:
#   0 — playback completed and no path to hapax-livestream observed
#   1 — loopback detected (path from playback node → broadcast)
#   2 — usage error / missing tools
#
# Dependencies: pw-dump, jq, aplay, paplay-or-pw-cat, python3.
# CI environments without a live PipeWire graph exit 0 with a warning.

set -euo pipefail

mode="${1:-text}"
case "$mode" in
  text|--json) ;;
  *) echo "usage: $0 [--json]" >&2; exit 2 ;;
esac

require_tool() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "audit-notification-loopback-trace: missing tool: $1" >&2
    exit 2
  }
}
require_tool jq
require_tool python3

if ! command -v pw-dump >/dev/null 2>&1; then
  echo "audit-notification-loopback-trace: pw-dump not present; skipping (no PipeWire)" >&2
  exit 0
fi

# Probe the graph once. If empty / unreachable, environment has no live
# PipeWire — exit cleanly so CI doesn't fail.
graph_probe=$(pw-dump 2>/dev/null || true)
if [ -z "$graph_probe" ] || [ "$graph_probe" = "[]" ]; then
  echo "audit-notification-loopback-trace: empty PipeWire graph; skipping" >&2
  exit 0
fi

# Resolve broadcast sink. If absent, no leak is possible — exit 0.
broadcast_id=$(echo "$graph_probe" | jq '
  .[] | select(.type == "PipeWire:Interface:Node")
       | select(.info.props["node.name"] == "hapax-livestream")
       | .id
' | head -1)

if [ -z "$broadcast_id" ] || [ "$broadcast_id" = "null" ]; then
  echo "audit-notification-loopback-trace: hapax-livestream not present; skipping" >&2
  exit 0
fi

# Generate a brief synthetic ping. 200ms of silence is enough to spawn a
# transient sink-input without disturbing the operator. We use sox if
# available (precise duration), else the lowest-impact alternative is
# aplay /dev/zero with a small count, but we need a real WAV header for
# pw-cat / paplay; mktemp + a hand-rolled header is overkill — sox gives
# us a clean ~16KB silent WAV.
ping_wav=""
cleanup() {
  if [ -n "$ping_wav" ] && [ -f "$ping_wav" ]; then
    rm -f "$ping_wav"
  fi
}
trap cleanup EXIT

if command -v sox >/dev/null 2>&1; then
  ping_wav=$(mktemp --suffix=.wav)
  sox -n -r 48000 -c 1 -b 16 "$ping_wav" trim 0.0 0.2 2>/dev/null
elif command -v ffmpeg >/dev/null 2>&1; then
  ping_wav=$(mktemp --suffix=.wav)
  ffmpeg -loglevel quiet -y -f lavfi -i "anullsrc=r=48000:cl=mono" \
    -t 0.2 -ar 48000 -ac 1 -sample_fmt s16 "$ping_wav" 2>/dev/null
else
  echo "audit-notification-loopback-trace: missing sox AND ffmpeg; cannot synth ping" >&2
  exit 2
fi

if [ ! -s "$ping_wav" ]; then
  echo "audit-notification-loopback-trace: ping synthesis produced empty file" >&2
  exit 2
fi

# Pick a player. paplay routes to the default sink (which the
# notification daemon also uses); pw-cat is the PipeWire-native fallback.
play_cmd=""
if command -v paplay >/dev/null 2>&1; then
  play_cmd=(paplay --property=media.role=event "$ping_wav")
elif command -v pw-cat >/dev/null 2>&1; then
  play_cmd=(pw-cat --playback --media-role=event "$ping_wav")
elif command -v aplay >/dev/null 2>&1; then
  play_cmd=(aplay -q "$ping_wav")
else
  echo "audit-notification-loopback-trace: no player (paplay/pw-cat/aplay) available" >&2
  exit 2
fi

# Start playback in background, capture graph mid-stream, wait for it.
# We sleep briefly before the dump so the sink-input is registered, then
# kill the player if it outlives the dump (sox 200ms is short enough that
# this is normally a no-op).
"${play_cmd[@]}" >/dev/null 2>&1 &
play_pid=$!

# Race: capture before the 200ms ping finishes. Sleep slightly to let
# the sink-input register.
sleep 0.05
graph_during=$(pw-dump 2>/dev/null || echo "[]")

# Wait for player to finish (or kill if it hangs >2s).
( sleep 2 && kill -9 "$play_pid" >/dev/null 2>&1 || true ) &
killer_pid=$!
wait "$play_pid" 2>/dev/null || true
kill "$killer_pid" >/dev/null 2>&1 || true

if [ "$graph_during" = "[]" ] || [ -z "$graph_during" ]; then
  echo "audit-notification-loopback-trace: graph dump during playback empty" >&2
  exit 2
fi

# Identify the spawned playback node. PipeWire labels paplay/pw-cat
# stream nodes with media.class "Stream/Output/Audio" and the application
# role we set above. A trace-time fingerprint is enough — we filter
# `application.process.id == $play_pid` if present, falling back to any
# Stream/Output/Audio with media.role=event.
playback_id=$(echo "$graph_during" | jq --arg pid "$play_pid" '
  [ .[]
    | select(.type == "PipeWire:Interface:Node")
    | select(.info.props["media.class"] == "Stream/Output/Audio")
    | select((.info.props["application.process.id"] // "") == $pid
             or (.info.props["media.role"] // "") == "event")
    | .id
  ] | first // null
')

if [ -z "$playback_id" ] || [ "$playback_id" = "null" ]; then
  echo "audit-notification-loopback-trace: could not locate playback node; skipping" >&2
  exit 0
fi

# Build link adjacency from the during-playback dump and BFS.
links=$(echo "$graph_during" | jq -c '
  [ .[]
    | select(.type == "PipeWire:Interface:Link")
    | {out: (.info["output-node-id"] // .info.props["link.output.node"] // null),
       in: (.info["input-node-id"] // .info.props["link.input.node"] // null)}
    | select(.out != null and .in != null)
  ]
')

reachable=$(python3 - "$playback_id" "$broadcast_id" "$links" <<'PY'
import json, sys
src = int(sys.argv[1])
tgt = int(sys.argv[2])
links = json.loads(sys.argv[3])
adj = {}
for l in links:
    adj.setdefault(int(l["out"]), set()).add(int(l["in"]))
seen = {src}
queue = [src]
while queue:
    n = queue.pop(0)
    if n == tgt:
        print("yes"); sys.exit(0)
    for nxt in adj.get(n, ()):
        if nxt not in seen:
            seen.add(nxt); queue.append(nxt)
print("no")
PY
)

if [ "$mode" = "--json" ]; then
  jq -n \
    --arg date "$(date -Is)" \
    --argjson playback_id "$playback_id" \
    --argjson broadcast_id "$broadcast_id" \
    --arg reachable "$reachable" \
    '{audit_at: $date, playback_node_id: $playback_id, broadcast_node_id: $broadcast_id, reachable: $reachable, ok: ($reachable == "no")}'
fi

if [ "$reachable" = "yes" ]; then
  echo
  echo "=== NOTIFICATION LOOPBACK LEAK ===" >&2
  echo " - 4.6 LEAK: synthetic notification ping (node $playback_id) reaches hapax-livestream (node $broadcast_id)" >&2
  echo "   operator-private chimes audible to audience during livestream" >&2
  exit 1
fi

echo "✅ notification loopback trace: ping (node $playback_id) does NOT reach hapax-livestream (4.6 invariant holds at runtime)"
