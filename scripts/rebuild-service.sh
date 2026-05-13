#!/usr/bin/env bash
# Generic auto-rebuild for Python services when origin/main advances.
# Checks if watched paths changed, pulls ff-only, restarts the systemd service.
# Intended to run via systemd timer (hapax-rebuild-services.timer).
#
# Usage:
#   rebuild-service.sh --repo ~/.cache/hapax/rebuild/worktree \
#       --service hapax-daimonion.service \
#       --watch "agents/hapax_daimonion/ shared/" \
#       --sha-key voice
#
#   rebuild-service.sh --repo ~/projects/hapax-mcp \
#       --sha-key hapax-mcp \
#       --pull-only
#
# Canonical worktree isolation
# ----------------------------
# Council-specific deploys point ``--repo`` at
# ``$HOME/.cache/hapax/rebuild/worktree`` — a dedicated build/deploy worktree
# permanently tracking ``origin/main``. The script auto-creates the worktree on
# first run and fast-forwards it at the start of every invocation. This
# replaces the previous defense-in-depth ``branch != main`` skip: the rebuild
# worktree is structurally on main, so a feature-branch checkout in the
# operator's interactive worktree (``~/projects/hapax-council``) can no longer
# accidentally block deploys for the rest of the system.
#
# Foreign repos (officium, mcp, etc.) keep their previous semantics — they are
# not managed worktrees, so the script still pulls ff-only on whatever branch
# they happen to be on. Only the council ``rebuild/worktree`` path triggers the
# managed-worktree code path.
#
# Recovery: if the rebuild worktree is dirty, locked, or otherwise unusable,
# the script logs a warning and skips the deploy without advancing SHA_FILE so
# the next cycle retries.
set -euo pipefail

# --- Parse arguments ---
REPO=""
SERVICE=""
WATCH_PATHS=""
SHA_KEY=""
PULL_ONLY=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)     REPO="$2"; shift 2 ;;
        --service)  SERVICE="$2"; shift 2 ;;
        --watch)    WATCH_PATHS="$2"; shift 2 ;;
        --sha-key)  SHA_KEY="$2"; shift 2 ;;
        --pull-only) PULL_ONLY=true; shift ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

if [ -z "$REPO" ] || [ -z "$SHA_KEY" ]; then
    echo "Usage: rebuild-service.sh --repo PATH --sha-key KEY [--service UNIT] [--watch PATHS] [--pull-only]" >&2
    exit 1
fi

# Test-injectable knobs. Real runs use the production paths.
: "${HAPAX_REBUILD_STATE_DIR:=$HOME/.cache/hapax/rebuild}"
: "${HAPAX_REBUILD_CANONICAL_REPO:=$HOME/projects/hapax-council}"
: "${HAPAX_REBUILD_WORKTREE:=$HOME/.cache/hapax/rebuild/worktree}"

STATE_DIR="$HAPAX_REBUILD_STATE_DIR"
SHA_FILE="$STATE_DIR/last-${SHA_KEY}-sha"
OUTCOME_FILE="$STATE_DIR/last-${SHA_KEY}-outcome.json"
OUTCOME_HISTORY_FILE="$STATE_DIR/rebuild-service-outcomes.jsonl"
LOG_TAG="hapax-rebuild-${SHA_KEY}"
NTFY_URL="${NTFY_BASE_URL:-http://localhost:8090}/hapax-build"

SERVICE_LOAD_STATE=""
SERVICE_UNIT_FILE_STATE=""
SERVICE_ACTIVE_STATE=""
SERVICE_SUB_STATE=""
SERVICE_RESULT=""
SERVICE_EXEC_MAIN_STATUS=""
SERVICE_ACTIVE_ENTER_MONOTONIC_US=""

mkdir -p "$STATE_DIR"

ntfy() {
    local title="$1" msg="$2" priority="${3:-default}" tags="${4:-}"
    curl -s -o /dev/null \
        -H "Title: $title" \
        -H "Priority: $priority" \
        ${tags:+-H "Tags: $tags"} \
        -d "$msg" \
        "$NTFY_URL" 2>/dev/null || true
}

write_outcome() {
    local outcome="$1"
    local exit_code="$2"
    local sha_file_written="$3"
    local restart_timeout_duration="$4"
    local observation_window_sec="$5"
    local attempt_start_monotonic_us="$6"
    local message="$7"

    python3 - "$OUTCOME_FILE" "$OUTCOME_HISTORY_FILE" \
        "$SHA_KEY" "$SERVICE" "$CURRENT_SHA" "$LAST_SHA" "$outcome" "$exit_code" \
        "$sha_file_written" "$restart_timeout_duration" "$observation_window_sec" \
        "$attempt_start_monotonic_us" "$SERVICE_LOAD_STATE" "$SERVICE_ACTIVE_STATE" \
        "$SERVICE_SUB_STATE" "$SERVICE_RESULT" "$SERVICE_EXEC_MAIN_STATUS" \
        "$SERVICE_ACTIVE_ENTER_MONOTONIC_US" "$message" <<'PY'
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

(
    current_path,
    history_path,
    sha_key,
    service,
    current_sha,
    last_sha,
    outcome,
    exit_code,
    sha_file_written,
    restart_timeout_duration,
    observation_window_sec,
    attempt_start_monotonic_us,
    load_state,
    active_state,
    sub_state,
    result,
    exec_main_status,
    active_enter_timestamp_monotonic_us,
    message,
) = sys.argv[1:]

record = {
    "schema_version": 1,
    "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    "sha_key": sha_key,
    "service": service,
    "current_sha": current_sha,
    "last_sha": last_sha,
    "outcome": outcome,
    "exit_code": int(exit_code),
    "sha_file_written": sha_file_written == "true",
    "restart_timeout_duration": restart_timeout_duration,
    "observation_window_sec": int(observation_window_sec or 0),
    "attempt_start_monotonic_us": int(attempt_start_monotonic_us or 0),
    "load_state": load_state,
    "active_state": active_state,
    "sub_state": sub_state,
    "result": result,
    "exec_main_status": exec_main_status,
    "active_enter_timestamp_monotonic_us": int(active_enter_timestamp_monotonic_us or 0),
    "message": message,
}

current = Path(current_path).expanduser()
history = Path(history_path).expanduser()
current.parent.mkdir(parents=True, exist_ok=True)
tmp = current.with_name(f"{current.name}.tmp")
tmp.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
os.replace(tmp, current)
with history.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(record, sort_keys=True) + "\n")
PY
}

write_sha() {
    echo "$CURRENT_SHA" > "$SHA_FILE"
}

read_service_state() {
    SERVICE_LOAD_STATE=""
    SERVICE_UNIT_FILE_STATE=""
    SERVICE_ACTIVE_STATE=""
    SERVICE_SUB_STATE=""
    SERVICE_RESULT=""
    SERVICE_EXEC_MAIN_STATUS=""
    SERVICE_ACTIVE_ENTER_MONOTONIC_US=""

    local state_output
    state_output=$(systemctl --user show "$SERVICE" \
        -p LoadState \
        -p UnitFileState \
        -p ActiveState \
        -p SubState \
        -p Result \
        -p ExecMainStatus \
        -p ActiveEnterTimestampMonotonic 2>/dev/null || true)
    while IFS='=' read -r key value; do
        case "$key" in
            LoadState) SERVICE_LOAD_STATE="$value" ;;
            UnitFileState) SERVICE_UNIT_FILE_STATE="$value" ;;
            ActiveState) SERVICE_ACTIVE_STATE="$value" ;;
            SubState) SERVICE_SUB_STATE="$value" ;;
            Result) SERVICE_RESULT="$value" ;;
            ExecMainStatus) SERVICE_EXEC_MAIN_STATUS="$value" ;;
            ActiveEnterTimestampMonotonic) SERVICE_ACTIVE_ENTER_MONOTONIC_US="$value" ;;
        esac
    done <<< "$state_output"
}

monotonic_us() {
    awk '{ printf "%.0f\n", $1 * 1000000 }' /proc/uptime 2>/dev/null || date +%s000000
}

classify_failed_restart() {
    local attempt_start_monotonic_us="$1"
    local observation_window_sec="$2"
    local observation_interval_sec="$3"
    local deadline=$((SECONDS + observation_window_sec))

    while true; do
        read_service_state

        if [ "$SERVICE_LOAD_STATE" != "loaded" ]; then
            printf '%s\n' "restart_timeout_unknown"
            return 0
        fi

        if [ "$SERVICE_ACTIVE_STATE" = "active" ] \
            && [[ "$SERVICE_ACTIVE_ENTER_MONOTONIC_US" =~ ^[0-9]+$ ]] \
            && [ "$SERVICE_ACTIVE_ENTER_MONOTONIC_US" -ge "$attempt_start_monotonic_us" ]; then
            printf '%s\n' "restart_timeout_late_active"
            return 0
        fi

        case "$SERVICE_ACTIVE_STATE:$SERVICE_SUB_STATE" in
            activating:*|deactivating:*|reloading:*|*:auto-restart)
                printf '%s\n' "restart_still_in_progress"
                return 0
                ;;
            failed:*|inactive:*)
                printf '%s\n' "restart_failed_unhealthy"
                return 0
                ;;
        esac

        if [ "$SECONDS" -ge "$deadline" ]; then
            printf '%s\n' "restart_timeout_unknown"
            return 0
        fi
        sleep "$observation_interval_sec"
    done
}

# --- Managed rebuild worktree bootstrap ---
# When --repo points at the dedicated rebuild worktree, ensure the worktree
# exists and is fast-forwarded to origin/main BEFORE any other git work. The
# canonical source repo (operator's interactive checkout) provides the git
# objects + remotes; the rebuild worktree is a sibling worktree linked to it.
#
# Foreign repos (--repo != HAPAX_REBUILD_WORKTREE) skip this step.
if [ "$REPO" = "$HAPAX_REBUILD_WORKTREE" ]; then
    if [ ! -e "$REPO/.git" ]; then
        if [ ! -d "$HAPAX_REBUILD_CANONICAL_REPO/.git" ] && [ ! -f "$HAPAX_REBUILD_CANONICAL_REPO/.git" ]; then
            logger -t "$LOG_TAG" "canonical repo missing at $HAPAX_REBUILD_CANONICAL_REPO — cannot bootstrap rebuild worktree"
            exit 0
        fi
        logger -t "$LOG_TAG" "creating rebuild worktree at $REPO"
        cd "$HAPAX_REBUILD_CANONICAL_REPO"
        git fetch origin main --quiet 2>/dev/null || {
            logger -t "$LOG_TAG" "git fetch failed during worktree bootstrap — skipping"
            exit 0
        }
        git worktree prune 2>/dev/null || true
        # Detach-mode worktree on origin/main: avoids consuming the 'main'
        # branch ref (which is checked out by the canonical repo).
        if ! git worktree add --detach "$REPO" origin/main --quiet 2>/dev/null; then
            logger -t "$LOG_TAG" "git worktree add failed for $REPO — skipping"
            ntfy "Rebuild worktree bootstrap FAILED" "git worktree add $REPO" "high" "x"
            exit 0
        fi
    fi

    # Fast-forward the rebuild worktree to origin/main at the start of every
    # run. Detached HEAD is the steady state — we never make commits here, so
    # `git fetch && git reset --hard origin/main` is the correct semantics.
    cd "$REPO"
    git fetch origin main --quiet 2>/dev/null || {
        logger -t "$LOG_TAG" "git fetch failed in rebuild worktree — skipping"
        exit 0
    }
    if ! git reset --hard origin/main --quiet 2>/dev/null; then
        logger -t "$LOG_TAG" "rebuild worktree reset to origin/main failed (dirty? locked?) — skipping for ${SHA_KEY}; SHA_FILE NOT updated"
        echo "[WARN] rebuild-service: rebuild worktree at $REPO not fast-forwardable — skipping ${SHA_KEY}" >&2
        exit 0
    fi
fi

# --- Fetch latest main ---
cd "$REPO"
git fetch origin main --quiet 2>/dev/null || {
    logger -t "$LOG_TAG" "git fetch failed — skipping"
    exit 0
}

CURRENT_SHA=$(git rev-parse origin/main 2>/dev/null)
LAST_SHA=$(cat "$SHA_FILE" 2>/dev/null || echo "none")

if [ "$CURRENT_SHA" = "$LAST_SHA" ]; then
    write_outcome "no_change" "0" "false" "" "0" "0" "origin/main already handled"
    exit 0  # no change
fi

# --- Check if watched paths changed ---
if [ -n "$WATCH_PATHS" ] && [ "$LAST_SHA" != "none" ]; then
    # shellcheck disable=SC2086
    CHANGED=$(git diff --name-only "$LAST_SHA" "$CURRENT_SHA" -- $WATCH_PATHS 2>/dev/null | wc -l)
    if [ "$CHANGED" -eq 0 ]; then
        # Main advanced but none of our paths changed — update SHA and skip
        write_sha
        logger -t "$LOG_TAG" "main advanced (${CURRENT_SHA:0:8}) but no watched path changes — skipping"
        write_outcome "skipped_no_watched_changes" "0" "true" "" "0" "0" "main advanced but watched paths unchanged"
        exit 0
    fi
fi

logger -t "$LOG_TAG" "main advanced: ${LAST_SHA:0:8} → ${CURRENT_SHA:0:8} — updating"

# --- Pull ff-only ---
# For the managed rebuild worktree we already reset to origin/main above, so
# this is a no-op. For foreign repos we still ff-merge onto whatever branch
# they're on (officium, mcp). The branch-check that previously refused to
# deploy when the council canonical was on a feature branch is gone: the
# rebuild worktree is structurally on main, so the operator's interactive
# checkout no longer blocks the deploy cascade.
if [ "$REPO" != "$HAPAX_REBUILD_WORKTREE" ]; then
    git merge origin/main --ff-only --quiet 2>/dev/null || {
        logger -t "$LOG_TAG" "ff-merge failed in $REPO — skipping"
        exit 0
    }
fi

# --- Restart service or just pull ---
if [ "$PULL_ONLY" = true ]; then
    write_sha
    logger -t "$LOG_TAG" "pull-only complete — ${CURRENT_SHA:0:8}"
    ntfy "$SHA_KEY updated" "${LAST_SHA:0:8} → ${CURRENT_SHA:0:8}" "low" "arrows_counterclockwise"
    write_outcome "pull_only_updated" "0" "true" "" "0" "0" "pull-only update complete"
    exit 0
fi

if [ -z "$SERVICE" ]; then
    write_sha
    write_outcome "no_service_sha_updated" "0" "true" "" "0" "0" "no service configured; SHA updated"
    exit 0
fi

# A service may be intentionally masked during an incident containment window
# (for example, Daimonion private voice egress). Treat that as a successful
# no-op instead of failing the whole rebuild cascade; the explicit restore path
# is responsible for unmasking and starting the service later.
read_service_state
if [[ " $SERVICE_UNIT_FILE_STATE " == *" masked "* ]]; then
    write_sha
    logger -t "$LOG_TAG" "$SERVICE masked - rebuild restart skipped at ${CURRENT_SHA:0:8}"
    write_outcome "skipped_masked" "0" "true" "" "0" "0" "$SERVICE masked; restart skipped"
    exit 0
fi

if [ "$SERVICE_LOAD_STATE" != "loaded" ]; then
    logger -t "$LOG_TAG" "$SERVICE missing or not loadable (LoadState=${SERVICE_LOAD_STATE:-unknown})"
    ntfy "$SERVICE restart FAILED" "missing unit for ${CURRENT_SHA:0:8}" "high" "x"
    write_outcome "missing_unit" "1" "false" "" "0" "0" "$SERVICE missing or not loadable"
    exit 1
fi

# --- System pressure guard ---
# 2026-04-16 incident: studio-compositor's main Python process went zombie
# after rebuild-services fired twice within 5 minutes while the rig was at
# load-avg 22 with 13 GB of swap in use. The restart itself crashed the
# process under memory pressure. Prevent: skip the restart when the
# system is too stressed to survive it cleanly. SHA_FILE is NOT updated
# on skip so the next rebuild cycle retries once pressure drops.
#
# Thresholds are conservative defaults; override via env vars when the
# migration changes the baseline.
: "${HAPAX_REBUILD_LOAD_MAX:=3.0}"      # load-avg per CPU core
: "${HAPAX_REBUILD_SWAP_PCT_MAX:=50}"   # swap used as % of total
: "${HAPAX_REBUILD_SKIP_GUARD:=0}"      # 1 to bypass the guard entirely
: "${HAPAX_REBUILD_RESTART_TIMEOUT_SEC:=60}"  # bound any single systemd restart
: "${HAPAX_REBUILD_RESTART_OBSERVATION_SEC:=30}"
: "${HAPAX_REBUILD_RESTART_OBSERVATION_INTERVAL_SEC:=2}"

PRESSURE_REASON=""
if [ "$HAPAX_REBUILD_SKIP_GUARD" != "1" ]; then
    read -r load_1min _ _ _ _ < /proc/loadavg
    cores=$(nproc 2>/dev/null || echo 1)
    load_per_core=$(awk -v l="$load_1min" -v c="$cores" 'BEGIN { printf "%.2f", l/c }')
    if awk -v lpc="$load_per_core" -v max="$HAPAX_REBUILD_LOAD_MAX" 'BEGIN { exit (lpc > max) ? 0 : 1 }'; then
        PRESSURE_REASON="load-per-core=${load_per_core} > ${HAPAX_REBUILD_LOAD_MAX} (load_1min=${load_1min}, cores=${cores})"
    else
        swap_total=$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo)
        swap_used=$(awk '/^SwapFree:/ {free=$2} /^SwapTotal:/ {total=$2} END {print total-free}' /proc/meminfo)
        if [ "${swap_total:-0}" -gt 0 ]; then
            swap_pct=$((swap_used * 100 / swap_total))
            if [ "$swap_pct" -gt "$HAPAX_REBUILD_SWAP_PCT_MAX" ]; then
                PRESSURE_REASON="swap=${swap_pct}% > ${HAPAX_REBUILD_SWAP_PCT_MAX}% (used=${swap_used}kB, total=${swap_total}kB)"
            fi
        fi
    fi
fi

if [ -n "$PRESSURE_REASON" ]; then
    # System too stressed for a safe restart. Skip without advancing
    # SHA_FILE so we retry next cycle. Throttled ntfy per distinct SHA
    # so the operator isn't spammed while pressure persists.
    PRESSURE_NOTIFIED_FILE="$STATE_DIR/last-pressure-skip-${SHA_KEY}-sha"
    LAST_PRESSURE_NOTIFIED=$(cat "$PRESSURE_NOTIFIED_FILE" 2>/dev/null || echo "none")
    skip_msg="$SERVICE restart SKIPPED under pressure — $PRESSURE_REASON — retrying next cycle"
    echo "[WARN] rebuild-service: $skip_msg" >&2
    logger -t "$LOG_TAG" -p user.warning "$skip_msg"
    if [ "$CURRENT_SHA" != "$LAST_PRESSURE_NOTIFIED" ]; then
        ntfy "$SERVICE restart deferred (pressure)" \
            "$PRESSURE_REASON. Deploy ${CURRENT_SHA:0:8} waits for system to settle. HAPAX_REBUILD_SKIP_GUARD=1 to force." \
            "default" "hourglass"
        echo "$CURRENT_SHA" > "$PRESSURE_NOTIFIED_FILE"
    fi
    write_outcome "deferred_pressure" "0" "false" "" "0" "0" "$skip_msg"
    exit 0
fi

ntfy "$SERVICE restarting" "${LAST_SHA:0:8} → ${CURRENT_SHA:0:8}" "low" "hammer_and_wrench"

RESTART_TIMEOUT_DURATION="$HAPAX_REBUILD_RESTART_TIMEOUT_SEC"
if [[ "$RESTART_TIMEOUT_DURATION" =~ ^[0-9]+$ ]]; then
    RESTART_TIMEOUT_DURATION="${RESTART_TIMEOUT_DURATION}s"
fi

ATTEMPT_START_MONOTONIC_US="$(monotonic_us)"
set +e
timeout --kill-after=10s "$RESTART_TIMEOUT_DURATION" \
    systemctl --user restart "$SERVICE" 2>/dev/null
RESTART_RC=$?
set -e

if [ "$RESTART_RC" -ne 0 ]; then
    RESTART_OUTCOME="$(classify_failed_restart "$ATTEMPT_START_MONOTONIC_US" "$HAPAX_REBUILD_RESTART_OBSERVATION_SEC" "$HAPAX_REBUILD_RESTART_OBSERVATION_INTERVAL_SEC")"
    if [ "$RESTART_OUTCOME" = "restart_timeout_late_active" ]; then
        write_sha
        logger -t "$LOG_TAG" "$SERVICE restart timed out but later became active — ${CURRENT_SHA:0:8}"
        ntfy "$SERVICE restart delayed-success" "${CURRENT_SHA:0:8}" "default" "white_check_mark"
        write_outcome "$RESTART_OUTCOME" "0" "true" "$RESTART_TIMEOUT_DURATION" "$HAPAX_REBUILD_RESTART_OBSERVATION_SEC" "$ATTEMPT_START_MONOTONIC_US" "$SERVICE restart timed out but became active in observation window"
        exit 0
    fi

    logger -t "$LOG_TAG" "$SERVICE restart failed ($RESTART_OUTCOME)"
    ntfy "$SERVICE restart FAILED" "${CURRENT_SHA:0:8}" "high" "x"
    write_sha
    write_outcome "$RESTART_OUTCOME" "1" "true" "$RESTART_TIMEOUT_DURATION" "$HAPAX_REBUILD_RESTART_OBSERVATION_SEC" "$ATTEMPT_START_MONOTONIC_US" "$SERVICE restart failed with rc=${RESTART_RC}"
    exit 1
fi

read_service_state
write_sha
logger -t "$LOG_TAG" "$SERVICE restarted — ${CURRENT_SHA:0:8}"
ntfy "$SERVICE restarted" "${CURRENT_SHA:0:8}" "default" "white_check_mark"
write_outcome "restart_success" "0" "true" "$RESTART_TIMEOUT_DURATION" "0" "$ATTEMPT_START_MONOTONIC_US" "$SERVICE restarted"
