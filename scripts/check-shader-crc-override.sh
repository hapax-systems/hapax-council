#!/usr/bin/env bash
# check-shader-crc-override.sh — Screwm Phase 1 P0 GATE.
#
# Protects the unified-fx prime directive: the screen-space shader overrides
# assets/quake/glsl/combined_crc{59807,27804}.glsl are DELIBERATE DIAGNOSTIC
# CANARIES (release-grade expression is geometry-bound, not screen-space).
# Any shader_glsl.h edit changes the builtin CRC and ORPHANS these overrides
# (the loader builds glsl/combined_crc<builtincrc>.glsl from the *current*
# builtin CRC — gl_rmain.c:~1111); a regenerated override must stay a canary
# and must NEVER re-introduce a production screen-space override.
#
# This gate enforces, pre-build:
#   1. both override files exist and are BYTE-IDENTICAL to each other
#      (the byte-exact contract test asserts crc27804 == crc59807),
#   2. they carry the diagnostic/geometry-bound canary markers,
#   3. they carry NO production screen-space markers.
#
# Wire it into ensure-darkplaces-live-texture-build.sh before the build, and
# re-run after any CRC regeneration. Orphan-CRC detection (recomputing the
# builtin CRC vs the filename suffix) is a follow-up — it requires replicating
# the DarkPlaces CRC and is added alongside the shader-edit increment.
#
# Exit 0 = canaries intact; non-zero = prime-directive violation.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Optional override dir (first arg) for testing; defaults to the repo assets.
glsl_dir="${1:-$repo_root/assets/quake/glsl}"
a="$glsl_dir/combined_crc59807.glsl"
b="$glsl_dir/combined_crc27804.glsl"

fail() { echo "check-shader-crc-override: FAIL — $1" >&2; exit 1; }

[ -f "$a" ] || fail "missing override $a"
[ -f "$b" ] || fail "missing override $b"

# (1) byte-identical canaries
cmp -s "$a" "$b" || fail "overrides diverged: $a != $b (the canaries must be byte-identical)"

# (2) diagnostic / geometry-bound markers MUST be present
diagnostic_markers=(
  "Screwm/Scroom diagnostic post-processing"
  "screen-space shader canary"
  "Release-grade expression is geometry-bound"
)
for m in "${diagnostic_markers[@]}"; do
  grep -qF "$m" "$a" || fail "diagnostic marker missing (canary downgraded?): '$m'"
done

# (3) production screen-space markers MUST be absent (prime directive)
production_markers=(
  "entity-local drift/compositing field"
  "All effects operate on the WORLD"
  "Effects run unconditionally"
)
for m in "${production_markers[@]}"; do
  ! grep -qF "$m" "$a" \
    || fail "production screen-space marker re-introduced (prime-directive violation): '$m'"
done

echo "check-shader-crc-override: OK — canaries byte-identical, geometry-bound, no production override"
