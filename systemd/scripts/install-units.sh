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

ORIGINAL_ARGS=("$@")
REPO_DIR="$(cd "$(dirname "$0")/../units" && pwd)"
PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
NSS_HOME=""
DEST_DIR=""
ROOT_REQUIRED_LOCK_FILE=""

configure_root_required_lock_domain() {
    if ! NSS_HOME="$(/usr/bin/python3 -I -S - <<'PY'
import os
import pwd
import sys

try:
    home = pwd.getpwuid(os.geteuid()).pw_dir
except KeyError:
    print("ERROR: current UID has no canonical NSS home", file=sys.stderr)
    raise SystemExit(1)
if not home or "\n" in home or len(home) > 4096 or not os.path.isabs(home):
    print("ERROR: current UID has an invalid canonical NSS home", file=sys.stderr)
    raise SystemExit(1)
print(home)
PY
    )"; then
        return 1
    fi

    if [ "${HAPAX_ROOT_REQUIRED_ISOLATED_TEST_ROOT+x}" != "x" ]; then
        for selector in HAPAX_ROOT_REQUIRED_STATE_ROOT HAPAX_ROOT_REQUIRED_LOCK_FILE; do
            if [[ -v "$selector" ]]; then
                echo "ERROR: production refuses $selector" >&2
                return 1
            fi
        done
        if [ "$HOME" != "$NSS_HOME" ]; then
            echo "ERROR: production HOME must exactly match canonical NSS home $NSS_HOME" >&2
            return 1
        fi
        DEST_DIR="$NSS_HOME/.config/systemd/user"
        ROOT_REQUIRED_LOCK_FILE="$NSS_HOME/.local/state/hapax/root-required/.lock"
        return
    fi

    DEST_DIR="$HOME/.config/systemd/user"
    ROOT_REQUIRED_LOCK_FILE="${HAPAX_ROOT_REQUIRED_LOCK_FILE:-$HOME/.local/state/hapax/root-required/.lock}"
    /usr/bin/python3 -I -S - \
        "$HAPAX_ROOT_REQUIRED_ISOLATED_TEST_ROOT" \
        "$HOME" "$DEST_DIR" "$ROOT_REQUIRED_LOCK_FILE" <<'PY'
from __future__ import annotations

import os
import stat
import sys

root, home, destination, lock = sys.argv[1:]
if (
    not root
    or "\n" in root
    or len(root) > 4096
    or not os.path.isabs(root)
):
    print(
        "ERROR: HAPAX_ROOT_REQUIRED_ISOLATED_TEST_ROOT must name an absolute directory",
        file=sys.stderr,
    )
    raise SystemExit(1)
try:
    root_inode = os.lstat(root)
except OSError as exc:
    print(
        f"ERROR: refused invalid isolated test root {root}: {exc}",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc
if (
    not stat.S_ISDIR(root_inode.st_mode)
    or root_inode.st_uid != os.geteuid()
    or root_inode.st_mode & 0o022
    or os.path.realpath(root) != root
):
    print(
        "ERROR: isolated test root must be a caller-owned, non-symlink directory "
        "with no group/world write bits",
        file=sys.stderr,
    )
    raise SystemExit(1)

resolved_root = os.path.realpath(root)
for label, path in (("home", home), ("destination", destination), ("lock", lock)):
    if not path or "\n" in path or len(path) > 4096 or not os.path.isabs(path):
        print(f"ERROR: isolated test {label} path is invalid", file=sys.stderr)
        raise SystemExit(1)
    lexical_path = os.path.abspath(path)
    resolved_path = os.path.realpath(path)
    try:
        confined = (
            lexical_path != root
            and resolved_path != resolved_root
            and os.path.commonpath((root, lexical_path)) == root
            and os.path.commonpath((resolved_root, resolved_path)) == resolved_root
        )
    except ValueError:
        confined = False
    if not confined:
        print(f"ERROR: isolated test {label} escapes {resolved_root}", file=sys.stderr)
        raise SystemExit(1)
PY
}

acquire_inherited_root_required_lock() {
    local lock_fd="${HAPAX_ROOT_REQUIRED_LOCK_FD:-}"
    if ! [[ "$lock_fd" =~ ^[0-9]+$ ]] || [ "$lock_fd" -lt 3 ]; then
        echo "ERROR: safe shared install lock descriptor is absent" >&2
        return 1
    fi
    /usr/bin/python3 -I -S - "$lock_fd" "$ROOT_REQUIRED_LOCK_FILE" <<'PY'
from __future__ import annotations

import fcntl
import os
import stat
import sys

fd = int(sys.argv[1])
lock_path = sys.argv[2]


def valid(inode: os.stat_result) -> bool:
    return (
        stat.S_ISREG(inode.st_mode)
        and inode.st_uid == os.geteuid()
        and inode.st_nlink == 1
        and not inode.st_mode & 0o022
    )


try:
    inode_before = os.fstat(fd)
    path_before = os.lstat(lock_path)
except OSError as exc:
    print(
        f"ERROR: refused invalid inherited shared install lock {lock_path}: {exc}",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc
if (
    not valid(inode_before)
    or not valid(path_before)
    or (inode_before.st_dev, inode_before.st_ino)
    != (path_before.st_dev, path_before.st_ino)
):
    print(
        f"ERROR: refused invalid inherited shared install lock {lock_path}; "
        "expected one caller-owned, single-link, non-group/world-writable regular path inode",
        file=sys.stderr,
    )
    raise SystemExit(1)

fcntl.flock(fd, fcntl.LOCK_EX)
os.fchmod(fd, 0o600)
try:
    inode_after = os.fstat(fd)
    path_after = os.lstat(lock_path)
except OSError as exc:
    print(
        f"ERROR: shared install lock path changed while acquiring {lock_path}: {exc}",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc
if (
    not valid(inode_after)
    or not valid(path_after)
    or (inode_after.st_dev, inode_after.st_ino)
    != (path_after.st_dev, path_after.st_ino)
    or (inode_before.st_dev, inode_before.st_ino)
    != (inode_after.st_dev, inode_after.st_ino)
):
    print(
        f"ERROR: shared install lock identity changed while acquiring {lock_path}",
        file=sys.stderr,
    )
    raise SystemExit(1)
PY
}

reexec_with_safe_root_required_lock() {
    if [ -n "${HAPAX_ROOT_REQUIRED_LOCK_FD:-}" ]; then
        acquire_inherited_root_required_lock
        return
    fi
    exec /usr/bin/python3 -I -S - \
        "$ROOT_REQUIRED_LOCK_FILE" "$0" "${ORIGINAL_ARGS[@]}" <<'PY'
from __future__ import annotations

import fcntl
import os
import stat
import subprocess
import sys

requested_path, script, *args = sys.argv[1:]
if not requested_path or "\n" in requested_path or len(requested_path) > 4096:
    print("ERROR: refused malformed shared install lock path", file=sys.stderr)
    raise SystemExit(1)
lock_path = os.path.abspath(requested_path)
parent = os.path.dirname(lock_path)
try:
    os.makedirs(parent, mode=0o700, exist_ok=True)
    fd = os.open(
        lock_path,
        os.O_CLOEXEC | os.O_CREAT | os.O_NOFOLLOW | os.O_RDWR,
        0o600,
    )
except OSError as exc:
    print(
        f"ERROR: refused unsafe shared install lock {lock_path}: {exc}",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc


def valid(inode: os.stat_result) -> bool:
    return (
        stat.S_ISREG(inode.st_mode)
        and inode.st_uid == os.geteuid()
        and inode.st_nlink == 1
        and not inode.st_mode & 0o022
    )


try:
    inode_before = os.fstat(fd)
    path_before = os.lstat(lock_path)
    if (
        not valid(inode_before)
        or not valid(path_before)
        or (inode_before.st_dev, inode_before.st_ino)
        != (path_before.st_dev, path_before.st_ino)
    ):
        print(
            f"ERROR: refused unsafe shared install lock inode {lock_path}; "
            "expected one caller-owned, single-link, non-group/world-writable regular file",
            file=sys.stderr,
        )
        raise SystemExit(1)
    fcntl.flock(fd, fcntl.LOCK_EX)
    os.fchmod(fd, 0o600)
    inode_after = os.fstat(fd)
    path_after = os.lstat(lock_path)
    if (
        not valid(inode_after)
        or not valid(path_after)
        or (inode_after.st_dev, inode_after.st_ino)
        != (path_after.st_dev, path_after.st_ino)
        or (inode_before.st_dev, inode_before.st_ino)
        != (inode_after.st_dev, inode_after.st_ino)
    ):
        print(
            f"ERROR: shared install lock identity changed while acquiring {lock_path}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    env = os.environ.copy()
    env.pop("HAPAX_ROOT_REQUIRED_LOCK_HELD", None)
    env.pop("HAPAX_ROOT_REQUIRED_LOCK_MODE", None)
    env["HAPAX_ROOT_REQUIRED_LOCK_FD"] = str(fd)
    env["HAPAX_ROOT_REQUIRED_LOCK_MODE"] = "exclusive"
    result = subprocess.run(
        [os.path.abspath(script), *args],
        env=env,
        pass_fds=(fd,),
        check=False,
    )
    raise SystemExit(result.returncode)
finally:
    os.close(fd)
PY
}

configure_root_required_lock_domain

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

reexec_with_safe_root_required_lock

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

LOCAL_JUDGE_CONFIG_ID="sha256:71de6ba513bcdb374a8ac597d78277ac78df1f484cdf929e1be01c60a42964af"
LOCAL_JUDGE_IMAGE_DIGEST="sha256:841b199aed2649a748875b043b32fed2e8c2d4d87e1d563556817fb7fa44b72b"
LOCAL_JUDGE_DOCKER_HOST="unix:///var/run/docker.sock"
LOCAL_JUDGE_DOCKER_CONFIG="/nonexistent/hapax-local-judge-retirement"
LOCAL_JUDGE_CONTAINER_ID=""
LOCAL_JUDGE_EXACT_ID_MATCH=""
LOCAL_JUDGE_IMAGE_RECORD=""
LOCAL_JUDGE_PROFILE=""
LOCAL_JUDGE_MANAGER_WITNESS=""
LOCAL_JUDGE_TEST_MODE=0

local_judge_docker() {
    /usr/bin/env -i \
        HOME="$HOME" LANG=C LC_ALL=C PATH=/usr/bin:/bin \
        /usr/bin/timeout --signal=KILL 5s \
            "$LOCAL_JUDGE_DOCKER_BIN" \
            --host="$LOCAL_JUDGE_DOCKER_HOST" \
            --config="$LOCAL_JUDGE_DOCKER_CONFIG" \
            "$@"
}

local_judge_systemctl() {
    /usr/bin/timeout --signal=KILL 5s \
        "$LOCAL_JUDGE_SYSTEMCTL_BIN" --user "$@"
}

configure_local_judge_retirement_commands() {
    local systemctl_override="${HAPAX_INSTALL_UNITS_RETIRE_SYSTEMCTL:-}"
    local docker_override="${HAPAX_INSTALL_UNITS_RETIRE_DOCKER:-}"
    LOCAL_JUDGE_TEST_MODE=0
    if [ -n "$systemctl_override" ] || [ -n "$docker_override" ]; then
        if [ "${ALLOW_NONSTANDARD_REPO:-0}" != "1" ] \
            || [ -z "$systemctl_override" ] || [ -z "$docker_override" ]; then
            echo "ERROR: local-judge retirement command overrides are paired test-only controls" >&2
            return 1
        fi
        LOCAL_JUDGE_SYSTEMCTL_BIN="$systemctl_override"
        LOCAL_JUDGE_DOCKER_BIN="$docker_override"
        LOCAL_JUDGE_TEST_MODE=1
    else
        LOCAL_JUDGE_SYSTEMCTL_BIN="/usr/bin/systemctl"
        LOCAL_JUDGE_DOCKER_BIN="/usr/bin/docker"
    fi
    if [ ! -x "$LOCAL_JUDGE_SYSTEMCTL_BIN" ]; then
        echo "ERROR: local-judge retirement requires an executable pinned systemctl client" >&2
        return 1
    fi
}

query_local_judge_container_id() {
    local output line count=0
    if ! output="$(
        local_judge_docker \
            ps -aq --no-trunc --filter 'name=^/hapax-local-judge$' \
            | /usr/bin/head -c 1025
    )"; then
        echo "ERROR: cannot enumerate the historical local-judge container from the pinned local Docker daemon" >&2
        return 1
    fi
    if [ "${#output}" -gt 1024 ]; then
        echo "ERROR: local-judge retirement Docker inventory exceeded its bound" >&2
        return 1
    fi

    LOCAL_JUDGE_CONTAINER_ID=""
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        count=$((count + 1))
        if ! [[ "$line" =~ ^[0-9a-f]{64}$ ]]; then
            echo "ERROR: local-judge retirement received a malformed Docker inventory" >&2
            return 1
        fi
        LOCAL_JUDGE_CONTAINER_ID="$line"
    done <<< "$output"
    if [ "$count" -gt 1 ]; then
        echo "ERROR: local-judge retirement found multiple exact-name containers" >&2
        return 1
    fi
}

query_local_judge_exact_id() {
    local container_id="$1" output
    LOCAL_JUDGE_EXACT_ID_MATCH=""
    if ! output="$(
        local_judge_docker \
            ps -aq --no-trunc --filter "id=$container_id" \
            | /usr/bin/head -c 130
    )"; then
        return 1
    fi
    if [ -n "$output" ] && [ "$output" != "$container_id" ]; then
        return 1
    fi
    LOCAL_JUDGE_EXACT_ID_MATCH="$output"
}

wait_for_local_judge_exact_id_absence() {
    local container_id="$1" attempt
    for attempt in {1..20}; do
        if ! query_local_judge_exact_id "$container_id"; then
            echo "ERROR: cannot prove exact local-judge container-ID disappearance" >&2
            return 2
        fi
        if [ -z "$LOCAL_JUDGE_EXACT_ID_MATCH" ]; then
            return 0
        fi
        [ "$attempt" -eq 20 ] || /usr/bin/sleep 0.1
    done
    echo "ERROR: exact local-judge container ID remained after bounded removal convergence" >&2
    return 1
}

admit_local_judge_cleanup_host() {
    local host os_name machine passwd_home passwd_record uid test_root
    if [ "$LOCAL_JUDGE_TEST_MODE" -eq 1 ]; then
        test_root="$(dirname "$HOME")"
        if [ "$HOME" != "$test_root/home" ] \
            || [ "$LOCAL_JUDGE_SYSTEMCTL_BIN" != "$test_root/bin/systemctl" ] \
            || [ "$LOCAL_JUDGE_DOCKER_BIN" != "$test_root/bin/docker" ] \
            || [ ! -f "$LOCAL_JUDGE_SYSTEMCTL_BIN" ] \
            || [ ! -f "$LOCAL_JUDGE_DOCKER_BIN" ] \
            || [ -L "$LOCAL_JUDGE_SYSTEMCTL_BIN" ] \
            || [ -L "$LOCAL_JUDGE_DOCKER_BIN" ] \
            || [ "$(/usr/bin/stat -c %u "$LOCAL_JUDGE_SYSTEMCTL_BIN")" != "$EUID" ] \
            || [ "$(/usr/bin/stat -c %u "$LOCAL_JUDGE_DOCKER_BIN")" != "$EUID" ]; then
            echo "ERROR: synthetic local-judge host facts require isolated owner-controlled test clients" >&2
            return 1
        fi
        host="${HAPAX_INSTALL_UNITS_RETIRE_TEST_HOSTNAME:-}"
        passwd_home="${HAPAX_INSTALL_UNITS_RETIRE_TEST_PASSWD_HOME:-}"
        os_name="${HAPAX_INSTALL_UNITS_RETIRE_TEST_OS:-}"
        machine="${HAPAX_INSTALL_UNITS_RETIRE_TEST_ARCH:-}"
    else
        if ! host="$(/usr/bin/hostname)" \
            || ! os_name="$(/usr/bin/uname -s)" \
            || ! machine="$(/usr/bin/uname -m)" \
            || ! uid="$(/usr/bin/id -u)" \
            || ! passwd_record="$(/usr/bin/getent passwd "$uid")"; then
            echo "ERROR: cannot establish the local-judge destructive-cleanup host witness" >&2
            return 1
        fi
        if [[ "$passwd_record" == *$'\n'* ]] \
            || ! passwd_home="$(
                /usr/bin/python3 -I -S - "$passwd_record" <<'PY'
import sys

parts = sys.argv[1].split(":")
if len(parts) != 7 or not parts[5].startswith("/"):
    raise SystemExit(1)
print(parts[5])
PY
            )"; then
            echo "ERROR: cannot establish the local-judge passwd HOME witness" >&2
            return 1
        fi
    fi
    if [ "$host" != "hapax-appendix" ] \
        || [ "$passwd_home" != "$HOME" ] \
        || [ "$os_name" != "Linux" ] \
        || [ "$machine" != "x86_64" ]; then
        echo "ERROR: local-judge destructive cleanup is admitted only on exact Appendix/passwd-HOME/linux-amd64" >&2
        return 1
    fi
}

query_local_judge_image_record() {
    local output format
    format='{{json .Id}}{{printf "\t"}}{{json .Os}}{{printf "\t"}}{{json .Architecture}}{{printf "\t"}}{{json .Config}}'
    if ! output="$(
        local_judge_docker image inspect --format "$format" "$LOCAL_JUDGE_CONFIG_ID" \
            | /usr/bin/head -c 65537
    )"; then
        echo "ERROR: cannot inspect the exact historical local-judge image config" >&2
        return 1
    fi
    if [ -z "$output" ] || [ "${#output}" -gt 65536 ] || [[ "$output" == *$'\n'* ]]; then
        echo "ERROR: historical local-judge image record was malformed" >&2
        return 1
    fi
    if ! /usr/bin/python3 -I -S - "$LOCAL_JUDGE_CONFIG_ID" 3<<<"$output" <<'PY'
import json
import os
import sys

expected_id = sys.argv[1]
record = os.fdopen(3, encoding="utf-8").read()
if not record.endswith("\n") or "\n" in record[:-1]:
    raise SystemExit(1)
record = record[:-1]
try:
    image_id, os_name, architecture, config = (
        json.loads(field) for field in record.split("\t")
    )
except (TypeError, ValueError, json.JSONDecodeError):
    raise SystemExit(1)
valid = (
    image_id == expected_id
    and os_name == "linux"
    and architecture == "amd64"
    and isinstance(config, dict)
    and config.get("Entrypoint") == ["/app/llama-server"]
    and config.get("WorkingDir") == "/app"
)
raise SystemExit(0 if valid else 1)
PY
    then
        echo "ERROR: exact historical image does not witness the pinned linux/amd64 config" >&2
        return 1
    fi
    LOCAL_JUDGE_IMAGE_RECORD="$output"
}

validate_historical_local_judge_container() {
    local container_id="$1" output format profile
    format='{{json .Id}}{{printf "\t"}}{{json .Name}}{{printf "\t"}}{{json .Image}}{{printf "\t"}}{{json .Platform}}{{printf "\t"}}{{json .Path}}{{printf "\t"}}{{json .Args}}{{printf "\t"}}{{json .Config}}{{printf "\t"}}{{json .HostConfig}}{{printf "\t"}}{{json .Mounts}}{{printf "\t"}}{{json .NetworkSettings.Networks}}{{printf "\t"}}{{json .State}}'
    if ! output="$(
        local_judge_docker container inspect --format "$format" "$container_id" \
            | /usr/bin/head -c 65537
    )"; then
        echo "ERROR: cannot inspect the captured historical local-judge container" >&2
        return 1
    fi
    if [ -z "$output" ] || [ "${#output}" -gt 65536 ] || [[ "$output" == *$'\n'* ]]; then
        echo "ERROR: historical local-judge container record was malformed" >&2
        return 1
    fi
    if ! profile="$(
        /usr/bin/python3 -I -S - \
            "$container_id" "$HOME" "$LOCAL_JUDGE_CONFIG_ID" \
            "$LOCAL_JUDGE_IMAGE_DIGEST" \
            3<<<"$LOCAL_JUDGE_IMAGE_RECORD" 4<<<"$output" <<'PY'
from __future__ import annotations

import ipaddress
import json
import os
import re
import sys

container_id, home, config_id, image_digest = sys.argv[1:]


def read_record(fd: int) -> str:
    value = os.fdopen(fd, encoding="utf-8").read()
    if not value.endswith("\n") or "\n" in value[:-1]:
        raise ValueError
    return value[:-1]


image_record = read_record(3)
record = read_record(4)


def decode_fields(value: str, count: int) -> list[object]:
    fields = value.split("\t")
    if len(fields) != count:
        raise ValueError
    return [json.loads(field) for field in fields]


def empty(value: object) -> bool:
    return value is None or value is False or value == 0 or value in ("", [], {})


try:
    image_id, image_os, image_arch, image_config = decode_fields(image_record, 4)
    (
        actual_id,
        name,
        actual_image,
        platform,
        path,
        args,
        config,
        host,
        mounts,
        networks,
        state,
    ) = decode_fields(record, 11)
except (TypeError, ValueError, json.JSONDecodeError):
    raise SystemExit(1)

if not all(isinstance(value, dict) for value in (image_config, config, host, networks, state)):
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
expected_device_requests = [
    {
        "Capabilities": [["gpu"]],
        "Count": 0,
        "DeviceIDs": ["GPU-347222d9-00af-5a94-a365-c57c09dfddcd"],
        "Driver": "",
        "Options": {},
    }
]
expected_ports = {"5001/tcp": [{"HostIp": "", "HostPort": "5001"}]}
expected_exposed = dict(image_config.get("ExposedPorts") or {})
expected_exposed["5001/tcp"] = {}

inherited_keys = (
    "User",
    "Env",
    "WorkingDir",
    "Entrypoint",
    "Labels",
    "Healthcheck",
    "StopSignal",
    "Volumes",
    "OnBuild",
    "Shell",
)
required_config_keys = set(inherited_keys) | {
    "Image",
    "Cmd",
    "AttachStdin",
    "AttachStdout",
    "AttachStderr",
    "OpenStdin",
    "StdinOnce",
    "Tty",
    "NetworkDisabled",
    "ExposedPorts",
    "Hostname",
    "Domainname",
    "MacAddress",
    "StopTimeout",
    "ArgsEscaped",
}
config_valid = (
    required_config_keys.issubset(config)
    and all(config.get(key) == image_config.get(key) for key in inherited_keys)
    and config.get("Cmd") == expected_args
    and config.get("AttachStdin") is False
    and config.get("AttachStdout") is True
    and config.get("AttachStderr") is True
    and config.get("OpenStdin") is False
    and config.get("StdinOnce") is False
    and config.get("Tty") is False
    and config.get("NetworkDisabled") is False
    and config.get("ExposedPorts") == expected_exposed
    and config.get("Hostname") == container_id[:12]
    and config.get("Domainname") == ""
    and config.get("MacAddress") in (None, "")
    and config.get("StopTimeout") is None
    and config.get("ArgsEscaped") in (None, False)
)
unknown_config_defaults = all(
    empty(value) for key, value in config.items() if key not in required_config_keys
)

standard_masked = {
    "/proc/acpi",
    "/proc/asound",
    "/proc/kcore",
    "/proc/keys",
    "/proc/latency_stats",
    "/proc/scsi",
    "/proc/timer_list",
    "/proc/timer_stats",
    "/sys/devices/virtual/powercap",
    "/sys/firmware",
}
standard_readonly = {
    "/proc/bus",
    "/proc/fs",
    "/proc/irq",
    "/proc/sys",
    "/proc/sysrq-trigger",
}
masked_paths = host.get("MaskedPaths")
readonly_paths = host.get("ReadonlyPaths")
baseline_host_valid = (
    host.get("Privileged") is False
    and empty(host.get("CapAdd"))
    and empty(host.get("CapDrop"))
    and empty(host.get("SecurityOpt"))
    and host.get("ReadonlyRootfs") is False
    and host.get("NetworkMode") in ("bridge", "default")
    and host.get("PidMode") == ""
    and host.get("IpcMode") in ("", "private")
    and host.get("UTSMode") in ("", "private")
    and host.get("CgroupnsMode") in ("", "private")
    and host.get("UsernsMode") == ""
    and host.get("Devices") == []
    and host.get("DeviceRequests") == expected_device_requests
    and host.get("PortBindings") == expected_ports
    and host.get("PublishAllPorts") is False
    and host.get("AutoRemove") is True
    and host.get("MemoryReservation", 0) == 0
    and host.get("OomKillDisable") in (None, False)
    and host.get("OomScoreAdj", 0) == 0
    and host.get("Runtime") == "runc"
    and host.get("PidsLimit") in (None, 0)
    and host.get("RestartPolicy") == {"Name": "no", "MaximumRetryCount": 0}
    and host.get("NanoCpus", 0) == 0
    and host.get("CpuShares", 0) == 0
    and host.get("CpusetCpus", "") == ""
    and host.get("CpusetMems", "") == ""
    and host.get("ShmSize") == 67108864
    and host.get("LogConfig") == {"Type": "json-file", "Config": {}}
    and empty(host.get("Tmpfs"))
    and empty(host.get("Dns"))
    and empty(host.get("DnsOptions"))
    and empty(host.get("DnsSearch"))
    and empty(host.get("ExtraHosts"))
    and empty(host.get("Links"))
    and empty(host.get("GroupAdd"))
    and empty(host.get("VolumesFrom"))
    and host.get("Init") in (None, False)
    and isinstance(masked_paths, list)
    and standard_masked.issubset(masked_paths)
    and isinstance(readonly_paths, list)
    and standard_readonly.issubset(readonly_paths)
    and empty(host.get("Sysctls"))
    and empty(host.get("StorageOpt"))
    and empty(host.get("Mounts"))
    and host.get("ConsoleSize") in (None, [0, 0])
)

checked_host_keys = {
    "Binds",
    "Privileged",
    "CapAdd",
    "CapDrop",
    "SecurityOpt",
    "ReadonlyRootfs",
    "NetworkMode",
    "PidMode",
    "IpcMode",
    "UTSMode",
    "CgroupnsMode",
    "UsernsMode",
    "Devices",
    "DeviceRequests",
    "PortBindings",
    "PublishAllPorts",
    "AutoRemove",
    "Memory",
    "MemorySwap",
    "MemoryReservation",
    "OomKillDisable",
    "OomScoreAdj",
    "Runtime",
    "PidsLimit",
    "RestartPolicy",
    "NanoCpus",
    "CpuShares",
    "CpusetCpus",
    "CpusetMems",
    "ShmSize",
    "LogConfig",
    "Tmpfs",
    "Dns",
    "DnsOptions",
    "DnsSearch",
    "ExtraHosts",
    "Links",
    "GroupAdd",
    "VolumesFrom",
    "Init",
    "MaskedPaths",
    "ReadonlyPaths",
    "Sysctls",
    "StorageOpt",
    "Mounts",
    "ConsoleSize",
}
unknown_host_defaults = all(
    empty(value) for key, value in host.items() if key not in checked_host_keys
)

bridge_endpoint_keys = {
    "IPAMConfig",
    "Links",
    "Aliases",
    "MacAddress",
    "DriverOpts",
    "GwPriority",
    "NetworkID",
    "EndpointID",
    "Gateway",
    "IPAddress",
    "IPPrefixLen",
    "IPv6Gateway",
    "GlobalIPv6Address",
    "GlobalIPv6PrefixLen",
    "DNSNames",
}


def valid_bridge_endpoint(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"bridge"}:
        return False
    endpoint = value.get("bridge")
    if not isinstance(endpoint, dict) or set(endpoint) != bridge_endpoint_keys:
        return False
    if any(
        endpoint.get(key) is not None
        for key in ("IPAMConfig", "Links", "Aliases", "DriverOpts", "DNSNames")
    ):
        return False
    if type(endpoint.get("GwPriority")) is not int or endpoint["GwPriority"] != 0:
        return False
    if (
        type(endpoint.get("GlobalIPv6PrefixLen")) is not int
        or endpoint["GlobalIPv6PrefixLen"] != 0
        or endpoint.get("IPv6Gateway") != ""
        or endpoint.get("GlobalIPv6Address") != ""
    ):
        return False
    network_id = endpoint.get("NetworkID")
    endpoint_id = endpoint.get("EndpointID")
    if (
        not isinstance(network_id, str)
        or not isinstance(endpoint_id, str)
        or re.fullmatch(r"[0-9a-f]{64}", network_id) is None
        or re.fullmatch(r"[0-9a-f]{64}", endpoint_id) is None
        or network_id == "0" * 64
        or endpoint_id == "0" * 64
        or network_id == endpoint_id
    ):
        return False

    prefix = endpoint.get("IPPrefixLen")
    gateway_value = endpoint.get("Gateway")
    address_value = endpoint.get("IPAddress")
    if (
        type(prefix) is not int
        or not 1 <= prefix <= 30
        or not isinstance(gateway_value, str)
        or not isinstance(address_value, str)
    ):
        return False
    try:
        gateway = ipaddress.IPv4Address(gateway_value)
        address = ipaddress.IPv4Address(address_value)
        network = ipaddress.IPv4Network((address, prefix), strict=False)
    except ipaddress.AddressValueError:
        return False
    if (
        gateway.is_unspecified
        or address.is_unspecified
        or gateway == address
        or gateway not in network
        or gateway in (network.network_address, network.broadcast_address)
        or address in (network.network_address, network.broadcast_address)
        or any(
            value.is_loopback
            or value.is_link_local
            or value.is_multicast
            or value.is_reserved
            for value in (gateway, address)
        )
    ):
        return False

    mac = endpoint.get("MacAddress")
    if not isinstance(mac, str) or not re.fullmatch(
        r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", mac
    ):
        return False
    mac_octets = bytes.fromhex(mac.replace(":", ""))
    return (
        mac_octets[0] & 0b11 == 0b10
        and mac_octets[:2] == b"\x02\x42"
        and mac_octets[2:] == address.packed
    )

profiles = (
    (
        "mutable-uncapped-home",
        "ghcr.io/ggml-org/llama.cpp:server-cuda",
        f"{home}/models/compassverifier-7b",
        0,
        0,
    ),
    (
        "mutable-capped-home",
        "ghcr.io/ggml-org/llama.cpp:server-cuda",
        f"{home}/models/compassverifier-7b",
        4294967296,
        6442450944,
    ),
    (
        "pinned-capped-content",
        f"ghcr.io/ggml-org/llama.cpp@{image_digest}",
        "/store-fast/hapax-models/sha256/"
        "d6d6fba56c25d2d0f1b2cc8ee261b209b77729510b3d770d43ccb6e741dff0db",
        4294967296,
        6442450944,
    ),
)
matched_profile = ""
for profile_name, config_image, source, memory, memory_swap in profiles:
    expected_mounts = [
        {
            "Destination": "/models",
            "Mode": "ro",
            "Propagation": "rprivate",
            "RW": False,
            "Source": source,
            "Type": "bind",
        }
    ]
    if (
        config.get("Image") == config_image
        and host.get("Binds") == [f"{source}:/models:ro"]
        and mounts == expected_mounts
        and host.get("Memory", 0) == memory
        and host.get("MemorySwap", 0) == memory_swap
    ):
        matched_profile = profile_name
        break

valid = (
    image_id == config_id
    and image_os == "linux"
    and image_arch == "amd64"
    and actual_id == container_id
    and name == "/hapax-local-judge"
    and actual_image == config_id
    and platform == "linux"
    and path == "/app/llama-server"
    and args == expected_args
    and config_valid
    and unknown_config_defaults
    and baseline_host_valid
    and checked_host_keys.issubset(host)
    and unknown_host_defaults
    and valid_bridge_endpoint(networks)
    and state.get("Status")
    in {"created", "running", "restarting", "paused", "removing", "exited", "dead"}
    and bool(matched_profile)
)
if not valid:
    raise SystemExit(1)
print(matched_profile)
PY
    )"; then
        echo "ERROR: exact-name container does not match a complete historical local-judge profile; preserving it" >&2
        return 1
    fi
    case "$profile" in
        mutable-uncapped-home|mutable-capped-home|pinned-capped-content)
            LOCAL_JUDGE_PROFILE="$profile"
            ;;
        *)
            echo "ERROR: historical local-judge profile result was malformed" >&2
            return 1
            ;;
    esac
}

local_judge_mask_generation() {
    local dest="$1"
    /usr/bin/python3 -I -S - "$dest" <<'PY'
import os
import stat
import sys

path = sys.argv[1]
link = os.lstat(path)
if not stat.S_ISLNK(link.st_mode) or os.readlink(path) != "/dev/null":
    raise SystemExit(1)
target = os.stat(path)
null = os.stat("/dev/null")
target_key = (target.st_dev, target.st_ino, target.st_mode, target.st_rdev)
null_key = (null.st_dev, null.st_ino, null.st_mode, null.st_rdev)
if target_key != null_key or not stat.S_ISCHR(target.st_mode):
    raise SystemExit(1)
print(
    ":".join(
        str(value)
        for value in (
            link.st_dev,
            link.st_ino,
            link.st_mode,
            link.st_uid,
            link.st_gid,
            link.st_nlink,
            link.st_mtime_ns,
            link.st_ctime_ns,
            *target_key,
        )
    )
)
PY
}

query_local_judge_manager_witness() {
    local dest="$1" before after output witness
    if ! before="$(local_judge_mask_generation "$dest")"; then
        return 1
    fi
    if ! output="$(
        local_judge_systemctl show hapax-local-judge.service \
            -p LoadState -p UnitFileState -p ActiveState \
            -p SubState -p MainPID -p ControlPID --no-pager \
            | /usr/bin/head -c 1025
    )"; then
        return 1
    fi
    if ! after="$(local_judge_mask_generation "$dest")" \
        || [ "$before" != "$after" ] || [ "${#output}" -gt 1024 ]; then
        return 1
    fi
    if ! witness="$(/usr/bin/python3 -I -S - "$output" <<'PY'
import sys

expected = ("LoadState", "UnitFileState", "ActiveState", "SubState", "MainPID", "ControlPID")
values = {}
for line in sys.argv[1].splitlines():
    if "=" not in line:
        raise SystemExit(1)
    key, value = line.split("=", 1)
    if key not in expected or key in values or not value:
        raise SystemExit(1)
    values[key] = value
if set(values) != set(expected) or len(values) != len(expected):
    raise SystemExit(1)
print("\t".join(values[key] for key in expected))
PY
    )"; then
        return 1
    fi
    LOCAL_JUDGE_MANAGER_WITNESS="$witness"
}

local_judge_manager_is_quiesced() {
    [ "$LOCAL_JUDGE_MANAGER_WITNESS" = $'masked\tmasked\tinactive\tdead\t0\t0' ]
}

wait_for_local_judge_manager_quiescence() {
    local dest="$1" attempt
    for attempt in {1..20}; do
        if query_local_judge_manager_witness "$dest" \
            && local_judge_manager_is_quiesced; then
            return 0
        fi
        local_judge_systemctl kill --kill-who=all --signal=SIGKILL \
            hapax-local-judge.service >/dev/null 2>&1 || true
        local_judge_systemctl reset-failed \
            hapax-local-judge.service >/dev/null 2>&1 || true
        [ "$attempt" -eq 20 ] || /usr/bin/sleep 0.1
    done
    echo "ERROR: user manager did not converge to stable masked/masked/inactive/dead/0/0" >&2
    return 1
}

require_final_local_judge_manager_witness() {
    local dest="$1"
    if ! query_local_judge_manager_witness "$dest" \
        || ! local_judge_manager_is_quiesced; then
        echo "ERROR: final user-manager witness is not stable masked/masked/inactive/dead/0/0" >&2
        return 1
    fi
}

install_local_judge_mask() {
    local dest="$1"
    /usr/bin/python3 -I -S - "$dest" <<'PY'
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
    local manager_changed=0 wants_link before_id before_profile wait_rc
    local dropin_dir="$DEST_DIR/${name}.d"
    if ! configure_local_judge_retirement_commands; then
        return 2
    fi

    # The manager transaction is independent of container cleanup. Mask first,
    # then kill the loaded unit cgroup without invoking its name-based ExecStop.
    local_judge_systemctl disable "$name" >/dev/null 2>&1 || true
    if ! { [ -L "$dest" ] && [ "$(readlink "$dest")" = "/dev/null" ]; }; then
        manager_changed=1
        if ! rm -f -- "$dest" || ! install_local_judge_mask "$dest"; then
            echo "ERROR: could not install the historical local-judge mask" >&2
            return 2
        fi
    fi
    for wants_link in "$DEST_DIR"/*.wants/"$name"; do
        [ -e "$wants_link" ] || [ -L "$wants_link" ] || continue
        manager_changed=1
        if ! rm -f -- "$wants_link"; then
            echo "ERROR: could not remove a historical local-judge wants link" >&2
            return 2
        fi
    done
    if [ -e "$dropin_dir" ] || [ -L "$dropin_dir" ]; then
        manager_changed=1
        if ! rm -rf -- "$dropin_dir"; then
            echo "ERROR: could not remove historical local-judge drop-ins" >&2
            return 2
        fi
    fi
    if ! local_judge_systemctl daemon-reload >/dev/null; then
        echo "ERROR: could not reload the user manager after local-judge masking" >&2
        return 2
    fi
    local_judge_systemctl kill --kill-who=all --signal=SIGKILL "$name" >/dev/null 2>&1 || true
    local_judge_systemctl reset-failed "$name" >/dev/null 2>&1 || true
    if ! wait_for_local_judge_manager_quiescence "$dest"; then
        return 2
    fi

    if [ ! -x "$LOCAL_JUDGE_DOCKER_BIN" ]; then
        echo "ERROR: local-judge container cleanup requires an executable pinned Docker client" >&2
        require_final_local_judge_manager_witness "$dest" || true
        return 2
    fi
    if ! query_local_judge_container_id; then
        require_final_local_judge_manager_witness "$dest" || true
        return 2
    fi
    before_id="$LOCAL_JUDGE_CONTAINER_ID"
    if [ -z "$before_id" ]; then
        if ! require_final_local_judge_manager_witness "$dest"; then
            return 2
        fi
        if [ "$manager_changed" -eq 0 ]; then
            return 1
        fi
        echo "retired and masked historical local judge (container_id=absent)"
        return 0
    fi

    if ! admit_local_judge_cleanup_host \
        || ! query_local_judge_image_record \
        || ! validate_historical_local_judge_container "$before_id"; then
        require_final_local_judge_manager_witness "$dest" || true
        return 2
    fi
    before_profile="$LOCAL_JUDGE_PROFILE"

    # Container configuration is immutable, but disappearance is not. Reinspect
    # the captured immutable ID immediately before passing that same ID to rm.
    if ! validate_historical_local_judge_container "$before_id" \
        || [ "$LOCAL_JUDGE_PROFILE" != "$before_profile" ]; then
        echo "ERROR: captured local-judge identity changed or disappeared before removal; preserving all observed containers" >&2
        require_final_local_judge_manager_witness "$dest" || true
        return 2
    fi
    if ! local_judge_docker rm -f "$before_id" >/dev/null; then
        echo "ERROR: could not remove the captured historical local-judge container ID" >&2
        require_final_local_judge_manager_witness "$dest" || true
        return 2
    fi
    wait_rc=0
    wait_for_local_judge_exact_id_absence "$before_id" || wait_rc=$?
    if [ "$wait_rc" -ne 0 ]; then
        require_final_local_judge_manager_witness "$dest" || true
        return 2
    fi
    if ! query_local_judge_container_id; then
        require_final_local_judge_manager_witness "$dest" || true
        return 2
    fi
    if [ -n "$LOCAL_JUDGE_CONTAINER_ID" ]; then
        echo "ERROR: a replacement local-judge container appeared; preserving its immutable ID" >&2
        require_final_local_judge_manager_witness "$dest" || true
        return 2
    fi
    if ! require_final_local_judge_manager_witness "$dest"; then
        return 2
    fi
    echo "retired and masked historical local judge (container_id=$before_id profile=$before_profile)"
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

UNIT_INSTALL_SCOPE=""
classify_unit_install_scope() {
    local path="$1" scope_marker_count system_marker_count
    UNIT_INSTALL_SCOPE="user"
    [ -f "$path" ] || return 0
    scope_marker_count="$(
        grep -Eic '^[[:blank:]]*[#;][[:blank:]]*Hapax-Install-Scope[[:blank:]]*:' "$path" || true
    )"
    system_marker_count="$(
        grep -Eic '^[[:blank:]]*[#;][[:blank:]]*Hapax-Install-Scope[[:blank:]]*:[[:blank:]]*system[[:blank:]]*$' "$path" || true
    )"
    if [ "$scope_marker_count" -eq 0 ]; then
        return 0
    fi
    if [ "$scope_marker_count" -eq 1 ] && [ "$system_marker_count" -eq 1 ]; then
        UNIT_INSTALL_SCOPE="system"
        return 0
    fi
    echo "ERROR: malformed Hapax-Install-Scope marker in $path (duplicate or unsupported value)" >&2
    return 1
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
    if ! classify_unit_install_scope "$unit"; then
        exit 1
    fi
    if [ "$UNIT_INSTALL_SCOPE" = "system" ]; then
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
        stale_dropin_dir="$DEST_DIR/${name}.d"
        if [ -e "$stale_dropin_dir" ] || [ -L "$stale_dropin_dir" ]; then
            rm -rf -- "$stale_dropin_dir"
            changed=$((changed + 1))
            echo "removed stale user-scope drop-ins for system unit: ${name}.d"
        fi
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
        if parked_unit "$unit"; then
            echo "not queued for enable: parked timer $name"
        else
            new_timers+=("$name")
        fi
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
        parked_unit "$timer_file" && continue
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
        parked_unit "$REPO_DIR/$timer" && continue
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
    base_unit="$REPO_DIR/${svc_name%.d}"
    if ! classify_unit_install_scope "$base_unit"; then
        exit 1
    fi
    if [ "$UNIT_INSTALL_SCOPE" = "system" ]; then
        dest_dropin_dir="$DEST_DIR/$svc_name"
        if [ -e "$dest_dropin_dir" ] || [ -L "$dest_dropin_dir" ]; then
            rm -rf -- "$dest_dropin_dir"
            dropin_changed=$((dropin_changed + 1))
            echo "dropin-removed-system-scope: $svc_name"
        fi
        continue
    fi
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
