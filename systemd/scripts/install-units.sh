#!/usr/bin/env bash
# install-units.sh — Symlink systemd user units from repo to ~/.config/systemd/user/
# and reload the daemon. Safe to run idempotently.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../units" && pwd)"
PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DEST_DIR="${HOME}/.config/systemd/user"

# Ensure all optional dependency groups are installed.
# Services run via `uv run` which uses the default venv — if optional
# extras (sync-pipeline, logos-api, audio) aren't installed, agents
# crash with ModuleNotFoundError at runtime.
echo "Syncing venv with all extras..."
(cd "$PROJECT_DIR" && uv sync --all-extras --quiet)
echo "venv synced"

mkdir -p "$DEST_DIR"

changed=0
new_timers=()
for unit in "$REPO_DIR"/*.service "$REPO_DIR"/*.timer "$REPO_DIR"/*.target "$REPO_DIR"/*.path; do
    [ -f "$unit" ] || continue
    name="$(basename "$unit")"
    dest="$DEST_DIR/$name"
    # Already a correct symlink — skip
    if [ -L "$dest" ] && [ "$(readlink "$dest")" = "$unit" ]; then
        continue
    fi
    is_new=0
    [ -e "$dest" ] || is_new=1
    ln -sf "$unit" "$dest"
    echo "linked: $name"
    changed=$((changed + 1))
    # Track newly installed timers so we can enable them after daemon-reload.
    if [ "$is_new" -eq 1 ] && [[ "$name" == *.timer ]]; then
        new_timers+=("$name")
    fi
done

if [ "$changed" -gt 0 ]; then
    systemctl --user daemon-reload
    echo "daemon-reload done ($changed units linked)"

    # Enable any newly installed timers — operator should not have to do this
    # by hand for every new unit. Existing timers are left alone (idempotent
    # re-runs do not re-enable already-enabled timers). Set SKIP_TIMER_ENABLE=1
    # to suppress for a one-off install.
    if [ "${SKIP_TIMER_ENABLE:-0}" != "1" ]; then
        for timer in "${new_timers[@]}"; do
            if systemctl --user enable --now "$timer" 2>/dev/null; then
                echo "enabled: $timer"
            else
                echo "WARN: failed to enable $timer (run manually)" >&2
            fi
        done
    elif [ "${#new_timers[@]}" -gt 0 ]; then
        echo "skipped enabling ${#new_timers[@]} new timer(s) (SKIP_TIMER_ENABLE=1)"
    fi
else
    echo "all units up to date"
fi
