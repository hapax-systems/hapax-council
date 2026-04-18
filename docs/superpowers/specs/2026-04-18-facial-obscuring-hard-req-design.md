# Facial Obscuring — HARD Privacy Requirement (Design)

**Status:** 🟣 SPEC (provisionally approved 2026-04-18)
**Last updated:** 2026-04-18
**Source:** [`docs/superpowers/research/2026-04-18-homage-follow-on-dossier.md`](../research/2026-04-18-homage-follow-on-dossier.md) §2 — Task #129
**Index:** [active-work-index](../plans/2026-04-18-active-work-index.md)
**Priority:** HIGHEST (live privacy leak today)

---

## 1. Goal

Enforce pixel-level facial obscuring on every camera egress path — non-operator faces obscured per axiom `it-irreversible-broadcast` T0; operator face obscured per operator's extension of the constraint to self-identifiability (2026-04-18).

This is **additive** to the consent-safe layout-swap mechanism, not a replacement. Swap is the governance-visible coarse action (ward-level recede); obscure is the pixel-level floor that holds during transitions and on non-swap egress paths.

---

## 2. Current Leak (2026-04-18)

The `content_injector` pipeline reads raw camera JPEGs, routes them to Reverie as texture inputs, and Reverie re-enters the compositor at the `pip-ur` slot. **No face-obscure stage exists on this path today.** This is the primary live leak.

Secondary leaks:
- Per-camera JPEG snapshots in `/dev/shm/hapax-compositor/cam-*.jpg` consumed by director multimodal LLM calls (sent to Claude vision).
- OBS V4L2 loopback: local preview egress can bypass compositor post-shader.
- HLS + RTMP tees.
- Recording branches (archival egress).

---

## 3. Architecture

### 3.1 Apply point: per-camera at capture

Obscuring runs on each per-camera source *before* the JPEG hits `/dev/shm`. This is the safety floor: all downstream tees inherit the protection.

**Why not post-shader compositor?**
Post-shader obscuring would leak through the snapshot path (director LLM calls pull raw `/dev/shm/*.jpg` frames, not composited frames) and through OBS V4L2 loopback.

### 3.2 Detection: SCRFD + Kalman carry-forward

- Primary detector: existing SCRFD face detector (`face_detector.py`, 512-d embeddings).
- Detection cadence: **5 Hz** (every 6 frames at 30 fps).
- Between detections: Kalman bbox carry-forward keeps the obscure rect anchored on the face.
- Fallback detector: YOLO11n person bbox (head region = top 25% of person rect) if SCRFD drops frames >200 ms.
- Failure floor: if both detectors fail for >500 ms, **fail-closed** — full-frame obscure for broadcast tees, last-known bbox for local preview.

### 3.3 Obscuring technique

- **Primary layer:** solid Gruvbox-dark rect (package-sourced color from `HomagePackage`).
- **Veneer:** large-block pixelation (16 px blocks) or Bayer-4 halftone stipple (BitchX-authentic).
- **Margin:** 20% bbox expansion to account for detection jitter.
- **No blur.** Gaussian blur is reversible under known-PSF attack; solid mask + pixelation is not.

### 3.4 Is-operator discrimination

- New signal: `is_operator: bool` per detected face, sourced from existing 512-d ReID embedding match (operator embedding is `/dev/shm/hapax-perception/operator-embedding.npy`).
- When `operator_face_obscure_policy == ALWAYS_OBSCURE` (operator's 2026-04-18 directive): ignore `is_operator`, obscure everyone.
- When policy == `OBSCURE_NON_OPERATOR`: obscure only `is_operator == False` faces.
- Policy default: `ALWAYS_OBSCURE` pending operator answer to open question 1.

---

## 4. Interaction with Existing Consent Gate

The consent-safe layout-swap already exists (triggered by guest-detected-no-contract). It moves the compositor to a compose-safe layout (no camera feeds visible).

**Relationship:**
- Face-obscure runs ALWAYS, regardless of consent gate state.
- During consent gate activation (swap in progress): face-obscure provides the pixel-level floor on frames still in flight.
- After consent swap complete: camera feeds recede entirely; obscure is redundant but harmless overhead.
- **Before** consent swap can fire (guest just detected, swap transitioning): obscure is the only thing protecting identifiable pixels. Load-bearing.

---

## 5. Performance Budget

- SCRFD at 5 Hz across 6 cameras: ~30 detections/sec total.
- SCRFD inference cost: ~6 ms per 720p frame on current GPU (TabbyAPI shares the lane; budget allocated from the 10–15% perception slack).
- Kalman carry-forward: <0.5 ms per frame, CPU.
- Obscure blit (solid rect + pixelation): <1 ms per frame per camera on GPU.
- **Aggregate ceiling: 12% of one GPU lane.** Fits within existing perception envelope.

---

## 6. File-Level Plan

### New files

- `agents/studio_compositor/face_obscure.py` — FaceObscurer class with `obscure(frame, bboxes)` method.
- `agents/studio_compositor/face_obscure_process.py` — per-camera capture-side subprocess; reads raw camera frames, writes obscured frames to `/dev/shm/hapax-compositor/cam-*.jpg`.
- `shared/face_obscure_policy.py` — `FaceObscurePolicy` enum (`ALWAYS_OBSCURE`, `OBSCURE_NON_OPERATOR`, `DISABLED`).
- `tests/studio_compositor/test_face_obscure.py` — golden-path + dropout + fail-closed tests.

### Modified files

- `agents/studio_compositor/camera_capture.py` — insert obscure pipeline stage between capture and JPEG write.
- `agents/studio_compositor/config.py` — add `face_obscure_policy` field.
- `shared/director_observability.py` — add Prometheus metrics: `hapax_face_obscure_detections_total{camera, source}`, `hapax_face_obscure_fail_closed_total{camera, reason}`, `hapax_face_obscure_latency_seconds{camera}` (histogram).
- `agents/studio_compositor/content_injector.py` — audit that it reads from the obscured `/dev/shm` path (expected: yes, since path is unchanged).

---

## 7. Observability

Three new Prometheus metrics:
- `hapax_face_obscure_detections_total{camera, source}` — per-camera detection counter.
- `hapax_face_obscure_fail_closed_total{camera, reason}` — fail-closed event counter.
- `hapax_face_obscure_latency_seconds{camera}` — detection-to-mask latency histogram.

Grafana dashboard additions:
- Panel: fail-closed rate per camera (alert threshold: >0.5 events / minute).
- Panel: detection-to-mask latency p99 (alert threshold: p99 > 50 ms sustained).

---

## 8. Open Operator Questions

**Q1. Operator's own face: obscure on every egress including local OBS V4L2 loopback?**
Default recommendation: **YES** (matches operator's 2026-04-18 directive). Cost: operator cannot visually verify their own framing in OBS preview without inspecting `/dev/shm/operator-unobscured.jpg` (which never leaves local disk). Alternative: leave local OBS V4L2 preview unobscured but obscure everything else. Need operator call.

**Q2. SCRFD dropout fallback: fail-closed full-frame vs last-known bbox?**
Default recommendation: **fail-closed for broadcast tees, last-known bbox for local preview.** Loud failure on broadcast (viewer sees full obscure rect) is safer than silent failure.

**Q3. Apply to archival recordings as well, or only live broadcast?**
Default recommendation: **YES, archival too.** Archival footage tends to outlive consent. If recordings are operator-only and never redistribute, operator can flag `recording_obscure_policy = DISABLED` as an override.

---

## 9. Test Strategy

1. **Unit:** `face_obscure.py` — obscure rect geometry under SCRFD, under YOLO fallback, under dropout.
2. **Integration:** capture-side process reads a test JPEG with a synthetic face, writes obscured JPEG, asserts bbox region is ≤ 2% original face-pixel information (perceptual-hash distance).
3. **Fail-closed:** inject SCRFD failure, verify full-frame rect within 500 ms.
4. **Negative:** verify obscured frame can NOT be de-obscured to recover original face (adversarial test: train a small CNN on (obscured, original) pairs, measure reconstruction quality; threshold: SSIM < 0.3).
5. **End-to-end:** trace a face through `content_injector` → Reverie → compositor → RTMP tap; assert obscured at every tee.

---

## 10. Implementation Order

1. Write `shared/face_obscure_policy.py` enum + unit tests.
2. Write `agents/studio_compositor/face_obscure.py` + unit tests for obscure geometry.
3. Write `face_obscure_process.py` + integration test.
4. Modify `camera_capture.py` to insert obscure stage. Run end-to-end test.
5. Add Prometheus metrics + Grafana panels.
6. Adversarial reconstruction test.
7. Ship behind feature flag `HAPAX_FACE_OBSCURE_ACTIVE`, default ON, staged rollout:
   - 2026-04-19: flag ON, policy `ALWAYS_OBSCURE`, all 6 cameras.
   - 2026-04-20: operator answers Q1/Q2/Q3, policy tuned.
   - 2026-04-22: remove flag, make unconditional.

---

## 11. Rollback Plan

Feature flag `HAPAX_FACE_OBSCURE_ACTIVE` off → capture-side process passes through frames untouched. No compositor-side change required. Verified by integration test that asserts flag-off round-trip is byte-identical to pre-feature behavior.

---

## 12. Risks

- **Detection false-negative in low-light:** SCRFD's accuracy drops in Pi NoIR IR-only conditions. Mitigation: YOLO11n fallback + fail-closed.
- **Performance regression under 6-camera peak load:** all cameras emitting motion at once could saturate. Mitigation: cadence-adaptive (drop to 3 Hz under CPU pressure, carry forward at last-known).
- **Operator self-preview degraded:** obscured local preview hurts framing feedback. Mitigation: Q1 answer.

---

## 13. Related

- **Dossier §2 #129** (source)
- **Axiom:** `axioms/implications/it-irreversible-broadcast.yaml` (T0 constraint)
- **Consent gate:** `agents/studio_compositor/consent_gate.py` (interacts, doesn't overlap)
- **Perception:** `agents/studio_perception/face_detector.py` (SCRFD reused)
