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
    # Retired 2026-06-07: superseded by the direct video50/video52 + UDP
    # ffmpeg media-source topology (#3819/#3827/#3837). The OBS V4L2 capture
    # source it monitored no longer exists in the live runtime; the compositor
    # ingests /dev/video52 directly. No runtime puller; was Restart=no +
    # WatchdogSec=120 (no self-recovery). Script kept as a manual one-shot tool.
    hapax-obs-v4l2-source-reset.service
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
    hapax-relay-heartbeat.service
    hapax-relay-heartbeat.timer
    hapax-youtube-viewer-count.timer
    # Retired 2026-08-12: the historical local judge used a mutable image,
    # mutable model bind, name-based removal, and no memory limit. Source omits
    # the unit and the installed path stays masked until a trusted broker exists.
    hapax-local-judge.service
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
    hapax-camera-loopback-setup.service              # oneshot Before=compositor; per-camera v4l2loopback devices
    hapax-chronicle-high-salience-public-event-producer.service
    hapax-coordinator.service
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

# Path-triggered units that must be enabled on install. Repo symlinking alone
# leaves path watchers inert, so deploy-critical path units need the same
# explicit default-on treatment as persistent daemon services.
AUTO_ENABLE_PATHS=(
    hapax-darkplaces-live-texture-rebuild.path
    hapax-screwm-gpu-drift-rebuild.path
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

query_local_judge_container_id() {
    local docker_bin="$1"
    local output
    if ! output="$(
        /usr/bin/env -i \
            HOME="$HOME" LANG=C LC_ALL=C PATH=/usr/bin:/bin \
            /usr/bin/timeout --signal=KILL 5s \
                "$docker_bin" \
                --host=unix:///var/run/docker.sock \
                --config=/nonexistent/hapax-local-judge-retirement \
                ps -aq --no-trunc --filter 'name=^/hapax-local-judge$' \
            | /usr/bin/head -c 1025
    )"; then
        echo "ERROR: cannot enumerate the historical local-judge container from the pinned local Docker daemon" >&2
        return 1
    fi
    if [ "${#output}" -gt 1024 ]; then
        echo "ERROR: local-judge retirement Docker inventory exceeded 1024 bytes" >&2
        return 1
    fi

    LOCAL_JUDGE_CONTAINER_ID=""
    local line
    local count=0
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        count=$((count + 1))
        if ! [[ "$line" =~ ^[0-9a-f]{64}$ ]]; then
            echo "ERROR: local-judge retirement received a malformed Docker container ID" >&2
            return 1
        fi
        LOCAL_JUDGE_CONTAINER_ID="$line"
    done <<< "$output"
    if [ "$count" -gt 1 ]; then
        echo "ERROR: local-judge retirement found multiple exact-name containers" >&2
        return 1
    fi
}

validate_historical_local_judge_container() {
    local docker_bin="$1" container_id="$2" output
    if ! output="$(
        /usr/bin/env -i \
            HOME="$HOME" LANG=C LC_ALL=C PATH=/usr/bin:/bin \
            /usr/bin/timeout --signal=KILL 5s \
                "$docker_bin" \
                --host=unix:///var/run/docker.sock \
                --config=/nonexistent/hapax-local-judge-retirement \
                inspect --format \
                '{{json .Id}}{{printf "\t"}}{{json .Name}}{{printf "\t"}}{{json .Config.Image}}{{printf "\t"}}{{json .Path}}{{printf "\t"}}{{json .Args}}{{printf "\t"}}{{json .HostConfig.Binds}}{{printf "\t"}}{{json .HostConfig.PortBindings}}{{printf "\t"}}{{json .HostConfig.AutoRemove}}' \
                "$container_id" \
            | /usr/bin/head -c 4097
    )"; then
        echo "ERROR: cannot inspect the captured historical local-judge container" >&2
        return 1
    fi
    if [ -z "$output" ] || [ "${#output}" -gt 4096 ] || [[ "$output" == *$'\n'* ]]; then
        echo "ERROR: historical local-judge Docker signature was empty, multiline, or oversized" >&2
        return 1
    fi
    if ! /usr/bin/python3 - "$container_id" "$HOME" "$output" <<'PY'
from __future__ import annotations

import json
import sys

container_id, home, record = sys.argv[1:]
fields = record.split("\t")
if len(fields) != 8:
    raise SystemExit(1)
try:
    actual_id, name, image, path, args, binds, ports, auto_remove = (
        json.loads(field) for field in fields
    )
except (TypeError, ValueError, json.JSONDecodeError):
    raise SystemExit(1)

expected_args = [
    "-m",
    "/models/CompassVerifier-7B.Q5_K_M.gguf",
    "-a",
    "compassverifier-7b",
    "-c",
    "65536",
    "-np",
    "8",
    "-cb",
    "-ngl",
    "99",
    "--host",
    "0.0.0.0",
    "--port",
    "5001",
]
expected_ports = {"5001/tcp": [{"HostIp": "", "HostPort": "5001"}]}
valid = (
    actual_id == container_id
    and name == "/hapax-local-judge"
    and image == "ghcr.io/ggml-org/llama.cpp:server-cuda"
    and path == "/app/llama-server"
    and args == expected_args
    and binds == [f"{home}/models/compassverifier-7b:/models:ro"]
    and ports == expected_ports
    and auto_remove is True
)
raise SystemExit(0 if valid else 1)
PY
    then
        echo "ERROR: exact-name container does not match the durable historical local-judge signature; refusing destructive cleanup" >&2
        return 1
    fi
}

query_local_judge_manager_property() {
    local systemctl_bin="$1" property="$2" output
    if ! output="$(
        /usr/bin/timeout --signal=KILL 5s \
            "$systemctl_bin" --user show hapax-local-judge.service \
            -p "$property" --value \
            | /usr/bin/head -c 129
    )"; then
        echo "ERROR: cannot query historical local-judge $property from the user manager" >&2
        return 1
    fi
    if [ -z "$output" ] || [ "${#output}" -gt 128 ] || [[ "$output" == *$'\n'* ]]; then
        echo "ERROR: historical local-judge $property was empty or malformed" >&2
        return 1
    fi
    printf '%s\n' "$output"
}

install_local_judge_mask() {
    local dest="$1"
    /usr/bin/python3 - "$dest" <<'PY'
from __future__ import annotations

import os
import secrets
import sys

dest = os.path.abspath(sys.argv[1])
parent, name = os.path.split(dest)
dir_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
tmp = f".{name}.mask.{os.getpid()}.{secrets.token_hex(8)}"
try:
    os.symlink("/dev/null", tmp, dir_fd=dir_fd)
    os.replace(tmp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    os.fsync(dir_fd)
finally:
    try:
        os.unlink(tmp, dir_fd=dir_fd)
    except FileNotFoundError:
        pass
    os.close(dir_fd)
PY
}

retire_historical_local_judge() {
    local name="hapax-local-judge.service"
    local dest="$DEST_DIR/$name"
    local already_masked=0
    local artifacts_clean=1
    if [ -e "$dest" ] || [ -L "$dest" ]; then
        if [ -L "$dest" ] && [ "$(readlink "$dest")" = "/dev/null" ]; then
            # A mask can be the residue of a failed first retirement after the
            # unit was disabled but before immutable-ID Docker cleanup. Keep
            # reconciling until both the unit and container absence converge.
            already_masked=1
        else
            artifacts_clean=0
        fi
    else
        artifacts_clean=0
    fi
    local wants_link
    for wants_link in "$DEST_DIR"/*.wants/"$name"; do
        [ -e "$wants_link" ] || [ -L "$wants_link" ] || continue
        artifacts_clean=0
    done
    local dropin_dir="$DEST_DIR/${name}.d"
    if [ -e "$dropin_dir" ] || [ -L "$dropin_dir" ]; then
        artifacts_clean=0
    fi
    local systemctl_bin="${HAPAX_INSTALL_UNITS_RETIRE_SYSTEMCTL:-/usr/bin/systemctl}"
    local docker_bin="${HAPAX_INSTALL_UNITS_RETIRE_DOCKER:-/usr/bin/docker}"
    if { [ -n "${HAPAX_INSTALL_UNITS_RETIRE_SYSTEMCTL:-}" ] \
        || [ -n "${HAPAX_INSTALL_UNITS_RETIRE_DOCKER:-}" ]; } \
        && [ "${ALLOW_NONSTANDARD_REPO:-0}" != "1" ]; then
        echo "ERROR: local-judge retirement command overrides are test-only" >&2
        return 2
    fi
    if [ ! -x "$systemctl_bin" ] || [ ! -x "$docker_bin" ]; then
        echo "ERROR: local-judge retirement requires executable systemctl and Docker clients" >&2
        return 2
    fi

    if ! query_local_judge_container_id "$docker_bin"; then
        return 2
    fi
    local before_id="$LOCAL_JUDGE_CONTAINER_ID"
    if [ -n "$before_id" ] \
        && ! validate_historical_local_judge_container "$docker_bin" "$before_id"; then
        return 2
    fi
    local manager_load_state manager_unit_file_state manager_active_state
    if ! manager_load_state="$(
        query_local_judge_manager_property "$systemctl_bin" LoadState
    )" || ! manager_unit_file_state="$(
        query_local_judge_manager_property "$systemctl_bin" UnitFileState
    )" || ! manager_active_state="$(
        query_local_judge_manager_property "$systemctl_bin" ActiveState
    )"; then
        return 2
    fi
    if [ "$already_masked" -eq 1 ] && [ "$artifacts_clean" -eq 1 ] \
        && [ -z "$before_id" ] \
        && [ "$manager_load_state" = "masked" ] \
        && [ "$manager_unit_file_state" = "masked" ] \
        && [ "$manager_active_state" = "inactive" ]; then
        return 1
    fi

    if [ "$manager_load_state" != "not-found" ]; then
        if ! "$systemctl_bin" --user disable "$name" >/dev/null; then
            echo "ERROR: could not disable the historical local-judge unit" >&2
            return 2
        fi
    fi
    if [ "$already_masked" -eq 0 ]; then
        if ! rm -f "$dest"; then
            echo "ERROR: could not remove the historical local-judge unit" >&2
            return 2
        fi
    fi
    for wants_link in "$DEST_DIR"/*.wants/"$name"; do
        [ -e "$wants_link" ] || [ -L "$wants_link" ] || continue
        if ! rm -f "$wants_link"; then
            echo "ERROR: could not remove a historical local-judge wants link" >&2
            return 2
        fi
    done
    if [ -e "$dropin_dir" ] || [ -L "$dropin_dir" ]; then
        if ! rm -rf "$dropin_dir"; then
            echo "ERROR: could not remove historical local-judge drop-ins" >&2
            return 2
        fi
    fi
    if [ "$already_masked" -eq 0 ]; then
        if ! install_local_judge_mask "$dest"; then
            echo "ERROR: could not mask the historical local-judge unit" >&2
            return 2
        fi
    fi
    if ! "$systemctl_bin" --user daemon-reload >/dev/null; then
        echo "ERROR: could not reload the user manager after local-judge masking" >&2
        return 2
    fi

    local container_remove_failed=0
    if [ -n "$before_id" ]; then
        if ! /usr/bin/env -i \
                HOME="$HOME" LANG=C LC_ALL=C PATH=/usr/bin:/bin \
                /usr/bin/timeout --signal=KILL 5s \
                    "$docker_bin" \
                    --host=unix:///var/run/docker.sock \
                    --config=/nonexistent/hapax-local-judge-retirement \
                    rm -f "$before_id" >/dev/null; then
            echo "ERROR: could not remove the captured historical local-judge container ID" >&2
            container_remove_failed=1
        fi
    fi
    "$systemctl_bin" --user kill --kill-who=main --signal=SIGTERM "$name" >/dev/null 2>&1 || true
    for _retirement_wait in {1..20}; do
        if ! "$systemctl_bin" --user is-active --quiet "$name"; then
            break
        fi
        /usr/bin/sleep 0.1
    done
    if "$systemctl_bin" --user is-active --quiet "$name"; then
        echo "ERROR: historical local-judge unit remained active after immutable-ID retirement" >&2
        return 2
    fi
    if [ "$container_remove_failed" -ne 0 ]; then
        return 2
    fi

    if ! query_local_judge_container_id "$docker_bin"; then
        return 2
    fi
    if [ -n "$LOCAL_JUDGE_CONTAINER_ID" ]; then
        echo "ERROR: local-judge container appeared or remained after immutable-ID reconciliation; refusing name-based cleanup" >&2
        return 2
    fi
    local final_load_state final_unit_file_state final_active_state
    if ! final_load_state="$(
        query_local_judge_manager_property "$systemctl_bin" LoadState
    )" || ! final_unit_file_state="$(
        query_local_judge_manager_property "$systemctl_bin" UnitFileState
    )" || ! final_active_state="$(
        query_local_judge_manager_property "$systemctl_bin" ActiveState
    )"; then
        return 2
    fi
    if [ "$final_load_state" != "masked" ] \
        || [ "$final_unit_file_state" != "masked" ] \
        || [ "$final_active_state" != "inactive" ]; then
        echo "ERROR: user manager does not witness local-judge masked/masked/inactive after retirement (LoadState=$final_load_state UnitFileState=$final_unit_file_state ActiveState=$final_active_state)" >&2
        return 2
    fi
    "$systemctl_bin" --user reset-failed "$name" >/dev/null 2>&1 || true
    echo "retired and masked historical local judge (container_id=${before_id:-absent})"
    return 0
}

remove_decommissioned_unit() {
    local name="$1"
    if [ "$name" = "hapax-local-judge.service" ]; then
        retire_historical_local_judge
        return
    fi
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

system_install_scope_unit() {
    grep -Eq '^[#;][[:space:]]*Hapax-Install-Scope:[[:space:]]*system[[:space:]]*$' "$1" || return 1
    return 0
}

timer_enable_only() {
    local timer_file="$1"
    grep -Eiq '^[#;][[:space:]]*Hapax-Timer-Enable-Only:[[:space:]]*(true|yes|1)[[:space:]]*$' "$timer_file" || return 1
    grep -Eq '^\[Install\]' "$timer_file" || return 1
    return 0
}

parked_unit() {
    grep -Eiq '^[#;][[:space:]]*Hapax-Parked:[[:space:]]*(true|yes|1)[[:space:]]*$' "$1"
}

dedicated_p0_oom_unit() {
    case "$1" in
        hapax-oom-policy-audit.service|\
        hapax-oom-policy-audit.timer|\
        hapax-root-required-deploy-audit.service|\
        hapax-root-required-deploy-audit.timer)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

changed=0
new_timers=()
for retired_unit in "${DECOMMISSIONED_UNITS[@]}"; do
    retirement_rc=0
    remove_decommissioned_unit "$retired_unit" || retirement_rc=$?
    case "$retirement_rc" in
        0) changed=$((changed + 1)) ;;
        1) ;;
        *)
            echo "ERROR: failed to retire $retired_unit" >&2
            exit "$retirement_rc"
            ;;
    esac
done

# Retire stale units before dependency synchronization. Decommissioning must
# remain reachable even when the project environment is currently unhealthy.
# Services installed below run via `uv run`, so synchronize before linking them.
echo "Syncing venv with all extras..."
(cd "$PROJECT_DIR" && uv sync --all-extras --quiet)
echo "venv synced"

for unit in "$REPO_DIR"/*.service "$REPO_DIR"/*.timer "$REPO_DIR"/*.target "$REPO_DIR"/*.path "$REPO_DIR"/*.slice; do
    [ -f "$unit" ] || continue
    name="$(basename "$unit")"
    dest="$DEST_DIR/$name"
    if is_decommissioned_unit "$name"; then
        echo "skipped decommissioned unit: $name"
        continue
    fi
    if dedicated_p0_oom_unit "$name"; then
        echo "skipped dedicated P0 OOM unit: $name"
        continue
    fi
    if system_install_scope_unit "$unit"; then
        systemctl --user disable --now "$name" >/dev/null 2>&1 || true
        if [ -e "$dest" ] || [ -L "$dest" ]; then
            rm -f "$dest"
            changed=$((changed + 1))
            echo "removed stale user-scope system unit: $name"
        fi
        for wants_link in "$DEST_DIR"/*.wants/"$name"; do
            [ -e "$wants_link" ] || [ -L "$wants_link" ] || continue
            rm -f "$wants_link"
            changed=$((changed + 1))
            echo "removed stale user-scope wants link: $wants_link"
        done
        echo "skipped system-scope unit: $name"
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

for parked_file in "$REPO_DIR"/*.service "$REPO_DIR"/*.timer "$REPO_DIR"/*.path; do
    [ -f "$parked_file" ] || continue
    parked_unit "$parked_file" || continue
    parked_name="$(basename "$parked_file")"
    systemctl --user disable --now "$parked_name"
    systemctl --user reset-failed "$parked_name" >/dev/null 2>&1 || true
    echo "parked: $parked_name"
done

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
        if timer_enable_only "$REPO_DIR/$timer"; then
            if systemctl --user enable "$timer" 2>/dev/null; then
                echo "enabled: $timer (Hapax-Timer-Enable-Only; not started)"
            else
                echo "WARN: failed to enable $timer (run manually)" >&2
            fi
        elif systemctl --user enable --now "$timer" 2>/dev/null; then
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

# Auto-enable path units that are part of deployment durability. This mirrors
# AUTO_ENABLE_SERVICES, but keeps the unit class explicit so oneshot services do
# not accidentally become default-on just because their path watcher should be.
if [ "${SKIP_TIMER_ENABLE:-0}" != "1" ]; then
    paths_enabled=0
    for path_name in "${AUTO_ENABLE_PATHS[@]}"; do
        if [ ! -f "$REPO_DIR/$path_name" ]; then
            echo "WARN: AUTO_ENABLE_PATHS entry $path_name not found in $REPO_DIR (skip)" >&2
            continue
        fi
        if is_decommissioned_unit "$path_name"; then
            echo "WARN: $path_name is in DECOMMISSIONED_UNITS; not auto-enabling" >&2
            continue
        fi
        if systemctl --user enable --now "$path_name" 2>/dev/null; then
            echo "auto-enabled path: $path_name"
            paths_enabled=$((paths_enabled + 1))
        else
            echo "WARN: failed to auto-enable path $path_name (run manually)" >&2
        fi
    done
    if [ "$paths_enabled" -gt 0 ]; then
        echo "auto-enabled $paths_enabled path unit(s)"
    fi
elif [ "${#AUTO_ENABLE_PATHS[@]}" -gt 0 ]; then
    echo "skipped auto-enabling ${#AUTO_ENABLE_PATHS[@]} path unit(s) (SKIP_TIMER_ENABLE=1)"
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
# 2026-07-09 P0 follow-up: the same install contract now covers slice/scope
# drop-ins as well. app.slice/session.slice containment is a host-safety
# backstop, and it must not be skipped merely because it is not a service unit.
#
# Destination layout: ``~/.config/systemd/user/<service>.service.d/``
# is a REAL directory (not a symlink). Individual ``.conf`` files
# inside it are symlinks back to the repo. P0 OOM containment backstops are
# skipped here because only scripts/install-p0-oom-containment may install
# them from a governed, commit-staged source package.
dedicated_p0_oom_dropin() {
    case "$1" in
        app.slice.d/oom-containment.conf|\
        session.slice.d/oom-containment.conf|\
        pipewire.service.d/oom-protect.conf|\
        pipewire-pulse.service.d/oom-protect.conf|\
        wireplumber.service.d/oom-protect.conf|\
        hapax-daimonion.service.d/oom-protect.conf|\
        studio-compositor.service.d/oom-protect.conf|\
        hapax-imagination.service.d/oom-protect.conf)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

dropin_changed=0
for dropin_dir in "$REPO_DIR"/*.service.d "$REPO_DIR"/*.timer.d "$REPO_DIR"/*.slice.d "$REPO_DIR"/*.scope.d; do
    [ -d "$dropin_dir" ] || continue
    svc_name="$(basename "$dropin_dir")"
    for conf in "$dropin_dir"/*.conf; do
        [ -f "$conf" ] || continue
        conf_name="$(basename "$conf")"
        if dedicated_p0_oom_dropin "$svc_name/$conf_name"; then
            echo "dropin-skipped-dedicated-installer: $svc_name/$conf_name"
            continue
        fi
        dest_dropin_dir="$DEST_DIR/$svc_name"
        mkdir -p "$dest_dropin_dir"
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

if [ "$changed" -eq 0 ] && [ "${enabled_in_sweep:-0}" -eq 0 ] && [ "${services_enabled:-0}" -eq 0 ] && [ "${paths_enabled:-0}" -eq 0 ] && [ "$dropin_changed" -eq 0 ]; then
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
