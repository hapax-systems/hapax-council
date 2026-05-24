#!/usr/bin/env bash
# Install source-controlled Screwm assets into DarkPlaces' game directory.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
GAME_ROOT="${DARKPLACES_GAME_ROOT:-$HOME/.darkplaces}"
GAME_DIR="$GAME_ROOT/screwm"

install -d "$GAME_ROOT/id1"
install -d "$GAME_DIR/maps" "$GAME_DIR/progs" "$GAME_DIR/sound" "$GAME_DIR/glsl"

if [ -d "$REPO_DIR/assets/quake/maps" ]; then
    find "$REPO_DIR/assets/quake/maps" -maxdepth 1 -type f \
        \( -name '*.bsp' -o -name '*.lit' -o -name '*.map' -o -name '*.prt' -o -name '*.wad' \) \
        -exec install -m 0644 {} "$GAME_DIR/maps/" \;
fi

if [ -f "$REPO_DIR/assets/quake/maps/screwm.wad" ]; then
    install -m 0644 "$REPO_DIR/assets/quake/maps/screwm.wad" "$GAME_DIR/screwm.wad"
fi

if [ -f "$REPO_DIR/assets/quake/qc/progs.dat" ]; then
    install -m 0644 "$REPO_DIR/assets/quake/qc/progs.dat" "$GAME_DIR/progs.dat"
fi

if [ -f "$REPO_DIR/assets/quake/models/aoa.mdl" ]; then
    install -m 0644 "$REPO_DIR/assets/quake/models/aoa.mdl" "$GAME_DIR/progs/aoa.mdl"
fi

if [ -d "$REPO_DIR/assets/quake/sound" ]; then
    cp -a "$REPO_DIR/assets/quake/sound/." "$GAME_DIR/sound/"
fi

if [ -d "$REPO_DIR/assets/quake/glsl" ]; then
    cp -a "$REPO_DIR/assets/quake/glsl/." "$GAME_DIR/glsl/"
fi

if [ -d "$REPO_DIR/assets/quake/config" ]; then
    cp -a "$REPO_DIR/assets/quake/config/." "$GAME_DIR/"
fi
