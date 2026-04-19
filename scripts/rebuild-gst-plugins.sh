#!/usr/bin/env bash
# Auto-rebuild for Rust GStreamer plugins (gst-plugin-glfeedback).
#
# Sibling to ``rebuild-service.sh``. That script handles Python services;
# this one handles Rust gst plugins which must be ``cargo build --release``'d
# and installed to /usr/lib/gstreamer-1.0/ via sudo before a ``studio-compositor``
# restart picks them up.
#
# Why this exists: on 2026-04-18 the installed ``libgstglfeedback.so`` at
# ``/usr/lib/gstreamer-1.0/`` was 3 weeks stale (dated Apr 5) and lacked
# the Python+Rust diff-guard fixes that had been in source for weeks.
# Manual ``cargo build --release`` + ``sudo cp`` were required. This script
# closes that gap by running at a 10-minute cadence parallel to the existing
# ``hapax-rebuild-services.timer`` (which handles Python).
#
# Behaviour:
#   1. For every plugin in PLUGINS[]: check source mtime against last-build
#      timestamp in $STATE_DIR. If source is newer, ``cargo build --release``.
#   2. Compare built ``target/release/libgst*.so`` mtime vs the installed
#      ``/usr/lib/gstreamer-1.0/libgst*.so``. If the built artefact is newer,
#      ``sudo cp`` it over the installed one.
#   3. On any successful install, restart listed services.
#   4. Emit a ntfy notification on install success / build failure / install
#      failure.
#
# Usage:
#   rebuild-gst-plugins.sh                   # default: rebuild all registered plugins
#   rebuild-gst-plugins.sh --plugin NAME     # rebuild a single plugin by name
#   rebuild-gst-plugins.sh --force           # ignore timestamps, always build
#
# Env overrides (primarily for tests):
#   HAPAX_GST_REPO               — plugin repo root (default: ~/projects/hapax-council)
#   HAPAX_GST_INSTALL_DIR        — install target (default: /usr/lib/gstreamer-1.0)
#   HAPAX_GST_STATE_DIR          — state dir (default: ~/.cache/hapax/rebuild-gst)
#   HAPAX_GST_CARGO              — cargo binary (default: cargo)
#   HAPAX_GST_SUDO               — sudo binary (default: sudo; set to empty for no-sudo install)
#   HAPAX_GST_SYSTEMCTL          — systemctl binary (default: systemctl)
#   HAPAX_GST_NTFY_CURL          — curl binary for ntfy (default: curl)
#   HAPAX_GST_SKIP_RESTART=1     — do not restart services (used in tests)
#   NTFY_BASE_URL                — ntfy base URL (default: http://localhost:8090)
set -euo pipefail

REPO="${HAPAX_GST_REPO:-$HOME/projects/hapax-council}"
INSTALL_DIR="${HAPAX_GST_INSTALL_DIR:-/usr/lib/gstreamer-1.0}"
STATE_DIR="${HAPAX_GST_STATE_DIR:-$HOME/.cache/hapax/rebuild-gst}"
CARGO_BIN="${HAPAX_GST_CARGO:-cargo}"
SUDO_BIN="${HAPAX_GST_SUDO-sudo}"
SYSTEMCTL_BIN="${HAPAX_GST_SYSTEMCTL:-systemctl}"
CURL_BIN="${HAPAX_GST_NTFY_CURL:-curl}"
NTFY_URL="${NTFY_BASE_URL:-http://localhost:8090}/hapax-build"
LOG_TAG="hapax-rebuild-gst-plugins"

# Plugin registry. Each entry: "plugin_dir|built_so|installed_so|restart_services".
# ``restart_services`` is space-separated; empty = no restart.
PLUGINS=(
    "gst-plugin-glfeedback|target/release/libgstglfeedback.so|libgstglfeedback.so|studio-compositor.service"
)

FORCE=0
ONE_PLUGIN=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --force)  FORCE=1; shift ;;
        --plugin) ONE_PLUGIN="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,40p' "$0"
            exit 0
            ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

mkdir -p "$STATE_DIR"

# ---------- helpers ----------

log() { logger -t "$LOG_TAG" "$*" 2>/dev/null || true; echo "[$LOG_TAG] $*"; }

ntfy() {
    local title="$1" msg="$2" priority="${3:-default}" tags="${4:-}"
    "$CURL_BIN" -s -o /dev/null \
        -H "Title: $title" \
        -H "Priority: $priority" \
        ${tags:+-H "Tags: $tags"} \
        -d "$msg" \
        "$NTFY_URL" 2>/dev/null || true
}

# mtime of a path, or 0 if missing.
mtime_or_zero() {
    local p="$1"
    if [ -e "$p" ]; then
        stat -c '%Y' "$p" 2>/dev/null || echo 0
    else
        echo 0
    fi
}

# Newest mtime under a directory (recursive), or 0 if empty/missing.
newest_mtime() {
    local d="$1"
    if [ ! -d "$d" ]; then
        echo 0
        return
    fi
    # find+awk is portable; default to 0 on empty.
    find "$d" -type f -printf '%T@\n' 2>/dev/null \
        | awk 'BEGIN{m=0} {if ($1+0 > m) m=$1+0} END{printf "%d\n", m}'
}

# Detects whether source has changed since last recorded build time.
# Returns 0 (true) if a build is needed; 1 otherwise.
source_changed_since() {
    local src_dir="$1" stamp_file="$2"
    local src_mtime stamp
    src_mtime=$(newest_mtime "$src_dir")
    stamp=$(cat "$stamp_file" 2>/dev/null || echo 0)
    if [ "$src_mtime" -gt "$stamp" ]; then
        return 0
    fi
    return 1
}

# Returns 0 if built so is newer than installed so (install needed), 1 otherwise.
built_newer_than_installed() {
    local built="$1" installed="$2"
    local bm im
    bm=$(mtime_or_zero "$built")
    im=$(mtime_or_zero "$installed")
    if [ "$bm" -gt "$im" ]; then
        return 0
    fi
    return 1
}

# ---------- per-plugin pipeline ----------

process_plugin() {
    local plugin_dir="$1"
    local built_rel="$2"
    local installed_name="$3"
    local restart_services="$4"

    local plugin_root="$REPO/$plugin_dir"
    local src_dir="$plugin_root/src"
    local built_path="$plugin_root/$built_rel"
    local installed_path="$INSTALL_DIR/$installed_name"
    local stamp_file="$STATE_DIR/last-build-${plugin_dir//\//_}.ts"

    if [ ! -d "$plugin_root" ]; then
        log "plugin directory missing: $plugin_root — skipping"
        return 0
    fi

    local need_build=0
    if [ "$FORCE" = "1" ]; then
        need_build=1
    elif source_changed_since "$src_dir" "$stamp_file"; then
        need_build=1
    fi

    if [ "$need_build" = "0" ]; then
        # Even with no source change, an install may still be needed (e.g. a
        # fresh clone that has ``target/`` pre-built but nothing installed).
        if built_newer_than_installed "$built_path" "$installed_path"; then
            install_and_restart "$plugin_dir" "$built_path" "$installed_path" "$restart_services"
        fi
        return 0
    fi

    log "building $plugin_dir (src mtime > stamp)"
    if ! (cd "$plugin_root" && "$CARGO_BIN" build --release) >/dev/null 2>&1; then
        log "build FAILED for $plugin_dir"
        ntfy "gst-plugin build FAILED" "$plugin_dir cargo build --release failed" "high" "x"
        return 1
    fi

    # Record successful build timestamp (post-build mtime of source tree).
    newest_mtime "$src_dir" > "$stamp_file"
    log "built $plugin_dir ok"

    if built_newer_than_installed "$built_path" "$installed_path"; then
        install_and_restart "$plugin_dir" "$built_path" "$installed_path" "$restart_services"
    else
        log "built artefact not newer than installed for $plugin_dir — no install"
    fi
}

install_and_restart() {
    local plugin_dir="$1"
    local built_path="$2"
    local installed_path="$3"
    local restart_services="$4"

    local built_mtime installed_mtime delta_desc
    built_mtime=$(mtime_or_zero "$built_path")
    installed_mtime=$(mtime_or_zero "$installed_path")
    delta_desc="$(date -d "@$installed_mtime" +%Y-%m-%d 2>/dev/null || echo ?) → $(date -d "@$built_mtime" +%Y-%m-%d 2>/dev/null || echo ?)"

    log "installing $plugin_dir: $delta_desc"
    local install_cmd=(install -m 0644 "$built_path" "$installed_path")
    if [ -n "$SUDO_BIN" ]; then
        if ! "$SUDO_BIN" -n "${install_cmd[@]}" 2>/dev/null; then
            log "sudo install FAILED for $plugin_dir (path: $installed_path)"
            ntfy "gst-plugin install FAILED" \
                "sudo refused to cp $built_path → $installed_path" \
                "high" "x"
            return 1
        fi
    else
        if ! "${install_cmd[@]}" 2>/dev/null; then
            log "install FAILED for $plugin_dir (no sudo)"
            ntfy "gst-plugin install FAILED" \
                "cp $built_path → $installed_path failed" \
                "high" "x"
            return 1
        fi
    fi

    log "installed $plugin_dir ok"
    ntfy "gst-plugin updated" "$plugin_dir: $delta_desc" "default" "white_check_mark"

    if [ "${HAPAX_GST_SKIP_RESTART:-0}" = "1" ]; then
        log "skipping service restart (HAPAX_GST_SKIP_RESTART=1)"
        return 0
    fi

    local svc
    for svc in $restart_services; do
        [ -z "$svc" ] && continue
        log "restarting $svc"
        if ! "$SYSTEMCTL_BIN" --user restart "$svc" 2>/dev/null; then
            log "$svc restart FAILED"
            ntfy "$svc restart FAILED" "after $plugin_dir install" "high" "x"
        fi
    done
}

# ---------- main ----------

main() {
    # Use flock to prevent concurrent invocations (timer + manual).
    local lock_file="$STATE_DIR/.lock"
    exec 9>"$lock_file"
    if ! flock -n 9; then
        log "another instance is running — exiting"
        exit 0
    fi

    local entry dir built installed services
    for entry in "${PLUGINS[@]}"; do
        IFS='|' read -r dir built installed services <<<"$entry"
        if [ -n "$ONE_PLUGIN" ] && [ "$dir" != "$ONE_PLUGIN" ]; then
            continue
        fi
        process_plugin "$dir" "$built" "$installed" "$services" || true
    done
}

main "$@"
