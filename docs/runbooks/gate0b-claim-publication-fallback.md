# Gate-0B Claim Publication Fallback

Use this runbook only when the default `cc-claim` admitted publication path is
blocked by a bad or missing Gate-0B claim-publication install receipt and the
operator explicitly authorizes a temporary legacy claim write.

Default mode is the repair target. The fallback does not produce an admitted
claim-publication receipt, so it must not be used to satisfy admitted close or
future machine-authorizing paths.

## Recheck The Default Path

```bash
cc-claim <task-id>
```

If this holds with `gate0b_install_receipt_missing`,
`gate0b_install_manifest_missing`, or another Gate-0B install error, repair the
composition receipt for the current `HOME` and rerun `cc-claim`. Do not switch to
the fallback for routine stale-claim cleanup.

## Emergency Fallback

```bash
HAPAX_GATE0B_CLAIM_PUBLICATION_OFF=1 cc-claim <task-id>
```

Expected stderr must include `HAPAX_GATE0B_CLAIM_PUBLICATION_OFF=1` and
`using legacy claim writer`. If that warning is absent, stop and inspect the
script version before mutating source.

## Verify

```bash
test "$(head -n1 ~/.cache/hapax/cc-active-task-<lane>)" = "<task-id>"
rg -n "^status: claimed|^assigned_to: <lane>|HAPAX_GATE0B_CLAIM_PUBLICATION_OFF" \
  ~/Documents/Personal/20-projects/hapax-cc-tasks/active/<task-id>*.md
```

Record why the fallback was used in the task session log or relay status. The
verification proves only a legacy claim write; it is not admitted-publication
evidence.

## Roll Back To Normal

```bash
unset HAPAX_GATE0B_CLAIM_PUBLICATION_OFF
cc-claim <task-id>
```

If the normal command still holds, repair the Gate-0B install root or release the
legacy claim through the governed task path before continuing.
