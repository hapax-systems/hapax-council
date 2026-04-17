# Phase 6 — Consent-Gate on Live-Video Egress

**Spec:** §3.5 (authorship legibility) + §5 Phase 6
**Goal:** Close the axiom enforcement gap that Agent 2 flagged: the live video egress to /dev/video42 + RTMP + HLS does NOT currently block on guest-detected-without-contract. The recording valve and Qdrant writes do; the stream output doesn't. This phase closes that.

**Axiom:** `interpersonal_transparency` + `it-irreversible-broadcast` T0 (ratified 2026-04-15). Any non-operator face detected without active contract ⇒ compose-safe fallback applied to egress *in addition to* the existing persistence block.

## File manifest

- **Create:** `config/compositor-layouts/consent-safe.json` — fallback layout that shows no camera feeds except reverie + Cairo chrome + anonymized visuals.
- **Modify:** `agents/studio_compositor/consent.py` — add `should_egress_compose_safe()` predicate + `apply_compose_safe_layout()` method. Extends existing recording-valve behavior.
- **Modify:** `agents/studio_compositor/state.py::state_reader_loop` — on `consent_phase ∈ {guest_detected, consent_pending, consent_refused}`, call `apply_compose_safe_layout()` within 5 s.
- **Modify:** `agents/studio_compositor/compositor.py` — watches consent state, hot-swaps layouts without frame drops.
- **Modify:** `agents/studio_compositor/cairo_sources/captions_source.py` — when consent-safe mode active, overlay a "CONSENT PENDING — no guest broadcast" banner in captions strip.
- **Create:** `tests/studio_compositor/test_consent_live_egress_gate.py`

## Consent-safe layout specification

`consent-safe.json`:
- No camera feeds from `brio-operator`, `brio-room`, `brio-synths`, `c920-desk`, `c920-room`, `c920-overhead` in main slot or PiPs.
- `reverie` (wgpu substrate) remains — fully abstract, no identifying content.
- Cairo surfaces remain: activity_header, stance_indicator, captions, chat_legend, grounding_ticker.
- Sierpinski YouTube slots: **retained** — YouTube content is third-party, not guest. Still consent-safe.
- Album overlay: retained — album art is not a person.
- Token pole: retained.
- Captions strip adds banner: "◆ consent pending — guest broadcast withheld".
- Palette shifts to a visibly different chrome (e.g., warning-accent border) so the mode is legibly abnormal.

## Tasks

- [ ] **6.1** — Write `consent-safe.json` layout. Start from `default.json`, remove all camera-feed sources + assignments, add banner rendering to captions source.
- [ ] **6.2** — Add `should_egress_compose_safe()` predicate to `consent.py`:
  ```python
  def should_egress_compose_safe(overlay_data: OverlayData) -> bool:
      if overlay_data.consent_phase in {"guest_detected", "consent_pending", "consent_refused"}:
          return True
      return False
  ```
  Preserves axiom — even "consent_pending" (guest was detected, waiting for approval) is fail-closed to compose-safe.
- [ ] **6.3** — Implement `apply_compose_safe_layout(compositor)` method:
  - Signals compositor via `/dev/shm/hapax-compositor/layout-override.json` ("apply consent-safe").
  - Compositor's layout-mutator reads and hot-swaps (existing mechanism from source-registry epic).
- [ ] **6.4** — Modify `state_reader_loop`: on consent_phase change, call `apply_compose_safe_layout` or revert to normal. Log transitions.
- [ ] **6.5** — Write tests:
  - `test_guest_detected_triggers_compose_safe`: inject consent_phase=guest_detected; assert layout override written within 5 s.
  - `test_consent_granted_restores_normal_layout`: transition to consent_granted; assert normal layout restored.
  - `test_consent_refused_stays_compose_safe`: assert compose-safe holds indefinitely.
  - `test_captions_banner_on_compose_safe`: captions source renders the consent-pending banner.
  - `test_reverie_and_chrome_preserved`: no camera feeds in consent-safe layout but reverie + overlays remain.
  - `test_recording_valve_still_blocked`: existing recording-valve behavior untouched.
- [ ] **6.6** — Run ruff + pyright + tests.
- [ ] **6.7** — Commit: `feat(consent): live-video egress compose-safe fallback on guest detection`.
- [ ] **6.8** — Smoke test on live system:
  - Inject a synthetic multi-person detection via test helper (or temporarily drop a test JSON into perception-state).
  - Verify stream output switches to consent-safe within 5 s.
  - Verify captions banner appears.
  - Revert the injection; verify normal layout restores.
- [ ] **6.9** — Mark Phase 6 ✓.

## Acceptance criteria

- Multi-person detection without active contract ⇒ compose-safe layout applied in ≤5 s.
- Compose-safe layout contains no camera feeds; reverie + Cairo chrome + album overlay + Sierpinski YT + captions + banner all present.
- Captions banner reads "consent pending" prominently.
- Transition back to normal layout on consent_granted is immediate (&lt;2 s).
- Existing recording valve + Qdrant write gate unchanged.
- Axiom `it-irreversible-broadcast` fully enforced at egress, not just persistence.

## Test strategy

- Unit: state-reader-loop transition logic.
- Integration: layout swap observed in running compositor after simulated consent_phase change.
- **Axiom validation:** commit a runbook note describing the test procedure for operator to verify with a real second person in frame at a later date. (Not automated in this phase since it requires another human.)

## Rollback

`HAPAX_CONSENT_EGRESS_GATE=0` env disables the new gate; recording valve + Qdrant gate (existing) still fire. Not recommended — axiom violation.

## Risks

- **Hot-swap latency**: if layout mutation takes &gt;5 s, guest frame is broadcast. Mitigation: use existing source-registry epic's hot-swap (known &lt;500 ms), measured in `test_consent_live_egress_gate.py`.
- **False-positive detections**: a misclassified shadow could trigger compose-safe unnecessarily. Mitigation: the `consent_phase` transition is already hysteresis-gated in presence_engine / vision backend; we don't add additional hysteresis here.
