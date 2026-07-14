# Review-Team Digest Migration

This runbook is the operational path for the one-shot legacy review-team
acceptance migration guarded by
`REVIEW_TEAM_DIGEST_MIGRATION_SOURCE_TRUST_ANCHOR` in
`shared/sdlc_lifecycle.py`.

## Preconditions

- Pause automatic review and autoqueue effects before any write:
  `systemctl --user stop hapax-pr-review-dispatch.timer hapax-pr-review-dispatch.service hapax-cc-pr-autoqueue.timer hapax-cc-pr-autoqueue.service`
- Prove the exact four deployed units are loaded and inactive, with each `Id`
  matching the requested unit name:
  `systemctl --user show hapax-pr-review-dispatch.timer hapax-pr-review-dispatch.service hapax-cc-pr-autoqueue.timer hapax-cc-pr-autoqueue.service --property=Id --property=LoadState --property=ActiveState --no-pager`
- Set the dispatcher killswitch while investigating or holding:
  `export HAPAX_REVIEW_TEAM_DISPATCH_OFF=1`
- Preserve any existing `_locks/review-team/*.lock` and
  `_locks/review-team-digest-migration.lock` files as evidence.

## Dry-Run Recheck

Use the providerless recheck first. It validates the source-pinned authority
tuple, proposal/carrier bytes, sealed artifact immutability, current receipt
drift, and before/after artifact hash without GitHub, reviewers, comments,
artifact writes, temp files, migration claims, or `_locks` directory creation.

```bash
uv run python scripts/cc-pr-review-dispatch.py --all --replay-only --migration-recheck \
  --migration-authority-proposal /path/to/ratified-proposal.yaml \
  --migration-authority-proposal-sha256 <64-hex> \
  --migration-consumed-act-carrier /path/to/consumed-carrier.yaml \
  --migration-consumed-act-carrier-sha256 <64-hex>
```

Require `status: migration_recheck_ready`, `pause_preconditions.unit_pause.validated:
true`, every unit entry to show matching `id`, `load_state: loaded`, and
`active_state: inactive`, and a populated `migration.acceptance_admission_trace`.
For an existing sealed artifact, require `migration.status: migration_unchanged`
and identical `before_artifact_sha256` / `after_artifact_sha256`.

## Apply

Only after the dry-run is clean and all four units still report
`LoadState=loaded` and `ActiveState=inactive`, capture current artifact bytes
and hash if the artifact exists:

```bash
cp ~/Documents/Personal/20-projects/hapax-cc-tasks/active/_review-team-digest-migration.yaml \
  /tmp/review-team-digest-migration.pre-apply.yaml
sha256sum /tmp/review-team-digest-migration.pre-apply.yaml
```

The foreground apply must be an explicit transition out of HOLD:

```bash
unset HAPAX_REVIEW_TEAM_DISPATCH_OFF
```

Then run:

```bash
uv run python scripts/cc-pr-review-dispatch.py --all --apply --replay-only \
  --migration-authority-proposal /path/to/ratified-proposal.yaml \
  --migration-authority-proposal-sha256 <64-hex> \
  --migration-consumed-act-carrier /path/to/consumed-carrier.yaml \
  --migration-consumed-act-carrier-sha256 <64-hex>
```

A valid pre-existing sealed artifact is immutable. Empty, partial, removed, or
forged seal mappings are blockers, not an unsealed legacy artifact. The only
replaceable unsealed artifact is the exact source-pinned legacy preimage named
by `legacy_unsealed_artifact_sha256` in the reviewed source trust anchor. Reruns
may rebind current open receipts from current dossiers, but must never rewrite,
shrink, expand, or replace `_review-team-digest-migration.yaml`. After apply,
rerun the providerless recheck with the killswitch set again and compare
before/after hashes:

```bash
export HAPAX_REVIEW_TEAM_DISPATCH_OFF=1
sha256sum ~/Documents/Personal/20-projects/hapax-cc-tasks/active/_review-team-digest-migration.yaml
```

## Recovery

There is no manual lifecycle-admission bypass. Missing or tampered migration
authority is recovered only by restoring the exact source-pinned proposal,
carrier, legacy preimage, and sealed artifact bytes, or by fresh authoritative
re-review.
Post-merge closure bookkeeping does not validate, repair, or bypass migration
authority and must not be cited as migration admission.

Malformed review claims remain HOLD until holder identity/liveness evidence is
preserved. Only stale same-host claims with exact dead-or-reused PID/proc-start
proof are archive-releasable. Unavailable storage must name the exact lock
probe failure. Use the no-provider probe before retrying unavailable lock
storage:

```bash
uv run python scripts/cc-pr-review-dispatch.py --pr <pr> --probe-lock
```

Rollback is to restore the saved artifact bytes and keep all four units stopped
with the killswitch in HOLD:

```bash
export HAPAX_REVIEW_TEAM_DISPATCH_OFF=1
systemctl --user stop hapax-pr-review-dispatch.timer hapax-pr-review-dispatch.service hapax-cc-pr-autoqueue.timer hapax-cc-pr-autoqueue.service
cp /tmp/review-team-digest-migration.pre-apply.yaml \
  ~/Documents/Personal/20-projects/hapax-cc-tasks/active/_review-team-digest-migration.yaml
```

Do not restart timers until lifecycle validation and the providerless recheck
are clean.
