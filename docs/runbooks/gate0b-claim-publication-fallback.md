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
  other sessions. It sweeps `cc-active-task-<role>-*` and retires a globbed key
  only when the remainder is a **minted-shape session id**
  (`shared/session_identity.py::is_minted_session_id`).

  State that guarantee precisely, because it is narrower than "an extending role
  name is never touched". `is_minted_session_id` is deliberately narrower than
  `is_claim_keyable_session_id`, and ids reach this system from several spawners:
  - a `cx-blue-shadow` lease whose remainder is keyable but **not** minted-shape is
    skipped — safe, and the reason the common case is safe;
  - a `cx-blue-shadow` lease whose remainder happens to be minted-shape **would**
    be retired by `cc-close` running as `cx-blue`, because the glob cannot separate
    the extending role name from a session suffix.

  The second case has not been observed and is not hypothetical-only: it needs a
  role name that extends another role's name AND a minted-shape remainder. If you
  name a role as an extension of an existing one, that is the hazard you are
  taking on.

  This is closure cleanup: it exists so a lane that restarted mid-task cannot leave
  the marker set disagreeing with the vault.
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

#### `cc-close --expect-status` — the precondition a stored command carries

`stale_claim_marker` remediations are generated by a sweep and run by a person,
possibly much later. In between, the task can resume. So the emitted command
carries the state the sweep observed:

```bash
cc-close <task-id> --status withdrawn --expect-status withdrawn
```

`--expect-status` is checked **inside the writer**, against the same bytes it is
about to rewrite, immediately before rewriting them, and **under an exclusive
per-task lock**. Not in an earlier process: a check that re-reads the note, exits,
and only then hands off to a writer that re-reads it leaves exactly the window the
flag exists to close.

### The per-task mutation lock

`cc-close` and `cc-claim` now take one exclusive lock per task id
(`shared/cc_task_lock.py`; the files live in
`~/.cache/hapax/cc-task-locks/<task-id>.lock`). Before it existed, cc-close's
sequence — read the note, validate it, write it into `closed/`, unlink the
original — was not atomic against a concurrent resume: a `cc-claim` landing after
the read made cc-close write its stale snapshot to `closed/` and delete the
resumed note. Atomic replacement (`tmp` + `os.replace`, which cc-claim already
did) makes each write all-or-nothing; it is not mutual exclusion.

Two refusals you may see:

```
cc-close: refusing — another process has held the cc-task lock for '<id>'
(<path>) for more than 30s. Next action: find the holder with
'fuser -v <path>' and let it finish, then re-run. Nothing was modified.
```

```
cc-claim: BLOCKED — another process has held the cc-task lock for '<id>' …
Another cc-claim or cc-close is mid-mutation on this task.
```

Both mean *wait, then re-run*. Neither leaves state behind: the lock is an
advisory `flock`, so the kernel drops it when the holder exits by any path,
including a crash — **there is no stale lock to clear and no reaper to run**. If a
refusal persists, something is genuinely wedged; find it with `fuser -v` rather
than deleting the lock file.

The lock is taken **after** cc-close's read-only gates, not before, because those
gates call `gh` and can block on the network; a lock held across a network call
would stall every other writer for as long as GitHub takes. Nothing above that
point mutates.

Limits, stated rather than patched: the lock is advisory and covers the writers
that take it. A hand edit of a note in a text editor takes nothing and is excluded
by nothing.

If it does not hold, cc-close exits 2 and **nothing is modified**:

```
cc-close: refusing — '<path>' is status 'in_progress' at write time, but
--expect-status 'withdrawn' was required. The task changed after the command was
generated. Next action: re-run the sweep and use its current recommendation.
```

**When it fires, do not re-run the command without the flag.** The refusal is the
correct outcome: the stored command describes a task state that no longer exists.
Re-run the sweep; if the marker is still stale, it emits a new command for the
state the task is in now. If it emits nothing, the disagreement resolved itself
and there is nothing to do.

Recheck:

```bash
uv run pytest tests/test_stale_marker_remediation_integration.py -q
```

Expected: all pass. Three carry this behaviour by name:
`test_a_saved_command_refuses_after_the_task_resumes` (the stored command refuses),
`test_the_precondition_holds_against_the_bytes_actually_rewritten` (it refuses with
the **expected-status** message, not merely nonzero — a cc-close without the flag
exits nonzero too, by rejecting an unknown argument), and
`test_the_precondition_is_evaluated_after_the_lock_is_taken`, which holds the lock,
changes the status underneath a waiting cc-close, and releases — the only shape
that can tell an early guard from one inside the protected section.

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

- `marker_dir_absent` (**violation** — ntfy alerts gate on that tier, and a
  reconciliation that checked nothing is exactly the case someone has to notice)
  — the marker directory does not exist, so the join checked nothing. Usually a misconfigured `--relay-root`, since the marker
  dir is derived from its parent.
- `marker_dir_unreadable` / `marker_unreadable` (violation) — enumeration or a
  specific file could not be read. Repair the permission, then re-sweep.
- `marker_dir_empty` (warning) — the DERIVED marker directory exists but holds no
  markers. Expected on an idle host; otherwise `--relay-root` has been relocated
  away from cc-claim's cache and the join is reconciling an empty directory.
- `vault_view_incomplete` (**violation**) — a note the parser rejected, or a
  directory it could not list, means the sweep cannot see the whole vault. It then
  declines **every** judgement about that marker, including "exists nowhere": a
  file it could not read may be the task. Repair the note or the permission named
  in `unparsed_notes` / `enumeration_errors`, then re-sweep. Do not delete a marker
  on the strength of a sweep that reported this.

Every event from this check also carries `marker_dir` and
`marker_dir_provenance` — the directory the join actually read and how that
location was chosen (derived from `--relay-root`, or passed explicitly). Read them
before acting: the derivation coincides with cc-claim's cache because of layout,
so a clean result from a derived directory is not by itself a verified one.

Recheck:

```bash
uv run pytest tests/test_cc_hygiene_stale_claim_marker.py -q
```

Expected: all pass. `test_an_unreadable_note_is_not_reported_as_a_nonexistent_task`
and `test_every_event_records_where_the_join_looked` carry these two properties by
name.

### `cc-close` refuses with "declares task_id ..."

cc-close selects a note by filename and then checks that the note's own
`task_id:` is the one you asked for. Two refusals (both exit 2, nothing mutated):

- **`declares task_id 'X', not 'Y'`** — the only note matching your id by filename
  belongs to a different task. Most often a prefix neighbour: asking for `t1` when
  only `t1-next.md` exists. Pass the exact id, or repair the filename/frontmatter
  so they agree.
- **`declares no readable task_id`** — the note's frontmatter has no parseable
  `task_id` scalar. Repair it (`task_id: <id>`, single-line) and re-run.

This guard exists because the filename glob can only ever match a prefix: without
it, `cc-close t1` selected `t1-next.md` and withdrew different, live work.

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

Until that lands there are three operator paths, and only the first is simple:

1. **Finish the work in the original session.** Always preferred.
2. **Release and re-claim — NOT just the sidecar removal above.** The exact-file
   stale-lease procedure removes the sidecars but leaves the note at `claimed` or
   `in_progress`, and cc-claim's eligibility branch refuses **both** (exit 4):
   neither is in `TASK_CLAIMABLE_STATUSES` (`offered` only) nor resumable once the
   sidecars are gone. The complete transition is:

   ```bash
   # after the stale-lease release above
   uv run python scripts/cc-task-repair <task-id>            # only if the note is malformed
   # return the note to an offered, unassigned state, then:
   cc-claim <task-id>
   ```

   Returning `status:`/`assigned_to:` to `offered`/`unassigned` is an operator
   edit — `cc-task-repair` only backfills ABSENT scaffolding and will not
   overwrite a live value. Verify the reclaim actually succeeded (`cc-claim`
   exits 0 and prints the written claim paths) rather than assuming the release
   was sufficient; that assumption is what made this procedure incomplete.
3. **`HAPAX_GATE0B_CLAIM_PUBLICATION_OFF=1`** for an operator-authorized
   emergency fallback. Do not hand-edit the binding sidecars.

### A second, independent collision path — deferred, not fixed

`scripts/hapax-claude` exports `HAPAX_SESSION_ID` into the **tmux pane**, so the
minted suffix identifies the PANE, not the harness session that claims. Every
Claude session that pane hosts over its lifetime keys the same claim file. That is
a distinct route to the same key collision this work repairs and it is **not**
addressed here; it needs the same cc-claim-side ownership the succession row does.
Ask the coordinator for its row before relying on per-session claim isolation in a
long-lived pane.

**Check it yourself — the mechanism is visible in the runner the launcher writes:**

```bash
runner="$(ls -t "${XDG_CACHE_HOME:-$HOME/.cache}"/hapax/claude-spawns/run-*.sh 2>/dev/null | head -1)"
printf 'runner: %s\n' "$runner"
grep -c '^export HAPAX_SESSION_ID=' "$runner"
grep    '^export HAPAX_SESSION_ID=' "$runner"
```

Expected today: `1`, and a single **literal** uuid — not `"$SESSION_UUID"`, not a
mint. The runner `exec`s the harness with that value exported, so it is the
environment of the pane rather than of one Claude session: a `--continue`, a
crash-and-restart in that pane, or a second `claude` typed there all resolve the
same id and therefore the same `cc-active-task-<role>-<uuid>` claim file.

That is the whole deferred defect, and it is what a fix would change: when the
suffix becomes per-harness-session, this runner will no longer carry a literal id
and the grep above will return `0`. Until then, treat a long-lived pane as ONE
claim identity.

What *is* fixed and tested is the adjacent property — two **launches** never share
an identity, and no launcher hands its child an ambient one:

```bash
uv run pytest tests/scripts/test_launch_capability_descriptors.py \
              tests/scripts/test_lane_session_id_minting.py -q
```

Expected: all pass. `test_the_child_gets_a_freshly_minted_identity` runs each of
the six launchers twice against a stub harness and asserts the two ids differ. It
says nothing about two sessions inside one pane, which is the gap above.

## Blocked By `exit 78` — "identity helper not found"

All six launchers (`hapax-claude`, `hapax-claude-headless`, `hapax-codex`,
`hapax-codex-headless`, `hapax-vibe`, `hapax-kimi`) resolve
`hooks/scripts/agent-role.sh` before minting a session identity, and refuse with
exit 78 (`sysexits` `EX_CONFIG` — an incomplete checkout is a configuration
error) rather than launch ungoverned. The message names the path it looked for.

**78 and not 9**, because `hapax-methodology-dispatch` already returns 8 for
"launcher not found" and 9 for "this claude profile has no declared model pin".
A caller that saw 9 could not tell a missing launcher's helper from the
dispatcher's own refusal. If you are reading an older transcript, this refusal was
exit 9 before round 12 of PR #4668.

They look in the launcher's **own tree** first (resolving symlinks, so the
`~/.local/bin` entrypoints find their real checkout), then `$HAPAX_COUNCIL_DIR`.
So exit 78 means both lookups failed:

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
