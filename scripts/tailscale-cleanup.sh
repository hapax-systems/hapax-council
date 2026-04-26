#!/usr/bin/env bash
# tailscale-cleanup.sh — remove devices offline longer than $1 days from operator's tailnet.
#
# Usage: tailscale-cleanup.sh [days] [--dry-run]
#   days     threshold (default 90)
#   --dry-run  log what would be deleted, do not call DELETE
#
# Auth: reads ~/.password-store/tailscale/api-key (Bearer token).
# API:  https://tailscale.com/kb/1101/api  (uses GET /tailnet/-/devices then DELETE /device/{id}).
#
# Surfaced by 8-hour audit B3 P0-2 (script referenced by tailscale-cleanup.service was missing).
# Service + timer at systemd/units/tailscale-cleanup.{service,timer}; timer fires Sun 03:30 weekly.

set -euo pipefail

THRESHOLD_DAYS="${1:-90}"
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in --dry-run) DRY_RUN=1 ;; esac
done

API_BASE="https://api.tailscale.com/api/v2"
TAILNET="-"  # `-` resolves to the auth-key's default tailnet

if ! command -v jq >/dev/null 2>&1; then
  echo "tailscale-cleanup: jq is required but missing" >&2
  exit 2
fi
if ! command -v pass >/dev/null 2>&1; then
  echo "tailscale-cleanup: pass is required but missing" >&2
  exit 2
fi

API_KEY="$(pass tailscale/api-key 2>/dev/null || true)"
if [[ -z "$API_KEY" ]]; then
  echo "tailscale-cleanup: no api-key in pass store at tailscale/api-key — aborting" >&2
  exit 3
fi

cutoff_epoch="$(date -d "${THRESHOLD_DAYS} days ago" +%s)"
echo "tailscale-cleanup: cutoff = $(date -d "@${cutoff_epoch}" -Iseconds) (threshold ${THRESHOLD_DAYS}d, dry_run=${DRY_RUN})"

devices_json="$(curl -fsSL -H "Authorization: Bearer ${API_KEY}" "${API_BASE}/tailnet/${TAILNET}/devices")"

stale_count=0
deleted_count=0
errors=0
total="$(jq '.devices | length' <<<"$devices_json")"

while IFS=$'\t' read -r id name last_seen; do
  [[ -z "$id" ]] && continue
  last_seen_epoch="$(date -d "${last_seen}" +%s 2>/dev/null || echo 0)"
  if (( last_seen_epoch == 0 )); then
    echo "tailscale-cleanup: skip ${name} (id=${id}) — unparseable lastSeen=${last_seen}"
    continue
  fi
  if (( last_seen_epoch < cutoff_epoch )); then
    stale_count=$((stale_count + 1))
    age_days=$(( (cutoff_epoch - last_seen_epoch) / 86400 + THRESHOLD_DAYS ))
    if (( DRY_RUN )); then
      echo "tailscale-cleanup: [dry-run] would delete ${name} (id=${id}, last_seen=${last_seen}, age=${age_days}d)"
    else
      if curl -fsSL -X DELETE -H "Authorization: Bearer ${API_KEY}" "${API_BASE}/device/${id}" -o /dev/null; then
        deleted_count=$((deleted_count + 1))
        echo "tailscale-cleanup: deleted ${name} (id=${id}, age=${age_days}d)"
      else
        errors=$((errors + 1))
        echo "tailscale-cleanup: ERROR deleting ${name} (id=${id})" >&2
      fi
    fi
  fi
done < <(jq -r '.devices[] | "\(.id)\t\(.name)\t\(.lastSeen)"' <<<"$devices_json")

echo "tailscale-cleanup: scanned=${total} stale=${stale_count} deleted=${deleted_count} errors=${errors}"
exit "$([[ $errors -gt 0 ]] && echo 1 || echo 0)"
