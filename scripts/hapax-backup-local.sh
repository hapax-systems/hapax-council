#!/usr/bin/env bash
set -euo pipefail

# Tier 1: Daily backup to NAS restic repo (was /store, migrated 2026-05-11)
# Scope: configs, secrets, state — everything that's hard to recreate
# Schedule: daily at 03:00 via systemd timer (hapax-backup-local.timer)
# Runs as user (not root). Database state captured via API dumps.
# Repo on Synology DS425+ NAS via NFS for true DR (separate physical device).
#
# Re-homed from ~/projects/distro-work (unversioned artifact) and
# receipt-instrumented for audit-w0-backup-integrity-20260611: every
# component leaves a witness in the backup receipt, and the run cannot
# exit green with a failed component (see scripts/hapax-backup-lib.sh).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/hapax-backup-lib.sh
source "$SCRIPT_DIR/hapax-backup-lib.sh"

log "Starting Tier 1 (local) backup"
receipt_init tier1-local

# Assignment kept separate from export: `export VAR="$(cmd)"` masks the
# command's exit status, silently exporting empty on pass failure.
RESTIC_PASSWORD="$(pass show backups/restic-password)"
RESTIC_REPOSITORY="/mnt/nas/backups/restic"
export RESTIC_PASSWORD RESTIC_REPOSITORY

# Remove stale locks left by a prior interrupted run — a recurring exit-11 cause
# (e.g. a backup killed mid-run, or the 2026-06-03 disk failure mid-backup).
restic unlock 2>/dev/null || true

# Pre-flight: dump databases for consistent backup
DUMP_DIR="/tmp/hapax-backup-dumps"
rm -rf "$DUMP_DIR"
mkdir -p "$DUMP_DIR/qdrant"
HAPAX_BACKUP_CLEANUP_DIR="$DUMP_DIR"  # removed by the receipt EXIT trap

dump_postgres() {
    docker exec postgres pg_dumpall -U hapax > "$DUMP_DIR/postgres-all.sql"
}

dump_qdrant() {
    local colls
    colls="$(curl -sf http://127.0.0.1:6333/collections | jq -r '.result.collections[].name')" \
        || { echo "cannot list qdrant collections"; return 1; }
    if [[ -z "$colls" ]]; then
        echo "qdrant returned 0 collections"
        return 1
    fi
    local ok=0 failed=0 coll snap_name
    for coll in $colls; do
        snap_name="$(curl -sf -X POST "http://127.0.0.1:6333/collections/${coll}/snapshots" \
            | jq -r '.result.name' 2>/dev/null)" || snap_name=""
        if [[ -n "$snap_name" && "$snap_name" != "null" ]] \
            && curl -sf "http://127.0.0.1:6333/collections/${coll}/snapshots/${snap_name}" \
                -o "$DUMP_DIR/qdrant/${coll}.snapshot"; then
            ok=$((ok + 1))
        else
            echo "snapshot failed for $coll"
            failed=$((failed + 1))
        fi
    done
    echo "$ok collections snapshotted, $failed failed"
    (( failed == 0 ))
}

# NOTE: component functions run with errexit suspended (they are invoked
# behind `||` in the component runner), so every step that must fail the
# witness needs an explicit `|| return 1`.
dump_docker_metadata() {
    docker volume ls --format '{{.Name}}' > "$DUMP_DIR/docker-volumes.txt" || return 1
    docker volume ls -q | while read -r vol; do
        docker volume inspect "$vol"
    done > "$DUMP_DIR/docker-volume-inspect.json" || return 1
}

dump_package_lists() {
    pacman -Qe > "$DUMP_DIR/pacman-explicit.txt" || return 1
    # pacman -Qm exits 1 when there are no foreign packages — empty list is valid
    pacman -Qm > "$DUMP_DIR/pacman-aur.txt" || true
    if command -v flatpak >/dev/null; then
        flatpak list --app --columns=application,origin > "$DUMP_DIR/flatpak-apps.txt" || return 1
    else
        echo "flatpak not installed (skipped)" > "$DUMP_DIR/flatpak-apps.txt"
    fi
}

dump_git_state() {
    local repo name failed=0
    for repo in "$HOME"/projects/*/; do
        [[ -d "$repo/.git" ]] || continue
        name="$(basename "$repo")"
        git -C "$repo" stash list > "$DUMP_DIR/git-stash-${name}.txt" || failed=$((failed + 1))
        git -C "$repo" diff > "$DUMP_DIR/git-diff-${name}.patch" || failed=$((failed + 1))
        git -C "$repo" diff --cached > "$DUMP_DIR/git-staged-${name}.patch" || failed=$((failed + 1))
        git -C "$repo" log --oneline -5 > "$DUMP_DIR/git-log-${name}.txt" || failed=$((failed + 1))
    done
    echo "git state captured ($failed failures)"
    (( failed == 0 ))
}

run_restic_backup() {
    restic backup \
        --verbose \
        --tag "tier1-local" \
        "$DUMP_DIR" \
        "$HOME/.config/fish/" \
        "$HOME/.gitconfig" \
        "$HOME/.config/hypr/" \
        "$HOME/.config/waybar/" \
        "$HOME/.config/foot/" \
        "$HOME/.config/fuzzel/" \
        "$HOME/.config/mako/" \
        "$HOME/.config/kanshi/" \
        "$HOME/.config/starship.toml" \
        "$HOME/.config/environment.d/" \
        "$HOME/.config/systemd/user/" \
        "$HOME/.config/autostart/" \
        "$HOME/.config/aichat/" \
        "$HOME/.config/mods/" \
        "$HOME/.config/gtk-3.0/" \
        "$HOME/.config/gtk-4.0/" \
        "$HOME/.config/qt6ct/" \
        "$HOME/.config/rclone/" \
        "$HOME/.config/hapax-daimonion/" \
        "$HOME/.config/wireplumber/" \
        "$HOME/.config/pipewire/" \
        "$HOME/.local/state/wireplumber/" \
        "$HOME/.config/gh/" \
        "$HOME/.config/atuin/" \
        "$HOME/.config/fabric/" \
        "$HOME/.claude/" \
        "$HOME/.local/bin/" \
        "$HOME/.local/share/atuin/" \
        "$HOME/.local/share/hapax-daimonion/" \
        "$HOME/.local/share/keyrings/" \
        "$HOME/models/" \
        "$HOME/.gnupg/" \
        "$HOME/.password-store/" \
        "$HOME/.ssh/" \
        "$HOME/.local/share/fonts/" \
        "$HOME/llm-stack/" \
        /etc/fstab \
        /etc/docker/daemon.json \
        /etc/bluetooth/main.conf \
        /etc/udev/rules.d/ \
        /etc/sysctl.d/ \
        /etc/NetworkManager/conf.d/ \
        /etc/systemd/journald.conf.d/ \
        /etc/modprobe.d/ \
        --exclude="*.pyc" \
        --exclude="__pycache__" \
        --exclude=".venv" \
        --exclude="node_modules" \
        --exclude=".cache" \
        --exclude="*.sock" \
        --exclude="*.lock" \
        --exclude="llm-stack/comfyui"
}

run_retention() {
    restic forget \
        --keep-daily 7 \
        --keep-weekly 4 \
        --keep-monthly 3 \
        --prune
}

log "Dumping PostgreSQL..."
component postgres_dump dump_postgres

log "Snapshotting Qdrant collections..."
component qdrant_snapshots dump_qdrant

log "Exporting n8n workflows..."
backup_n8n_export "$DUMP_DIR"

log "Capturing Docker volume metadata..."
component docker_volume_metadata dump_docker_metadata

log "Capturing package lists..."
component package_lists dump_package_lists

log "Capturing git repo state..."
component git_state dump_git_state

# Witness record so far travels inside the snapshot itself
receipt_precommit "$DUMP_DIR/backup-receipt-precommit.json"

log "Running restic backup..."
component_required restic_backup run_restic_backup

log "Applying retention policy (7 daily, 4 weekly, 3 monthly)..."
component retention_prune run_retention

log "Tier 1 backup complete"
restic snapshots --latest 1 || true

notify-send -u low "Backup" "Tier 1 (local) backup complete" 2>/dev/null || true

receipt_complete
