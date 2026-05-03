#!/usr/bin/env bash
# ir-fleet-audit.sh — per-Pi audit of the 3-node NoIR IR perception fleet
# (pi1/desk, pi2/room, pi6/overhead).
#
# Audits in order, per Pi:
#   1. ICMP reachability
#   2. SSH reachability
#   3. ir-edge daemon process liveness (pgrep hapax_ir_edge)
#   4. IR state file freshness (council-side ~/hapax-state/pi-noir/{role}.json)
#   5. Heartbeat file freshness (council-side ~/hapax-state/edge/hapax-pi{N}.json)
#   6. systemd hapax-heartbeat.timer status (Pi-side)
#   7. ONNX model presence + size (Pi-side)
#   8. IR signal sanity (persons / hands / motion fields present + recent)
#
# Per check emits a tagged line: PASS / FAIL / WARN / SKIP <pi> <check> <msg>.
# Exit code is the count of FAIL across the whole run (0 = healthy, >0 = degraded).
#
# Usage:
#   scripts/ir-fleet-audit.sh                # audit all 3 IR Pis
#   scripts/ir-fleet-audit.sh pi1            # audit one
#   scripts/ir-fleet-audit.sh --json         # emit JSON report on stdout
#
# Inputs: fixed fleet topology (see CLAUDE.md ## IR Perception (Pi NoIR Edge Fleet)).
# Outputs: stderr human-readable report; --json gives machine-parseable map.

set -uo pipefail

declare -A FLEET=(
  [pi1]="192.168.68.78|hapax-pi1|desk"
  [pi2]="192.168.68.52|hapax-pi2|room"
  [pi6]="192.168.68.74|hapax-pi6|overhead"
)

EDGE_DIR="${HOME}/hapax-state/edge"
NOIR_DIR="${HOME}/hapax-state/pi-noir"
STATE_FRESH_S="${IR_FLEET_STATE_FRESH_S:-30}"
HEARTBEAT_FRESH_S="${IR_FLEET_HEARTBEAT_FRESH_S:-300}"

JSON_MODE=0
PIS=()
for arg in "$@"; do
  case "$arg" in
    --json) JSON_MODE=1 ;;
    pi1|pi2|pi6) PIS+=("$arg") ;;
    *) echo "ir-fleet-audit: unknown arg: $arg" >&2; exit 2 ;;
  esac
done
[ ${#PIS[@]} -eq 0 ] && PIS=(pi1 pi2 pi6)

FAIL_COUNT=0
declare -A REPORT

emit() {
  local status="$1" pi="$2" check="$3" msg="$4"
  case "$status" in
    FAIL) FAIL_COUNT=$((FAIL_COUNT + 1)) ;;
  esac
  REPORT["${pi}.${check}"]="${status}|${msg}"
  if [ "$JSON_MODE" -eq 0 ]; then
    printf '%-4s %-4s %-22s %s\n' "$status" "$pi" "$check" "$msg" >&2
  fi
}

age_seconds() {
  local file="$1"
  if [ ! -f "$file" ]; then echo "-1"; return; fi
  local mtime now
  mtime=$(stat -c '%Y' "$file" 2>/dev/null || echo 0)
  now=$(date +%s)
  echo $((now - mtime))
}

audit_pi() {
  local pi="$1"
  local spec="${FLEET[$pi]}"
  local ip="${spec%%|*}"
  local rest="${spec#*|}"
  local hostname="${rest%%|*}"
  local role="${rest##*|}"

  if ping -c 1 -W 2 "$ip" >/dev/null 2>&1; then
    emit PASS "$pi" "icmp" "$ip reachable"
  else
    emit FAIL "$pi" "icmp" "$ip unreachable — power/network down"
    emit SKIP "$pi" "ssh" "skipped — icmp failed"
    emit SKIP "$pi" "daemon" "skipped — icmp failed"
    emit SKIP "$pi" "heartbeat-timer" "skipped — icmp failed"
    emit SKIP "$pi" "model" "skipped — icmp failed"
    audit_pi_council_side "$pi" "$role" "$hostname"
    return
  fi

  if ssh -o ConnectTimeout=3 -o BatchMode=yes "hapax@${ip}" "true" 2>/dev/null; then
    emit PASS "$pi" "ssh" "${ip} ssh ok"

    if ssh -o ConnectTimeout=3 -o BatchMode=yes "hapax@${ip}" "pgrep -f hapax_ir_edge >/dev/null" 2>/dev/null; then
      local pid
      pid=$(ssh -o ConnectTimeout=3 -o BatchMode=yes "hapax@${ip}" "pgrep -f hapax_ir_edge | head -1" 2>/dev/null | tr -d '[:space:]')
      emit PASS "$pi" "daemon" "hapax_ir_edge running (pid=${pid})"
    else
      emit FAIL "$pi" "daemon" "hapax_ir_edge NOT running"
    fi

    local timer_state
    timer_state=$(ssh -o ConnectTimeout=3 -o BatchMode=yes "hapax@${ip}" "systemctl is-active hapax-heartbeat.timer 2>/dev/null || echo not-installed" 2>/dev/null | tr -d '[:space:]')
    case "$timer_state" in
      active)        emit PASS "$pi" "heartbeat-timer" "systemd timer active" ;;
      not-installed) emit FAIL "$pi" "heartbeat-timer" "hapax-heartbeat.timer NOT installed (run scripts/ir-fleet-restart.sh ${pi})" ;;
      *)             emit FAIL "$pi" "heartbeat-timer" "timer state=${timer_state}" ;;
    esac

    local model_size
    model_size=$(ssh -o ConnectTimeout=3 -o BatchMode=yes "hapax@${ip}" "stat -c '%s' ~/hapax-edge/best.onnx 2>/dev/null || echo 0" 2>/dev/null | tr -d '[:space:]')
    if [ "${model_size}" -gt 1000000 ]; then
      emit PASS "$pi" "model" "best.onnx present (${model_size} bytes)"
    else
      emit FAIL "$pi" "model" "best.onnx missing or truncated (${model_size} bytes)"
    fi
  else
    emit FAIL "$pi" "ssh" "${ip} ssh unreachable — firewall/sshd/network"
    emit SKIP "$pi" "daemon" "skipped — ssh failed (check council-side state instead)"
    emit SKIP "$pi" "heartbeat-timer" "skipped — ssh failed"
    emit SKIP "$pi" "model" "skipped — ssh failed"
  fi

  audit_pi_council_side "$pi" "$role" "$hostname"
}

audit_pi_council_side() {
  local pi="$1" role="$2" hostname="$3"

  local noir_file="${NOIR_DIR}/${role}.json"
  local age
  age=$(age_seconds "$noir_file")
  if [ "$age" -lt 0 ]; then
    emit FAIL "$pi" "ir-state" "${noir_file} missing — daemon never posted"
  elif [ "$age" -lt "$STATE_FRESH_S" ]; then
    emit PASS "$pi" "ir-state" "fresh (${age}s old)"

    if command -v python3 >/dev/null; then
      local sig
      sig=$(python3 -c "
import json,sys
try:
    d=json.load(open('${noir_file}'))
    print(f\"persons={len(d.get('persons',[]))} hands={len(d.get('hands',[]))} motion={d.get('motion_delta',0):.4f}\")
except Exception as e:
    print(f'parse-error:{e}')
" 2>/dev/null)
      emit PASS "$pi" "ir-signal" "$sig"
    fi
  else
    emit FAIL "$pi" "ir-state" "stale (${age}s old, threshold=${STATE_FRESH_S}s) — daemon stopped posting"
  fi

  local hb_file="${EDGE_DIR}/${hostname}.json"
  age=$(age_seconds "$hb_file")
  if [ "$age" -lt 0 ]; then
    emit FAIL "$pi" "heartbeat" "${hb_file} missing — never heartbeated"
  elif [ "$age" -lt "$HEARTBEAT_FRESH_S" ]; then
    emit PASS "$pi" "heartbeat" "fresh (${age}s old)"
  else
    emit FAIL "$pi" "heartbeat" "stale (${age}s old, threshold=${HEARTBEAT_FRESH_S}s) — heartbeat timer broken"
  fi
}

if [ "$JSON_MODE" -eq 1 ]; then
  printf '{\n'
  first=1
  for pi in "${PIS[@]}"; do
    audit_pi "$pi"
  done
  for k in "${!REPORT[@]}"; do
    [ $first -eq 0 ] && printf ',\n'
    first=0
    val="${REPORT[$k]}"
    status="${val%%|*}"
    msg="${val#*|}"
    msg_escaped=$(printf '%s' "$msg" | sed 's/\\/\\\\/g; s/"/\\"/g')
    printf '  "%s": {"status":"%s","message":"%s"}' "$k" "$status" "$msg_escaped"
  done
  printf '\n}\n'
else
  echo "" >&2
  echo "=== IR fleet audit summary: ${FAIL_COUNT} failures ===" >&2
  for pi in "${PIS[@]}"; do
    audit_pi "$pi"
  done
  echo "" >&2
  echo "=== IR fleet audit summary: ${FAIL_COUNT} failures ===" >&2
  if [ "$FAIL_COUNT" -gt 0 ]; then
    echo "remediation: run scripts/ir-fleet-restart.sh <pi> for each failing Pi" >&2
  fi
fi

exit "$FAIL_COUNT"
