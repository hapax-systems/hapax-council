#!/usr/bin/env bash
set -euo pipefail

# Tier 2: Nightly remote backup to Backblaze B2 via rclone
# Scope: everything from Tier 1 + git bundles + full system metadata
# Schedule: daily at 03:30 via systemd timer (hapax-backup-remote.timer)
# Runs as user (not root). Database state captured via API dumps.
#
# Re-homed from ~/projects/distro-work (unversioned artifact) and
# receipt-instrumented for audit-w0-backup-integrity-20260611: every
# component leaves a witness in the backup receipt, and the run cannot
# exit green with a failed component (see scripts/hapax-backup-lib.sh).
#
# DR script upload: the previous source (~/.local/bin/hapax-dr-restore.sh)
# never existed on this host — it was the Pop!_OS-era restore script, two
# machine generations old. The current-generation restore script is
# hapax-cachyos-restore.sh in ~/projects/distro-work; a missing source is
# now a witnessed component failure, not a swallowed WARNing.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/hapax-backup-lib.sh
source "$SCRIPT_DIR/hapax-backup-lib.sh"

log "Starting Tier 2 (remote) backup"
receipt_init tier2-remote

# Assignment kept separate from export: `export VAR="$(cmd)"` masks the
# command's exit status, silently exporting empty on pass failure.
RESTIC_PASSWORD="$(pass show backblaze/restic-password)"
RESTIC_REPOSITORY="rclone:b2:hapax-backups/restic"
export RESTIC_PASSWORD RESTIC_REPOSITORY

DR_SCRIPT_SOURCE="${HAPAX_DR_SCRIPT_SOURCE:-$HOME/projects/distro-work/hapax-cachyos-restore.sh}"

# Remove stale locks from a prior interrupted/OOM-killed run (preventive — the B2
# prune was being OOM-killed mid-run, which can leave a stale lock → exit 11).
restic unlock 2>/dev/null || true

DUMP_DIR="/tmp/hapax-backup-dumps-remote"
rm -rf "$DUMP_DIR"
mkdir -p "$DUMP_DIR/qdrant" "$DUMP_DIR/git-bundles"
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

dump_system_metadata() {
    lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT > "$DUMP_DIR/partition-layout.txt" || return 1
    cp /etc/fstab "$DUMP_DIR/fstab-copy.txt" || return 1
    systemctl --user list-unit-files --state=enabled > "$DUMP_DIR/systemd-user-enabled.txt" || return 1
    systemctl list-unit-files --state=enabled > "$DUMP_DIR/systemd-system-enabled.txt" || return 1
    # crontab -l exits 1 when the user has no crontab — that is a valid state
    crontab -l > "$DUMP_DIR/crontab-user.txt" 2>/dev/null \
        || echo "(no user crontab)" > "$DUMP_DIR/crontab-user.txt"
}

dump_git_bundles() {
    local repo name failed=0
    for repo in "$HOME"/projects/*/; do
        [[ -d "$repo/.git" ]] || continue
        name="$(basename "$repo")"
        if ! git -C "$repo" bundle create "$DUMP_DIR/git-bundles/${name}.bundle" --all 2>/dev/null; then
            echo "bundle failed for $name"
            failed=$((failed + 1))
        fi
        git -C "$repo" stash list > "$DUMP_DIR/git-stash-${name}.txt" || failed=$((failed + 1))
        git -C "$repo" diff > "$DUMP_DIR/git-diff-${name}.patch" || failed=$((failed + 1))
    done
    echo "git bundles captured ($failed failures)"
    (( failed == 0 ))
}

run_restic_backup() {
    restic backup \
        --verbose \
        --tag "tier2-remote" \
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
        --keep-weekly 4 \
        --keep-monthly 2 \
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

log "Capturing system metadata..."
component system_metadata dump_system_metadata

log "Creating git bundles..."
component git_bundles dump_git_bundles

# Witness record so far travels inside the snapshot itself
receipt_precommit "$DUMP_DIR/backup-receipt-precommit.json"

log "Running restic backup to B2..."
component_required restic_backup run_restic_backup

log "Applying retention policy (4 weekly, 2 monthly)..."
component retention_prune run_retention

# Upload current-generation DR restore script independently (accessible without restic)
log "Uploading DR restore script to B2..."
backup_dr_script_upload "$DR_SCRIPT_SOURCE" "b2:hapax-backups/dr-scripts/"

log "Tier 2 backup complete"
restic snapshots --latest 1 || true

notify-send -u low "Backup" "Tier 2 (remote → B2) backup complete" 2>/dev/null || true

receipt_complete
