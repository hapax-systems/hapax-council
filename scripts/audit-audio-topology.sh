#!/usr/bin/env bash
# audit-audio-topology.sh — assert PipeWire graph invariants for broadcast safety.
#
# Audit-closeout 4.2 + 4.6:
#   4.2 contact_mic must NOT chain to hapax-livestream
#   4.6 notification loopback target must NOT be hapax-livestream
#
# Both invariants are "no path exists from X to broadcast sink". This script
# walks the live PipeWire graph and asserts each invariant. Non-zero exit on
# any violation. Suitable for pre-live gating + cron monitoring.
#
# Usage:
#   audit-audio-topology.sh          # run all checks, exit 1 on any failure
#   audit-audio-topology.sh --json   # emit findings JSON for downstream tools
#
# Exit codes:
#   0 — all invariants hold
#   1 — at least one invariant violated (details on stderr)
#   2 — usage error / missing tools

set -euo pipefail

require_tool() {
  command -v "$1" >/dev/null 2>&1 || { echo "missing: $1" >&2; exit 2; }
}
require_tool pw-dump
require_tool jq

mode="${1:-text}"

# Pull full graph.
graph_json=$(pw-dump 2>/dev/null)

# Build name → id maps (PipeWire ids reset on restart; names are stable).
nodes_by_name=$(echo "$graph_json" | jq -c '
  [ .[]
    | select(.type == "PipeWire:Interface:Node")
    | {id: .id, name: (.info.props["node.name"] // "<unnamed>"), media: (.info.props["media.class"] // null)}
  ]
')

# Resolve broadcast sink id.
broadcast_id=$(echo "$nodes_by_name" | jq '
  .[] | select(.name == "hapax-livestream") | .id
' | head -1)

if [ -z "$broadcast_id" ] || [ "$broadcast_id" = "null" ]; then
  echo "warn: hapax-livestream sink not present in graph; skipping leak check" >&2
  echo "(if the broadcast sink is named differently in this session, update this script)" >&2
  exit 0
fi

# Build adjacency: for each link, output→input pair.
links=$(echo "$graph_json" | jq -c '
  [ .[]
    | select(.type == "PipeWire:Interface:Link")
    | {out: (.info["output-node-id"] // .info.props["link.output.node"] // null),
       in: (.info["input-node-id"] // .info.props["link.input.node"] // null)}
    | select(.out != null and .in != null)
  ]
')

# Reachability: can we reach broadcast_id from a given source name?
# Simple BFS.
reachable_from() {
  local source_name="$1"
  local target_id="$2"
  local source_id
  source_id=$(echo "$nodes_by_name" | jq --arg n "$source_name" '.[] | select(.name == $n) | .id' | head -1)
  if [ -z "$source_id" ] || [ "$source_id" = "null" ]; then
    echo "absent"
    return
  fi
  # BFS with python (simpler than bash deps)
  python3 - "$source_id" "$target_id" "$links" <<'PY'
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
}

violations=()

# Check 4.2: contact_mic → hapax-livestream
contact_status=$(reachable_from "contact_mic" "$broadcast_id")
case "$contact_status" in
  yes)
    violations+=("4.2 LEAK: contact_mic reaches hapax-livestream — broadcast carries fingernail/scratch/room rumble")
    ;;
  no)
    ;; # OK
  absent)
    echo "info: contact_mic node not present (audio capture may be down)" >&2
    ;;
esac

# Check 4.6: notification loopback → hapax-livestream
notif_node="output.loopback.sink.role.notification"
notif_status=$(reachable_from "$notif_node" "$broadcast_id")
case "$notif_status" in
  yes)
    violations+=("4.6 LEAK: notification loopback reaches hapax-livestream — operator-private chimes audible to audience")
    ;;
  no)
    ;; # OK
  absent)
    echo "info: notification loopback node not present" >&2
    ;;
esac

# Emit results.
if [ "$mode" = "--json" ]; then
  jq -n --arg date "$(date -Is)" --argjson violations "$(printf '%s\n' "${violations[@]+"${violations[@]}"}" | jq -R . | jq -s .)" \
    '{audit_at: $date, violations: $violations, ok: ($violations | length == 0)}'
fi

if [ "${#violations[@]}" -gt 0 ]; then
  echo
  echo "=== AUDIO TOPOLOGY VIOLATIONS ===" >&2
  for v in "${violations[@]}"; do echo " - $v" >&2; done
  exit 1
fi

echo "✅ audio topology invariants hold (4.2 contact_mic + 4.6 notification both isolated from hapax-livestream)"
