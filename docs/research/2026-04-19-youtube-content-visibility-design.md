# YouTube Content Visibility — Sierpinski-Fronted vs Dedicated Ward vs Hybrid

**Date:** 2026-04-19
**Status:** Design investigation — pre-implementation
**Session:** cascade-2026-04-18 (delta)
**Scope:** Make YouTube react content clearly visible on the livestream without
abandoning the signature Sierpinski aesthetic. Propose a single recommendation
with a phased rollout.
**Register:** scientific, neutral
**Cross-refs:**
- `docs/superpowers/specs/2026-04-11-sierpinski-visual-layout-design.md` (the approved Sierpinski design)
- `docs/superpowers/specs/2026-04-12-sierpinski-background-render-design.md` (renderer architecture)
- `docs/research/2026-04-14-sierpinski-renderer-cost-walk.md` (per-tick cost audit, 17 triangles × 2 strokes)
- `docs/superpowers/specs/2026-04-18-homage-framework-design.md` (HOMAGE framework, BitchX package)
- `docs/superpowers/specs/2026-04-18-youtube-broadcast-bundle-design.md` (#144/#145: YT attribution + ducking)
- `docs/logos-design-language.md` (visual-surface authority, §3/§4/§6)
- `docs/superpowers/specs/2026-04-10-spirograph-reactor-design.md` (prior YT-display lineage)
- `agents/studio_compositor/ward_fx_mapping.py` (Phase 6 ward↔FX coupling)

---

## 1. Current-state audit

### 1.1 YouTube data path end-to-end

The YouTube content path from KDE-Connect share to composited frame is:

```
KDE Connect share (Pixel 10)            ┐
  → youtube-player.service (:8055)      │  = scripts/youtube-player.py
    - yt-dlp extracts video+audio URLs  │
    - 3 VideoSlot objects, slot 0 only  │
      emits v4l2loopback (/dev/video50) │
    - All 3 slots write JPEG snapshots  │
      to /dev/shm/hapax-compositor/     │
      yt-frame-{0,1,2}.jpg @ 10 fps,    │
      scaled to 384×216                 │
    - All 3 slots write attribution to  │
      yt-attribution-{0,1,2}.txt        │
    - Audio to PipeWire as              │
      youtube-audio-{0,1,2} streams     │
                                        │
                                        ▼
Studio compositor process               ┐
  → SierpinskiLoader (thread)           │  agents/studio_compositor/sierpinski_loader.py
    Poll yt-frame-*.jpg every 0.4s      │
    Publish each as "yt-slot-N" via     │  = /dev/shm/hapax-imagination/sources/
      agents.reverie.content_injector   │     yt-slot-{0,1,2}/
    Active slot opacity 0.9, z=5        │
    Inactive slots 0.3, z=2..4          │
                                        │
  → DirectorLoop (thread)               │  director_loop.py
    150s cadence, narrative LLM,        │
    emits activity ∈ {react, chat,      │
    propose, work, ...}                 │
    Active-slot selection via           │
    SlotAudioControl                    │
                                        │
  → StructuralDirector (thread, 150s)   │  structural_director.py
    Emits StructuralIntent(scene_mode,  │
    preset_family_hint, rotation_mode,  │
    long_horizon_direction)             │
    No YouTube-specific field today     │
                                        │
                                        ▼
Two visible render paths today          ┐
                                        │
  (1) Sierpinski triangle overlay       │  sierpinski_renderer.py
       - Cairo pre-FX overlay           │
       - 1 main triangle + 3 level-1    │
         corners + 12 level-2 triangles │
       - 3 corner rects inscribe        │
         yt-frame-{0..2}.jpg at ~25-30% │
         of canvas each                 │
       - Center void = 8-bar waveform   │
       - Synthwave palette lines        │
       - Active slot alpha 0.9,         │
         inactive 0.4                   │
                                        │
  (2) Reverie wgpu pipeline             │  agents/reverie/
       - yt-slot-N sources composite    │  agents/shaders/nodes/
         into content_layer pass via    │  sierpinski_content.wgsl
         sierpinski_content.wgsl        │
       - Output: /dev/shm/hapax-        │
         sources/reverie.rgba           │
       - Consumed by pip-ur surface     │  (640×360, upper right)
                                        │  = ~6% of canvas
```

Every YouTube video therefore appears on-canvas through exactly two Cairo /
shader paths: **(a)** the Sierpinski triangle overlay rendered via the
`cairooverlay` element in the GStreamer chain (pre-FX, so glfeedback effects
apply on top), and **(b)** the reverie wgpu output composited into `pip-ur` at
640×360. No YouTube frames flow into any other surface today. No PiP is
directly bound to `/dev/video50`; the `video50` device exists only because
some debugging tools expect a V4L2 handle, and the snapshot JPEGs are the
canonical frames.

### 1.2 Visible-area accounting (1920×1080 canvas; env override)

Current default output canvas is 1920×1080 (see
`agents/studio_compositor/config.py` line 39 — `OUTPUT_WIDTH` defaults 1280;
the running env sets it to 1920 under `HAPAX_COMPOSITOR_OUTPUT_WIDTH=1920`).
Under 1920×1080 ≈ 2 073 600 px total:

| Surface | Binding | Pixels | % of canvas |
|---|---|---|---|
| Sierpinski triangle (full-frame overlay) | `cairooverlay`, pre-FX | 1920 × 1080 alpha-blended at 50 % base | ~100 % stroked |
| Sierpinski inscribed rect, corner 0 (top) | yt-frame-0 at active 0.9 alpha | ~400 × 225 | ~4.3 % |
| Sierpinski inscribed rect, corner 1 (BL) | yt-frame-1 at inactive 0.4 alpha | ~400 × 225 | ~4.3 % |
| Sierpinski inscribed rect, corner 2 (BR) | yt-frame-2 at inactive 0.4 alpha | ~400 × 225 | ~4.3 % |
| pip-ur (reverie composite) | yt-slot-N via content_layer pass | 640 × 360 | ~11.1 % |

The single currently-active YT video is therefore visible at roughly:

- **Inscribed corner rect:** ~4.3 % of canvas, ~400 × 225 px visually (with a
  16:9 aspect), clipped to a non-rectangular triangle edge, surrounded by
  stroked glow-lines.
- **Reverie pip-ur:** ~11.1 % of canvas at 640 × 360, but only if the reverie
  mixer has recruited the `yt-slot-N` source into the active generative graph
  at a meaningful opacity. In practice the reverie pipeline blends content at
  variable opacity per stimmung — a react-tagged yt-slot source rarely
  crosses 0.5 blended opacity.

**Total visible YT area per active slot: ~10-12 % of canvas.** The remaining
88-90 % is Sierpinski line work, the six non-YT cairo wards (token_pole,
album, captions, chat_ambient, etc.), and the underlying camera mix.

### 1.3 Why YouTube content is subdued today

Three compounding causes, in descending order of impact:

1. **Geometric constraint — the triangle inscribes the video, not the other
   way around.** The Sierpinski subdivision at `scale=0.75` produces a main
   triangle whose level-1 corner triangles each have a base of roughly
   0.375 × canvas_h. A 16:9 inscribed rectangle inside a triangle that small
   computes to ~400 × 225 px (see `_inscribed_rect` in
   `sierpinski_renderer.py` lines 226-291). This is geometric; no amount of
   style tuning grows the inscribed rect beyond the triangle's interior.

2. **Three equal slots, one active at a time.** The director only audios one
   slot; the other two render at alpha 0.4. This is intentional — it
   communicates which slot is "the" react — but it means ~8.6 % of canvas
   is given to inactive videos that are neither legible enough to "read"
   nor completely absent.

3. **Line work dominates.** Per
   `docs/research/2026-04-14-sierpinski-renderer-cost-walk.md`, the renderer
   strokes 17 triangles twice each tick — 34 stroke operations covering
   most of the canvas with synthwave-neon outlines at alpha 0.8 core +
   alpha 0.15 glow. The line work is the aesthetic but also the dominant
   "voice" of the surface; YT content is secondary texture inside a
   line-art composition.

The technical path is solid — the frames reach the canvas, the active slot
is correctly salience-marked, the audio reaches the ytube sink. The issue is
geometric-aesthetic: the videos are inside a container that makes them small.

---

## 2. Three competing directions

### 2.1 Direction A — Sierpinski-fronted YouTube

**Intent:** Make the Sierpinski the *front* of the canvas during react
activity, and grow the inscribed rectangles.

**Concrete moves:**

- **Triangle scale up.** `_get_triangle(scale=0.75, y_offset=-0.02)` becomes
  `scale=0.95` during react activity, tapering back to 0.75 during non-react
  activity. Main triangle fills more of the canvas.
- **Inscribed rect scale parameter.** Add `inscribed_scale ∈ [1.0, 1.35]`
  that multiplies the 16:9 rect inside each corner triangle. Rect can extend
  up to 35 % past the triangle edges when YT is the focal content — the rects
  are the videos, not the triangle's decorative contents. Triangle becomes a
  frame around the video rects rather than the container they live inside.
- **Per-vertex emphasis.** When the director's active_slot advances from 0→1
  or similar, the newly-active corner pulses (scale 1.0→1.05 over 400 ms)
  while the exiting corner desaturates (saturation 1.0→0.6 over 400 ms). The
  center waveform pulses on each audio kick.
- **Triangle rotation / breath.** Triangle rotates continuously at
  0.002 rad/s (one revolution per 52 min — slow enough to feel alive but not
  busy). During audio peaks, the whole triangle scales 1.0→1.02 → 1.0 on
  kick onset, tying its breath to the react audio.
- **Z-order bump.** Sierpinski surface moves from "pre-FX overlay" to a
  top-strata layer (`z_order 40+`) during react activity; line-work glow
  alpha drops from 0.15→0.08 during react so the lines don't drown the video
  content they now surround.
- **Legibility strip inside the triangle's center void.** Replace the
  waveform with: `»»» [YT-0] {title} — {channel}` running on a CP437 raster
  with a beneath-strip 4-bar audio reactivity peak meter. Grounds the active
  video in narrative without pulling it off the triangle.

**File-level changes (Direction A):**

| File | Change |
|---|---|
| `agents/studio_compositor/sierpinski_renderer.py` | Add `SierpinskiCairoSource.__init__` params: `inscribed_scale: float = 1.0`, `triangle_scale: float = 0.75`, `react_active: bool = False`. Rebuild geom cache when any changes. In `render_content`, read `state["react_active"]` / `state["active_slot"]` and vary the inscribed-rect scale accordingly. Add `set_react_state(active: bool)` facade method. |
| `agents/studio_compositor/sierpinski_renderer.py::_rebuild_geometry_cache` | Replace hardcoded `scale=0.75, y_offset=-0.02` with the instance fields. |
| `agents/studio_compositor/sierpinski_renderer.py::_inscribed_rect` | Accept `scale` kwarg that multiplies the computed `rect_w, rect_h` before clamping. Clamps go from 0.95 to 1.35 — allow overflow beyond the triangle. |
| `agents/studio_compositor/overlay.py::on_draw` | Pass `compositor._director_activity` (already cached) into `sierpinski.set_react_state(activity == "react")`. |
| `agents/studio_compositor/director_loop.py::_speak_activity` | When activity becomes "react", write `/dev/shm/hapax-compositor/react-active.txt` with slot_id. Cleared when activity changes. |
| `agents/studio_compositor/ward_fx_mapping.py::WARD_DOMAIN` | Add `"sierpinski": "perception"` → "reaction" (new domain). Add `"reaction": "audio-reactive"` to DOMAIN_PRESET_FAMILY. |
| `shared/ward_fx_bus.py::WardDomain` | Add `"reaction"` literal. |

**Pros:**
- Preserves the signature aesthetic.
- Re-uses the already-debugged renderer + geometry cache + frame pipeline.
- Composes cleanly with Phase 6 ward↔FX coupling — the sierpinski ward
  becomes an `audio-reactive` domain member during react and contributes to
  the `preset_family_selector`'s bias.
- No new ward; no new surface geometry; no new appsrc pad.
- Retains all existing invariants: pre-FX placement, cairooverlay callback
  synchronous-blit contract, Sierpinski facade API.
- Incremental: the inscribed_scale=1.0 path is the current behaviour.

**Cons:**
- Still geometry-bounded. Pushing `inscribed_scale=1.35` grows each corner
  rect to ~540 × 304 px (≈7.6 % of 1920×1080), but two corner rects now
  visibly overlap at the midpoints of the main triangle's edges. Overlap is
  aesthetically interesting (feedback/cross-talk) but can shred text-heavy
  content (news scrolls, subtitles on the video) that sits near the frame
  edges.
- No dedicated typography strip. YT metadata lives only in the center
  waveform's legibility strip — ~280 × 40 px. Long titles truncate. Channel
  + URL + ts barely fit.
- Inactive slots still waste ~8.6 % of canvas showing videos at alpha 0.4.
  Direction A addresses active-slot visibility but not the "three-slot
  waste" concern.

### 2.2 Direction B — Dedicated YouTube HOMAGE ward

**Intent:** Treat YouTube react content as a first-class ward, framed by the
HOMAGE grammar, explicitly legible, sized for reading.

**Concrete moves:**

- **New ward: `youtube_embed`.** Subclass of `HomageTransitionalSource`
  living at `agents/studio_compositor/homage/wards/youtube_embed.py`.
- **Ward composition:**
  ```
  ┌─ »»» [YT-0 · live] ────────────────────────────────────┐
  │ {title truncated to 96 cols}                            │
  │ ── by {channel} ── via {chatter_handle} @ 14:32 ───     │
  │                                                         │
  │  ╔═════════════════════════════════════════════════════╗│
  │  ║  (YT video frame)                                   ║│
  │  ║  cover-fit, inscribed with 2 px BitchX border       ║│
  │  ║  960 × 540 px natural, scales to surface rect       ║│
  │  ║                                                     ║│
  │  ╚═════════════════════════════════════════════════════╝│
  │                                                         │
  │  ▏director commentary (rolling 64-char scroll)         │
  │  ▏« so the seam between these two rooms is musical »   │
  │                                                         │
  │  ∿ ∿∿ ∿∿∿ ∿∿∿∿ ∿∿∿∿∿ ∿∿∿∿∿∿  (12-bar reactivity)        │
  └─────────────────────────────────────────────────────────┘
  ```
- **Natural size:** 960 × 600 (16:9 video area + header + commentary +
  meter).
- **Surface geometry:** new `youtube-embed-center` surface at
  (480, 120, 960, 600) on 1920×1080 — centered horizontally, anchored in the
  upper half. Roughly 25.9 % of canvas.
- **Emphasis border** via the existing HOMAGE `_maybe_paint_emphasis` hook:
  during `activity == "react"`, the director's structural_intent nominates
  this ward and the 2 px BitchX accent border glows with audio-reactive
  brightness.
- **Audio-reactive shimmer:** add `youtube_embed` to `AUDIO_REACTIVE_WARDS`
  in `ward_fx_mapping.py`; the border hue cycles on kick onset, the 12-bar
  reactivity meter at the bottom pulses to `mixer_energy`.
- **Director commentary feed:** read from
  `/dev/shm/hapax-compositor/compositional-impingements.jsonl` (last record
  with `source=="react"`) and scroll it at 1 char / tick under the video
  rect.
- **BitchX grammar compliance:** `»»»` line-start, angle-bracket container
  (the double-line border is constructed from CP437 `╔ ═ ╗ ║` code points),
  muted-grey punctuation, bright-identity title, accent_cyan "via" chatter
  handle, terminal_default commentary body. Refuses proportional fonts,
  rounded corners, emoji — enforced at package level.

**File-level changes (Direction B):**

| File | Change |
|---|---|
| `agents/studio_compositor/homage/wards/youtube_embed.py` | NEW. `class YouTubeEmbedCairoSource(HomageTransitionalSource)`. Implements `render_content(cr, canvas_w, canvas_h, t, state)` with (a) BitchX header strip, (b) inscribed video rect blitting `yt-frame-{active_slot}.jpg`, (c) commentary scroll, (d) 12-bar reactivity meter. Reads active_slot from `/dev/shm/hapax-compositor/react-active.txt`, title/channel from `yt-attribution-{active_slot}.txt`. |
| `agents/studio_compositor/cairo_source_registry.py` | Register `YouTubeEmbedCairoSource` under class_name `"YouTubeEmbedCairoSource"`. |
| `config/compositor-layouts/default.json` | Add `youtube_embed` source (natural 960×600, rate 15), `youtube-embed-center` surface at (480, 120, 960, 600, z_order 50), and a conditional assignment gated on `structural_intent.youtube_surface ∈ {"dedicated", "hybrid"}`. Layout loader needs a new `assignment.conditional_on` schema field. |
| `shared/compositor_model.py::Assignment` | Add optional `conditional_on: dict[str, Any] | None = None`. Layout resolver filters out assignments whose condition doesn't match current structural state. |
| `agents/studio_compositor/layout_loader.py` | Evaluate `conditional_on` during layout materialization; read structural intent from `/dev/shm/hapax-structural/intent.json` each tick. |
| `agents/studio_compositor/structural_director.py::StructuralIntent` | Add field `youtube_surface: Literal["sierpinski_only", "dedicated", "hybrid"] = "sierpinski_only"`. LLM prompt addendum (§3.4 below) teaches the director when to shift. |
| `agents/studio_compositor/ward_fx_mapping.py` | Add `"youtube_embed": "reaction"`, add `"reaction": "audio-reactive"` to `DOMAIN_PRESET_FAMILY`, and add `"youtube_embed"` to `AUDIO_REACTIVE_WARDS`. |
| `shared/ward_fx_bus.py::WardDomain` | Add `"reaction"` literal. |
| `tests/studio_compositor/test_youtube_embed_ward.py` | NEW. Unit: FSM transitions, render_content snapshot, structural_intent gating, commentary scroll advance. |

**Pros:**
- Maximum legibility. Title and channel are never truncated to a few pixels.
- Director commentary is *on the same surface as the video* — the operator
  and the audience can read what Hapax is saying about the content while
  looking at the content.
- BitchX framing preserves the aesthetic register (CP437, monospaced, muted
  punctuation, bright identity). Not a generic YouTube PiP.
- Emphasis + ward_fx_mapping integration is free once the ward exists.
- Natural rollout path: ship behind `structural_intent.youtube_surface ==
  "dedicated"` and let the director decide when to deploy it.

**Cons:**
- Adds a new fullscreen-adjacent surface (~26 % of canvas). During its
  active window, it will cover cameras, some wards, and portions of the
  Sierpinski. This is the feature, but it is also the cost.
- Risk of "generic media-viewer box". The BitchX grammar is the
  differentiator — if the package design drifts to rounded corners or
  proportional fonts, this ward becomes a YouTube iframe. The framework's
  `refuses_anti_patterns` set on the BitchX package is load-bearing.
- New conditional-assignment machinery in layout loader. Cross-cutting
  change.
- Inactive slots 1 and 2 are not addressed — this ward shows only the active
  slot by design. (Arguably correct: show the react you're reacting to,
  hide the queue.)

### 2.3 Direction C — Hybrid foreground (recommended)

**Intent:** Sierpinski remains the primary YT surface (Direction A base).
When the director decides the video deserves focused attention, the
dedicated ward materializes on top of / alongside the triangle. The
Sierpinski "flowers" around the dedicated ward — triangle vertices continue
to show YT at lower salience; the ward is the focal point.

**Orchestration:**

- `structural_intent.youtube_surface` is the *vocabulary*:
  - `"sierpinski_only"` — default. Direction A render path. Sierpinski with
    enlarged inscribed rects during react activity.
  - `"dedicated"` — Direction B render path. `youtube_embed` ward visible at
    (480, 120, 960, 600). Sierpinski renders at `triangle_scale=0.60`,
    `inscribed_scale=0.85` — it shrinks and pulls inward, visibly ceding
    the centre to the ward.
  - `"hybrid"` — both. `youtube_embed` ward visible. Sierpinski renders at
    `triangle_scale=0.85`, `inscribed_scale=1.20` — it grows around the
    ward, the corner rects showing the inactive slots (1 and 2) while
    the dedicated ward centres on slot 0. Line-work glow alpha drops to
    0.08 so the triangle reads as a frame, not a container. The ward's
    bottom edge sits just above the triangle's apex; the triangle
    surrounds it on three sides like a shrine.
- **Director decision hooks (structural_director LLM prompt addendum):**
  The prompt gains a one-paragraph instruction: *"When YouTube react
  content is active and meaningful to narrate (new video just started, a
  lyric or visual element is worth isolating, chat has just asked about
  the content), set `youtube_surface` to `dedicated` for ~30-60 s.
  When the react has settled into background (just-vibing, no narration),
  shift to `hybrid` so the content stays large without consuming the whole
  frame. Return to `sierpinski_only` between react activities."*
- **Cadence:** structural_director runs every 150 s. If a tighter cadence
  is needed (e.g. new video shared in chat), `twitch_director` (4 s
  cadence, deterministic) writes a one-shot `youtube_surface` override
  that expires after 60 s.

**File-level changes (Direction C = A + B + orchestration):**

All of Direction A's and Direction B's changes, plus:

| File | Change |
|---|---|
| `agents/studio_compositor/structural_director.py::StructuralIntent` | `youtube_surface` field already added by Direction B. Prompt addendum in the LLM template. |
| `agents/studio_compositor/twitch_director.py` | Add `youtube_surface_override: {"mode": str, "expires_at": float}` writable from HTTP endpoint `POST /twitch/youtube_surface`. Expiry read by layout_loader. |
| `agents/studio_compositor/sierpinski_renderer.py` | In `set_react_state`, also accept `surface_mode ∈ {"sierpinski_only", "dedicated", "hybrid"}`. Apply per-mode (triangle_scale, inscribed_scale, glow_alpha, line_alpha) profiles. |
| `config/compositor-layouts/default.json` | `youtube-embed-center` surface conditional_on `{"structural_intent.youtube_surface": ["dedicated", "hybrid"]}`. |
| `docs/superpowers/specs/2026-04-19-youtube-surface-orchestration-design.md` | NEW. Spec for the 3-mode vocabulary, director decision policy, twitch override mechanism, test matrix. (Follow-on to this research doc.) |

**Pros:**
- Best-of-both: legibility when needed, signature aesthetic at rest.
- Sierpinski never disappears. The dedicated ward *emerges from* the
  triangle rather than replacing it.
- Director decides — this composes with the existing
  structural_director / twitch_director split.
- Each mode is independently testable.

**Cons:**
- Two render paths to maintain. Direction A's inscribed_scale field AND
  Direction B's ward both need to work, AND the hybrid-mode choreography of
  how they coexist. More test matrix.
- The layout loader's `conditional_on` addition is strictly required; the
  layout machinery grows a new concept.

---

## 3. Implementation sketches

### 3.1 `SierpinskiRenderer` changes (Direction A core)

```python
# agents/studio_compositor/sierpinski_renderer.py

class SierpinskiCairoSource(HomageTransitionalSource):
    def __init__(self) -> None:
        super().__init__(source_id="sierpinski")
        # New fields:
        self._triangle_scale = 0.75      # 0.60..0.95 depending on mode
        self._inscribed_scale = 1.00     # 0.85..1.35 depending on mode
        self._line_glow_alpha = 0.15     # 0.08 in hybrid/dedicated
        self._line_core_alpha = 0.80     # unchanged in all modes
        self._react_active = False
        self._surface_mode = "sierpinski_only"
        # ... existing cache fields ...

    def set_react_state(
        self,
        *,
        active: bool,
        surface_mode: str = "sierpinski_only",
        active_slot: int = 0,
    ) -> None:
        """Update react/surface state. Invalidates geometry cache on change."""
        changed = (
            active != self._react_active
            or surface_mode != self._surface_mode
            or active_slot != self._active_slot
        )
        self._react_active = active
        self._surface_mode = surface_mode
        self._active_slot = active_slot
        if changed:
            # Per-mode visual profile.
            profile = _MODE_PROFILES[surface_mode if active else "sierpinski_only_rest"]
            self._triangle_scale = profile["triangle_scale"]
            self._inscribed_scale = profile["inscribed_scale"]
            self._line_glow_alpha = profile["glow_alpha"]
            # Force geom rebuild next tick:
            self._geom_cache_size = None

    def _rebuild_geometry_cache(self, canvas_w: int, canvas_h: int) -> None:
        tri = self._get_triangle(
            float(canvas_w), float(canvas_h),
            scale=self._triangle_scale,
            y_offset=-0.02,
        )
        # ... subdivisions unchanged ...
        self._cached_corner_rects = [
            self._inscribed_rect(corner_0, scale=self._inscribed_scale),
            self._inscribed_rect(corner_1, scale=self._inscribed_scale),
            self._inscribed_rect(corner_2, scale=self._inscribed_scale),
        ]
        # ... rest unchanged ...

    def _inscribed_rect(
        self,
        tri: list[tuple[float, float]],
        *,
        scale: float = 1.0,
    ) -> tuple[float, float, float, float]:
        # ... existing math to rect_h, rect_w ...
        rect_h *= scale
        rect_w *= scale
        # Clamp upper bound to scale * 0.95 of base (allows overflow past triangle):
        max_w = base_len * max(0.95, scale * 0.95)
        if rect_w > max_w:
            rect_w = max_w
            rect_h = rect_w / aspect
        # ... position math unchanged ...


_MODE_PROFILES = {
    # Rest (no react): preserve current aesthetic.
    "sierpinski_only_rest": {"triangle_scale": 0.75, "inscribed_scale": 1.00, "glow_alpha": 0.15},
    # React + sierpinski-only: enlarge.
    "sierpinski_only":       {"triangle_scale": 0.95, "inscribed_scale": 1.20, "glow_alpha": 0.10},
    # React + dedicated: cede centre to ward.
    "dedicated":             {"triangle_scale": 0.60, "inscribed_scale": 0.85, "glow_alpha": 0.08},
    # React + hybrid: surround the ward.
    "hybrid":                {"triangle_scale": 0.85, "inscribed_scale": 1.20, "glow_alpha": 0.08},
}
```

### 3.2 New ward — `YouTubeEmbedCairoSource` (Direction B core)

```python
# agents/studio_compositor/homage/wards/youtube_embed.py

"""YouTube react-content ward. HOMAGE-framed video embed with director commentary.

When active, renders the currently-active YT slot's frame with a BitchX-grammar
header (title, channel, attribution chatter), a rolling commentary scroll fed
from compositional-impingements.jsonl, and a 12-bar audio-reactivity meter.
"""

from __future__ import annotations
import json
from pathlib import Path

import cairo

from agents.studio_compositor.homage.rendering import (
    active_package, paint_bitchx_bg, select_bitchx_font,
)
from agents.studio_compositor.homage.transitional_source import (
    HomageTransitionalSource,
)

YT_FRAME_DIR = Path("/dev/shm/hapax-compositor")
REACT_STATE = YT_FRAME_DIR / "react-active.txt"
IMPINGEMENTS = Path("/dev/shm/hapax-compositor/compositional-impingements.jsonl")

class YouTubeEmbedCairoSource(HomageTransitionalSource):
    def __init__(self) -> None:
        super().__init__(source_id="youtube_embed")
        self._active_slot = 0
        self._video_surface: cairo.ImageSurface | None = None
        self._video_mtime = 0.0
        self._title = ""
        self._channel = ""
        self._audio_energy = 0.0
        self._commentary = ""
        self._commentary_scroll_px = 0.0

    def set_active_slot(self, slot_id: int) -> None:
        self._active_slot = slot_id

    def set_audio_energy(self, energy: float) -> None:
        self._audio_energy = energy

    def render_content(self, cr, canvas_w, canvas_h, t, state):
        pkg = active_package()

        # 1. BitchX background with domain tint ("reaction" domain).
        paint_bitchx_bg(cr, canvas_w, canvas_h, pkg, ward_id="youtube_embed")

        # 2. Refresh attribution + commentary once per tick.
        self._refresh_attribution()
        self._refresh_commentary()

        # 3. Header strip: »»» [YT-0 · live] {title truncated}
        header_h = 56
        self._render_header(cr, canvas_w, header_h, pkg)

        # 4. Video rect: 16:9 centred, below header, above footer.
        footer_h = 140  # commentary scroll + reactivity meter
        video_area_h = canvas_h - header_h - footer_h
        video_rect = self._compute_video_rect(
            canvas_w, header_h, video_area_h
        )
        self._render_video(cr, video_rect)

        # 5. Commentary scroll.
        self._render_commentary(cr, canvas_w, canvas_h - footer_h, pkg)

        # 6. 12-bar reactivity meter at the bottom.
        self._render_reactivity(cr, canvas_w, canvas_h, t, pkg)

    def _refresh_attribution(self) -> None:
        try:
            raw = (YT_FRAME_DIR / f"yt-attribution-{self._active_slot}.txt").read_text()
            lines = raw.splitlines()
            self._title = lines[0] if lines else ""
            self._channel = lines[1] if len(lines) > 1 else ""
        except OSError:
            pass

    def _refresh_commentary(self) -> None:
        # Tail the compositional-impingements feed for the latest react-tagged record.
        try:
            lines = IMPINGEMENTS.read_text().splitlines()[-30:]
            for line in reversed(lines):
                record = json.loads(line)
                if record.get("source") == "react":
                    text = record.get("narrative", "").strip()
                    if text and text != self._commentary:
                        self._commentary = text
                        self._commentary_scroll_px = 0.0
                    break
        except (OSError, json.JSONDecodeError):
            pass

    def _render_header(self, cr, w, h, pkg):
        select_bitchx_font(cr, 18, bold=True)
        r, g, b, a = pkg.resolve_colour("muted")
        cr.set_source_rgba(r, g, b, a)
        cr.move_to(16, 36)
        cr.show_text("»»» ")
        r, g, b, a = pkg.resolve_colour("accent_cyan")
        cr.set_source_rgba(r, g, b, a)
        cr.show_text(f"[YT-{self._active_slot} · live] ")
        r, g, b, a = pkg.resolve_colour("bright")
        cr.set_source_rgba(r, g, b, a)
        # Truncate title to canvas-appropriate char count.
        char_w = 10
        max_chars = max(20, (w - 220) // char_w)
        title = self._title[:max_chars]
        cr.show_text(title)
        # Channel line (row 2) in terminal_default.
        if self._channel:
            r, g, b, a = pkg.resolve_colour("terminal_default")
            cr.set_source_rgba(r, g, b, a)
            cr.move_to(16, 52)
            select_bitchx_font(cr, 12, bold=False)
            cr.show_text(f"── by {self._channel} ──")

    def _compute_video_rect(self, w, top, area_h):
        """Return the largest 16:9 rect fitting (w - 40, area_h - 20)."""
        aspect = 16.0 / 9.0
        max_w = w - 40
        max_h = area_h - 20
        if max_w / aspect <= max_h:
            rect_w = max_w
            rect_h = rect_w / aspect
        else:
            rect_h = max_h
            rect_w = rect_h * aspect
        x = (w - rect_w) * 0.5
        y = top + (area_h - rect_h) * 0.5
        return (x, y, rect_w, rect_h)

    def _render_video(self, cr, rect):
        # Mtime-cached load (same pattern as SierpinskiCairoSource._load_frame).
        # Blit with cover-fit into the rect, 2 px BitchX accent_cyan border.
        ...

    def _render_commentary(self, cr, w, y, pkg):
        # Marquee scroll at 1 char / 80 ms using self._commentary_scroll_px.
        ...

    def _render_reactivity(self, cr, w, h, t, pkg):
        # 12 bars, amp = self._audio_energy * (0.5 + 0.5 * sin(i * 0.8 + t * 2)).
        # accent_cyan bars, muted-grey baseline.
        ...
```

### 3.3 Layout conditional-assignment (Direction C machinery)

```python
# shared/compositor_model.py

class Assignment(BaseModel):
    source: str
    surface: str
    transform: dict[str, Any] = Field(default_factory=dict)
    opacity: float = 1.0
    per_assignment_effects: list[Any] = Field(default_factory=list)
    non_destructive: bool = False
    # NEW:
    conditional_on: dict[str, list[str]] | None = Field(
        default=None,
        description=(
            "Optional. Key = dotted path into compositor state "
            "(e.g. 'structural_intent.youtube_surface'); value = list of "
            "accepted values. Assignment materializes only when the state "
            "read at the dotted path matches one of the values. None = "
            "always materialize. Read from /dev/shm state at layout-resolve "
            "time each tick."
        ),
    )


# agents/studio_compositor/layout_loader.py

def _evaluate_conditional(cond: dict[str, list[str]] | None, state_snapshot: dict) -> bool:
    if cond is None:
        return True
    for dotted, accepted in cond.items():
        parts = dotted.split(".")
        value: Any = state_snapshot
        for part in parts:
            value = value.get(part) if isinstance(value, dict) else None
            if value is None:
                return False
        if str(value) not in accepted:
            return False
    return True


def resolve_layout(layout: Layout) -> list[Assignment]:
    state = _read_compositor_state_snapshot()
    return [a for a in layout.assignments if _evaluate_conditional(a.conditional_on, state)]


def _read_compositor_state_snapshot() -> dict:
    """Read /dev/shm state files into a snapshot dict for conditional eval."""
    snapshot: dict[str, dict[str, Any]] = {"structural_intent": {}}
    try:
        intent = json.loads(Path("/dev/shm/hapax-structural/intent.json").read_text())
        snapshot["structural_intent"] = intent
    except (OSError, json.JSONDecodeError):
        pass
    return snapshot
```

### 3.4 Director prompt addendum (Direction C orchestration)

Addendum to `StructuralDirector`'s prompt template (after the existing
scene_mode / preset_family_hint sections):

```
You can also shape how YouTube react content is visible on the canvas via the
"youtube_surface" field:

- "sierpinski_only": the default. The YouTube react videos live inscribed in
  the Sierpinski triangle's three corners. Use when: no react activity, or the
  react is ambient background, or you want the canvas to breathe.

- "dedicated": a fullscreen-adjacent YouTube embed ward appears centered in
  the upper half of the canvas (960x600). The Sierpinski shrinks to 60% and
  moves out of the way. Use when: a new video has just started and deserves
  the operator + audience's direct attention; chat has just asked about the
  content; a lyric or visual element is worth isolating for narration. Budget
  this sparingly - dedicated mode should last 30-60s per deployment; longer
  deployments feel like a YouTube player instead of a livestream.

- "hybrid": both surfaces visible simultaneously. The dedicated ward is
  present, and the Sierpinski enlarges to 85% around it - the triangle frames
  the ward, its vertices continuing to show the other YT slots at lower
  salience. Use when: the react is steady and you want the content large
  without it feeling like a media player; when audio-reactive co-motion
  between the triangle and ward carries the aesthetic.

Return to "sierpinski_only" between react activities, always. The dedicated
and hybrid modes are for moments, not states.
```

Valid `youtube_surface` values enumerated in the Pydantic field; model
output constrained via `response_format={"type": "json_object"}` + schema.

### 3.5 Layout JSON example — Direction C

```json
{
  "sources": [
    {
      "id": "youtube_embed",
      "kind": "cairo",
      "backend": "cairo",
      "params": {
        "class_name": "YouTubeEmbedCairoSource",
        "natural_w": 960,
        "natural_h": 600
      },
      "update_cadence": "rate",
      "rate_hz": 15.0,
      "tags": ["homage", "reaction", "authorship"]
    }
  ],
  "surfaces": [
    {
      "id": "youtube-embed-center",
      "geometry": {
        "kind": "rect",
        "x": 480, "y": 120, "w": 960, "h": 600
      },
      "z_order": 50,
      "update_cadence": "always"
    }
  ],
  "assignments": [
    {
      "source": "youtube_embed",
      "surface": "youtube-embed-center",
      "opacity": 0.95,
      "conditional_on": {
        "structural_intent.youtube_surface": ["dedicated", "hybrid"]
      }
    }
  ]
}
```

### 3.6 `ward_fx_mapping.py` addition

```python
# shared/ward_fx_bus.py
WardDomain = Literal[
    "communication", "presence", "token", "music", "cognition",
    "director", "perception",
    "reaction",  # NEW
]

# agents/studio_compositor/ward_fx_mapping.py
DOMAIN_PRESET_FAMILY: dict[WardDomain, PresetFamily] = {
    # ... existing ...
    "reaction": "audio-reactive",  # NEW
}

WARD_DOMAIN: dict[str, WardDomain] = {
    # ... existing ...
    "sierpinski": "reaction",      # was "perception"
    "youtube_embed": "reaction",   # NEW
}

AUDIO_REACTIVE_WARDS: frozenset[str] = frozenset({
    # ... existing ...
    "sierpinski",       # NEW
    "youtube_embed",    # NEW (Direction B/C)
})
```

Effect: when the director emits a ward_dispatch for either ward, the
`preset_family_selector` biases toward `audio-reactive` presets, and the
reactor emits `scale_bump_pct` + `border_pulse_hz` onto
`ward-properties.json` on each audio kick.

---

## 4. Tight integration invariant

Regardless of direction chosen, the following invariants hold and must be
verified by test and by manual rehearsal:

1. **Sierpinski never fully disappears.** The triangle is the signature; the
   aesthetic is non-negotiable. In `dedicated` mode it shrinks to 0.60 scale
   but still renders. A render path that zeroes the sierpinski surface for
   any structural intent is a regression.
2. **YT audio reactivity drives both surfaces.** `SierpinskiCairoSource.
   set_audio_energy()` and `YouTubeEmbedCairoSource.set_audio_energy()` both
   receive `mixer_energy` from `compositor._cached_audio`. The 12-bar meter
   in the ward and the waveform / line-width modulation in the triangle
   pulse on the same beat — the canvas is coherent, not two independent
   animations.
3. **Director intent stays legible.** Even when `youtube_embed` covers the
   centre at 26 % of canvas, the `grounding_provenance_ticker` (bottom-left,
   480×40), `activity_header` (top centre, 800×56), `captions_strip` (bottom
   full-width), and `stance_indicator` (top right) remain visible. The
   ward's surface is centred and 600 px tall; the legibility surfaces live
   at the margins. This is enforced by z_order (ward z=50, legibility
   z=22-30 but positioned in uncovered areas).
4. **Face obscure applies to cameras only.** The face_obscure_pipeline
   (`agents/studio_compositor/face_obscure_integration.py`) pixelates every
   camera frame before any tee. YouTube content flows through a separate
   ffmpeg → JPEG → cairo-blit path that never touches the camera pipeline.
   The dedicated ward's video rect is NOT behind a face obscure; this
   mirrors current behaviour for the Sierpinski corner rects. If a given
   YT video contains faces, face obscure does NOT apply to them — this is
   consistent with today's invariant, and it means the ward does not
   create a new consent exposure. Documented explicitly in the ward
   docstring.
5. **Consent-safe layout remains a strict superset.** `consent-safe.json`
   layout (triggered when a guest is detected and no contract exists) has
   no `youtube_embed` assignment. Even if structural_intent is
   `dedicated`, consent-safe gates it out upstream. Verified by
   `tests/test_consent_safe_layout.py` snapshot.
6. **Sierpinski's pre-FX position is preserved.** In `sierpinski_only` and
   `hybrid`, the triangle renders via `cairooverlay` before the GL shader
   chain, so glfeedback/ripple/etc. still compose over it. In `dedicated`,
   same — the ward is a separate Cairo source composited post-FX at z=50,
   but the Sierpinski itself stays pre-FX. Two surfaces, one pre-FX, one
   post-FX. This is already the pattern for album / token_pole.

---

## 5. Rollout plan

| Phase | Direction | Ship window | Scope |
|---|---|---|---|
| 1 | A — Sierpinski inscribed-scale + triangle-scale modulation | 1-2 days | Ship `SierpinskiCairoSource` changes + ward_fx_mapping update + director hook for `react-active.txt` writeout + smoke test. No new ward, no conditional-assignment machinery. Incremental improvement on active-slot visibility. |
| 2 | B — `YouTubeEmbedCairoSource` ward + layout conditional-assignment | 3-5 days | Ship the new ward, the BitchX header / commentary / reactivity meter rendering, the `Assignment.conditional_on` field and layout_loader evaluation, the `StructuralIntent.youtube_surface` field, CairoSource registry entry, layout JSON additions, ward_fx_mapping entry, tests. Ship behind `structural_intent.youtube_surface == "dedicated"` — operator manually writes the intent file during rehearsal to exercise the path. LLM prompt addendum deferred to Phase 3. |
| 3 | C — director orchestration | 1 day once A+B ship | Add the prompt addendum to `StructuralDirector`. Add the `twitch_director` override endpoint. Test that director's LLM emits `dedicated` / `hybrid` / `sierpinski_only` across scenarios; measure dedicated-mode cadence to ensure it stays ~30-60 s per deployment. |

**Testing matrix (per direction):**

| Scenario | A sierpinski_only | B dedicated | C hybrid | Expected |
|---|---|---|---|---|
| No YT active | line-art only, no yt-frames | line-art only | line-art only | ward absent, triangle at rest |
| YT active, no emphasis (rest react) | corner rects at 1.00× scale, active alpha 0.9 | ward absent, triangle as sierpinski_only | n/a | triangle carries the react |
| YT active, ward emphasized | n/a | ward at z=50, tri shrunk to 0.60 | both visible | ward is focal, tri frames it |
| YT active, hybrid | n/a | n/a | ward + tri at 0.85 surround | both audio-react; tri glow is low |
| Audio kick during dedicated | n/a | 12-bar meter spikes, border hue pulses | both meters + tri lines pulse | coherent beat across surfaces |
| Consent-safe layout | ward absent | ward absent | ward absent | regardless of intent, ward gated |
| Guest detected mid-dedicated | ward instantly absent | ward instantly absent | ward instantly absent | layout rematerialise picks consent-safe, ward removed |

Golden-frame tests with `tests/studio_compositor/test_sierpinski_visibility.py`
and `tests/studio_compositor/test_youtube_embed_ward.py` snapshot the
rendered output for each scenario on a 1280×720 test canvas.

---

## 6. Aesthetic principles

### 6.1 What tight integration looks like

Tight integration means: the triangle and the video breathe on the same
clock. When a kick drops in the YT audio, the triangle's line width pulses
upward, the ward's border hue cycles, the 12-bar meter spikes, the inscribed
rects scale 1.00→1.02, all on the same envelope. The viewer does not
experience "a video playing inside a triangle overlay" — they experience a
geometric field that is *reacting to* the video, and the video *is* the
field.

In `hybrid` mode specifically: the ward sits centred; the triangle wraps
around it, scale 0.85, vertices extending to the canvas corners with
yt-slot-1 in the bottom-left and yt-slot-2 in the bottom-right. The
triangle's apex sits just above the ward's top edge; the triangle's base
below the ward's bottom edge. The composition reads as a monstrance — a
sacred container — for the react content. The line-art glow is dim
(0.08 alpha), so the lines draw the eye without competing with the video.
When Hapax is reacting, the whole geometric field responds; the ward is
the pupil, the triangle the iris.

### 6.2 What tight integration does NOT look like

- **A YouTube player on a background.** If the ward's border is rounded, or
  its typography is sans-serif, or it has a progress bar, it becomes a
  generic media player. The BitchX grammar refuses all of those.
- **A video popping in over a static triangle.** If the triangle doesn't
  acknowledge the ward — doesn't shrink in `dedicated`, doesn't enlarge
  around the ward in `hybrid` — the two surfaces read as uncoordinated.
- **Three equal slots screaming for attention.** The director's active-slot
  selection is load-bearing; the inactive slots must be visibly subdued.
  The current alpha 0.9 / 0.4 ratio is correct; if it drifts toward 0.9 /
  0.7 the canvas becomes illegible. Direction A's enlarged inscribed rects
  make the ratio more important, not less.
- **Beat-independent animation.** Both surfaces share `mixer_energy`; a
  path that pulses the triangle on one audio source and the ward on another
  is a correctness regression.

### 6.3 Homage lineage

The dedicated ward is HOMAGE-framed via the BitchX package (current active
package). Its aesthetic ancestry is: early-2000s IRC text mode, `»»»`
line-start markers, mIRC-16 colour contract (bright identity, muted
punctuation, cyan accent), CP437 raster — filtered through a post-digital
reading of "what does a livestream's reaction to video content look like in
a text-mode imaginary?" The ward is not a modern YouTube card; it is a
BitchX `/tell` notification of "the channel is currently reacting to THIS".

The Sierpinski's ancestry is synthwave neon line-art; fractal subdivision
as a geometric commitment, not decoration. The two surfaces meet in
`hybrid` mode: BitchX text-mode centred in a synthwave geometric field,
sharing an audio-reactive clock. Register: scientific + nostalgic +
minimal.

---

## 7. Recommendation

**Ship Direction C (hybrid foreground orchestrated by the structural
director), with a staged rollout: A first (1-2 days), then B (3-5 days),
then director orchestration (1 day).**

Justification:

1. **Direction A alone is insufficient** — the operator's stated problem is
   that YouTube content is subdued. Growing inscribed rects from 4.3 % to
   7.6 % of canvas is an improvement but does not resolve "videos need to
   be more visible". Direction A is the prerequisite for the others, but
   it is not the deliverable.
2. **Direction B alone abandons the signature** — a 26 % dedicated ward
   without a Sierpinski response reduces the canvas to "a YouTube embed
   with some text overlays". The triangle is the aesthetic identity.
3. **Direction C compounds both** — the ward provides legibility when the
   director decides the content deserves focus; the triangle stays present
   and responds to the ward's activation. The director's decisions are
   grounded (per the grounding-exhaustive axiom) and cadenced by the slow
   150 s structural cycle + the 4 s twitch override. This composes with
   the existing director architecture without new policy.
4. **The staged rollout is low-risk** — each direction ships independently
   and is individually testable. Direction A is pure renderer delta;
   Direction B introduces a new ward (additive, gated behind a field that
   defaults to `sierpinski_only`); Direction C is a prompt change + a
   small override endpoint. If Direction C's prompt doesn't produce good
   timing, the operator can write `intent.json` by hand in rehearsal and
   the surfaces still work.

### 7.1 Next-ship items

Ordered by priority:

1. **Phase 1 PR:** `SierpinskiCairoSource` inscribed-scale + triangle-scale
   + react-state hook. Write `/dev/shm/hapax-compositor/react-active.txt`
   from `director_loop._speak_activity`. Wire `overlay.on_draw` to pass
   react state. Unit tests on the inscribed-rect math, snapshot tests
   on the enlarged-corners render. **Ship first — proves the visibility
   lift is real on the livestream before building the ward.**
2. **Phase 2 PR A:** `Assignment.conditional_on` schema field +
   `layout_loader` evaluation. Pure infrastructure, no visible change
   yet. Unit tests on state-snapshot reading and conditional evaluation.
3. **Phase 2 PR B:** `YouTubeEmbedCairoSource` ward + registry entry +
   layout JSON addition + ward_fx_mapping update. Ships gated by
   `structural_intent.youtube_surface ∈ {"dedicated", "hybrid"}`, which
   defaults to `sierpinski_only`, so it's dormant until exercised.
   Snapshot tests for each render region (header, video, commentary,
   reactivity).
4. **Phase 3 PR:** Structural director prompt addendum + twitch override
   endpoint + first end-to-end rehearsal. Measure dedicated-mode cadence
   in `structural-intent.jsonl`; adjust prompt if the director
   over-deploys.
5. **Follow-on:** Spec doc
   `docs/superpowers/specs/2026-04-19-youtube-surface-orchestration-design.md`
   formalising the three-mode vocabulary, decision policy, test matrix.
   (This research doc is the pre-spec; the spec ships with Phase 2.)

### 7.2 One-sentence operator summary

*Sierpinski becomes the signature frame, a new BitchX-framed YouTube-embed
ward materialises on top when the director wants focus, and the structural
director chooses among three modes — sierpinski_only, dedicated, hybrid —
on a 150 s cadence so the canvas breathes between "react is vibing in the
triangle" and "this one deserves a close look".*

---

Echo path:
`hapax-council--cascade-2026-04-18/docs/research/2026-04-19-youtube-content-visibility-design.md`
