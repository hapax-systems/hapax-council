#!/usr/bin/env bash
# Launch DarkPlaces rendering the Screwm tower.
# Outputs to a window; frame capture handled separately.
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/darkplaces-runtime-guard.sh"

MAP="screwm"
WIDTH="${SCREWM_WIDTH:-1280}"
HEIGHT="${SCREWM_HEIGHT:-720}"

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
"$REPO_DIR/scripts/install-darkplaces-screwm-assets.sh"

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
