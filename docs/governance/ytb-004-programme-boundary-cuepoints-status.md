# YTB-004 Programme-Boundary Cuepoints — Reconcile Status

**Status:** Normative. The cc-task `ytb-004-programme-boundary-cuepoints`
acceptance criterion **(1) "Emit programme-manager JSONL events for
boundary transitions"** is **already satisfied** by the production
`programme_outcome_log` writer (Phase 9 Critical #5 / B3 audit). The
remaining work is exclusively on the **consumer side** — the
`live_cuepoints/consumer.py` tailer needs a multi-file walker for the
per-show / per-programme JSONL tree at
`~/hapax-state/programmes/<show>/<programme>.jsonl`. The two stale
docstring claims in `agents/live_cuepoints/consumer.py` lines 14-16
and 252-258 (which asserted "programme_manager emits only Prometheus
counters, not a JSONL surface") have been updated in this PR to
reflect reality and point at this status doc.
**Scope:** the cc-task's four acceptance criteria + the two stale
docstring claims in `agents/live_cuepoints/consumer.py`.
**Driver task:** `ytb-004-programme-boundary-cuepoints` (cc-task,
WSJF 4.8). Companion to PRs #1953, #1963, #1969, #1979 in the
docs-led status-doc family.

---

## 1. The decision

Three options were available per the cc-task spec: (a) implement the
full producer + consumer + tests path now, (b) defer with concrete
blockers, or (c) split — landing whichever portion is already done as
a confirm-and-document, deferring the rest.

**Decision:** (c) — split.

**Why:** an audit of `agents/programme_manager/manager.py` and
`shared/programme_outcome_log.py` shows that the JSONL emission half
of the cc-task is already shipped. The remaining work is genuinely
non-trivial (multi-file walker + per-file cursor + dedup) and
benefits from being scoped as a stand-alone follow-up cc-task with
its own acceptance criteria rather than rolled into the same PR as
the docstring fix.

---

## 2. What's already shipped (Producer side — cc-task acceptance #1)

### 2.1 The JSONL writer

`shared/programme_outcome_log.py` (240 LOC + tests in
`tests/shared/test_programme_outcome_log.py`) ships the
production-grade outcome log:

- **Path:** `~/hapax-state/programmes/<show_id>/<programme_id>.jsonl`
- **Schema (`record_event`):**
  ```json
  {
    "event": "started" | "ended_planned" | "ended_operator" | "ended_emergent" | "ended_aborted",
    "emitted_at": "<ISO 8601 UTC>",
    "programme_id": "<id>",
    "show_id": "<parent-show>",
    "role": "<programme-role>",
    "planned_duration_s": <float>,
    "elapsed_s": <float | null>,
    "metadata": {<caller-supplied>}
  }
  ```
- **Rotation:** 5 MiB per file, 3 generations retained
  (`.jsonl` / `.jsonl.1` / `.jsonl.2`).
- **Atomic append:** sub-PIPE_BUF write under threading lock —
  matches `AttributionFileWriter` posture.
- **Defensive:** every public method tolerates filesystem failures
  by logging at `WARNING` and returning. The lifecycle path never
  breaks on disk-full or permission errors.

### 2.2 The lifecycle hook into ProgrammeManager

`agents/programme_manager/manager.py` line 337 + line 346 call
`record_event()` on every lifecycle transition:

- **`started` event** — emitted when a programme transitions from
  `PENDING` → `ACTIVE` (line 346).
- **`ended_<reason>` event** — emitted when a programme transitions
  out of `ACTIVE`, with the reason tag matching `EndReason` from
  `shared.programme_observability` (line 337).

The hook is in the production tick path, not behind a feature flag.

### 2.3 Reference docs

- Plan: `docs/superpowers/plans/2026-04-20-programme-layer-plan.md` §Phase 9
- Audit: `docs/superpowers/audits/2026-04-20-3h-work-audit-remediation.md` (B3 / Critical #5)
- Sibling writer: `shared/attribution.AttributionFileWriter`

The "no JSONL surface" framing from
`agents/live_cuepoints/consumer.py` lines 14-17 + 252-258 is
**superseded** by the above. Both docstrings have been updated in
this PR to reflect the current state and reference this status doc.

---

## 3. What's still deferred (Consumer side — cc-task acceptance #2 + #3)

### 3.1 Why the consumer side is non-trivial

The current `live_cuepoints/consumer.py` tailer:

- Reads from a **single fixed file** (`HAPAX_LIVE_CUEPOINT_EVENT_PATH`,
  default `/dev/shm/hapax-broadcast/events.jsonl`).
- Maintains **one byte cursor** in `~/.cache/hapax/live-cuepoints-cursor.txt`.
- Filters event types via `_is_chapter_worthy()` — currently only
  `broadcast_rotated` qualifies.

The programme outcome log lives under a **tree** of files
(`<show>/<programme>.jsonl`), not a single fixed path. To consume
from it, the consumer needs:

1. **Multi-file walker** — periodic glob over
   `~/hapax-state/programmes/*/*.jsonl` (and rotated variants).
2. **Per-file cursor** — one byte cursor per programme JSONL file
   (programmes are mostly write-once / append-only / completed,
   so cursors can be pinned to file-end once the closure event has
   been seen).
3. **Start/end-event dedup** — a single programme emits at most
   one `started` and one `ended_<reason>` event over its lifetime;
   the cuepoint emitter must not double-fire if the consumer
   restarts mid-programme. Two strategies:
   - **Per-programme idempotency ledger** keyed on `programme_id`
     × `event` (mirrors the mastodon idempotency pattern from PR
     #1942 / mastodon_post.py).
   - **File-level closure detection** — once an `ended_*` event has
     been observed for a programme JSONL, mark the cursor at file-end
     and skip the file on subsequent walks unless rotation produces
     a new generation.
4. **Cuepoint timing semantics** — the cc-task acceptance is "boundary
   transitions" → cuepoints. Two events per programme means two
   chapter cuepoints (one at start, one at end) OR one cuepoint per
   transition (the "ended_X → started_Y" boundary maps to a single
   chapter break). The follow-up impl needs an explicit choice;
   recommend **one cuepoint per `started` event** (chapter starts at
   programme start, ends implicitly at the next chapter — matches
   YouTube's chapter model) plus the `ended_*` events kept for
   metric/audit visibility.

### 3.2 The follow-up cc-task

The remaining work is a single cohesive task. Filing it as
`ytb-004-programme-boundary-cuepoints-consumer` with these acceptance
criteria:

- [ ] `live_cuepoints/consumer.py` walks
  `~/hapax-state/programmes/*/*.jsonl` on each tick alongside the
  existing single-file tail.
- [ ] Per-programme byte cursor at
  `~/.cache/hapax/live-cuepoints-programme-cursor/<programme_id>.txt`
  (atomic tmp+rename, mirrors the mastodon adapter pattern).
- [ ] Start/end-event idempotency via a single ledger at
  `~/.cache/hapax/live-cuepoints-programme-event-ids.json`.
- [ ] `_is_chapter_worthy()` returns `True` for canonical
  `programme.boundary` events (one cuepoint per `started`; `ended_*`
  observed for audit only).
- [ ] Tests: programme-boundary cuepoint creation; duplicate
  suppression (same `programme_id` + `event` doesn't re-fire);
  cursor restart correctness; multi-programme concurrent walking.
- [ ] No new dependencies; schema change limited to `_is_chapter_worthy`
  + the new walker private helpers.

**WSJF estimate:** 5.5 (medium — pure consumer-side wiring with a
clear acceptance gate; no production data dependency).

---

## 4. Cross-task observation: the canonical `programme.boundary` event type

`shared/research_vehicle_public_event.py::EventType` already lists
`programme.boundary` as a first-class canonical event type. Today
that event type has **no producer** on the canonical
`/dev/shm/hapax-public-events/events.jsonl` bus — the
`programme_outcome_log` writes to a different (per-programme) tree.

A separate Phase-2 follow-up could materialize `programme.boundary`
events on the canonical bus by reading the per-programme JSONL tree
(or by adding a parallel emit path inside `programme_manager`'s
lifecycle hook). That work is **out of scope** for both
`ytb-004-programme-boundary-cuepoints` and the proposed
`-consumer` follow-up; it would belong under the
`youtube-research-translation-ledger` parent task that owns the
broader canonical-event surface for YouTube.

---

## 5. What stays unchanged

- `shared/programme_outcome_log.py` — the producer is correct as-is.
- `agents/programme_manager/manager.py` lifecycle hooks — the
  `record_event()` call sites remain in the production tick path.
- The canonical `ResearchVehiclePublicEvent` contract — no new
  Surface or EventType additions are needed; `programme.boundary`
  already exists.
- The current single-file `live_cuepoints/consumer.py` tail of
  `broadcast_rotated` events — that path stays live and unchanged
  through the consumer-side follow-up.

---

## 6. Closure criteria for THIS task

- [x] Acceptance criterion (1) "emit programme-manager JSONL events for
  boundary transitions" — confirmed shipped (§2).
- [x] Acceptance criterion (4) "update YTB-004 notes with the split
  completion or explicit deferral" — this status doc is the split
  record. The two stale docstrings in
  `agents/live_cuepoints/consumer.py` have been updated in this PR.
- [-] Acceptance criteria (2) "consume those events in the live
  cuepoint path" + (3) "add tests for programme boundary creation
  and duplicate suppression" — explicitly deferred to the
  `ytb-004-programme-boundary-cuepoints-consumer` follow-up cc-task
  (§3.2).

The split makes both halves shippable on their own evidence: the
producer half stands on the existing tests in
`tests/shared/test_programme_outcome_log.py` + the
`tests/programme_manager/` suite; the consumer half ships when the
follow-up cc-task lands.
