# CBIP dual-IR + displacement compositing — design spec

**Status:** draft
**Authored:** 2026-05-06 (alpha lane, operator directive 02:05Z + 02:08Z)
**Phase:** infrastructure scaffolding (not segment authorship)

## Context

CBIP (Chess Board Interpretive Platter) physically relocated. Operator added a second onboard IR camera to the Raspberry Pi watching it. CBIP is a general interpretative-platter surface where any objects can be accepted for content-programming consumption.

**Current scene state (2026-05-06):** 6 lenormand cards on the chess board.

**First segment idea (NOT in this spec):** lenormand reading session. Codex content-prep owns segment authorship; alpha owns infrastructure to enable any segment that uses the platter.

**Operator emphasis:** "make sure all the pieces are there" — ensure infrastructure is ready, not plan the segment.

## Operator-binding invariants

1. **Static frame.** Chess board position will never move. Optimize ROI as fixed crop, not per-frame detection.
2. **Locked lighting.** External light is orange-yellow tone/hue, won't change (or only slightly). White balance + exposure locked, not auto.
3. **Per-camera independence.** Both cameras configured separately — different ROI corners, different WB/exposure.
4. **Compositing intent (2026-05-06T02:08Z clarification):** the 2 cams composite together for displacement effects (parallax / stereo disparity / dual-channel chromatic warp). NOT redundancy. Both streams must reach council separately and be near-time-synchronized.
5. **Generalization.** Detector accepts any object on the platter (one large object, six lenormand cards, future N objects). Stable per-position IDs (not per-content) so downstream consumers can map identity → slot.

## Component graph

```
+-------------------+        +---------------------------+
|  Pi (cam0/cam1)   | -----> | hapax_ir_edge daemon     |
|  ROI-locked,      |        | dual capture, time-tagged |
|  WB/exposure-     |        | POST /pi/{role}/ir-platter |
|  locked           |        +---------------------------+
+-------------------+                     |
                                          v
                          +---------------------------+
                          | logos-api (council)        |
                          | /api/pi/{role}/ir-platter  |
                          | persists per-cam frames    |
                          +---------------------------+
                                          |
                  +-----------------------+----------------------+
                  v                                              v
+-----------------------------+              +---------------------------------+
| CBIP perception (council)   |              | Dual-IR displacement compositor |
| multi-object detector       |              | source — consumes both streams,  |
| stable per-position IDs     |              | produces displaced visual output |
+-----------------------------+              +---------------------------------+
                  |                                              |
                  v                                              v
        downstream content-prep                          studio compositor cairo /
        consumers (segment-time)                          reverie wgpu node
```

## Pieces (5 cc-tasks)

| Task | Priority | WSJF | Depends |
|---|---|---|---|
| cbip-dual-ir-pi-daemon-multi-camera | p1 | 6.5 | none |
| cbip-dual-ir-displacement-compositor-source | p1 | 7.0 | pi-daemon |
| cbip-vinyl-to-interpretative-platter-rename-generalize | p2 | 5.5 | none |
| cbip-static-frame-roi-lighting-calibration | p2 | 5.0 | none |
| cbip-multi-object-platter-detector | p2 | 5.5 | rename + roi-lighting |

## Hardware verification needed

- Which Pi watches the CBIP? (likely Pi-6 = ir-overhead per `agents/health_monitor/constants.py::PI_FLEET`)
- Pi 4 / Pi 5 / Pi-CM4? (1 CSI vs 2 CSI vs USB-add-on path differs)
- 2nd cam connection: CSI-1, CSI-2, or USB?

Operator confirms via direct check, then alpha picks daemon implementation path.

## Out of scope

- Lenormand card-face recognition (template matching, OCR, ML) — codex content-prep's call when authoring the lenormand-reading segment
- Tarot, found objects, books, instruments — future use cases, infra scaffolding ready but no per-domain detector
- Reverie wgpu shader for displacement — could land in compositor source PR or be its own follow-up
- Segment authorship (lenormand reading, etc.) — codex territory

## v2 detector contract

- Canonical Pi-edge module: `pi-edge/ir_platter.py`.
- Canonical function: `detect_platter_objects(grey_frame) -> list[dict]`.
- Empty platter returns `[]`; one large object and multiple smaller objects use the same list contract.
- Each object carries `object_id`, `position_index`, `bbox`, `center`, `corners`, `rotation`, `size`, `area_pct`, `aspect_ratio`, and `extent`.
- IDs are deterministic per visible position in the current frame (`platter-01`, `platter-02`, ...), not content identity or semantic class.
- `extract_platter_crop(frame, detection, output_size=...)` is the canonical crop helper.
- `/platter.json` exposes the current detected object list on the Pi frame server. `/album.jpg` and `/album.json` remain compatibility aliases for older consumers, backed by the primary detected object.
- Detector output is contour geometry only. Content identity, card reading, music provenance, segment authorship, and broadcast claims require downstream receipts.

## References

- Memory: `~/.claude/projects/-home-hapax-projects/memory/project_cbip_relocation_dual_ir_lenormand.md`
- Existing: `pi-edge/hapax_ir_edge.py`, `pi-edge/ir_platter.py`, `pi-edge/ir_album.py`, `agents/studio_compositor/cbip/`, `agents/studio_compositor/cbip_signal_density.py`, `agents/studio_compositor/album_overlay.py`
- Pi fleet config: `agents/health_monitor/constants.py::PI_FLEET`
- IR perception system memory: `project_ir_perception`
