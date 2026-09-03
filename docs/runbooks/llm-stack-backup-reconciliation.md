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

- Timer: `hapax-backup-critical-offsite.timer`
- Service: `hapax-backup-critical-offsite.service`
- Script: `%h/.cache/hapax/source-activation/worktree/scripts/hapax-backup-critical-offsite`
  (the governed activation worktree; the source is `scripts/hapax-backup-critical-offsite`)
- Restic repository: `rclone:r2:hapax-restic-critical`
- Cache: `/store/llm-data/restic-cache/critical-offsite`

The critical off-site lane is the bounded critical-artifact baseline in
Cloudflare R2. It backs up already-materialized Postgres PITR artifacts, latest
Qdrant snapshot files, and selected vault evidence/SOP files. It does not create
new Qdrant snapshots, dump databases into `/tmp`, upload live MinIO backing
stores, or run destructive prune. Retention is `--retention-dry-run` only unless
a later governed task changes policy.

The broad Backblaze B2 remote backup is not part of this lane. It was retired by
operator policy on 2026-06-06 (registry `b2-restic-offsite`: retired), and its
return as a daily `hapax-backup-remote.timer` is a separate change,
`backup-scripts-into-council-20260902` (#4623), which carries the timer, the unit,
the manifest and the registry row together. The repository `b2:hapax-backups/restic`
still holds the snapshots the retired lane wrote; restoring from it works as
documented below, but nothing on this branch writes to it.

## Cutover on podium (2026-09-02)

The unit runs its script from the governed source-activation worktree
(`~/.cache/hapax/source-activation/worktree`), never from a development
checkout. On podium that worktree is deliberately HELD by the operator
(`~/.cache/hapax/source-activation/HOLD`, 2026-08-18: podium source activation is
an operator ratify-line), so it will not carry this unit's script until the hold
is released. Two steps, in order:

1. Release the hold (an operator ratify-line, not a script's decision): remove
   `~/.cache/hapax/source-activation/HOLD`, let `hapax-source-activate.timer`
   bring the worktree to main, and confirm with
   `git -C ~/.cache/hapax/source-activation/worktree log -1 --oneline`.
2. Let the governed deploy install the units. `hapax-source-activate` installs every
   merged unit, conf and script itself as part of the deploy (it does not call
   `systemd/scripts/install-units.sh`, which refuses to run from anything but the
   primary checkout). Do not hand-create symlinks and do not run the installer from
   any worktree. What remains is retiring the old unit and its drop-ins, then
   enabling the new timer:

```bash
systemctl --user disable --now hapax-backup-gdrive-critical.timer
rm -rf ~/.config/systemd/user/hapax-backup-gdrive-critical.service.d ~/.config/systemd/user/hapax-backup-watchdog.service.d/20-r2.conf
rm -f ~/.config/systemd/user/hapax-backup-gdrive-critical.{service,timer}
systemctl --user daemon-reload && systemctl --user enable --now hapax-backup-critical-offsite.timer
systemctl --user show hapax-backup-critical-offsite.service -p FragmentPath -p ExecStart
```

Until step 1 happens, the R2 lane keeps running under the secret-free
`20-r2.conf` drop-ins that carried the 2026-09-02 switch (they name pass entries,
never values); step 2 removes them.

The `rclone:gdrive:` remote and the Drive restic repository at
`rclone:gdrive:hapax-backups/restic-critical` are retired. Snapshots carrying
the old `gdrive-critical` tag exist only in that dead Drive repository; the R2
repository uses `critical-offsite` tags.

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

The broad Backblaze B2 remote backup is retired on this branch (its return is
#4623); this compatibility receipt does not invoke it.

This intentionally removes the stale standalone script assumptions:

- No per-database `pg_dump` list.
- No `postgres` database user assumption.
- No obsolete `ragdb` database assumption.
- No hot raw capture of live service data directories.

## Restore Path

1. Restore the chosen restic snapshot from the Tier 1 local repo or the critical
   off-site R2 repo into a staging directory.
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
