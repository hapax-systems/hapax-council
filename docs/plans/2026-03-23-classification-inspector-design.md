# Classification Inspector: Design Document

**Date:** 2026-03-23
**Scope:** Dedicated per-camera classification viewer, separate from terrain UI, theme-aware colors
**Authority:** Exempt from Logos design language signal density rules (§11 governed surfaces). This is an operator diagnostic tool, not a perception interface.

---

## 1. Concept

A dedicated overlay — toggled by `C` key — that shows every per-camera classification signal with individual toggles and theme-aware color assignments. Separate from the terrain's detection overlay (which uses mode-invariant hardcoded colors per §3.8). The inspector is an informational tool for the operator to see what the system classifies, at full density, with no flow gating or signal caps.

## 2. Layout

Split layout: left = live camera feed with colored detection boxes, right = classification channel controls.

Camera selector dropdown at top-right. Live MJPEG feed from `/api/studio/stream/camera/{role}`.

## 3. Classification Channels (12 toggleable)

| Channel | Color Token | Source |
|---------|-------------|--------|
| Detections | `green-400` | scene_inventory YOLO boxes |
| Gaze | `blue-400` | vision backend gaze_direction |
| Emotion | `yellow-400` | HSEmotion 8-class |
| Posture | `orange-400` | YOLO pose |
| Gesture | `fuchsia-400` | MediaPipe hands |
| Scene type | `emerald-400` | SigLIP 2 |
| Action | `red-400` | X3D-XS |
| Motion | `orange-600` | Frame differencing |
| Depth | `blue-600` | Depth-Anything-V2 |
| Trajectory | `green-600` | Temporal delta |
| Novelty | `yellow-600` | Seen count + age |
| Dwell | `fuchsia-600` | Dwell time |

All colors resolve via `useTheme().palette[token]` — switch with R&D/Research mode.

## 4. Files to Create

- `hapax-logos/src/components/terrain/overlays/ClassificationInspector.tsx`
- `hapax-logos/src/components/terrain/overlays/InspectorChannelPanel.tsx`

## 5. Files to Modify

- `hapax-logos/src/contexts/TerrainContext.tsx` — extend Overlay type
- `hapax-logos/src/components/terrain/TerrainLayout.tsx` — add C key handler + render
