#!/usr/bin/env bash
# Rebuild + install the screwm GPU drift daemons (screwm-drift-field, screwm-media-drift)
# after source activation.
#
# The DarkPlaces engine has ensure-darkplaces-live-texture-build.sh + a rebuild .path/.service,
# so engine-side (C/GLSL) changes reach the live binary on every source-activation cutover. The
# Rust GPU daemons had NO equivalent — they ran a hand-built ~/.local/bin binary that went stale,
# so daemon-side WGSL/Rust changes (per-zone drift currency #3995, the temporal-feedback substrate
# #4000, the media-drift ACES egress #3997) never reached production. This closes that gap by
# mirroring the darkplaces on-activation pattern for the Rust daemons.
#
# Idempotent: a content-hash stamp skips the (multi-minute) cargo build when the deployed
# hapax-visual source is unchanged. flock-serialized against a manual `just install-screwm-*`.
# Builds into a DEDICATED CARGO_TARGET_DIR (build-target-screwm) so it never contends with
# rebuild-logos.sh's build-target (different source trees on one target dir => cargo-lock blocking
# + fingerprint thrash). Driven from the source-activation worktree (the health-probed, deployed
# SHA), matching the darkplaces precedent.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"   # source-activation worktree root when run from there
CRATE_DIR="$REPO_DIR/hapax-logos/crates/hapax-visual"
MEDIA_WGSL="$REPO_DIR/agents/shaders/nodes/media_drift.wgsl"  # screwm_media_drift embeds this out-of-tree
STATE_DIR="$HOME/.cache/hapax/screwm-gpu-drift"
STAMP="$STATE_DIR/build.stamp"
LOCK="$STATE_DIR/lock"
BIN_DIR="$HOME/.local/bin"
# Dedicated build target so concurrent rebuild-logos (build-target) never blocks/thrashes us.
export HAPAX_BUILD_TARGET="${HAPAX_BUILD_TARGET:-$HOME/.cache/hapax/build-target-screwm}"

mkdir -p "$STATE_DIR"

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "ensure-screwm-gpu-drift-build: missing $1" >&2; exit 1; }; }
need_cmd cargo
need_cmd just

if [ ! -f "$CRATE_DIR/Cargo.toml" ]; then
    echo "ensure-screwm-gpu-drift-build: crate not found at $CRATE_DIR" >&2
    exit 1
fi

# Hash the daemon Rust sources + the WGSL embedded via include_str! (the crate's shaders/ AND
# agents/shaders/nodes/media_drift.wgsl) so exactly a real source change triggers a rebuild.
src_hash() {
    {
        find "$CRATE_DIR/src" -type f -name '*.rs' -print0 2>/dev/null
        find "$CRATE_DIR/shaders" -type f -name '*.wgsl' -print0 2>/dev/null
        [ -f "$MEDIA_WGSL" ] && printf '%s\0' "$MEDIA_WGSL"
    } | sort -z | xargs -0 sha256sum 2>/dev/null | sha256sum | cut -d' ' -f1
}

hash="$(src_hash)"
if [ -x "$BIN_DIR/screwm-drift-field" ] && [ -x "$BIN_DIR/screwm-media-drift" ] \
    && [ -f "$STAMP" ] && grep -qx "src_sha256=$hash" "$STAMP"; then
    echo "ensure-screwm-gpu-drift-build: up to date ($hash)"
    exit 0
fi

exec 9>"$LOCK"
if ! flock -n 9; then
    echo "ensure-screwm-gpu-drift-build: another build holds the lock — skipping"
    exit 0
fi

echo "ensure-screwm-gpu-drift-build: building screwm GPU drift daemons (src $hash, target $HAPAX_BUILD_TARGET)..."
cd "$REPO_DIR/hapax-logos"
just install-screwm-drift-field
just install-screwm-media-drift
printf 'src_sha256=%s\n' "$hash" > "$STAMP"
echo "ensure-screwm-gpu-drift-build: done ($hash)"
