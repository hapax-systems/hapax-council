# Visual Surface Content Layer — Imagination Fragment Rendering

## Summary

Sub-project 2 of 3. Renders content from imagination bus fragments into the wgpu visual surface. Two resolution paths (Rust fast for camera/file, Python slow for text/qdrant/url) feed a content texture stack that composites between the existing 6-technique compositor and postprocess. Continuation-aware cross-fade between fragments.

## Architecture

### Two Resolution Paths

**Fast path (Rust):** `camera_frame` references read directly from `/dev/shm/hapax-compositor/{role}.jpg`. `file` references read from disk. Decoded to RGBA via the `image` crate, uploaded to GPU texture slots. Sub-millisecond for camera frames.

**Slow path (Python):** A resolver process (`imagination_resolver.py`) watches `/dev/shm/hapax-imagination/current.json`. On new fragment, resolves slow kinds:

| Kind | Resolution | Output |
|------|-----------|--------|
| `text` | Rasterize via Pillow (white on transparent black, monospace, auto-sized) | JPEG |
| `qdrant_query` | Query collection → top result text → rasterize | JPEG |
| `url` | httpx fetch → Pillow decode → resize | JPEG |
| `camera_frame` | SKIP — Rust fast path | — |
| `file` | SKIP — Rust fast path | — |
| `audio_clip` | SKIP — not visual | — |

Resolved images written to `/dev/shm/hapax-imagination/content/{fragment_id}-{index}.jpg`. Directory cleaned on each new fragment before writing new files.

### Content Pass in Compositor Pipeline

```
existing compositor (6 techniques) → CONTENT PASS → postprocess (vignette, sediment) → surface
```

The content pass reads up to 4 content textures and screen-blends them onto the composite output. Content emerges from the procedural field rather than covering it. Postprocess applies uniformly over everything.

### Texture Pool

4 fixed GPU texture slots. Content references map to slots in order. If a fragment carries more than 4 references, lowest-salience references are dropped. In practice, most fragments carry 1-2 references.

Per-slot state tracked in Rust:
- Texture handle (wgpu::Texture + TextureView)
- Current opacity (0.0-1.0, updated per frame)
- Target opacity (set on fragment arrival)
- Fade rate (derived from cadence interval)
- Source identifier (for debugging)

### Blending

Screen blend mode per content texture:
```
blended = 1.0 - (1.0 - composite) * (1.0 - content * opacity)
```

Opacity per texture = `reference.salience * fragment_intensity_dimension * fade_factor`

### Cross-Fade Behavior

Continuation-aware transitions:

**`continuation=true`:** New content cross-fades over old. Old slots fade out while new slots fade in simultaneously. Duration: 2.0 seconds.

**`continuation=false`:** Old content fades out first (1.5s), brief gap of pure procedural (~0.5s), then new content fades in (1.5s). Total transition: 3.5s.

Durations scale proportionally with the imagination cadence interval. At accelerated cadence (4s), transitions compress to 60% of nominal. At base cadence (12s), full duration.

## Python Content Resolver

### Process Identity

Standalone async loop. Can run inside the voice daemon process (alongside DMN and imagination loop) or as a separate service. Watches `/dev/shm/hapax-imagination/current.json` every 500ms.

### Resolution Logic

On detecting a new fragment (fragment ID differs from last-seen):
1. Clean `/dev/shm/hapax-imagination/content/` (delete all files)
2. Filter content references to slow kinds only (text, qdrant_query, url)
3. Resolve each concurrently (asyncio.gather)
4. Write resolved images to `{fragment_id}-{index}.jpg`

### Text Rasterization

Pillow `ImageDraw.text()` with system monospace font. White text on transparent black (RGBA). Font size auto-scaled so text fits within 1920x1080 (or window dimensions from state). Line wrapping at word boundaries. Output as JPEG (opaque black background — transparency not needed since screen blend naturally handles dark backgrounds).

### Qdrant Resolution

Query the specified collection with the reference's `query` field. Take the top result's text content. Rasterize as text (same path as text kind).

### URL Resolution

Fetch with httpx (5s timeout). Decode with Pillow. Resize to fit texture slot dimensions (max 1920x1080, preserve aspect ratio). Output as JPEG.

### Error Handling

Resolution failures are silent — the content slot simply stays empty. Log at debug level. The visual surface continues rendering procedural techniques. No content is better than broken content.

## Rust Integration

### StateReader Extension

`poll_now()` reads `/dev/shm/hapax-imagination/current.json` for fragment metadata (id, continuation, dimensions, content_references). Scans `/dev/shm/hapax-imagination/content/` for resolved JPEG files matching the current fragment ID.

New struct:
```rust
struct ImaginationState {
    fragment_id: String,
    continuation: bool,
    dimensions: HashMap<String, f32>,
    content_slots: Vec<ContentSlot>,
}

struct ContentSlot {
    kind: String,        // "camera_frame", "text", etc.
    source: String,      // camera role, text content, etc.
    image_path: String,  // resolved JPEG path
    salience: f32,
}
```

For fast-path references (camera_frame, file), the StateReader constructs ContentSlots directly from the fragment's content_references with paths to the existing shm files. For slow-path references, it reads whatever the Python resolver has written to the content/ directory.

### Content Layer Module

New file `content_layer.rs`:
- `ContentLayerPipeline` — render pipeline for screen-blending content textures
- `TexturePool` — 4 texture slots with fade state
- `FadeController` — per-slot fade animation (current opacity → target opacity at fade rate)
- `upload_jpeg(device, queue, path) → Option<Texture>` — decode JPEG, create wgpu texture

### Content Layer Shader

New file `content_layer.wgsl`:
```wgsl
// Inputs: composite texture + up to 4 content textures + 4 opacity uniforms
// Output: screen-blended result
// For each active slot: result = 1.0 - (1.0 - result) * (1.0 - content * opacity)
```

### Bridge Changes

`bridge.rs` render loop modified:
1. After `compositor.render()` and before `postprocess.render()`: run content layer pass
2. On each `poll()`: check for new fragment ID, trigger fade transitions
3. For camera_frame references: read JPEG on fast path (every 2nd frame to match existing shm output cadence)
4. For resolved content: read JPEG from content/ directory when file appears

## File Layout

| File | Responsibility |
|------|---------------|
| `agents/imagination_resolver.py` | Python content resolver (watch, resolve text/qdrant/url, write JPEG) |
| `tests/test_imagination_resolver.py` | Unit tests: text rasterization, qdrant resolution mock, URL fetch mock, cleanup, file output |
| `hapax-logos/src-tauri/src/visual/content_layer.rs` | Texture pool, fade controller, content pass render pipeline, JPEG upload |
| `hapax-logos/src-tauri/src/visual/shaders/content_layer.wgsl` | Screen-blend content textures onto composite |
| `hapax-logos/src-tauri/src/visual/state.rs` | Extended: read imagination current.json + scan content/ dir |
| `hapax-logos/src-tauri/src/visual/bridge.rs` | Extended: wire content pass, manage fade transitions |
| `hapax-logos/src-tauri/src/visual/mod.rs` | Extended: add content_layer module |

## Dependencies

- **Python:** Pillow (already available via system packages), httpx (already a dependency), Qdrant client (from shared/config)
- **Rust:** `image` crate for JPEG decoding (check Cargo.toml, add if needed)

## Dimensional Modulation of Content Geometry

Content has no fixed geometric constraints — no locked positions, no fixed scales, no prescribed regions. Instead, the same 9 expressive dimensions that modulate the procedural techniques and the vocal chain modulate how content appears spatially. Content obeys the same expressive physics as the rest of the visual field.

### Dimension → Spatial Mapping

| Dimension | Spatial Effect on Content |
|-----------|-------------------------|
| **intensity** | Scale + opacity. Higher intensity = larger, more opaque presence. |
| **tension** | Edge sharpness. Higher tension = crisper borders. Lower = softer feather. |
| **diffusion** | Spatial scatter. Higher diffusion = content fragments into multiple smaller instances, spread across the field. |
| **degradation** | Noise/distortion applied to content texture. Pixel displacement, scanline artifacts. |
| **depth** | Recession. Higher depth = content shrinks, moves toward periphery, darkens. |
| **pitch_displacement** | Spatial drift. Content position shifts/rotates over time. Higher = more displacement from center. |
| **temporal_distortion** | Animation speed of drift/breathing. Can freeze (low) or accelerate (high). |
| **spectral_color** | Color treatment applied to content (warmth/chroma shift, same as gradient). |
| **coherence** | Structural integrity. Low coherence = content breaks apart, dissolves into procedural field. High = recognizable, intact. |

### Implementation

The content_layer.wgsl shader receives the 9 dimension values as uniforms. Each content texture's UV coordinates, opacity, edge feathering, and color treatment are computed per-pixel from these dimensions. No fixed layout — the shader generates all spatial properties procedurally from the dimensional state.

Base behavior (all dimensions at 0.0): content appears centered at moderate scale (~40% of frame), fully feathered edges, static, at natural color. As dimensions activate, the appearance departs from this neutral state.

### Cloud/Field Aesthetic

The result is that content appears as a field phenomenon, not a UI element. A camera frame doesn't pop up in a rectangle — it materializes through the procedural texture, its edges dissolving into the RD patterns, its position drifting with the wave modulation, its scale breathing with the ambient speed. Text doesn't render in a box — it emerges from the gradient field, its letterforms blending with voronoi cell boundaries at low coherence.

## Reflective Feedback — Surface Field Perception

### General Principle

A surface is not the system's output — it is the complete perceptual field in a modality. The visual surface is the full rendered frame (procedural + content + postprocess). The audio surface is the full audio environment (system TTS + MIDI effects reflected through the room + operator voice + ambient sound + music). Every expressive surface produces a field artifact that feeds back to the DMN as a sensor source.

This principle applies uniformly across modalities. The DMN sensor module provides a generic `read_surface_output(surface_name)` pattern. Each surface writes its field capture to its shm directory. The DMN perceives the field, not the system's contribution to it.

### Visual Field

The visual surface already writes the complete rendered frame to `/dev/shm/hapax-visual/frame.jpg` via ShmOutput. This IS the visual field — all procedural techniques + content textures + dimensional coloring + postprocess composited together.

The DMN's evaluative tick reads this frame periodically (~30s) and passes it as multimodal input to a vision-capable model (gemini-flash via LiteLLM). The model describes what it sees, and that description enters the observation buffer alongside sensor data. The DMN can be surprised by what the rendered combination looks like — juxtapositions, emergent patterns, aesthetic qualities not predicted by the fragment's narrative.

### Sensor Integration

```python
"surfaces": {
    "visual": {
        "frame_path": "/dev/shm/hapax-visual/frame.jpg",
        "frame_age_s": 0.5,
        "imagination_fragment_id": "abc123",
    },
}
```

The evaluative tick includes surface field data when imagination is active (fragment_id is non-null).

## Testing

### Python
- Text rasterization: produces JPEG of expected dimensions with non-zero content
- Qdrant resolution: mock Qdrant client, verify text rasterization of result
- URL resolution: mock httpx, verify image decode and resize
- Cleanup: old fragment files deleted before new ones written
- Fragment filtering: only slow kinds passed to resolver, fast kinds skipped

### Rust
- Compilation check: content_layer.rs compiles, wgsl shader compiles
- Texture pool: slots track state correctly (active/inactive, opacity targets)
- Fade controller: opacity transitions at correct rate, handles continuation vs non-continuation
- JPEG upload: valid JPEG produces texture, missing/corrupt file returns None
- Integration: content pass runs in pipeline without errors (visual verification)
