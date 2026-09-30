# WSL transcript custody

The Windows puller inventories `%USERPROFILE%`; that does not include a WSL distribution's Linux home.
Run the existing transcript CLI inside the distribution with `backup --capture`, followed by `verify`.
The capture uses the shared path table, including `.glmcp-claude`, rejects dangling or nested symlinks and
empty sources, excludes credential basenames and their backup variants, and captures SQLite through the
online backup API. Every regular file is hashed before backup and checked again through `restic dump`.
The existing count, missing-path and drop checks apply to the reconstructed capture listing.

`systemd/units/hapax-backup-transcripts-wsl.{service,timer}` binds Ubuntu 24.04 on dextra to the existing
encrypted NAS repository over pinned SSH/SFTP. Its host identity is `hapax-dextra-wsl-ubuntu24.04`, which
distinguishes the distro and the new capture format from the retained one-off `hapax-dextra-wsl` archive.
The first enrollment must reconcile its counts with that earlier archive; subsequent checks compare
captured paths and counts against the preceding snapshot. Both carry the never-pruned `tier1-transcripts`
tag. There is no forget/prune action in this service.

Install only from a merged, independently accepted council commit through the target's governed
source-activation binding, `%h/.cache/hapax/source-activation/worktree`. Preserve the previous
commit-addressed release. This service uses only Python's standard library, restic and the existing
`hapax-secret` forwarding interface; no reins key is copied. On WSL, use a bounded source-activation
profile instead of deploying appendix's unrelated services. A candidate checkout is not an active
release. Do not enable the timer until the active source root and installed units have matching
commit/hash receipts, pinned appendix SSH authentication works, and a manual custody run passes.

Recheck the installed source, units, scheduling and snapshot from dextra's Ubuntu distribution:

```bash
readlink -f ~/.cache/hapax/source-activation/worktree
git -C ~/.cache/hapax/source-activation/worktree rev-parse HEAD
sha256sum ~/.cache/hapax/source-activation/worktree/scripts/{hapax-transcript-custody,transcript_custody.py}
sha256sum ~/.config/systemd/user/hapax-backup-transcripts-wsl.{service,timer}
systemctl --user cat hapax-backup-transcripts-wsl.service
systemctl --user start hapax-backup-transcripts-wsl.service
systemctl --user show hapax-backup-transcripts-wsl.service -p Result -p ExecMainStatus
systemctl --user list-timers hapax-backup-transcripts-wsl.timer
journalctl --user -u hapax-backup-transcripts-wsl.service --since today --no-pager
RESTIC_REPOSITORY=sftp:hapax-appendix:/mnt/nas/backups/restic \
  python3 ~/.cache/hapax/source-activation/worktree/scripts/hapax-transcript-custody verify
restic -r sftp:hapax-appendix:/mnt/nas/backups/restic \
  --password-command 'hapax-secret backups/restic-password' snapshots \
  --host hapax-dextra-wsl-ubuntu24.04 --tag tier1-transcripts
```

Record the exact snapshot ID from that successful run. Independently run `restic dump SNAPSHOT
/transcripts-consistent.tar` from appendix's NAS repository, verify its manifest with
`transcript_custody.read_capture`, restore the Codex SQLite member into a new private directory and
run `PRAGMA quick_check`. A transport failure, truncated archive, hash/count drop or failed database
check leaves custody unaccepted; inspect the private failure receipt and repeat a new capture after
repairing the named source or link. Record the actual restored-file observations beside the installed
commit and unit hashes. Runtime acceptance is separate from this PR's source acceptance; the parent
hearth commission also includes device recovery and hardware acceptance and remains open.

The timer runs while WSL's user manager runs. It does not wake Windows or start an otherwise stopped
distribution. Surface a stopped or sleeping seat as unobserved; the Windows puller's separate 72-hour
bound is unchanged. Preserve the previous release and snapshots for rollback. Disabling this timer and
restoring the previous `current` link must not delete any custody snapshot.

A live `wsl --export` interrupted dextra's running sessions on September 29. Do not use an export as this
recurring producer. A system recovery export needs an explicitly idle or stopped distribution. Validate
an existing export offline and import it under a different name with systemd, boot commands, interop and
automatic host mounts disabled before the first test boot. Preserve failed receipts; a process exit code
without the resulting VHDX and restored-file observations is not an import test.
