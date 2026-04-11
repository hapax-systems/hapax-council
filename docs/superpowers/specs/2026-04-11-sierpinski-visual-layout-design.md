# Sierpinski Triangle Visual Layout

**Date:** 2026-04-11
**Status:** Approved
**Scope:** Replace spirograph reactor with Sierpinski triangle renderer in the Reverie visual surface (wgpu pipeline)

## Problem

The spirograph reactor renders YouTube video frames as orbiting circles in the Reverie visual surface. The orbit animation is jerky (10fps snapshot poll), the layout is visually busy, and the circular masking wastes screen area. The operator wants a static, structured layout with clear regions for video content and audio visualization.

## Design

### 1. Sierpinski Triangle Shader (`sierpinski` node)

A WGSL shader pass in the wgpu vocabulary graph renders a 2-3 level Sierpinski triangle:

- **Geometry:** Equilateral triangle subdivided 2-3 levels deep. 3 large corner regions (video content), 1 center region (waveform), with visible sub-triangle line work inside the corner regions for visual texture.
- **Palette:** Synthwave — neon pink, cyan, purple gradients on line work. Colors defined as shader uniforms, driven by `spectral_color` dimension.
- **Line variations:** Thickness and glow modulated by `intensity` and `tension` shader params. Audio-reactive via existing modulator bindings.
- **Opacity:** 50% base alpha over content beneath. The triangle is an overlay, not an opaque mask.
- **Position:** Static placement initially. Dynamic placement deferred to future work.

The shader takes standard vocabulary params (intensity, tension, spectral_color, time) and outputs RGBA with alpha. It slots into the vocabulary graph as a node between the content layer and postprocess.

### 2. Video Content Masking

Extend the content layer pass (or add a `video_content` pass) to composite YouTube video frames into the 3 large corner triangle regions:

- **Texture upload:** Load 3 JPEG snapshots from `/dev/shm/hapax-compositor/yt-frame-{0,1,2}.jpg` as GPU textures. Upload at 10fps (matching youtube-player snapshot rate).
- **Triangle masking:** Each video is clipped to its corner triangle region using triangle-shaped geometry in the shader. The mask is computed from the same Sierpinski subdivision math as the line renderer.
- **Slot mapping:** slot 0 → top corner, slot 1 → bottom-left, slot 2 → bottom-right.
- **Active slot visual:** The currently active slot (audio unmuted, director reacting to it) gets full opacity. Inactive slots render at reduced opacity or with a desaturation effect.

### 3. Waveform in Center Triangle

The center triangle section (the void in the Sierpinski subdivision) renders a Hapax audio waveform:

- **Data source:** `mixer_master` audio capture signals already available in the shader pipeline via modulator bindings (`mixer_energy`, `mixer_bass`, `mixer_mid`, `mixer_high`, `mel_*` bands).
- **Visualization:** Frequency bar or waveform line rendered in WGSL, using the 8 mel band signals for per-bar amplitude.
- **Style:** Synthwave palette consistent with triangle line work. Glow effect on peaks.

### 4. Sierpinski Content Loader (replaces spirograph reactor)

A Python module replaces `spirograph_reactor.py`. Responsibilities:

- Poll `yt-frame-{0,1,2}.jpg` snapshots at 10fps (100ms interval, matching current spirograph poll rate after the performance fix).
- Upload frames to the wgpu pipeline as textures via the existing content injection path (UDS socket to hapax-imagination or `/dev/shm` shared memory).
- Track which slot is active (read from director loop state) for opacity modulation.
- Handle slot finished/reload events (same as current spirograph reactor's `check_finished()` / playlist reload).

The director loop's `_speak_activity` / `_do_speak_and_advance` integration stays unchanged — the content loader is a drop-in replacement for the spirograph reactor's video display role.

### 5. Vocabulary Graph Integration

The Sierpinski triangle slots into the existing 8-pass vocabulary graph. Current graph:

```
noise → rd → color → drift → breath → feedback → content_layer → postprocess
```

Updated graph:

```
noise → rd → color → drift → breath → feedback → video_content → sierpinski → postprocess
```

- `video_content`: Composites YouTube frames into triangle-masked regions + waveform in center
- `sierpinski`: Renders triangle line work at 50% opacity over the video content

Both are new WGSL shader nodes registered in the effect graph node type registry.

### 6. What Gets Removed

- `agents/studio_compositor/spirograph_reactor.py` — orbiting circle renderer
- Spirograph-related imports and initialization in `fx_chain.py`
- Spirograph tick calls in `fx_tick.py` and `fx_chain.py`
- Orbit position tracking, spirograph layout math

### 7. What Stays Unchanged

- Director loop — still cycles YouTube slots, speaks reactions, manages audio via SlotAudioControl
- YouTube player — still runs 3 ffmpeg slots, writes JPEG snapshots to `/dev/shm`
- Audio control (SlotAudioControl) — mutes/unmutes per slot
- Vocabulary shader graph architecture — Sierpinski nodes are additions, pipeline structure unchanged
- Content recruitment — still recruits video content via affordance pipeline
- hapax-imagination binary — renders the shader graph, no Rust changes needed (new WGSL nodes are hot-loaded)
- Effect presets — existing presets continue to work, Sierpinski nodes are additional vocabulary

## File Changes

| File | Action | Summary |
|------|--------|---------|
| `agents/effect_graph/nodes/sierpinski.wgsl` | New | Sierpinski triangle line renderer shader |
| `agents/effect_graph/nodes/video_content.wgsl` | New | Video frame masking + waveform shader |
| `agents/effect_graph/node_types/sierpinski.json` | New | Node type definition (params, defaults) |
| `agents/effect_graph/node_types/video_content.json` | New | Node type definition (params, defaults) |
| `agents/studio_compositor/sierpinski_loader.py` | New | Content loader (replaces spirograph reactor) |
| `agents/studio_compositor/fx_chain.py` | Edit | Replace spirograph init with Sierpinski loader |
| `agents/studio_compositor/fx_tick.py` | Edit | Replace spirograph tick with Sierpinski loader tick |
| `agents/studio_compositor/spirograph_reactor.py` | Delete | Replaced by Sierpinski loader |
| Vocabulary preset JSON | Edit | Update default vocabulary graph to include new nodes |

## Deferred

- **Dynamic Sierpinski placement** — the triangle position/size/rotation changes at runtime. Requires param bridge for position uniforms. Separate spec.
- **Dynamic camera resolution/framerate** — hero mode vs dual mode for OBS compositor. Separate spec (design B).

## Testing

1. Start compositor — verify Sierpinski shader loads without GPU errors
2. YouTube videos render inside triangle corner regions (not black, not full-frame)
3. Waveform renders in center triangle with audio reactivity
4. Director loop slot cycling changes active video opacity
5. Shader params (intensity, spectral_color) modulate triangle line work
6. No regression in existing vocabulary shader effects (rd, color, drift, etc.)
