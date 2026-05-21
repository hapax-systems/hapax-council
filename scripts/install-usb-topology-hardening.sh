#!/usr/bin/env bash
# Install the S-4/L-12/CalDigit USB topology hardening packet.
#
# This installer writes only host policy/config/service files. It never writes
# firmware to S-4, L-12, camera, or CalDigit hardware.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODE="apply"
ROOT=""
HOME_DIR="$HOME"
PYTHON_BIN="${PYTHON:-python3}"
TMP_FILES=()

cleanup() {
    for tmp in "${TMP_FILES[@]}"; do
        rm -f "$tmp"
    done
}
trap cleanup EXIT

usage() {
    cat <<'EOF'
Usage: scripts/install-usb-topology-hardening.sh [--dry-run|--check] [--root PATH] [--home PATH]

Modes:
  --dry-run   print the files that would be installed; write nothing
  --check     compare installed files with repo sources; write nothing

Options:
  --root PATH  install/check system files under PATH instead of /
  --home PATH  install/check user files under PATH instead of $HOME
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            MODE="dry-run"
            ;;
        --check)
            MODE="check"
            ;;
        --root)
            ROOT="${2:?--root requires a path}"
            shift
            ;;
        --home)
            HOME_DIR="${2:?--home requires a path}"
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

user_path() {
    local suffix="$1"
    printf '%s/%s\n' "${HOME_DIR%/}" "$suffix"
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
    local scope="$4"

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
            if [[ "$scope" == "system" ]]; then
                run_privileged install -Dm "$mode" "$src" "$dst"
            else
                install -Dm "$mode" "$src" "$dst"
            fi
            echo "wrote $dst"
            ;;
    esac
}

merged_policy_source() {
    local src="$1"
    local dst="$2"
    local tmp

    tmp="$(mktemp)"
    TMP_FILES+=("$tmp")

    "$PYTHON_BIN" - "$src" "$dst" "$tmp" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

source_path = Path(sys.argv[1])
installed_path = Path(sys.argv[2])
output_path = Path(sys.argv[3])


def read_policy(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise SystemExit(f"USB topology policy must be a JSON object: {path}")
    return data


def merge_required_cameras(
    source: list[object],
    installed: list[object],
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []

    for entry in [*source, *installed]:
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("role", ""))
        serial = str(entry.get("serial", ""))
        key = (role, serial)
        if key == ("", ""):
            continue
        if key not in merged:
            order.append(key)
        merged[key] = dict(entry)

    return [merged[key] for key in order]


source_policy = read_policy(source_path)
installed_policy = read_policy(installed_path)
merged_policy = dict(source_policy)

source_absences = source_policy.get("known_absences", {})
installed_absences = installed_policy.get("known_absences", {})
if isinstance(source_absences, dict) or isinstance(installed_absences, dict):
    merged_policy["known_absences"] = {
        **(source_absences if isinstance(source_absences, dict) else {}),
        **(installed_absences if isinstance(installed_absences, dict) else {}),
    }

merged_policy["required_cameras"] = merge_required_cameras(
    source_policy.get("required_cameras", []),
    installed_policy.get("required_cameras", []),
)

output_path.write_text(json.dumps(merged_policy, indent=2) + "\n", encoding="utf-8")
PY

    printf '%s\n' "$tmp"
}

install_policy_file() {
    local src="$1"
    local dst="$2"
    local mode="$3"
    local scope="$4"
    local effective_src="$src"

    if [[ "$MODE" != "dry-run" && -f "$dst" ]]; then
        effective_src="$(merged_policy_source "$src" "$dst")"
    fi

    install_file "$effective_src" "$dst" "$mode" "$scope"
}

status=0

system_installs=(
    "$REPO_DIR/config/udev/rules.d/50-hapax-usb-audio-video-noautosuspend.rules|$(system_path /etc/udev/rules.d/50-hapax-usb-audio-video-noautosuspend.rules)|0644"
    "$REPO_DIR/config/udev/rules.d/53-hapax-suppress-camera-audio.rules|$(system_path /etc/udev/rules.d/53-hapax-suppress-camera-audio.rules)|0644"
    "$REPO_DIR/config/udev/rules.d/90-hapax-s4-composite.rules|$(system_path /etc/udev/rules.d/90-hapax-s4-composite.rules)|0644"
    "$REPO_DIR/config/NetworkManager/conf.d/90-hapax-s4-unmanaged.conf|$(system_path /etc/NetworkManager/conf.d/90-hapax-s4-unmanaged.conf)|0644"
    "$REPO_DIR/config/modprobe.d/99-hapax-usb-reliability-override.conf|$(system_path /etc/modprobe.d/99-hapax-usb-reliability-override.conf)|0644"
    "$REPO_DIR/scripts/hapax-usb-bandwidth-watchdog|$(system_path /usr/local/bin/hapax-usb-bandwidth-watchdog)|0755"
    "$REPO_DIR/systemd/units/hapax-usb-bandwidth-watchdog.service|$(system_path /etc/systemd/system/hapax-usb-bandwidth-watchdog.service)|0644"
    "$REPO_DIR/scripts/hapax-xhci-death-watchdog|$(system_path /usr/local/bin/hapax-xhci-death-watchdog)|0755"
    "$REPO_DIR/systemd/units/hapax-xhci-death-watchdog.service|$(system_path /etc/systemd/system/hapax-xhci-death-watchdog.service)|0644"
    "$REPO_DIR/scripts/hapax-usb-bandwidth-preflight|$(system_path /usr/local/bin/hapax-usb-bandwidth-preflight)|0755"
    "$REPO_DIR/shared/usb_bandwidth_table.py|$(system_path /usr/local/share/hapax-council/shared/usb_bandwidth_table.py)|0644"
    "$REPO_DIR/systemd/units/hapax-usb-bandwidth-preflight.service|$(system_path /etc/systemd/system/hapax-usb-bandwidth-preflight.service)|0644"
    "$REPO_DIR/systemd/units/hapax-usb-bandwidth-preflight.timer|$(system_path /etc/systemd/system/hapax-usb-bandwidth-preflight.timer)|0644"
    "$REPO_DIR/scripts/hapax-l12-critical-usb-guard|$(system_path /usr/local/bin/hapax-l12-critical-usb-guard)|0755"
    "$REPO_DIR/systemd/units/hapax-l12-critical-usb-guard.service|$(system_path /etc/systemd/system/hapax-l12-critical-usb-guard.service)|0644"
    "$REPO_DIR/systemd/units/hapax-l12-critical-usb-guard.timer|$(system_path /etc/systemd/system/hapax-l12-critical-usb-guard.timer)|0644"
)

user_installs=(
    "$REPO_DIR/scripts/hapax-usb-topology-witness|$(user_path .local/bin/hapax-usb-topology-witness)|0755"
    "$REPO_DIR/scripts/hapax-l12-hotplug-recover|$(user_path .local/bin/hapax-l12-hotplug-recover)|0755"
    "$REPO_DIR/config/usb-topology-policy.json|$(user_path .config/hapax/usb-topology-policy.json)|0644"
    "$REPO_DIR/systemd/units/hapax-usb-topology-witness.service|$(user_path .config/systemd/user/hapax-usb-topology-witness.service)|0644"
    "$REPO_DIR/systemd/units/hapax-usb-topology-witness.timer|$(user_path .config/systemd/user/hapax-usb-topology-witness.timer)|0644"
    "$REPO_DIR/systemd/units/hapax-l12-hotplug-recover.service|$(user_path .config/systemd/user/hapax-l12-hotplug-recover.service)|0644"
    "$REPO_DIR/systemd/units/hapax-usb-router.service|$(user_path .config/systemd/user/hapax-usb-router.service)|0644"
)

for entry in "${system_installs[@]}"; do
    IFS='|' read -r src dst mode <<< "$entry"
    install_file "$src" "$dst" "$mode" system || status=1
done

for entry in "${user_installs[@]}"; do
    IFS='|' read -r src dst mode <<< "$entry"
    if [[ "$src" == "$REPO_DIR/config/usb-topology-policy.json" ]]; then
        install_policy_file "$src" "$dst" "$mode" user || status=1
    else
        install_file "$src" "$dst" "$mode" user || status=1
    fi
done

if [[ "$MODE" == "check" ]]; then
    exit "$status"
fi

if [[ "$MODE" == "apply" ]]; then
    if [[ -z "$ROOT" ]]; then
        run_privileged udevadm control --reload-rules
        run_privileged udevadm trigger --subsystem-match=usb --action=change || true
        run_privileged systemctl daemon-reload
        run_privileged systemctl enable --now hapax-usb-bandwidth-watchdog.service
        run_privileged systemctl enable --now hapax-xhci-death-watchdog.service
        run_privileged systemctl enable --now hapax-l12-critical-usb-guard.timer
    fi
    systemctl --user daemon-reload
    systemctl --user enable --now hapax-usb-topology-witness.timer
    systemctl --user start hapax-usb-topology-witness.service || true
fi

if [[ "$MODE" == "dry-run" ]]; then
    echo "kernel params source: $REPO_DIR/config/kernel-cmdline/hapax-usb-reliability.params"
    echo "apply bootloader/kernel-command-line changes manually per docs/runbooks/usb-s4-l12-topology-hardening.md"
fi

exit 0
