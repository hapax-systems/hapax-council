# AoA Pane AVSDLC Release Dossier

**Authority case:** CASE-LIVESTREAM-AOA-20260516
**Date:** 2026-05-20
**Witness:** delta session (automated)
**Status:** Release evidence assembled; live visual witness deferred to compositor runtime

## 1. Impacted AVSDLC Axes

| Axis | Applicable | Standard | Evidence Source |
|------|-----------|----------|----------------|
| Design language compliance | Yes | `docs/logos-design-language.md` §11 | PR #3439 (proof content binding) |
| Text readability | Yes | AVSDLC visual evidence contract §2 | Pane content uses governed text rendering |
| Camera framing quality | Yes | AVSDLC visual evidence contract §3 | AoA layout mode (`agents/studio_compositor/layout.py:198`) |
| Obscuring compliance | Yes | AVSDLC visual evidence contract §3.5 | PR #3442 (privacy posture gates) |
| Privacy posture | Yes | Axiom: interpersonal_transparency (weight 88) | PR #3442 (anti-parasocial gates) |
| Frame pacing | Yes | No regression from baseline | Deferred: requires live compositor runtime |
| Audio routing | No | N/A | AoA panes are visual-only surfaces |

## 2. Dependency Evidence

### PR #3439 — feat(visual): bind proof content to AoA panes [MERGED]

- Outer pane content bound to compositor proof-of-concept content pipeline
- Content renders within pane geometry, not fullscreen
- No fourth-wall violation: content stays within triangular aperture bounds

### PR #3443 — feat(visual): gate AoA inner pane payload LOD [MERGED]

- Inner pane Level-of-Detail accent rendering
- LOD gating prevents high-detail content from rendering at inappropriate distances
- Pane content scales with compositor viewport, not independently

### PR #3442 — fix(visual): gate AoA pane privacy postures [MERGED]

- Privacy posture gates enforced on AoA pane content
- Anti-parasocial gates prevent pane content from displaying non-operator personal data
- Consent gate fail-closed on `consent_required` capabilities (per USR spec)

## 3. Negative Evidence — Fourth-Wall / Fullscreen Behavior

| Forbidden Behavior | Gate | Evidence |
|-------------------|------|----------|
| Pane content rendering fullscreen | AoA layout constrains to corner apertures | `_aoa_layout()` in `layout.py:198` clips to `TileRect` |
| Pane content overlapping camera tiles | Layout geometry is exclusive | Camera tiles and AoA panes occupy disjoint regions |
| Pane content bypassing compositor pipeline | All pane rendering goes through `CairoSourceRunner` | No direct framebuffer writes from pane content |
| Pane content during non-AoA layout modes | `is_aoa_layout_mode()` guard | Panes only render when layout mode is "aoa" |

## 4. Privacy and Anti-Parasocial Gates

| Gate | Implementation | PR | Status |
|------|---------------|-----|--------|
| Consent gate on pane content | Fail-closed on `consent_required` | #3442 | Merged |
| Anti-parasocial content filter | No non-operator personal data in panes | #3442 | Merged |
| Privacy posture inheritance | Panes inherit compositor privacy mode | #3442 | Merged |
| Interpersonal transparency axiom | Weight 88, constitutional | Axiom registry | Enforced |

## 5. Frame Pacing Evidence

**Status: Deferred to live witness.**

Frame pacing evidence requires a sustained (>10 minute) compositor runtime with AoA
layout mode active. This cannot be collected without the compositor running on the
operator's hardware with cameras connected.

**Collection method when available:**
1. `scripts/compositor-frame-capture.sh` at 10-second intervals during a 10-minute run
2. Verify no frame drops attributable to AoA pane rendering
3. Compare frame timing against non-AoA baseline

**Acceptance threshold:** AoA pane rendering adds <2ms to per-frame compositor latency.

## 6. Residual Risks

| Risk | Severity | Mitigation | Follow-Up |
|------|----------|-----------|-----------|
| Frame pacing not yet witnessed live | Medium | Deferred to first AoA livestream session | `compositor-layout-fine-iteration` task |
| LOD accent thresholds are initial estimates | Low | Tunable at runtime via pane config | Iterate during live use |
| AoA layout only supports 3 cameras | Low | Design constraint, not a bug | Document in layout reference |
| No A/B comparison between AoA and balanced modes | Low | Deferred to iteration | Collect during first stream |

## 7. Revision Triggers

This dossier must be revised if:

- AoA pane content sources change (new content types added)
- Privacy posture gates are modified
- Layout geometry is altered (pane sizes, positions)
- Compositor pipeline changes affect pane rendering path
- Frame pacing evidence contradicts the <2ms threshold
