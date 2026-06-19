#!/usr/bin/env bash
# Promote the DarkPlaces renderer from contained to ATTENDED-allowed by creating
# ~/.config/hapax/enable-darkplaces-runtime — but ONLY if a fresh PASS soak
# receipt matches the current hardware fingerprint. All the fail-closed decision
# logic lives in scripts/darkplaces-soak.py (shared/darkplaces_soak.py core).
#
# Usage: scripts/darkplaces-promote.sh [--max-age-s N] [--receipt PATH] [--gpu-index N]
#
# A driver/GPU change, a stale receipt, a FAIL, or a missing END marker all
# REFUSE. Unattended boot-enable is a separate tier-2 step (repeat/overnight pass
# AND the 2026-05-23 reset cause understood) — this only clears ATTENDED runtime.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$REPO_DIR/scripts/darkplaces-soak.py" promote "$@"
