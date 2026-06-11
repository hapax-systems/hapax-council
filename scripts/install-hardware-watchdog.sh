#!/usr/bin/env bash
# Install + arm the SP5100-TCO hardware watchdog (audit-w0-watchdog-arm-20260611).
#
# Installs the un-denylist shadow, boot-time module load, and the systemd
# RuntimeWatchdogSec drop-in; removes the superseded 2026-03 podium-era
# artifacts; then loads the module and re-executes PID 1 so the watchdog is
# armed without a reboot. Config-only: never touches firmware or BIOS.
# Rollback: docs/runbooks/hardware-watchdog-sp5100.md (re-denylist).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODE="apply"
ROOT=""

usage() {
    cat <<'EOF'
Usage: scripts/install-hardware-watchdog.sh [--dry-run|--check] [--root PATH]

Modes:
  --dry-run   print the files that would be installed/removed; write nothing
  --check     compare installed files with repo sources; write nothing

Options:
  --root PATH  install/check system files under PATH instead of /
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) MODE="dry-run" ;;
        --check) MODE="check" ;;
        --root)
            ROOT="${2:?--root requires a path}"
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

system_path() {
    local path="$1"
    if [[ -n "$ROOT" ]]; then
        printf '%s%s\n' "${ROOT%/}" "$path"
    else
        printf '%s\n' "$path"
    fi
}

run_privileged() {
    if [[ -n "$ROOT" || $EUID -eq 0 ]]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo -n "$@"
    else
        echo "ERROR: need root or passwordless sudo for system install: $*" >&2
        exit 1
    fi
}

install_file() {
    local src="$1"
    local dst="$2"
    local mode="$3"

    if [[ ! -f "$src" ]]; then
        echo "ERROR: source file missing: $src" >&2
        exit 1
    fi

    case "$MODE" in
        dry-run)
            echo "would install $dst <- $src"
            ;;
        check)
            if [[ -f "$dst" ]] && cmp -s "$src" "$dst"; then
                echo "ok   $dst"
            else
                echo "drift $dst"
                return 1
            fi
            ;;
        apply)
            if [[ -f "$dst" ]] && cmp -s "$src" "$dst"; then
                echo "ok   $dst"
                return 0
            fi
            run_privileged install -Dm "$mode" "$src" "$dst"
            echo "wrote $dst"
            ;;
    esac
}

# Podium-era artifacts superseded by this packet (never worked: the vendor
# blacklist defeats modules-load.d, and the install-override only helps
# explicit CLI modprobe).
remove_stale() {
    local dst="$1"

    case "$MODE" in
        dry-run)
            [[ -e "$dst" ]] && echo "would remove $dst"
            ;;
        check)
            if [[ -e "$dst" ]]; then
                echo "stale $dst"
                return 1
            fi
            ;;
        apply)
            if [[ -e "$dst" ]]; then
                run_privileged rm -f "$dst"
                echo "removed $dst"
            fi
            ;;
    esac
    return 0
}

status=0

system_installs=(
    "$REPO_DIR/config/modprobe.d/blacklist.conf|$(system_path /etc/modprobe.d/blacklist.conf)|0644"
    "$REPO_DIR/config/modules-load.d/hapax-watchdog.conf|$(system_path /etc/modules-load.d/hapax-watchdog.conf)|0644"
    "$REPO_DIR/systemd/system/system.conf.d/10-hapax-watchdog.conf|$(system_path /etc/systemd/system.conf.d/10-hapax-watchdog.conf)|0644"
)

stale_files=(
    "$(system_path /etc/modules-load.d/watchdog.conf)"
    "$(system_path /etc/modprobe.d/sp5100_tco.conf)"
)

for entry in "${system_installs[@]}"; do
    IFS='|' read -r src dst mode <<< "$entry"
    install_file "$src" "$dst" "$mode" || status=1
done

for dst in "${stale_files[@]}"; do
    remove_stale "$dst" || status=1
done

# Drop-ins win over system.conf, but a live uncommented RuntimeWatchdogSec=
# there is unversioned drift — flag it (the 2026-03 podium edit class).
main_conf="$(system_path /etc/systemd/system.conf)"
if [[ -f "$main_conf" ]] && grep -Eq '^\s*RuntimeWatchdogSec=' "$main_conf"; then
    echo "WARN: $(grep -En '^\s*RuntimeWatchdogSec=' "$main_conf" | head -1) set directly in $main_conf — drop-in overrides it, but revert the edit to keep the drop-in as SSOT" >&2
fi

if [[ "$MODE" == "check" ]]; then
    exit "$status"
fi

if [[ "$MODE" == "apply" && -z "$ROOT" ]]; then
    run_privileged systemctl restart systemd-modules-load.service
    run_privileged systemctl daemon-reexec

    sleep 2
    fail=0
    if [[ -e /dev/watchdog ]]; then
        echo "ok   /dev/watchdog present"
    else
        echo "FAIL /dev/watchdog absent — sp5100_tco did not load (dmesg | grep sp5100)" >&2
        fail=1
    fi
    state="$(cat /sys/class/watchdog/watchdog0/state 2>/dev/null || echo missing)"
    if [[ "$state" == "active" ]]; then
        echo "ok   watchdog0 state=active ($(cat /sys/class/watchdog/watchdog0/identity 2>/dev/null), timeout=$(cat /sys/class/watchdog/watchdog0/timeout 2>/dev/null)s)"
    else
        echo "FAIL watchdog0 state=$state (expected active — PID 1 did not arm it)" >&2
        fail=1
    fi
    armed="$(systemctl show -p RuntimeWatchdogUSec --value)"
    if [[ "$armed" == "1min" ]]; then
        echo "ok   RuntimeWatchdogUSec=$armed"
    else
        echo "FAIL RuntimeWatchdogUSec=$armed (expected 1min)" >&2
        fail=1
    fi
    exit "$fail"
fi

exit 0
