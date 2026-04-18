# Vision Integration Design — CVS #150

**Date:** 2026-04-18
**Status:** spec stub
**Source research:** `tmp/cvs-research-150.md` (vision stack capability inventory + unused-signal audit)
**Adjacent tasks:** #135 (camera naming), #136 (follow-mode), #121 (HARDM), #158 (director no-op)

---

## 1. Goal

Close the gap between the dense vision stack and the livestream director.

Operator quote (2026-04-17):
> "We have a massive video/image classification and detection system that we are not at all using in the livestream."

The vision backend runs 11 classifiers across all studio cameras on a ~3s round-robin. The livestream director branches on exactly one visual signal: `visual.detected_action == "away"`. Everything else is produced, serialized into `perception-state.json`, and then discarded at the compositional boundary. This spec sequences the work to consume the remaining signals as three phased, operator-visible integrations.

---

## 2. Current State

### 2.1 Vision stack capability inventory

Per research §1, running in `agents/hapax_daimonion/backends/vision.py`:

- **YOLOv8x-worldv2** — open-vocab detection on room cameras (bboxes, labels, track_ids).
- **YOLO11m** — COCO person detection on operator camera.
- **YOLO11m-pose** — 17 COCO keypoints → posture.
- **SCRFD** (insightface) — faces, 5-pt landmarks, 512-d embeddings (reused for gaze + emotion + re-ID).
- **HSEmotion enet_b2_8** — 8-class emotion on SCRFD crops → `top_emotion`, valence, arousal.
- **MediaPipe FaceMesh** — `gaze_direction` (screen/left/right/up/down/unknown).
- **MediaPipe Hands** — `overhead_hand_zones`.
- **Places365 ResNet18** — coarse `scene_type`.
- **SigLIP-2 ViT-B-16-SigLIP2-256** — zero-shot custom-label scenes per camera.
- **ByteTrack** — per-camera stable track IDs.
- **CrossCameraStitcher** — re-ID across cameras via face embedding.
- **SceneInventory** — persistent cross-camera object store (24h static / 30m dynamic).

Writer `agents/hapax_daimonion/_perception_state_writer.py` serializes all of the above into the daimonion cache as `perception-state.json` at 1 Hz. `shared/perceptual_field.py` aggregates into `PerceptualField.visual`.

### 2.2 Single-signal consumption via `twitch_director.py`

Deterministic twitch director (4s cadence) reads `PerceptualField` and branches on:

- `field.ir.ir_hand_zone` (edge NIR, not RGB vision)
- `field.audio.midi.*`, `field.audio.contact_mic.*`
- `field.visual.detected_action` — **only the string "away"**
- `field.stream_health.*`, `field.album.*`, `field.chat.*`, `field.presence.*`

`director_loop.py` (narrative Claude director) serializes the full `VisualField` into its prompt but does not branch mechanically on it. `compositional_consumer.py` is dispatcher-only and vision-agnostic. `objective_hero_switcher.py` picks hero cameras from vault-objective activity, ignoring vision entirely. VLA consumes emotion/gaze/posture/hand-gesture for **stimmung** (operator state), never for livestream composition.

---

## 3. Sixteen Unused Signals

Produced, persisted, reachable from the director, currently branched on by nothing in the livestream path:

1. `visual.per_camera_scenes` (dict[role, label]) — SigLIP-2
2. `visual.scene_type` (global) — Places365 + SigLIP-2
3. `visual.top_emotion` — HSEmotion (VLA stimmung only)
4. `visual.hand_gesture` (RGB) — MediaPipe Hands (VLA stimmung only)
5. `visual.gaze_direction` (RGB) — FaceMesh (VLA stimmung only)
6. `visual.posture` (RGB) — YOLO11m-pose (VLA stimmung only)
7. `visual.overhead_hand_zones` (RGB) — MediaPipe Hands overhead
8. `visual.per_camera_person_count` — YOLO
9. `visual.ambient_brightness` — histogram
10. `visual.color_temperature` — per-frame mean
11. `visual.operator_confirmed` — SCRFD face-match
12. `emotion_valence` / `emotion_arousal` — HSEmotion
13. `scene_state_clip` — CLIP scene
14. `detected_objects` — YOLO-World, stringified
15. `frustration_score` — writer-synthesized
16. `gesture_intent` — writer-synthesized

Plus `SceneInventory` (entire cross-camera persistent store) — `by_label()`, `recent()`, `snapshot()` queries untapped by livestream code.

---

## 4. Phase 1 (P0) — Scene → Preset-Family Bias

**Feature flag:** `HAPAX_VISION_SCENE_BIAS` (default off in research, on in rnd after smoke).

New module `agents/studio_compositor/scene_family_router.py`:

- On each twitch tick, read `field.visual.per_camera_scenes[hero_role]`.
- Lookup operator-editable table `config/scene-family-map.yaml` (default shipped):
  ```yaml
  turntable: fx.family.audio-reactive
  mpc_station: fx.family.audio-reactive
  modular_rack: fx.family.generative-field
  desk_work: fx.family.text-mode
  room_wide: fx.family.ambient
  kitchen: fx.family.ambient
  empty_studio: fx.family.ambient
  ```
- Emit `preset.bias.<family>` with `salience=0.4` on scene change. Debounce 20s per family.

**Integration point:** `compositional_consumer.dispatch_preset_bias` already accepts `fx.family.<family>`. No new dispatcher plumbing. Scene change detection uses the existing `_emit_if_cool` machinery in twitch director.

**Dependency:** #135 must land first — `camera_role` strings must be stable for the scene-family map to be operator-editable without breakage.

---

## 5. Phase 2 (P0) — Object-Presence → Ward Triggers

**Feature flag:** `HAPAX_VISION_OBJECT_WARDS` (default off, on after Phase 1 smoke).

Zero new inference. Pure read-only queries against the already-populated `SceneInventory`. New rule block in `twitch_director.tick_once`:

- `inventory.by_label("book")` with `mobility=="static"`, recency < 60s → emit `ward.highlight.citation.foreground`.
- `inventory.by_label("guitar") | by_label("keyboard")` on overhead, `mobility=="dynamic"` → emit `ward.appearance.instrument.tint-warm` + `preset.bias.audio-reactive`.
- `inventory.recent(30)` contains a label absent from the prior 10 min → emit `ward.staging.novelty-cue.top` once, 8s TTL.

**Ward families used:** `ward.highlight.*`, `ward.appearance.*` (both exist in `compositional_consumer.py`).

**Object→ward mapping (extensible via same YAML pattern):**
- book → `ward.highlight.citation.foreground`
- guitar / keyboard → `ward.appearance.instrument.tint-warm`
- turntable / mpc → `preset.bias.audio-reactive` reinforcement
- novel label → `ward.staging.novelty-cue.top` (once, 8s)

---

## 6. Phase 3 (P0) — `per_camera_person_count` Hero Gate

**Feature flag:** `HAPAX_VISION_HERO_GATE` (default on; low-risk).

One-line fix in `agents/studio_compositor/objective_hero_switcher.dispatch_camera_hero`: skip any candidate camera whose `field.visual.per_camera_person_count[role] == 0` when alternatives exist.

Kills the "hero is empty room" failure mode flagged in the 2026-04-18 viewer-experience audit. No new signals needed; `per_camera_person_count` is already in `PerceptualField`.

Fallback: if *all* cameras are empty, preserve current behavior (operator briefly away is a valid hero state via `detected_action=="away"`).

---

## 7. Cross-References

| Task | Relationship | Sequencing |
|---|---|---|
| **#135 camera naming** | Hard dependency. Phase 1's `scene-family-map.yaml` keys on `camera_role`. | Land #135 first. |
| **#121 HARDM** | Phase 1–2 signals populate HARDM rows 0–6 (research §5G, 96 cells currently unused). | HARDM consumes what this spec publishes. |
| **#136 follow-mode** | Shares YOLO track-continuity layer. #136 owns *which person, where*; #150 owns *what scene, which family*. | Coordinate on ByteTrack surface; no blocker. |
| **#158 director no-op** | One documented cause of director punting: grounded signals are serialized but never branched on. Phase 1–3 give the deterministic director reasons to act. | Partial remediation. |

---

## 8. File-Level Plan

Phase 1:
- `agents/studio_compositor/scene_family_router.py` — **new**, ~180 LOC.
- `config/scene-family-map.yaml` — **new**, operator-editable, ships with defaults.
- `agents/studio_compositor/twitch_director.py` — add 1 rule block calling router; debounce state.
- `tests/agents/studio_compositor/test_scene_family_router.py` — **new**.

Phase 2:
- `agents/studio_compositor/twitch_director.py` — add SceneInventory rule block (~60 LOC).
- `agents/studio_compositor/object_ward_rules.py` — **new**, pure functions over `SceneInventory`.
- `config/object-ward-map.yaml` — **new**, label→ward mapping.
- `tests/agents/studio_compositor/test_object_ward_rules.py` — **new**.

Phase 3:
- `agents/studio_compositor/objective_hero_switcher.py` — 1-line gate + tests.
- `tests/agents/studio_compositor/test_objective_hero_switcher.py` — add empty-camera cases.

Shared:
- `shared/feature_flags.py` — three new flags if not already present.

---

## 9. Test Strategy

**Phase 1:**
- Unit: `scene_family_router` with synthetic `PerceptualField` fixtures, all 7 default scene keys, missing-key fallback, debounce boundary.
- Integration: twitch_director tick with scene change → assert `preset.bias.<family>` emitted once per debounce window.

**Phase 2:**
- Unit: `object_ward_rules` against hand-built `SceneInventory` snapshots (static book, dynamic guitar, novel label).
- Integration: twitch_director tick with populated inventory → assert ward emissions with correct TTL.

**Phase 3:**
- Unit: `dispatch_camera_hero` with `per_camera_person_count={a:0, b:2}` → assert `b` chosen.
- Edge: all-zero → preserves `detected_action=="away"` behavior.

All phases: smoke on livestream for one 30-min session before flipping flag from off → on in rnd mode.

---

## 10. Rollback + Feature Flags

| Phase | Flag | Default | Rollback |
|---|---|---|---|
| 1 | `HAPAX_VISION_SCENE_BIAS` | off | unset env, restart compositor; router no-ops, twitch rules skip |
| 2 | `HAPAX_VISION_OBJECT_WARDS` | off | unset env, restart; ward rule block skipped |
| 3 | `HAPAX_VISION_HERO_GATE` | on | unset env; hero switcher reverts to count-blind selection |

All flags read at twitch-tick boundary; no restart required for toggle-off during live session (flag re-checked every 4s).

---

## 11. Open Questions

1. **Debounce windows.** 20s per family (Phase 1), 8s novelty TTL (Phase 2) — operator-tunable or hard-coded? Default to YAML-tunable, hard-coded fallback.
2. **Scene confidence floor.** SigLIP-2 returns a confidence; below what threshold do we suppress family bias? Proposed 0.55 (matches existing SigLIP-2 gates in `vision.py`) — confirm against livestream data.
3. **Multi-hero arbitration.** If hero-switch mid-debounce changes `per_camera_scenes[hero_role]`, do we re-fire the family bias? Proposed: yes, treat hero change as a scene change event.
4. **Interaction with narrative director.** Does `director_loop.py` need a prompt hint that twitch is already acting on scene/object signals so the LLM doesn't double-dispatch? Defer to Phase 2 smoke.
5. **Phase 4+ deferred integrations.** Emotion → ward-appearance nudge (research §5E), scene-novelty → Reverie exploration pressure (§5D), gesture intent (§5C). All gated on Phases 1–3 stability and #121 HARDM landing.

---

**Written to:** `docs/superpowers/specs/2026-04-18-vision-integration-design.md`
