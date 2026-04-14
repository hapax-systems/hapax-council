#!/usr/bin/env bash
# install-units.sh — Symlink systemd user units from repo to ~/.config/systemd/user/
# and reload the daemon. Safe to run idempotently.
#
# IMPORTANT: run ONLY from the primary alpha worktree
# (~/projects/hapax-council). Running from any other worktree re-links
# every unit to that worktree's path — when the worktree is later
# removed, every systemd symlink becomes dangling and services fail
# to start. The guard below aborts if REPO_DIR is outside primary.
# Set ALLOW_NONSTANDARD_REPO=1 to override (for intentional testing).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../units" && pwd)"
PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DEST_DIR="${HOME}/.config/systemd/user"

EXPECTED_PRIMARY="${HOME}/projects/hapax-council"
if [ "$PROJECT_DIR" != "$EXPECTED_PRIMARY" ] && [ "${ALLOW_NONSTANDARD_REPO:-0}" != "1" ]; then
    echo "ERROR: install-units.sh must run from the primary alpha worktree" >&2
    echo "  expected: $EXPECTED_PRIMARY" >&2
    echo "  actual:   $PROJECT_DIR" >&2
    echo "  Running from a non-primary worktree re-links every systemd user" >&2
    echo "  unit to that worktree's path, which breaks everything after the" >&2
    echo "  worktree is removed. Set ALLOW_NONSTANDARD_REPO=1 to override" >&2
    echo "  (e.g. for intentional testing in a dedicated long-lived worktree)." >&2
    exit 1
fi

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
fi

# Delta 2026-04-14-systemd-timer-enablement-gap.md identified that 14 of 51
# council timers had been linked (symlinked into ~/.config/systemd/user/)
# but never enabled (no symlink in timers.target.wants/). The previous
# version of this script only enabled *newly* linked timers, so any timer
# that was linked in one run but failed to enable (or the operator ran
# SKIP_TIMER_ENABLE=1, or the script was killed mid-run) stayed dead
# forever.
#
# Fix: always sweep every repo-owned timer symlink and run
# ``systemctl --user enable`` on each. ``enable`` is idempotent for
# already-enabled units, so the cost of a re-sweep on a clean state is
# effectively zero — one subprocess per timer. We do NOT pass --now in
# the sweep: that is the right behavior for first install (the newly-
# linked path above), but in the sweep a timer that is merely linked-
# but-not-enabled has been dormant possibly for weeks, and firing it
# synchronously from the install script is surprising. ``enable`` alone
# creates the .wants symlink; the next daemon-reload and the timer will
# then fire on its natural schedule.
if [ "${SKIP_TIMER_ENABLE:-0}" != "1" ]; then
    enabled_in_sweep=0
    for timer_file in "$REPO_DIR"/*.timer; do
        [ -f "$timer_file" ] || continue
        timer_name="$(basename "$timer_file")"
        # Skip if not linked yet — the symlink block above handles those.
        [ -L "$DEST_DIR/$timer_name" ] || continue
        # Check whether the timer already has a .wants symlink (already enabled).
        if [ -L "$DEST_DIR/timers.target.wants/$timer_name" ]; then
            continue
        fi
        if systemctl --user enable "$timer_name" 2>/dev/null; then
            echo "sweep-enabled: $timer_name (was linked but not enabled)"
            enabled_in_sweep=$((enabled_in_sweep + 1))
        else
            echo "WARN: sweep failed to enable $timer_name (run manually)" >&2
        fi
    done
    if [ "$enabled_in_sweep" -gt 0 ]; then
        systemctl --user daemon-reload
        echo "sweep enabled $enabled_in_sweep previously-dormant timer(s)"
    fi

    # First-install newly-linked timers get --now so they also start
    # immediately. Existing dormant timers handled by the sweep above
    # do NOT get --now; they fire on their next natural schedule.
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

if [ "$changed" -eq 0 ] && [ "${enabled_in_sweep:-0}" -eq 0 ]; then
    echo "all units up to date"
fi
