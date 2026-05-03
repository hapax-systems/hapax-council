#!/usr/bin/env bash
# install-webcam-audio-suppress-udev.sh — install the O1 udev rule.
#
# cc-task: audio-audit-O1-webcam-audio-suppress
#
# Copies config/udev/rules.d/56-hapax-webcam-audio-suppress.rules into
# /etc/udev/rules.d/, reloads udev, and triggers a re-enumeration of the
# USB subsystem so the rule applies without a reboot.
#
# Operator action: requires sudo.

set -euo pipefail

REPO_RULE_REL="config/udev/rules.d/56-hapax-webcam-audio-suppress.rules"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${REPO_ROOT}/${REPO_RULE_REL}"
DST="/etc/udev/rules.d/56-hapax-webcam-audio-suppress.rules"

if [ ! -r "$SRC" ]; then
  echo "install-webcam-audio-suppress-udev: source rule missing: $SRC" >&2
  exit 1
fi

echo "[install] copying $SRC -> $DST"
sudo install -m 0644 "$SRC" "$DST"

echo "[install] reloading udev rules"
sudo udevadm control --reload

echo "[install] triggering USB subsystem re-enumeration"
sudo udevadm trigger --subsystem-match=usb --action=add

echo "[install] done. Verify with:"
echo "    pactl list cards short | grep -i 'alsa_card\\.usb.*Logi'"
echo "(empty output = success)"
