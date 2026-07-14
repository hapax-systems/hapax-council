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
drift, before/after artifact hash, and a deterministic prepared-plan binding
without GitHub, reviewers, comments, artifact writes, temp files, migration
claims, or `_locks` directory creation. It also reports the existing migration
claim state as absent, active, stale, malformed, or unavailable; any non-absent
state is HOLD.

```bash
uv run python scripts/cc-pr-review-dispatch.py --all --replay-only --migration-recheck \
  --migration-authority-proposal /path/to/ratified-proposal.yaml \
  --migration-authority-proposal-sha256 <64-hex> \
  --migration-consumed-act-carrier /path/to/consumed-carrier.yaml \
  --migration-consumed-act-carrier-sha256 <64-hex>
```

Require `status: migration_recheck_ready`, `pause_preconditions.unit_pause.validated:
true`, every unit entry to show matching `id`, `load_state: loaded`, and
`active_state: inactive`. For an initial absent or unsealed artifact candidate,
require `migration.status: migration_ready`. For an existing sealed artifact,
require `migration.status: migration_unchanged`, identical
`before_artifact_sha256` / `after_artifact_sha256`, empty
`current_receipt_drift`, no `acceptance_trace_blockers`, and a populated
`migration.acceptance_admission_trace`. In both cases record
`migration.plan_binding.plan_sha256`,
`migration.plan_binding.disposition_manifest_sha256`,
`migration.plan_binding.write_set_sha256`, and
`migration.plan_binding.evidence_manifest_sha256`,
`migration.plan_binding.candidate_artifact_core_sha256`, and
`migration.plan_binding.candidate_authority_sha256`. Write
`migration.prepared_plan.raw_bytes_hex` byte-exactly to a durable prepared-plan
file and record its `migration.prepared_plan.file_sha256`. The later candidate
authority carrier must consume the exact
`migration.plan_binding.candidate_authority` body and use the exact
`migration.plan_binding.candidate_authority_response` text; the source
remediation act is not apply authority. The sealed artifact's persisted
`integrity_recheck` text must name the providerless `--migration-recheck`
command, not the applying replay command.

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

Then run only the exact candidate authorized by the later digest-binding act:

```bash
uv run python scripts/cc-pr-review-dispatch.py --all --apply --replay-only \
  --migration-authority-proposal /path/to/ratified-proposal.yaml \
  --migration-authority-proposal-sha256 <64-hex> \
  --migration-consumed-act-carrier /path/to/consumed-carrier.yaml \
  --migration-consumed-act-carrier-sha256 <64-hex> \
  --migration-prepared-plan /path/to/prepared-plan.json \
  --migration-prepared-plan-sha256 <64-hex> \
  --migration-candidate-authority-carrier /path/to/consumed-candidate-carrier.yaml \
  --migration-candidate-authority-carrier-sha256 <64-hex>
```

Every `--apply` invocation requires both the exact prepared-plan file/SHA-256
and the candidate-authority carrier, including an already-sealed or otherwise
no-op apply. `--apply` without them, or with a carrier whose candidate body,
frozen anchor, disposition manifest, write set, evidence manifest, prepared-plan
file digest, or plan digest differs from the prepared plan, is a blocker before
journal creation or target effects.

A valid pre-existing sealed artifact is immutable. Empty, partial, removed, or
forged seal mappings are blockers, not an unsealed legacy artifact. The only
replaceable unsealed artifact is the exact source-pinned legacy preimage named
by `legacy_unsealed_artifact_sha256` in the reviewed source trust anchor. Reruns
may rebind current open receipts from current dossiers through the exact
prepared write bytes only; apply must not recompute PR discovery, replay
classification, or acceptance semantics after a write. Acceptance admission is
checked from an in-memory overlay of the prepared outputs, not a temporary
copied vault. Immediately before the transaction, the complete evidence
manifest is compared again; any drift blocks before the first target effect.
The prepared plan binds a deterministic absent-to-owned migration-lock
transition, while the running apply records exact owned lock bytes and rechecks
them immediately before effects. Any lock byte, holder, stat, or hash drift is
a blocker before journal creation. The consumed candidate-authority carrier is
also bound by exact bytes/stat/hash evidence and rechecked at transaction entry;
any carrier drift is a blocker before journal creation. The transaction never
serializes mutable payload maps at effect time; missing prepared
`candidate_raw_bytes` is HOLD before journal, stage, archive, or target effects.
The transaction validates every target preimage against the prepared plan before
creating the journal. It then writes a same-filesystem initializing journal
under `_locks`, stages exact outputs and preimages, records preimage hashes and
archive paths, fsyncs phase changes, and rolls back or reports
`migration_recovery_required` on any archive, stage, journal, replace, fsync,
post-write verification, rollback, or recovery failure. After apply, rerun the
providerless recheck with the killswitch set again and compare before/after
hashes:

```bash
export HAPAX_REVIEW_TEAM_DISPATCH_OFF=1
sha256sum ~/Documents/Personal/20-projects/hapax-cc-tasks/active/_review-team-digest-migration.yaml
```

## Recovery

There is no manual lifecycle-admission bypass. Missing or tampered migration
authority or candidate authority is recovered only by restoring the exact
source-pinned proposal, source carrier, consumed candidate carrier, legacy
preimage, and sealed artifact bytes, or by fresh authoritative re-review.
Post-merge closure bookkeeping does not validate, repair, or bypass migration
authority and must not be cited as migration admission.

An existing `_locks/review-team-digest-migration.transaction.json` is HOLD for
fresh planning and unauthenticated apply. To recover, rerun `--apply` with the
same exact prepared-plan file/SHA-256 and consumed candidate-authority carrier.
Valid `initializing`, `prepared`, `applied:N`, `rollback_started`, and
`rollback_failed` phases recover by exact rollback; `complete` recovers by exact
roll-forward/finalization; `rolled_back` verifies rollback and finalizes. Do not
delete the journal to retry; preserve it with the staged files and recover or
escalate under a new governed act. An orphan stage path matching
`_locks/.review-team-digest-migration.transaction.*.files` is also HOLD even
when the journal is absent unless the exact journal-bound recovery path can
prove it belongs to the prepared plan.

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
