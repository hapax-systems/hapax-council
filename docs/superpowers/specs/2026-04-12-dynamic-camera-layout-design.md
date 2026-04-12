# Dynamic Camera Layout — Design Spec

**Date:** 2026-04-12
**Status:** Approved (self-authored, alpha session)
**Scope:** Runtime camera layout switching for the studio compositor

---

## Problem

The compositor builds its camera layout once at startup from `layout.compute()`. All 6 cameras get equal-weighted tiles in a grid. There's no way to emphasize one camera (hero mode for vinyl/study activity) or rearrange the layout when Sierpinski is active (3 corners).

The handoff research identified "Approach D" as the recommended path: capture at max resolution, scale down non-hero cameras via compositor tile properties. Only restart v4l2src for framerate changes (out of scope for this spec).

## Constraints

- All cameras currently at 1280×720 MJPEG @ 30fps (hardcoded in `agents/studio_compositor/config.py`)
- The compositor element uses `xpos`/`ypos`/`width`/`height` sink pad properties — these are already how tiles are positioned
- Runtime pad property updates are well-supported by GStreamer — no pipeline rebuild needed
- The existing `state_reader_loop` polls `/dev/shm/hapax-compositor/*.txt` at ~10 Hz for control signals
- Layout modes must not break FX chain, recording, snapshots, or the Sierpinski overlay

## Design

### Layout Modes

Three layout modes:

1. **balanced** (default) — Equal grid. Current behavior from `layout.compute()`.

2. **hero/{role}** — One camera takes 2/3 of the canvas area, others stack on the right side. Already partially implemented in `layout.compute()` when `hero_role` is passed (lines 25-83). We'll wire the existing code to a control signal.

3. **sierpinski** — 3 specific cameras occupy the triangle corners (sized to fit the inscribed rectangles of the Sierpinski renderer), the other 3 cameras are hidden (width=0, height=0). Corner positions match `SierpinskiRenderer._inscribed_rect()`.

### Control Signal

File: `/dev/shm/hapax-compositor/layout-mode.txt`

Contents (single line, whitespace-stripped):
- `balanced`
- `hero/{role}` where `role` matches a camera role (e.g. `hero/brio-room`)
- `sierpinski`

Absent file or invalid content → `balanced` (backwards compatible).

### Runtime Application

`state_reader_loop` reads the file each tick. If the mode changes:

1. Recompute tile rects via `layout.compute()` (already accepts `hero_role` param, add `sierpinski` mode)
2. Iterate compositor sink pads, update `xpos`/`ypos`/`width`/`height` on each camera pad
3. Log the transition
4. For `sierpinski` mode, cameras not in the triangle get `alpha=0` or `width=0/height=0` (check which works reliably)

No pipeline rebuild. No v4l2src restart. No caps renegotiation. Transitions are instant.

### API Endpoint

Add `POST /studio/layout` to `logos/api/routes/studio.py`:
```json
{"mode": "hero/brio-room"}
```
Writes the mode file and returns success. Frontend command registry and voice commands can invoke this.

### Command Registry

Register three commands:
- `compositor.layout.balanced`
- `compositor.layout.hero` (takes role arg)
- `compositor.layout.sierpinski`

Wired via the existing command registry WebSocket relay.

## Implementation Scope

**In scope:**
- `layout.py`: extend `compute()` to support sierpinski mode (3 corner rects + hidden others)
- `state.py`: add `_read_layout_mode()` polling, apply via pad property updates
- `logos/api/routes/studio.py`: add `POST /studio/layout` endpoint
- Commands in `hapax-logos/src/lib/commands/studio.ts` (or similar)
- Test that layout transitions don't break the pipeline

**Out of scope:**
- V4L2 resolution changes (requires v4l2src restart, ~200-500ms blackout)
- Framerate changes (same restart requirement)
- Per-camera framerate (all at 30fps is fine for now)
- Automatic mode selection based on activity (director-driven — future stage)

## Acceptance Criteria

- [ ] `echo "hero/brio-room" > /dev/shm/hapax-compositor/layout-mode.txt` switches layout within 200ms
- [ ] `echo "balanced" > /dev/shm/hapax-compositor/layout-mode.txt` returns to the default grid
- [ ] `echo "sierpinski" > /dev/shm/hapax-compositor/layout-mode.txt` places 3 cameras in triangle corners
- [ ] `POST /studio/layout {"mode": "..."}` works via API
- [ ] Pipeline CPU stays within baseline (no camera restart spikes)
- [ ] Recording and HLS outputs continue uninterrupted during transitions
- [ ] Invalid mode falls back to balanced
- [ ] Mode persists until changed (no automatic revert)

## Risk

**Low.** Pad property updates are well-understood GStreamer operations. The existing `layout.compute()` already supports hero mode — we're just wiring control. Sierpinski mode is new but straightforward.

**Unknown:** Whether setting `width=0` or `alpha=0` on hidden cameras reliably hides them without glitching. May need to fall back to moving hidden cameras to negative coordinates (offscreen) instead.
