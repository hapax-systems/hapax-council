#!/usr/bin/env bash
# Install the studio camera udev rules to /etc/udev/rules.d/.
# Idempotent: only writes when the source differs from the installed copy.
# Requires sudo for the install step.
#
# Used as an ExecStartPre= in studio-compositor.service so the rules are
# guaranteed to be in place before the compositor starts, and re-applied if
# the repo-tracked copy changes.
#
# See docs/superpowers/plans/2026-04-12-camera-247-resilience-epic.md § Phase 1.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$REPO_DIR/systemd/udev/70-studio-cameras.rules"
TARGET="/etc/udev/rules.d/70-studio-cameras.rules"

if [[ ! -f "$SOURCE" ]]; then
    echo "ERROR: source rule file not found at $SOURCE" >&2
    exit 1
fi

# Idempotent install: skip if content matches.
if [[ -f "$TARGET" ]] && cmp -s "$SOURCE" "$TARGET"; then
    exit 0
fi

# Need root to write to /etc/udev/rules.d and to run udevadm.
if [[ $EUID -ne 0 ]]; then
    if command -v sudo &>/dev/null; then
        exec sudo -n "$0" "$@"
    else
        echo "ERROR: need root to install udev rule" >&2
        exit 1
    fi
fi

install -m 0644 "$SOURCE" "$TARGET"
udevadm control --reload-rules
udevadm trigger --subsystem-match=usb --action=change
echo "installed $TARGET and reloaded udev rules"
