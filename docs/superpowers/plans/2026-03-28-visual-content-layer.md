# Visual Content Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render imagination bus content fragments into the wgpu visual surface — content textures screen-blended between compositor and postprocess, with 9-dimensional spatial modulation and continuation-aware cross-fade.

**Architecture:** Python resolver writes resolved images to shm. Rust content layer reads images, uploads to GPU texture pool (4 slots), screen-blends onto composite via content_layer.wgsl shader driven by 9 expressive dimension uniforms. DMN evaluative tick gains visual surface feedback via multimodal LLM.

**Tech Stack:** Python (Pillow, httpx, Qdrant), Rust (wgpu, turbojpeg, serde_json), WGSL shaders

---

## File Structure

| File | Responsibility |
|------|---------------|
| `agents/imagination_resolver.py` | Python content resolver: watch current.json, resolve text/qdrant/url to JPEG |
| `tests/test_imagination_resolver.py` | Tests for resolution, file output, cleanup |
| `hapax-logos/src-tauri/src/visual/content_layer.rs` | Texture pool (4 slots), fade controller, JPEG decode+upload, content pass render pipeline |
| `hapax-logos/src-tauri/src/visual/shaders/content_layer.wgsl` | Screen-blend content textures with 9-dimensional spatial modulation |
| `hapax-logos/src-tauri/src/visual/state.rs` | Extended: read imagination current.json + scan content/ dir |
| `hapax-logos/src-tauri/src/visual/bridge.rs` | Extended: wire content pass between compositor and postprocess |
| `hapax-logos/src-tauri/src/visual/mod.rs` | Extended: add content_layer module |
| `agents/dmn/sensor.py` | Extended: read_visual_surface() sensor source |

---

### Task 1: Python Content Resolver — Text and File Resolution

**Files:**
- Create: `agents/imagination_resolver.py`
- Create: `tests/test_imagination_resolver.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_imagination_resolver.py
"""Tests for imagination content resolver."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agents.imagination import ContentReference, ImaginationFragment
from agents.imagination_resolver import (
    resolve_text,
    resolve_references,
    cleanup_content_dir,
)


def _make_fragment(refs: list[ContentReference], fid: str = "test123") -> ImaginationFragment:
    return ImaginationFragment(
        id=fid,
        content_references=refs,
        dimensions={"intensity": 0.5},
        salience=0.3,
        continuation=False,
        narrative="test thought",
    )


def test_resolve_text_creates_jpeg(tmp_path: Path):
    ref = ContentReference(kind="text", source="Hello world", query=None, salience=0.5)
    result = resolve_text(ref, tmp_path, "frag1", 0)
    assert result is not None
    assert result.exists()
    assert result.name == "frag1-0.jpg"
    assert result.stat().st_size > 100  # non-trivial JPEG


def test_resolve_text_multiline(tmp_path: Path):
    ref = ContentReference(
        kind="text",
        source="Line one\nLine two\nLine three",
        query=None,
        salience=0.5,
    )
    result = resolve_text(ref, tmp_path, "frag2", 0)
    assert result is not None
    assert result.exists()


def test_cleanup_removes_old_files(tmp_path: Path):
    # Create some old files
    (tmp_path / "old1-0.jpg").write_bytes(b"\xff\xd8fake")
    (tmp_path / "old1-1.jpg").write_bytes(b"\xff\xd8fake")
    assert len(list(tmp_path.glob("*.jpg"))) == 2

    cleanup_content_dir(tmp_path)
    assert len(list(tmp_path.glob("*.jpg"))) == 0


def test_resolve_references_skips_fast_kinds(tmp_path: Path):
    refs = [
        ContentReference(kind="camera_frame", source="overhead", query=None, salience=0.8),
        ContentReference(kind="file", source="/some/path.jpg", query=None, salience=0.5),
        ContentReference(kind="text", source="hello", query=None, salience=0.3),
    ]
    frag = _make_fragment(refs)
    results = resolve_references(frag, tmp_path)
    # Only text should be resolved (camera_frame and file are Rust fast-path)
    assert len(results) == 1
    assert results[0].name == "test123-2.jpg"  # index 2 = the text ref
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_imagination_resolver.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the resolver**

```python
# agents/imagination_resolver.py
"""Imagination content resolver — resolves slow content references to JPEG images.

Watches /dev/shm/hapax-imagination/current.json for new fragments.
Resolves text, qdrant_query, and url references to JPEG files in
/dev/shm/hapax-imagination/content/ for the Rust visual surface to read.

camera_frame and file references are resolved by the Rust fast path.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from agents.imagination import ContentReference, ImaginationFragment

log = logging.getLogger("imagination.resolver")

CONTENT_DIR = Path("/dev/shm/hapax-imagination/content")
RENDER_WIDTH = 1920
RENDER_HEIGHT = 1080

# Kinds resolved by Python (slow path)
SLOW_KINDS = {"text", "qdrant_query", "url"}


def cleanup_content_dir(content_dir: Path | None = None) -> None:
    """Remove all resolved content files."""
    d = content_dir or CONTENT_DIR
    if d.exists():
        for f in d.glob("*.jpg"):
            f.unlink(missing_ok=True)


def resolve_text(
    ref: ContentReference,
    content_dir: Path | None = None,
    fragment_id: str = "unknown",
    index: int = 0,
) -> Path | None:
    """Rasterize text to a JPEG image."""
    d = content_dir or CONTENT_DIR
    d.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGB", (RENDER_WIDTH, RENDER_HEIGHT), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    text = ref.source
    try:
        font = ImageFont.truetype("/usr/share/fonts/TTF/JetBrainsMono-Regular.ttf", 48)
    except (OSError, IOError):
        font = ImageFont.load_default(size=36)

    # Word-wrap and center
    max_chars = RENDER_WIDTH // 30  # approximate chars per line at font size
    lines = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        current_line = ""
        for word in words:
            test = f"{current_line} {word}".strip()
            if len(test) > max_chars:
                if current_line:
                    lines.append(current_line)
                current_line = word
            else:
                current_line = test
        if current_line:
            lines.append(current_line)

    line_height = 60
    total_height = len(lines) * line_height
    y_start = (RENDER_HEIGHT - total_height) // 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        x = (RENDER_WIDTH - text_width) // 2
        y = y_start + i * line_height
        draw.text((x, y), line, fill=(255, 255, 255), font=font)

    out_path = d / f"{fragment_id}-{index}.jpg"
    img.save(out_path, "JPEG", quality=85)
    return out_path


def resolve_references(
    fragment: ImaginationFragment,
    content_dir: Path | None = None,
) -> list[Path]:
    """Resolve slow content references to JPEG files. Returns list of written paths."""
    d = content_dir or CONTENT_DIR
    results = []

    for i, ref in enumerate(fragment.content_references):
        if ref.kind not in SLOW_KINDS:
            continue

        path = None
        if ref.kind == "text":
            path = resolve_text(ref, d, fragment.id, i)
        elif ref.kind == "qdrant_query":
            path = _resolve_qdrant(ref, d, fragment.id, i)
        elif ref.kind == "url":
            path = _resolve_url(ref, d, fragment.id, i)

        if path is not None:
            results.append(path)

    return results


def _resolve_qdrant(
    ref: ContentReference,
    content_dir: Path,
    fragment_id: str,
    index: int,
) -> Path | None:
    """Query Qdrant, take top result text, rasterize."""
    try:
        from shared.config import get_qdrant_client, embed_text

        client = get_qdrant_client()
        vector = embed_text(ref.query or ref.source)
        results = client.query_points(
            collection_name=ref.source,
            query=vector,
            limit=1,
        )
        if results.points:
            text = results.points[0].payload.get("text", str(results.points[0].payload))
            text_ref = ContentReference(kind="text", source=text, query=None, salience=ref.salience)
            return resolve_text(text_ref, content_dir, fragment_id, index)
    except Exception as exc:
        log.debug("Qdrant resolution failed for %s: %s", ref.source, exc)
    return None


def _resolve_url(
    ref: ContentReference,
    content_dir: Path,
    fragment_id: str,
    index: int,
) -> Path | None:
    """Fetch image from URL, resize, save as JPEG."""
    try:
        import httpx

        resp = httpx.get(ref.source, timeout=5.0, follow_redirects=True)
        resp.raise_for_status()

        from io import BytesIO

        img = Image.open(BytesIO(resp.content))
        img.thumbnail((RENDER_WIDTH, RENDER_HEIGHT), Image.Resampling.LANCZOS)

        # Paste onto black background at center
        bg = Image.new("RGB", (RENDER_WIDTH, RENDER_HEIGHT), (0, 0, 0))
        offset = ((RENDER_WIDTH - img.width) // 2, (RENDER_HEIGHT - img.height) // 2)
        bg.paste(img, offset)

        out_path = content_dir / f"{fragment_id}-{index}.jpg"
        bg.save(out_path, "JPEG", quality=85)
        return out_path
    except Exception as exc:
        log.debug("URL resolution failed for %s: %s", ref.source, exc)
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_imagination_resolver.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add agents/imagination_resolver.py tests/test_imagination_resolver.py
git commit -m "feat(imagination): content resolver — text rasterization, qdrant, URL fetch"
```

---

### Task 2: DMN Reflective Feedback Sensor

**Files:**
- Modify: `agents/dmn/sensor.py`
- Modify: `tests/test_imagination_resolver.py` (add sensor test)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_imagination_resolver.py`:

```python
from agents.dmn.sensor import read_visual_surface


def test_read_visual_surface_missing():
    result = read_visual_surface()
    # Returns dict even when files are missing
    assert result["source"] == "visual_surface"
    assert result["stale"] is True


def test_read_visual_surface_with_frame(tmp_path: Path):
    # Create a fake frame file
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"\xff\xd8\xff\xe0fake jpeg")

    # Create a fake imagination current.json
    current = tmp_path / "current.json"
    current.write_text(json.dumps({"id": "abc123", "timestamp": 0.0}))

    result = read_visual_surface(
        frame_path=frame,
        imagination_path=current,
    )
    assert result["source"] == "visual_surface"
    assert result["frame_path"] == str(frame)
    assert result["imagination_fragment_id"] == "abc123"
    assert result["stale"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_imagination_resolver.py::test_read_visual_surface_missing -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Add read_visual_surface to sensor.py**

Add to `agents/dmn/sensor.py` after `read_watch()`:

```python
VISUAL_SURFACE_FRAME = Path("/dev/shm/hapax-visual/frame.jpg")
IMAGINATION_CURRENT = Path("/dev/shm/hapax-imagination/current.json")


def read_visual_surface(
    frame_path: Path | None = None,
    imagination_path: Path | None = None,
) -> dict:
    """Read visual surface state — rendered frame + active imagination fragment."""
    fp = frame_path or VISUAL_SURFACE_FRAME
    ip = imagination_path or IMAGINATION_CURRENT

    frame_age = _age_s(fp)
    imagination_data = _read_json(ip) or {}

    return {
        "source": "visual_surface",
        "age_s": round(frame_age, 1),
        "stale": frame_age > STALE_THRESHOLD_S,
        "frame_path": str(fp) if fp.exists() else None,
        "imagination_fragment_id": imagination_data.get("id"),
    }
```

Then add it to `read_all()`:

```python
def read_all() -> dict:
    """Read all sensor sources. Returns a unified snapshot."""
    return {
        "timestamp": time.time(),
        "perception": read_perception(),
        "stimmung": read_stimmung(),
        "fortress": read_fortress(),
        "watch": read_watch(),
        "visual_surface": read_visual_surface(),
        "sensors": read_sensors(),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_imagination_resolver.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add agents/dmn/sensor.py tests/test_imagination_resolver.py
git commit -m "feat(dmn): visual surface sensor — frame path + imagination fragment ID for reflective feedback"
```

---

### Task 3: Rust Content Layer — Texture Pool and JPEG Decode

**Files:**
- Create: `hapax-logos/src-tauri/src/visual/content_layer.rs`
- Modify: `hapax-logos/src-tauri/src/visual/mod.rs`

- [ ] **Step 1: Create the content_layer module**

```rust
// hapax-logos/src-tauri/src/visual/content_layer.rs
//! Content layer: renders imagination content textures between compositor and postprocess.
//!
//! 4 texture slots, screen-blend onto composite, 9-dimensional spatial modulation.

use std::collections::HashMap;
use std::path::Path;

use bytemuck::{Pod, Zeroable};
use wgpu::util::DeviceExt;

use super::compositor::COMPOSITE_FORMAT;
use super::gpu::GpuContext;

/// Maximum content texture slots.
pub const MAX_SLOTS: usize = 4;

/// Per-slot fade state.
#[derive(Debug, Clone)]
pub struct SlotState {
    pub active: bool,
    pub opacity: f32,
    pub target_opacity: f32,
    pub fade_rate: f32, // per second
    pub source: String,
}

impl Default for SlotState {
    fn default() -> Self {
        Self {
            active: false,
            opacity: 0.0,
            target_opacity: 0.0,
            fade_rate: 0.5,
            source: String::new(),
        }
    }
}

impl SlotState {
    /// Advance fade animation by dt seconds.
    pub fn tick(&mut self, dt: f32) {
        if (self.opacity - self.target_opacity).abs() < 0.001 {
            self.opacity = self.target_opacity;
            if self.opacity == 0.0 {
                self.active = false;
            }
            return;
        }
        let direction = if self.target_opacity > self.opacity { 1.0 } else { -1.0 };
        self.opacity += direction * self.fade_rate * dt;
        self.opacity = self.opacity.clamp(0.0, 1.0);
    }
}

/// Uniforms for the content layer shader.
#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
pub struct ContentUniforms {
    // Per-slot opacities (after fade + salience + intensity)
    pub slot_opacities: [f32; 4],
    // 9 expressive dimensions for spatial modulation
    pub intensity: f32,
    pub tension: f32,
    pub diffusion: f32,
    pub degradation: f32,
    pub depth: f32,
    pub pitch_displacement: f32,
    pub temporal_distortion: f32,
    pub spectral_color: f32,
    pub coherence: f32,
    pub time: f32,
    pub _pad0: f32,
    pub _pad1: f32,
}

impl Default for ContentUniforms {
    fn default() -> Self {
        Self {
            slot_opacities: [0.0; 4],
            intensity: 0.0,
            tension: 0.0,
            diffusion: 0.0,
            degradation: 0.0,
            depth: 0.0,
            pitch_displacement: 0.0,
            temporal_distortion: 0.0,
            spectral_color: 0.0,
            coherence: 0.0,
            time: 0.0,
            _pad0: 0.0,
            _pad1: 0.0,
        }
    }
}

/// Decode a JPEG file to RGBA pixels using turbojpeg.
pub fn decode_jpeg_to_rgba(path: &Path) -> Option<(Vec<u8>, u32, u32)> {
    let jpeg_data = std::fs::read(path).ok()?;
    let decompressor = turbojpeg::Decompressor::new().ok()?;
    let header = decompressor.read_header(&jpeg_data).ok()?;
    let width = header.width as u32;
    let height = header.height as u32;

    let mut rgba = vec![0u8; (width * height * 4) as usize];
    let image = turbojpeg::Image {
        pixels: rgba.as_mut_slice(),
        width: width as usize,
        pitch: (width * 4) as usize,
        height: height as usize,
        format: turbojpeg::PixelFormat::RGBA,
    };
    decompressor.decompress(&jpeg_data, image).ok()?;
    Some((rgba, width, height))
}

pub struct ContentLayer {
    pipeline: wgpu::RenderPipeline,
    uniform_buf: wgpu::Buffer,
    bind_group_layout: wgpu::BindGroupLayout,
    sampler: wgpu::Sampler,
    /// 4 content texture slots
    pub slots: [SlotState; MAX_SLOTS],
    textures: [Option<wgpu::Texture>; MAX_SLOTS],
    views: [Option<wgpu::TextureView>; MAX_SLOTS],
    /// Placeholder 1x1 black texture for inactive slots
    placeholder_view: wgpu::TextureView,
    width: u32,
    height: u32,
    /// Current fragment ID (for detecting new fragments)
    pub current_fragment_id: String,
    /// Continuation state for cross-fade behavior
    pub is_continuation: bool,
}

impl ContentLayer {
    pub fn new(gpu: &GpuContext, width: u32, height: u32) -> Self {
        let shader = gpu.device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("content_layer.wgsl"),
            source: wgpu::ShaderSource::Wgsl(include_str!("shaders/content_layer.wgsl").into()),
        });

        let uniform_buf = gpu.device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("content uniforms"),
            contents: bytemuck::bytes_of(&ContentUniforms::default()),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });

        let sampler = gpu.device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("content sampler"),
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            ..Default::default()
        });

        let bind_group_layout = gpu.device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("content bgl"),
            entries: &[
                // Uniforms
                wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
                // Composite input
                bgl_texture(1),
                // Content slot 0-3
                bgl_texture(2),
                bgl_texture(3),
                bgl_texture(4),
                bgl_texture(5),
                // Sampler
                wgpu::BindGroupLayoutEntry {
                    binding: 6,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                    count: None,
                },
            ],
        });

        let pipeline_layout = gpu.device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("content pl"),
            bind_group_layouts: &[&bind_group_layout],
            push_constant_ranges: &[],
        });

        let pipeline = gpu.device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("content pipeline"),
            layout: Some(&pipeline_layout),
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: Some("vs_main"),
                buffers: &[],
                compilation_options: Default::default(),
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: Some("fs_main"),
                targets: &[Some(wgpu::ColorTargetState {
                    format: COMPOSITE_FORMAT,
                    blend: Some(wgpu::BlendState::REPLACE),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
                compilation_options: Default::default(),
            }),
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::TriangleList,
                ..Default::default()
            },
            depth_stencil: None,
            multisample: wgpu::MultisampleState::default(),
            multiview: None,
            cache: None,
        });

        // Create 1x1 black placeholder
        let placeholder = gpu.device.create_texture(&wgpu::TextureDescriptor {
            label: Some("content placeholder"),
            size: wgpu::Extent3d { width: 1, height: 1, depth_or_array_layers: 1 },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: COMPOSITE_FORMAT,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });
        gpu.queue.write_texture(
            wgpu::TexelCopyTextureInfo { texture: &placeholder, mip_level: 0, origin: wgpu::Origin3d::ZERO, aspect: wgpu::TextureAspect::All },
            &[0u8; 4],
            wgpu::TexelCopyBufferLayout { offset: 0, bytes_per_row: Some(4), rows_per_image: Some(1) },
            wgpu::Extent3d { width: 1, height: 1, depth_or_array_layers: 1 },
        );
        let placeholder_view = placeholder.create_view(&Default::default());

        Self {
            pipeline,
            uniform_buf,
            bind_group_layout,
            sampler,
            slots: Default::default(),
            textures: [None, None, None, None],
            views: [None, None, None, None],
            placeholder_view,
            width,
            height,
            current_fragment_id: String::new(),
            is_continuation: false,
        }
    }

    /// Upload JPEG image data to a texture slot.
    pub fn upload_to_slot(&mut self, gpu: &GpuContext, slot: usize, path: &Path, salience: f32, source: &str) {
        if slot >= MAX_SLOTS {
            return;
        }
        let Some((rgba, w, h)) = decode_jpeg_to_rgba(path) else { return };

        let texture = gpu.device.create_texture(&wgpu::TextureDescriptor {
            label: Some(&format!("content slot {}", slot)),
            size: wgpu::Extent3d { width: w, height: h, depth_or_array_layers: 1 },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: COMPOSITE_FORMAT,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });
        gpu.queue.write_texture(
            wgpu::TexelCopyTextureInfo { texture: &texture, mip_level: 0, origin: wgpu::Origin3d::ZERO, aspect: wgpu::TextureAspect::All },
            &rgba,
            wgpu::TexelCopyBufferLayout { offset: 0, bytes_per_row: Some(w * 4), rows_per_image: Some(h) },
            wgpu::Extent3d { width: w, height: h, depth_or_array_layers: 1 },
        );

        let view = texture.create_view(&Default::default());
        self.textures[slot] = Some(texture);
        self.views[slot] = Some(view);
        self.slots[slot].active = true;
        self.slots[slot].target_opacity = salience;
        self.slots[slot].source = source.to_string();
    }

    /// Start fade-out on all active slots.
    pub fn fade_out_all(&mut self) {
        for slot in &mut self.slots {
            if slot.active {
                slot.target_opacity = 0.0;
            }
        }
    }

    /// Tick fade animations for all slots.
    pub fn tick_fades(&mut self, dt: f32) {
        for slot in &mut self.slots {
            slot.tick(dt);
        }
    }

    /// Update uniforms from dimensional state.
    pub fn update_uniforms(&self, queue: &wgpu::Queue, dimensions: &HashMap<String, f32>, time: f32) {
        let get = |k: &str| *dimensions.get(k).unwrap_or(&0.0);
        let uniforms = ContentUniforms {
            slot_opacities: [
                self.slots[0].opacity,
                self.slots[1].opacity,
                self.slots[2].opacity,
                self.slots[3].opacity,
            ],
            intensity: get("intensity"),
            tension: get("tension"),
            diffusion: get("diffusion"),
            degradation: get("degradation"),
            depth: get("depth"),
            pitch_displacement: get("pitch_displacement"),
            temporal_distortion: get("temporal_distortion"),
            spectral_color: get("spectral_color"),
            coherence: get("coherence"),
            time,
            _pad0: 0.0,
            _pad1: 0.0,
        };
        queue.write_buffer(&self.uniform_buf, 0, bytemuck::bytes_of(&uniforms));
    }

    /// Render content layer onto the composite texture.
    pub fn render(
        &self,
        encoder: &mut wgpu::CommandEncoder,
        composite_view: &wgpu::TextureView,
        device: &wgpu::Device,
    ) {
        // Skip if nothing active
        if !self.slots.iter().any(|s| s.active && s.opacity > 0.001) {
            return;
        }

        let slot_view = |i: usize| -> &wgpu::TextureView {
            self.views[i].as_ref().unwrap_or(&self.placeholder_view)
        };

        let bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("content bg"),
            layout: &self.bind_group_layout,
            entries: &[
                wgpu::BindGroupEntry { binding: 0, resource: self.uniform_buf.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 1, resource: wgpu::BindingResource::TextureView(composite_view) },
                wgpu::BindGroupEntry { binding: 2, resource: wgpu::BindingResource::TextureView(slot_view(0)) },
                wgpu::BindGroupEntry { binding: 3, resource: wgpu::BindingResource::TextureView(slot_view(1)) },
                wgpu::BindGroupEntry { binding: 4, resource: wgpu::BindingResource::TextureView(slot_view(2)) },
                wgpu::BindGroupEntry { binding: 5, resource: wgpu::BindingResource::TextureView(slot_view(3)) },
                wgpu::BindGroupEntry { binding: 6, resource: wgpu::BindingResource::Sampler(&self.sampler) },
            ],
        });

        let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("content pass"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: composite_view,
                resolve_target: None,
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Load, // preserve compositor output
                    store: wgpu::StoreOp::Store,
                },
            })],
            depth_stencil_attachment: None,
            ..Default::default()
        });
        pass.set_pipeline(&self.pipeline);
        pass.set_bind_group(0, &bg, &[]);
        pass.draw(0..3, 0..1);
    }

    pub fn resize(&mut self, _device: &wgpu::Device, width: u32, height: u32) {
        self.width = width;
        self.height = height;
    }
}

fn bgl_texture(binding: u32) -> wgpu::BindGroupLayoutEntry {
    wgpu::BindGroupLayoutEntry {
        binding,
        visibility: wgpu::ShaderStages::FRAGMENT,
        ty: wgpu::BindingType::Texture {
            sample_type: wgpu::TextureSampleType::Float { filterable: true },
            view_dimension: wgpu::TextureViewDimension::D2,
            multisampled: false,
        },
        count: None,
    }
}
```

- [ ] **Step 2: Add module to mod.rs**

Add to `hapax-logos/src-tauri/src/visual/mod.rs`:

```rust
pub mod content_layer;
```

- [ ] **Step 3: Verify compilation**

Run: `cd ~/projects/hapax-council--beta/hapax-logos && cargo check --manifest-path src-tauri/Cargo.toml 2>&1 | grep -E "error" | head -5`

Note: This will fail because `content_layer.wgsl` doesn't exist yet. Create a minimal placeholder:

```wgsl
// hapax-logos/src-tauri/src/visual/shaders/content_layer.wgsl
// Placeholder — full shader in Task 4

struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
}

@vertex
fn vs_main(@builtin(vertex_index) idx: u32) -> VertexOutput {
    var out: VertexOutput;
    let x = f32(i32(idx & 1u)) * 4.0 - 1.0;
    let y = f32(i32(idx >> 1u)) * 4.0 - 1.0;
    out.position = vec4<f32>(x, y, 0.0, 1.0);
    out.uv = vec2<f32>((x + 1.0) * 0.5, (1.0 - y) * 0.5);
    return out;
}

struct ContentUniforms {
    slot_opacities: vec4<f32>,
    intensity: f32,
    tension: f32,
    diffusion: f32,
    degradation: f32,
    depth: f32,
    pitch_displacement: f32,
    temporal_distortion: f32,
    spectral_color: f32,
    coherence: f32,
    time: f32,
    _pad0: f32,
    _pad1: f32,
}

@group(0) @binding(0) var<uniform> u: ContentUniforms;
@group(0) @binding(1) var tex_composite: texture_2d<f32>;
@group(0) @binding(2) var tex_slot0: texture_2d<f32>;
@group(0) @binding(3) var tex_slot1: texture_2d<f32>;
@group(0) @binding(4) var tex_slot2: texture_2d<f32>;
@group(0) @binding(5) var tex_slot3: texture_2d<f32>;
@group(0) @binding(6) var samp: sampler;

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    let composite = textureSample(tex_composite, samp, in.uv);
    return composite; // passthrough for now
}
```

- [ ] **Step 4: Verify compilation**

Run: `cd ~/projects/hapax-council--beta/hapax-logos && cargo clean -p hapax-logos --manifest-path src-tauri/Cargo.toml && cargo check --manifest-path src-tauri/Cargo.toml`
Expected: compiles with warnings only

- [ ] **Step 5: Commit**

```bash
git add hapax-logos/src-tauri/src/visual/content_layer.rs hapax-logos/src-tauri/src/visual/mod.rs hapax-logos/src-tauri/src/visual/shaders/content_layer.wgsl
git commit -m "feat(visual): content layer — texture pool, JPEG decode, fade controller, render pipeline"
```

---

### Task 4: Content Layer Shader — 9-Dimensional Spatial Modulation

**Files:**
- Modify: `hapax-logos/src-tauri/src/visual/shaders/content_layer.wgsl`

- [ ] **Step 1: Write the full content layer shader**

Replace the placeholder `content_layer.wgsl` with:

```wgsl
// Content layer: screen-blend up to 4 content textures onto composite
// with 9-dimensional spatial modulation (cloud/field aesthetic)

struct ContentUniforms {
    slot_opacities: vec4<f32>,
    intensity: f32,
    tension: f32,
    diffusion: f32,
    degradation: f32,
    depth: f32,
    pitch_displacement: f32,
    temporal_distortion: f32,
    spectral_color: f32,
    coherence: f32,
    time: f32,
    _pad0: f32,
    _pad1: f32,
}

@group(0) @binding(0) var<uniform> u: ContentUniforms;
@group(0) @binding(1) var tex_composite: texture_2d<f32>;
@group(0) @binding(2) var tex_slot0: texture_2d<f32>;
@group(0) @binding(3) var tex_slot1: texture_2d<f32>;
@group(0) @binding(4) var tex_slot2: texture_2d<f32>;
@group(0) @binding(5) var tex_slot3: texture_2d<f32>;
@group(0) @binding(6) var samp: sampler;

struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
}

@vertex
fn vs_main(@builtin(vertex_index) idx: u32) -> VertexOutput {
    var out: VertexOutput;
    let x = f32(i32(idx & 1u)) * 4.0 - 1.0;
    let y = f32(i32(idx >> 1u)) * 4.0 - 1.0;
    out.position = vec4<f32>(x, y, 0.0, 1.0);
    out.uv = vec2<f32>((x + 1.0) * 0.5, (1.0 - y) * 0.5);
    return out;
}

// Simple hash for spatial noise
fn hash21(p: vec2<f32>) -> f32 {
    return fract(sin(dot(p, vec2<f32>(127.1, 311.7))) * 43758.5453);
}

// Compute modulated UV for a content slot
fn modulate_uv(uv: vec2<f32>, slot_index: f32) -> vec2<f32> {
    var muv = uv;

    // Intensity → scale (higher = larger, closer to edges of frame)
    let scale = mix(0.4, 1.0, u.intensity);
    muv = (muv - 0.5) / scale + 0.5;

    // Depth → recession (shrink toward periphery)
    let depth_scale = mix(1.0, 0.5, u.depth);
    let depth_offset = u.depth * 0.15;
    muv = (muv - 0.5) * depth_scale + 0.5 + vec2<f32>(depth_offset, depth_offset * 0.7);

    // Pitch displacement → spatial drift
    let drift_speed = mix(0.0, 0.3, u.pitch_displacement);
    let phase = u.time * drift_speed + slot_index * 1.5;
    muv += vec2<f32>(sin(phase) * 0.05, cos(phase * 0.7) * 0.03) * u.pitch_displacement;

    // Temporal distortion → breathing (scale oscillation)
    let breath_speed = mix(0.5, 3.0, u.temporal_distortion);
    let breath = 1.0 + sin(u.time * breath_speed) * 0.02 * u.temporal_distortion;
    muv = (muv - 0.5) * breath + 0.5;

    return muv;
}

// Compute per-pixel opacity for a content slot (edge feathering + coherence)
fn content_opacity(uv: vec2<f32>, muv: vec2<f32>, base_opacity: f32) -> f32 {
    // Out-of-bounds check
    if muv.x < 0.0 || muv.x > 1.0 || muv.y < 0.0 || muv.y > 1.0 {
        return 0.0;
    }

    var opacity = base_opacity;

    // Tension → edge sharpness (low tension = wide feather, high = crisp)
    let feather_width = mix(0.25, 0.02, u.tension);
    let edge_dist = min(min(muv.x, 1.0 - muv.x), min(muv.y, 1.0 - muv.y));
    let edge_fade = smoothstep(0.0, feather_width, edge_dist);
    opacity *= edge_fade;

    // Coherence → structural dissolution (low coherence = noisy holes)
    let dissolution = 1.0 - u.coherence;
    if dissolution > 0.1 {
        let noise = hash21(uv * 50.0 + u.time * 0.1);
        let threshold = dissolution * 0.8;
        opacity *= smoothstep(threshold - 0.1, threshold + 0.1, noise);
    }

    // Depth → darken
    opacity *= mix(1.0, 0.4, u.depth);

    return opacity;
}

// Apply per-pixel color modulation
fn modulate_color(color: vec3<f32>, uv: vec2<f32>) -> vec3<f32> {
    var c = color;

    // Spectral color → warmth/chroma shift
    let warmth = u.spectral_color;
    c = mix(c, c * vec3<f32>(1.1, 0.95, 0.85), warmth);

    // Degradation → noise/distortion
    if u.degradation > 0.1 {
        let noise = hash21(uv * 100.0 + u.time * 0.5);
        let glitch = step(1.0 - u.degradation * 0.3, noise);
        c = mix(c, vec3<f32>(noise * 0.5, noise * 0.3, noise * 0.7), glitch * 0.5);
    }

    return c;
}

// Screen blend: result = 1 - (1 - base) * (1 - layer)
fn blend_screen(base: vec3<f32>, layer: vec3<f32>) -> vec3<f32> {
    return 1.0 - (1.0 - base) * (1.0 - layer);
}

fn sample_slot(tex: texture_2d<f32>, uv: vec2<f32>, muv: vec2<f32>, base_opacity: f32) -> vec4<f32> {
    let opacity = content_opacity(uv, muv, base_opacity);
    if opacity < 0.001 {
        return vec4<f32>(0.0);
    }
    let color = textureSample(tex, samp, muv).rgb;
    let modulated = modulate_color(color, uv);
    return vec4<f32>(modulated, opacity);
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    let uv = in.uv;
    var color = textureSample(tex_composite, samp, uv).rgb;

    // Slot 0
    if u.slot_opacities.x > 0.001 {
        let muv = modulate_uv(uv, 0.0);
        let s = sample_slot(tex_slot0, uv, muv, u.slot_opacities.x);
        color = mix(color, blend_screen(color, s.rgb), s.a);
    }

    // Slot 1
    if u.slot_opacities.y > 0.001 {
        let muv = modulate_uv(uv, 1.0);
        let s = sample_slot(tex_slot1, uv, muv, u.slot_opacities.y);
        color = mix(color, blend_screen(color, s.rgb), s.a);
    }

    // Slot 2
    if u.slot_opacities.z > 0.001 {
        let muv = modulate_uv(uv, 2.0);
        let s = sample_slot(tex_slot2, uv, muv, u.slot_opacities.z);
        color = mix(color, blend_screen(color, s.rgb), s.a);
    }

    // Slot 3
    if u.slot_opacities.w > 0.001 {
        let muv = modulate_uv(uv, 3.0);
        let s = sample_slot(tex_slot3, uv, muv, u.slot_opacities.w);
        color = mix(color, blend_screen(color, s.rgb), s.a);
    }

    return vec4<f32>(color, 1.0);
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd ~/projects/hapax-council--beta/hapax-logos && cargo clean -p hapax-logos --manifest-path src-tauri/Cargo.toml && cargo check --manifest-path src-tauri/Cargo.toml`
Expected: compiles with warnings only

- [ ] **Step 3: Commit**

```bash
git add hapax-logos/src-tauri/src/visual/shaders/content_layer.wgsl
git commit -m "feat(visual): content layer shader — 9-dimensional spatial modulation, screen blend"
```

---

### Task 5: Bridge Integration — Wire Content Layer into Render Loop

**Files:**
- Modify: `hapax-logos/src-tauri/src/visual/bridge.rs`
- Modify: `hapax-logos/src-tauri/src/visual/state.rs`

- [ ] **Step 1: Add ImaginationState to state.rs**

Add after the `VisualChainState` struct in `state.rs`:

```rust
const IMAGINATION_CURRENT_PATH: &str = "/dev/shm/hapax-imagination/current.json";
const IMAGINATION_CONTENT_DIR: &str = "/dev/shm/hapax-imagination/content";

#[derive(Debug, Clone, Default, Deserialize)]
pub struct ImaginationState {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub continuation: bool,
    #[serde(default)]
    pub dimensions: HashMap<String, f64>,
    #[serde(default)]
    pub content_references: Vec<ImaginationContentRef>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct ImaginationContentRef {
    #[serde(default)]
    pub kind: String,
    #[serde(default)]
    pub source: String,
    #[serde(default)]
    pub salience: f64,
}
```

Add a field to `StateReader`:

```rust
pub struct StateReader {
    pub visual: VisualLayerState,
    pub stimmung: SystemStimmung,
    pub smoothed: SmoothedParams,
    pub imagination: ImaginationState,
    last_poll: Instant,
}
```

Initialize in `new()`:

```rust
imagination: ImaginationState::default(),
```

Add to `poll_now()`:

```rust
        // Read imagination state for content layer
        if let Some(img) = Self::read_json::<ImaginationState>(IMAGINATION_CURRENT_PATH) {
            self.imagination = img;
        }
```

- [ ] **Step 2: Add content_layer to bridge.rs**

Add the import and field to `VisualApp`:

```rust
use super::content_layer::ContentLayer;

// In VisualApp struct:
    content_layer: Option<ContentLayer>,

// In new():
    content_layer: None,

// In resumed(), after postprocess creation:
    let content_layer = ContentLayer::new(&gpu, w, h);

// In self assignments:
    self.content_layer = Some(content_layer);
```

In the `render()` method, after `compositor.render()` and before `postprocess.render()`:

```rust
        // Content layer: imagination content between compositor and postprocess
        if let Some(content) = &mut self.content_layer {
            // Check for new fragment
            let new_id = &self.state_reader.imagination.id;
            if !new_id.is_empty() && *new_id != content.current_fragment_id {
                let is_continuation = self.state_reader.imagination.continuation;

                if !is_continuation {
                    content.fade_out_all();
                }

                // Upload resolved content images
                let content_dir = std::path::Path::new("/dev/shm/hapax-imagination/content");
                for (i, cref) in self.state_reader.imagination.content_references.iter().enumerate() {
                    if i >= 4 { break; }
                    let path = match cref.kind.as_str() {
                        "camera_frame" => {
                            let p = format!("/dev/shm/hapax-compositor/{}.jpg", cref.source);
                            std::path::PathBuf::from(p)
                        }
                        "file" => std::path::PathBuf::from(&cref.source),
                        _ => content_dir.join(format!("{}-{}.jpg", new_id, i)),
                    };
                    if path.exists() {
                        content.upload_to_slot(gpu, i, &path, cref.salience as f32, &cref.source);
                    }
                }

                content.current_fragment_id = new_id.clone();
                content.is_continuation = is_continuation;
            }

            content.tick_fades(dt);

            let dims: std::collections::HashMap<String, f32> = self.state_reader.imagination.dimensions
                .iter()
                .map(|(k, v)| (k.clone(), *v as f32))
                .collect();
            content.update_uniforms(&gpu.queue, &dims, time);
            content.render(&mut encoder, &compositor.composite_view, &gpu.device);
        }
```

In the resize handler, add:

```rust
                if let Some(content) = &mut self.content_layer {
                    content.resize(&gpu.device, w, h);
                }
```

- [ ] **Step 3: Verify compilation**

Run: `cd ~/projects/hapax-council--beta/hapax-logos && cargo clean -p hapax-logos --manifest-path src-tauri/Cargo.toml && cargo check --manifest-path src-tauri/Cargo.toml`
Expected: compiles with warnings only

- [ ] **Step 4: Commit**

```bash
git add hapax-logos/src-tauri/src/visual/state.rs hapax-logos/src-tauri/src/visual/bridge.rs
git commit -m "feat(visual): wire content layer into render loop — imagination state, fragment detection, fade"
```
