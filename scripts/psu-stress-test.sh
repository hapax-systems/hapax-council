#!/usr/bin/env bash
#
# LRR Phase 3 spec §3 / plan §3 — PSU audit + combined-load stress test
#
# Runs a 30-minute combined-load stress test that exercises TabbyAPI
# (GPU inference), the studio compositor (GPU encode + Cairo), the
# imagination daemon (wgpu render), and Reverie (stim mixer) at the
# same time. While the load is running, this script polls
# `nvidia-smi --query-gpu=power.draw,temperature.gpu,clocks_throttle_reasons.hw_power_brake_slowdown`
# once per second and logs the trace to
# `~/hapax-state/hardware-validation/psu-<date>.log`.
#
# Success criteria (per spec §3):
#   - Zero `hw_power_brake_slowdown` events during the window
#   - Peak power.draw stays under (PSU_RATING × 0.8)
#
# NOTE: this script does NOT actually start TabbyAPI / compositor /
# imagination / reverie. Those are managed by systemd user units. The
# expected invocation is:
#
#   1. Operator verifies all four units are active:
#        systemctl --user is-active tabbyapi hapax-imagination \
#          studio-compositor hapax-reverie
#   2. Operator triggers load on each surface (voice session for
#      tabbyapi, livestream for compositor, visual surface for
#      imagination + reverie)
#   3. Operator runs this script; it polls + logs + computes the
#      summary at the end
#
# So the script is the MONITORING harness, not the LOAD GENERATOR. That
# matches the spec's "operator consent + hardware stability" gate at
# the §3 risks paragraph — we never autonomously drive 30 min of GPU
# load without the operator holding the wheel.
#
# Exit codes:
#   0 — completed 30 min with no slowdown events and peak below budget
#   1 — slowdown events detected OR peak power exceeded budget
#   2 — cannot run (nvidia-smi missing, state dir not writable, etc.)
#
# Usage:
#   scripts/psu-stress-test.sh [--duration-s N] [--psu-rating-w W]
#                               [--gpu-index I]
#
# Defaults:
#   --duration-s 1800       (30 min, per spec)
#   --psu-rating-w 1000     (operator verifies PSU + passes explicit)
#   --gpu-index 0           (primary GPU — 5060 Ti in current build)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${HOME}/hapax-state/hardware-validation"

DURATION_S=1800
PSU_RATING_W=1000
GPU_INDEX=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --duration-s)
            DURATION_S="$2"
            shift 2
            ;;
        --psu-rating-w)
            PSU_RATING_W="$2"
            shift 2
            ;;
        --gpu-index)
            GPU_INDEX="$2"
            shift 2
            ;;
        -h|--help)
            sed -n '3,47p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "psu-stress-test: unknown flag $1" >&2
            exit 2
            ;;
    esac
done

if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "psu-stress-test: nvidia-smi not found; cannot run PSU audit" >&2
    exit 2
fi

mkdir -p "${STATE_DIR}" || {
    echo "psu-stress-test: cannot create state dir ${STATE_DIR}" >&2
    exit 2
}

DATE_STAMP="$(date -u +%Y-%m-%d)"
LOG_FILE="${STATE_DIR}/psu-${DATE_STAMP}.log"
BUDGET_W="$(awk -v r="${PSU_RATING_W}" 'BEGIN { printf "%.1f", r * 0.8 }')"

echo "psu-stress-test: starting ${DURATION_S}s poll on GPU ${GPU_INDEX}"
echo "psu-stress-test: PSU rating ${PSU_RATING_W}W, 80% budget ${BUDGET_W}W"
echo "psu-stress-test: log ${LOG_FILE}"

{
    echo "# LRR Phase 3 item 3 PSU stress test"
    echo "# Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "# GPU index: ${GPU_INDEX}"
    echo "# PSU rating: ${PSU_RATING_W} W"
    echo "# 80% budget: ${BUDGET_W} W"
    echo "# Duration: ${DURATION_S} s"
    echo "# Columns: iso_ts power_w temp_c brake_reason"
} > "${LOG_FILE}"

END_TS=$(( $(date +%s) + DURATION_S ))
PEAK_POWER=0
BRAKE_COUNT=0
SAMPLE_COUNT=0

while (( $(date +%s) < END_TS )); do
    SAMPLE="$(nvidia-smi \
        --query-gpu=power.draw,temperature.gpu,clocks_throttle_reasons.hw_power_brake_slowdown \
        --format=csv,noheader,nounits \
        --id="${GPU_INDEX}" 2>/dev/null || true)"
    if [[ -z "${SAMPLE}" ]]; then
        sleep 1
        continue
    fi
    POWER="$(echo "${SAMPLE}" | awk -F', ' '{print $1}' | tr -d ' ')"
    TEMP="$(echo "${SAMPLE}" | awk -F', ' '{print $2}' | tr -d ' ')"
    BRAKE="$(echo "${SAMPLE}" | awk -F', ' '{print $3}' | tr -d ' ')"
    ISO_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '%s %s %s %s\n' "${ISO_TS}" "${POWER}" "${TEMP}" "${BRAKE}" >> "${LOG_FILE}"
    SAMPLE_COUNT=$((SAMPLE_COUNT + 1))
    if [[ "${BRAKE}" == "Active" ]]; then
        BRAKE_COUNT=$((BRAKE_COUNT + 1))
    fi
    # Floating-point max via awk
    PEAK_POWER="$(awk -v a="${PEAK_POWER}" -v b="${POWER}" 'BEGIN { if (b > a) print b; else print a }')"
    sleep 1
done

# Summary
{
    echo "# SUMMARY"
    echo "# samples: ${SAMPLE_COUNT}"
    echo "# peak_power_w: ${PEAK_POWER}"
    echo "# hw_power_brake_slowdown_events: ${BRAKE_COUNT}"
    echo "# budget_w: ${BUDGET_W}"
} >> "${LOG_FILE}"

echo "psu-stress-test: samples=${SAMPLE_COUNT} peak=${PEAK_POWER}W brake=${BRAKE_COUNT}"
echo "psu-stress-test: summary appended to ${LOG_FILE}"

OVER_BUDGET="$(awk -v p="${PEAK_POWER}" -v b="${BUDGET_W}" 'BEGIN { print (p > b) ? 1 : 0 }')"
if [[ ${BRAKE_COUNT} -gt 0 || ${OVER_BUDGET} -eq 1 ]]; then
    echo "psu-stress-test: FAIL — brake=${BRAKE_COUNT} peak=${PEAK_POWER}W budget=${BUDGET_W}W" >&2
    exit 1
fi
echo "psu-stress-test: PASS — no slowdown, peak under budget"
exit 0
