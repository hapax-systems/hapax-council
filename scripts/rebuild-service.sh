#!/usr/bin/env bash
# Generic auto-rebuild for Python services when origin/main advances.
# Checks if watched paths changed, pulls ff-only, restarts the systemd service.
# Intended to run via systemd timer (hapax-rebuild-services.timer).
#
# Usage:
#   rebuild-service.sh --repo ~/projects/hapax-council \
#       --service hapax-voice.service \
#       --watch "agents/hapax_voice/ shared/" \
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
    logger -t "$LOG_TAG" "repo not on main (on $CURRENT_BRANCH) — skipping pull, SHA-only update"
    echo "$CURRENT_SHA" > "$SHA_FILE"
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
