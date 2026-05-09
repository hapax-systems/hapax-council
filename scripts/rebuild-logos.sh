#!/usr/bin/env bash
# Rebuild the hapax-imagination binary if main has advanced.
# Intended to run via systemd timer (hapax-rebuild-logos.timer, every 5 min).
# Only rebuilds when the commit SHA on origin/main differs from the last build.
# The timer name is retained for compatibility; the Tauri/WebKit hapax-logos
# runtime is decommissioned and is not built, installed, or restarted here.
#
# Builds run in an isolated scratch worktree under $STATE_DIR/worktree so the
# primary alpha/beta worktrees are never mutated mid-session. The scratch
# worktree lives outside ~/projects/ and is not subject to the three-slot
# discipline enforced on the project root.
#
# History: see FU-6 (PR #703) for the scratch-worktree rewrite and the
# retirement handoff at docs/superpowers/handoff/2026-04-12-alpha-fu6-handoff.md
# for the scope split and architectural follow-up. The 2026-04-13 OOM cascade
# (handoff: docs/superpowers/handoff/2026-04-13-alpha-oom-cascade-handoff.md)
# re-surfaced the alpha-as-deploy-target tension when a primary-worktree
# `git restore` silently reverted a symlinked systemd unit file mid-session.
set -euo pipefail

REPO="${HAPAX_COUNCIL_DIR:-$HOME/projects/hapax-council}"
STATE_DIR="$HOME/.cache/hapax/rebuild"
BUILD_WORKTREE="$STATE_DIR/worktree"
SHA_FILE="$STATE_DIR/last-build-sha"
LOG_TAG="hapax-rebuild"

NTFY_URL="${NTFY_BASE_URL:-http://localhost:8090}/hapax-build"

mkdir -p "$STATE_DIR"

# Serialize against concurrent runs. systemd Type=oneshot prevents the timer
# from overlapping itself, but manual invocations (e.g. smoke tests) can still
# race against a timer firing. Without this lock, two concurrent runs would
# step on the shared scratch worktree (git reset + vite dist/ writes).
exec 9>"$STATE_DIR/lock"
if ! flock -n 9; then
    logger -t "hapax-rebuild" "another rebuild-logos run is active — skipping"
    exit 0
fi

ntfy() {
    local title="$1" msg="$2" priority="${3:-default}" tags="${4:-}"
    curl -s -o /dev/null \
        -H "Title: $title" \
        -H "Priority: $priority" \
        ${tags:+-H "Tags: $tags"} \
        -d "$msg" \
        "$NTFY_URL" 2>/dev/null || true
}

# Fetch latest main into the shared refs store. `git fetch` in any worktree
# updates origin refs for all worktrees that share the same repo.
cd "$REPO"
git fetch origin main --quiet 2>/dev/null || {
    logger -t "$LOG_TAG" "git fetch failed — skipping rebuild"
    exit 0
}

CURRENT_SHA=$(git rev-parse origin/main 2>/dev/null)
LAST_SHA=$(cat "$SHA_FILE" 2>/dev/null || echo "none")

if [ "$CURRENT_SHA" = "$LAST_SHA" ]; then
    exit 0  # no change
fi

logger -t "$LOG_TAG" "main advanced: ${LAST_SHA:0:8} -> ${CURRENT_SHA:0:8} - rebuilding imagination"
ntfy "Imagination rebuild starting" "${LAST_SHA:0:8} -> ${CURRENT_SHA:0:8}" "low" "hammer_and_wrench"

# Sync the scratch build worktree to origin/main. On first run, create it.
# Subsequent runs reset it to origin/main, preserving untracked node_modules
# so pnpm install --frozen-lockfile stays fast.
if [ ! -e "$BUILD_WORKTREE/.git" ]; then
    logger -t "$LOG_TAG" "creating build worktree at $BUILD_WORKTREE"
    git worktree prune 2>/dev/null || true
    rm -rf "$BUILD_WORKTREE"
    git worktree add --detach "$BUILD_WORKTREE" "$CURRENT_SHA" --quiet 2>/dev/null || {
        logger -t "$LOG_TAG" "worktree add failed — skipping rebuild"
        ntfy "Logos rebuild FAILED" "worktree add failed" "high" "x"
        exit 0
    }
else
    cd "$BUILD_WORKTREE"
    if ! git reset --hard "$CURRENT_SHA" --quiet 2>/dev/null; then
        logger -t "$LOG_TAG" "build worktree reset failed — recreating"
        cd "$REPO"
        rm -rf "$BUILD_WORKTREE"
        git worktree prune 2>/dev/null || true
        git worktree add --detach "$BUILD_WORKTREE" "$CURRENT_SHA" --quiet 2>/dev/null || {
            logger -t "$LOG_TAG" "worktree recreate failed — skipping rebuild"
            ntfy "Logos rebuild FAILED" "worktree recreate failed" "high" "x"
            exit 0
        }
    fi
fi

# Build and install via justfile (isolated CARGO_TARGET_DIR, rollback backup)
cd "$BUILD_WORKTREE/hapax-logos"
if just install-imagination 2>"$STATE_DIR/build.log"; then
    echo "$CURRENT_SHA" > "$SHA_FILE"
    VERSION_OUTPUT=$(just version 2>/dev/null || true)
    VERSION="${VERSION_OUTPUT%%$'\n'*}"
    logger -t "$LOG_TAG" "rebuild complete - $VERSION"
    ntfy "Imagination rebuild complete" "${CURRENT_SHA:0:8} - $VERSION" "default" "white_check_mark"
else
    logger -t "$LOG_TAG" "build failed - see $STATE_DIR/build.log"
    ntfy "Imagination rebuild FAILED" "See ~/.cache/hapax/rebuild/build.log" "high" "x"
fi

# Auto-restart stale services (binary newer than running process)
svc=hapax-imagination
if systemctl --user is-active "$svc" &>/dev/null; then
    svc_start=$(systemctl --user show "$svc" --property=ActiveEnterTimestamp --value 2>/dev/null)
    if [[ -n "$svc_start" ]]; then
        svc_epoch=$(date -d "$svc_start" +%s 2>/dev/null || echo 0)
        bin_epoch=$(stat -c %Y "$HOME/.local/bin/$svc" 2>/dev/null || echo 0)
        if [[ "$bin_epoch" -gt "$svc_epoch" ]]; then
            logger -t "$LOG_TAG" "auto-restarting $svc (binary newer by $((bin_epoch - svc_epoch))s)"
            systemctl --user restart "$svc"
        fi
    fi
fi

# Run freshness check and alert on staleness
FRESHNESS_SCRIPT="$(dirname "$0")/freshness-check.sh"
if [[ -x "$FRESHNESS_SCRIPT" ]]; then
    STALE_OUTPUT=$("$FRESHNESS_SCRIPT" 2>&1) || {
        ntfy "Stale items detected" "$STALE_OUTPUT" "high" "warning"
    }
fi
