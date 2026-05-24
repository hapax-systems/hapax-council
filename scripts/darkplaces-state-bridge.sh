#!/usr/bin/env bash
# Bridge external state files into the DarkPlaces game directory.
# QuakeC fopen is sandboxed to the game directory — this sidecar
# copies live state from /dev/shm into the game's data/ directory.
set -euo pipefail

GAME_DIR="${HOME}/.darkplaces/screwm/data"
SHM_DIR="/dev/shm/hapax-compositor"
UNIFORMS_FILE="/dev/shm/hapax-imagination/uniforms.json"
MODE_FILE="${HOME}/.cache/hapax/working-mode"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
EXPORTER="${REPO_DIR}/scripts/darkplaces-state-export.py"

mkdir -p "$GAME_DIR"

while true; do
    if ! "$EXPORTER" --game-dir "$GAME_DIR" --shm-dir "$SHM_DIR" --mode-file "$MODE_FILE" --uniforms-file "$UNIFORMS_FILE" 2>/dev/null; then
        # Keep the original minimal bridge alive if Python/export parsing fails.
        if [ -f "$MODE_FILE" ]; then
            cp "$MODE_FILE" "$GAME_DIR/working-mode.txt" 2>/dev/null || true
        fi
        if [ -f "$SHM_DIR/stimmung-energy.txt" ]; then
            cp "$SHM_DIR/stimmung-energy.txt" "$GAME_DIR/stimmung-energy.txt" 2>/dev/null || true
        fi
        if [ -f "$SHM_DIR/voice-active.txt" ]; then
            cp "$SHM_DIR/voice-active.txt" "$GAME_DIR/voice-active.txt" 2>/dev/null || true
        fi
    fi

    sleep 1
done
