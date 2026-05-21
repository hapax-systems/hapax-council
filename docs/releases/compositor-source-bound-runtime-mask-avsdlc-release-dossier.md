# Compositor Source-Bound Runtime Mask AVSDLC Release Dossier

**Authority case:** `20-projects/hapax-requests/active/REQ-20260518225227-compositor-incident-recovery-ledger.md` in the operator vault
**Task:** `compositor-temporal-entity-bound-effect-repair`
**PR:** #3624
**Branch:** `codex/compositor-source-bound-runtime-mask`
**Evidence collected:** 2026-05-21T02:02:35Z
**Status:** Release evidence assembled for merge; incident closure deferred to post-activation witness

## 1. Impacted AVSDLC Axes

| Axis | Applicable | Standard | Evidence source |
|------|------------|----------|-----------------|
| Visual | Yes | AVSDLC visual evidence contract and operator no-fourth-wall mandate | Runtime source-bound mask tests; live screenshots; paired frame audit |
| Audiovisual runtime witness | Runtime-adjacent | Live-surface compositor incident standards | `hapax-live-surface-preflight --require-full-surface` |
| Audio | No source mutation | Audio topology is not changed by this PR | Residual audio/director state is noted as out of scope |

This PR changes the visual effect execution path in `hapax-visual`. It does not
claim to solve camera enumeration, director silence, audio routing, or final
effect taste. It blocks one class of unacceptable visual behavior: shader passes
with `source_bound=true`, `full_surface=true`, and
`fourth_wall_policy=forbid_foreground_overlay` should not paint the whole output
plane as a detached foreground pane.

## 2. Standards Declaration

Applied standards:

- No fourth-wall/glass-pane effect treatment: effects work on livestream
  entities/source geometry, not on a reified output pane.
- No permanent disabling as the repair: dramatic effects remain available when
  bounded by visible source presence.
- Runtime metadata must distinguish policy intent from runtime enforcement.
- Live-surface release evidence must include fresh visual witness and runtime
  media witness before merge.

Failure predicates:

- A source-bound effect visibly floods empty field outside live geometry.
- Runtime output reads as a foreground pane laid over the livestream space.
- The repair only changes metadata while the pipeline still renders the pass as
  an unconditional full-screen replacement.
- Post-activation drift state does not expose the runtime mask route for repaired
  passes.

## 3. Implementation Evidence

PR #3624 adds a source-bound runtime mask in
`hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs`.

Behavior:

- High-risk source-bound/full-surface/no-fourth-wall passes render into a scratch
  texture.
- The pass is composited back through a luma-derived live-scene mask.
- Empty field remains anchored to the incoming scene instead of being painted by
  the effect pass.
- Runtime metadata records the mask route with
  `runtime_source_bound_mask` and `runtime_source_bound_mask_basis`.

Local verification passed before this dossier:

- `cargo test -p hapax-visual dynamic_pipeline --lib`
- `cargo test -p hapax-visual effect_drift --lib`
- `cargo test -p hapax-visual --lib`
- `git diff --check`

## 4. Fresh Visual Witness

Primary frame witness:

- `screenshots/pr3624-premerge-live-surface/20260521T015624Z` in the local Hapax cache

Paired pre-FX/final witness:

- `screenshots/paired-fx-audit/pr3624-premerge-paired/20260521T015802Z` in the local Hapax cache

Paired audit summary:

- 8 paired samples captured from `/dev/shm/hapax-imagination/3d-proof/frame.jpg`
  and `/dev/shm/hapax-visual/frame.jpg`.
- Final output changed continuously across samples; transition metrics show no
  zero-motion static hold in the sampled window.
- The center region carried the largest effect delta, which is consistent with
  source-bound geometry receiving stronger treatment than empty field.

This is pre-merge witness against the current active runtime. It verifies the
current incident context and provides comparison material, but cannot prove the
new runtime mask is active until #3624 is merged and activated.

## 5. Runtime Media Witness

Preflight receipt:

- `/tmp/hapax-preflight-3624-current.txt`

Result:

- `state`: `degraded_containment`
- `full_surface_failures`: `[]`
- `final_frame_classification.width`: 1280
- `final_frame_classification.height`: 720
- `full_surface_performance.stage_fps.imagination_output`: about 38.5
- `full_surface_performance.stage_fps.imagination_v4l2_writer`: about 38.5

Known residual blockers in that witness:

- `not_all_cameras_healthy`: `c920-room` is configured for serial `86B6B75F`,
  but that USB device is not currently enumerated by the host.
- `director_silent`: unrelated to the source-bound visual effect repair.

The preflight is therefore acceptable as release evidence for this visual repair
but not as global incident closure evidence.

## 6. Effect Inventory Evidence

Audit receipt:

- `/tmp/pr3624-effect-surface-audit.json`
- `/tmp/pr3624-effect-drift-state.json`

Audit summary:

- 86 graph presets observed.
- 63 shader node types observed.
- 60 live-surface-bounded node types observed.
- 0 live-surface blocked-pending-repair node types.
- 0 live-surface unclassified node types.
- Active drift sample: 22 passes, 16 non-neutral passes.

The active pre-merge drift state does not yet include
`runtime_source_bound_mask`; that is expected because #3624 is not deployed.
Post-merge activation must confirm the metadata appears in live state.

## 7. Residual Risks

| Risk | Severity | Status |
|------|----------|--------|
| Sixth camera absent from USB enumeration | High | Out of scope for #3624; covered by required-camera presence witness gate |
| Director silence | Medium | Out of scope for this PR |
| Effect variation/taste still needs iteration | Medium | This PR repairs routing semantics only |
| Runtime mask not yet witnessed live | Medium | Requires post-merge activation readback |
| Source-luma mask may need tuning for very dark geometry | Low | Follow-up tuning if post-activation witness shows over-preservation |

## 8. Release Decision

This dossier authorizes merging #3624 as a visual-routing repair. It does not
authorize closing the livestream compositor incident.

Post-merge requirements:

1. Activate merged source through the normal source activation path.
2. Restart or verify `hapax-imagination` and the visual output chain as needed.
3. Rerun `scripts/hapax-live-surface-preflight --require-full-surface`.
4. Capture fresh paired pre-FX/final output witness.
5. Confirm live drift metadata exposes `runtime_source_bound_mask` on repaired
   source-bound passes.
6. Confirm no foreground fourth-wall/glass-pane flooding is visible.

## 9. Revision Triggers

Revise this dossier if:

- The source-bound mask route changes.
- Drift metadata names change.
- The live witness shows source geometry being under-treated or empty field being
  over-treated.
- A later effect family bypasses `DynamicPipeline` and needs equivalent
  source-bound enforcement.
