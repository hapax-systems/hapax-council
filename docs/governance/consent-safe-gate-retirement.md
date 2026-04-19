# Consent-Safe Compose Gate — Retirement Note

**Status:** Normative. The consent-safe layout-swap gate is retired as
of 2026-04-18. The face-obscure pipeline (#129) is now the canonical
privacy floor for all visual egress paths.
**Scope:** Visual privacy at livestream egress (RTMP, HLS, V4L2 loopback).
**Companion modules:** `agents/studio_compositor/consent_live_egress.py`,
`agents/studio_compositor/cameras.py` (face-obscure integration),
`agents/studio_compositor/face_obscure_integration.py`,
`shared/consent.py`, `axioms/contracts/`.

---

## 1. What is being retired

The "consent-safe compose" path in
`agents/studio_compositor/consent_live_egress.py` — specifically the
`should_egress_compose_safe()` predicate wired through
`agents/studio_compositor/state.py` into the compositor's
`PipelineManager.set_compose_safe()` — formerly enforced a
layout-level swap whenever the predicate fired: every camera
interpipesrc was swapped to a fallback producer and ward PiPs were
hidden, so nothing but the "consent-safe" layout reached egress.

**What the gate actually did:**

- Watched `OverlayData` for consent-phase ambiguity (guest_detected,
  consent_pending, consent_refused, unknown future phases).
- On ambiguity, flipped every camera sub-pipeline to its black/fallback
  producer, wrote `/dev/shm/hapax-compositor/consent-safe-active.json`,
  and toggled the `consent-safe.json` layout.
- Fail-CLOSED on any unexpected condition — None overlay, stale state,
  missing fields, unrecognized phase strings.

**Why it's being retired:**

The face-obscure pipeline (#129) is strictly stronger. It operates at
capture time — every camera frame is pixelated to a Gruvbox-dark
veneer (hard pixelation when `cv2`/`mediapipe` face detectors are
healthy) or full-frame filled (fail-closed when detectors are
unavailable) BEFORE any tee to the egress paths. That means no
un-obscured camera pixel reaches RTMP, HLS, or `/dev/video42` under
any circumstance — including the exact ambiguity classes the layout
swap was designed to cover (unknown guest present, consent refused,
stale state).

The layout swap was, by comparison, coarse. It hid every camera and
every ward PiP the instant ambiguity was detected, regardless of
whether the face-obscure pipeline had already rendered the frame
privacy-safe. Livestream aesthetics degraded to a single consent-safe
fill even though the pixels themselves carried no identifying content.
That is redundancy in the privacy direction but regression in the
expressive direction.

---

## 2. The invariant preserved

**No un-obscured camera pixel reaches egress.** This was the point of
the consent-safe gate and remains the point of this system. What
changed is the layer at which the invariant is enforced:

- **Before (retired path):** compositor layout swap hides cameras and
  ward PiPs when `should_egress_compose_safe()` fires.
- **After (authoritative path):**
  `agents/studio_compositor/cameras.py::add_camera_snapshot_branch`
  routes every incoming camera frame through
  `agents/studio_compositor/face_obscure_integration.py::obscure_frame_for_camera`.
  On exception, the entire frame is pixelated/filled (fail-CLOSED). The
  obscured frame is what gets composited, what gets teed to RTMP, HLS,
  and V4L2. No upstream branch sees the un-obscured frame except the
  obscurer itself.

The face-obscure path covers the full ambiguity surface that the
layout swap covered:

| Ambiguity class | Layout-swap response (retired) | Face-obscure response (authoritative) |
|---|---|---|
| Unknown guest visible | Hide all cameras | Pixelate every face; if detector fails, fill entire frame |
| Consent refused | Hide all cameras | Same — face-obscure is always on |
| Consent pending | Hide all cameras | Same |
| Stale overlay state | Hide all cameras | Obscure still runs — capture-layer, not overlay-dependent |
| Unknown future phase | Hide all cameras | Same — obscure is phase-independent |
| None overlay data | Hide all cameras | Same — obscure does not consult overlay |
| Detector crash | (not covered — layout-layer only) | **Fail-closed fill** — full-frame pixelation |

In every row, the face-obscure path is equal-or-stronger than the
layout swap for visual privacy and stricter on the detector-crash
edge case the layout swap never addressed.

---

## 3. What is NOT retired

Consent contracts remain authoritative for every **non-visual** domain:

- **Audio recording / streaming.** RTMP audio, HLS audio, and local
  capture are gated by the `ConsentContract` recording-valve path in
  `shared/consent.py` (`contract_check()`), not by the layout swap.
- **Transcription persistence.** STT transcripts, daimonion utterance
  logs, and post-hoc transcript-indexed Qdrant entries all check
  `persistence_allowed` and the relevant consent contract before
  writing.
- **Interaction recording.** Per-person interaction memory (Qdrant
  `operator-episodes` payloads, RAG indexing of conversations involving
  non-operators) continues to enforce `interpersonal_transparency`
  through the usual contract path.
- **Ward content derived from non-operator identity.** Any ward, PiP,
  or overlay source whose content depends on an identified non-operator
  (e.g., personalized captions, relationship inference) remains gated
  behind active consent contracts.

The Agatha, Simon, Jason, and other consent contracts under
`axioms/contracts/` continue to govern these domains unchanged.

---

## 4. Axiom compliance

**`it-irreversible-broadcast` (T0, ratified 2026-04-15).** Any
identifiable non-operator broadcast without active contract is a T0
violation. This axiom is honored at the face-obscure layer: no
identifiable face reaches any egress tee. The face-obscure pipeline's
fail-closed fallback (full-frame pixelation on exception) preserves
this property even when the detector stack is unhealthy.

**`interpersonal_transparency` (weight 88).** No persistent state
about non-operator persons without active consent contract. The audio
+ transcription + interaction-recording gates continue to enforce
this axiom; the layout swap never did. Retirement is no-op for this
axiom.

**`single_user` (weight 100).** Unaffected. No multi-user code path
is introduced or retired by this change.

**`executive_function` (weight 95).** Improved. The layout swap
produced a visually jarring blackout whenever overlay state was stale
— a common condition when the consent state publisher lagged behind
the compositor tick. Eliminating the false-positive blackouts
reduces operator surprise.

**`management_governance` (weight 85).** Unaffected.

---

## 5. Re-enable path

The legacy fail-closed layout-swap behavior is preserved behind an
explicit opt-in:

```sh
export HAPAX_CONSENT_EGRESS_GATE=1   # or: true, on, enabled
# then restart studio-compositor.service
```

When enabled, `should_egress_compose_safe()` reverts to its
pre-retirement semantics (fail-closed on None overlay, stale state,
unsafe or unknown phases, guest without persistence). The module-load
banner logs a warning noting the gate is active and that it is now
redundant with face-obscure.

The re-enable path exists for three scenarios:

1. **Face-obscure regression.** If #129 is reverted or a detector bug
   is discovered that lets un-obscured frames through, setting the
   env var restores the defense-in-depth layout swap while the
   primary pipeline is fixed.
2. **Operator preference.** If the operator specifically wants the
   layout-swap aesthetic (full blackout on ambiguity rather than
   obscured-but-visible framing), the flag allows it.
3. **Audit rehearsal.** Compliance rehearsals may want both layers
   active simultaneously to verify the combined behavior.

The env var is checked once at module load; runtime toggling requires
a service restart.

---

## 6. Observability

The compositor still writes
`/dev/shm/hapax-compositor/consent-safe-active.json` when the gate
fires (only possible with the gate enabled). Under default (disabled)
operation, this marker becomes static — never written by the
retirement path. Any stale marker left on disk from a previous
gate-enabled run is harmless; `state.py` only writes on transitions,
so a disabled gate produces no writes.

The face-obscure pipeline has its own observability surface under
`agents/studio_compositor/face_obscure_integration.py` (detector
health, frame-fail counter, obscure-latency histogram). That surface
is the authoritative source for "is visual privacy healthy?" in the
post-retirement world.

---

## 7. Cross-references

- **#129 face-obscure spec** — the authoritative privacy floor.
- **`agents/studio_compositor/cameras.py`** — `add_camera_snapshot_branch`,
  integration point where every camera frame is routed through the
  obscurer.
- **`agents/studio_compositor/face_obscure_integration.py`** —
  `obscure_frame_for_camera`, the fail-closed obscurer.
- **`agents/studio_compositor/consent_live_egress.py`** — retired
  module; retained as a compatibility shim + re-enable path.
- **`agents/studio_compositor/state.py`** — consumer of the predicate;
  now receives `False` on every tick by default, making the downstream
  `PipelineManager.set_compose_safe()` and LayoutStore toggles no-ops.
- **`shared/consent.py`** — `ConsentContract`, `ConsentRegistry`,
  `contract_check()` — unchanged, continues to gate audio +
  transcription + interaction domains.
- **`axioms/contracts/`** — per-person consent contracts; unchanged.
- **`axioms/implications/it-irreversible-broadcast.yaml`** — the axiom
  this retirement realigns.
- **`tests/studio_compositor/test_consent_live_egress.py`** — tests
  now cover both the default-disabled path and the legacy
  gate-enabled path.
- **`scripts/verify-epic-2-hothouse.sh`** — updated verification
  assertions reflecting the new default.

---

## 8. Migration checklist

- [x] Flip default in `consent_live_egress.py` (`_is_gate_disabled` →
      `_is_gate_enabled`, invert semantics).
- [x] Module-load banner rewritten to reflect retirement.
- [x] `should_egress_compose_safe()` returns False unconditionally when
      the gate is disabled (new default).
- [x] Tests updated: `TestDefaultDisabled` covers the new default,
      `TestLegacyGateEnabled*` covers the re-enable path.
- [x] `scripts/verify-epic-2-hothouse.sh` assertions updated.
- [x] Governance doc authored (this file).
- [x] CLAUDE.md annotated with the scope change — consent gate
      governs non-visual capabilities only; visual privacy is
      enforced at face-obscure.
- [x] `/dev/shm/hapax-compositor/consent-safe-active.json` left alone
      — live service will update it on state change; stale marker is
      an observability artifact, not a correctness problem.

---

## 9. Rollback

If the retirement itself is judged wrong (separate from the per-deploy
re-enable via env var above), revert the commit that flipped
`_is_gate_disabled` → `_is_gate_enabled` and the test file. The
face-obscure pipeline and consent-contract paths are independent and
remain in place regardless.
