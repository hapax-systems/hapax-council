# LLM Stack Backup Reconciliation

The standalone `llm-backup` lane is deprecated. It is retained only as a
compatibility receipt so legacy timer invocations cannot run stale backup logic
or create misleading artifacts.

## Canonical Backup Lanes

Tier 1 local coverage:

- Timer: `hapax-backup-local.timer`
- Service: `hapax-backup-local.service`
- Script: `scripts/hapax-backup-local`, run from the activation worktree (`~/.cache/hapax/source-activation/worktree`); recheck with `systemctl --user show hapax-backup-local.service -p ExecStart`
- Restic repository: `/mnt/nas/backups/restic`
- Staging: `/store/llm-data/backup-dumps-local` (tier 2: `/store/llm-data/backup-dumps-remote`); recheck with `ls -d /store/llm-data/backup-dumps-*` during a run

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

## FileStore (Secrets) Custody

Since the 2026-09-16 migration, the estate's secrets live in each host's
`hapax-secret` FileStore: `~/.config/reins/secrets/`, the `.key` plus one
`.bin` per entry (`a/b` is stored as `a-b.bin`). Key and blobs travel together
inside the encrypted restic repositories, like `~/.password-store/` and
`~/.gnupg/`.

- Podium: in the tier-1 local (NAS) and tier-2 remote (B2) snapshots
  (`scripts/hapax-backup-{local,remote}`).
- Every other host running a store: `hapax-backup-filestore.{service,timer}`
  writes it to the tier-1 NAS repository with tag `tier1-filestore` and
  `--host <host>`, then verifies the new snapshot by path listing: the `.key`,
  and every `.bin` entry the store holds, by name. Retention is podium's
  tier-1 forget (`--group-by host,tags`).
- Recheck, names only: on the host, `scripts/hapax-backup-filestore --verify`
  (from the activation worktree, with `RESTIC_REPOSITORY` set) re-checks its
  latest `tier1-filestore` snapshot against the store by name and writes
  nothing. By hand, find the snapshot with
  `restic snapshots --tag tier1-filestore --host <host>`, then compare names:
  `comm -23 <(ls ~/.config/reins/secrets | grep '\.bin$' | sort) <(restic ls <snapshot-id> | grep -oE '[^/]+\.bin$' | sort)`
  prints every store entry the snapshot lacks; empty output means all are
  present.

Restore order: **the FileStore comes back before any service that reads a
secret starts** (the backup units, logos-api, anything calling `hapax-secret`).

1. From the snapshot for the host, restore `~/.config/reins/secrets/` (the
   `.key` and every `.bin`) into place: `restic restore <snapshot-id> --target /
   --include "$HOME/.config/reins/secrets"`, or copy it out of a staging tree.
2. Set the modes: `chmod 700 ~/.config/reins/secrets` and `chmod 600` on every
   file in it.
3. Check the entries by name, never by value, for example
   `hapax-secret --where backups/restic-password` prints `filestore`.
4. Only then start the services.

The hand-made preservation tarballs
`/mnt/nas/archive/hapax-preservation/secret-store/reins-secrets-20260829.tar.gpg`
and `reins-secrets-20260902.tar.gpg` are **superseded, not deleted**. They
predate the migration and are kept as history; the scheduled snapshots above
are the current copies.
