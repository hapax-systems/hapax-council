#!/usr/bin/env bash
#
# LRR Phase 3 item 11 — brio-operator 28fps deficit re-measurement
#
# Runs a 5-minute fps measurement on the brio-operator camera while
# the studio compositor is running its normal load. Reads the
# per-camera fps exported by the compositor's Prometheus endpoint on
# 127.0.0.1:9482 and logs each sample to
# `~/hapax-state/camera-validation/brio-operator-fps-<date>.log`.
#
# Decision rule (per Phase 3 plan §5):
#   - ~30.5 fps steady → root cause closed (was TabbyAPI inference
#     contention; 24/7 resilience + inference offload fixed it)
#   - ~28.5 fps steady → 4 original candidates remain (hero=True,
#     metrics lock, queue depth, hardware cause)
#
# The script prints the mean fps + sample count at exit and uses the
# mean to emit a one-line verdict. It does NOT attempt to take
# follow-up action — the verdict lands in the log and the operator
# decides the next step.
#
# Exit codes:
#   0 — measurement complete (regardless of verdict; verdict is
#        communicated in the log + stdout, not the exit code)
#   1 — measurement failed (compositor metrics unreachable or the
#        fps series stayed at 0)
#   2 — cannot run (state dir not writable, etc.)
#
# Usage:
#   scripts/measure-brio-operator-fps.sh [--duration-s N]
#                                         [--metrics-url URL]
#                                         [--camera ROLE]
#
# Defaults:
#   --duration-s 300                     (5 min per plan §5)
#   --metrics-url http://127.0.0.1:9482/metrics
#   --camera brio-operator

set -uo pipefail

STATE_DIR="${HOME}/hapax-state/camera-validation"

DURATION_S=300
METRICS_URL="http://127.0.0.1:9482/metrics"
CAMERA_ROLE="brio-operator"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --duration-s)
            DURATION_S="$2"
            shift 2
            ;;
        --metrics-url)
            METRICS_URL="$2"
            shift 2
            ;;
        --camera)
            CAMERA_ROLE="$2"
            shift 2
            ;;
        -h|--help)
            sed -n '3,38p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "measure-brio-operator-fps: unknown flag $1" >&2
            exit 2
            ;;
    esac
done

mkdir -p "${STATE_DIR}" || {
    echo "measure-brio-operator-fps: cannot create state dir ${STATE_DIR}" >&2
    exit 2
}

if ! command -v curl >/dev/null 2>&1; then
    echo "measure-brio-operator-fps: curl not found" >&2
    exit 2
fi

DATE_STAMP="$(date -u +%Y-%m-%d)"
LOG_FILE="${STATE_DIR}/${CAMERA_ROLE}-fps-${DATE_STAMP}.log"

# The metric exposed by `agents/studio_compositor/source_registry.py` (or
# similar) is expected to be `studio_camera_fps{role="brio-operator"}`.
# The script accepts any metric name matching `.*fps.*role="<role>".*`.
METRIC_PATTERN="fps.*role=\"${CAMERA_ROLE}\""

{
    echo "# LRR Phase 3 item 11 brio-operator fps re-measurement"
    echo "# Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "# Duration: ${DURATION_S} s"
    echo "# Metrics URL: ${METRICS_URL}"
    echo "# Camera role: ${CAMERA_ROLE}"
    echo "# Metric pattern: ${METRIC_PATTERN}"
    echo "# Columns: iso_ts fps"
} > "${LOG_FILE}"

echo "measure-brio-operator-fps: sampling ${CAMERA_ROLE} for ${DURATION_S}s"
echo "measure-brio-operator-fps: log ${LOG_FILE}"

END_TS=$(( $(date +%s) + DURATION_S ))
SAMPLES=0
NONZERO_SAMPLES=0
SUM_FPS=0.0

while (( $(date +%s) < END_TS )); do
    RESPONSE="$(curl -fsS "${METRICS_URL}" 2>/dev/null || true)"
    if [[ -z "${RESPONSE}" ]]; then
        sleep 1
        continue
    fi
    FPS_LINE="$(echo "${RESPONSE}" | grep -E "${METRIC_PATTERN}" | grep -v '^#' | head -1)"
    if [[ -z "${FPS_LINE}" ]]; then
        sleep 1
        continue
    fi
    FPS="$(echo "${FPS_LINE}" | awk '{print $NF}')"
    ISO_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '%s %s\n' "${ISO_TS}" "${FPS}" >> "${LOG_FILE}"
    SAMPLES=$((SAMPLES + 1))
    IS_NONZERO="$(awk -v f="${FPS}" 'BEGIN { print (f > 0.01) ? 1 : 0 }')"
    if [[ ${IS_NONZERO} -eq 1 ]]; then
        NONZERO_SAMPLES=$((NONZERO_SAMPLES + 1))
        SUM_FPS="$(awk -v s="${SUM_FPS}" -v f="${FPS}" 'BEGIN { printf "%.3f", s + f }')"
    fi
    sleep 1
done

if [[ ${SAMPLES} -eq 0 ]]; then
    echo "measure-brio-operator-fps: no metric samples read from ${METRICS_URL}" >&2
    exit 1
fi
if [[ ${NONZERO_SAMPLES} -eq 0 ]]; then
    echo "measure-brio-operator-fps: fps stayed at 0 across ${SAMPLES} samples (compositor not running?)" >&2
    exit 1
fi

MEAN_FPS="$(awk -v s="${SUM_FPS}" -v n="${NONZERO_SAMPLES}" 'BEGIN { printf "%.2f", s / n }')"

# Verdict: > 29.5 → root-cause-closed, else deficit-persists
VERDICT="deficit-persists"
if (( $(awk -v m="${MEAN_FPS}" 'BEGIN { print (m > 29.5) ? 1 : 0 }') )); then
    VERDICT="root-cause-closed"
fi

{
    echo "# SUMMARY"
    echo "# samples: ${SAMPLES}"
    echo "# nonzero_samples: ${NONZERO_SAMPLES}"
    echo "# mean_fps: ${MEAN_FPS}"
    echo "# verdict: ${VERDICT}"
} >> "${LOG_FILE}"

echo "measure-brio-operator-fps: samples=${SAMPLES} nonzero=${NONZERO_SAMPLES} mean=${MEAN_FPS} verdict=${VERDICT}"
echo "measure-brio-operator-fps: summary appended to ${LOG_FILE}"
exit 0
