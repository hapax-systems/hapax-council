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
shopt -s nullglob
matches=()
for claim_file in "$HOME"/.cache/hapax/cc-active-task-<lane>*; do
  test "$(head -n1 "$claim_file")" = "<task-id>" && printf '%s\n' "$claim_file"
  test "$(head -n1 "$claim_file")" = "<task-id>" && matches+=("$claim_file")
done
test "${#matches[@]}" -gt 0
rg -n "^status: claimed|^assigned_to: <lane>|HAPAX_GATE0B_CLAIM_PUBLICATION_OFF" \
  ~/Documents/Personal/20-projects/hapax-cc-tasks/active/<task-id>*.md
```

Expected result: at least one exact `cc-active-task-<lane>*` path is printed,
the task note contains `status: claimed` and `assigned_to: <lane>`, and the
operator log records why the non-admitted fallback was used. If no path prints
or the `rg` command does not show both frontmatter lines, the fallback did not
produce a complete legacy claim.

Record why the fallback was used in the task session log or relay status. The
verification proves only a legacy claim write; it is not admitted-publication
evidence.

## Manual Stale-Lease Release

Governed release is scheduled for a later Gate-0B slice. Until then, use this
manual procedure only with operator approval when a stale claim HOLD names an
exact `cc-active-task-*` path:

```bash
claim_file='<absolute-cc-active-task-path>'
claim_file="$(realpath -e "$claim_file")"
claim_base="$(basename "$claim_file")"
case "$claim_base" in
  cc-active-task-*) ;;
  *) echo "not a cc-active-task path: $claim_file" >&2; exit 2 ;;
esac
claim_key="${claim_base#cc-active-task-}"
task_id="${task_id:-$(head -n1 "$claim_file" | tr -d '[:space:]')}"
test -n "$task_id"
archive_dir="$HOME/Documents/Personal/20-projects/hapax-cc-tasks/_lineage/$task_id/manual-stale-lease-release-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$archive_dir"
cache_dir="$HOME/.cache/hapax"
for path in \
  "$claim_file" \
  "$cache_dir/cc-claim-epoch-$claim_key" \
  "$cache_dir/cc-claim-dispatch-$claim_key.json"; do
  if test -e "$path"; then
    cp -p -- "$path" "$archive_dir/"
    rm -f -- "$path"
  fi
done
printf 'archived stale lease sidecars to %s\n' "$archive_dir"
```

Expected result: the command prints exactly one archive directory, and the
named `claim_file`, matching `cc-claim-epoch-<claim-key>`, and matching
`cc-claim-dispatch-<claim-key>.json` no longer exist in the cache after copies
land in that archive. Then rerun `cc-claim <task-id>`; if it still holds on the
same path, stop and inspect the archive before removing anything else.

If the task id cannot be recovered from the claim file, inspect the matching
`cc-claim-epoch-*` and `cc-claim-dispatch-*.json` files for the same lane or
session key, set `task_id='<recovered-task-id>'`, and rerun the exact-path
procedure. Do not use `cc-close` for another session's stale claim file: it
does not target that file.

## Roll Back To Normal

```bash
unset HAPAX_GATE0B_CLAIM_PUBLICATION_OFF
cc-claim <task-id>
```

If the normal command still holds, repair the Gate-0B install root or release the
legacy claim through the exact stale-lease release procedure before continuing.
