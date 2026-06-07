# LLM Stack Backup Reconciliation

The standalone `llm-backup` lane is deprecated. It is retained only as a
compatibility receipt so legacy timer invocations cannot run stale backup logic
or create misleading artifacts.

## Canonical Backup Lanes

Tier 1 local coverage:

- Timer: `hapax-backup-local.timer`
- Service: `hapax-backup-local.service`
- Script: `$HOME/projects/distro-work/hapax-backup-local.sh`
- Restic repository: `/mnt/nas/backups/restic`
- Staging: `/tmp/hapax-backup-dumps`

Critical offsite safety baseline:

- Timer: `hapax-backup-gdrive-critical.timer`
- Service: `hapax-backup-gdrive-critical.service`
- Script: `$HOME/projects/hapax-council/scripts/hapax-backup-gdrive-critical`
- Restic repository: `rclone:gdrive:hapax-backups/restic-critical`
- Cache: `/store/llm-data/restic-cache/gdrive-critical`

The GDrive critical lane is the bounded critical-artifact offsite baseline
after the broad Backblaze B2 remote lane was retired by operator policy on
2026-06-06. It backs up already-materialized Postgres PITR
artifacts, latest Qdrant snapshot files, and selected vault evidence/SOP files.
It does not create new Qdrant snapshots, dump databases into `/tmp`, upload live
MinIO backing stores, or run destructive prune. Retention is
`--retention-dry-run` only unless a later governed task changes policy.

Both lanes stage service-native artifacts before restic runs:

- PostgreSQL: `pg_dumpall` from the live `postgres` container with the current
  service user, written as `postgres-all.sql`.
- Qdrant: per-collection snapshots from the REST snapshot API.
- n8n: workflow export through the n8n container.
- Docker: volume inventory and inspect metadata for disaster recovery.
- Filesystem: the configured restic path set, including `$HOME/llm-stack/`.

## Deprecated Lane

`llm-backup.service` now calls the source-controlled
`systemd/scripts/backup.sh` compatibility receipt. That script exits
successfully, writes no backup artifacts, does not read secrets, and points at
the Tier 1/Tier 2 lanes above.

Backblaze B2 broad remote backup is retained only as historical context; no
`hapax-backup-remote.timer` should be installed, enabled, or expected by health
policy unless a later governed task reinstates it.

This intentionally removes the stale standalone script assumptions:

- No per-database `pg_dump` list.
- No `postgres` database user assumption.
- No obsolete `ragdb` database assumption.
- No hot raw capture of live service data directories.

## Restore Path

1. Restore the chosen restic snapshot from the Tier 1 local repo or the GDrive
   critical repo into a staging directory.
2. Restore `$HOME/llm-stack/` configuration from the restored filesystem tree.
3. Restore PostgreSQL from the staged `postgres-all.sql` dump, or use the
   separately governed PITR lane when a point-in-time restore is required.
4. Restore Qdrant collections from the staged snapshots through the Qdrant
   snapshot restore flow.
5. Restore n8n workflows from the staged export if the service state was lost.
6. Recreate Docker volumes from the restored service configs and the captured
   volume metadata.
7. Verify backup freshness with `scripts/hapax-backup-watchdog`.

`scripts/hapax-restore-verify` remains available for historical standalone
`backup.sh` directory layouts. It is not the producer for the current
service-native lanes.
