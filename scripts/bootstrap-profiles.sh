#!/usr/bin/env bash
# Bootstrap ~/.hapax directory structure.
# Links profile output directory so Tauri commands find agent-written data.
# Safe to run repeatedly — handles existing symlinks, dirs, and missing targets.
set -euo pipefail

HAPAX_DIR="$HOME/.hapax"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_PROFILES="$REPO_DIR/profiles"

mkdir -p "$HAPAX_DIR"

# Symlink profiles/ → project profiles dir (where agents write via PROFILES_DIR)
if [[ -L "$HAPAX_DIR/profiles" ]]; then
    target=$(readlink "$HAPAX_DIR/profiles")
    if [[ "$target" != "$PROJECT_PROFILES" ]]; then
        echo "Updating profiles symlink: $target → $PROJECT_PROFILES"
        ln -sfn "$PROJECT_PROFILES" "$HAPAX_DIR/profiles"
    fi
elif [[ -d "$HAPAX_DIR/profiles" ]]; then
    echo "WARNING: $HAPAX_DIR/profiles is a real directory — moving to .bak"
    mv "$HAPAX_DIR/profiles" "$HAPAX_DIR/profiles.bak.$(date +%s)"
    ln -s "$PROJECT_PROFILES" "$HAPAX_DIR/profiles"
else
    ln -s "$PROJECT_PROFILES" "$HAPAX_DIR/profiles"
fi

# operator.json — Tauri reads ~/.hapax/operator.json for goals panel
# Agents write operator-profile.json in profiles/
if [[ ! -e "$HAPAX_DIR/operator.json" && -f "$PROJECT_PROFILES/operator-profile.json" ]]; then
    ln -s "$PROJECT_PROFILES/operator-profile.json" "$HAPAX_DIR/operator.json"
fi

echo "Bootstrap: $HAPAX_DIR/profiles → $PROJECT_PROFILES"
