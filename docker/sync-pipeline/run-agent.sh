#!/usr/bin/env bash
set -euo pipefail

# Wrapper for cron-invoked sync agents.
# Prevents overlapping runs via flock.

AGENT="$1"
shift
EXTRA_ARGS="${*:---auto}"
LOCKDIR="/tmp/sync-locks"
mkdir -p "$LOCKDIR"
LOCKFILE="${LOCKDIR}/${AGENT}.lock"

# Skip if previous run still active
exec 200>"$LOCKFILE"
if ! flock -n 200; then
    echo "$(date -Iseconds) [${AGENT}] SKIP — previous run still active"
    exit 0
fi

NTFY_URL="${NTFY_URL:-http://127.0.0.1:8090}"

echo "$(date -Iseconds) [${AGENT}] START"
if python -m "agents.${AGENT}" ${EXTRA_ARGS} 2>&1; then
    echo "$(date -Iseconds) [${AGENT}] DONE (exit 0)"
else
    RC=$?
    echo "$(date -Iseconds) [${AGENT}] FAILED (exit ${RC})" >&2
    # Notify on failure (best-effort, don't block on notification errors)
    curl -sf -d "sync-pipeline: ${AGENT} failed (exit ${RC})" \
        -H "Title: Sync Agent Failed" -H "Priority: high" -H "Tags: warning" \
        "${NTFY_URL}/hapax-alerts" >/dev/null 2>&1 || true
fi
