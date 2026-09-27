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
| key namespace | `task:<id>` and/or `path:<absolute note path>` — a writer may take either or both |
| digest | SHA-256 of the key, `.lock` suffix |
| lock root | `coord_base_dir()/task-locks` (moves with `HAPAX_COORD_DIR`) |

## Properties you can rely on

- **Per task, not global.** Contention on one note does not delay writers of another. An early
  revision held the lock root exclusively while polling a contended key, which made one busy note
  refuse every unrelated note in the estate; pinned against regression by
  `test_contention_on_one_task_does_not_stall_an_unrelated_task`.
- **No hold-and-wait, among projected-path locks.** A writer that cannot take every key it needs
  releases what it took, waits, and retries the whole attempt. No wait cycle can form among these
  locks, whatever other participants do. **Composed with the claim path's role lock, the property
  is an acquisition order** — role-then-note — and it is enforced at the moment of use, not by
  convention: `_claim_publication_lock` refuses with `claim_publication_lock_order_inversion` if
  the calling thread already holds any projected-path lock. If you are writing code that holds a
  note lock and needs to publish a claim, release the note first; there is no third option.
- **Re-entrant per thread, but not expandable.** Nesting the same keys is fine. A nested
  acquisition that *adds* a key is refused (`task_note_lock_expansion_under_hold`) — that is the
  one shape all-or-nothing cannot make deadlock-free, because an outer frame's keys cannot be
  released. Name every key in the outermost call.
- **Bounded.** `HAPAX_TASK_NOTE_LOCK_TIMEOUT` (seconds) tunes the wait; the gate uses 5s because
  it runs inside a tool-call hook. Malformed, negative, `inf` and `nan` all fall back to the
  30s default — a bad knob must not be able to wedge every writer in the estate.

## What it does NOT cover

**Daemon and one-shot writers listed in `KNOWN_UNCONVERTED`.** The nine writers a session
actually runs are inside the domain — `cc-stage-advance`, `cc-scope-widen`, `cc-task-repair`,
`cc-task-offer-ready`, `cc-cascade-unblock`, the gate stamp, `cc-task-pr-link`, `cc-close`, and
claim publication (`cc-claim` via `shared/sdlc_claim.py`, plus its documented legacy fallback).
What remains are daemons, reconcilers and one-shot migrations.

The full inventory is machine-checked in
`tests/shared/test_projected_path_writer_lock_coverage.py`: every file the three search shapes
reach must be classified as under the lock, not a note writer, or unconverted with a named owner.
Adding a writer without classifying it fails CI, and the sweep asserts it still finds its own
known writers so it cannot pass by finding nothing.

**Two notes on how `cc-claim` and `cc-close` got here**, because the shape matters more than the
outcome. Claim publication holds a lock keyed by the *role*, under a different root; the
projection lock is taken **inside** it, so the order is always role-then-note. That order is the
whole deadlock argument across the two domains, and it is asserted where it can be broken: the
role lock refuses when its caller already holds a projected-path lock (see the property above).
A test drives both orders and expects the inversion to be refused before the role lock is
touched; the site-count assertion that preceded it is kept as a containment check, not as the
enforcement, because the inversion that matters needs no new site. And `cc-close` is the only writer that
*unlinks* a projected path, so it locks both the source it removes and the destination it
installs.

`shared/sdlc_close.py` still has no production caller — it is correct and unwired, while
`scripts/cc-close` is the live closer. That, and the remaining daemon writers, are owned by
`claim-close-writers-outside-the-projection-lock-domain-20260916`.

**A lock file removed while a section is held.** `_verify_identity` protects an *acquirer* at
acquisition, not an *incumbent* for the duration. So:

> **Anything that removes files from the lock root must take the root `LOCK_EX` first.**

Acquirers hold the root `LOCK_SH`, so a reaper taking it exclusively waits for every in-flight
critical section. Nothing in the estate removes lock files today; the protocol is written down so
that the day something does — a cache sweep over `coord_base_dir()`, a recovery reaper, a hand-run
`rm` — it has a rule to follow rather than an assumption to break. The recheck section below has
a pasteable probe that demonstrates the exclusion actually holds.

## The bypass is `HAPAX_COORD_DIR` — and it is the dangerous one

An earlier draft of this runbook said there was deliberately no bypass. That was wrong in the
dangerous direction. The lock root is `coord_base_dir()/task-locks`, and **`HAPAX_COORD_DIR`
moves it**: a writer invoked with a different value takes a *different* lock and excludes
nothing, silently. An undocumented escape hatch is worse than a documented one, because the
people who trip it are not the people who chose it.

- **`HAPAX_COORD_DIR` splits the lock domain.** Every participant that must exclude the others —
  each converted writer, the gate stamp, claim publication, every lifecycle transition — has to
  resolve the *same* root. It is the emergency route out of a wedged or unusable lock root, and
  its hazard is exactly the fail-open this lock exists to close.
- **`HAPAX_TASK_NOTE_LOCK_TIMEOUT` is not a killswitch.** It tunes the wait; `0` refuses sooner,
  it never admits. A malformed, negative, `inf` or `nan` value falls back to the 30s default
  **and says so on stderr**, so nobody reasons about a timeout that was never in effect.

Order of preference when the root is unusable:

1. Repair the root (`chmod 700`, fix the mount, remove a foreign-owned directory).
2. If it cannot be repaired, move `HAPAX_COORD_DIR` **for the whole estate at once** — never for
   a single writer, which is what silently splits the domain.

```bash
# Is the domain whole right now? Both must print the same path.
uv run python -c "from shared.coord_projection import _lock_root; print(_lock_root(None))"
uv run python -c "from shared.task_note_lock import default_lock_root; print(default_lock_root())"
```

## Recheck commands

Every claim above is pinned by a test. These are the commands, not the test names:

```bash
# Per-task granularity: one contended task must not delay an unrelated one.
uv run pytest tests/shared/test_task_note_lock.py::test_contention_on_one_task_does_not_stall_an_unrelated_task -q

# No hold-and-wait: opposite acquisition orders, concurrently, must both complete.
uv run pytest tests/shared/test_task_note_lock.py::test_no_lock_is_held_while_another_is_wanted -q

# The composition with the role lock: note-then-role is refused before the role lock is opened.
uv run pytest tests/shared/test_task_note_lock.py::test_the_role_lock_refuses_while_this_thread_holds_a_projected_path_lock -q

# The gate's 5s bound actually reaches the interpreter (asked, not read from the source).
uv run pytest tests/shared/test_projected_path_writer_lock_coverage.py::test_the_gate_s_lock_bound_reaches_the_interpreter -q

# A real lifecycle transition cannot enter a writer's window.
uv run pytest "tests/shared/test_projected_path_writer_lock_coverage.py::test_a_real_lifecycle_transition_cannot_enter_a_writer_s_window" -q

# The inventory: every writer the sweep reaches is classified, and the sweep still works.
uv run pytest tests/shared/test_projected_path_writer_lock_coverage.py -q

# The whole domain, including the transition mapping and the role/note ordering.
uv run pytest tests/shared/test_task_note_lock.py tests/shared/test_projected_path_writer_lock_coverage.py -q

# The reaper contract, by hand: hold a lock in one shell, then confirm an exclusive
# root acquisition blocks until it is released.
uv run python - <<'EOF'
from pathlib import Path
from shared.task_note_lock import default_lock_root, projected_path_lock
import fcntl, os, time
with projected_path_lock("probe-task", (), timeout=5.0):
    fd = os.open(default_lock_root(), os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print("REAPER GOT THE ROOT WHILE A SECTION WAS HELD — contract broken")
    except BlockingIOError:
        print("ok: a reaper taking LOCK_EX waits for the in-flight section")
    finally:
        os.close(fd)
EOF
```

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

**Scratch-class recovery-sweep discovery.** Work item 1 pre-registered recovery-sweep discovery
of every scratch class, not only `scratch.path.name`. Fallback B (PR #4667,
`coord-projection-nfs-fallback-20260913`) introduces three classes — pin, holding, spent — with
random transition names the current glob (`.*.transition-scratch`) does not discover. That half
of the inventory is deferred, not silently absent: the three classes are listed in
`SCRATCH_RECOVERY_DEFERRED` in `tests/shared/test_projected_path_writer_lock_coverage.py`, and a
new class without a classification fails CI. Owner: `coord-projection-nfs-fallback-20260913` on
landing fallback B.
