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
DECOMMISSIONED_UNITS=(
    hapax-logos.service
    hapax-build-reload.path
    hapax-build-reload.service
    logos-dev.service
    tabbyapi-hermes8b.service
    hapax-discord-webhook.service
    # Retired 2026-05-05: the old break-prep path swapped TabbyAPI model
    # residency for content prep. Prepared content is now resident
    # Command-R-only via hapax-segment-prep.{service,timer}.
    hapax-break-prep.service
    hapax-break-prep.timer
    # Retired 2026-05-14: unit files removed from repo but stale symlinks
    # remained in ~/.config/systemd/user/. Scripts and agent modules were
    # deleted; no runtime consumers remain.
    hapax-environmental-emphasis.service
    hapax-environmental-emphasis.timer
    hapax-visual-pool-snapshot-harvester.service
    hapax-visual-pool-snapshot-harvester.timer
    # Retired 2026-05-14: unit files removed from repo, stale symlinks found
    # by hapax-stale-unit-audit after canonical checkout restore.
    hapax-broadcast-boundary-public-event-producer.service
    hapax-hailo-frame-feeder.service
    hapax-triage-officer.service
    hapax-youtube-viewer-count.timer
    # Superseded 2026-05-02 by hapax-parametric-modulation-heartbeat.service.
    # Per memory `feedback_no_presets_use_parametric_modulation`: preset-pulse
    # heartbeats (PR #2239) are the wrong unit. Parametric modulation at the
    # node-graph level (cc-task ``parametric-modulation-heartbeat``) replaces
    # them. Listing here ensures the unit is disabled+masked on the next
    # install run, even on operator workstations where it was previously
    # enabled. See ``docs/superpowers/specs/2026-05-02-parametric-modulation-heartbeat.md``
    # §"Migration" and the 24h auditor batch 2026-05-02 finding #13.
)

# Services that must be auto-enabled (and started) on install.
#
# Per ``feedback_features_on_by_default`` + ``feedback_always_activate_features``
# (memory): shipping a unit file is not the same as shipping a feature. The
# 24h auditor batch 2026-05-02 finding #13 caught five recently-shipped
# services living dormant in the repo because the installer only auto-enabled
# *.timer units (via the sweep + new_timers paths above) — never *.service
# units. Adding a service here flips it ON by default at install time so the
# operator does not have to remember a manual ``systemctl --user enable --now``
# step per shipped unit.
#
# Membership criteria: the unit is a persistent always-on daemon (or a
# oneshot whose first run is desirable at install time) and shipped without
# operator-facing opt-in semantics. Timer-driven units do NOT belong here —
# the existing timer sweep covers them.
AUTO_ENABLE_SERVICES=(
    hapax-bt-firmware-watchdog.service               # PR #2223
    hapax-xhci-death-watchdog.service                # PR #2220
    hapax-private-broadcast-leak-guard.service       # PR #2221 (also has .timer; kicking the oneshot once at install fires the first protection cycle immediately)
    hapax-broadcast-egress-loopback-producer.service # PR #2235
    hapax-parametric-modulation-heartbeat.service    # PR #2252 (supersedes hapax-preset-bias-heartbeat above)
    hapax-hls-no-cache.service                       # live-surface proof egress; must not stay repo-only
    hapax-live-surface-guard.service                 # live-surface observability/remediation daemon
)
# Privacy / safety-critical timers that MUST be enabled. The script's
# sweep loop also enables every linked-but-not-enabled timer, so this
# list is documentation + a belt-and-braces final pass to guarantee
# these specific timers are running. Any privacy-critical timer added
# here is enabled --now (immediate start) regardless of its prior
# enable state.
AUTO_ENABLE_PRIVACY_TIMERS=(
    hapax-private-broadcast-leak-guard.timer
    hapax-private-monitor-recover.timer
    hapax-audio-topology-assertion.timer
)

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

is_decommissioned_unit() {
    local candidate="$1"
    local retired
    for retired in "${DECOMMISSIONED_UNITS[@]}"; do
        if [ "$candidate" = "$retired" ]; then
            return 0
        fi
    done
    return 1
}

remove_decommissioned_unit() {
    local name="$1"
    local removed=0
    local dest="$DEST_DIR/$name"
    if [ -e "$dest" ] || [ -L "$dest" ]; then
        rm -f "$dest"
        echo "removed decommissioned unit: $name"
        removed=1
    fi
    local wants_link
    for wants_link in "$DEST_DIR"/*.wants/"$name"; do
        [ -e "$wants_link" ] || [ -L "$wants_link" ] || continue
        rm -f "$wants_link"
        echo "removed decommissioned wants link: $wants_link"
        removed=1
    done
    local dropin_dir="$DEST_DIR/${name}.d"
    if [ -d "$dropin_dir" ]; then
        rm -rf "$dropin_dir"
        echo "removed decommissioned drop-in dir: ${name}.d"
        removed=1
    fi
    systemctl --user disable --now "$name" >/dev/null 2>&1 || true
    systemctl --user mask "$name" >/dev/null 2>&1 || true
    [ "$removed" -eq 1 ]
}

changed=0
new_timers=()
for retired_unit in "${DECOMMISSIONED_UNITS[@]}"; do
    if remove_decommissioned_unit "$retired_unit"; then
        changed=$((changed + 1))
    fi
done

for unit in "$REPO_DIR"/*.service "$REPO_DIR"/*.timer "$REPO_DIR"/*.target "$REPO_DIR"/*.path; do
    [ -f "$unit" ] || continue
    name="$(basename "$unit")"
    dest="$DEST_DIR/$name"
    if is_decommissioned_unit "$name"; then
        echo "skipped decommissioned unit: $name"
        continue
    fi
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

# Auto-enable persistent daemon services listed in AUTO_ENABLE_SERVICES.
#
# 24h auditor batch 2026-05-02 finding #13: shipped-but-dormant services
# violate the operator's standing directive that features ship live, not
# behind a manual enable step (memory: ``feedback_features_on_by_default``
# + ``feedback_always_activate_features``). The timer paths above only
# touch *.timer units; these *.service units need a parallel sweep.
#
# ``enable --now`` is idempotent: already-enabled and already-running
# units are no-ops, so re-running the installer is safe. Honors the
# same ``SKIP_TIMER_ENABLE`` escape hatch as the timer sweep — there's
# no separate ``SKIP_SERVICE_ENABLE`` because both paths exist for the
# same reason (operator may want a quiet install during incident response).
if [ "${SKIP_TIMER_ENABLE:-0}" != "1" ]; then
    services_enabled=0
    for service_name in "${AUTO_ENABLE_SERVICES[@]}"; do
        # Skip if the unit isn't on disk in the repo (defense-in-depth: the
        # symlink loop above won't have linked it, so enabling would fail
        # noisily). Surface as a WARN so the operator notices a stale entry
        # in AUTO_ENABLE_SERVICES vs. a renamed/removed unit.
        if [ ! -f "$REPO_DIR/$service_name" ]; then
            echo "WARN: AUTO_ENABLE_SERVICES entry $service_name not found in $REPO_DIR (skip)" >&2
            continue
        fi
        # Skip if decommissioned — covers the case where someone moved a
        # unit name into both lists by mistake.
        if is_decommissioned_unit "$service_name"; then
            echo "WARN: $service_name is in DECOMMISSIONED_UNITS; not auto-enabling" >&2
            continue
        fi
        if systemctl --user enable --now "$service_name" 2>/dev/null; then
            echo "auto-enabled: $service_name"
            services_enabled=$((services_enabled + 1))
        else
            echo "WARN: failed to auto-enable $service_name (run manually)" >&2
        fi
    done
    if [ "$services_enabled" -gt 0 ]; then
        echo "auto-enabled $services_enabled persistent service(s)"
    fi
elif [ "${#AUTO_ENABLE_SERVICES[@]}" -gt 0 ]; then
    echo "skipped auto-enabling ${#AUTO_ENABLE_SERVICES[@]} service(s) (SKIP_TIMER_ENABLE=1)"
fi

# LRR Phase 3 item 1: walk ``systemd/units/*.service.d/`` directories
# and install each drop-in as a real symlink under
# ``~/.config/systemd/user/<service>.service.d/<name>.conf``. Previously
# the script only handled top-level unit files, so drop-ins shipped in
# the repo (audio-recorder.service.d/, contact-mic-recorder.service.d/)
# were silently not installed. Phase 3 adds tabbyapi.service.d/ and
# hapax-dmn.service.d/ — both MUST be active for the Option α → γ
# partition reconciliation to take effect. Handling this class of
# file now fixes both the new drop-ins and the latent existing ones.
#
# Destination layout: ``~/.config/systemd/user/<service>.service.d/``
# is a REAL directory (not a symlink). Individual ``.conf`` files
# inside it are symlinks back to the repo. This matches the existing
# manually-placed ``tabbyapi.service.d/gpu-pin.conf`` file that has
# been on disk since Sprint 5b Phase 2a.
dropin_changed=0
for dropin_dir in "$REPO_DIR"/*.service.d; do
    [ -d "$dropin_dir" ] || continue
    svc_name="$(basename "$dropin_dir")"
    dest_dropin_dir="$DEST_DIR/$svc_name"
    mkdir -p "$dest_dropin_dir"
    for conf in "$dropin_dir"/*.conf; do
        [ -f "$conf" ] || continue
        conf_name="$(basename "$conf")"
        dest_conf="$dest_dropin_dir/$conf_name"
        if [ -L "$dest_conf" ] && [ "$(readlink "$dest_conf")" = "$conf" ]; then
            continue
        fi
        ln -sf "$conf" "$dest_conf"
        echo "dropin-linked: $svc_name/$conf_name"
        dropin_changed=$((dropin_changed + 1))
    done
done

if [ "$dropin_changed" -gt 0 ]; then
    systemctl --user daemon-reload
    echo "daemon-reload done ($dropin_changed drop-in conf(s) linked)"
fi

if [ "$changed" -eq 0 ] && [ "${enabled_in_sweep:-0}" -eq 0 ] && [ "${services_enabled:-0}" -eq 0 ] && [ "$dropin_changed" -eq 0 ]; then
    echo "all units up to date"
fi

# Privacy / safety-critical timer guarantee (final pass).
# The L-12 broadcast bus carries everything that touches it. Any private
# monitor stream reaching it is a constitutional axiom violation
# (`feedback_l12_equals_livestream_invariant`). The 3-layer leak guard
# (WP rules 55+56 + runtime backstop) and the recover/topology-assertion
# timers are the runtime defense. They MUST be enabled and active. This
# block ensures they are even if the sweep skipped them (e.g., they were
# already linked-and-enabled but no .wants/ symlink due to a prior
# rollback). Idempotent — `enable --now` on a running active unit is a
# no-op.
if [ "${SKIP_TIMER_ENABLE:-0}" != "1" ]; then
    privacy_failures=0
    for timer_name in "${AUTO_ENABLE_PRIVACY_TIMERS[@]}"; do
        if [ ! -L "$DEST_DIR/$timer_name" ] && [ ! -f "$DEST_DIR/$timer_name" ]; then
            echo "WARN: privacy-critical timer $timer_name is not installed" >&2
            privacy_failures=$((privacy_failures + 1))
            continue
        fi
        if systemctl --user enable --now "$timer_name" 2>/dev/null; then
            echo "privacy-critical: $timer_name enabled+started"
        else
            echo "ERROR: failed to enable privacy-critical $timer_name" >&2
            privacy_failures=$((privacy_failures + 1))
        fi
    done
    if [ "$privacy_failures" -gt 0 ]; then
        echo "WARN: $privacy_failures privacy-critical timer(s) could not be enabled" >&2
    fi
fi
