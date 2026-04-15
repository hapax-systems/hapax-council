#!/usr/bin/env bash
#
# LRR Phase 4 spec §3.6 — data integrity lock at Phase 4 completion
#
# Seals Condition A data for analysis by:
#
#   1. Computing sha256 of every JSONL reactor log file that was written
#      during Condition A's collection window.
#   2. Recording the checksums + file sizes + line counts at
#      ~/hapax-state/research-registry/<cond>/data-checksums.txt
#   3. Taking a Qdrant snapshot of the stream-reactions collection
#      (full collection, not just Condition A points, because Qdrant
#      snapshots operate on the whole collection; the payload filter
#      for Condition A is applied at analysis time, not at snapshot time).
#   4. Storing the snapshot tarball at
#      ~/hapax-state/research-registry/<cond>/qdrant-snapshot.tgz
#   5. Writing a lock manifest at
#      ~/hapax-state/research-registry/<cond>/integrity-lock.yaml
#      recording the timestamp, the git HEAD SHA, the set of files
#      sealed, and the Qdrant snapshot metadata.
#
# The lock is idempotent-but-explicit: re-running on the same condition
# refuses to overwrite an existing lock manifest unless --force is
# given. This matches the P-3 invariant (conditions never close) —
# the integrity lock is a one-shot seal, not a running state.
#
# Expected invocation is once, by the operator, at the end of Phase 4
# just before `research-registry.py set-collection-halt`. The ordering
# matters: lock first (while the window is still conceptually live),
# then set the halt marker (which forbids further collection).
#
# Exit codes:
#   0 — lock created successfully
#   1 — lock already exists (and --force not given), or a checksum /
#        snapshot step failed
#   2 — cannot run (registry uninitialized, condition missing, etc.)
#
# Usage:
#   scripts/lrr-phase-4-integrity-lock.sh [--condition COND] [--force]
#                                          [--skip-snapshot]
#
# Default --condition: the value of ~/hapax-state/research-registry/current.txt
#
# --skip-snapshot: skip the Qdrant export (useful for dry-runs + tests
# where Qdrant is not reachable; the checksums are still written).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REGISTRY_DIR="${HOME}/hapax-state/research-registry"
REACTOR_LOGS_DIR="${REACTOR_LOGS_DIR:-${HOME}/hapax-state/reactor-logs}"
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
QDRANT_COLLECTION="${QDRANT_COLLECTION:-stream-reactions}"

CONDITION=""
FORCE=0
SKIP_SNAPSHOT=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --condition)
            CONDITION="$2"
            shift 2
            ;;
        --force)
            FORCE=1
            shift
            ;;
        --skip-snapshot)
            SKIP_SNAPSHOT=1
            shift
            ;;
        -h|--help)
            sed -n '3,45p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "lrr-phase-4-integrity-lock: unknown flag $1" >&2
            exit 2
            ;;
    esac
done

log() {
    echo "lrr-phase-4-integrity-lock: $*"
}

fail() {
    echo "lrr-phase-4-integrity-lock: FAIL — $*" >&2
}

# --- Resolve target condition -------------------------------------------------

if [[ -z "${CONDITION}" ]]; then
    if [[ ! -f "${REGISTRY_DIR}/current.txt" ]]; then
        fail "registry not initialized (${REGISTRY_DIR}/current.txt missing); pass --condition explicitly"
        exit 2
    fi
    CONDITION="$(tr -d '[:space:]' < "${REGISTRY_DIR}/current.txt")"
    if [[ -z "${CONDITION}" ]]; then
        fail "current.txt is empty; pass --condition explicitly"
        exit 2
    fi
fi

COND_DIR="${REGISTRY_DIR}/${CONDITION}"
if [[ ! -d "${COND_DIR}" ]]; then
    fail "condition ${CONDITION} not found at ${COND_DIR}"
    exit 2
fi

CHECKSUMS_FILE="${COND_DIR}/data-checksums.txt"
SNAPSHOT_FILE="${COND_DIR}/qdrant-snapshot.tgz"
LOCK_MANIFEST="${COND_DIR}/integrity-lock.yaml"

# --- Idempotency guard --------------------------------------------------------

if [[ -f "${LOCK_MANIFEST}" && ${FORCE} -eq 0 ]]; then
    fail "integrity lock already exists at ${LOCK_MANIFEST}; pass --force to overwrite"
    exit 1
fi

# --- Step 1: sha256 the reactor JSONL logs -----------------------------------

if [[ ! -d "${REACTOR_LOGS_DIR}" ]]; then
    log "reactor logs dir ${REACTOR_LOGS_DIR} does not exist; writing empty checksums file"
    : > "${CHECKSUMS_FILE}"
    FILE_COUNT=0
else
    # Collect all .jsonl files under reactor-logs (bounded depth to avoid
    # surprise traversal into sibling dirs). Sort for deterministic output.
    mapfile -t JSONL_FILES < <(find "${REACTOR_LOGS_DIR}" -maxdepth 3 -name '*.jsonl' -type f | sort)
    FILE_COUNT=${#JSONL_FILES[@]}
    if [[ ${FILE_COUNT} -eq 0 ]]; then
        log "no .jsonl reactor log files found under ${REACTOR_LOGS_DIR}"
        : > "${CHECKSUMS_FILE}"
    else
        log "computing sha256 for ${FILE_COUNT} reactor log file(s)"
        {
            echo "# LRR Phase 4 data integrity checksums for ${CONDITION}"
            echo "# Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
            echo "# Format: sha256  bytes  lines  path"
            for f in "${JSONL_FILES[@]}"; do
                hash="$(sha256sum "$f" | awk '{print $1}')"
                bytes="$(stat -c '%s' "$f")"
                lines="$(wc -l < "$f")"
                printf '%s  %s  %s  %s\n' "${hash}" "${bytes}" "${lines}" "${f}"
            done
        } > "${CHECKSUMS_FILE}"
    fi
fi
log "wrote checksums to ${CHECKSUMS_FILE}"

# --- Step 2: Qdrant snapshot --------------------------------------------------

SNAPSHOT_STATUS="skipped"
SNAPSHOT_URL=""
if [[ ${SKIP_SNAPSHOT} -eq 1 ]]; then
    log "--skip-snapshot set; skipping Qdrant export"
else
    if ! command -v curl >/dev/null 2>&1; then
        fail "curl not available; cannot trigger Qdrant snapshot"
        exit 1
    fi
    log "creating Qdrant snapshot for collection ${QDRANT_COLLECTION}"
    SNAPSHOT_RESPONSE="$(curl -fsS -X POST "${QDRANT_URL}/collections/${QDRANT_COLLECTION}/snapshots" 2>/dev/null || true)"
    SNAPSHOT_NAME="$(echo "${SNAPSHOT_RESPONSE}" | grep -oE '"name"\s*:\s*"[^"]+"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/')"
    if [[ -z "${SNAPSHOT_NAME}" ]]; then
        fail "qdrant snapshot creation failed; response: ${SNAPSHOT_RESPONSE}"
        exit 1
    fi
    SNAPSHOT_URL="${QDRANT_URL}/collections/${QDRANT_COLLECTION}/snapshots/${SNAPSHOT_NAME}"
    log "downloading snapshot ${SNAPSHOT_NAME}"
    if ! curl -fsS "${SNAPSHOT_URL}" -o "${SNAPSHOT_FILE}"; then
        fail "qdrant snapshot download failed from ${SNAPSHOT_URL}"
        exit 1
    fi
    SNAPSHOT_STATUS="captured"
    log "wrote snapshot to ${SNAPSHOT_FILE}"
fi

# --- Step 3: lock manifest ----------------------------------------------------

GIT_HEAD="$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || echo 'unknown')"
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

{
    echo "# LRR Phase 4 data integrity lock manifest"
    echo "# Spec: docs/superpowers/specs/2026-04-15-lrr-phase-4-phase-a-completion-osf-design.md §3.6"
    echo "condition: ${CONDITION}"
    echo "locked_at: ${NOW}"
    echo "git_head: ${GIT_HEAD}"
    echo "reactor_logs_dir: ${REACTOR_LOGS_DIR}"
    echo "reactor_logs_file_count: ${FILE_COUNT}"
    echo "checksums_file: ${CHECKSUMS_FILE}"
    echo "qdrant:"
    echo "  collection: ${QDRANT_COLLECTION}"
    echo "  snapshot_status: ${SNAPSHOT_STATUS}"
    if [[ "${SNAPSHOT_STATUS}" == "captured" ]]; then
        echo "  snapshot_file: ${SNAPSHOT_FILE}"
        echo "  snapshot_name: ${SNAPSHOT_NAME}"
        SNAPSHOT_SHA="$(sha256sum "${SNAPSHOT_FILE}" | awk '{print $1}')"
        SNAPSHOT_SIZE="$(stat -c '%s' "${SNAPSHOT_FILE}")"
        echo "  snapshot_sha256: ${SNAPSHOT_SHA}"
        echo "  snapshot_bytes: ${SNAPSHOT_SIZE}"
    fi
} > "${LOCK_MANIFEST}"

log "wrote lock manifest to ${LOCK_MANIFEST}"
log "integrity lock complete for ${CONDITION}"
exit 0
