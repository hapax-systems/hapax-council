#!/usr/bin/env bash
# studio-compositor-archive-precheck.sh — LRR Phase 2 archive install verifier.
#
# Invoked from studio-compositor.service ExecStartPre. Idempotent. Non-fatal
# by default — a broken precheck must NEVER block the compositor from starting
# since livestream uptime takes priority over archive completeness.
#
# Responsibilities (in order, each independent):
#
#   1. Ensure the archive destination directories exist:
#      ~/hapax-state/stream-archive/hls/
#      ~/hapax-state/stream-archive/audio/
#
#   2. Verify hls-archive-rotate.timer is both loaded AND enabled. If not,
#      emit a LOUD warning to journald so the operator notices — but do not
#      attempt to install or enable the timer from here. Installing units
#      mid-boot is the install-units.sh script's job.
#
# Delta 2026-04-14-lrr-phase-2-hls-archive-dormant.md identified that
# Phase 2 shipped code + unit files but the operator hadn't run
# install-units.sh post-merge, so every HLS segment was being deleted at
# the old hlssink2 max_files=15 boundary. This precheck now protects archive
# completeness only; live HLS cache ownership belongs to hlssink2.
set -euo pipefail

HLS_ARCHIVE_DIR="${HAPAX_HLS_ARCHIVE_ROOT:-${HOME}/hapax-state/stream-archive/hls}"
AUDIO_ARCHIVE_DIR="${HAPAX_AUDIO_ARCHIVE_ROOT:-${HOME}/hapax-state/stream-archive/audio}"

mkdir -p "$HLS_ARCHIVE_DIR" "$AUDIO_ARCHIVE_DIR"
echo "archive-precheck: dirs OK ($HLS_ARCHIVE_DIR, $AUDIO_ARCHIVE_DIR)"

# Verify hls-archive-rotate.timer is installed + enabled. Tolerate "not found"
# without failing the service — the compositor has to start regardless.
if systemctl --user is-enabled hls-archive-rotate.timer >/dev/null 2>&1; then
    echo "archive-precheck: hls-archive-rotate.timer enabled"
else
    echo "archive-precheck: WARNING hls-archive-rotate.timer NOT enabled — " \
         "run scripts/install-units.sh to restore LRR Phase 2 archive pipeline" >&2
fi

if systemctl --user is-active hls-archive-rotate.timer >/dev/null 2>&1; then
    echo "archive-precheck: hls-archive-rotate.timer active"
else
    echo "archive-precheck: WARNING hls-archive-rotate.timer NOT active — " \
         "research archive will not receive HLS segment copies" >&2
fi

exit 0
