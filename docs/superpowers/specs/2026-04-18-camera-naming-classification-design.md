# Camera Naming + Classification Metadata — Design

**Date:** 2026-04-18
**Status:** spec stub (provisional approval)
**Source:** `docs/superpowers/research/2026-04-18-homage-follow-on-dossier.md` § Perception → "#135 Camera Naming"
**Blocks:** #136 follow-mode (operator-tracking)
**Feeds:** #150 image classification (scene-family routing), #121 HARDM (scene-label cells)

---

## 1. Goal

Give every physical camera an operator-actionable identity and a curated scene vocabulary so downstream consumers (twitch narrative director, hero-mode selector, follow-mode) can reason about *what this camera is seeing right now* instead of averaging six feeds into one scalar.

- Stable camera roles (schema-enforced) survive USB path churn and Pi re-flashing.
- Scene labels are operator-authored, not researcher-chosen ImageNet phrases.
- Per-camera scene state already flows through the pipeline (`per_camera_scenes` on `DaimonionVision`); it just never reaches the narrative or hero layers.

## 2. Naming Schema

Format: `{role}-{position}-{class}`

| role     | position   | class  | Example                 |
|----------|------------|--------|-------------------------|
| desk     | left/right | hw     | `desk-left-hw`          |
| overhead | ceiling    | room   | `overhead-ceiling-room` |
| pi       | shelf      | ir     | `pi-shelf-ir`           |
| room     | wide       | room   | `room-wide-room`        |

- **role** (required): `desk`, `overhead`, `pi`, `room`, `hero`. Matches existing compositor role slugs (`_resolve_camera_role`, `populate_camera_pips`).
- **position** (required): coarse spatial anchor — never resolution, never vendor.
- **class** (required): `hw` (hardware-contact, BRIO), `room` (wide-FOV, C920), `ir` (NoIR Pi edge).

6-camera inventory (3 BRIO + 3 C920 + 3 Pi NoIR per MEMORY `project_studio_cameras`) maps cleanly: BRIO → `*-hw`, C920 → `*-room`, Pi → `pi-*-ir`.

## 3. Scene Labels YAML

Replace `_SCENE_LABELS` list at `agents/hapax_daimonion/backends/vision.py:886–899` with operator-curated `config/camera_scene_labels.yaml`:

```yaml
# config/camera_scene_labels.yaml
defaults:
  - "operator typing at keyboard"
  - "hands on turntable"
  - "hands on MPC pads"
  - "hands on mixer"
  - "hands on modular synth"
  - "operator sleeping or resting"
  - "operator away"
  - "dark room with colored LED lighting"
  - "empty studio"

per_camera:
  desk-left-hw:    [typing, mouse, drawing-tablet]
  overhead-ceiling-room: [mpc-pads, turntable, mixer, modular]
  pi-shelf-ir:     [operator-present, operator-absent, low-light-only]
```

Per-camera overrides opt-in; `defaults` applies when no override exists. YAML watched via inotify; reload rebuilds SigLIP-2 text embeddings without service restart.

## 4. Per-Camera Scene Wiring

`per_camera_scenes` dict (populated at `vision.py:302,349`; exported at `vision.py:591,622,724,760`; surfaced at `_perception_state_writer.py:367`) already reaches `perception-state.json`. Remaining work:

- **Twitch narrative director** (`agents/studio_compositor/twitch_director.py`): extend prompt context to include `{role}: {scene}` pairs from `per_camera_scenes`, not just global `scene_type`.
- **Objective hero switcher** (`agents/studio_compositor/objective_hero_switcher.py`): add per-camera scene to scoring input so "hands on MPC pads on `overhead-ceiling-room`" outranks a stale `desk-left-hw`.
- **Environmental salience emphasis** (`environmental_salience_emphasis.py::EmphasisRecommendation.camera_role`): already per-role; pass through per-camera scene label in `reason`.

## 5. Blocks #136 Follow-Mode

Follow-mode (`follow_operator` stance) needs *per-camera* `operator_detected` + activity tag. This spec delivers the substrate:

- Stable role slugs (unchanged across USB re-enumeration).
- Per-camera scene label = activity tag input for tie-break (`hardware-contact > gaze-at-screen > room-presence`).

Without #135, follow-mode has no stable addressing and no activity signal.

## 6. Feeds #150 Image Classification

Scene-family routing keys directly on scene labels: `hands on *` → fine-grained hand pose branch, `operator sleeping *` → low-power classifier, `empty studio` → skip classification entirely. Labels become the dispatcher's discriminator.

## 7. Feeds #121 HARDM

HARDM cells can bind to scene labels as discrete signals: one cell per scene-family lit when any camera reports a matching label. Gives the dot-matrix a per-camera-aware activity register without new sensor wiring.

## 8. File-Level Plan

| File | Change |
|---|---|
| `config/camera_scene_labels.yaml` | **new** — operator-curated label set (defaults + per_camera) |
| `config/cameras.yaml` | **new** — canonical role→{position, class, USB hint} registry |
| `agents/hapax_daimonion/backends/vision.py` | Replace `_SCENE_LABELS` (lines 886–899) with YAML-loaded `_load_scene_labels()`; rebuild SigLIP-2 text embeddings on YAML mtime change; keep hardcoded list as fallback when YAML missing/invalid |
| `agents/hapax_daimonion/backends/vision.py` | Extend `_run_scene_classification` to accept `camera_role` and consult `per_camera[role]` first, `defaults` second |
| `agents/studio_compositor/twitch_director.py` | Inject `per_camera_scenes` dict into narrative prompt context |
| `agents/studio_compositor/objective_hero_switcher.py` | Consume `per_camera_scenes` in hero selection scoring |
| `shared/camera_registry.py` | **new** — Pydantic model + loader for `cameras.yaml`; single source of truth for role→metadata |
| `tests/test_camera_scene_labels.py` | **new** — YAML parse, fallback, per-camera override resolution, reload on mtime change |

## 9. Test Strategy

- **Unit:** `camera_scene_labels.yaml` parses; missing file falls back to hardcoded list; per-camera override beats default; malformed YAML logs + falls back.
- **Integration (mocked SigLIP-2):** per-camera scene propagates to `perception-state.json`; twitch director prompt includes per-camera pairs; hero switcher scoring receives per-camera scene input.
- **Regression pin:** existing 12-label hardcoded list remains the fallback set — test asserts exact equality when YAML absent.
- **No GPU required:** SigLIP-2 mocked at `open_clip.create_model_and_transforms` boundary.

## 10. Open Questions

1. Should the fallback hardcoded list stay in `vision.py` or move to `config/camera_scene_labels.yaml.default`? (Recommend: file, so operator always edits YAML; ships with a real default payload.)
2. Reload strategy: inotify vs. mtime check on each classification tick? (Recommend: mtime — classification already runs at <1 Hz per camera.)
3. Do Pi NoIR cameras run SigLIP-2 at all, or only the scene-label *slot* for the label without classification? (Recommend: skip SigLIP-2 on Pi, use IR-specific label list driven by IR perception output.)
4. `cameras.yaml` authoritative vs. inferred from USB udev rules? (Recommend: authoritative; udev rules reference the YAML, not vice versa.)

## 11. Rollback

- `config/camera_scene_labels.yaml` missing or malformed → `_load_scene_labels()` returns the existing 12-entry `_SCENE_LABELS` list verbatim; SigLIP-2 re-encodes; behavior is identical to pre-change state.
- `config/cameras.yaml` missing → fall back to current role resolution in `compositor.py::_resolve_camera_role`; no regression.
- Per-camera scene wiring into twitch/hero is additive; consumers default to global `scene_type` when `per_camera_scenes` is empty.

No migration required; no schema break in `perception-state.json` (per_camera_scenes field already present).
