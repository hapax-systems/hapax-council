# Zeta Session Handoff — 2026-05-07T04:35Z

## Session shape

RTE-dispatched then `/loop dynamic 270s wakes` self-pacing. Throughput across the loop while the upstream queue was drainable. Triggered after 50+h idle; closed out at the operator's "self-claim or end-of-shift handoff" RTE message when no offered cc-task fit zeta lane.

## Shipped this session

| PR | Theme | Status | Note |
|----|-------|--------|------|
| #2798 | `test(audio-modulation)`: tighten `KNOWN_BANNED_VIOLATIONS` cap from `<= 20` to `== 0` | merged 04:15Z (admin) | Closes the followup tail of gap #4/31; cap now reflects the post-2026-05-07 zero-grandfather state. |
| #2799 | `feat(garage-door)`: mount `ChronicleTickerCairoSource` in right column at (1380, 560, 420×140) | merged 04:20Z (admin) | Pure additive layout slot. Feature-flagged off (`HAPAX_LORE_CHRONICLE_TICKER_ENABLED`). The 10+ recent salience-tagging PRs now have a deployment target. |
| #2802 | `feat(garage-door)`: mount `PrecedentTickerCairoSource` in right column at (1380, 720, 460×140) | merged 04:29Z (admin) | Stacked directly below #2799. Same feature-flag pattern (`HAPAX_LORE_PRECEDENT_TICKER_ENABLED`). |
| #2805 | `test(layouts)`: drop pins for purged `default-legacy.json` + `examples/vinyl-focus.json` | OPEN, BLOCKED | Removes ~12 CI-blocking `FileNotFoundError` failures. Two files: `test_programme_banner_in_layouts.py` + `test_default_layout_render_stage_pins.py`. 34 tests pass locally. Awaiting admin-merge. |

All four were single-file or two-file PRs, single-theme. Same pattern as recent zeta cadence.

## Right-column inventory after this session (garage-door)

| y-band | content | z |
|--------|---------|---|
| 0..380 | reverie | 15 |
| 396..524 | m8 oscilloscope | 3 |
| 420..460 | stance indicator (overlap) | 54 |
| 480..520 | grounding ticker (overlap) | 52 |
| 560..700 | **chronicle ticker** (#2799) | 52 |
| 720..860 | **precedent ticker** (#2802) | 52 |
| 860..1080 | lyrics scroll / right_marker | 2 |

The previously-empty `y=525..860` band is now stacked with two typed authorship surfaces. Saturation point — adding a third ward without operator approval would over-stuff.

## In-flight queued work (next zeta session)

### Continuation of #2805 — purged-layout test cleanup tail

`#2805` closes the `default-legacy.json` + `examples/vinyl-focus.json` tail. Three more layouts were purged in #2770 and have orphan test references that still produce CI `FileNotFoundError` failures:

| Test file | Missing fixture |
|-----------|-----------------|
| `tests/studio_compositor/test_cbip_dual_ir_displacement.py::TestRegistrationAndLayout::test_example_layout_is_valid` | `config/compositor-layouts/examples/cbip-dual-ir-displacement.json` |
| `tests/studio_compositor/test_research_poster_ward_family.py::test_research_poster_example_layout_is_declarable` | `config/compositor-layouts/examples/research-poster-family.json` |
| `tests/studio_compositor/test_mobile_layout.py::test_mobile_json_matches_portrait_schema` | `config/compositor-layouts/mobile.json` |

Same pattern as #2805: remove parametrize entries / skip-when-missing / delete obsolete tests. Each is a 5-15 line PR. Could ship as one combined PR or one per file.

Also pre-existing in main: `tests/effect_graph/test_smoke.py::TestPresetCompilation::test_all_presets_compile` and siblings fail with `GraphValidationError: Disconnected node 'posterize'`. Probably a single bad preset that wires `posterize` without a downstream connection — find it via `grep -rln '"posterize"' presets/` and fix the wiring or remove the dangling node.

### Other unmounted Cairo sources (low priority)

Garage-door right column saturated. But other cairo classes are registered + tested but never mounted:

- `ProgrammeBannerWard` (540×280) — too big for garage-door without operator approval; mounted in `default.json` at top-strip.
- `ProgrammeStateCairoSource` / `ProgrammeHistoryCairoSource` — programme-cycle ward family.
- `VinylPlatterCairoSource` — was in the purged `vinyl-focus.json`; reintroduction needs operator approval.
- `ConstructivistResearchPosterWard` / `ASCIISchematicWard` — research-register wards.
- `CBIPDualIrDisplacementCairoSource` — CBIP family; was in the purged `cbip-dual-ir-displacement.json`.

If the operator wants more right-column or top-strip work, evaluate each against current saturation before mounting.

### Other directive options not pursued

- **Audio reactivity tightening** — touched `ward param modulation` heartbeat (`agents/parametric_modulation_heartbeat/heartbeat.py`); current state ships `border_pulse_hz` and `scale_bump_pct` from envelopes. Plausible extension: add `glow_radius_px` driven by `breath.amplitude`. Risk: runtime behavior change, harder to validate without livestream test.
- **Phase 13 CBIP cc-task** — none active in the queue at session close. All CBIP-tagged tasks are in `closed/`.

## Hooks + branch state

- Local zeta branches: only `zeta/handoff-2026-05-07` (this branch). Earlier `zeta/banned-luma-grandfather-cap-tighten`, `zeta/garage-door-chronicle-ticker-mount`, `zeta/garage-door-precedent-ticker-mount` were deleted post-merge.
- Remote zeta branches: `zeta/cairo-wards-heartbeat-extension-gap26` (PR #2790 closed; alpha shipped #2788 in main; commit `17afba81` lives only on the closed-PR ref). `zeta/hero-effect-rotator-tests-gap15` has open PR #2795 — KEEP, contract tests gap-#15 stage-1 work. `zeta/test-fix-purged-layout-refs` has open PR #2805. `zeta/handoff-2026-05-07` (this).
- Hook check: `no-stale-branches.sh` blocks new branches whenever any unmerged exist; was a real friction during this session (had to wait for #2798 admin-merge before opening #2799).
- The 270s `/loop` wakeup is being canceled with this handoff (no further `ScheduleWakeup` call). The Monitor task `b2m8per08` ("Main CI segment_iteration_review test status") is NOT one I armed — leaving it alone.

## Audit notes for next zeta

- The pre-existing main breakage (`Disconnected node 'posterize'` + missing layout fixtures) blocks normal CI. Operator/RTE has been admin-merging zeta PRs through it. If next session wants clean CI, fixing the `posterize` issue is the highest-leverage move (one bad preset blocks 4 effect_graph tests).
- Both newly-mounted tickers (`#2799` chronicle, `#2802` precedent) are feature-flagged OFF. Operator should validate each independently after toggling `HAPAX_LORE_*_TICKER_ENABLED=1` and restarting the compositor — visual sanity check that the typography reads cleanly against the lyrics scroll layered behind them. If one looks bad in-broadcast, the right-column z-order or x-offset can be tuned without touching the source class.

## End-state

- Zeta worktree clean except for ephemeral `.claude/scheduled_tasks.lock` (untracked).
- Loop heartbeat canceled.
- 4 PRs shipped (3 merged, 1 in-flight pending admin-merge).
- No active claim. `~/.cache/hapax/relay/zeta.yaml` reflects ACTIVE_PR / `current_pr: 2798` from earlier in the session — would benefit from refresh at next session start.
