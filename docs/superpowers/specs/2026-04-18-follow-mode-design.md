# Follow-Mode Design (#136)

**Status:** stub
**Date:** 2026-04-18
**Source:** `docs/superpowers/research/2026-04-18-homage-follow-on-dossier.md` § Perception → #136
**Depends on:** #135 (stable camera roles + operator-authored scene labels)
**Cross-cuts with:** #129 (facial obscuring, HARD req), #150 (image classification / YOLO tracks)

---

## 1. Goal

Creative hero-mode shot selection should *track the operator* across the 6-camera rig — follow hands-on-hardware, follow gaze-at-screen, follow room-presence when operator roams — while preserving the cinematic floor (no frenetic cuts, no camera starvation, minimum dwell). Follow-mode is a **gate on candidate cameras**, not a replacement for the existing hero-mode selector.

Non-goal: replacing stance-neutral hero-mode. Follow-mode is an opt-in constraint.

## 2. Stance-gated hero-mode

New stance: `follow_operator`.

When `follow_operator` is the active stance (set by director loop / operator intent / twitch narrative), hero-mode candidate selection is filtered:

- **Admissible cameras** = `{ cam ∈ all_cams : operator_detected(cam, now - 2s, now) == True }`
- If the admissible set is empty, fall back to stance-neutral hero-mode (log reason: `follow_operator no-candidates`).
- If only one camera is admissible and it is within its dwell floor, hold the current pick rather than cut; emit a `hero.follow.starved` metric.

Stance-neutral hero-mode selection is otherwise unchanged.

## 3. Activity-tag priority

Inside the admissible set, tie-break by activity tag (highest priority wins):

1. `hardware-contact` — MediaPipe Hands detects hands on MPC / mixer / turntable / keyboard (activity tag from #135 scene labels)
2. `gaze-at-screen` — MediaPipe Face Mesh gaze estimate == `screen` for ≥ 1 s
3. `room-presence` — operator ReID match but no hardware contact or screen gaze

Ties within a class: highest SCRFD detection confidence wins. Further ties: most recent activity timestamp.

## 4. Preserved invariants

All existing cinematic-floor constraints in `agents/studio_compositor/compositional_consumer.py` are preserved:

- `_CAMERA_VARIETY_WINDOW = 3` — proposed role must not be in the last 3 applied roles.
- `_CAMERA_MIN_DWELL_S = 12.0` — same role cannot re-apply within 12 s.
- `_CAMERA_ROLE_HISTORY` — 600 s window, capped at 20 entries.

Follow-mode filtering runs **before** dwell / variety gates. If variety or dwell blocks the only admissible camera, the pick is *skipped* (not forced); compositor holds previous hero.

## 5. Per-camera operator-detected signal

New field on per-camera perception state: `operator_detected: bool` with timestamp.

Computation (each camera frame):

1. `face_detector.py` (SCRFD, `agents/hapax_daimonion/face_detector.py`) yields faces + 512-d embeddings.
2. For each face, compute cosine similarity vs enrolled operator embedding (`face_detector.is_operator`).
3. `operator_detected = any(similarity > 0.7)` (threshold matches existing `is_operator` convention).
4. Sticky for 2 s: `operator_detected_recent(cam) = last_detected_ts[cam] ≥ now - 2.0`.
5. Absent face detection (e.g. back turned, Pi NoIR), fall back to MediaPipe Hands presence + YOLO `person` track on that camera as a *soft* signal (contributes to `room-presence` tag only, not hardware-contact).

Signal is published on the existing perception stream so director loop and hero selector consume it without new transport.

## 6. Depends on #135

Follow-mode requires:

- Stable per-camera `role` IDs (`desk-left-hw`, `overhead-ceiling-room`, `pi-shelf-ir`, ...).
- Per-camera activity tags derived from operator-authored `camera_scene_labels.yaml`.
- Activity-tag priority ordering depends on the label vocabulary being real and consistent.

#135 must ship first; follow-mode is a thin consumer of those signals.

## 7. Cross-cut with #129 — facial obscuring

**Order of operations is load-bearing:**

1. Follow-mode selects the hero camera.
2. Face-obscure policy (#129) then applies to the chosen camera's rendered output.

If `#129 policy == ALWAYS_OBSCURE`, the operator's face is still blurred on the hero camera — follow-mode does not exempt the operator from privacy floor. Follow-mode only changes *which camera* is hero; it never changes what gets rendered.

A misimplementation where follow-mode bypasses the obscure filter is a privacy violation. Test explicitly for this.

## 8. Synergy with #150 — image classification

- #150 (YOLO-based scene routing) and follow-mode share the same YOLO11n + SCRFD tracks.
- **Split concerns:** #150 answers "what is happening in the scene" → routes to *narrative* subsystems. Follow-mode answers "where is the operator" → routes to *hero selection*.
- Both read from the same perception stream; neither should double-count tracks or re-run detection.

## 9. Logos sidebar UX — operator question

Proposed: Logos sidebar pane showing `currently following: desk-left-hw (hands on MPC)` whenever `follow_operator` stance is active.

**Open operator question:** Is this useful (confidence/transparency) or distracting (visual noise on a working surface)? If approved, implementation is trivial — new WS topic `hero.follow.status` consumed by a Logos sidebar card.

Default: off; operator toggles via command registry if wanted.

## 10. File-level plan

- `agents/studio_compositor/compositional_consumer.py` — add `follow_operator` stance gate in `apply_hero_camera` (or equivalent) before dwell / variety checks; read `operator_detected_recent` per-cam from perception state.
- `agents/hapax_daimonion/face_detector.py` — no changes; `is_operator` already returns the needed boolean.
- `agents/hapax_daimonion/backends/vision.py` — publish per-camera `operator_detected_ts` alongside existing gaze / hand / scene fields.
- `agents/studio_perception/` (when created for #135) — extend per-camera activity-tag emission with `hardware-contact` / `gaze-at-screen` / `room-presence`.
- `agents/studio_compositor/director_loop.py` — add stance transition logic: enter `follow_operator` on operator intent or narrative cue; exit on timeout / explicit stance change.
- `shared/stances.py` (or existing registry) — register `follow_operator` stance.
- `logos/` sidebar card (optional, gated on operator answer to §9).

## 11. Test strategy

Unit:

- `test_follow_mode_gate.py` — admissible set filtering; empty-set fallback; one-admissible-within-dwell hold behavior.
- `test_activity_tag_priority.py` — tie-break ordering hardware-contact > gaze-at-screen > room-presence, confidence tiebreaker, timestamp tiebreaker.
- `test_operator_detected_sticky.py` — 2 s sticky window; dropout mid-window; post-window clearing.
- `test_variety_window_preserved.py` — variety window blocks repeat follow picks.
- `test_dwell_floor_preserved.py` — 12 s floor still enforced under follow_operator.

Integration:

- `test_follow_mode_obscure_order.py` — #129 obscure policy still applied to hero output when follow_operator is active and operator face is visible.
- `test_follow_mode_starvation.py` — with no operator-detected cams, fallback to stance-neutral hero selection without stall.
- `test_follow_mode_with_135_labels.py` — scene labels from #135 drive correct activity tags.

Property / soak:

- 10-minute livestream replay: verify no cut violates dwell floor; verify variety window never regresses; verify hero never locks to a single camera for > 60 s under operator movement.

## 12. Open questions

1. Threshold for operator ReID (0.7) — reuse existing `is_operator` constant or make follow-mode-specific (tighter) to avoid false positives under IR cameras?
2. Stance entry trigger — director loop heuristic, explicit operator command, or both? (Lean: both, operator command wins.)
3. Fallback priority when no operator-detected camera exists — revert to stance-neutral, or emit a distinct `operator_absent` stance that the director loop can use for interlude shots (album art / reverie)?
4. Logos sidebar pane — default off, operator opt-in? (Pending §9 answer.)
5. Pi NoIR cameras often lack face detection; should soft signals (YOLO person + gesture) contribute to `room-presence` tag weight, or only count when SCRFD confirms? (Lean: SCRFD hard-requires for hardware-contact / gaze; person-track sufficient for room-presence.)
6. Metrics — expose `hero.follow.candidates`, `hero.follow.starved`, `hero.follow.activity_tag`, `hero.follow.stance_dwell` to Prometheus for livestream perf observability.
