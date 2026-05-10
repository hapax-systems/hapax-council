#!/usr/bin/env bash
# install-compositor-layouts.sh — install all known compositor layouts.
#
# Usage: ./scripts/install-compositor-layouts.sh
#
# Installs current runtime layouts from config/compositor-layouts/ and
# config/layouts/ to
# $XDG_CONFIG_HOME/hapax-compositor/layouts/ (or ~/.config/...).
#
# Existing files are left in place so operator edits survive re-runs.
# Delete a file manually to force reinstall on the next run.
#
# Required by u6-periodic-tick-driver and segment layout control. Retired
# static layouts (default-legacy, vinyl-focus) are intentionally not
# installed; if old copies exist in the user config directory, remove
# them by hand rather than reviving them here.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/hapax-compositor/layouts"

mkdir -p "$DEST_DIR"

required_layouts=(
    "$REPO_ROOT/config/compositor-layouts/default.json"
    "$REPO_ROOT/config/compositor-layouts/consent-safe.json"
    "$REPO_ROOT/config/compositor-layouts/segment-chat.json"
    "$REPO_ROOT/config/compositor-layouts/segment-compare.json"
    "$REPO_ROOT/config/compositor-layouts/segment-detail.json"
    "$REPO_ROOT/config/compositor-layouts/segment-list.json"
    "$REPO_ROOT/config/compositor-layouts/segment-poll.json"
    "$REPO_ROOT/config/compositor-layouts/segment-programme-context.json"
    "$REPO_ROOT/config/compositor-layouts/segment-receipt.json"
    "$REPO_ROOT/config/compositor-layouts/segment-tier.json"
    "$REPO_ROOT/config/layouts/garage-door.json"
)

missing=0
for src in "${required_layouts[@]}"; do
    if [ ! -f "$src" ]; then
        echo "ERROR: required source layout not found at $src" >&2
        missing=1
    fi
done
if [ "$missing" != "0" ]; then
    exit 1
fi

install_one() {
    local src="$1"
    local name
    name="$(basename "$src")"
    local dest="$DEST_DIR/$name"
    if [ -f "$dest" ]; then
        echo "  skip $name (already installed; delete $dest to force reinstall)"
        return 0
    fi
    install -m 644 "$src" "$dest"
    echo "  installed $name"
}

echo "Installing layouts to $DEST_DIR"
for src in "${required_layouts[@]}"; do
    install_one "$src"
done

echo "Done."
