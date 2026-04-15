#!/usr/bin/env bash
# rename-runbook.sh — rename the existing Pi fleet from hapax-piN → role-based names
# Pre-staged 2026-04-15 (epsilon). DO NOT RUN until operator declares a maintenance window.
#
# Plan reference: relay context 2026-04-15-epsilon-pi-fleet-deployment-plan.md §2 + §7.1
#
# WHAT THIS DOES (per Pi):
#   1. SSH to the Pi as user hapax
#   2. sudo hostnamectl set-hostname <new>
#   3. sudo sed -i /etc/hosts for the 127.0.1.1 line
#   4. sudo systemctl restart avahi-daemon (so .local resolves to new name)
#   5. Verify: hostname + getent hosts <new>.local
#   6. [Pi-side services that encode hostname in unit names or paths — manual review]
#
# WHAT THIS DOES NOT DO:
#   - Rename any systemd units that have hostname in their filename
#   - Update /etc/machine-id or any DHCP hostname broadcast (use dhclient hook if needed)
#   - Touch the workstation /etc/hosts (already dual-bound as of 2026-04-15)
#   - Update agents/health_monitor/constants.py::PI_FLEET on the workstation
#     (that's a separate council-side PR, see plan §7.2)
#
# PRE-FLIGHT CHECKLIST (operator runs before invoking this):
#   [ ] Livestream is not actively streaming to a public CDN
#   [ ] Hermes 3 quant job is NOT in progress (it finishes ~6h after 2026-04-14 20:25Z)
#   [ ] All 5 Pis are reachable via ssh hapax@hapax-piN
#   [ ] Workstation /etc/hosts already has dual-bind (verify: getent hosts hapax-ir-desk returns 192.168.68.78)
#   [ ] You have a terminal open to each Pi in a tmux session for parallel cleanup
#   [ ] A rollback plan: the script keeps /etc/hosts.bak-<timestamp> on each Pi; reverting is hostname revert + /etc/hosts restore + avahi restart
#
# USAGE:
#   bash rename-runbook.sh                  # dry run, prints commands without executing
#   bash rename-runbook.sh --execute        # actually run the sequence across all 5 Pis
#   bash rename-runbook.sh --execute --pi hapax-pi1   # run on one Pi only
#
# RECOMMENDED APPROACH: run with --pi hapax-pi4 first (sentinel, lowest-risk), verify,
# then --pi hapax-pi5 (rag, also low-risk), then the three IR Pis, then the hub last
# (the hub has 8 sync agents and album-identifier running on it, highest risk).

set -euo pipefail

DRY_RUN=true
ONLY_PI=""

while [ $# -gt 0 ]; do
    case "$1" in
        --execute) DRY_RUN=false; shift ;;
        --pi) ONLY_PI="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# Rename map: old_hostname → new_hostname
declare -A RENAME_MAP=(
    ["hapax-pi1"]="hapax-ir-desk"
    ["hapax-pi2"]="hapax-ir-room"
    ["hapax-pi4"]="hapax-sentinel"
    ["hapax-pi5"]="hapax-rag"
    ["hapax-pi6"]="hapax-hub"
)

# Recommended order (lowest risk first)
ORDER=(hapax-pi4 hapax-pi5 hapax-pi1 hapax-pi2 hapax-pi6)

run_on_pi() {
    local old="$1"
    local new="$2"
    local timestamp
    timestamp=$(date +%Y%m%d-%H%M%S)

    echo
    echo "=== ${old} → ${new} ==="

    if ! ping -c1 -W2 "${old}" &>/dev/null; then
        echo "SKIP: ${old} is not reachable via /etc/hosts"
        return 1
    fi

    local cmd
    cmd=$(cat <<PI_SHELL
set -euo pipefail
echo 'Pre-change state:'
echo "  hostname: \$(hostname)"
echo "  /etc/hostname: \$(cat /etc/hostname)"
echo "  127.0.1.1 line: \$(grep '^127.0.1.1' /etc/hosts || echo '(none)')"

# Backup
sudo cp /etc/hosts /etc/hosts.bak-${timestamp}
sudo cp /etc/hostname /etc/hostname.bak-${timestamp}

# Rename
sudo hostnamectl set-hostname ${new}
# Update /etc/hosts 127.0.1.1 line to the new name
sudo sed -i "s|^127\.0\.1\.1.*|127.0.1.1  ${new}|" /etc/hosts

# Restart avahi so .local resolves
sudo systemctl restart avahi-daemon

echo 'Post-change state:'
echo "  hostname: \$(hostname)"
echo "  /etc/hostname: \$(cat /etc/hostname)"
echo "  127.0.1.1 line: \$(grep '^127.0.1.1' /etc/hosts || echo '(none)')"

# Verify avahi publishes the new name
sleep 1
avahi-resolve-host-name -n ${new}.local || echo 'avahi-resolve failed (may need ~5s to propagate)'
PI_SHELL
    )

    if $DRY_RUN; then
        echo "DRY RUN — would execute:"
        echo "ssh hapax@${old} \"${cmd}\""
        echo "(add --execute to actually run)"
    else
        ssh hapax@"${old}" "${cmd}"
        echo "--- post-rename workstation-side verification ---"
        # Note: we still address the Pi by its OLD name because /etc/hosts
        # is dual-bound; the rename changed the Pi's OWN hostname, not the
        # workstation's view of it via /etc/hosts alias.
        getent hosts "${new}" && echo "OK: workstation resolves ${new}"
        getent hosts "${new}.local" 2>/dev/null && echo "OK: avahi resolves ${new}.local"
    fi
}

echo "=== rename-runbook.sh ==="
echo "DRY_RUN=${DRY_RUN}"
echo "ONLY_PI=${ONLY_PI:-(all)}"

for pi in "${ORDER[@]}"; do
    if [ -n "${ONLY_PI}" ] && [ "${ONLY_PI}" != "${pi}" ]; then
        continue
    fi
    new="${RENAME_MAP[$pi]}"
    run_on_pi "${pi}" "${new}"
done

echo
echo "=== done ==="
if $DRY_RUN; then
    echo "This was a DRY RUN. Add --execute to actually perform the renames."
else
    echo "Verify each Pi's heartbeat is still writing to ~/hapax-state/edge/"
    echo "Verify each Pi's services are still running: ssh to each new hostname and run 'systemctl --user status'"
    echo
    echo "NEXT: follow-up cleanup commit to remove old hapax-piN aliases from workstation"
    echo "/etc/hosts after a 1-week soak confirms nothing references the legacy names."
fi
