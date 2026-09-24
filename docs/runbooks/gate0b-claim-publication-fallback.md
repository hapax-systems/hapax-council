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

## Claim publication interruption and retry

Claim admission resolves the complete active and closed task namespace. Index
construction can make up to three attempts, reusing only unchanged stat-bound
parses between attempts. Removal between directory listing and stat, in either
inventory, consumes an attempt; unsafe directories refuse immediately.
Every attempt checks the full frontier; continuing
drift, duplicate identities and changed task preimages still HOLD. A supplied
index is never silently refreshed.

A typed refusal in the second locked preflight, before projection begins,
records an `aborted` journal. Recovery preserves that history and cannot turn
the refusal into a delayed claim. Once projection may have begun, failures
remain recoverable. Recovery validates the complete task identity and exact
preimage or postimage before writing any missing projection.

Do not interpret exit code 8 alone as evidence that nothing was published.
Publication errors report the original role, session, epoch, intent and binding
hash, plus read-only journal observations. An observation can be terminal
applied, terminal aborted, held or unknown; preserve held/unknown evidence and
reconcile it before choosing another session. Ordinary `cc-claim` recovery
requires the pending journal's original role and session. A different session
gets `claim_publication_recovery_owner_mismatch` without applying that journal.
The explicit `cc-claim --recover-claim-publications <task-id>` operation also
binds the caller's resolved role/session. The API refuses omitted, empty or
malformed owner coordinates before filesystem access. Both CLI paths replay
only the original owner's existing admitted publication. The coordinates
select that admission; they are not a new grant. Cross-owner maintenance is
unsupported here and requires a separately governed authority path, not an
omitted argument or a caller inventing another session's identity. Recovery
completes the original admitted publication,
not an ownership transfer. Resolve its durable result before retrying dispatch.

Recovery holds retain the underlying task-store reason and its repair action.
For example, `task_note_cross_state_duplicate` requires reconciling every state
copy, while `task_store_frontier_changed_during_resolution` requires a stable
frontier. Follow that action before repeating recovery; a generic journal
quarantine cannot resolve a conflicting task identity.
Publication-error observations also include the journal's stored refusal cause
and the sealed inspection reference/hash, including for terminal aborted journals.

The claim transaction holds the existing role lock and projected-path lock,
including the task-identity key. A writer participating with that task identity
cannot insert a conflicting note at another filename during recovery. This is
not namespace exclusion against nonparticipating writers: a raw write after
resolution can still cause a hold after partial projection. The unconverted
writer inventory in `tests/shared/test_projected_path_writer_lock_coverage.py`
and the concurrency contract in `shared/coord_projection.py::_transition_locks`
define that remaining boundary. Keep the release hold until its independent
disposition; another pre-write scan alone cannot close it.

Run these behavioral rechecks from the repository root. The tests construct
temporary vaults, claims and journals and do not recover a real task:

```bash
uv run --no-sync pytest -q tests/shared/test_sdlc_task_store.py \
  -k 'bounded_index'
uv run --no-sync pytest -q tests/shared/test_sdlc_claim.py \
  -k 'pre_projection_frontier_refusal or recovery_checks_complete or automatic_recovery_preserves or cc_claim_fresh_session or recovery_reports_task_identity'
uv run --no-sync pytest -q tests/scripts/test_cc_claim.py \
  -k 'publication_failure_reports_durable_outcome or corrupt_install_receipt'
uv run --no-sync pytest -q tests/shared/test_sdlc_claim.py \
  -k 'rehydrate_refuses_current_identity_change'
uv run --no-sync pytest -q tests/shared/test_sdlc_claim.py \
  -k 'recovery_excludes_duplicate_writer or recovery_refuses_changed_unique_task'
```

The first command exercises full-namespace retries, removal races, exhaustion
and unsafe-directory refusal. The next two check terminal preflight refusal,
original-owner recovery, actionable reasons and actual CLI observations of
pending, aborted, applied and unobservable outcomes. The fourth pins refusal
when an applied claim loses its activation caches and its current owner changes,
including an `offered/unassigned` note with surviving epoch/dispatch sidecars.
That state needs reconciliation of the ownership change; missing caches alone
do not authorize reconstructing an owner. The fifth checks the participating
writer exclusion and changed unique-task preimage refusal.

These checks cover the publication-availability prerequisite. They do not
establish the governed-rebind task's positive ownership-transfer exit predicate.
Qualified whole-attempt terminality, transfer races and launcher integration
remain separate unfinished obligations; this increment cannot close that task.

For an offered Codex task, `hapax-methodology-dispatch` removes the inherited
`HAPAX_SESSION_ID` before handing control to the headless launcher. Its existing
session producer then mints a fresh ID. Claimed/in-progress continuations retain
their supplied original identity and `--no-claim` behavior. This separation does
not transfer a claim or repair a previously inherited session.

## Role exclusion interface and writer boundary

`shared.sdlc_claim.claim_role_exclusion(role, *, lock_root)` exposes the
existing exclusive role lock. Supply the exact `claim_lock_root` from the
installed Gate-0B composition. The ordinary CLI binding is
`default_claim_publication_roots(home=Path.home()).claim_lock_root`, currently
`~/.local/state/hapax/task-locks/gate0b-claim-publish-v1`. The low-level library's
historical default `~/.cache/hapax/task-locks` is a different namespace; a
consumer must not substitute it for the installed root.

The key is SHA-256 of `claim-publication-role\0` plus the exact role, shared
across every task and session in that role. The root is a real euid-owned
0700 directory; lock files are euid-owned, single-link 0600 regular files.
The existing bounded `flock` acquisition returns
`claim_publication_lock_unavailable` on contention. Descriptors close on
normal return or exception. This is host-local, cooperative exclusion, not
process liveness, cross-host exclusion, authorization, or a rebind receipt.

Order is **role first, then task identity/note paths**. A caller already
holding a projected-path lock gets `claim_publication_lock_order_inversion`
before opening the role lock. The context is non-reentrant: a consumer holding
it must not call an operation that acquires it again. The supervisor interface
is to hold role exclusion across its final ownership observation and dependent
action, with any necessary note lock inside; its independent authority,
process identity and cleanup checks still apply. Source delivery alone does
not qualify that supervisor integration or its installed postimage.

The source/caller census covered `scripts/`, `shared/`, `agents/` and the
existing projected-path writer inventory, using both publication/sidecar
symbol searches and claim/close/repair/dispatch path inventories:

| Writer | Exclusion supplied here |
|---|---|
| Admitted `cc-claim`, manual or dispatch-bound | Role then task identity/note, through the existing journal, receipt and activation writes. |
| `recover_claim_publications`, activation-cache rehydration | Same role/task locks as admitted publication; the existing intent and receipt checks remain. |
| Explicit emergency `cc-claim` | Same installed role namespace, then note lock through all note/epoch/activation/charter writes. It remains a non-admitted, non-journaled fallback. |
| Charter-unit recording | Role then unit/parent note paths, recheck the parent receipt/lease and exact unit preimage, retain locks through the unit note, charter marker and ledger append. |
| Charter mint's auxiliary marker | Reacquire role then note; revalidate the exact applied owner before writing. Contention reports the already-applied publication separately. An original-owner retry completes this projection. |
| Local launchers / dispatch adapters | Call the publication path; they do not acquire or decide this shared lock themselves. |
| Codex remote `REMOTE_EXEC_PY` materializer | Takes the execution host's installed role lock before session-role, epoch and activation writes. Missing helper/import or unavailable lock refuses before those writes, proof or native exec. No note lock is taken; any future note lock must follow role exclusion. |

`cc-close` takes task/note locks and then removes matching cache projections;
it does not participate in role exclusion. Terminal disappearance during
supervisor cleanup therefore needs its own checked terminal case.
Dispatch-residue archival, emergency stale-marker deletion, the explicit
manual stale-release procedure, `codex-claim-audit`, supervisor legacy cleanup,
and raw/manual/daemon task-note writes are also outside role exclusion.
The `REMOTE_EXEC_PY` block in `scripts/hapax-claude-headless` still writes
epoch/activation files without this lock in this source checkout. That peer-owned
writer needs separate qualification before any all-writer supervisor exclusion
claim. Codex's materializer now participates locally on its execution host; this
does not establish cross-host exclusion, admission, whole-attempt terminality or
positive rebind. Its existing exact task/epoch and proof fields remain required.
Remote execution resolves `HAPAX_SOURCE_ACTIVATE_WORKTREE`, then the explicitly
bound `HAPAX_COUNCIL_DIR`, otherwise the host's activated source path. It pins
that directory before executing its provisioned `.venv/bin/python` with isolated
imports. The worker checkout is not the helper source. Missing runtime or helper
is a refusal, never permission to publish without exclusion. The lock does not
make the existing multi-file materializer crash-atomic.

Recheck the real temporary-HOME subprocess cases (no remote/native capability):

```bash
uv run --no-sync python -m pytest tests/scripts/test_hapax_codex_headless.py \
  -k remote_materialization_ -q
```

Metadata-only repair/stage/PR-link tools take projected-path locks and do not
publish a new claim. See the full unconverted inventory in
`tests/shared/test_projected_path_writer_lock_coverage.py`, including
`agents/coordinator/core.py`; stopping a daemon does not convert its writer.

No no-partial-write guarantee covers a raw writer ignoring these locks. A
duplicate inserted after task resolution can still produce a typed hold after
note/epoch/dispatch changes, before receipt/activation. Preserve that partial
state and its journal; do not call it rollback or a completed transfer. The
source-author raw-writer counterexample remains a separate release finding.
Neither this exclusion increment nor availability work satisfies the original
positive-rebind exit predicate.

Recheck the bounded contracts using isolated fixtures:

```bash
uv run --no-sync python -m pytest tests/scripts/test_cc_claim_role_exclusion.py -q
uv run --no-sync python -m pytest tests/shared/test_sdlc_claim.py -q \
  -k 'requires_explicit_valid_owner or fresh_session_does_not_apply or transaction_postimage_retries'
uv run --no-sync python -m pytest tests/shared/test_task_note_lock.py -q \
  -k 'role_lock or claim_publication'
uv run --no-sync python -m pytest tests/scripts/test_hapax_methodology_dispatch.py -q \
  -k scrubs_fresh_session
```

For the preserved, deliberately failing raw-writer counterexample, from this
source checkout on the dispatched host:

```bash
uv run --no-sync python -m pytest \
  "$HOME/.cache/hapax/claim-rebind-20260924/test_role_raw_writer_race.py" -q
```

That last probe uses only temporary claims. Expected: one failure showing
`claim_publication_task_projection_invalid`, a changed note and four sidecars,
with no receipt/activation. Its failure documents the exclusion boundary; it
is not a passing invariant check or permission to recover a real specimen.

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
procedure. Do not use `cc-close` for another session's stale claim file: it
does not target that file.

## Roll Back To Normal

```bash
unset HAPAX_GATE0B_CLAIM_PUBLICATION_OFF
cc-claim <task-id>
```

If the normal command still holds, repair the Gate-0B install root or release the
legacy claim through the exact stale-lease release procedure before continuing.
