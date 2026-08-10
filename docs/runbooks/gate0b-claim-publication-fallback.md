# Gate-0B Claim Publication Fallback

Use this runbook only when the default `cc-claim` admitted publication path is
blocked and the operator explicitly authorizes a temporary legacy claim write.
Default mode is the repair target. The fallback does not produce an admitted
claim-publication receipt, so it must not satisfy admitted close or future
machine-authorizing paths.

## Default Recheck

Manual claims have a built-in producer. A hand-run default claim with no
dispatch flags issues a self-witnessed manual binding bound to the task
`authority_case`, claimer role, and session id. The sidecar keeps the installed
Gate-0B carrier route fields (`platform=codex`, `mode=headless`,
`profile=ultra`) and distinguishes manual provenance with
`manual-cc-claim:*` message/idempotency roots plus the self-witnessed binding
hash.

```bash
cc-claim <task-id>
```

First use on a host installs the Gate-0B claim-publication composition root for
the current `HOME` and then publishes the admitted claim. The install is
content-addressed and idempotent for exact matching files. A corrupt,
noncanonical, or mismatched receipt/manifest HOLDs; `cc-claim` does not
overwrite non-matching install artifacts.

Governed dispatch may still pass an explicit dispatch-issued binding:

```bash
HAPAX_CLAIM_DISPATCH_MESSAGE_ID='<dispatch-message-id>' \
HAPAX_CLAIM_DISPATCH_BINDING_HASH='<64-hex-binding-hash>' \
HAPAX_CLAIM_DISPATCH_PLATFORM='<platform>' \
HAPAX_CLAIM_DISPATCH_MODE='<mode>' \
HAPAX_CLAIM_DISPATCH_PROFILE='<profile>' \
HAPAX_CLAIM_DISPATCH_AUTHORITY_CASE='<authority-case>' \
HAPAX_CLAIM_DISPATCH_IDEMPOTENCY_KEY='<idempotency-key>' \
cc-claim <task-id>
```

If default mode holds on install corruption or stale claim state, repair that
condition and rerun `cc-claim`. Do not switch to the fallback for routine
stale-claim cleanup.

## Emergency Fallback

```bash
HAPAX_GATE0B_CLAIM_PUBLICATION_OFF=1 cc-claim <task-id>
```

Expected stderr must include `HAPAX_GATE0B_CLAIM_PUBLICATION_OFF=1` and
`using legacy claim writer`. If that warning is absent, stop and inspect the
script version before mutating source.

## Verify Fallback

Check both legacy role-keyed and governed session-keyed cache files:

```bash
for claim_file in ~/.cache/hapax/cc-active-task-<lane>*; do
  test -f "$claim_file" || continue
  test "$(head -n1 "$claim_file")" = "<task-id>" && printf '%s\n' "$claim_file"
done
rg -n "^status: claimed|^assigned_to: <lane>|HAPAX_GATE0B_CLAIM_PUBLICATION_OFF" \
  ~/Documents/Personal/20-projects/hapax-cc-tasks/active/<task-id>*.md
```

Record why the fallback was used in the task session log or relay status. The
verification proves only a legacy claim write; it is not admitted-publication
evidence.

## Manual Stale-Lease Release

Governed release is scheduled for a later Gate-0B slice. Until then, use this
manual procedure only with operator approval when a stale claim HOLD names an
exact `cc-active-task-*` path:

```bash
claim_file='<absolute-cc-active-task-path>'
task_id="$(head -n1 "$claim_file" | tr -d '[:space:]')"
cc-close "$task_id"
```

If the task id cannot be recovered from the claim file, inspect the matching
`cc-claim-epoch-*` and `cc-claim-dispatch-*.json` files for the same lane or
session key. Archive the stale sidecars under the affected task lineage before
removing them, then rerun `cc-claim <task-id>`.

## Roll Back To Normal

```bash
unset HAPAX_GATE0B_CLAIM_PUBLICATION_OFF
cc-claim <task-id>
```

If the normal command still holds, repair the Gate-0B install root or release the
legacy claim through the governed task path before continuing.
