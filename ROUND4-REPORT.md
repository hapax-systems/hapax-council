# PR #4623 round 4 report

Worktree: `feat/backup-scripts-into-council-20260902` at base `c98af079c`.
No commit, branch, push, stash, `cc-*` command, or secret access was performed.

## Criticals

### 1. FIXED (finding confirmed; not rebutted) — activation/deploy ordering

The governed activation path does promote before it deploys. Evidence from
`~/.local/bin/hapax-source-activate`:

```text
1550 promote_active_worktree "$candidate_worktree"
1876 write_receipt "deploying" "in_progress" "0" "active source promoted; post-merge deploy starting"
1891 (
1892     cd "$ACTIVE_WORKTREE"
1893     REPO="$ACTIVE_WORKTREE" "$DEPLOY_SCRIPT" "${deploy_args[@]}"
```

However, the requested rebuttal is not valid because another automatic path
exists. `systemd/units/hapax-post-merge-deploy.path:47-49` watches the local main
ref, and `systemd/units/hapax-post-merge-deploy.service:32-40` independently
resolves `origin/main` and runs the installed post-merge deploy helper. That
path can install units from the new SHA before source activation has promoted
its worktree.

The affected backup units now pull in and order themselves after
`hapax-source-activate.service`, then use an `ExecCondition` that requires the
activation receipt's `active_source_head` to equal `origin_main_sha` and its
status to be a successful terminal state before the source-controlled
`ExecStart` can run:

- `systemd/units/hapax-backup-local.service:3-13`
- `systemd/units/hapax-backup-remote.service:3-12`
- behavioral stale/current receipt test:
  `tests/systemd/test_llm_backup_reconciliation.py:114`

Thus the independent installer is acknowledged rather than rebutted, while a
newly installed backup unit cannot execute an absent/stale activation-worktree
script. A held or failed activation makes the condition skip the backup.

### 2. FIXED — PostgreSQL duplicate bootstrap role/database

`scripts/hapax-cachyos-restore:54,227-273` now streams the real `pg_dumpall`
file through a narrow filter. It removes only `CREATE ROLE` for the fresh
cluster's initialization superuser and `CREATE DATABASE` for its already-created
initial database. It retains their `ALTER`/`\\connect` statements and all other
roles, databases, schema, and data, then imports with `psql -v ON_ERROR_STOP=1`.

`tests/scripts/test_hapax_cachyos_restore.py:201` sends a realistic prologue
containing `CREATE ROLE hapax;`, `CREATE DATABASE hapax ...`, another role,
another database, `ALTER`, `\\connect`, and schema through the real helper path.
Its mocked `psql` fails if either duplicate bootstrap creation reaches it.

Mutation check:

- Mutated the role filter so `CREATE ROLE hapax;` reached mocked `psql`.
- Focused test result: `1 failed, 10 deselected`; stderr contained
  `ERROR: bootstrap role or database already exists`; exit `1`.
- Restored the filter and reran: `1 passed, 10 deselected`; exit `0`.

### 3. FIXED — canonical bare-metal storage roots

The single canonical backup-policy table now declares `/store` and `/mnt/nas`
for Tier 1 and `/store` for B2 at
`config/infrastructure/host-storage-registry.json:12-16,58-60`.

`scripts/hapax-cachyos-restore:64-127,839-908` reads and validates those roots,
creates/mounts each one, and exits with the root and a next action when creation
or mounting fails. Phase 11 now provisions `/store` rather than partitioning for
the obsolete restore-time `/data` layout. Phase 14 derives the Tier 1 repository
from the registry-selected `/mnt/nas` root at
`scripts/hapax-cachyos-restore:1032-1050`; it no longer initializes
`/data/backups/restic`.

The B2 recovery lane uploads the registry beside the restore script at
`scripts/hapax-backup-remote:223-249`, and the standalone recovery instructions
name both objects. Fake-root coverage is at
`tests/scripts/test_hapax_cachyos_restore.py:378,394`: it mounts fake `/store`
and `/mnt/nas`, asserts no fake `/data`, and verifies an unmountable `/mnt/nas`
fails loudly naming that root.

## Majors and runbook findings

- FIXED — producer harness failure branches:
  `tests/scripts/backup_test_support.py:21-188` now drives Qdrant list/empty/
  invalid/snapshot-create/invalid-response/download failures; n8n export/copy/
  empty-output failures; PostgreSQL exit/missing-terminator/undersize failures;
  restic backup/retention failures; and both B2 recovery-object upload failures.
  Assertions that each producer fails before later stages are in
  `tests/scripts/test_hapax_backup_local.py:21-98` and
  `tests/scripts/test_hapax_backup_remote.py:21-129`.
- FIXED — the B2 watchdog paths are executed, not matched as source text:
  `tests/scripts/test_hapax_backup_watchdog.py:107-198` runs stale,
  inaccessible, corrupt, and dump-less B2 cases and requires each to fail with
  the correct diagnosis. The script header now describes B2, and test-only path
  overrides permit isolated execution (`scripts/hapax-backup-watchdog:4-24`).
- FIXED — fatal PostgreSQL producer messages include actionable recovery steps
  (`scripts/hapax-backup-local:99-108`,
  `scripts/hapax-backup-remote:91-100`); remote recovery-object upload failures
  do likewise (`scripts/hapax-backup-remote:233-247`).
- FIXED — direct DR-object reconciliation commands compare both remote objects
  byte-for-byte at `docs/runbooks/llm-stack-backup-reconciliation.md:106-111`.
- FIXED — the runbook no longer treats static checks as deployed-runtime
  evidence. `docs/runbooks/llm-stack-backup-reconciliation.md:114-124` leaves
  that clause pending until merge/governed activation and requires the actual
  active-source, loaded-unit (including `ExecCondition`), timer, and journal
  output in the PR/task receipt. No pre-merge runtime-success claim was made.

## Verification

Required pytest set plus the new tests:

```text
475 passed, 2 skipped, 2 warnings in 13.44s
exit 0
```

The warnings were two existing Qdrant client version-probe warnings. LiteLLM
also reported that the sandbox could not fetch its optional remote model-price
map and used its local backup.

Python checks on all six touched Python test/support files:

```text
ruff format --check: 6 files already formatted
ruff check: All checks passed!
```

Shell and diff checks:

```text
bash -n scripts/hapax-backup-local scripts/hapax-backup-remote \
  scripts/hapax-backup-watchdog scripts/hapax-cachyos-restore
exit 0

git diff --check
exit 0
```

`shellcheck` is not installed in this environment.

Additional unit validation:

```text
systemd-analyze --user verify systemd/units/hapax-backup-local.service \
  systemd/units/hapax-backup-remote.service
Failed to turn off SO_PASSRIGHTS on user lookup socket, ignoring: Operation not permitted
Failed to enable SO_PASSCRED on handoff timestamp socket: Operation not permitted
exit 1
```

This sandbox limitation produced no unit-file diagnostic. The pytest unit parser
and the executed `ExecCondition` behavior test both passed in the required
suite.

## Final `git status --short`

```text
 M config/infrastructure/host-storage-registry.json
 M docs/runbooks/llm-stack-backup-reconciliation.md
 M scripts/hapax-backup-local
 M scripts/hapax-backup-remote
 M scripts/hapax-backup-watchdog
 M scripts/hapax-cachyos-restore
 M systemd/units/hapax-backup-local.service
 M systemd/units/hapax-backup-remote.service
 M tests/scripts/backup_test_support.py
 M tests/scripts/test_hapax_backup_local.py
 M tests/scripts/test_hapax_backup_remote.py
 M tests/scripts/test_hapax_backup_watchdog.py
 M tests/scripts/test_hapax_cachyos_restore.py
 M tests/systemd/test_llm_backup_reconciliation.py
?? ACTIVATION-NOTE.md
?? ROUND4-REPORT.md
```

`ROUND4-REPORT.md` is a scratch file and was not staged. The pre-existing
untracked `ACTIVATION-NOTE.md` was left untouched.
