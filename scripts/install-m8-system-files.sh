#!/usr/bin/env bash
# Install the M8 udev rule + modprobe.d + modules-load.d to /etc/.
# Idempotent: skips files whose content already matches.
# Requires sudo for the install steps.
#
# After this script:
#   - /dev/hapax-m8-serial appears whenever the M8 is plugged in
#   - /dev/video15 exists at boot via v4l2loopback module
#   - hapax-m8-monitor.service is pulled into the user graph on M8 plug
#
# Operator flow:
#   $ sudo bash scripts/install-m8-system-files.sh
#   $ systemctl --user daemon-reload
#   $ systemctl --user enable hapax-m8-monitor.service  # optional; udev pulls it
#
# cc-task: re-splay-homage-ward-m8

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# (source-path, target-path) pairs.
INSTALLS=(
    "${REPO_DIR}/systemd/udev/99-hapax-m8.rules:/etc/udev/rules.d/99-hapax-m8.rules"
    "${REPO_DIR}/config/modprobe.d/hapax-m8.conf:/etc/modprobe.d/hapax-m8.conf"
    "${REPO_DIR}/config/modules-load.d/hapax-m8.conf:/etc/modules-load.d/hapax-m8.conf"
)

# Need root.
if [[ $EUID -ne 0 ]]; then
    if command -v sudo &>/dev/null; then
        exec sudo -n "$0" "$@"
    else
        echo "ERROR: need root to install system files" >&2
        exit 1
    fi
fi

changed=0
for entry in "${INSTALLS[@]}"; do
    src="${entry%%:*}"
    dst="${entry##*:}"
    if [[ ! -f "$src" ]]; then
        echo "ERROR: source file missing: $src" >&2
        exit 1
    fi
    if [[ -f "$dst" ]] && cmp -s "$src" "$dst"; then
        echo "ok   $dst (unchanged)"
        continue
    fi
    install -m 0644 "$src" "$dst"
    echo "wrote $dst"
    changed=1
done

if [[ $changed -eq 1 ]]; then
    echo "reloading udev rules"
    udevadm control --reload-rules

    # Load v4l2loopback now (no reboot required) so /dev/video15 appears
    # immediately. Idempotent — modprobe is a no-op if already loaded
    # with matching options.
    if ! lsmod | grep -q "^v4l2loopback "; then
        echo "loading v4l2loopback module"
        modprobe v4l2loopback
    fi

    # Trigger udev to re-evaluate already-plugged USB devices so the M8
    # gets the new SYMLINK + SYSTEMD_USER_WANTS without a replug.
    echo "triggering udev re-evaluation"
    udevadm trigger --subsystem-match=usb --action=change || true
    udevadm trigger --subsystem-match=tty --action=change || true
fi

echo "done — operator next step: systemctl --user daemon-reload"
