#!/usr/bin/env bash
# Generic auto-rebuild for Python services when origin/main advances.
# Checks if watched paths changed, pulls ff-only, restarts the systemd service.
# Intended to run via systemd timer (hapax-rebuild-services.timer).
#
# Usage:
#   rebuild-service.sh --repo ~/projects/hapax-council \
#       --service hapax-daimonion.service \
#       --watch "agents/hapax_daimonion/ shared/" \
#       --sha-key voice
#
#   rebuild-service.sh --repo ~/projects/hapax-mcp \
#       --sha-key hapax-mcp \
#       --pull-only
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

STATE_DIR="$HOME/.cache/hapax/rebuild"
SHA_FILE="$STATE_DIR/last-${SHA_KEY}-sha"
LOG_TAG="hapax-rebuild-${SHA_KEY}"
NTFY_URL="${NTFY_BASE_URL:-http://localhost:8090}/hapax-build"

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

# --- Fetch latest main ---
cd "$REPO"
git fetch origin main --quiet 2>/dev/null || {
    logger -t "$LOG_TAG" "git fetch failed — skipping"
    exit 0
}

CURRENT_SHA=$(git rev-parse origin/main 2>/dev/null)
LAST_SHA=$(cat "$SHA_FILE" 2>/dev/null || echo "none")

if [ "$CURRENT_SHA" = "$LAST_SHA" ]; then
    exit 0  # no change
fi

# --- Check if watched paths changed ---
if [ -n "$WATCH_PATHS" ] && [ "$LAST_SHA" != "none" ]; then
    # shellcheck disable=SC2086
    CHANGED=$(git diff --name-only "$LAST_SHA" "$CURRENT_SHA" -- $WATCH_PATHS 2>/dev/null | wc -l)
    if [ "$CHANGED" -eq 0 ]; then
        # Main advanced but none of our paths changed — update SHA and skip
        echo "$CURRENT_SHA" > "$SHA_FILE"
        logger -t "$LOG_TAG" "main advanced (${CURRENT_SHA:0:8}) but no watched path changes — skipping"
        exit 0
    fi
fi

logger -t "$LOG_TAG" "main advanced: ${LAST_SHA:0:8} → ${CURRENT_SHA:0:8} — updating"

# --- Pull ff-only ---
CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "")
if [ "$CURRENT_BRANCH" = "main" ]; then
    git merge origin/main --ff-only --quiet 2>/dev/null || {
        logger -t "$LOG_TAG" "ff-merge failed — skipping"
        exit 0
    }
else
    # Repo is on a feature branch — we can't auto-deploy without clobbering
    # the operator's work. Do NOT update SHA_FILE; the next cycle must keep
    # flagging this as stale until the operator rebases/merges. Notify once
    # per distinct origin/main SHA so the operator isn't spammed.
    #
    # Queue 025 round-4 Phase 6 Gap 3: upgrade visibility. Previously the
    # "deploy skipped" line was only emitted via ``logger -t`` at default
    # priority (user.notice) and the single-shot ntfy only fired once per
    # new origin/main SHA. After alpha's queue 023 incident where two
    # consecutive rebuild cycles silently skipped a voice-critical fix
    # on a feature branch, we want the skip to be loud at every cycle.
    # Changes:
    #
    #   1. upgrade ``logger`` to ``user.warning`` so the journal filters
    #      it above informational messages
    #   2. echo a ``[WARN] rebuild-service: ...`` line to stderr so
    #      systemd captures it in the per-run status output
    #   3. keep the throttled per-SHA ntfy so the phone still gets a
    #      single actionable alert per advance (no spam)
    NOTIFIED_FILE="$STATE_DIR/last-notified-${SHA_KEY}-sha"
    LAST_NOTIFIED=$(cat "$NOTIFIED_FILE" 2>/dev/null || echo "none")
    skip_msg="repo not on main (on $CURRENT_BRANCH) — deploy skipped for ${SHA_KEY}; SHA_FILE NOT updated"
    echo "[WARN] rebuild-service: $skip_msg" >&2
    logger -t "$LOG_TAG" -p user.warning "$skip_msg"
    if [ "$CURRENT_SHA" != "$LAST_NOTIFIED" ]; then
        ntfy "$SHA_KEY stale on $CURRENT_BRANCH" \
            "Operator: rebase $CURRENT_BRANCH onto origin/main to deploy ${CURRENT_SHA:0:8}. rebuild-service.sh refuses to auto-advance a feature branch." \
            "default" "warning"
        echo "$CURRENT_SHA" > "$NOTIFIED_FILE"
    fi
    exit 0
fi

# --- Restart service or just pull ---
if [ "$PULL_ONLY" = true ]; then
    echo "$CURRENT_SHA" > "$SHA_FILE"
    logger -t "$LOG_TAG" "pull-only complete — ${CURRENT_SHA:0:8}"
    ntfy "$SHA_KEY updated" "${LAST_SHA:0:8} → ${CURRENT_SHA:0:8}" "low" "arrows_counterclockwise"
    exit 0
fi

if [ -z "$SERVICE" ]; then
    echo "$CURRENT_SHA" > "$SHA_FILE"
    exit 0
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
    exit 0
fi

ntfy "$SERVICE restarting" "${LAST_SHA:0:8} → ${CURRENT_SHA:0:8}" "low" "hammer_and_wrench"

systemctl --user restart "$SERVICE" 2>/dev/null || {
    logger -t "$LOG_TAG" "$SERVICE restart failed"
    ntfy "$SERVICE restart FAILED" "${CURRENT_SHA:0:8}" "high" "x"
    echo "$CURRENT_SHA" > "$SHA_FILE"
    exit 1
}

echo "$CURRENT_SHA" > "$SHA_FILE"
logger -t "$LOG_TAG" "$SERVICE restarted — ${CURRENT_SHA:0:8}"
ntfy "$SERVICE restarted" "${CURRENT_SHA:0:8}" "default" "white_check_mark"
