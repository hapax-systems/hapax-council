# shellcheck shell=bash
# tier1-snapshot.sh — the one way to name "the newest tier-1 snapshot" of the NAS repository.
#
# The NAS repository (/mnt/nas/backups/restic) holds more than podium's tier-1 job: hapax-monocle's
# monocle-daily snapshots, and since 2026-09-27 each host's tier1-transcripts snapshots
# (hapax-backup-transcripts). A bare `restic ls latest` / `restic dump latest` picks the newest snapshot of
# ANY host and tag. Witnessed 2026-09-27 02:14Z: hapax-backup-gdrive-critical then read a transcript
# snapshot and failed with "Tier-1 latest snapshot contains no postgres-all.sql", and the watchdog's
# freshness check would have counted a transcript snapshot as a fresh tier-1 backup.
#
# Usage (with RESTIC_REPOSITORY and RESTIC_PASSWORD in the environment of the call):
#   id="$(tier1_latest_snapshot_id)"   # empty when no tier-1 snapshot exists
#   tier1_latest_snapshot_time         # its RFC 3339 time, or empty
# Overrides: HAPAX_TIER1_HOST (default hapax-podium), HAPAX_TIER1_TAG (default tier1-local).

TIER1_HOST="${HAPAX_TIER1_HOST:-hapax-podium}"
TIER1_TAG="${HAPAX_TIER1_TAG:-tier1-local}"

_tier1_newest() {
    local field="$1"
    restic snapshots --no-lock --json --host "$TIER1_HOST" --tag "$TIER1_TAG" 2>/dev/null \
        | jq -r "max_by(.time).${field} // empty" 2>/dev/null
}

tier1_latest_snapshot_id() {
    _tier1_newest id
}

tier1_latest_snapshot_time() {
    _tier1_newest time
}
