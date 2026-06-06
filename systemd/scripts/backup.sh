#!/usr/bin/env bash
# backup.sh - Deprecated llm-backup compatibility receipt.
#
# The old standalone LLM-stack backup path has been retired. It overlapped with
# the service-native Tier 1/GDrive-critical backup lanes and carried stale PostgreSQL
# assumptions. Keep this entry point side-effect-light so legacy timers or
# manual invocations cannot create misleading backup artifacts.

set -euo pipefail

log() { echo "[llm-backup] $*"; }

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    cat <<'EOF'
llm-backup is deprecated.

Canonical backup lanes:
  systemctl --user start hapax-backup-local.service
  systemctl --user start hapax-backup-gdrive-critical.service

Restore/runbook:
  docs/runbooks/llm-stack-backup-reconciliation.md
EOF
    exit 0
fi

if [[ $# -gt 0 ]]; then
    log "Ignoring legacy backup target argument: $1"
fi

log "DEPRECATED: standalone LLM-stack backup is retired."
log "No backup artifacts were written by this compatibility receipt."
log "Use hapax-backup-local.service for Tier 1 NAS restic coverage."
log "Use hapax-backup-gdrive-critical.service for bounded offsite GDrive coverage."
log "Backblaze B2 broad remote backup is retired as a required routine lane."
log "Restore path: docs/runbooks/llm-stack-backup-reconciliation.md"
