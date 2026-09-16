# The projection lock domain

One lock guards every mutation of a projected task-note path, and the same lock guards the
transactional relocation of that note. This is the operator-facing statement of that contract:
what it covers, what it does not, and what to do when it refuses.

Implementation: `shared/task_note_lock.py`. The transition's `coord_projection._transition_locks`
is a call into it, not a second implementation.

## The contract

*Independent mutators of a document must take the same exclusion the document's transactional
relocator takes, keyed by document identity.* Stated without estate nouns, that is the whole
architecture; everything below is a binding, and each is swappable:

| binding | today |
|---|---|
| exclusion mechanism | `flock` on one lock file per key |
| key namespace | `task:<id>`, `path:<absolute note path>` |
| digest | SHA-256 of the key, `.lock` suffix |
| lock root | `coord_base_dir()/task-locks` (moves with `HAPAX_COORD_DIR`) |

## Properties you can rely on

- **Per task, not global.** Contention on one note does not delay writers of another. An early
  revision held the lock root exclusively while polling a contended key, which made one busy note
  refuse every unrelated note in the estate; pinned against regression by
  `test_contention_on_one_task_does_not_stall_an_unrelated_task`.
- **No hold-and-wait.** A writer that cannot take every key it needs releases what it took, waits,
  and retries the whole attempt. No wait cycle can form, whatever other participants do.
- **Re-entrant per thread, but not expandable.** Nesting the same keys is fine. A nested
  acquisition that *adds* a key is refused (`task_note_lock_expansion_under_hold`) — that is the
  one shape all-or-nothing cannot make deadlock-free, because an outer frame's keys cannot be
  released. Name every key in the outermost call.
- **Bounded.** `HAPAX_TASK_NOTE_LOCK_TIMEOUT` (seconds) tunes the wait; the gate uses 5s because
  it runs inside a tool-call hook. Malformed, negative, `inf` and `nan` all fall back to the
  30s default — a bad knob must not be able to wedge every writer in the estate.

## What it does NOT cover

**`cc-claim` and `cc-close` are outside this domain.** They are the two highest-frequency note
writers in the estate:

- claim publication holds a lock keyed by the *role*, under a different root
  (`shared/sdlc_claim.py`), and calls `coord_projection._apply_projections` directly — which takes
  no lock of its own;
- the live close is `scripts/cc-close` moving `active/ → closed/` itself, unserialized, ending in
  `path.unlink()` on the active note. The correctly locked `shared/sdlc_close.py` has no
  production caller.

The full inventory is machine-checked in
`tests/shared/test_projected_path_writer_lock_coverage.py`: every file the sweep reaches must be
classified as under the lock, not a note writer, or a known-unconverted hazard with a named owner.
Adding a writer without classifying it fails CI.

Owner of the remainder: `claim-close-writers-outside-the-projection-lock-domain-20260916`.

**A lock file removed while a section is held.** `_verify_identity` protects an *acquirer* at
acquisition, not an *incumbent* for the duration. So:

> **Anything that removes files from the lock root must take the root `LOCK_EX` first.**

Acquirers hold the root `LOCK_SH`, so a reaper taking it exclusively waits for every in-flight
critical section. Nothing in the estate removes lock files today; the protocol is written down so
that the day something does — a cache sweep over `coord_base_dir()`, a recovery reaper, a hand-run
`rm` — it has a rule to follow rather than an assumption to break.

## There is no bypass, deliberately

`HAPAX_TASK_NOTE_LOCK_TIMEOUT=0` refuses sooner; it does not admit. The estate documents
per-invocation bypasses for comparable machinery (`HAPAX_GATE0B_CLAIM_PUBLICATION_OFF`), and this
one has none on purpose: a bypass here would write a task note *while a transition holds it*,
which is the exact fail-open the lock exists to close. A failure path may do less than the
primary; it may not do something else instead.

If the lock root is unavailable, every converted writer refuses with
`task_note_lock_root_unavailable` or `task_note_lock_root_unsafe` and a next action. That is a
legible estate-wide stop rather than a silent estate-wide corruption. Repair the root.

## When a writer refuses

| reason code | meaning | next action |
|---|---|---|
| `task_note_lock_timeout` | someone else holds this note | retry; if it persists, `fuser -v "$(echo ${HAPAX_COORD_DIR:-~/.cache/hapax/coord})/task-locks"/*.lock` |
| `task_note_lock_expansion_under_hold` | nested acquisition added a key | take every key in the outermost call |
| `task_note_lock_root_unsafe` | lock root is not a euid-owned mode-0700 directory | `chmod 700` it, or remove a foreign-owned root |
| `task_note_lock_root_unavailable` | a component is missing, a symlink, or not flock-able | repair the path; do not point the root at a shared directory |
| `task_note_lock_file_unsafe` | the lock pathname is not a plain single-link mode-0600 file | remove the impostor at that path |
| `task_note_lock_identity_changed` | the lock file was swapped under us | something is removing lock files — see the reaper contract above |

Transitions translate these into `transition_lock_*` codes; the map is asserted total in
`tests/shared/test_task_note_lock.py`, so an unmapped code surfaces as
`transition_lock_unclassified` carrying the real one rather than as a wrong diagnosis.

## Deferred

The ratified NFS-fallback design still records "concurrent writers are out of contract", which
this work falsifies. That text lives only on the `coord-projection-nfs-fallback-20260913` branch
(PR #4667) — `origin/main` has neither the residual list nor the function it hangs on — and the
projection-lock row **precedes** #4667 by the 2026-09-14T00:38Z sequencing inversion, so it cannot
be corrected from here without inverting that. It is corrected in #4667's rebase, together with
the re-scoped R1: *closed for writers that take the projection lock, open for those that do not.*
