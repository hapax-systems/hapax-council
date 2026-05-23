#!/usr/bin/env bash
# Launch DarkPlaces rendering the Screwm tower.
# Outputs to a window; frame capture handled separately.
set -euo pipefail

GAME_DIR="$HOME/.darkplaces"
MAP="screwm"
WIDTH="${SCREWM_WIDTH:-1280}"
HEIGHT="${SCREWM_HEIGHT:-720}"

# Ensure map is current
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MAP_SRC="$REPO_DIR/assets/quake/maps/screwm.bsp"
MAP_DST="$GAME_DIR/screwm/maps/screwm.bsp"

if [ -f "$MAP_SRC" ] && [ "$MAP_SRC" -nt "$MAP_DST" ] 2>/dev/null; then
    mkdir -p "$GAME_DIR/screwm/maps"
    cp "$MAP_SRC" "$MAP_DST"
    cp "${MAP_SRC%.bsp}.lit" "$GAME_DIR/screwm/maps/" 2>/dev/null || true
fi

# DarkPlaces needs id1 directory to exist (even empty for shareware mode)
mkdir -p "$GAME_DIR/id1"

# Copy QuakeC progs if available
if [ -f "$REPO_DIR/assets/quake/qc/progs.dat" ]; then
    cp "$REPO_DIR/assets/quake/qc/progs.dat" "$GAME_DIR/screwm/"
fi

exec darkplaces-sdl \
    -game screwm \
    -window \
    -width "$WIDTH" \
    -height "$HEIGHT" \
    +map "$MAP" \
    +crosshair 0 \
    +r_drawviewmodel 0 \
    +cl_bob 0 \
    +sbar_alpha 0 \
    +sv_cheats 1 \
    +gl_texturemode GL_NEAREST \
    +r_fog 1 \
    +cl_maxfps 30 \
    "$@"
