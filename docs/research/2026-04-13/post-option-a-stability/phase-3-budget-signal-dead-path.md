# Phase 3 — `budget_signal.publish_degraded_signal` dead-path trace + wiring proposal

**Queue item:** 023
**Phase:** 3 of 6
**Depends on:** Queue 022 BETA-FINDING-2026-04-13-F (the initial sighting)
**Date:** 2026-04-13 CDT
**Register:** scientific, neutral (per `feedback_scientific_register.md`)

## Headline

The dead path is wider than queue 022 reported. PR #752 Phase 4 found
that `publish_degraded_signal` has no production caller. A line-level
trace through the upstream tracker and the cairo-source runner proves
a larger fact:

**`BudgetTracker` itself has zero production instantiations.** Every
production site that constructs a `CairoSourceRunner`
(`source_registry.py:103`, `overlay_zones.py:373`,
`sierpinski_renderer.py:349`) omits the `budget_tracker=` keyword
argument, falling back to the default `None`. Because the tracker is
never wired into a runner, `tracker.record()` is never called anywhere
outside tests, `tracker.snapshot()` would return an empty dict, and
both `publish_costs` and `publish_degraded_signal` — the two publishers
the Phase 7 budget-enforcement epic shipped — are wired-but-never-called
from production. The half-merged observability failure pattern repeats
at one level up from queue 022's finding.

A new post-queue-022 observation: alpha's PR #754 (OPEN,
`chore/compositor-small-fixes`) adds `FreshnessGauge` wrappers around
both publishers. The wrapper reports
`compositor_publish_degraded_{published_total, failed_total, age_seconds}`
from the compositor exporter. This makes the dead-path state directly
**observable** (age stays at `+inf` forever) without making it
**operational**. The PR description acknowledges this explicitly:

> Both publishers are currently dormant in production (beta's PR #752
> Phase 4 flagged publish_degraded_signal as a dead end-to-end path).
> Constructing the gauges at import means the dead-path status is
> directly observable — age stays at +inf and the silent mask becomes
> a loud signal on :9482.

PR #754 is the right short-term move — it converts an invisible failure
into a visible one. It is not a long-term fix. The wiring proposal
below is the long-term decision: resurrect the publisher with a VLA
subscriber, or formally delete the whole dormant feature.

## Live reproduction

### `/dev/shm/hapax-compositor/` directory at T+17 min post-restart

```text
$ ls -la /dev/shm/hapax-compositor/ 2>&1 | head -40
drwxr-xr-x  2 hapax hapax     720 Apr 13 16:55 .
drwxrwxrwt 27 root  root      600 Apr 13 16:55 ..
-rw-r--r--  1 hapax hapax  274862 Apr 13 16:55 album-cover.png
-rw-r--r--  1 hapax hapax     223 Apr 13 16:55 album-state.json
-rwxr-xr-x  1 hapax hapax   51698 Apr 13 16:55 brio-operator.jpg
…
[30+ files total, none named degraded.json]
```

Neither `degraded.json` nor the `publish_costs` output file
(`source-costs.json` per the Phase 7 spec) exists on disk. The shared-
memory directory is otherwise fully populated — the compositor writes
30+ other status/snapshot files — so it is not a directory-missing
issue. The file is not being written.

### Grep survey

```text
$ grep -rn 'publish_degraded_signal\|publish_costs\|build_degraded_signal' \
     agents/ shared/ logos/ --include='*.py'
```

| Symbol | Production callers | Test callers | Doc references |
|---|---|---|---|
| `build_degraded_signal` | 0 | 8 (`tests/test_budget_signal.py`) | `budget_signal.py` docstring |
| `publish_degraded_signal` | 0 | 6 (`tests/test_budget_signal.py`) | `CLAUDE.md § Studio Compositor` |
| `publish_costs` | 0 | 3 (`tests/test_budget.py`) | `docs/superpowers/specs/2026-04-12-phase-7-budget-enforcement-design.md` + related handoffs |
| `BudgetTracker(…)` (instantiation) | 0 | 50 across `tests/test_budget.py` and `tests/test_budget_signal.py` | specs + CLAUDE.md |

Zero production callers for any of the four public symbols.

### Who *would* construct a tracker, if anyone?

`CairoSourceRunner.__init__` (line 94) accepts `budget_tracker: BudgetTracker | None = None`.
Every production call site passes only positional + natural-size kwargs:

```text
$ grep -n "CairoSourceRunner\|budget_tracker=" agents/studio_compositor/*.py
agents/studio_compositor/budget.py:11:local ``CairoSourceRunner._last_render_ms`` field stays as instant
agents/studio_compositor/source_registry.py:103: return CairoSourceRunner(
agents/studio_compositor/overlay_zones.py:373:  self._runner = CairoSourceRunner(
agents/studio_compositor/sierpinski_renderer.py:349: self._runner = CairoSourceRunner(
```

None of the three production call sites pass `budget_tracker=`. No
call site passes `budget_ms=` either. The tracker-and-budget code in
`CairoSourceRunner._run_tick_once` (the `_consecutive_skips`
accumulator, the `self._budget_tracker.record(source_id, elapsed_ms)`
call, the over-budget skip branch) is correctly written but runs against
a `None` tracker — so `record()` is never called, `skip_count` stays at
zero, and the snapshot would be empty if anyone were to request it.

### FreshnessGauge supersedes per-source frame age

In Phase 8 of the completion epic (`a625499db` precursor commits),
`CairoSourceRunner.__init__` was taught to instantiate a
`FreshnessGauge` unconditionally at construction (lines 145–161). That
gauge exposes `compositor_source_frame_<source_id>_age_seconds` on the
compositor's `:9482` exporter for every cairo source. This means the
per-source frame-age observability function that `BudgetTracker`
originally served is already covered by the FreshnessGauge path, and
has been since the completion epic shipped.

This matters for the wiring decision below: the only *unique*
responsibilities of the BudgetTracker that the FreshnessGauge path
does not cover are:

1. **Per-source skip counts** (skip-due-to-over-budget telemetry).
2. **Rolling-window aggregate statistics** (avg_ms, p95_ms across the
   window).
3. **Layout-level budget decisions** (`over_layout_budget`,
   `headroom_ms` — used by a frame planner that drops
   lowest-priority sources when total budget is exceeded).
4. **The aggregate "degraded source count" signal** that
   `publish_degraded_signal` was designed to emit to the stimmung
   dimension pipeline.

Responsibilities 1–3 have no current consumer — no frame planner, no
dashboard, no alert queries the data. Responsibility 4 is the original
F3 design intent and is what the wiring proposal must either satisfy
or retire.

## Git archaeology

```text
$ git log --oneline --all -- agents/studio_compositor/budget_signal.py
a625499db chore(compositor): budget freshness gauges + token_pole golden-image pin
45ce584d3 feat: audit polish round (observability, validation, cleanup) (#676)
c2b0f9696 feat(f3): compositor degraded-signal publisher (#672)
```

Three commits, two merged and one in-flight:

- `c2b0f9696 feat(f3): compositor degraded-signal publisher (#672)` —
  the original ship. Adds `build_degraded_signal` + `publish_degraded_signal`
  + 8 unit tests. Does **not** add a call site and does **not** ship
  a consumer.
- `45ce584d3 feat: audit polish round (#676)` — cosmetic polish,
  extracts `atomic_write_json` to `budget.py` for reuse by both
  publishers, adds `wall_clock` to the payload. Does not add a call
  site.
- `a625499db chore(compositor): budget freshness gauges + token_pole golden`
  — alpha's in-flight PR #754. Wraps both publishers in a
  `FreshnessGauge`. Does not add a call site. Explicitly notes: "Both
  publishers are currently dormant in production."

The design intent was captured in
`docs/superpowers/specs/2026-04-12-phase-7-budget-enforcement-design.md`
(Phase 7 of the compositor unification epic) and extended in the
followups document for F3. The VLA-side subscriber was scoped out in
F3 with an explicit "iterate later" note that never iterated:

> This module ships the **publisher** (mirrors publish_costs from
> Phase 7). The VLA-side subscriber that maps the signal into a
> stimmung dimension is a separate piece of work and is intentionally
> out of scope here — landing the signal first means the operator can
> introspect the data immediately and the VLA wiring can iterate
> without blocking the data plane.
> — `budget_signal.py:13–19`

The comment is reasonable in context but load-bearing: "iterate later"
became "never iterate," and because no one wired the publisher either,
the F3 deliverable is functionally a file sitting in the repo.

## Proposed wiring — two options, operator picks

### Option A — Resurrect (full F3 landing)

Do what F3 promised to do but did not. Three sub-changes:

1. **Producer side — wire `BudgetTracker` into the cairo runner fleet.**
   Instantiate a singleton `BudgetTracker` at compositor startup
   (alongside `start_metrics_server`) and pass it to every
   `CairoSourceRunner` constructor in `source_registry.py`,
   `overlay_zones.py`, and `sierpinski_renderer.py`. Also pass a
   `budget_ms` per source from existing layout config.

2. **Producer side — call `publish_degraded_signal` at a reasonable
   cadence.** The natural call site is a GLib timeout callback in
   `compositor.py` ticking at 0.5–1 Hz. Publishes are cheap (one
   `os.replace` of a small JSON file). PR #754's FreshnessGauge wrapper
   is already in place, so the publish path is instrumented on arrival.

3. **Consumer side — ship a stimmung reader.** VLA already polls
   `/dev/shm/hapax-compositor/` for several JSON signal files
   (`visual-layer-state.json`, `activity-correction.json`,
   `watershed-events.json` via `shared/notify.py`); add a poll entry
   for `degraded.json`. Map `degraded_source_count` to a 0–1 dimension
   that feeds a new stimmung backend (`compositor_degraded`). The
   cross-modal recruitment threshold already consults stimmung
   dimensions to gate SEEKING and similar states, so the new
   dimension plugs in directly.

   Effort: roughly 50 lines in a new `agents/hapax_daimonion/backends/compositor_degraded.py`
   (following the ir_presence.py / contact_mic_ir.py backend pattern)
   + registration in the VLA backend list + a dimension entry.

**JSON schema** (already defined in `build_degraded_signal`, verified
against the existing unit tests):

```json
{
  "timestamp_ms": 12345.6789,
  "wall_clock": 1712345678.123,
  "total_skip_count": 17,
  "degraded_source_count": 2,
  "total_active_sources": 6,
  "worst_source": {
    "source_id": "sierpinski-lines",
    "skip_count": 9,
    "last_ms": 12.3,
    "avg_ms": 7.4
  },
  "per_source": {
    "sierpinski-lines": {"skip_count": 9, "last_ms": 12.3, "avg_ms": 7.4},
    "album-overlay":    {"skip_count": 8, "last_ms": 6.1,  "avg_ms": 5.0}
  }
}
```

**Atomicity guarantee** — already enforced via
`budget.atomic_write_json` (`budget.py:291–308`): mkdir → write tmp →
`os.replace` onto the final path. External readers either see the
previous snapshot or the new one, never a partial write. Matches the
existing `publish_health`, `publish_visual_layer_state`, and
`token_ledger.py` patterns.

**Staleness policy** — the `wall_clock` field is in the payload. VLA
should treat any file older than 5 × expected_cadence as stale and
gate on `degraded_source_count=0` rather than the last-read value.
Matches the staleness pattern in `env_context.py` for other signal
files.

**Where to ship it.** A dedicated PR touching the three files above
and adding the VLA backend. Estimate 200–300 lines of production code
plus tests. Do not bundle into the `cameras_healthy` fix (Phase 2) —
the VLA backend review is scope-bearing and deserves its own diff.

### Option B — Retire (formal deletion)

Acknowledge that the stimmung-gated "compositor degraded under load"
signal has not been a real operator need in the 30+ days since F3
shipped, and that the FreshnessGauge path covers the per-source
frame-age observability function that the BudgetTracker was originally
designed for. Formally delete the whole dormant layer:

1. Delete `agents/studio_compositor/budget_signal.py`.
2. Delete `agents/studio_compositor/budget.py` except for the
   `atomic_write_json` helper, which has become the canonical atomic
   write primitive. Migrate the helper into
   `agents/studio_compositor/_atomic_io.py` (new module, single
   function) and update the two callers.
3. Delete `tests/test_budget.py` and `tests/test_budget_signal.py`.
4. Remove the `budget_tracker` and `budget_ms` kwargs from
   `CairoSourceRunner.__init__`, along with the `_consecutive_skips`
   accumulator and the over-budget skip branch in `_run_tick_once`.
5. Remove the budget references from `docs/superpowers/specs/`
   (Phase 7 design doc marked superseded) and `CLAUDE.md`
   (§ Studio Compositor — one line).
6. Rebase PR #754 to drop the FreshnessGauge wrapper for the
   publishers, keeping only the token_pole golden-image change.

Net diff: around −600 lines of production code + tests + docs. Roughly
twice the size of Option A but leaves a cleaner compositor surface
and unblocks the PR #754 scope from being about a dead path.

### Recommendation

**Option B.** The rationale:

- 30+ days have elapsed since F3 shipped. The operator has not asked
  for a "compositor degraded under load" stimmung dimension and has
  not found the absence of one to be a gap.
- Per-source frame-age observability is already covered by the
  Phase 8 `FreshnessGauge` path. The BudgetTracker's frame-age
  function is redundant; its skip-count and p95 functions have no
  live consumer.
- The layout-level budget decisions the spec anticipated
  (`over_layout_budget`, `headroom_ms` for a frame planner) have not
  materialized either. There is no frame planner that would call
  them.
- Keeping the feature around as "published but unused observability"
  ties alpha's in-flight PR #754 to a load-bearing-dead-code shape
  that propagates forward. Rebasing PR #754 to drop the wrapper once
  the publishers are gone is cleaner than keeping the wrapper as a
  tombstone.
- If a future need materializes for the stimmung-gated degraded
  signal, the git history preserves the Phase 7 design and the F3
  publisher. Resurrection from git is one `git show c2b0f9696 --
  agents/studio_compositor/budget_signal.py` and 30 minutes of
  reading.

Option A is not wrong — it is simply more expensive and the demand
signal is not strong enough to justify the scope. Operator may
disagree: the "scope" call depends on whether the stimmung layer is
seen as "needs every signal it can get" vs "needs only the signals
that currently move behavior." Queue 022's finding assumed the former;
this phase's deeper trace reveals no downstream consumer that would
actually act on the signal if it were live, weakening the case.

## PR recommendation + coordination with alpha's in-flight work

- **PR #754 (`chore/compositor-small-fixes`, alpha)** is currently in
  CI. It wraps both publishers in `FreshnessGauge`. If Option B is
  chosen, PR #754 should either:
  - (a) merge as-is (the gauges harmlessly show +inf forever while
    the deletion PR is drafted), then get partially reverted in the
    deletion PR — suboptimal.
  - (b) be rebased before merge to drop the budget freshness gauge
    wrappers, keeping only the token_pole golden-image change —
    cleaner and smaller scope.
- If Option A is chosen, PR #754 is a clean complement to the
  wiring PR — the FreshnessGauge surfaces the dead-path state
  during the window before the producer + consumer land, and
  automatically flips to "fresh" the moment the producer wires up.
- **No Phase 3 fix should ship as part of this research pass.** Phase
  3's deliverable is the decision brief plus the wiring proposal,
  not a PR. The next compositor-touching session picks up the chosen
  option and ships it.

## Backlog additions (for retirement handoff)

1. **Phase 3 decision**: resurrect-or-retire the entire Phase 7
   BudgetTracker + budget_signal layer. **Recommendation: retire
   (Option B).** Write the decision up in a short ADR before taking
   either path.
2. **If Option B is chosen**: rebase PR #754 to drop the
   `_PUBLISH_DEGRADED_FRESHNESS` and `_PUBLISH_COSTS_FRESHNESS`
   gauge wrappers before merge. Coordinate with alpha.
3. **If Option A is chosen**: three sub-tickets, each a separate PR:
   - `fix(compositor): instantiate a module-level BudgetTracker and
     pass it through CairoSourceRunner construction sites`
   - `feat(compositor): publish_degraded_signal call site on a 1 Hz
     GLib timeout`
   - `feat(vla): compositor_degraded stimmung backend reading
     /dev/shm/hapax-compositor/degraded.json`
4. **Independent of option**: update `CLAUDE.md § Studio Compositor`
   to reflect the final shape (either "budget_signal publishes a
   degraded dimension" or "budget subsystem retired, use
   FreshnessGauge for frame-age"). Do not leave the description
   pointing at a dead or inconsistent surface.
5. **Correction for queue 022 handoff BETA-FINDING-F**: the finding
   originally framed `publish_degraded_signal` as a "publisher shipped,
   consumer never shipped" half-merge. The deeper trace in this phase
   reveals the state is worse: the entire `BudgetTracker` upstream is
   also dormant. Update the PR #752 retirement handoff's description
   of finding F to reflect this.
