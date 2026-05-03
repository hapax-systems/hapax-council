#!/usr/bin/env bash
# install-compositor-layouts.sh — install all known compositor layouts.
#
# Usage: ./scripts/install-compositor-layouts.sh
#
# Installs all 4 layouts the LayoutSwitcher knows about
# (default, default-legacy, consent-safe, vinyl-focus) plus garage-door
# from config/compositor-layouts/ and config/layouts/ to
# $XDG_CONFIG_HOME/hapax-compositor/layouts/ (or ~/.config/...).
#
# Existing files are left in place so operator edits survive re-runs.
# Delete a file manually to force reinstall on the next run.
#
# Required by u6-periodic-tick-driver — without these JSONs in the
# user-config directory, the LayoutSwitcher cannot apply switches and
# the surface stays pinned to ``garage-door``.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/hapax-compositor/layouts"

mkdir -p "$DEST_DIR"

install_one() {
    local src="$1"
    local name
    name="$(basename "$src")"
    local dest="$DEST_DIR/$name"
    if [ ! -f "$src" ]; then
        echo "WARN: source layout not found at $src" >&2
        return 0
    fi
    if [ -f "$dest" ]; then
        echo "  skip $name (already installed; delete $dest to force reinstall)"
        return 0
    fi
    install -m 644 "$src" "$dest"
    echo "  installed $name"
}

echo "Installing layouts to $DEST_DIR"
install_one "$REPO_ROOT/config/compositor-layouts/default.json"
install_one "$REPO_ROOT/config/compositor-layouts/default-legacy.json"
install_one "$REPO_ROOT/config/compositor-layouts/consent-safe.json"
install_one "$REPO_ROOT/config/compositor-layouts/examples/vinyl-focus.json"
install_one "$REPO_ROOT/config/layouts/garage-door.json"

echo "Done."
