#!/usr/bin/env bash
# Ensure the Hapax live-texture DarkPlaces fork is available from persistent
# cache, not /tmp. Prints the executable path on success.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PATCH_FILE="${HAPAX_DARKPLACES_LIVE_TEXTURE_PATCH:-$REPO_DIR/assets/quake/darkplaces/hapax-live-texture.patch}"
CACHE_ROOT="${HAPAX_DARKPLACES_LIVE_TEXTURE_ROOT:-$HOME/.cache/hapax/darkplaces-live-texture}"
SOURCE_REPO="${HAPAX_DARKPLACES_SOURCE_REPO:-/data/cache/paru/clone/darkplaces-git/darkplaces}"
SOURCE_REV="${HAPAX_DARKPLACES_SOURCE_REV:-}"
BUILD_ROOT="$CACHE_ROOT/src"
BUILD_TMP="$CACHE_ROOT/src.tmp.$$"
BIN="$CACHE_ROOT/darkplaces-sdl"
STAMP="$CACHE_ROOT/build.stamp"
BUILD_JOBS="${HAPAX_DARKPLACES_BUILD_JOBS:-$(nproc)}"

need_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "ensure-darkplaces-live-texture-build: missing required command: $1" >&2
        exit 69
    fi
}

patch_hash() {
    sha256sum "$PATCH_FILE" | awk '{print $1}'
}

stamp_matches() {
    local hash="$1"

    [ -x "$BIN" ] || return 1
    [ -f "$STAMP" ] || return 1
    grep -qx "patch_sha256=$hash" "$STAMP" || return 1
    if [ -n "$SOURCE_REV" ]; then
        grep -qx "source_rev=$SOURCE_REV" "$STAMP" || return 1
    fi
}

write_stamp() {
    local hash="$1"
    {
        printf 'patch_sha256=%s\n' "$hash"
        if [ -n "$SOURCE_REV" ]; then
            printf 'source_rev=%s\n' "$SOURCE_REV"
        else
            git -C "$BUILD_ROOT" rev-parse HEAD | sed 's/^/source_rev=/'
        fi
    } >"$STAMP"
}

build_binary() {
    local hash="$1"

    need_cmd git
    need_cmd patch
    need_cmd make
    need_cmd cc
    mkdir -p "$CACHE_ROOT"
    rm -rf "$BUILD_TMP"
    git clone "$SOURCE_REPO" "$BUILD_TMP" >/dev/null 2>&1
    if [ -n "$SOURCE_REV" ]; then
        git -C "$BUILD_TMP" checkout "$SOURCE_REV" >/dev/null 2>&1
    fi
    patch -d "$BUILD_TMP" -p1 <"$PATCH_FILE" >/dev/null
    make -C "$BUILD_TMP" -j"$BUILD_JOBS" DP_FS_BASEDIR=/usr/share/games/quake sdl-release >/dev/null
    rm -rf "$BUILD_ROOT"
    mv "$BUILD_TMP" "$BUILD_ROOT"
    install -m755 "$BUILD_ROOT/darkplaces-sdl" "$BIN"
    write_stamp "$hash"
}

if [ ! -f "$PATCH_FILE" ]; then
    echo "ensure-darkplaces-live-texture-build: missing patch: $PATCH_FILE" >&2
    exit 69
fi

hash="$(patch_hash)"
if ! stamp_matches "$hash"; then
    build_binary "$hash"
fi

printf '%s\n' "$BIN"
