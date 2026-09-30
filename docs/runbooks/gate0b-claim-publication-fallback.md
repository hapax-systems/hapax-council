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

## Claimant-Scoped Blocked Recovery

`cc-claim` has one narrow recovery edge for an owned, non-dependency blocked
row. It is not a generic `blocked -> claimed` edit and `blocked` is still not a
dispatchable status. The row must already name the current lane in
`assigned_to`, must have `depends_on: []`, and must carry a typed
`blocked_witness` whose live evaluation satisfies at use time.

The witness must bind the exact blocker it resolves:

```yaml
blocked_reason: codex_platform_capability_receipt_invalid
blocked_witness:
  kind: receipt_fresh
  ref: ~/.cache/hapax/platform-capability-receipts/<current-codex-receipt>.json
  recovery: claimant_scoped_cc_claim
  resolves_blocked_reason: codex_platform_capability_receipt_invalid
```

Recovery currently recognizes only `codex_platform_capability_receipt_invalid`
with `kind: receipt_fresh`. It re-runs the existing typed platform-receipt loader
against its configured producer directory (`HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR`,
or the default directory above). The referenced JSON must belong to that directory
and be its selected current Codex receipt covering `codex.headless.full`, with
fresh, observed capability/resource surfaces and no blocker reasons. A malformed
sibling receipt still refuses: one valid file cannot clear a directory-loader
failure. A generic timestamp receipt, an unrelated path, `path_exists`,
`ancestor_of_main`, or any unrecognized blocked reason cannot authorize recovery.
The generic witness kinds remain available to their existing non-recovery callers.

Unknown, untyped, stale, future-dated, missing, or reason-mismatched witnesses
refuse before any claim publication. Receipt validity is rechecked under the
publication lock. Duplicate YAML keys (including quoted aliases), malformed
frontmatter, and missing original claim timestamps refuse before the status
rewrite, including on the explicit legacy writer. Another live claim marker for
the row also refuses. A
successful recovery publishes an admitted Gate-0B claim-publication receipt
whose preimage is `status: blocked` and postimage is `status: claimed`; it keeps
the prior `claimed_at`, `blocked_reason` and `blocked_witness` in the note as
historical evidence and adds a session-log recovery line. This receipt predicate
does not prove stable route/quota admission or authorize the blocked runtime act.

Read-only witness recheck from the source tree (exit 0 means satisfied, 4 means
held; this does not claim, unblock, or accept a task):

```bash
uv run --no-sync python - /absolute/path/to/task.md <<'PY'
import sys
from pathlib import Path
from shared.blocked_witness import evaluate_claimant_blocked_recovery
from shared.sdlc_claim import ClaimPublicationError, blocked_recovery_fields

try:
    fields = blocked_recovery_fields(Path(sys.argv[1]).read_bytes())
except ClaimPublicationError as exc:
    print(exc)
    raise SystemExit(4) from exc
result = evaluate_claimant_blocked_recovery(fields)
print(result)
raise SystemExit(0 if result.verdict == "satisfied" else 4)
PY
```

After an authorized claimant runs `cc-claim <task-id>`, check the publication ID
printed by that command. This verifies the journal's exact before/after bytes,
recovery mode, retained evidence, and live task postimage:

```bash
uv run --no-sync python - /absolute/path/to/claim-publications/claim-pub-ID/manifest.json <<'PY'
import hashlib
import json
import sys
from pathlib import Path
from shared.sdlc_claim import blocked_recovery_fields

path = Path(sys.argv[1])
record = json.loads(path.read_text())
assert record["state"] == "applied"
intent = record["intent"]
assert (intent["claim_mode"], intent["from_status"], intent["to_status"]) == (
    "blocked_recovery", "blocked", "claimed"
)
note = next(p for p in record["projections"] if p["path"] == intent["note_path"])
blobs = [(path.parent / note[f"{side}_blob"]).read_bytes() for side in ("before", "after")]
for side, blob in zip(("before", "after"), blobs, strict=True):
    assert hashlib.sha256(blob).hexdigest() == note[f"{side}_sha256"]
before, after = map(blocked_recovery_fields, blobs)
assert (before["status"], after["status"]) == ("blocked", "claimed")
for key in ("assigned_to", "claimed_at", "blocked_reason", "blocked_witness"):
    assert before[key] == after[key]
assert Path(note["path"]).read_bytes() == blobs[1]
print("Applied recovery journal and current task postimage match; independent acceptance is separate.")
PY
```

Focused regression recheck:

```bash
uv run --no-sync pytest tests/scripts/test_cc_claim.py tests/shared/test_sdlc_claim.py \
  -k 'blocked_recovery or owner_recovers_blocked_row' -q
```

For a legacy row that only has free-text `blocked_reason` and no typed witness,
do not fabricate a historical witness. The safe one-time path is:

1. Preserve the existing `blocked_reason` text.
2. Only if the original reason is recognized by the evaluator, add a typed
   `blocked_witness` pointing to its current producer receipt. Keep unsupported
   free-text reasons held; do not relabel a reason to obtain a supported transition.
3. Set `recovery: claimant_scoped_cc_claim` and
   `resolves_blocked_reason` to the exact current `blocked_reason`.
4. Obtain the required independent source acceptance for that one-time evidence
   binding before using it.
5. Rerun `cc-claim` from the original claimant lane and verify the admitted
   receipt and postimage.

If the evidence cannot satisfy this contract, keep the row blocked. For the GLM
refresh timer row described by the 2026-09-29 recovery brief, this means the
row stays held until its own route/admission producer emits a fresh typed
receipt and the later bounded timer act is challenged separately. This recovery
does not authorize a service act, provider switch, timer restart, merge, or
manual row shortcut.

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

## Install Re-Provision After A Bound-Module Merge

The executor descriptor binds seven `shared/` modules by content (`BOUND_EXECUTOR_MODULES` in
`shared/gate0b_claim_publication_install.py`). A merge that changes one of them correctly makes
every claim hold on `gate0b_install_executor_descriptor_mismatch` until the install receipt is
replaced. The install re-provision replaces it. `hapax-source-activate` runs it after every
activation, and again on each already-activated timer tick, so a hold is retried once its cause
is repaired. It never fails an activation. By hand, from the active release:

```bash
release="$HOME/.cache/hapax/source-activation/worktree"
( cd "$release" && .venv/bin/python -m shared.gate0b_claim_publication_install \
    reprovision --repo "$release" --head "$(git -C "$release" rev-parse HEAD)" )
```

It prints one JSON object. It exits 0 for `absent` (no receipt yet; cc-claim's first-use install
applies), `current` (nothing to do) or `reprovisioned`. It exits 3 for `held`, with a
`reason_code`. The activation keeps the last outcome in
`~/.cache/hapax/source-activation/gate0b-reprovision-last.json`.

**What a re-provision does.** It re-provisions only when the bound-file state just before one of
main's recent bound-file commits reproduces the receipt's descriptor. Those later commits are the
reviewed authority basis.

1. It creates `reprovision-in-flight.json` exclusively. A second run refuses on it.
2. It writes `reprovision-basis-<stamp>.pending.json`.
3. It quarantines `activation-receipt.json` and `composition-manifest.json` in place as
   `*.quarantined-<stamp>`.
4. It installs fresh from the release's own modules.
5. It completes `reprovision-basis-<stamp>.json`.
6. It retires the marker by renaming it to `reprovision-in-flight.json.resolved-<stamp>`.

All of these are in the install directory. `<stamp>` is `YYYYMMDDTHHMMSS.ffffffZ`. Nothing is
deleted. While the marker exists, `cc-claim` holds on `gate0b_install_reprovision_in_flight`,
even with no receipt: a first-use install never fills a re-provision's gap.

| `reason_code` | Meaning | Next action |
|---------------|---------|-------------|
| `gate0b_reprovision_live_drift` | The release's bound modules differ from the commit it activated | Never edit a release in place; rerun governed source activation |
| `gate0b_reprovision_unexplained` | No recent state of main reproduces the receipt | Inspect the receipt; quarantine it by hand only on an operator decision |
| `gate0b_reprovision_quarantine_exists` | A quarantine name for this stamp is taken (a concurrent run) | Preserve both files, inspect, rerun |
| `gate0b_reprovision_git_unavailable` | The repo given carries no history | Run it from the activated release worktree |
| `gate0b_reprovision_basis_unrecorded` | A basis record could not be written | Restore a writable install directory; the next tick retries |
| `gate0b_reprovision_quarantine_failed` | Moving the pair aside failed part-way | Repair the install directory; the next tick retries |
| `gate0b_reprovision_install_failed` | The fresh install failed | Repair the cause named in the detail; the next tick retries |
| `gate0b_reprovision_in_flight` | The marker exists: another run, or an unfinished one | Wait one tick. If it stays, follow "An unfinished re-provision" below |
| `gate0b_reprovision_rollback_failed` | Putting the old pair back failed; the marker stays | Follow "An unfinished re-provision" below |

After `basis_unrecorded`, `quarantine_failed` or `install_failed`:
- the pair this run moved is put back, and the marker is retired;
- once the install has run, any fresh file is also set aside as `*.unrecorded-<stamp>`.

So claims keep holding on the old receipt. The final basis record reads `rolled_back` if the
directory still accepts a write; after a `basis_unrecorded`, it may not, and then only the
`.pending.json` record exists.

**An unfinished re-provision.** The marker names its stamp and the quarantined pair. Recheck:

```bash
store="$HOME/.local/share/hapax/execution-invocations/gate0b-claim-publish-v1"
cat "$store/reprovision-in-flight.json"            # the stamp, head and quarantined pair
ls -la "$store" | grep -E "activation-receipt|composition-manifest|reprovision-"
```

If the live pair is whole and matches the `reprovision-basis-<stamp>.json` record, or the
quarantined pair is back under its live names, retire the marker. Never delete it:

```bash
mv -n "$store/reprovision-in-flight.json" "$store/reprovision-in-flight.json.resolved-<stamp>"
```

Otherwise, first put the `*.quarantined-<stamp>` pair back under its live names, then retire the
marker. Rerun `cc-claim`; it should no longer hold on `gate0b_install_reprovision_in_flight`.

## Governed Release Of Claim Residue

A role wedged by its own claim residue releases it itself, without operator scripts:

```bash
cc-claim --release-claim-residue <task-id>
```

Name the task the residue names; the claim HOLD prints the exact command. The release acts
only on the calling role's residue for that task. Every file it touches must equal the
after-image of a claim-publication journal of that role and task, and must be one of that
journal's own session sidecars. It holds the role's publication lock. It moves each file out of
its live name, and copies the moved bytes, verified, into
`_lineage/<task-id>/claim-residue-release-<stamp>-<role>/` (with a README). It never unlinks
anything, and never touches the task note. It covers four shapes:

| Shape | What is left | What the release does |
|-------|--------------|-----------------------|
| `held_publication` (M166, M167) | A `recovery_required` journal whose note has moved past both of its images, so recovery holds on a projection conflict. Epoch and dispatch sidecars exist; the markers were never written. | Archives the sidecars, then quarantines the journal in place as `claim-pub-<sha>.quarantined-<stamp>`. |
| `lapsed_lease` (M168) | Epoch and dispatch sidecars with no `cc-active-task-*` marker; the next claim holds on `claim_cache_missing`. | Archives the sidecars. |
| `closed_task` (M173) | Markers, epochs and dispatch naming a row that another process closed (it is terminal and absent from `active/`); the next claim holds on `claim_task_mismatch`. | Archives all six sidecars. |
| `reassigned_task` | Markers naming an active row whose note no longer names this role (re-offered or reassigned). Every other role's claim or resume of it refuses on them. | Archives all six sidecars, run by the lane that owns them. |
| `pipeline_held` (#4826) | Markers naming this role's row that the pipeline now holds (`pr_open` through `merged_awaiting_runtime_witness`). | Archived automatically by the next `cc-claim` of another row, which frees the slot; the row stays assigned to this role, its named resumer. |
| `returned_claim` (#4832) | This role's own live, unstarted claim, returned with `cc-claim --return-claim` (below). | The note is returned to `offered` first; then all six sidecars are archived. |

It refuses, with exit 8 and a named `claim_residue_*` reason, before the first mutation (except
`live-differed`, below):
- on a live claim (a marker naming a task that is not closed, or another session's marker for it);
- on a sidecar that differs from the journal;
- on a journal that recovery can still finish, or whose admission evidence drifted;
- when the calling role has no journal for the task.

A released row whose note still reads `claimed` by the role stays that way; the release never
edits it.

Recheck after a release (the output decides the next step):

```bash
role="${HAPAX_AGENT_ROLE:?}"
ls -la ~/.cache/hapax/ | grep -E "cc-(active-task|claim-epoch|claim-dispatch)-${role}(-|\.json|$)" || echo "no sidecars left for ${role}"
ls ~/Documents/Personal/20-projects/hapax-cc-tasks/_lineage/<task-id>/ | grep claim-residue-release-
cc-claim --recover-claim-publications <task-id>   # expect no hold; a quarantined journal is skipped
cc-claim <next-task-id>                           # expect the claim to publish
```

Nothing is ever unlinked. Each sidecar is moved, atomically and inside the cache's own filesystem,
into `~/.cache/hapax/claim-residue-release/<task-id>/<stamp>-<role>/`. The bytes actually moved are
what is compared with the journal and what is copied, verified, into the lineage. The vault can be
a different filesystem (on appendix it is an NFS mount), so it is never the rename target. A
`<name>.live-differed-from-journal` file in the lineage means a sidecar changed during the
release. The moved bytes are kept in both places, the README records it, and the release stopped
before the journal; inspect them before rerunning.

**Emergency path.** The release has no override flag and no bypass. If it refuses and the operator
decides the residue must go anyway, the Manual Stale-Lease Release below is the emergency path,
run with operator approval and recorded in the row's lineage.

### Return An Unstarted Claim

A role that claimed a row and has not started it (no PR, no branch) returns it itself:

```bash
cc-claim --return-claim <task-id>
```

Under the role's publication lock and the note's projection lock, the note is read once and
rewritten, by position, to `status: offered`, `assigned_to: unassigned` and `claimed_at: null`,
with a session-log line. The rewritten note must read back that way before it is written. Then the
six sidecars are archived as `returned_claim`. It refuses, with exit 8 and a `claim_return_*`
reason, changing nothing:
- `claim_return_started`: the row names a `pr` or a `branch`, or is not `claimed` or `in_progress`.
  Finish it and run `cc-close`, or close it `withdrawn`.
- `claim_return_not_holder`: the calling role has no claim on the row, or the row is assigned
  elsewhere.
- `claim_return_not_live`: no single live claim. A lapsed lease goes through
  `--release-claim-residue`.
- `claim_return_note_malformed`: the frontmatter does not parse, states a key twice, or does not
  state `status`, `assigned_to` and `claimed_at` each exactly once and plainly. Repair it by hand,
  then rerun.
- `claim_return_archive_collision`: an archive name for this second is already taken. It is checked
  before the note is written, so nothing changed; rerun after a second.
- `claim_return_unfinished`, `claim_return_live_marker`, `claim_return_rewrite_unverified`: follow
  the printed next action.

The one exception to "changing nothing": `claim_return_archive_incomplete` means the note **was**
returned to `offered` but the claim files could not be archived (an I/O failure). That is the same
state a crash between the note write and the archive leaves, the `reassigned_task` shape, and
`cc-claim --release-claim-residue <task-id>` releases it.

Recheck after a return, or after the claim path released a `pipeline_held` row. The output decides
the next step:

```bash
role="${HAPAX_AGENT_ROLE:?}"
tasks=~/Documents/Personal/20-projects/hapax-cc-tasks
# A return: expect `status: offered`, `assigned_to: unassigned`, `claimed_at: null`.
# A pipeline_held release: expect the row's pipeline status, still assigned to the role.
grep -E '^(status|assigned_to|claimed_at):' "$tasks/active/<task-id>.md"
# Expect no marker of the role still naming the task.
grep -lx '<task-id>' ~/.cache/hapax/cc-active-task-"${role}"* 2>/dev/null || echo "no marker names <task-id>"
# Expect `shape: returned_claim` or `shape: pipeline_held` in the newest archive.
grep -h '^shape:' "$tasks/_lineage/<task-id>"/claim-residue-release-*/README.md
```

### An Unreadable Held Row

**Symptom.** `cc-claim <next>` refuses with
`role '<role>' already has active task '<held>' (status: unreadable)`.

**Why.** The held row's frontmatter does not parse, states a key twice (a quoted and a plain
spelling are one key), or does not spell `status` plainly exactly once. A release decides only from
frontmatter that can ground it, so the row's slot stays held, and **nothing is released**: not by
the claim path, not by `--release-claim-residue`, not by `--return-claim`.

**Emergency path.**
1. Repair the held row's frontmatter by hand: one plain `status:` line, no duplicated keys, and no
   `status:` only in the body. Keep every other field.
2. Rerun `cc-claim <next>`. The row's own status now decides:
   - a pipeline-held row is released by the claim path;
   - a worker-held row keeps the slot, and the refusal names close, resume, or return.
3. Never hand-write or delete claim markers to get past it.

## Manual Stale-Lease Release

Use this manual procedure only with operator approval, and only for the shape the governed release
refuses: an **expired** claim HOLD (exit 7) that names an exact `cc-active-task-*` path whose task
is still live. For the four shapes above, use `cc-claim --release-claim-residue` instead.

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
