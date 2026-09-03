# LLM Stack Backup Reconciliation

The standalone `llm-backup` lane is deprecated. It is retained only as a
compatibility receipt so legacy timer invocations cannot run stale backup logic
or create misleading artifacts.

## Canonical Backup Lanes

Tier 1 local coverage:

- Timer: `hapax-backup-local.timer`
- Service: `hapax-backup-local.service`
- Script: `%h/.cache/hapax/source-activation/worktree/scripts/hapax-backup-local`
- Restic repository: `/mnt/nas/backups/restic`
- Staging: `/store/llm-data/backup-dumps-local`

Tier 2 Backblaze B2 coverage:

- Timer: `hapax-backup-remote.timer` (daily at 03:30 with randomized delay)
- Service: `hapax-backup-remote.service`
- Script: `%h/.cache/hapax/source-activation/worktree/scripts/hapax-backup-remote`
- Restic repository: `rclone:b2:hapax-backups/restic`
- Staging: `/store/llm-data/backup-dumps-remote`
- Recovery bootstrap object: `b2:hapax-backups/dr-scripts/hapax-cachyos-restore.sh`
- Recovery storage registry: `b2:hapax-backups/dr-scripts/host-storage-registry.json`

The operator reinstated B2 as a live daily offsite lane on 2026-09-02. It
creates its own database and workflow exports and does not consume Tier 1's
staging directory. That is a separate *staging path*, not a separate failure
domain: both producers run on hapax-podium, stage under the same `/store`
filesystem, and depend on the same PostgreSQL, Qdrant, `pass` store and
source-activation tree, so a host-, store- or database-level fault stops both
on the same day. What is independent is the destination — the NAS repository
and the B2 repository fail separately — and the cross-host copy is the critical
off-site lane below.

Recheck the B2 lane's claims on podium:

```bash
systemctl --user list-timers hapax-backup-remote.timer --no-pager
systemctl --user status hapax-backup-remote.service --no-pager | head -5
export RESTIC_PASSWORD_COMMAND='pass show backblaze/restic-password'  # pragma: allowlist secret
restic -r rclone:b2:hapax-backups/restic snapshots --latest 1
~/.cache/hapax/source-activation/worktree/scripts/hapax-backup-watchdog 2>&1 | grep Tier2-B2
```

Critical offsite safety baseline:

- Timer: `hapax-backup-gdrive-critical.timer`
- Service: `hapax-backup-gdrive-critical.service`
- Script: `$HOME/projects/hapax-council/scripts/hapax-backup-gdrive-critical`
- Restic repository: `rclone:gdrive:hapax-backups/restic-critical`
- Cache: `/store/llm-data/restic-cache/gdrive-critical`

The GDrive critical lane is a complementary bounded critical-artifact offsite
baseline. It backs up already-materialized Postgres PITR artifacts, latest
Qdrant snapshot files, and selected vault evidence/SOP files. It does not
create new Qdrant snapshots, dump databases, upload live MinIO backing stores,
or run destructive prune. Retention is
`--retention-dry-run` only unless a later governed task changes policy.

The Tier 1 and B2 producer lanes stage service-native artifacts before restic
runs:

- PostgreSQL: `pg_dumpall` from the live `postgres` container with the current
  service user, written as `postgres-all.sql`. Bare-metal restore omits only
  the fresh cluster's pre-existing initialization-superuser `CREATE ROLE` and
  empty initialization-database `CREATE DATABASE` statements, then replays the
  remaining `ALTER`, `\connect`, schema/data, and other database statements
  with `ON_ERROR_STOP=1`.
- Qdrant: per-collection snapshots from the REST snapshot API.
- n8n: workflow export through the n8n container.
- Docker: volume inventory and inspect metadata for disaster recovery.
- Filesystem: the configured restic path set, including `$HOME/llm-stack/`.

## Deprecated Lane

`llm-backup.service` now calls the source-controlled
`systemd/scripts/backup.sh` compatibility receipt. That script exits
successfully, writes no backup artifacts, does not read secrets, and points at
the Tier 1/Tier 2 lanes above.

This intentionally removes the stale standalone script assumptions:

- No per-database `pg_dump` list.
- No `postgres` database user assumption.
- No obsolete `ragdb` database assumption.
- No hot raw capture of live service data directories.

## Restore Path

1. Restore the chosen restic snapshot from the Tier 1 local, B2, or GDrive
   critical repository into a staging directory.
2. Restore `$HOME/llm-stack/` configuration from the restored filesystem tree.
3. Restore PostgreSQL from the staged `postgres-all.sql` dump, or use the
   separately governed PITR lane when a point-in-time restore is required.
4. Restore Qdrant collections from the staged snapshots through the Qdrant
   snapshot restore flow.
5. Restore n8n workflows from the staged export if the service state was lost.
6. Recreate Docker volumes from the restored service configs and the captured
   volume metadata.
7. Verify backup freshness with `scripts/hapax-backup-watchdog`.

For bare-metal B2 recovery, download
`b2:hapax-backups/dr-scripts/hapax-cachyos-restore.sh` and its companion
`b2:hapax-backups/dr-scripts/host-storage-registry.json`. The script reads the
canonical `/store` and `/mnt/nas` requirements from that registry, refuses to
continue unless both roots are mount points, searches the restored
`/store/llm-data/backup-dumps-remote` and
`/store/llm-data/backup-dumps-local` paths, and exits non-zero if neither exists.

`scripts/hapax-restore-verify` remains available for historical standalone
`backup.sh` directory layouts. It is not the producer for the current
service-native lanes.

## Recheck

From the activated source root:

```bash
bash -n scripts/hapax-backup-local scripts/hapax-backup-remote scripts/hapax-cachyos-restore
shellcheck -S warning scripts/hapax-backup-local scripts/hapax-backup-remote scripts/hapax-cachyos-restore
uv run pytest -q tests/scripts/test_hapax_backup_local.py tests/scripts/test_hapax_backup_remote.py tests/scripts/test_hapax_cachyos_restore.py tests/systemd/test_llm_backup_reconciliation.py tests/test_infra_drift.py tests/test_agent_registry.py
systemd-analyze --user verify systemd/units/hapax-backup-local.service systemd/units/hapax-backup-remote.service
set -o pipefail
rclone cat b2:hapax-backups/dr-scripts/hapax-cachyos-restore.sh | cmp -s scripts/hapax-cachyos-restore -
rclone cat b2:hapax-backups/dr-scripts/host-storage-registry.json | cmp -s config/infrastructure/host-storage-registry.json -
```

The source checks above do not satisfy the deployed-runtime clause. At this PR
head that clause remains pending until after merge and governed source
activation; do not close the task or claim runtime success from static tests.
After activation completes, record the actual command output in the PR/task
receipt without reading credentials:

```bash
git -C ~/.cache/hapax/source-activation/worktree rev-parse HEAD
systemctl --user show hapax-backup-local.service hapax-backup-remote.service -p FragmentPath -p ExecCondition -p ExecStart -p Result -p ExecMainStatus
systemctl --user list-timers hapax-backup-local.timer hapax-backup-remote.timer
journalctl --user -u hapax-backup-local.service -u hapax-backup-remote.service --since today --no-pager
```
