#!/usr/bin/env bash
# Rebuild hapax-logos and hapax-imagination binaries if main has advanced.
# Intended to run via systemd timer (hapax-rebuild-logos.timer, every 5 min).
# Only rebuilds when the commit SHA on origin/main differs from the last build.
set -euo pipefail

REPO="$HOME/projects/hapax-council"
CARGO_DIR="$REPO/hapax-logos"
STATE_DIR="$HOME/.cache/hapax/rebuild"
SHA_FILE="$STATE_DIR/last-build-sha"
LOG_TAG="hapax-rebuild"

LOGOS_BIN="$HOME/.local/bin/hapax-logos"
IMAGINATION_BIN="$HOME/.local/bin/hapax-imagination"
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

# Fetch latest main
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

logger -t "$LOG_TAG" "main advanced: ${LAST_SHA:0:8} → ${CURRENT_SHA:0:8} — rebuilding"
ntfy "Logos rebuild starting" "${LAST_SHA:0:8} → ${CURRENT_SHA:0:8}" "low" "hammer_and_wrench"

# Ensure worktree is on main (or detach to origin/main)
CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "")
if [ "$CURRENT_BRANCH" != "main" ]; then
    # Don't disturb active branches — build from the fetched ref directly
    git checkout --detach origin/main --quiet 2>/dev/null || {
        logger -t "$LOG_TAG" "checkout failed — worktree busy, skipping"
        exit 0
    }
    RESTORE_BRANCH="$CURRENT_BRANCH"
else
    git merge origin/main --ff-only --quiet 2>/dev/null || {
        logger -t "$LOG_TAG" "ff-merge failed — skipping"
        exit 0
    }
    RESTORE_BRANCH=""
fi

# Build imagination (pure Rust) and logos (Tauri — bundles frontend)
cd "$CARGO_DIR"
cargo build --release -p hapax-imagination 2>"$STATE_DIR/build.log" || {
    logger -t "$LOG_TAG" "imagination build failed — see $STATE_DIR/build.log"
    ntfy "Imagination build FAILED" "See ~/.cache/hapax/rebuild/build.log" "high" "x"
    # Restore branch if we detached
    cd "$REPO"
    if [ -n "${RESTORE_BRANCH:-}" ]; then
        git checkout "$RESTORE_BRANCH" --quiet 2>/dev/null || true
    fi
    exit 1
}
# Build frontend dist, then cargo with custom-protocol to embed it.
# Using cargo directly (not pnpm tauri build) avoids the bundler which
# opens a window and produces unwanted .deb/.rpm/.AppImage artifacts.
pnpm --dir "$CARGO_DIR" build 2>>"$STATE_DIR/build.log" || true
cargo build --release -p hapax-logos --features tauri/custom-protocol 2>>"$STATE_DIR/build.log"
if [ $? -eq 0 ] || [ -f "$CARGO_DIR/target/release/hapax-logos" ]; then
    # Stop services before replacing binaries
    systemctl --user stop hapax-imagination.service 2>/dev/null || true

    cp "$CARGO_DIR/target/release/hapax-logos" "$LOGOS_BIN"
    cp "$CARGO_DIR/target/release/hapax-imagination" "$IMAGINATION_BIN"

    # Restart imagination (always-on service)
    systemctl --user start hapax-imagination.service 2>/dev/null || true

    echo "$CURRENT_SHA" > "$SHA_FILE"
    logger -t "$LOG_TAG" "rebuild complete — ${CURRENT_SHA:0:8} installed"
    ntfy "Logos rebuild complete" "${CURRENT_SHA:0:8} installed" "default" "white_check_mark"
else
    logger -t "$LOG_TAG" "build failed — see $STATE_DIR/build.log"
    ntfy "Logos rebuild FAILED" "See ~/.cache/hapax/rebuild/build.log" "high" "x"
fi

# Restore branch if we detached
cd "$REPO"
if [ -n "${RESTORE_BRANCH:-}" ]; then
    git checkout "$RESTORE_BRANCH" --quiet 2>/dev/null || true
fi
