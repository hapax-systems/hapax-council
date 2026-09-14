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

For an isolated behavioral recheck from the repository root:

```bash
set -euo pipefail
smoke_home="$(mktemp -d /tmp/hapax-gate0b-default-recheck.XXXXXX)"
trap 'rm -rf "$smoke_home"' EXIT
HOME="$smoke_home" UV_LINK_MODE=copy scripts/hapax-fsm-smoke --mode default
```

Expected result: the smoke prints the default admitted claim path, manual
binding, first-use install, admitted publication, normal close, claim-after-close
dispatch-only residue archival, and second admitted publication.

For a live default claim, assert the expected sidecars and receipts after
`cc-claim <task-id>`:

```bash
set -euo pipefail
task_id='<task-id>'
lane="${HAPAX_AGENT_ROLE:-${CODEX_ROLE:-${CLAUDE_ROLE:-<lane>}}}"
session="${HAPAX_SESSION_ID:-${CLAUDE_CODE_SESSION_ID:-<session-id>}}"
cache_dir="$HOME/.cache/hapax"
install_root="$HOME/.local/share/hapax/execution-invocations/gate0b-claim-publish-v1"
dispatch_file="$cache_dir/cc-claim-dispatch-$lane-$session.json"
test -f "$dispatch_file" || dispatch_file="$cache_dir/cc-claim-dispatch-$lane.json"
test -f "$dispatch_file"
test -f "$install_root/activation-receipt.json"
test "$(head -n1 "$cache_dir/cc-active-task-$lane")" = "$task_id"
test "$(head -n1 "$cache_dir/cc-active-task-$lane-$session")" = "$task_id"
receipt_hash="$(
  python - "$dispatch_file" "$task_id" "$lane" "$session" <<'PY'
import json
import re
import sys
from pathlib import Path

record = json.loads(Path(sys.argv[1]).read_text(encoding="ascii"))
task_id, lane, session = sys.argv[2:5]
assert record["task_id"] == task_id
assert record["lane"] == lane
assert record["session_id"] == session
assert record["dispatch_message_id"].startswith("manual-cc-claim:")
assert str(record["coord_dispatch_idempotency_key"]).startswith("manual-cc-claim:")
assert record["platform"] == "codex"
assert record["mode"] == "headless"
assert record["profile"] == "ultra"
assert re.fullmatch(r"[0-9a-f]{64}", record["binding_hash"])
assert re.fullmatch(r"[0-9a-f]{64}", record["receipt_hash"])
print(record["receipt_hash"])
PY
)"
test -f "$cache_dir/claim-publication-receipts/$receipt_hash.json"
```

Expected result: every command exits zero. The dispatch sidecar is manual
provenance, the content-addressed install receipt exists, both activation
sidecars name the claimed task, and the admitted receipt named by the binding is
present.

First use on a host installs the Gate-0B claim-publication composition root for
the current `HOME` and then publishes the admitted claim. The install is
content-addressed and idempotent for exact matching files. A corrupt,
noncanonical, or mismatched receipt/manifest HOLDs; `cc-claim` does not
overwrite non-matching install artifacts.

The admitted writer stages the task note, epoch sidecars, and dispatch-binding
sidecars first. It persists the content-addressed claim-publication receipt
before constructing or publishing any `cc-active-task-*` activation file. If a
normal close leaves terminal dispatch-only residue, the next admitted
`cc-claim` archives that residue under the old task's `_lineage/` before
publishing the fresh claim.

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
set -euo pipefail
shopt -s nullglob
task_id='<task-id>'
lane="${HAPAX_AGENT_ROLE:-${CODEX_ROLE:-${CLAUDE_ROLE:-<lane>}}}"
vault_active="$HOME/Documents/Personal/20-projects/hapax-cc-tasks/active"
task_notes=()
test -f "$vault_active/$task_id.md" && task_notes+=("$vault_active/$task_id.md")
for candidate in "$vault_active/$task_id-"*.md; do
  task_notes+=("$candidate")
done
test "${#task_notes[@]}" -gt 0
task_note="${task_notes[0]}"
matches=()
for claim_file in "$HOME"/.cache/hapax/cc-active-task-"$lane"*; do
  observed_task="$(head -n1 "$claim_file")"
  test "$observed_task" = "$task_id" && printf '%s\n' "$claim_file"
  test "$observed_task" = "$task_id" && matches+=("$claim_file")
done
test "${#matches[@]}" -gt 0
test -f "$task_note"
rg -q "^status: claimed$" "$task_note"
rg -q "^assigned_to: $lane$" "$task_note"
relay_files=("$HOME"/.cache/hapax/relay/*.yaml)
rg -q "HAPAX_GATE0B_CLAIM_PUBLICATION_OFF=1|operator-authorized emergency fallback|using legacy claim writer" \
  "$task_note" "${relay_files[@]}"
```

Expected result: at least one exact `cc-active-task-$lane*` path is printed,
the resolved task note (`active/<task-id>.md` or `active/<task-id>-*.md`)
contains `status: claimed` and `assigned_to: $lane`, and the operator log or
relay records why the non-admitted fallback was used. If any command exits
nonzero, the fallback did not produce a complete legacy claim or the operator
reason is missing.

Record why the fallback was used in the task session log or relay status. The
verification proves only a legacy claim write; it is not admitted-publication
evidence.

## Manual Stale-Lease Release

Governed release is scheduled for a later Gate-0B slice. Until then, use this
manual procedure only with operator approval when a stale claim HOLD names an
exact `cc-active-task-*` path:

```bash
set -euo pipefail
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
    archived="$archive_dir/$(basename "$path")"
    tmp_archived="$archive_dir/.copying-$(basename "$path")"
    cp -p -- "$path" "$tmp_archived"
    cmp -s -- "$path" "$tmp_archived"
    mv -f -- "$tmp_archived" "$archived"
    cmp -s -- "$path" "$archived"
    rm -f -- "$path"
    test ! -e "$path"
    test -e "$archived"
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
procedure.

**`cc-close` is not a stale-lease tool, but it is no longer blind to other
sessions.** Two different operations, easily confused:

- **Role-wide closure** — `cc-close <task-id>` retires *every* lease **this role**
  holds that names **the task being closed**, including leases keyed to the role's
  other sessions. It sweeps `cc-active-task-<role>-*`, retiring a globbed key only
  when the remainder is an id this system minted, so a role whose name extends
  this one (`cx-blue` vs `cx-blue-shadow`) is never touched. This is closure
  cleanup: it exists so a lane that restarted mid-task cannot leave the marker set
  disagreeing with the vault.
- **Exact-file stale-lease release** — the procedure above. Use it for a lease
  naming a *different* task, a lease belonging to a *different role*, or any lease
  you must retire without closing the task. `cc-close` will not touch those, by
  design: a lease for other work is another session's live claim.

So: closing a task no longer requires hand-releasing the closing role's other
leases for it. Everything else still does.

Recheck both guarantees — the role-wide sweep and the overlapping-role
protection — before relying on either:

```bash
uv run pytest tests/scripts/test_cc_close_session_lease.py -q
```

Expected: all pass. The two that carry these guarantees by name are
`test_cc_close_clears_a_lease_for_this_task_held_by_another_session` (role-wide
closure reaches another session's lease for the closed task) and
`test_cc_close_orphan_sweep_spares_a_role_sharing_its_prefix` (`cx-blue` does not
sweep `cx-blue-shadow`). The stale-lease commands above verify a *different*
operation — exact-file release — and say nothing about either.

## Paged By `stale_claim_marker`

cc-hygiene's live↔declared join compares runtime `cc-active-task-*` markers with
the vault. Every event carries a `next_action` in its metadata; do what it says,
because the four cases have genuinely different remedies.

| `next_action` | `reason` | What it means | Do |
|---|---|---|---|
| `re-emit-close` | — | Terminal task, note still in `active/`, status one cc-close accepts | Run the `remediation` command verbatim. It carries `--status` so the existing outcome is preserved — do not drop it, cc-close defaults to `done`. |
| `retire-orphan-marker` | — | Note already in `closed/`, or a terminal status cc-close's `--status` rejects (`refused`, `completed`, `closed_poisoned`, …) | No governed tool retires these. Confirm the closure, then remove the two paths the event names. **Use the paths in the event, not `~/.cache/hapax`** — a sweep of a non-default marker dir names that dir instead. |
| `operator-adjudication` | `task_not_in_vault` | The marker names a task that exists nowhere | A person decides. Nothing can distinguish a deleted note from a corrupt marker, and guessing either way destroys evidence. |
| `operator-adjudication` | `assignee_disagreement` / `role_unattributable` | Two parties believe they hold the task, or the marker names no role the vault knows | A person decides. Do not delete: the marker IS the contention evidence. |

Two further events report that the sweep itself was incomplete, and mean the
check's silence is not evidence of agreement:

- `marker_dir_absent` (warning) — the marker directory does not exist, so the
  join checked nothing. Usually a misconfigured `--relay-root`, since the marker
  dir is derived from its parent.
- `marker_dir_unreadable` / `marker_unreadable` (violation) — enumeration or a
  specific file could not be read. Repair the permission, then re-sweep.

### Silencing it

`stale_claim_marker` has no killswitch of its own. It is covered by the sweeper's,
which stops every check:

```bash
HAPAX_CC_HYGIENE_OFF=1     # sweeper-wide: silences all checks, not just this one
```

Deliberately not per-check. A reconciliation whose job is noticing that live state
disagrees with declared state is the last check that should be individually
muteable — silencing it leaves the drift and removes the only thing reporting it.
If it is firing repeatedly, the `next_action` is the thing to act on; if the events
are wrong, that is a defect to file, not a check to mute.

Recheck the remediation matrix and the two incomplete-sweep behaviours:

```bash
uv run pytest tests/test_cc_hygiene_stale_claim_marker.py -q
```

Expected: all pass. `test_emitted_remediation_is_a_runnable_command` is the one
that keeps the `re-emit-close` command executable (it is fed to `bash -n`), and
`test_remediation_names_the_cache_the_sweep_actually_read` is the one that keeps a
non-default marker dir from being told to delete local files.
`test_unlistable_directory_is_reported_not_read_as_empty` and
`test_unreadable_marker_becomes_a_violation_event` cover the two incomplete-sweep
events above.

## Resuming A Lane Whose Claim Is Bound To An Older Session

**There is no supported resume.** A Gate-0B claim binds `session_id`, every
launcher mints a fresh one per launch, and `resolve_applied_claim_publication`
refuses a mismatch with `claim_binding_vector_mismatch`. So relaunching a lane
that holds an unfinished admitted claim will HOLD.

This is pre-existing, not new: `origin/main` mints on every clean relaunch too.
A launcher-side succession helper was attempted and removed — it cannot be made
exclusive from a launcher (see the REMOVED block in
`hooks/scripts/agent-role.sh`). Governed rebinding belongs in cc-claim, which
holds the lease lock, and is rowed separately.

Until that lands, the operator paths are: finish the work in the original
session; or release the claim through the exact-file stale-lease procedure above
and re-claim; or use `HAPAX_GATE0B_CLAIM_PUBLICATION_OFF=1` for an
operator-authorized emergency fallback. Do not hand-edit the binding sidecars.

## Blocked By `exit 9` — "identity helper not found"

All six launchers (`hapax-claude`, `hapax-claude-headless`, `hapax-codex`,
`hapax-codex-headless`, `hapax-vibe`, `hapax-kimi`) resolve
`hooks/scripts/agent-role.sh` before minting a session identity, and refuse with
exit 9 rather than launch ungoverned. The message names the path it looked for.

They look in the launcher's **own tree** first (resolving symlinks, so the
`~/.local/bin` entrypoints find their real checkout), then `$HAPAX_COUNCIL_DIR`.
So exit 9 means both lookups failed:

```bash
ls -l "$(readlink -f "$(command -v hapax-claude)")"        # which tree am I actually running?
ls "$(dirname "$(readlink -f "$(command -v hapax-claude)")")/../hooks/scripts/agent-role.sh"
```

Fix by running from a complete council checkout, or point `HAPAX_COUNCIL_DIR` at
one. The refusal is deliberate: a launcher that quietly re-implemented the mint is
how five divergent copies of it came to exist.

## Roll Back To Normal

```bash
unset HAPAX_GATE0B_CLAIM_PUBLICATION_OFF
cc-claim <task-id>
```

If the normal command still holds, repair the Gate-0B install root or release the
legacy claim through the exact stale-lease release procedure before continuing.
