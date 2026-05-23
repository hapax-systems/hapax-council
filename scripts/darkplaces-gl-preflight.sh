#!/usr/bin/env bash
# Fail-closed OpenGL renderer preflight for DarkPlaces launch paths.
set -euo pipefail

EXPECTED_GPU_INDEX="${HAPAX_DARKPLACES_EXPECTED_GPU_INDEX:-1}"
EXPECTED_GL_RENDERER="${HAPAX_DARKPLACES_EXPECTED_GL_RENDERER:-}"
SKIP_GL_RENDERER_ASSERT="${HAPAX_DARKPLACES_SKIP_GL_RENDERER_ASSERT:-0}"

resolve_expected_gl_renderer() {
    if [ "$SKIP_GL_RENDERER_ASSERT" = "1" ]; then
        return
    fi
    if [ -n "$EXPECTED_GL_RENDERER" ]; then
        printf '%s\n' "$EXPECTED_GL_RENDERER"
        return
    fi
    if ! command -v nvidia-smi >/dev/null 2>&1; then
        return
    fi
    nvidia-smi -i "$EXPECTED_GPU_INDEX" --query-gpu=name --format=csv,noheader,nounits 2>/dev/null |
        sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

extract_glxinfo_renderer() {
    awk -F': ' '/OpenGL renderer string/ { print $2; found=1; exit } END { if (!found) exit 1 }'
}

expected="$(resolve_expected_gl_renderer || true)"

if [ -z "$expected" ]; then
    echo "darkplaces-gl-preflight: skipped; no expected GL renderer resolved" >&2
    exit 0
fi

if ! command -v glxinfo >/dev/null 2>&1; then
    echo "darkplaces-gl-preflight: glxinfo unavailable; refusing DarkPlaces launch" >&2
    exit 4
fi

observed="$(glxinfo -B 2>/dev/null | extract_glxinfo_renderer || true)"
if [ -z "$observed" ]; then
    echo "darkplaces-gl-preflight: glxinfo did not report OpenGL renderer; refusing DarkPlaces launch" >&2
    exit 4
fi

if [[ "$observed" != *"$expected"* ]]; then
    printf "darkplaces-gl-preflight: refusing launch; observed GL renderer '%s', expected '%s'\n" \
        "$observed" "$expected" >&2
    exit 4
fi

printf "darkplaces-gl-preflight: GL renderer OK: %s\n" "$observed" >&2
