#!/usr/bin/env bash
# install-compositor-layout.sh — install the canonical compositor layout
# to the user config directory on first run.
#
# Usage: ./scripts/install-compositor-layout.sh
#
# Installs config/compositor-layouts/default.json to
# $XDG_CONFIG_HOME/hapax-compositor/layouts/default.json (or
# $HOME/.config/hapax-compositor/layouts/default.json if XDG_CONFIG_HOME
# is unset). If the destination already exists, it is left in place so
# operator edits survive re-runs — delete the file manually to force
# reinstall.
#
# Part of the compositor source-registry epic, Phase D task 12. See
# docs/superpowers/plans/2026-04-12-compositor-source-registry-foundation-plan.md.

set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)/config/compositor-layouts/default.json"
DEST_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/hapax-compositor/layouts"
DEST="$DEST_DIR/default.json"

if [ ! -f "$SRC" ]; then
    echo "error: source layout not found at $SRC" >&2
    exit 1
fi

mkdir -p "$DEST_DIR"
if [ -f "$DEST" ]; then
    echo "layout already installed at $DEST; leaving in place"
    exit 0
fi
install -m 644 "$SRC" "$DEST"
echo "installed $DEST"
