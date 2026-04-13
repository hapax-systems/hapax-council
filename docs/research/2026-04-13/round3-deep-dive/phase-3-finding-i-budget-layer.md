# Phase 3 — FINDING-I: BudgetTracker retirement scoping

**Queue item:** 024
**Phase:** 3 of 6
**Depends on:** PR #756 FINDING-I, PR #754, PR #755
**Date:** 2026-04-13 CDT
**Register:** scientific, neutral (per `feedback_scientific_register.md`)

## Headline

The Phase 7 `BudgetTracker` layer (budget.py + budget_signal.py +
test_budget.py + test_budget_signal.py + the `budget_tracker=` kwarg
on `CairoSourceRunner`) is **wired-but-never-called** in production.
PR #756 Phase 3 and this phase both confirm via grep: **zero
production callers** of `BudgetTracker(`, `publish_costs(`, and
`publish_degraded_signal(`. Alpha's subsequent PRs #754 (budget
freshness gauge wrapper) and #755 (freshness gauge registry wire)
added visibility of the dead state — the gauges will show
`age_seconds=+Inf` forever — but did not wire the underlying layer.

Plus, per Phase 2 of this research, the compositor's `:9482`
exporter is not scraped by Prometheus at all. **So PR #755's
freshness-gauge-visibility value is currently zero** — the gauges
are registered on a registry that Prometheus does not read. Any
retirement or resurrection decision happens inside an observability
blackhole that will be closed by the Phase 2 fixes.

**Recommendation: Option B (retire).** Delete 1422 lines of dead
code and one yet-to-ship VLA subscriber obligation. Rebase PR #754
and PR #755 to drop the `_PUBLISH_*_FRESHNESS` wrappers before
merging the retirement PR.

## Live caller inventory

```text
# Production grep across agents/ shared/ logos/
$ grep -rn "BudgetTracker(" --include='*.py' agents/ shared/ logos/ | grep -v test
(empty)

$ grep -rn "budget_tracker=" --include='*.py' agents/ | grep -v test
(empty)

$ grep -rn "publish_costs(\|publish_degraded_signal(" --include='*.py' agents/ shared/ logos/ | grep -v test
agents/studio_compositor/budget.py:350:def publish_costs(tracker: BudgetTracker, path: Path) -> None:
agents/studio_compositor/budget_signal.py:145:def publish_degraded_signal(
# Both are *definitions*, not calls.
```

Three public symbols. Zero call sites outside the modules that
define them. Zero call sites outside tests.

## Design spec review

`docs/superpowers/specs/2026-04-12-phase-7-budget-enforcement-design.md`
defines the API, the data model, and sample usage snippets, but
**does not specify the call site** for `BudgetTracker`
instantiation. The spec's usage example is a standalone snippet:

```python
tracker = BudgetTracker(window_size=120)  # ~4s at 30fps
tracker.record("sierpinski-lines", elapsed_ms=12.5)
tracker.last_frame_ms("sierpinski-lines")  # 12.5
if tracker.over_budget("sierpinski-lines", budget_ms=5.0):
    ...
publish_costs(tracker, Path("/dev/shm/hapax-compositor/source-costs.json"))
```

The File structure table lists `budget.py` + `cairo_source.py`
changes + `test_budget.py` but **not `compositor.py`** or any
caller location. The Phase 7 PR (#665) correspondingly shipped the
tracker + the cairo_source.py plumbing but did **not** add any call
site for tracker instantiation. This was the specification gap that
produced the dead layer.

The F2 followup (#671 — per-frame layout budgets) and F3 followup
(#672 — degraded-signal publisher) extended the API surface but
neither added a call site either. The unification-epic audit
(`docs/superpowers/audits/2026-04-12-compositor-unification-audit.md`
§ followups) explicitly noted:

> `budget_signal.py::publish_degraded_signal` — no VLA subscriber

…but did not notice that there was also no producer-side caller.
The audit assumed the producer existed and only the consumer was
missing. Neither was true.

## Git archaeology

```text
$ git log --oneline --all -- agents/studio_compositor/budget.py agents/studio_compositor/budget_signal.py
4af213651 fix(compositor): wire FreshnessGauge series through the custom metrics REGISTRY (#755)
d93bfa120 fix(compositor): wire FreshnessGauge series through the custom metrics REGISTRY
2e948a8e0 chore(compositor): budget freshness gauges + token_pole golden-image pin (#754)
a625499db chore(compositor): budget freshness gauges + token_pole golden-image pin
45ce584d3 feat: audit polish round (observability, validation, cleanup) (#676)
c2b0f9696 feat(f3): compositor degraded-signal publisher (#672)
16ae06c00 feat(f2): per-frame layout budgets in BudgetTracker (#671)
739771125 feat(phase-7): budget enforcement — tracker + skip-if-over-budget (#665)
```

Timeline:

- **#665 (2026-04-12)** — Phase 7 ships. BudgetTracker + CairoSourceRunner
  plumbing. No caller wiring. Explicit "opt-in" default.
- **#671 (2026-04-12)** — F2 followup. Per-frame layout budget
  queries added. Still no caller wiring.
- **#672 (2026-04-12)** — F3 followup. `publish_degraded_signal`
  added. Commit message explicitly scopes out the VLA subscriber.
  Still no caller wiring on the producer side either.
- **#676 (2026-04-12)** — Audit polish round. `atomic_write_json`
  extracted. Still no caller wiring.
- **#754 (2026-04-13)** — Freshness gauge wrappers. Still no caller
  wiring. PR description explicitly acknowledges dormant state.
- **#755 (2026-04-13)** — Freshness gauge registry wire. Still no
  caller wiring.

**Seven commits over two days, zero production callers added.** The
caller wiring was deferred at #665 ship time and never revisited.
Every subsequent PR layered observability on top of a dead layer.

## Option A — Resurrect

Minimum caller wiring to make the layer functional:

1. **`agents/studio_compositor/compositor.py`** — add
   `self._budget_tracker = BudgetTracker(window_size=120)` at the
   top of `StudioCompositor.__init__`. Attach it to the compositor
   as an instance attribute so all runners can reference it.
2. **`agents/studio_compositor/source_registry.py:103`** — pass
   `budget_tracker=compositor._budget_tracker` and
   `budget_ms=source.params.get("budget_ms")` to the
   `CairoSourceRunner` constructor.
3. **`agents/studio_compositor/overlay_zones.py:373`** — same.
4. **`agents/studio_compositor/sierpinski_renderer.py:349`** — same.
5. **`agents/studio_compositor/compositor.py`** — add a GLib
   timeout callback ticking at 1 Hz that calls
   `publish_costs(self._budget_tracker, Path("/dev/shm/hapax-compositor/source-costs.json"))`
   and
   `publish_degraded_signal(self._budget_tracker, DEFAULT_SIGNAL_PATH)`.
   Wire the cleanup in `stop_compositor`.
6. **`agents/visual_layer_aggregator/backends/compositor_degraded.py`**
   (new) — VLA backend that polls
   `/dev/shm/hapax-compositor/degraded.json` with staleness cutoff
   5 s, maps `degraded_source_count` to a 0–1 dimension, publishes
   to the stimmung dimension pipeline.
7. **`agents/visual_layer_aggregator/registry.py`** — register the
   new backend.
8. **`shared/dimensions.py`** — declare the `compositor_degraded`
   dimension if not already present.
9. **`config/compositor-layouts/default.json`** — add
   `budget_ms` fields to each source spec so the tracker actually
   enforces budgets. (Without this, the machinery runs but never
   triggers the skip path.)

**Line count estimate**: ~80 lines in compositor.py, ~9 lines in
source_registry.py, ~9 lines each in overlay_zones.py and
sierpinski_renderer.py, ~100 lines for the new VLA backend, ~20
lines for registration + dimension declaration, ~30 lines of config.
Total: **~260 lines of new code** across 8 files, plus tests for
the VLA backend (~100 lines). Estimated effort: 3–4 hours.

Obligations Option A incurs:

- Keeping 1422 lines of tested dead-code-path alive as load-bearing
  observability
- VLA backend review + stimmung mapping review
- Grafana panel for the degraded-count signal
- A Prometheus alert rule for `degraded_source_count > 0` sustained
- Cross-training future sessions on how the degraded path interacts
  with FINDING-H's observability-gap closure

Value Option A delivers:

- Stimmung-gated "compositor under load" signal (stage gate for
  SEEKING, shedding, degraded banner)
- Per-source rolling cost stats for Grafana panels
- `budget_ms`-driven skip-with-fallback for expensive sources

The operator has not asked for any of these in the 30+ days since
the Phase 7 layer landed. They are nice-to-have observability; they
are not operator-requested features.

## Option B — Retire

Deletion scope:

| file | lines | role |
|---|---|---|
| `agents/studio_compositor/budget.py` | 425 | `BudgetTracker`, `SourceCost`, `publish_costs`, `atomic_write_json`, `_percentile` |
| `agents/studio_compositor/budget_signal.py` | 174 | `build_degraded_signal`, `publish_degraded_signal`, `DEFAULT_SIGNAL_PATH` |
| `tests/test_budget.py` | 587 | 40+ unit tests covering tracker, publish, percentile |
| `tests/test_budget_signal.py` | 236 | 15+ tests covering build + publish + freshness gauge |
| **total deleted** | **1422** | |

Plus in-place edits:

- **`agents/studio_compositor/cairo_source.py`** — remove lines
  27 (`TYPE_CHECKING import`), 94–95 (`budget_tracker: BudgetTracker
  | None = None, budget_ms: float | None = None`), 101–102
  (validation), 127–131 (state init), 368–380 (over-budget skip
  branch), 425–428 (tracker record). Remove `_consecutive_skips`
  accessor (lines 199–209). Net: ~45 lines deleted.
- **`agents/studio_compositor/cairo_source.py`** — keep the
  `_atomic_write_json` helper if it was extracted from budget.py's
  `atomic_write_json`. If not, move the helper from budget.py into
  a new tiny module `agents/studio_compositor/_atomic_io.py` since
  it's a legitimately reusable primitive (token_ledger, publish_health,
  and publish_visual_layer_state all rely on the same pattern — see
  Phase 5 silent-failure sweep).

Additionally, rebase **PR #754** (open) to drop the
`_PUBLISH_COSTS_FRESHNESS` and `_PUBLISH_DEGRADED_FRESHNESS` gauge
wrappers and keep only the token_pole golden-image change. And
**PR #755** already merged — its budget-related gauge wires should
be reverted in the retirement PR (the hooks that register
`compositor_publish_costs_*` and `compositor_publish_degraded_*`
go away with the publishers). Per-source `compositor_source_frame_*`
gauges from PR #755 **should stay** — they are not part of the
BudgetTracker layer and are the one piece of PR #755 that is not
tombstone observability.

**Total net line change**: −1467 lines (1422 deleted + ~45 lines
of cairo_source.py cleanup), plus ~20 lines of PR #754/#755
rollback. No new files.

**Effort**: 1 hour for the deletion + 30 minutes for the PR #754
rebase + 30 minutes for the PR #755 partial revert + 30 minutes
of test runs. Risk: low — no production code references exist.

**What is lost**: the *possibility* of a stimmung-gated "compositor
under load" signal. If the operator later asks for it, git history
preserves the design spec, the test plan, the publisher, and the
four PRs listed above. Resurrection from git is one `git log -p`
session + 30 minutes of reading + the ~260-line Option A wiring pass.

## Recommendation

**Ship Option B.** Rationale:

1. **30+ days have elapsed** since the Phase 7 layer landed
   without any operator-felt gap from its absence.
2. **Per-source frame-age observability is already covered by
   Phase 8's FreshnessGauge path** (`cairo_source.py:145–161`,
   shipping `compositor_source_frame_<id>_age_seconds`). The
   BudgetTracker's `last_frame_ms` function is redundant.
3. **Layout-level budget decisions** that the spec anticipated
   (`over_layout_budget`, `headroom_ms` for a frame planner) have
   not materialized. There is no frame planner to call them.
4. **The FINDING-H fix (Phase 2 of this research) closes the
   observability blackhole** that would have justified PR #754/#755's
   freshness gauge wrappers. Once the compositor is actually
   scraped, the wrappers would show `+Inf` forever — operator
   signal value zero, maintenance cost nonzero.
5. **PR #754 and PR #755 together account for ~400 lines of code
   whose entire operator-visible impact is "surfaces the dead
   state of a layer that has no callers"**. Deleting the layer is
   strictly simpler than maintaining the dead-state surface.
6. **The wider observability gap list** from Phase 6 of PR #756
   identifies real missing metrics (daimonion, VLA, imagination,
   tabbyAPI) that would produce actual operator value. Budget
   spending observability effort on those instead of the Phase 7
   layer retirement is higher ROI.

Option A is not wrong. It is architecturally clean and the code is
ready to wire. It is simply the lower-value choice given the
elapsed-time signal that the operator does not need this layer.

## Proposed retirement PR structure

Single PR, single commit, title
`chore(compositor): retire Phase 7 budget layer (dead-but-wired)`:

1. Delete `agents/studio_compositor/budget.py`
2. Delete `agents/studio_compositor/budget_signal.py`
3. Delete `tests/test_budget.py`
4. Delete `tests/test_budget_signal.py`
5. Update `agents/studio_compositor/cairo_source.py` — remove
   `budget_tracker`, `budget_ms`, `_consecutive_skips`, and the
   over-budget skip branch.
6. Create `agents/studio_compositor/_atomic_io.py` with
   `atomic_write_json(payload, path)`. Update every caller of the
   old `budget.atomic_write_json` to import from the new module.
   (Grep hint: at least `publish_health.py`, `token_ledger.py`,
   `publish_visual_layer_state.py` if they use it.)
7. Remove `compositor_publish_costs_*` and
   `compositor_publish_degraded_*` freshness gauge wrappers from
   PR #754/#755's wiring.
8. Update `CLAUDE.md § Studio Compositor` to remove the line
   "`budget_signal.py` publishes degraded signal for VLA".
9. Update `docs/superpowers/specs/2026-04-12-phase-7-budget-enforcement-design.md`
   with a superseded banner + pointer to this phase's doc.

## Coordination with PR #754 and PR #755 (both alpha's, already merged)

Checked: PR #754 merged (see `2e948a8e0` in git log). PR #755
merged (`4af213651`). So the retirement PR works against already-
landed code, not open PRs. **No PR rebase coordination needed;**
the retirement PR simply revs the relevant wrappers as part of
the broader deletion.

This is a change from PR #756 Phase 3's coordination recommendation,
which assumed PR #754 was still open. PR #754 merged at some point
after PR #756 landed.

## Backlog additions (for retirement handoff)

55. **`chore(compositor): retire Phase 7 budget layer (Option B)`**
    [Phase 3 recommendation] — 1467-line net deletion + atomic
    write helper relocation. Single PR. HIGH clarity value, LOW
    operator-user-visible impact. Ship after FINDING-H fix lands
    (Phase 2) so there's no argument that "retire would kill a
    signal that would have been visible after the scrape gap
    closed" — Phase 2 makes the gap closure explicit.
56. **`docs(compositor): supersede phase-7-budget-enforcement-design.md`**
    [Phase 3] — add a `**SUPERSEDED**` banner at the top of the
    spec pointing at the retirement PR and this research doc.
    Keep the spec for git-archaeology-rebuild purposes.
57. **`docs(handoff): correction to PR #756 Phase 3 recommendation`**
    [Phase 3] — PR #756 Phase 3 said "rebase PR #754 to drop the
    wrapper before merge." By the time this research ran, PR #754
    had merged. The retirement PR is the correct surface now.
58. **`feat(compositor): extract atomic_write_json helper into
    _atomic_io.py`** [Phase 3 step 6] — this is a legitimate
    reusable primitive that was only inside budget.py because of
    historical shipping order. The retirement PR can either
    include this extraction or file it as a separate small PR.
