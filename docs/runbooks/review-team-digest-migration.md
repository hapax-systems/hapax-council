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
`migration.plan_binding.candidate_authority_sha256`. When planning is ready,
the CLI writes the canonical `PreparedMigrationPlan` JSON bytes directly to
stdout; capture those bytes byte-exactly to a durable prepared-plan file and
record its SHA-256. Blocked or non-ready planning still emits the diagnostic
dispatcher JSON wrapper. The later candidate authority carrier must consume the
exact `migration.plan_binding.candidate_authority` commitment body, carry the
exact prepared-plan file and canonical SHA-256 values, embed the exact prepared
plan bytes as `prepared_plan_raw_bytes_hex`, and use the exact
`migration.plan_binding.candidate_authority_response` text; the source
remediation act is not apply authority. The sealed artifact carries the
candidate-authority commitment and commitment SHA, but not the consumed carrier
path or carrier SHA, so apply can validate the carrier without rewriting any
plan-carried output byte. Lifecycle validation rechecks the active carrier
sidecar's embedded prepared-plan bytes against both prepared-plan hashes. The
sealed artifact's persisted `integrity_recheck` text must name the providerless
`--migration-recheck` command, not the applying replay command.

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
frozen anchor, disposition manifest, write set, evidence manifest, embedded
prepared-plan bytes, prepared-plan file digest, or plan digest differs from the
prepared plan, is a blocker before journal creation or target effects.

A valid pre-existing sealed artifact is immutable. Empty, partial, removed, or
forged seal mappings are blockers, not an unsealed legacy artifact. The only
replaceable unsealed artifact is the exact source-pinned legacy preimage named
by `legacy_unsealed_artifact_sha256` in the reviewed source trust anchor. Reruns
may rebind current open receipts from current dossiers through the exact
prepared write bytes only; apply must not recompute PR discovery, replay
classification, output construction, or acceptance semantics after loading the
prepared plan. Immediately before the transaction, the complete evidence
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
post-write verification, rollback, or recovery failure.

Admission is total, capability-bound, and re-proved at the last pre-effect
boundary:

- **One exact decoder.** The prepared plan is decoded by a single function,
  `prepared_migration_plan_blockers` in `shared/sdlc_lifecycle.py`, which the
  runtime apply path and lifecycle admission both call over the same decoded
  bytes. It is total over constants, enums, digest forms, counts, container
  types and cross-object relations, and it **recomputes** the disposition
  manifest, write set, evidence digest, plan identity and candidate authority
  from the plan's own contents. A plan that merely agrees with its own claimed
  digests is refused: self-consistency is not evidence. A second, laxer
  lifecycle decoder is what previously let a grossly malformed embedded plan
  reach admission while still hashing correctly.
- **One live root capability.** A single `MigrationRootCapability` is opened
  when the migration lock is acquired and carried through apply, rollback,
  recovery, cleanup and release. The vault root, `active`, `_locks` and the
  stage directory are held as `O_DIRECTORY | O_NOFOLLOW` descriptors, and every
  effect is performed *at* those descriptors (`openat`, `renameat`, `unlinkat`,
  `linkat`, `fstatat`). Admitted paths are never re-resolved through the mutable
  namespace between admission and effect, so replacing `active` (or any
  ancestor) with a symlink after the pre-effect boundary cannot redirect a
  write — the held descriptor still refers to the directory that was admitted.
- **Owner capability.** The migration lock file publishes only `owner_proof`, a
  SHA-256 digest. The pre-image secret never reaches disk and is held with an
  open descriptor, so the lock capability cannot be reconstructed from readable
  lock bytes. Release additionally requires that the entry published at the lock
  name still **be the held inode**: matching the world-readable `owner_token` is
  not ownership, because any writer can rename the claim away and publish a
  different inode carrying a copy of those bytes.
- **Exact temp identities.** Every migration write publishes through a temp named
  from the journal token (`.<name>.<token>.<slot>.mtmp`) at an exact
  (parent-descriptor, name) **site**. Cleanup deletes only a verified regular
  inode created by the current transaction at one of its own sites. The same
  basename in a different directory is a different site and is never touched: it
  is unknown evidence, and unknown, wrong-directory, symlink, partial, malformed
  or conflicting evidence is always preserved and HOLD.
- **Power-loss-safe publication.** The initial journal, every stage child and the
  terminal receipt are published through an explicit prepared-temp → fsync →
  rename/`linkat` transition. The initial journal uses `linkat`, which is both
  exclusive and atomic, so a crash part-way through its bytes cannot leave a
  half-written *final* journal — a state that could be neither trusted nor
  destroyed, and which stuck the vault forever.

After apply, rerun the providerless recheck with the killswitch set again and
compare before/after hashes:

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
fresh planning and unauthenticated apply. To recover, run the explicit
providerless recovery operation with the same exact prepared-plan file/SHA-256
and consumed candidate-authority carrier:

```bash
uv run python scripts/cc-pr-review-dispatch.py --all --replay-only --migration-recover \
  --migration-prepared-plan /path/to/prepared-plan.json \
  --migration-prepared-plan-sha256 <64-hex> \
  --migration-candidate-authority-carrier /path/to/consumed-candidate-carrier.yaml \
  --migration-candidate-authority-carrier-sha256 <64-hex>
```

Valid `initializing`, `prepared`, `applied:N`, `rollback_started`, and
`rollback_failed` phases recover by exact rollback; `complete` and
`terminal_publishing` recover by exact roll-forward/finalization; `rolled_back`
verifies rollback and finalizes. `applied:N` items must equal the exact ordered
prefix of the planned operations — including each item's `preimage_sha256`,
which is bound to *its* operation's `expected_before_sha256`, so a journal cannot
name the right target while claiming bytes that target never held. Phase-
conditional fields (`error`, `rollback_error`, `journal_errors`) are refused
outside their legal phases.

The journal makes publication, cleanup, and retirement explicit phases, and the
terminal receipt is published through a deterministic temp and an atomic rename.
A successful recovery writes
`_locks/review-team-digest-migration.recovery-terminal.json`; a repeated
recovery with the same inputs returns that same terminal receipt, byte for byte,
instead of starting a fresh apply. Terminal evidence is also checked for
cross-field coherence: a target carries either a digest or a read error, never
both, and an archive that does not exist cannot carry a digest or an error.

A **partial or corrupt** terminal receipt (a torn final write) is superseded
rather than treated as a permanent conflict — otherwise recovery could never
converge — but its bytes are first **preserved** to
`_locks/review-team-digest-migration.recovery-terminal.preserved.<sha16>.json`.
Convergence is never bought by destroying evidence we could not read. Only a
well-formed terminal receipt belonging to a **different** journal identity is a
hard conflict, which is a real governance stop, not a torn write.

### Transaction result states

`applied`, `recovered` and `rolled_back` are **terminal**: the state is sealed
and there is nothing for a recovery pass to act on. `rolled_back` means the
transaction failed, the inline rollback succeeded, a `rolled_back` terminal
receipt is durable and the journal is retired — the vault is back at its
preimage. It is reported as `migration_rolled_back`, **not**
`migration_recovery_required`; the latter would point the operator at a recovery
that has no journal left to recover. `migration_recovery_required` is reserved
for genuinely unresolved transactions (for example a rollback that itself
failed, which leaves the journal in place).

Do not delete the journal to retry; preserve it with the staged files and recover
or escalate under a new governed act. A broken journal symlink or an orphan stage
path matching `_locks/.review-team-digest-migration.transaction.*.files` is also
HOLD even when the journal is absent unless the exact journal-bound recovery path
can prove it belongs to the prepared plan. An unclassified publication temp
(`.*.tmp` / `.*.mtmp`) in any effect directory is HOLD for both apply and
recovery until it is attributed or removed under a governed act.

### Provenance: a site is a location, not an identity

A `(parent descriptor, leaf name)` site says **where**, never **what**. There is
exactly **one** authority for deleting an entry: **proved entry provenance** —
this process created the inode, and `dev`, `ino`, size and digest were recorded at
creation, and the entry still names it.

Content is **not** a second authority. The protocol used to accept one — "the
journal-bound plan says which bytes belong at this site, and the bytes on disk are
those bytes, so the entry is ours" — and that is deletion from a *deterministic
location plus reproducible content*. It is not provenance. Content is evidence
about **bytes**; it is never evidence about which inode a directory entry names,
or who put it there. The plan's digests are public, and the temp names are derived
from a public grammar, so anything an unrelated writer could reproduce was
sufficient to destroy an inode the transaction had never seen.

Durable entry identity *would* license crash-recovery deletion, but this protocol
does not have it and cannot: temp inodes are created between journal phases, so an
inode created immediately before a crash could never have been recorded anywhere.
Rather than claim an attribution the protocol cannot make, the unproved inode is
**preserved**.

A fresh recovery capability starts with an **empty** provenance map by
construction: it created nothing, so it may claim nothing by name. It therefore
deletes nothing it inherits — not an unattributed temp, not a leftover stage child,
not a journal-slot temp with no journal. Every such entry is preserved instead.

Preservation is **lossless and per-entry**. The destination encodes a
**collision-resistant full identity**: the whole content digest **and** the
device/inode:

```
_locks/review-team-digest-migration.recovery-temp.preserved.<sha256>.<dev>-<ino>.bin
_locks/review-team-digest-migration.recovery-stage.preserved.<sha256>.<dev>-<ino>.bin
_locks/review-team-digest-migration.recovery-terminal.preserved.<sha256>.<dev>-<ino>.bin
_locks/review-team-digest-migration.prior-final.preserved.<sha256>.<dev>-<ino>.bin
_locks/review-team-digest-migration.displaced.preserved.<sha256>.<dev>-<ino>.bin
```

Two consequences are load-bearing:

- **Idempotence is proved by inode identity at the destination** — never by the
  name existing, and never by the digest matching. An occupied slot is re-verified,
  not believed. A slot occupied by a *different* inode gets a **distinct** slot
  (`....1.bin`, `....2.bin`); nothing is ever overwritten or unlinked to make room.
  Reuse of an existing slot **fsyncs the destination directory** even though it adds
  no entry: a link that is merely *visible* after an earlier crash is not thereby
  *durable*, and dropping the last known-durable name on the strength of an unsynced
  one loses the inode outright.
- **Distinct inodes carrying identical bytes are preserved distinctly.** They were
  previously content-addressed onto one truncated-digest destination and the second
  was unlinked as a "duplicate entry" — destroying a directory entry, an inode
  identity and a full set of metadata that the transaction had no provenance for.

A symlink or a non-regular inode at a temp site is retained and HOLDs. Convergence
is never bought by destroying bytes we cannot account for.

Every preservation is bound into the durable terminal receipt as `preserved_entries`
— and each record is **self-describing**: the exact relative source site, the exact
relative destination site, the full `sha256`, and the `dev`/`ino`/`mode`/`size` of
what actually moved. A record used to be three bare strings, which proved nothing:
a receipt could assert that an inode had been rescued to a path that was never
written, and that claim was structurally indistinguishable from a true one. The
destination name is now checked against the grammar this protocol can mint, and
wherever a live capability is available the record is **re-proved against the disk**
before it is accepted or accumulated. See *The terminal receipt describes the
terminal state* below.

### Entry transitions destroy nothing

`rename(2)` is atomic in what it **publishes** and unconditional in what it
**destroys**: if anything is at the destination, the rename silently unlinks it.
`unlink(2)` names a *path*, not an inode, so a verified identity does not bind the
entry the kernel actually removes. Every "safe" operation built on those two is a
stat followed by a syscall that does not name the thing the stat looked at — and an
entry substituted in that window is destroyed by a call that reports success. That
is not a race to be narrowed; it is a primitive that cannot express the invariant.

The protocol therefore uses the only two transitions Linux offers that destroy
nothing, through a small private `renameat2` wrapper:

- **`RENAME_NOREPLACE`** fails with `EEXIST` rather than overwriting an occupied
  destination. "The destination was absent" becomes a property of the **transition**
  instead of an earlier observation.
- **`RENAME_EXCHANGE`** swaps two entries atomically, so **both inodes still have
  names** afterwards.

There is no portable fallback and none is attempted. A kernel or filesystem without
these flags cannot perform a non-destructive transition at all, so the protocol
**fails closed** (`migration_transaction_renameat2_unavailable:<reason>`) rather than
silently degrading to the overwriting rename it was built to replace.

Everything follows from that:

- **Publication** uses NOREPLACE when the destination is absent and EXCHANGE when it
  exists. Preserving the destination we *observed* never protected the destination we
  *consumed* — a final replaced between the classification and the rename was
  destroyed, and publication reported success. Now the displaced entry always keeps a
  name. If it is the final we classified and linked aside, it is legitimately
  superseded; if it is **anything else**, it is preserved with full evidence and the
  transaction **HOLDs**.
- **Cleanup is a move, never an unlink — and never a delete at the end of it either.**
  When a name must be cleared, the entry is renamed (NOREPLACE) to a private
  retirement name *first*, then judged, then renamed again onto a durable,
  identity-derived landing name. The private name is not a capability: it is an
  ordinary visible directory entry another same-owner process can stat and replace,
  so nothing rests on it being unguessable. Both transitions are NOREPLACE renames,
  which cannot overwrite and cannot destroy, so whatever the final syscall consumes
  **survives** — an entry proved to be an inode this transaction created lands as
  **reclaimable**, anything else lands as **preserved**, and there is no third
  outcome in which an entry ceases to exist. There is no destructive pathname syscall
  (`unlink`/`rmdir`) anywhere in the governed lock/claim/migration surface; a
  regression parses the module and fails if one reappears.
- **A cleanup may report success only after re-checking that its source site is
  absent.** The move consumes the entry atomically; if something is at the name
  afterwards it is a *new* entry, and the protocol HOLDs
  (`migration_transaction_cleanup_source_reoccupied`) rather than claiming a
  convergence it did not reach. **No replacement inode is ever deleted to make state
  converge.**
- The same rule covers archive moves, rollback restores (an EXCHANGE, since the
  target legitimately exists), journal retirement, lock release, temp retirement,
  preservation cleanup and stage removal. `rename_child` now *requires* the identity
  the caller proved; several rollback call sites previously omitted it entirely.
- **Wrong-kind destinations are refused before any transition can reach them.** A
  symlink or directory at a publication destination cannot be linked aside — there is
  no inode to link and no digest to address it by — so publication HOLDs
  (`migration_transaction_publication_prior_final_wrong_kind`) instead of renaming
  over it.

### Writes are complete, and publication is by descriptor

`os.write` may accept fewer bytes than it is offered and report exactly that,
without raising: a short write is a legal, silent, successful return. Every temp
is therefore written by a loop that retries `EINTR`, advances on any positive
count, fails closed on zero progress, and finally confirms the inode's size — so a
writer that claims a full count while landing fewer bytes is caught **before**
anything is published. Nothing is published until the exact intended byte count is
written and fsynced.

Publication is anchored to the **descriptor**, not the name. `rename(temp, final)`
names its source, so an inode swapped in at the temp name after creation would be
published as ours while the authorized inode survived under a moved name. Instead
the created inode — held open since `_create_temp` — is `linkat`'d from
`/proc/self/fd/N` to a staging entry (which provably names *that inode*, whatever
the temp name now points at), the staging entry is renamed over the final, and the
final is then re-verified to name the recorded inode. If the platform cannot
supply that proof (no `/proc`, or the inode has no link left to make), publication
**fails closed** rather than renaming an unproven name and calling the result its
own.

**Publication failure is non-destructive.** Linux exposes no rename that names its
source by *inode*, so a substitution at the staging entry cannot be *prevented* by
the transition — only detected after it. What **can** be made total is the
consequence. The prior final is linked aside first (an extra name, not a move, so
the transition is still the atomic old-complete-to-new-complete replacement the
protocol depends on — a crash anywhere in the sequence leaves a complete final,
never a gap), and the transition itself is non-destructive (see *Entry transitions
destroy nothing*). Then:

- publication lands and the final is verified to name the authorized inode → the
  transitional preservation link is retired, on identity;
- the final names **anything else** → the old inode survives under its preservation
  link, the uncertain inode survives at the name, **both** are retained, and the
  transaction **HOLDs**.

The **exclusive** path (the initial journal) is verified the same way. A successful
`linkat` proves what was published *at that instant*, not what is there when it
returns; the path used to stop at the syscall and report success, so a final moved
aside and replaced immediately after the link was reported as this transaction's
own. The published entry is now re-verified, and on mismatch the temp holding the
authorized bytes is deliberately **not** retired — it is the only inode carrying
what the transaction meant to publish. Both survive; the caller HOLDs.

The same identity rule extends to the generic helpers, and none of them reaches a
destructive syscall through a public name. `rename_child` (NOREPLACE) requires the
identity the caller proved and refuses an occupied destination; `restore_child`
(EXCHANGE) restores over a destination that legitimately exists and adjudicates what
it displaced; `clear_name` moves a regular file to a private retirement name before
judging it. `retire_stage` is where the difference between an identity and a
guarantee matters most. A directory record binds kind, inode and mode and says
nothing about **contents**, yet the one claim the stage record exists to make —
`emptied_stage_dir` — is entirely a claim about contents. Binding only the
descriptor identity therefore left a gap: cleanup enumerated the stage, the name was
consumed, the directory was minted reclaimable on identity alone, and a child
created in the window between the enumeration and the move survived *inside* the
retained directory while the record said it was emptied. `retire_stage` now consumes
the stage name into an identity-derived in-flight retirement name and then
**re-enumerates the moved directory through the descriptor opened at `open_stage`**,
which names the stage inode and keeps naming it across the rename. A late **regular**
child is moved out to a self-describing preserved entry (`late_stage_child`) and
recorded in the retention ledger; a late **symlink, nested directory or device** is
not followed, not deleted, not hidden and not sealed — it stays where it is, the
directory stays alive at its in-flight retirement name, and the transaction **HOLDs**.
Only a directory proved empty through that descriptor is landed as reclaimable.

This is the explicit **cooperative-writer boundary**, and its edge is worth stating
exactly. The by-name injection window — a process reaching the stage through its
public pathname at the instant of the consuming rename — is closed on both sides:
the descriptor re-enumeration moves the late child out before the record is minted,
and the terminal decoder re-proves the directory empty against the live root at seal
time and at every reuse, so kind/inode/mode agreement is no longer sufficient to
accept the record. The residual case is a foreign writer that *already holds a
descriptor* on the stage directory and creates a child through it **after** the
final re-enumeration: that is a genuine concurrent-writer race, and it is out of
contract for the same reason every other temp-name mutation under the held migration
lock is. The protocol does not claim atomic emptiness against such a writer — the
stage inode has no lock of its own — only that it never *records* an emptiness it did
not prove and never seals a state a later live recheck would reject. Emptiness here
is a cooperative-writer guarantee, not a kernel-atomic one.

### The terminal receipt describes the terminal state

The receipt is the durable, digest-bound account of what the transaction left on
disk, so two things must hold before it is published.

**It is sealed from the root the effects mutated.** Terminal evidence is read
through the same held `MigrationRootCapability` descriptors the writes went through
— never by re-reading an absolute pathname, which is re-resolved through a mutable
namespace on every use. A vault directory swapped out *after* the capability was
opened previously produced a sealed, digest-bound, internally coherent receipt
describing a directory the transaction never touched. Evidence read through a
different root than the effects is not evidence. The pathname is still reported, as
a **label** for the operator; it is never the thing that was read.

**It is published only after reconciliation has converged.** Stage cleanup, late
stage-child reconciliation and temp reconciliation all run first, and everything
they had to preserve is bound into the receipt as `preserved_entries` before it is
sealed and before the journal is retired. The receipt previously asserted
`cleanup_result: stage_cleaned` over a directory whose unattributed temps had not
yet been looked at, and whatever reconciliation then preserved existed only in an
in-memory return value that died with the process. It later asserted
`emptied_stage_dir` over a directory that still held a child created after cleanup
enumerated it — a claim proved only against the directory's inode, never its
contents. Both are the same failure: a terminal receipt that omits, or misdescribes,
what recovery could not account for is a receipt reporting a clean convergence it did
not achieve. The reclaimable stage-directory record is now re-proved **empty**
against the live root at seal time, and a proved-late regular child rides into the
receipt as a `late_stage_child` preserved entry rather than surviving invisibly.

**An interrupted retirement is rediscovered, not stranded — and adoption is bound to the
particular stage object, not to shape or to a public token.** Proving the moved directory
empty means enumerating it, so the window between the rename that consumes the stage name
and the rename that lands it as reclaimable now spans real work; a crash inside it must
converge on retry. The in-flight name states both the inode it holds and the **journal
token** of the transaction retiring it (`…retired.stage-dir.<token>.<dev>-<ino>.dir`), but
neither is self-authenticating. The inode is self-consistent by construction — a forger
derives exactly that identity from the directory it just made — so it proves what the
directory *is*, never that a transaction retired it; and the token is **public, readable
correlation**, so it says which transaction the name *claims*, not that the claim is true.
So adoption of `emptied_stage_dir` is gated on **two** facts checked against the live
journal: the embedded token must match (a fabricated directory carries no live token, an
unrelated transaction's carries the wrong one), **and** the embedded and live device/inode
must equal the **stage identity the journal recorded** — the durable pre-move intent the
journal binds and fsyncs the moment the stage exists, before the stage can be moved. That
identity is **bound into `journal_identity_sha256`** the moment the stage exists, so it is a
recomputable journal relation rather than an optional undigested claim: a load recomputes the
digest from the journal's own fields and **rejects a journal whose `stage_identity` was
rewritten while the digest was left unchanged**, and the recovery recheck additionally anchors
the digest's base fields to the plan and authority the transaction was admitted under, so a
substituted stage identity never reaches adoption (V12-PROBE-81). A journal that records a
`stage_identity` in the `initializing` phase — before its own phase says the stage exists — is
incoherent and rejected; `prepared`, `applied:N`, `complete`, and `terminal_publishing` without
one are equally incoherent and rejected. The writer captures that identity once after stage
creation and keeps it after descriptor detach, so the terminal publication and terminal receipt
cannot regress to an unbound digest after stage retirement (V12-PROBE-83 / V12-PROBE-84). A
fabricated well-shaped directory that adopts the *live* token still
carries its own inode, which this transaction never created, so it fails the identity bind and
stays visible as a typed HOLD (V12-STATIC-29 / V12-PROBE-78). Absent or malformed recorded
identity is unknown provenance and denies adoption rather than falling back to shape. A regular file stranded
at an opaque `…retired.<hex>.bin` name — the other half of an interrupted `clear_name` — is
swept the same way and **preserved** (`interrupted_clear`), never reclaimed, and needs
neither gate because preservation mints no authority. Reconciliation is entered from the
**providerless recovery path itself**, before a terminal result can be reused or a
missing/unreadable journal can return, so a stranded clear is never stepped over. A second
recovery over converged state finds neither in-flight grammar occupied, records nothing,
and seals byte-identical terminal state.

**A landed retention is reconstructable from durable state, and it has a production
consumer that accounts for it or HOLDs.** A clear *lands* a self-describing
preserved/reclaimable name and only then records it in the in-memory ledger, so a process
stop between those two steps must not lose the relation: the record is re-derived from the
durable name and the live inode alone — never from a Python list append that may have been
skipped. The grammar only *locates* a candidate; corroboration proves it against the live
**device, inode and content digest** together, and does so through a **single** open of the
name on the held lock descriptor (`O_NOFOLLOW`): the device/inode come from an `fstat` of that
one descriptor and a file's digest is read from the *same* descriptor, so there is no
stat-then-reopen seam. A field the name encodes is never validated by halves — a false device
fails corroboration exactly as a false inode or digest does (V12-STATIC-30 / V12-PROBE-79) —
and because identity and digest are one resolution, a same-content inode swapped in between an
earlier stat and a later open can no longer be reported corroborated while the record credits
the original inode (V12-PROBE-80). An entry whose live identity does not back its name is
reported uncorroborated, stays visible in the evidence manifest, and never mints reclamation
authority. Crucially, this reconstruction is no longer reachable only from a status
enumerator a test calls by hand: `MigrationRootCapability.landed_retention` runs it through
the **held** root, and `unaccounted_transaction_retention` is consumed by the **recovery
seal, terminal reuse, and the pre-effect boundary** alike. A corroborated *transaction*
retention that no durable relation names — the lost-append record — is exposed and produces
a typed HOLD at each of those boundaries rather than being sealed over or stepped past
(V12-STATIC-27 / V12-STATIC-28 / V12-PROBE-77). What counts as "named" is proven, not assumed:
at the pre-effect boundary the existing terminal receipt is **decoded through the same held
root by the one complete terminal decoder and live-reproved**. It also revalidates the receipt's
persisted candidate-authority payload against the exact consumed carrier, carrier evidence,
operator act, and prepared-plan relation. Only then are the preserved, reclaimable and
reconstructed destinations projected into the accounted set. So the boundary holds **only** on a
corroborated transaction retention that a *valid durable and authority-proven seal* does not name
— a retention a prior successful recovery already sealed is accounted, not re-read as unsealed,
and does not permanently wedge the next migration behind it (V12-PROBE-82). A structurally valid
standalone receipt with plausible hashes is integrity evidence, not authority; legacy receipts
remain readable but credit no retention unless that carrier relation is present and revalidated
(V12-PROBE-85). A missing, malformed or foreign receipt is likewise credited nothing, so the
retention it fails to account for still HOLDs. A legitimate lock-claim retention, told apart by
its durable prefix rather than by timing, is a different lock's residue and does not block.
Filenames locate; the live inode proves; and a retention nobody governs is made to HOLD, not
hidden.

**It is read back through the capability too.** The loader used to re-read the
receipt by absolute pathname while the effects had landed in a held descriptor, so
replacing the vault pathname with a directory containing a well-shaped receipt made
the loader accept it — with `error=null` — even though the root the transaction
actually mutated had no receipt at all. Classification and evidence must name **one**
root.

Re-running recovery over its own terminal state is a no-op: identity is compared on
the receipt **core** (everything but `preserved_entries`), and the preserved set is
*accumulated* across passes rather than recomputed by the last one — otherwise a
second pass would find nothing left to preserve, read that as a different terminal
state, preserve the perfectly good receipt it had just written, and never converge.

**Core-equality is not validity.** An existing receipt may be adopted as this
transaction's own durable state only after it passes the **same complete loader** a
reader applies — schema, exact keys, canonical bytes, target coherence, and every
preservation claim re-proved against the live root. Reuse was previously decided by
a bare core comparison over a `json.loads`, so a receipt that merely agreed on the
core keys — and asserted that a *nonexistent* path had preserved an unattributed
temp — was adopted whole, and its unproved claim was inherited and re-sealed. A
merely core-equal document contributes **nothing**.

### Stage entries are classified, never filtered

Stage-name enumeration is **by name only**. Classification is a separate, explicit
step: every entry matching the transaction stage grammar is reported as
`directory`, `regular`, `symlink` or `other`. Only the directories can be attached
to and driven; every other kind is an explicit blocker
(`migration_transaction_stage_entry_wrong_kind:<name>:<kind>`) **and** appears in
`stage_paths` / `stage_entries`.

The enumerator used to drop every non-directory silently, so a regular file sitting
at an exact, valid stage name — the strongest possible evidence that a transaction
ran here and left something nobody can explain — was invisible: no blocker, no
evidence path, nothing, and recovery reported only `journal_missing` over the top
of it. A type filter in an enumerator does not classify uncertain evidence; it
hides it.

### One root, one decoder

Recovery reads the journal, enumerates stage directories and classifies terminal
evidence **through the same held `MigrationRootCapability` descriptors it mutates**.
Loading the journal by absolute pathname re-resolved `vault/_locks` through the
mutable namespace on every read, so a directory swapped in after the capability was
opened could supply the journal that recovery *classified* while every effect
recovery then performed landed in the held root — two directories, one decision. A
swapped vault pathname is now either detected or simply irrelevant.

The prepared plan has exactly **one** decoder,
`shared.sdlc_lifecycle.decode_prepared_migration_plan`. Every nested exact-key set,
scalar kind, enum, protocol constant, digest, byte representation and cross-field
relation lives there once, and both admission surfaces — runtime apply and
lifecycle artifact admission — run it over the same decoded object, reporting the
same named reasons. The runtime adds **only** filesystem evidence checks
(vault-root path admission, on-disk digests); it may not add a second semantic or
type decoder, because a check that only one surface runs is a check the other
surface can be walked straight past.

The decoder is **total over every plan-owned nested object**. "It is a mapping" is
not a schema: `counts.rebound = "wrong-type"` and
`source_trust_anchor = {"arbitrary": []}` both decoded with no blockers for as long
as those objects were admitted by container shape alone. Each now carries an exact
key set, scalar kinds, enums and cross-field relations, and the derived ones are
**recomputed rather than believed**:

| Object | How it is closed |
|---|---|
| `migration.counts` | exact classification keys; recomputed from `migration.entries` |
| `migration.entries[*]` | exact keys, classification enum, reason↔classification relation, basename/relpath relations |
| `entries[*].legacy_admission` | exact keys; present **iff** the entry is exact-hash preserved; route/classification/head/anchor all pinned |
| `migration.next_actions` | exact keys; values are protocol constants |
| `migration.authority`, plan `authority` | exact keys, scalar kinds, ISO instants |
| `source_trust_anchor` (all three sites) | exact keys **and exact values** — it names the reviewed proposal the whole legacy route rests on |
| `sealed_generation` (all sites) | exact keys, ISO `sealed_at`, git-SHA `source_head_sha` |
| `current_receipt_drift[*]` | exact keys, status enum, `actual_receipt_sha256` present iff `sha256_mismatch` |
| `artifact_preflight` | exact keys, status enum, nested sealed generation |
| `evidence_manifest.{source_trust_anchor,artifact_preflight,lock_transition,planned_writes,paths}` | exact schemas — they were *required keys read by no decoder*, which is a key set, not a schema |
| `paths[*]` and every `target_preimage.evidence` | exact file-evidence schema, **including** the `entries` directory listing |
| `open_pr_results[*].migration_claim` | exact keys, status enum, exact `lock_evidence`/`stat` schemas |
| `receipt_writes[*].payload` | bound byte-exactly **and decoded under the real acceptance-receipt schema** |
| `migration.candidate_payload` | full artifact schema, plus every disposition-bearing object must be identical to the migration's |
| `candidate_payload.candidate_authority` | must equal the **ratified** candidate authority in artifact form, including its exact self digest |
| `generated_at` (plan, migration, artifact) | valid **aware ISO instants**, not merely nonempty strings |
| `plan_binding_core.{disposition_manifest,write_set,evidence_manifest}` | recomputed from the plan's own contents |

**Duplicated objects must agree.** A plan carries its authority, its preflight and
its lock transition in up to four places. Each was decoded against its own schema and
none against the others, so a plan could be internally well-typed while its manifest
described one authority, its migration a second and its artifact a third — and only
one of them is the object the ratified digests actually cover. Where two objects
overlap they must be equal; where one is a projection (the manifest's authority
carries a subset of the plan authority's keys) the projection must agree on every key
it carries. This is a **totality** check, not a tamper check: the digest chain already
catches edits made *after* ratification, but the operator ratifies a digest, not a
semantic review of every object the plan duplicates.

**Authority boundaries.** A field may be left uninterpreted **only** with a written
reason, and only when it satisfies all three: the protocol does not author the
document (it *observes* a foreign one), apply never reads it to decide an effect,
and its bytes are digest-bound into something the operator ratified. Those fields
are enumerated in `PREPARED_PLAN_AUTHORITY_BOUNDARIES` — the observed task-note
frontmatter, the observed body of an existing receipt, the replay side-effect
reports, and the lock-holder document of *another* process's migration claim. They
are still **totally typed**: `json_mapping` / `json_document` admits a JSON value tree
(string keys, bounded depth, JSON scalars) and nothing else — not a tuple, not a
datetime, not a non-string key, and **not NaN or the infinities**, which Python's
`json` will happily emit and read back but which are not in the JSON value domain the
boundary claims to enforce. Declaring a field opaque is a decision with a reason
attached; it is never the absence of one.

The candidate artifact is likewise one object, not three claims. `candidate_payload`,
`candidate_raw_bytes_hex`, the exact YAML bytes, the candidate artifact SHA-256 and
the candidate artifact **core** SHA-256 are all re-derived from the payload parsed
back out of the plan's own candidate bytes, and must agree in the migration, the
binding core and the candidate authority. A plan that merely agrees with itself —
tampered bytes re-digested, or a payload edited while every digest claim is left
intact — is rejected. Self-consistency is not evidence.

The artifact's **embedded** `candidate_authority` needs its own relation, because it
is deliberately **excluded** from the core digest (the authority is computed *over*
the core, so it cannot also be inside it). That exclusion was load-bearing and
unguarded: rewriting the embedded authority to an unrelated object, then recomputing
the candidate bytes and the candidate *file* digest, left the core digest and every
ratified binding untouched — and the plan decoded clean. It is now pinned by relation
to the ratified candidate authority in its exact artifact form.

Recovery is verified against real, uncatchable `SIGKILL` delivered **inside** each
durable syscall — part-way through the payload bytes of `write`, and inside
`fsync`, `rename`, `linkat`, `unlink` and the directory fsync — at several
occurrences each, which walks the kill across the journal, the stage children,
every `applied:N` boundary, the archive rename, the target publications and the
terminal seal. Substitution is exercised the same way: a probe plants a replacement
**inside** the transition syscall itself (at the `renameat2` boundary), which is the
window every destructive primitive in this protocol used to lose an inode in. Killing *after* a write helper returns proves nothing: it can only
observe states the helper already made atomic and durable, which is the property
under test. After any such kill the tree is either recoverable to a terminal
state or already terminal; targets are either the exact preimages or the exact
prepared outputs, never anything in between; no orphan temp survives; and a
second recovery pass changes no byte.

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
