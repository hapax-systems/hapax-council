# Condition: cond-phase-a-homage-active-001

**Declared:** 2026-04-18
**Parent condition:** cond-phase-a-volitional-director-001
**Status:** declared-not-yet-active (activation pending Phase 10 rehearsal)
**Declarer:** alpha (HOMAGE framework epic, task #115)
**Related DEVIATION:** none (new condition, not a deviation — HOMAGE is a
deliberate parameter change, not a bug fix)
**Design spec:** `docs/superpowers/specs/2026-04-18-homage-framework-design.md`
**Implementation plan:** `docs/superpowers/plans/2026-04-18-homage-framework-plan.md`

## Delta description (vs parent)

Enumerated concrete changes relative to `cond-phase-a-volitional-director-001`:

1. **HOMAGE package always-on.** A `HomagePackage` (data bundle: grammar,
   typography, palette, transition vocabulary, coupling rules, signature
   conventions, voice register) is resolved at compositor boot and every
   ward renders through the package's grammar. BitchX is the first
   concrete package. Parent had no package abstraction; compositor
   rendered with an ad-hoc sans-serif-on-dark aesthetic.

2. **Transition FSM on every ward.** Every `CairoSource` subclass inherits
   `HomageTransitionalSource` and renders through an
   `absent → entering → hold → exiting → absent` FSM. Non-transitional
   draw calls log a violation. Parent had paint-and-hold rendering only.

3. **Choreographer reconciliation.** A `Choreographer` module runs at
   compositor tick rate, reads pending transitions from
   `/dev/shm/hapax-compositor/homage-pending-transitions.json`,
   enforces concurrency rules (max 2 simultaneous entries, max 2
   exits, netsplit-burst with cooldown), and emits the ordered
   transition plan. Parent had no arbiter.

4. **Bidirectional ward ↔ shader coupling.** Choreographer writes the
   active-transition summary to `uniforms.custom[4]` (active energy,
   palette accent hue, signature-artefact intensity, rotation phase);
   WGSL shaders read it. Shader dominant-activity derivative flows
   back into Python via `/dev/shm/hapax-imagination/shader-feedback.json`.
   Parent: one-way Python → shader signal flow only.

5. **`homage.*` IntentFamily extensions.** Six new family entries
   (`homage.rotation`, `homage.emergence`, `homage.swap`, `homage.cycle`,
   `homage.recede`, `homage.expand`) the director can recruit through
   existing `AffordancePipeline`. Parent's director had no explicit
   transition recruitment — visual state advanced ambiently.

6. **`StructuralIntent.homage_rotation_mode`.** Structural director
   emits one of `steady | deliberate | rapid | burst`, scaling the
   rotation cadence of signature artefacts. Parent's structural
   director had no compositional cadence agency.

7. **`VoiceRegister` enum coupling.** CPAL reads
   `/dev/shm/hapax-compositor/homage-voice-register.json` and selects
   `announcing | conversing | textmode` register, influencing prompt
   partner-block construction and Kokoro TTS pacing. Parent had
   persona doctrine but no package-selectable register.

8. **`PerceptualField.homage: HomageField`.** The narrative director's
   `PerceptualField` input gains a `homage` sub-field carrying
   `package_name`, `active_artefact_form`, `voice_register`,
   `consent_safe_active`. The director cites these in
   `grounding_provenance` entries. Parent's director could not
   reference the active package or register because the information
   was not surfaced.

9. **Consent-safe variant.** When
   `/dev/shm/hapax-compositor/consent-safe-active.json` exists, the
   choreographer swaps `bitchx` for `bitchx_consent_safe` (identity
   accents collapsed to muted; empty artefact corpus). HOMAGE never
   overrides the consent gate — the gate wins. Parent had a general
   consent-safe layout but no homage-specific contract.

## Measurable hypotheses

- **H1: palette coverage.** 10-minute-window palette-coverage ratio
  remains ≥ 0.5 (non-regression from parent) across the 6
  compositional families even after HOMAGE lands.
- **H2: transition legibility.** Zero `hapax_homage_violation_total`
  increments during 30-minute rehearsal.
- **H3: grounding_provenance coverage including homage signals.**
  Mean provenance signals per narrative tick remains ≥ 3 with
  homage-sourced signals present in ≥ 25% of ticks under the new
  condition.
- **H4: operator stress non-regression.** Operator stimmung
  dimensions (`operator_stress`, `operator_energy`) under HOMAGE
  remain within 1σ of parent baseline.
- **H5: director activity distribution non-regression.** Activity
  distribution under HOMAGE within 2σ of parent baseline (same
  activities at same rates; HOMAGE adds compositional moves, not
  director-activity moves).

## Activation criteria

All of:

- HOMAGE Phases 1–9 merged to main (framework, BitchX package, FSM,
  legibility surfaces migrated, intent families wired, shader
  coupling, voice register, structural hint, research condition
  declared — this file).
- Phase 10 rehearsal passes — 30-minute private-mode rehearsal per
  `docs/superpowers/specs/2026-04-18-homage-framework-design.md §8`:
  - No `hapax_homage_violation_total` increments.
  - Activity distribution within 2σ of parent baseline.
  - Stimmung dimensions unchanged beyond noise band.
  - `grounding_provenance` signal distribution includes homage
    signals but no unexpected new signals.
  - Visual-contrast audit passes (overlay text readable against all
    9 shader dimensions × colour-warmth range).
- `scripts/research-registry.py open cond-phase-a-homage-active-001 --parent cond-phase-a-volitional-director-001`
  invoked locally; `/dev/shm/hapax-compositor/research-marker.json`
  carries the new id.
- Operator sign-off at rehearsal completion.

## Frozen files

Inherit from parent
(`cond-phase-a-volitional-director-001`). Additionally freeze once
framework lands:

- `shared/homage_package.py`
- `agents/studio_compositor/homage/__init__.py`
- `agents/studio_compositor/homage/choreographer.py`
- `agents/studio_compositor/homage/transitional_source.py`
- `agents/studio_compositor/homage/bitchx.py`
- `agents/studio_compositor/homage/rendering.py`
- `agents/studio_compositor/homage/substrate_source.py`

## Rollback criteria

- `hapax_homage_violation_total` ≥ 1 per 10-minute window during
  live stream.
- Operator stimmung regression > 1σ vs parent baseline.
- `grounding_provenance` coverage regresses below parent baseline
  after 20 minutes of active use (H3 violated).
- Operator override.

Rollback procedure: set `HAPAX_HOMAGE_ACTIVE=0` in the systemd drop-in
(currently default-ON per Phase 12), daemon-reload, restart compositor.
Mark this condition as closed with failure note; parent condition
resumes.

## Sample-size target

≥ 8 post-activation sessions before MCMC BEST analysis, matching
parent's ongoing sample target. Aims for early-to-mid May at current
session cadence.

## Data-path notes for analysts

- Condition ID in `~/hapax-state/stream-experiment/director-intent.jsonl`
  under `condition_id` per line.
- Langfuse tag `stream-experiment` with `condition_id` metadata.
- Prometheus metrics labelled `condition_id=<id>` plus the HOMAGE-
  specific counters:
  - `hapax_homage_package_active{package}`
  - `hapax_homage_transition_total{package, transition_name}`
  - `hapax_homage_choreographer_rejection_total{reason}`
  - `hapax_homage_violation_total{package, kind}`
  - `hapax_homage_signature_artefact_emitted_total{package, form}`
- `PerceptualField.homage` sub-field present on every director tick
  JSONL record post-activation: `homage.package_name`,
  `homage.active_artefact_form`, `homage.voice_register`,
  `homage.consent_safe_active`.

## Governance — axiom compliance

| Axiom | Compliance |
|---|---|
| `single_user` | No per-spectator customisation. One rendered surface. |
| `executive_function` | Package ships pre-configured; operator does not tune per-session. |
| `management_governance` | Signature artefacts carry only Hapax-authored content; never feedback about named persons. |
| `interpersonal_transparency` | Chat rendering under BitchX grammar uses aggregate counts only (tier counts + unique-author counts), never names or bodies. `it-irreversible-broadcast` gate: consent-safe variant engages when flag file present. |
| `corporate_boundary` | HOMAGE does not surface work data. |
