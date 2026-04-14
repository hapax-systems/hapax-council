#!/usr/bin/env bash
# Retire the local studio-compositor-reload.{path,service} unit pair.
#
# BETA-FINDING-P (queue 025 Phase 6) migrated compositor rebuild
# coverage into hapax-rebuild-services.service. The legacy
# ``studio-compositor-reload.path`` unit fired on any file-system
# change without a branch check and caused three unexplained
# restarts during queue 023 research. The new path runs through
# ``scripts/rebuild-service.sh`` which enforces the branch check.
#
# The old unit pair lives at ~/.config/systemd/user/ and is NOT
# tracked in the repo (they were local-only config). Removing
# them requires operator-side action after the repo-side unit
# edit merges.
#
# Run this script once after merging the PR that adds the
# compositor ExecStart line to hapax-rebuild-services.service.
# It is idempotent — running twice is a safe no-op.
set -euo pipefail

UNIT_DIR="$HOME/.config/systemd/user"
PATH_UNIT="studio-compositor-reload.path"
SERVICE_UNIT="studio-compositor-reload.service"

echo "[retire] studio-compositor-reload unit pair cleanup"

if [[ -f "$UNIT_DIR/$PATH_UNIT" ]] || [[ -f "$UNIT_DIR/$SERVICE_UNIT" ]]; then
    echo "[retire] stopping + disabling $PATH_UNIT"
    systemctl --user stop "$PATH_UNIT" 2>/dev/null || true
    systemctl --user disable "$PATH_UNIT" 2>/dev/null || true

    echo "[retire] stopping $SERVICE_UNIT"
    systemctl --user stop "$SERVICE_UNIT" 2>/dev/null || true

    for f in "$PATH_UNIT" "$SERVICE_UNIT"; do
        if [[ -f "$UNIT_DIR/$f" ]]; then
            echo "[retire] removing $UNIT_DIR/$f"
            rm -f "$UNIT_DIR/$f"
        fi
    done

    echo "[retire] daemon-reload"
    systemctl --user daemon-reload

    echo "[retire] done — compositor rebuild now routes through"
    echo "[retire] hapax-rebuild-services.timer (every 5 min, branch-checked)"
else
    echo "[retire] no-op: both units already absent"
fi

echo "[retire] ensuring hapax-rebuild-services reads the new ExecStart"
systemctl --user daemon-reload
systemctl --user show hapax-rebuild-services.service \
    --property ExecStart \
    | tr ';' '\n' \
    | grep -c compositor > /tmp/retire-compositor-count.$$ || true
count=$(cat /tmp/retire-compositor-count.$$ 2>/dev/null || echo 0)
rm -f /tmp/retire-compositor-count.$$
if [[ "$count" -ge "1" ]]; then
    echo "[retire] verified: hapax-rebuild-services has compositor ExecStart"
else
    echo "[retire] WARNING: hapax-rebuild-services does not appear to have"
    echo "[retire]          a compositor ExecStart line. Make sure the repo"
    echo "[retire]          is on a main commit that includes the migration."
    exit 1
fi
