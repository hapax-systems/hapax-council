#!/usr/bin/env bash
# Launch DarkPlaces with obs-glcapture for OBS game capture.
# On KDE/KWin Wayland, wlr-screencopy is unavailable.
# obs-glcapture hooks OpenGL render calls for zero-copy capture.
#
# The captured frames are available to OBS via the linux-vkcapture plugin,
# or to any application that reads the OBS game capture shared memory.
# This script does not write the dedicated DarkPlaces v4l2loopback device;
# use darkplaces-v4l2-xvfb.sh for the direct headless renderer feed.
set -euo pipefail

# shellcheck source=scripts/darkplaces-runtime-guard.sh
source "$(cd "$(dirname "$0")" && pwd)/darkplaces-runtime-guard.sh"

DEVICE="${HAPAX_DARKPLACES_V4L2_DEVICE:-${DARKPLACES_V4L2_DEVICE:-/dev/video52}}"
WIDTH="${DARKPLACES_WIDTH:-1280}"
HEIGHT="${DARKPLACES_HEIGHT:-720}"

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
"$REPO_DIR/scripts/darkplaces-gl-preflight.sh"
"$REPO_DIR/scripts/install-darkplaces-screwm-assets.sh"

printf 'darkplaces-capture: OBS capture mode; dedicated renderer loopback is %s\n' "$DEVICE" >&2

# Launch DarkPlaces wrapped with obs-glcapture for zero-copy GL frame capture.
# OBS reads via linux-vkcapture source plugin. The compositor reads from
# the dedicated DarkPlaces loopback when darkplaces-v4l2-xvfb.sh is used.
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
