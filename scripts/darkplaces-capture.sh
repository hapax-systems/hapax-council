#!/usr/bin/env bash
# Launch DarkPlaces with obs-glcapture for frame capture.
# On KDE/KWin Wayland, wlr-screencopy is unavailable.
# obs-glcapture hooks OpenGL render calls for zero-copy capture.
#
# The captured frames are available to OBS via the linux-vkcapture plugin,
# or to any application that reads the OBS game capture shared memory.
set -euo pipefail

DEVICE="${DARKPLACES_V4L2_DEVICE:-/dev/video52}"
WIDTH="${DARKPLACES_WIDTH:-1280}"
HEIGHT="${DARKPLACES_HEIGHT:-720}"
GAME_DIR="$HOME/.darkplaces"

# Ensure map is current
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MAP_SRC="$REPO_DIR/assets/quake/maps/screwm.bsp"
MAP_DST="$GAME_DIR/screwm/maps/screwm.bsp"

if [ -f "$MAP_SRC" ] && [ "$MAP_SRC" -nt "$MAP_DST" ] 2>/dev/null; then
    mkdir -p "$GAME_DIR/screwm/maps"
    cp "$MAP_SRC" "$MAP_DST"
    cp "${MAP_SRC%.bsp}.lit" "$GAME_DIR/screwm/maps/" 2>/dev/null || true
fi

mkdir -p "$GAME_DIR/id1"

if [ -f "$REPO_DIR/assets/quake/qc/progs.dat" ]; then
    cp "$REPO_DIR/assets/quake/qc/progs.dat" "$GAME_DIR/screwm/"
fi

# Launch DarkPlaces wrapped with obs-glcapture for zero-copy GL frame capture.
# OBS reads via linux-vkcapture source plugin. The compositor reads from
# OBS's v4l2sink output, or from a dedicated capture pipeline.
exec obs-glcapture darkplaces-sdl \
    -game screwm \
    -window \
    -width "$WIDTH" \
    -height "$HEIGHT" \
    +map screwm \
    +crosshair 0 \
    +r_drawviewmodel 0 \
    +cl_bob 0 \
    +sbar_alpha 0 \
    +sv_cheats 1 \
    +gl_texturemode GL_NEAREST \
    +r_fog 1 \
    +cl_maxfps 30 \
    +showfps 0 \
    +scr_showturtle 0 \
    "$@"
