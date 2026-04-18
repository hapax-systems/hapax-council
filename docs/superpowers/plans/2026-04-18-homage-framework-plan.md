# HOMAGE Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the HOMAGE framework (spec §1–§14) with the BitchX package as its first concrete member, migrating all 22 compositor wards onto a transition FSM + choreographer, coupling ward state bidirectionally with the WGSL shader pipeline, and declaring a new research condition before activation.

**Architecture:** A `HomagePackage` data bundle (grammar, typography, palette, transition vocabulary, coupling, signatures) drives a `HomageTransitionalSource` base class every Cairo ward inherits; a choreographer reconciles pending transitions against concurrency rules; `homage.*` IntentFamily entries let the director recruit rotations, emergences, swaps. `StructuralIntent.homage_rotation_mode` gains structural-director agency; a `VoiceRegister` enum couples tonality to package state. Nothing paints-and-holds; every ward appearance is a transition.

**Tech stack:** Python 3.12 (Pydantic, pytest, Cairo via PyGObject), Rust (WGSL compiler extension), WGSL (uniform layout extension), GStreamer (compositor unchanged), systemd user units (rebuild triggers).

**Governance:** New research condition `cond-phase-a-homage-active-001` opened pre-activation; 8 spec amendments land alongside implementation; interpersonal_transparency + it-irreversible-broadcast axioms enforced by consent-safe gate and chat-aggregate rendering.

---

## Phase 1 — Spec + Plan Docs

**Branch:** `feat/homage-epic-spec-plan` (current branch). **PR:** 1 of 12.

**Files:**
- Create: `docs/superpowers/specs/2026-04-18-homage-framework-design.md` (done in this PR)
- Create: `docs/superpowers/plans/2026-04-18-homage-framework-plan.md` (this file)

**Tasks:**

- [ ] **Step 1:** Commit spec + plan.
- [ ] **Step 2:** Push and open PR.
- [ ] **Step 3:** CI must pass (doc-only change; lint+typecheck+test on docs paths is filtered but run anyway).
- [ ] **Step 4:** Merge. No runtime effect; the epic is mobilised.

---

## Phase 2 — HomagePackage Abstraction + BitchX Package Data

**Branch:** `feat/homage-package-abstraction`. **PR:** 2 of 12.

**Files:**
- Create: `shared/homage_package.py` — the `HomagePackage`, `GrammarRules`, `TypographyStack`, `HomagePalette`, `TransitionVocab`, `CouplingRules`, `SignatureRules`, `SignatureArtefact` Pydantic models.
- Create: `shared/voice_register.py` — the `VoiceRegister` enum.
- Create: `agents/studio_compositor/homage/__init__.py` — registry, `get_active_package()`, `register_package()`.
- Create: `agents/studio_compositor/homage/bitchx.py` — BitchX-specific `HomagePackage` instance built from the authenticity data.
- Create: `assets/homage/bitchx/artefacts.yaml` — seed corpus of ~40 signature artefacts (quit-quips, join-banners, MOTD blocks, kick-reasons).
- Create: `assets/fonts/homage/bitchx/README.md` — font provenance + licensing note (fonts added in follow-on if not already present).
- Create: `tests/shared/test_homage_package.py` — pin schema, round-trip, defaults.
- Create: `tests/studio_compositor/homage/test_bitchx_package_authenticity.py` — pin palette role assignments, grammar rules, anti-pattern detection.

**Tasks (TDD):**

- [ ] **Step 1:** Write failing test `test_homage_package_schema_round_trip` — construct a minimal `HomagePackage`, dump to dict, reload, assert equal.

    ```python
    def test_homage_package_schema_round_trip():
        pkg = HomagePackage(
            name="bitchx",
            version="1.0.0",
            grammar=GrammarRules(...),
            # ... fill minimally
        )
        reconstructed = HomagePackage.model_validate(pkg.model_dump())
        assert reconstructed == pkg
    ```

- [ ] **Step 2:** Run `uv run pytest tests/shared/test_homage_package.py::test_homage_package_schema_round_trip -v` → FAIL (module missing).

- [ ] **Step 3:** Implement `shared/homage_package.py` with the 7 Pydantic models from spec §4.1–§4.7. Add `VoiceRegister` enum in `shared/voice_register.py`.

- [ ] **Step 4:** Run test → PASS.

- [ ] **Step 5:** Commit `feat(homage): HomagePackage + VoiceRegister schemas`.

- [ ] **Step 6:** Write failing test `test_bitchx_palette_role_assignments` — mIRC-16 contract pinned per spec §4.4.

- [ ] **Step 7:** Run test → FAIL.

- [ ] **Step 8:** Implement `agents/studio_compositor/homage/bitchx.py` with the `BITCHX_PACKAGE` instance.

- [ ] **Step 9:** Run test → PASS.

- [ ] **Step 10:** Write failing tests for:
    - `test_bitchx_grammar_rules_load_bearing` — punctuation_colour_role="muted", line_start_marker="»»»", container_shape="angle-bracket", raster_cell_required=True, transition_frame_count=0.
    - `test_bitchx_typography_stack_cp437_primary` — primary font is CP437-capable.
    - `test_bitchx_signature_artefact_corpus_has_required_forms` — at least one of each: quit-quip, join-banner, motd-block, kick-reason.
    - `test_anti_pattern_detection_fires_on_bad_config` — feeding a non-monospace font or frame_count > 0 into the BitchX package raises a validation error.

- [ ] **Step 11:** Implement the BITCHX_PACKAGE fully + artefacts.yaml loader + anti-pattern validators.

- [ ] **Step 12:** Run tests → ALL PASS.

- [ ] **Step 13:** Commit `feat(homage): BitchX package data + artefact corpus`.

- [ ] **Step 14:** Write failing test `test_registry_returns_active_package`.

- [ ] **Step 15:** Implement the registry + active-package resolution (reads `/dev/shm/hapax-compositor/homage-active.json`, defaults to `bitchx`).

- [ ] **Step 16:** Commit `feat(homage): package registry + active-package resolution`.

- [ ] **Step 17:** Run `uv run ruff check` + `uv run pyright` → clean.

- [ ] **Step 18:** Push, open PR, await CI green, merge.

**Acceptance:** `from agents.studio_compositor.homage import get_active_package; pkg = get_active_package()` returns the `BITCHX_PACKAGE` instance with full grammar + palette + artefact corpus. No wards touched yet.

---

## Phase 3 — Transition FSM + Choreographer

**Branch:** `feat/homage-fsm-choreographer`. **PR:** 3 of 12.

**Files:**
- Create: `agents/studio_compositor/homage/transitional_source.py` — `HomageTransitionalSource` mixin class.
- Create: `agents/studio_compositor/homage/choreographer.py` — the reconciliation + transition-plan emitter.
- Modify: `agents/studio_compositor/cairo_source.py:384–512` — `CairoSourceRunner.run()` routes through mixin hooks when enabled (feature-flag by `HAPAX_HOMAGE_ACTIVE` env var until Phase 10).
- Modify: `shared/director_observability.py` — add `hapax_homage_transition_total`, `hapax_homage_package_active`, `hapax_homage_choreographer_rejection_total`, `hapax_homage_violation_total`, `hapax_homage_signature_artefact_emitted_total` (spec §6).
- Create: `tests/studio_compositor/homage/test_transitional_source_fsm.py` — per-state render invariants.
- Create: `tests/studio_compositor/homage/test_choreographer_invariants.py` — concurrency rules, violation detection.

**Tasks (TDD):**

- [ ] **Step 1:** Write failing test `test_absent_state_renders_no_op` — a transitional source in `absent` state produces a fully transparent surface.

- [ ] **Step 2:** Run → FAIL (module missing).

- [ ] **Step 3:** Implement the mixin with the 4-state FSM + hook methods.

- [ ] **Step 4:** Run → PASS.

- [ ] **Step 5:** Commit `feat(homage): HomageTransitionalSource mixin with 4-state FSM`.

- [ ] **Step 6:** Write failing tests for entry/exit/hold render behaviours:
    - `test_entering_state_applies_entry_transition` — during `entering`, the package's named entry transition is invoked.
    - `test_hold_state_applies_grammar_rules` — during `hold`, line-start marker, colour roles, container shape are honoured.
    - `test_exiting_state_applies_exit_transition` — during `exiting`, the package's named exit transition is invoked.

- [ ] **Step 7:** Implement the state dispatch in the mixin's `render()` wrapper.

- [ ] **Step 8:** Run → PASS. Commit `feat(homage): entry/hold/exit state rendering dispatch`.

- [ ] **Step 9:** Write failing test `test_choreographer_rejects_excess_simultaneous_entries` — if 3 entries pending and max is 2, one is deferred.

- [ ] **Step 10:** Implement `choreographer.reconcile()` with concurrency limits.

- [ ] **Step 11:** Run → PASS. Commit `feat(homage): choreographer concurrency reconciliation`.

- [ ] **Step 12:** Write failing tests for:
    - `test_choreographer_emits_transition_plan_to_animation_state` — pending transitions are written via `animation_engine.append_transitions`.
    - `test_choreographer_publishes_shader_coupling_payload` — `uniforms.custom[4]` 4-float payload written to `uniforms.json`.
    - `test_choreographer_logs_violation_on_non_choreographed_draw` — a ward that draws without a choreographer-emitted transition fires `hapax_homage_violation_total`.

- [ ] **Step 13:** Implement the three behaviours.

- [ ] **Step 14:** Run → PASS. Commit `feat(homage): choreographer emits plan + shader coupling + violation logging`.

- [ ] **Step 15:** Extend `director_observability.py` with the 5 new counters. Test: `test_homage_metrics_present`.

- [ ] **Step 16:** Commit `feat(observability): homage Prometheus counters`.

- [ ] **Step 17:** Wire the feature flag: `HAPAX_HOMAGE_ACTIVE=0` (default until Phase 10) short-circuits the FSM back to legacy paint-and-hold.

- [ ] **Step 18:** Ruff + pyright clean. Push, PR, CI, merge.

**Acceptance:** With `HAPAX_HOMAGE_ACTIVE=1`, every `CairoSourceRunner` render goes through the mixin; the choreographer reconciles transitions at tick rate; Prometheus sees the new counters. No existing ward migrated yet.

---

## Phase 4 — Legibility Surface Migration (first 4 wards)

**Branch:** `feat/homage-legibility-migration`. **PR:** 4 of 12.

**Files:**
- Modify: `agents/studio_compositor/cairo_sources/legibility_sources.py` — `ActivityHeaderCairoSource`, `StanceIndicatorCairoSource`, `ChatKeywordLegendCairoSource`, `GroundingProvenanceTickerCairoSource` inherit `HomageTransitionalSource`.
- Modify: `config/compositor-layouts/default.json:71–132` — assignments for these surfaces gain `transition_in`, `transition_out`, `transition_hold` metadata keys.
- Create: `tests/studio_compositor/homage/golden/` — golden frames for the 4 surfaces in BitchX `entering`, `hold`, `exiting` states (PNGs or deterministic byte hashes).
- Create: `tests/studio_compositor/homage/test_legibility_surface_migration.py`.

**Tasks (TDD):**

- [ ] **Step 1:** Write failing test `test_activity_header_renders_in_bitchx_grammar` — rendered surface, under BitchX package, shows:
    - Grey `[` bracket, bright identity text, grey `]`.
    - `»»»` prefix.
    - CP437-capable font selected.
    - No sans-serif fallback.

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3:** Migrate `ActivityHeaderCairoSource` to inherit `HomageTransitionalSource` + re-render under package grammar rules.

- [ ] **Step 4:** Run → PASS. Commit `feat(homage): migrate ActivityHeader to HomageTransitionalSource`.

- [ ] **Step 5:** Repeat steps 1–4 for `StanceIndicatorCairoSource` (stance as `[+H <stance>]` IRC-mode-change format).

- [ ] **Step 6:** Repeat for `ChatKeywordLegendCairoSource` — renders as an IRC-style "channel topic" line: `-:- Topic (#homage): <keyword1>, <keyword2>, ...`, all grey punctuation + bright keyword identity.

- [ ] **Step 7:** Repeat for `GroundingProvenanceTickerCairoSource` — renders as an IRC backscroll of join/part-style lines: `* <signal.name> has joined (conf=0.87)`, zero-frame cuts between updates.

- [ ] **Step 8:** Add entry/exit transition metadata to the 4 surfaces in `default.json`. Assignments gain `transition_in: "ticker-scroll-in"`, `transition_out: "ticker-scroll-out"` (per spec §4.5).

- [ ] **Step 9:** Generate golden frames for `entering`, `hold`, `exiting` per surface. Check golden frames into `tests/studio_compositor/homage/golden/`.

- [ ] **Step 10:** Visual-regression test pins the golden frames.

- [ ] **Step 11:** Commit `feat(homage): 4 legibility surfaces under BitchX package`.

- [ ] **Step 12:** Ruff + pyright. Push, PR, CI, merge.

**Acceptance:** With `HAPAX_HOMAGE_ACTIVE=1` on a local rebuild, the 4 legibility surfaces render in BitchX grammar with entry/exit transitions and zero paint-and-hold draws. Golden-frame tests green.

---

## Phase 5 — IntentFamily Extensions + Dispatchers + Director Prompt

**Branch:** `feat/homage-intent-families`. **PR:** 5 of 12.

**Files:**
- Modify: `shared/director_intent.py` — add 6 new `IntentFamily` members: `homage.rotation`, `homage.emergence`, `homage.swap`, `homage.cycle`, `homage.recede`, `homage.expand`.
- Modify: `shared/compositional_affordances.py` — register ~24 `homage.*` capabilities (4 per family × 6 families), each with Gibson-verb narrative.
- Modify: `agents/studio_compositor/compositional_consumer.py` — add `dispatch_homage_rotation`, `dispatch_homage_emergence`, `dispatch_homage_swap`, `dispatch_homage_cycle`, `dispatch_homage_recede`, `dispatch_homage_expand`; extend top-level `dispatch()` routing.
- Modify: `agents/studio_compositor/director_loop.py:595–644` — insert the Homage Composition section from spec §4.12 into the prompt.
- Modify: `scripts/seed-compositional-affordances.py` — include homage.* entries in Qdrant seeding.
- Create: `tests/shared/test_homage_intent_families.py`.
- Create: `tests/studio_compositor/homage/test_homage_dispatchers.py`.
- Create: `tests/studio_compositor/homage/test_director_prompt_includes_homage_section.py`.

**Tasks (TDD):**

- [ ] **Step 1:** Write failing test `test_intent_family_includes_homage_members` — 6 new members.

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3:** Extend enum in `director_intent.py`.

- [ ] **Step 4:** Run → PASS. Commit `feat(intent): homage.* IntentFamily members`.

- [ ] **Step 5:** Write failing test `test_compositional_catalog_includes_homage_entries` — ≥24 entries with `homage.*` family_prefix.

- [ ] **Step 6:** Add catalog entries; extend seed script.

- [ ] **Step 7:** Run → PASS. Commit `feat(homage): catalog + seed for homage.* families`.

- [ ] **Step 8:** Write failing tests for each dispatcher — given a recruitment record, writes the correct transition to `homage-pending-transitions.json`.

- [ ] **Step 9:** Implement dispatchers.

- [ ] **Step 10:** Run → PASS. Commit `feat(homage): dispatchers for homage.* families`.

- [ ] **Step 11:** Write failing test `test_every_catalog_capability_has_a_dispatcher` (extends existing) — ward.* AND homage.* routes.

- [ ] **Step 12:** Extend `dispatch()` top-level routing for homage prefixes.

- [ ] **Step 13:** Run → PASS. Commit `feat(homage): dispatch() routing for homage prefixes`.

- [ ] **Step 14:** Write failing test `test_director_prompt_contains_homage_section` — the prompt output from `_build_unified_prompt()` contains "## Homage Composition".

- [ ] **Step 15:** Insert the section per spec §4.12.

- [ ] **Step 16:** Run → PASS. Commit `feat(director): homage composition prompt section`.

- [ ] **Step 17:** Ruff + pyright. Push, PR, CI, merge.

**Acceptance:** The narrative director can emit homage.* intent families; dispatchers write to `homage-pending-transitions.json`; the choreographer (Phase 3) picks them up and reconciles. No visual change yet if `HAPAX_HOMAGE_ACTIVE=0`.

---

## Phase 6 — Ward↔Shader Bidirectional Coupling

**Branch:** `feat/homage-shader-coupling`. **PR:** 6 of 12.

**Files:**
- Modify: `hapax-logos/crates/hapax-visual/src/shaders/uniforms.wgsl:16–28` — document `custom[4]` as the homage payload: `.x=active_transition_energy, .y=palette_accent_hue_deg, .z=signature_artefact_intensity, .w=rotation_phase`.
- Create: `hapax-logos/src-imagination/src/homage_feedback.rs` — emits `shader_energy: f32` from the dominant-pass activity per frame to `/dev/shm/hapax-imagination/shader-feedback.json`.
- Modify: `agents/studio_compositor/homage/choreographer.py` — writes the `custom[4]` payload via the existing `uniforms.json` writer.
- Modify: `agents/studio_compositor/homage/transitional_source.py` — on each tick, reads `shader-feedback.json` and modulates the chosen entry/exit transition per coupling rules §4.6.
- Create: `tests/studio_compositor/homage/test_shader_coupling.py`.
- Create: `tests/studio_compositor/homage/test_shader_feedback_modulation.py`.

**Tasks (TDD):**

- [ ] **Step 1:** Write failing test `test_choreographer_writes_custom_4_payload` — checks `uniforms.json` has `custom[4]` keys after a tick with pending transitions.

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3:** Implement the payload writer in choreographer.

- [ ] **Step 4:** Run → PASS. Commit `feat(homage): choreographer writes shader coupling payload`.

- [ ] **Step 5:** Write failing Rust test for `homage_feedback.rs` (cargo test under the imagination crate) — given a mock pipeline with dominant pass activity, emits the correct `shader_energy` float.

- [ ] **Step 6:** Implement in Rust.

- [ ] **Step 7:** Commit `feat(homage): shader feedback emission from imagination crate`.

- [ ] **Step 8:** Write failing Python test `test_transitional_source_modulates_on_shader_feedback` — when `shader_energy > 0.7`, the entry transition selects the "netsplit-burst" variant; when low, selects "ticker-scroll-in".

- [ ] **Step 9:** Implement the read + modulation.

- [ ] **Step 10:** Run → PASS. Commit `feat(homage): ward modulation from shader feedback`.

- [ ] **Step 11:** Add smoke-test: end-to-end tick with a WGSL shader that reads `uniforms.custom[4]` and produces visible grain bump proportional to `.x`. Pin via deterministic WGSL test or visual-regression.

- [ ] **Step 12:** Commit `feat(homage): WGSL grain-bump coupling shader`.

- [ ] **Step 13:** Ruff + pyright + cargo fmt + cargo clippy clean. Push, PR, CI, merge.

**Acceptance:** With `HAPAX_HOMAGE_ACTIVE=1`, a homage.emergence transition on a ward causes the shader pipeline to bump grain proportionally; high shader energy causes subsequent ward entries to use the more intense transition variant. Bidirectional coupling observable end-to-end.

---

## Phase 7 — Voice Register Enum + CPAL Wiring

**Branch:** `feat/homage-voice-register`. **PR:** 7 of 12.

**Files:**
- Modify: `shared/voice_register.py` — finalise enum (done in Phase 2; add helpers).
- Create: `agents/hapax_daimonion/voice_register_reader.py` — reads `/dev/shm/hapax-daimonion/voice-register.json`, caches with TTL.
- Modify: `agents/hapax_daimonion/persona.py` — CPAL prompt construction reads register and injects tonality block (TEXTMODE → clipped IRC-style; ANNOUNCING → existing; CONVERSING → existing).
- Modify: `agents/studio_compositor/homage/__init__.py` — on package activation, write the package's `voice_register_default` to `/dev/shm/hapax-daimonion/voice-register.json`.
- Create: `tests/hapax_daimonion/test_voice_register_reader.py`.
- Create: `tests/hapax_daimonion/test_persona_register_injection.py`.

**Tasks (TDD):**

- [ ] **Step 1:** Write failing test `test_voice_register_reader_returns_package_default_when_file_missing`.

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3:** Implement reader with TTL cache, atomic-tmp+rename tolerance, JSON parse-error fallback.

- [ ] **Step 4:** Run → PASS. Commit `feat(daimonion): VoiceRegister reader with TTL cache`.

- [ ] **Step 5:** Write failing test `test_persona_injects_textmode_tonality_block` — CPAL prompt includes a "Textmode register" section when register == TEXTMODE.

- [ ] **Step 6:** Implement the injection in `persona.py` — small prompt block: `## Textmode register\nYou are speaking in textmode tonality. Keep replies clipped, IRC-style. Use / for actions (/me thinks, /me checks). Avoid prose runs; use short declarative lines.`

- [ ] **Step 7:** Run → PASS. Commit `feat(persona): textmode register tonality injection`.

- [ ] **Step 8:** Write failing test `test_homage_package_activation_writes_voice_register` — calling `set_active_package(bitchx)` writes `{"register": "textmode", "set_at": <ts>}` to the SHM file.

- [ ] **Step 9:** Implement activation hook in the homage registry.

- [ ] **Step 10:** Run → PASS. Commit `feat(homage): package activation writes voice register`.

- [ ] **Step 11:** Persona note: this PR touches the frozen `persona.py` file. DEVIATION is NOT sufficient — this is a deliberate parameter change tied to the new condition. The PR blocks on the research-condition-open PR (Phase 9) being ready to merge first; sequence in §Execution Order.

- [ ] **Step 12:** Ruff + pyright. Push, hold PR open until Phase 9 ready.

**Acceptance:** When the BitchX package is active, CPAL prompts include the textmode tonality block; TTS output is audibly more clipped/IRC-register. Wiring is reversible by package-deactivation + SHM file removal.

---

## Phase 8 — StructuralIntent `homage_rotation_mode`

**Branch:** `feat/homage-structural-hint`. **PR:** 8 of 12.

**Files:**
- Modify: `shared/structural_intent.py` — add `homage_rotation_mode: Literal["steady", "deliberate", "rapid", "burst"] | None = None`.
- Modify: `agents/studio_compositor/structural_director.py` — include the new field in the prompt and output schema.
- Modify: `agents/studio_compositor/homage/choreographer.py` — reads the structural file for the active rotation mode; adjusts rotation cadence + burst triggers accordingly.
- Create: `tests/studio_compositor/homage/test_structural_homage_mode.py`.

**Tasks (TDD):**

- [ ] **Step 1:** Write failing test `test_structural_intent_schema_homage_rotation_mode`.

- [ ] **Step 2:** Run → FAIL. Add field. Run → PASS. Commit `feat(structural): homage_rotation_mode field`.

- [ ] **Step 3:** Write failing test `test_structural_prompt_instructs_homage_rotation_mode_choice` — the structural director's prompt explains the 4 rotation modes.

- [ ] **Step 4:** Implement prompt extension. Run → PASS. Commit `feat(structural): homage rotation mode prompt section`.

- [ ] **Step 5:** Write failing test `test_choreographer_respects_rotation_mode` — `rapid` mode triggers rotation at ~30s; `deliberate` at ~180s.

- [ ] **Step 6:** Implement the rotation-cadence adapter in choreographer.

- [ ] **Step 7:** Run → PASS. Commit `feat(homage): choreographer honours structural rotation mode`.

- [ ] **Step 8:** Ruff + pyright. Push, PR, CI, merge.

**Acceptance:** The structural director emits `homage_rotation_mode` at its 90s cadence; the choreographer adjusts signature-artefact rotation rate accordingly. Rehearsal-measurable.

---

## Phase 9 — Research Condition Declaration

**Branch:** `chore/homage-condition-declaration`. **PR:** 9 of 12.

**Files:**
- Create: `~/hapax-state/research-registry/cond-phase-a-homage-active-001/condition.yaml` (via `scripts/research-registry.py open`).
- Create: `research/protocols/deviations/` entry if any concurrent DEVIATION needed (likely none — this is a new condition).
- Modify: `docs/superpowers/specs/2026-04-15-lrr-phase-1-research-registry-design.md` §6 risk table — append HOMAGE row.
- Modify: `docs/superpowers/specs/2026-04-17-volitional-grounded-director-design.md` §3.2 — note `PerceptualField.homage` addition.
- Modify: `shared/perceptual_field.py` — add `HomageField` + wire into `PerceptualField.homage`.
- Create: `tests/shared/test_perceptual_field_homage.py`.

**Tasks (TDD):**

- [ ] **Step 1:** Write failing test `test_homage_field_populated_from_package_and_choreographer`.

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3:** Add `HomageField` dataclass + reader that pulls from registry + SHM state.

- [ ] **Step 4:** Run → PASS. Commit `feat(perception): HomageField in PerceptualField`.

- [ ] **Step 5:** Run `scripts/research-registry.py open cond-phase-a-homage-active-001 --parent cond-phase-a-volitional-director-001` locally (operator or alpha with lock file present).

- [ ] **Step 6:** Commit the generated condition.yaml.

- [ ] **Step 7:** Amend the two existing specs (§6 risk table + §3.2 PerceptualField note).

- [ ] **Step 8:** Commit `docs(lrr): open cond-phase-a-homage-active-001 + spec amendments`.

- [ ] **Step 9:** Push, PR, CI, merge. **This PR must merge before Phase 7 (voice register) can merge** because Phase 7 touches frozen persona.py under the new condition's manifest.

**Acceptance:** New research condition open and active; PerceptualField includes homage state; the director can cite `homage.package`, `homage.active_transitions`, `homage.rotation_phase` in grounding_provenance.

---

## Phase 10 — Rehearsal + Audit (no PR, runbook)

**Files:** `scripts/rehearsal-capture.sh` unchanged. New audit template at `docs/superpowers/audits/2026-04-18-homage-rehearsal-audit.md`.

**Tasks:**

- [ ] **Step 1:** Flip `HAPAX_HOMAGE_ACTIVE=1` in `~/.envrc`. Rebuild services (`systemctl --user restart hapax-rebuild-services`; logos relaunch by operator).

- [ ] **Step 2:** Set stream mode to `private`. Run `scripts/rehearsal-capture.sh 30min homage-activation`.

- [ ] **Step 3:** Collect:
    - `grounding_provenance` signal distribution JSONL
    - director activity distribution
    - stimmung dimension time series
    - `hapax_homage_*` Prometheus counts
    - Operator-stress delta vs baseline condition

- [ ] **Step 4:** Fill in the audit template: activity distribution within 2σ of baseline (yes/no), stimmung dimensions unchanged (yes/no), no homage_violation increments (yes/no), visual contrast acceptable (yes/no), operator readability during production (yes/no — operator-reported).

- [ ] **Step 5:** If any check fails: flip `HAPAX_HOMAGE_ACTIVE=0`, investigate, fix in a scoped PR, re-rehearse.

- [ ] **Step 6:** If all checks pass: commit the audit with operator sign-off and move to Phase 11.

**Acceptance:** Audit checked in under the new condition; activation path approved.

---

## Phase 11 — Remaining Ward Migration (3 sub-PRs, batches 1–3)

**Branches:** `feat/homage-ward-migration-batch-1`, `-batch-2`, `-batch-3`. **PRs:** 10, 11, 12 (and 13).

### Batch 1 (6 wards — hothouse diagnostic)

- `impingement_cascade`, `recruitment_candidate_panel`, `thinking_indicator`, `pressure_gauge`, `activity_variety_log`, `whos_here`.

**Per ward:** same TDD pattern as Phase 4 (Step 1–4 × 4 tests × 6 wards).

### Batch 2 (6 wards — content)

- `token_pole`, `album_overlay`, `sierpinski_renderer`, `captions_source`, `stream_overlay`, `research_marker_overlay`.

**Note:** `token_pole` and `sierpinski_renderer` are geometric, not text — their transition vocabulary is scale + alpha + position, not scroll-in/scroll-out. The package's `TransitionVocab` supports these via the existing `animation_engine` properties (alpha, scale).

### Batch 3 (6 surfaces — overlay zones + Reverie external_rgba)

- Pango markdown zones (main, research, lyrics), Reverie external_rgba consumer wrapper.

**Acceptance:** All 22 wards render through `HomageTransitionalSource`. Paint-and-hold render paths removed. Golden frames pinned.

---

## Phase 12 — Consent-Safe Variant + Retirement

**Branch:** `feat/homage-consent-safe-and-retirement`. **PR:** 14 of 14 (final).

**Files:**
- Modify: `config/compositor-layouts/consent-safe.json` — explicitly unsets HOMAGE (no package active); renders with baseline legibility-only sources.
- Modify: `agents/studio_compositor/homage/__init__.py` — consent-safe layout triggers `get_active_package()` to return `None`; wards gracefully fall back.
- Create: `tests/studio_compositor/homage/test_consent_safe_disables_homage.py`.
- Delete: Any legacy paint-and-hold code paths verified unused by greps across all 22 wards.
- Modify: `~/.envrc` template — promote `HAPAX_HOMAGE_ACTIVE=1` to default for `research`/`rnd` working modes.

**Tasks (TDD):**

- [ ] **Step 1:** Write failing test `test_consent_safe_layout_disables_homage`.

- [ ] **Step 2:** Implement the gate in `get_active_package()` (reads layout; returns `None` under consent-safe).

- [ ] **Step 3:** Ward mixin falls back to legacy-legible rendering when package is `None`.

- [ ] **Step 4:** Run → PASS. Commit.

- [ ] **Step 5:** Grep for dead paint-and-hold paths; remove with accompanying test evidence.

- [ ] **Step 6:** Commit.

- [ ] **Step 7:** Promote env default to `HAPAX_HOMAGE_ACTIVE=1`.

- [ ] **Step 8:** Ruff + pyright. Push, PR, CI, merge.

**Acceptance:** HOMAGE is the default aesthetic under research/rnd working modes; consent-safe disables it cleanly; no dead code in the compositor tree.

---

## Execution Order

1. **Phase 1** (this PR) — spec + plan.
2. **Phase 2** — HomagePackage + BitchX data.
3. **Phase 3** — FSM + choreographer (feature-flagged off).
4. **Phase 4** — 4 legibility surfaces migrated (still flagged).
5. **Phase 9** — condition open + PerceptualField extension (unblocks Phase 7).
6. **Phase 5** — IntentFamilies + dispatchers + director prompt.
7. **Phase 6** — ward↔shader coupling.
8. **Phase 7** — voice register + CPAL wiring (depends on Phase 9).
9. **Phase 8** — StructuralIntent homage_rotation_mode.
10. **Phase 10** — rehearsal (runbook).
11. **Phase 11** batches 1–3 — remaining ward migration.
12. **Phase 12** — consent-safe + retirement + flag flip to default-on.

## Conventions

- **Branch names:** `feat/homage-<phase-slug>` or `chore/homage-<phase-slug>` as applicable.
- **Commit messages:** conventional; scope `homage`, `perception`, `director`, `observability`, `structural`, `persona`, `docs(lrr)`, `chore(lrr)` as appropriate.
- **Testing:** TDD. Every step that changes behaviour has a failing-test step before the implementation step.
- **DRY/YAGNI:** add fields only as used; tests pin behaviour, not every possible shape.
- **Frequent commits:** within a phase, commit at each logical milestone (scaffold, feature, test-pin, refactor). Do not accumulate a single mega-commit.
- **Reversibility:** every phase ships with the feature-flag path intact until Phase 12 flips the default.

## Self-Review Checklist

- [x] Every spec §3–§9 requirement maps to a phase task.
- [x] No "TBD" / "fill in later" placeholders.
- [x] Method/field names consistent between phases (HomagePackage, GrammarRules, HomageTransitionalSource, get_active_package, homage.*, HAPAX_HOMAGE_ACTIVE).
- [x] Dependencies between phases explicit (Phase 7 depends on Phase 9; Phase 4 depends on Phase 3).
- [x] Exit criteria per phase.
- [x] Test before implementation for every behaviour-changing step.
