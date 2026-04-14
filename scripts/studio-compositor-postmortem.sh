#!/usr/bin/env bash
# studio-compositor-postmortem.sh — postmortem capture hook
#
# Wired via ``ExecStopPost=`` in ``studio-compositor.service`` so every
# watchdog timeout, segfault, restart, or manual stop yields a dated
# snapshot of the rig state at the moment the compositor was tearing
# down. Without this, Sprint 6 F7 noted that the only survivors of a
# compositor crash are a counter increment + plaintext journal lines —
# the per-frame state, GPU snapshot, and /dev/shm artifacts are lost.
#
# Captures (each with a 2-second subprocess timeout so a hung tool can
# never block the shutdown path):
#
#   * ``$EXIT_STATUS`` / ``$EXIT_CODE`` / ``$SERVICE_RESULT`` from
#     systemd — the authoritative reason for the stop
#   * ``systemctl show`` property dump (uptime, restart count, watchdog
#     state, main PID, last exit reason)
#   * last 120 journal lines from the compositor
#   * ``nvidia-smi`` dump with compute + graphics app detail
#   * ``/dev/shm/hapax-compositor/`` state file listing + small-file
#     contents (fx-current.txt, any .json)
#   * ``/dev/shm/hapax-imagination/pool_metrics.json`` snapshot
#   * last 32 lines of the compositor's ``:9482/metrics`` scrape (via
#     ``timeout 1 curl`` — the compositor is stopping so this may fail,
#     which is fine — the file just records that the metrics endpoint
#     was unreachable at stop time)
#
# The script NEVER exits non-zero. A broken postmortem hook must never
# block the shutdown cascade.
#
# Output directory: ``~/hapax-state/postmortem/studio-compositor/{ts}/``
# Keeps the last 30 postmortems; older ones are pruned.
#
# Refs: livestream-performance-map Sprint 6 F7 / W1.5.
set +e  # never exit non-zero from this hook

TS=$(date +%Y-%m-%dT%H-%M-%S)
OUT_DIR="${HOME}/hapax-state/postmortem/studio-compositor/${TS}"
mkdir -p "${OUT_DIR}" || exit 0

# 1. systemd-provided stop reason (set in the ExecStopPost environment)
{
    echo "=== systemd stop reason ==="
    echo "EXIT_CODE=${EXIT_CODE:-unset}"
    echo "EXIT_STATUS=${EXIT_STATUS:-unset}"
    echo "SERVICE_RESULT=${SERVICE_RESULT:-unset}"
    echo "MAINPID=${MAINPID:-unset}"
    echo "INVOCATION_ID=${INVOCATION_ID:-unset}"
    echo
    echo "=== systemctl show ==="
    timeout 2 systemctl --user show studio-compositor.service 2>&1 \
        | grep -E "^(MainPID|SubState|ActiveState|Result|NRestarts|WatchdogLastPingTimestamp|ExecMainStartTimestamp|ExecMainExitTimestamp|ExecMainStatus)="
} > "${OUT_DIR}/systemd-state.txt" 2>&1

# 2. last 120 journal lines from the compositor
timeout 2 journalctl --user -u studio-compositor.service -n 120 --no-pager \
    > "${OUT_DIR}/journal.txt" 2>&1

# 3. nvidia-smi snapshots
{
    echo "=== nvidia-smi (default) ==="
    timeout 2 nvidia-smi 2>&1
    echo
    echo "=== compute-apps ==="
    timeout 2 nvidia-smi --query-compute-apps=pid,process_name,gpu_uuid,used_memory --format=csv 2>&1
    echo
    echo "=== per-process sm/mem/enc ==="
    timeout 2 nvidia-smi pmon -c 1 -s mu 2>&1
    echo
    echo "=== throttle reasons ==="
    timeout 2 nvidia-smi --query-gpu=index,name,clocks_throttle_reasons.hw_power_brake_slowdown,clocks_throttle_reasons.sw_thermal_slowdown,power.draw,temperature.gpu --format=csv 2>&1
} > "${OUT_DIR}/nvidia-smi.txt" 2>&1

# 4. /dev/shm compositor state
if [[ -d /dev/shm/hapax-compositor ]]; then
    {
        echo "=== /dev/shm/hapax-compositor/ listing ==="
        timeout 1 ls -la /dev/shm/hapax-compositor/ 2>&1
        echo
        echo "=== fx-current.txt ==="
        timeout 1 cat /dev/shm/hapax-compositor/fx-current.txt 2>/dev/null
        echo
        echo "=== graph-mutation.json (if present) ==="
        timeout 1 cat /dev/shm/hapax-compositor/graph-mutation.json 2>/dev/null
    } > "${OUT_DIR}/shm-compositor.txt" 2>&1
fi

if [[ -f /dev/shm/hapax-imagination/pool_metrics.json ]]; then
    timeout 1 cat /dev/shm/hapax-imagination/pool_metrics.json \
        > "${OUT_DIR}/reverie-pool-metrics.json" 2>&1
fi

# 5. last metrics scrape (may fail — compositor is stopping)
timeout 1 curl -s http://127.0.0.1:9482/metrics \
    > "${OUT_DIR}/metrics-at-stop.txt" 2>&1 || \
    echo "# metrics unreachable at stop time (expected)" \
        > "${OUT_DIR}/metrics-at-stop.txt"

# 6. rotate old postmortems — keep only the last 30
POSTMORTEM_ROOT="${HOME}/hapax-state/postmortem/studio-compositor"
if [[ -d "${POSTMORTEM_ROOT}" ]]; then
    # List postmortem directories by mtime (newest first), skip the first 30,
    # delete the rest. ``ls -1t`` is fine here — directory names are
    # timestamps so there are no tricky filenames to worry about.
    find "${POSTMORTEM_ROOT}" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' 2>/dev/null \
        | sort -rn \
        | awk 'NR>30 {print $2}' \
        | xargs -r rm -rf
fi

# Never propagate failure — the shutdown path must always continue.
exit 0
