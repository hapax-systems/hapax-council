#!/usr/bin/env bash
#
# LRR Phase 4 spec §3.3 — mid-collection integrity checks
#
# Runs every 24h during the Condition A data-collection window and
# verifies five invariants that, if violated, indicate the collection
# is producing invalid data:
#
#   1. The active research condition is the expected condition when one is
#      explicitly pinned. By default the check follows current.txt, so condition
#      handoffs do not leave the daily timer falsely failed.
#   2. No files listed in the active condition's frozen_files have
#      mid-collection diffs applied (via check-frozen-files.py --probe).
#   3. The stream-reactions Qdrant collection's point count is strictly
#      growing (delta vs last run > 0) — catches writer stalls.
#   4. Langfuse traces for recent director-loop runs carry the
#      condition_id metadata tag.
#   5. The collection's `collection_halt_at` marker is still null —
#      if it has been set, the window has been sealed and this timer
#      should no longer fire.
#
# Exit codes:
#   0 — all checks pass
#   1 — one or more checks failed (details in stderr)
#   2 — cannot run (registry uninitialized, qdrant unreachable, etc.)
#   3 — integrity window already sealed (collection_halt_at set); timer
#       should be disabled
#
# Runs via systemd/units/hapax-lrr-phase-4-integrity.{timer,service}.
# The timer fires once per day; each run appends a JSONL record to
# ~/hapax-state/research-registry/<cond>/integrity-check-log.jsonl so
# the operator can see the trajectory across the collection window.
#
# Usage:
#   scripts/lrr-phase-4-integrity-check.sh [--expected-condition COND]
#                                           [--quiet]
#
# Default --expected-condition: current active condition from current.txt.
# Set HAPAX_LRR_EXPECTED_CONDITION or pass --expected-condition to pin a
# particular condition during a collection window.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTRY_DIR="${HOME}/hapax-state/research-registry"
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"

EXPECTED_CONDITION="${HAPAX_LRR_EXPECTED_CONDITION:-}"
QUIET=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --expected-condition)
            EXPECTED_CONDITION="$2"
            shift 2
            ;;
        --quiet)
            QUIET=1
            shift
            ;;
        -h|--help)
            sed -n '3,37p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "lrr-phase-4-integrity-check: unknown flag $1" >&2
            exit 2
            ;;
    esac
done

log() {
    [[ ${QUIET} -eq 1 ]] && return
    echo "lrr-phase-4-integrity-check: $*"
}

fail() {
    echo "lrr-phase-4-integrity-check: FAIL — $*" >&2
}

FAILURES=0

# --- Check 1: active condition matches expected baseline ----------------------

if [[ ! -f "${REGISTRY_DIR}/current.txt" ]]; then
    fail "registry not initialized (${REGISTRY_DIR}/current.txt missing)"
    exit 2
fi

CURRENT="$(tr -d '[:space:]' < "${REGISTRY_DIR}/current.txt")"
if [[ -z "${CURRENT}" ]]; then
    fail "no active condition (current.txt empty); collection is not live"
    exit 2
fi

if [[ -z "${EXPECTED_CONDITION}" || "${EXPECTED_CONDITION}" == "current" ]]; then
    EXPECTED_CONDITION="${CURRENT}"
    log "no expected condition pinned; using active condition ${CURRENT}"
fi

if [[ "${CURRENT}" != "${EXPECTED_CONDITION}" ]]; then
    fail "active condition is ${CURRENT}, expected ${EXPECTED_CONDITION}"
    FAILURES=$((FAILURES + 1))
else
    log "check 1/5 pass — active condition is ${CURRENT}"
fi

CONDITION_YAML="${REGISTRY_DIR}/${CURRENT}/condition.yaml"
if [[ ! -f "${CONDITION_YAML}" ]]; then
    fail "condition.yaml missing at ${CONDITION_YAML}"
    exit 2
fi

# --- Check 5 (early): collection_halt_at must still be null -------------------
# Running this early means we exit 3 before wasting time on checks that no
# longer matter once the window is sealed.

HALT_AT="$(grep -E '^collection_halt_at:' "${CONDITION_YAML}" | sed 's/^collection_halt_at: *//' | tr -d '"' | tr -d "'")"
if [[ -n "${HALT_AT}" && "${HALT_AT}" != "null" && "${HALT_AT}" != "~" ]]; then
    log "collection_halt_at=${HALT_AT}; integrity window is sealed"
    log "this timer should be disabled: systemctl --user disable --now hapax-lrr-phase-4-integrity.timer"
    exit 3
fi
log "check 5/5 pass — collection_halt_at still null"

# --- Check 2: no frozen-file diffs mid-collection -----------------------------

FROZEN_FILES="$(sed -n '/^frozen_files:/,/^[a-z_]/p' "${CONDITION_YAML}" | grep -E '^\s+-\s' | sed 's/^\s*-\s*//' | tr -d '"')"
if [[ -z "${FROZEN_FILES}" ]]; then
    log "check 2/5 skip — no frozen_files declared under ${CURRENT}"
else
    FROZEN_VIOLATIONS=0
    while IFS= read -r frozen; do
        [[ -z "${frozen}" ]] && continue
        if ! "${SCRIPT_DIR}/check-frozen-files.py" --probe "${frozen}" >/dev/null 2>&1; then
            fail "frozen file ${frozen} is modified mid-collection without a covering deviation"
            FROZEN_VIOLATIONS=$((FROZEN_VIOLATIONS + 1))
        fi
    done <<< "${FROZEN_FILES}"
    if [[ ${FROZEN_VIOLATIONS} -eq 0 ]]; then
        log "check 2/5 pass — no frozen-file diffs detected"
    else
        FAILURES=$((FAILURES + FROZEN_VIOLATIONS))
    fi
fi

# --- Check 3: stream-reactions Qdrant point count is growing ------------------

LAST_COUNT_FILE="${REGISTRY_DIR}/${CURRENT}/.integrity-last-count.txt"
if ! command -v curl >/dev/null 2>&1; then
    fail "curl not available; cannot query Qdrant"
    FAILURES=$((FAILURES + 1))
else
    COUNT_JSON="$(curl -fsS -X POST "${QDRANT_URL}/collections/stream-reactions/points/count" \
        -H 'Content-Type: application/json' \
        -d '{"exact": true}' 2>/dev/null || true)"
    CURRENT_COUNT="$(echo "${COUNT_JSON}" | grep -oE '"count":\s*[0-9]+' | head -1 | grep -oE '[0-9]+')"
    if [[ -z "${CURRENT_COUNT}" ]]; then
        fail "could not read stream-reactions count from Qdrant at ${QDRANT_URL}"
        FAILURES=$((FAILURES + 1))
    else
        if [[ -f "${LAST_COUNT_FILE}" ]]; then
            LAST_COUNT="$(cat "${LAST_COUNT_FILE}")"
            if (( CURRENT_COUNT > LAST_COUNT )); then
                log "check 3/5 pass — stream-reactions grew from ${LAST_COUNT} to ${CURRENT_COUNT}"
            else
                fail "stream-reactions count stalled: last=${LAST_COUNT} current=${CURRENT_COUNT}"
                FAILURES=$((FAILURES + 1))
            fi
        else
            log "check 3/5 skip — no prior count to compare (baseline=${CURRENT_COUNT})"
        fi
        echo "${CURRENT_COUNT}" > "${LAST_COUNT_FILE}"
    fi
fi

# --- Check 4: recent director-loop traces carry condition_id ------------------
# Langfuse lookup requires API creds. Skip if not configured; do not fail.

if [[ -n "${LANGFUSE_PUBLIC_KEY:-}" && -n "${LANGFUSE_SECRET_KEY:-}" ]]; then
    LANGFUSE_HOST="${LANGFUSE_HOST:-http://localhost:3000}"
    FROM_TS="$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)"
    TRACE_JSON="$(curl -fsS -u "${LANGFUSE_PUBLIC_KEY}:${LANGFUSE_SECRET_KEY}" \
        "${LANGFUSE_HOST}/api/public/traces?name=director-loop&from_timestamp=${FROM_TS}&limit=10" 2>/dev/null || true)"
    if [[ -n "${TRACE_JSON}" ]] && echo "${TRACE_JSON}" | grep -q "${CURRENT}"; then
        log "check 4/5 pass — recent director-loop traces tagged with ${CURRENT}"
    else
        fail "no Langfuse traces in last 24h carry condition_id=${CURRENT}"
        FAILURES=$((FAILURES + 1))
    fi
else
    log "check 4/5 skip — LANGFUSE_{PUBLIC,SECRET}_KEY not set"
fi

# --- Log the run --------------------------------------------------------------

LOG_FILE="${REGISTRY_DIR}/${CURRENT}/integrity-check-log.jsonl"
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '{"ts":"%s","condition":"%s","failures":%d,"current_count":%s}\n' \
    "${NOW}" "${CURRENT}" "${FAILURES}" "${CURRENT_COUNT:-null}" >> "${LOG_FILE}"

if [[ ${FAILURES} -eq 0 ]]; then
    log "integrity check PASSED for ${CURRENT}"
    exit 0
fi

fail "${FAILURES} check(s) failed for ${CURRENT}"
exit 1
