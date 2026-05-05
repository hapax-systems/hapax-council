#!/usr/bin/env bash
# install-voice-fx-ducking.sh — install hapax-voice-over-ytube-duck.conf + restart pipewire
#
# Audit-closeout 4.4: hapax-voice-over-ytube-duck.conf was missing from
# ~/.config/pipewire/pipewire.conf.d/. The audio-ducking FSM works at the
# Python layer (AudioDuckingController + youtube-player wpctl tick), but
# without this PipeWire sidechain conf the sink-level gain modulation
# never engages. Layer (c) of the 4-layer audio-ducking defence per the
# audit synthesis.
#
# Idempotent. Safe to run multiple times. Exit codes:
#   0 — installed (or already present + verified)
#   1 — install failed
#   2 — verification failed (sink not registered after restart)
#   3 — missing prereq (sc4m_1916 LADSPA plugin / swh-plugins)

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${REPO_ROOT}/config/pipewire/hapax-voice-over-ytube-duck.conf"
DEST_DIR="${HOME}/.config/pipewire/pipewire.conf.d"
DEST="${DEST_DIR}/hapax-voice-over-ytube-duck.conf"

[ -f "$SRC" ] || { echo "missing source: $SRC" >&2; exit 1; }

# Prereq: sc4m_1916 LADSPA plugin
if ! find /usr/lib/ladspa /usr/local/lib/ladspa ~/.ladspa -name 'sc4m_1916.so' 2>/dev/null | grep -q .; then
  echo "WARNING: sc4m_1916 LADSPA plugin not found. Install swh-plugins:" >&2
  echo "  pacman -S swh-plugins  (Arch)" >&2
  echo "Continuing — the conf will load but sidechain compression will fail silently." >&2
fi

mkdir -p "$DEST_DIR"

if [ -e "$DEST" ] && cmp -s "$SRC" "$DEST"; then
  echo "already installed and matches repo source: $DEST"
else
  if [ -e "$DEST" ]; then
    backup="${DEST}.bak.$(date +%Y%m%d-%H%M%S)"
    cp "$DEST" "$backup"
    echo "backed up existing $DEST → $backup"
  fi
  cp "$SRC" "$DEST"
  echo "installed $SRC → $DEST"
fi

# Symlinking would be cleaner but pipewire.conf.d treats symlinks
# inconsistently across distros — copy is the documented pattern.

echo
echo "restarting pipewire stack..."
systemctl --user restart pipewire pipewire-pulse wireplumber
sleep 2

# Verify the hapax-ytube-ducked sink is now registered.
if pactl list short sinks 2>/dev/null | grep -q 'hapax-ytube-ducked'; then
  echo "✅ hapax-ytube-ducked sink registered"
else
  echo "❌ hapax-ytube-ducked sink NOT registered after restart" >&2
  echo "   inspect: journalctl --user -u pipewire --since '1 min ago'" >&2
  exit 2
fi

# Smoke: gain control reachable
if wpctl set-volume @hapax-ytube-ducked@ 1.0 2>/dev/null; then
  echo "✅ gain control responsive (set-volume @hapax-ytube-ducked@ 1.0 ok)"
else
  echo "⚠️  could not set volume on @hapax-ytube-ducked@; check wireplumber" >&2
fi

echo
echo "Voice-over-YT ducking sink installed. To route YT audio through it:"
echo "  - OBS: Advanced Audio Properties → Audio Monitoring → Hapax YouTube Ducker"
echo "  - Chromium: --alsa-output-device or PipeWire sink chooser"
