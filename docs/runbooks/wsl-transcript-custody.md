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

Install a reviewed, immutable subset under `~/.local/share/hapax/transcript-custody/releases/<commit>/`:
`scripts/hapax-transcript-custody`, `scripts/transcript_custody.py`, and `shared/secrets.py`, with their
package directories. Bind `current` to that release and install the two authored units. No reins key is
copied; `shared.secrets` uses the existing `hapax-secret` forwarding interface. The service's SSH alias
must already have a verified host key and noninteractive key authentication. Enable its user timer and
observe a successful manual start, snapshot listing and independently restored database. Record the
installed hashes and source commit; a symlink or enabled timer alone does not establish custody.

The timer runs while WSL's user manager runs. It does not wake Windows or start an otherwise stopped
distribution. Surface a stopped or sleeping seat as unobserved; the Windows puller's separate 72-hour
bound is unchanged. Preserve the previous release and snapshots for rollback. Disabling this timer and
restoring the previous `current` link must not delete any custody snapshot.

A live `wsl --export` interrupted dextra's running sessions on September 29. Do not use an export as this
recurring producer. A system recovery export needs an explicitly idle or stopped distribution. Validate
an existing export offline and import it under a different name with systemd, boot commands, interop and
automatic host mounts disabled before the first test boot. Preserve failed receipts; a process exit code
without the resulting VHDX and restored-file observations is not an import test.
