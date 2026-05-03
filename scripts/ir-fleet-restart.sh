#!/usr/bin/env bash
# ir-fleet-restart.sh — restart procedure for the 3-node NoIR IR perception fleet.
#
# Idempotent. Per-Pi steps:
#   1. SSH reachability check
#   2. Stop running ir-edge daemon (TERM, then KILL after 5s if still running)
#   3. Install/refresh hapax-heartbeat.{service,timer} from staged unit files
#      (located at ~/hapax-edge/hapax-heartbeat.{service,timer} on the Pi)
#   4. systemctl daemon-reload
#   5. systemctl enable --now hapax-heartbeat.timer
#   6. Restart ir-edge daemon as a direct background process (matches the
#      stable production pattern: pid=875 ran 10 days+ as direct process)
#   7. Wait 8s, verify daemon is publishing fresh state to council
#
# Usage:
#   scripts/ir-fleet-restart.sh             # restart all 3 IR Pis
#   scripts/ir-fleet-restart.sh pi1         # restart one
#   scripts/ir-fleet-restart.sh --dry-run   # show plan without executing
#
# Pi-6 SSH unreachable: scripts skips with FAIL and prints operator-action notice.

set -uo pipefail

declare -A FLEET=(
  [pi1]="192.168.68.78|hapax-pi1|desk"
  [pi2]="192.168.68.52|hapax-pi2|room"
  [pi6]="192.168.68.74|hapax-pi6|overhead"
)

DRY_RUN=0
PIS=()
for arg in "$@"; do
  case "$arg" in
    --dry-run|-n) DRY_RUN=1 ;;
    pi1|pi2|pi6)  PIS+=("$arg") ;;
    -h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "ir-fleet-restart: unknown arg: $arg" >&2; exit 2 ;;
  esac
done
[ ${#PIS[@]} -eq 0 ] && PIS=(pi1 pi2 pi6)

run_remote() {
  local ip="$1" cmd="$2"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  [dry-run] ssh hapax@${ip} '${cmd}'" >&2
    return 0
  fi
  ssh -o ConnectTimeout=3 -o BatchMode=yes "hapax@${ip}" "$cmd"
}

restart_pi() {
  local pi="$1"
  local spec="${FLEET[$pi]}"
  local ip="${spec%%|*}"
  local rest="${spec#*|}"
  local hostname="${rest%%|*}"
  local role="${rest##*|}"

  echo "" >&2
  echo "=== ${pi} (${hostname}, role=${role}, ${ip}) ===" >&2

  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  [dry-run] would ssh-check hapax@${ip}" >&2
  elif ! ssh -o ConnectTimeout=3 -o BatchMode=yes "hapax@${ip}" "true" 2>/dev/null; then
    echo "FAIL: ${pi} ssh unreachable — operator must restart Pi directly" >&2
    if [ "$pi" = "pi6" ]; then
      echo "      Pi-6 has known sshd/firewall issue. Operator action: power-cycle or local console." >&2
    fi
    return 1
  else
    echo "PASS: ${pi} ssh reachable" >&2
  fi

  local repo_root
  repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
  local src_dir="${repo_root}/pi-edge"

  echo "step 1/5: rsyncing latest hapax-heartbeat.{service,timer,py} to Pi" >&2
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  [dry-run] rsync ${src_dir}/hapax-heartbeat.{service,timer,py} hapax@${ip}:~/hapax-edge/" >&2
  else
    rsync -az --timeout=10 \
      "${src_dir}/hapax-heartbeat.service" \
      "${src_dir}/hapax-heartbeat.timer" \
      "${src_dir}/hapax-heartbeat.py" \
      "hapax@${ip}:~/hapax-edge/" || {
        echo "FAIL: rsync to ${ip} failed" >&2
        return 1
      }
  fi

  echo "step 2/5: stopping ir-edge daemon" >&2
  run_remote "$ip" "
    pid=\$(pgrep -f 'hapax_ir_edge' | head -1)
    if [ -n \"\$pid\" ]; then
      kill -TERM \$pid 2>/dev/null || true
      for i in 1 2 3 4 5; do
        sleep 1
        kill -0 \$pid 2>/dev/null || break
      done
      kill -KILL \$pid 2>/dev/null || true
    fi
  "

  echo "step 3/5: installing hapax-heartbeat.{service,timer} (role=${role})" >&2
  run_remote "$ip" "
    cd ~/hapax-edge || exit 1
    if [ ! -f hapax-heartbeat.service ] || [ ! -f hapax-heartbeat.timer ]; then
      echo 'ERROR: hapax-heartbeat unit files not staged in ~/hapax-edge/' >&2
      exit 2
    fi
    sudo install -m 0644 hapax-heartbeat.service /etc/systemd/system/hapax-heartbeat.service
    sudo install -m 0644 hapax-heartbeat.timer   /etc/systemd/system/hapax-heartbeat.timer
    sudo sed -i 's|^Environment=HEARTBEAT_ROLE=.*|Environment=HEARTBEAT_ROLE=${role}|' /etc/systemd/system/hapax-heartbeat.service
    sudo systemctl daemon-reload
    sudo systemctl enable --now hapax-heartbeat.timer
    sudo systemctl restart hapax-heartbeat.service
  "

  echo "step 4/5: restarting ir-edge daemon (direct background process)" >&2
  run_remote "$ip" "
    cd ~/hapax-edge || exit 1
    nohup .venv/bin/python hapax_ir_edge.py --role=${role} --hostname=${hostname} > /tmp/ir-edge.log 2>&1 &
    disown
    sleep 2
    pgrep -f 'hapax_ir_edge' >/dev/null || { echo 'ERROR: daemon failed to start; tail of /tmp/ir-edge.log:' >&2; tail -20 /tmp/ir-edge.log >&2; exit 3; }
  "

  echo "step 5/5: verifying state freshness on council side" >&2
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  [dry-run] would wait 8s and check ~/hapax-state/pi-noir/${role}.json" >&2
    return 0
  fi
  sleep 8
  local noir_file="${HOME}/hapax-state/pi-noir/${role}.json"
  if [ ! -f "$noir_file" ]; then
    echo "FAIL: ${noir_file} missing after restart" >&2
    return 1
  fi
  local mtime now age
  mtime=$(stat -c '%Y' "$noir_file")
  now=$(date +%s)
  age=$((now - mtime))
  if [ "$age" -lt 30 ]; then
    echo "PASS: ${pi} restart complete — state fresh (${age}s old)" >&2
    return 0
  else
    echo "FAIL: ${pi} state stale (${age}s old) — daemon not posting" >&2
    return 1
  fi
}

EXIT_CODE=0
for pi in "${PIS[@]}"; do
  restart_pi "$pi" || EXIT_CODE=$((EXIT_CODE + 1))
done

echo "" >&2
echo "=== IR fleet restart summary: ${EXIT_CODE} failures ===" >&2
exit "$EXIT_CODE"
