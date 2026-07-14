# Review-Team Digest Migration

This runbook is the operational path for the one-shot legacy review-team
acceptance migration guarded by
`REVIEW_TEAM_DIGEST_MIGRATION_SOURCE_TRUST_ANCHOR` in
`shared/sdlc_lifecycle.py`.

## Preconditions

- Pause automatic review and autoqueue effects before any write:
  `systemctl --user stop hapax-pr-review-dispatch.timer cc-pr-autoqueue.timer`
- Set the dispatcher killswitch while investigating or holding:
  `export HAPAX_REVIEW_TEAM_DISPATCH_OFF=1`
- Preserve any existing `_locks/review-team/*.lock` and
  `_locks/review-team-digest-migration.lock` files as evidence.

## Dry-Run Recheck

Use the providerless recheck first. It validates the source-pinned authority
tuple, proposal/carrier bytes, sealed artifact immutability, current receipt
drift, and before/after artifact hash without GitHub, reviewers, comments, or
artifact writes.

```bash
uv run python scripts/cc-pr-review-dispatch.py --all --replay-only --migration-recheck \
  --migration-authority-proposal /path/to/ratified-proposal.yaml \
  --migration-authority-proposal-sha256 <64-hex> \
  --migration-consumed-act-carrier /path/to/consumed-carrier.yaml \
  --migration-consumed-act-carrier-sha256 <64-hex>
```

Require `status: migration_recheck_ready`. For an existing sealed artifact,
require `migration.status: migration_unchanged` and identical
`before_artifact_sha256` / `after_artifact_sha256`.

## Apply

Only after the dry-run is clean and timers remain paused:

```bash
uv run python scripts/cc-pr-review-dispatch.py --all --apply --replay-only \
  --migration-authority-proposal /path/to/ratified-proposal.yaml \
  --migration-authority-proposal-sha256 <64-hex> \
  --migration-consumed-act-carrier /path/to/consumed-carrier.yaml \
  --migration-consumed-act-carrier-sha256 <64-hex>
```

A valid pre-existing sealed artifact is immutable. Reruns may rebind current
open receipts from current dossiers, but must never rewrite, shrink, expand, or
replace `_review-team-digest-migration.yaml`.

## Recovery

There is no manual lifecycle-admission bypass. Missing or tampered migration
authority is recovered only by restoring the exact source-pinned proposal,
carrier, and sealed artifact bytes, or by fresh authoritative re-review.

Malformed review claims remain HOLD until holder identity/liveness evidence is
preserved. Use the no-provider probe before retrying unavailable lock storage:

```bash
uv run python scripts/cc-pr-review-dispatch.py --pr <pr> --probe-lock
```

Rollback is to restore the saved artifact bytes and keep timers/killswitch in
HOLD until lifecycle validation and the providerless recheck are clean.
