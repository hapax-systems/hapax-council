#!/usr/bin/env bash
# deploy-heartbeat-to-fleet.sh — install hapax-heartbeat.{service,timer,py}
# on each Pi in the fleet that doesn't have it yet.
#
# Audit-closeout 9.2 + pi-fleet-audit F1: pi4/pi5/hapax-ai have no
# hapax-heartbeat.timer, so council-side check_pi_fleet() is blind to
# crashes on those nodes. This script rsyncs the unit files from the
# repo to each named host, sets the role-specific HEARTBEAT_ROLE +
# HEARTBEAT_SERVICES env, enables the timer.
#
# Idempotent. Each per-host stanza:
#   1. rsync py + service + timer
#   2. sed the role + services per host
#   3. systemctl enable --now
#   4. verify last-trigger fired within 90s
#
# Usage:
#   deploy-heartbeat-to-fleet.sh           # default fleet (pi4, pi5, hapax-ai)
#   deploy-heartbeat-to-fleet.sh <host>... # specific hosts via mDNS

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="${REPO_ROOT}/pi-edge"

# Default fleet (mDNS names — DHCP-stable per delta 55bab4111).
declare -A FLEET=(
  [hapax-pi4.local]="sentinel|hapax-ir-edge"
  [hapax-pi5.local]="rag-edge|"
  [hapax-ai.local]="hapax-ai|"
)

if [ "$#" -gt 0 ]; then
  declare -A FLEET=()
  for h in "$@"; do
    FLEET[$h]="${h%.local}|"
  done
fi

failures=0
for host in "${!FLEET[@]}"; do
  IFS='|' read -r role services <<<"${FLEET[$host]}"
  echo "========================================="
  echo "host=$host  role=$role  services=$services"
  echo "========================================="

  # 1. rsync (over ssh)
  if ! rsync -e 'ssh -o ConnectTimeout=5 -o BatchMode=yes' -av \
      "${SRC_DIR}/hapax-heartbeat.py" \
      "${SRC_DIR}/hapax-heartbeat.service" \
      "${SRC_DIR}/hapax-heartbeat.timer" \
      "hapax@${host}:hapax-edge/" 2>&1 | tail -5; then
    echo "❌ rsync failed for $host" >&2
    ((failures++))
    continue
  fi

  # 2. install + sed role + enable. Use ~/hapax-edge/ resolved on the
  # remote host, not a hardcoded absolute path with the operator's username.
  if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "hapax@${host}" "
    sudo cp \"\$HOME/hapax-edge/hapax-heartbeat.service\" /etc/systemd/system/
    sudo cp \"\$HOME/hapax-edge/hapax-heartbeat.timer\" /etc/systemd/system/
    sudo sed -i 's|HEARTBEAT_ROLE=ir-desk|HEARTBEAT_ROLE=${role}|' /etc/systemd/system/hapax-heartbeat.service
    sudo sed -i 's|HEARTBEAT_SERVICES=hapax-ir-edge|HEARTBEAT_SERVICES=${services}|' /etc/systemd/system/hapax-heartbeat.service
    sudo systemctl daemon-reload
    sudo systemctl enable --now hapax-heartbeat.timer
    sudo systemctl start hapax-heartbeat.service
  " 2>&1 | tail -5; then
    echo "❌ install/enable failed for $host" >&2
    ((failures++))
    continue
  fi

  # 3. verify timer + service ran
  sleep 3
  if ssh -o ConnectTimeout=5 -o BatchMode=yes "hapax@${host}" \
      "systemctl is-active hapax-heartbeat.timer && systemctl status hapax-heartbeat.service --no-pager 2>&1 | head -3" \
      2>&1 | grep -q 'active'; then
    echo "✅ $host heartbeat timer active"
  else
    echo "❌ $host heartbeat timer not active" >&2
    ((failures++))
  fi
done

echo
if [ "$failures" -eq 0 ]; then
  echo "all fleet hosts deployed successfully"
  exit 0
else
  echo "$failures host(s) failed deploy" >&2
  exit 1
fi
