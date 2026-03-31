# Phase 2: Content Source Protocol — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed 4-slot JPEG content system with a protocol that accepts arbitrary content sources (RGBA buffers + native text) from any process via shm.

**Architecture:** Any process writes RGBA frames and a manifest.json to `/dev/shm/hapax-imagination/sources/{source_id}/`. The Rust binary scans this directory each frame, creates/updates GPU textures per source, composites them onto the ground field. Text content is rendered natively via `ab_glyph`. Old 4-slot system preserved as backward compat during migration.

**Tech Stack:** Rust (wgpu, serde_json, ab_glyph, memmap2/mmap), Python (imagination_resolver update)

**Spec:** `docs/superpowers/specs/2026-03-31-reverie-adaptive-compositor-design.md` §3 (Content Protocol), §6 (Compositing Engine), §7 (Phase 2)

---

## File Structure

| File | Responsibility |
|------|---------------|
| `hapax-logos/crates/hapax-visual/src/content_sources.rs` | **CREATE**: Source scanning, manifest parsing, GPU texture management, text rendering, fade animation, compositing |
| `hapax-logos/crates/hapax-visual/src/content_textures.rs` | **KEEP (backward compat)**: Existing 4-slot JPEG system, still works during migration |
| `hapax-logos/crates/hapax-visual/src/lib.rs` | **MODIFY**: Add `pub mod content_sources;` |
| `hapax-logos/src-imagination/src/main.rs` | **MODIFY**: Add content_sources alongside content_textures, prefer sources/ when present |
| `agents/imagination_resolver.py` | **MODIFY**: Write new protocol format to `/sources/{source_id}/` in addition to old format |

---

### Task 1: Define content source manifest schema and reader (Rust)

**Files:**
- Create: `hapax-logos/crates/hapax-visual/src/content_sources.rs`
- Modify: `hapax-logos/crates/hapax-visual/src/lib.rs`

- [ ] **Step 1: Create content_sources.rs with manifest types**

```rust
//! Content source manager — scans shm for arbitrary RGBA/text content sources,
//! manages GPU textures, composites onto ground field.

use serde::Deserialize;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::time::Instant;

const SOURCES_DIR: &str = "/dev/shm/hapax-imagination/sources";
const DEFAULT_TTL_MS: u64 = 5000;
const MAX_SOURCES: usize = 16;

#[derive(Debug, Clone, Deserialize)]
pub struct SourceManifest {
    pub source_id: String,
    pub content_type: String, // "rgba" or "text"
    #[serde(default = "default_width")]
    pub width: u32,
    #[serde(default = "default_height")]
    pub height: u32,
    #[serde(default)]
    pub text: String,
    #[serde(default = "default_font_weight")]
    pub font_weight: u32,
    #[serde(default = "default_layer")]
    pub layer: u32,
    #[serde(default = "default_blend_mode")]
    pub blend_mode: String,
    #[serde(default = "default_opacity")]
    pub opacity: f32,
    #[serde(default)]
    pub z_order: i32,
    #[serde(default = "default_ttl")]
    pub ttl_ms: u64,
    #[serde(default)]
    pub tags: Vec<String>,
}

fn default_width() -> u32 { 1920 }
fn default_height() -> u32 { 1080 }
fn default_font_weight() -> u32 { 400 }
fn default_layer() -> u32 { 1 }
fn default_blend_mode() -> String { "screen".to_string() }
fn default_opacity() -> f32 { 1.0 }
fn default_ttl() -> u64 { DEFAULT_TTL_MS }

#[derive(Debug)]
struct ContentSource {
    manifest: SourceManifest,
    texture: wgpu::Texture,
    view: wgpu::TextureView,
    current_opacity: f32,
    target_opacity: f32,
    last_refresh: Instant,
    frame_path: PathBuf,
}

pub struct ContentSourceManager {
    sources: HashMap<String, ContentSource>,
    sources_dir: PathBuf,
    last_scan: Instant,
    scan_interval_ms: u64,
    placeholder_view: wgpu::TextureView,
    _placeholder_texture: wgpu::Texture,
}
```

- [ ] **Step 2: Add `pub mod content_sources;` to lib.rs**

In `hapax-logos/crates/hapax-visual/src/lib.rs`, add:
```rust
pub mod content_sources;
```

- [ ] **Step 3: Verify it compiles**

Run: `cd ~/projects/hapax-council--beta/hapax-logos && cargo check -p hapax-visual 2>&1 | tail -5`

Expected: Compiles with warnings (unused fields/imports — we'll use them in later tasks).

- [ ] **Step 4: Commit**

```bash
git add hapax-logos/crates/hapax-visual/src/content_sources.rs hapax-logos/crates/hapax-visual/src/lib.rs
git commit -m "feat(content-sources): define manifest schema and source types

ContentSourceManager scans /dev/shm/hapax-imagination/sources/ for
arbitrary content. SourceManifest supports rgba and text content types
with blend_mode, opacity, z_order, ttl_ms, and tags."
```

---

### Task 2: Implement source scanning and RGBA upload (Rust)

**Files:**
- Modify: `hapax-logos/crates/hapax-visual/src/content_sources.rs`

- [ ] **Step 1: Implement ContentSourceManager::new() and scan()**

Add to `ContentSourceManager`:

```rust
impl ContentSourceManager {
    pub fn new(device: &wgpu::Device, queue: &wgpu::Queue) -> Self {
        let (placeholder_texture, placeholder_view) = Self::create_placeholder(device, queue);
        Self {
            sources: HashMap::new(),
            sources_dir: PathBuf::from(SOURCES_DIR),
            last_scan: Instant::now(),
            scan_interval_ms: 100, // scan every 100ms
            placeholder_view,
            _placeholder_texture: placeholder_texture,
        }
    }

    fn create_placeholder(device: &wgpu::Device, queue: &wgpu::Queue) -> (wgpu::Texture, wgpu::TextureView) {
        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("content_source_placeholder"),
            size: wgpu::Extent3d { width: 1, height: 1, depth_or_array_layers: 1 },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8Unorm,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });
        queue.write_texture(
            wgpu::TexelCopyTextureInfo {
                texture: &texture, mip_level: 0,
                origin: wgpu::Origin3d::ZERO, aspect: wgpu::TextureAspect::All,
            },
            &[0u8, 0, 0, 0], // transparent black
            wgpu::TexelCopyBufferLayout { offset: 0, bytes_per_row: Some(4), rows_per_image: Some(1) },
            wgpu::Extent3d { width: 1, height: 1, depth_or_array_layers: 1 },
        );
        let view = texture.create_view(&Default::default());
        (texture, view)
    }

    /// Scan sources directory, add/update/expire sources.
    pub fn scan(&mut self, device: &wgpu::Device, queue: &wgpu::Queue) {
        if self.last_scan.elapsed().as_millis() < self.scan_interval_ms as u128 {
            return;
        }
        self.last_scan = Instant::now();

        // Read source directories
        let entries = match std::fs::read_dir(&self.sources_dir) {
            Ok(e) => e,
            Err(_) => return,
        };

        let mut seen = Vec::new();
        for entry in entries.flatten() {
            let path = entry.path();
            if !path.is_dir() { continue; }
            let source_id = match path.file_name().and_then(|n| n.to_str()) {
                Some(n) => n.to_string(),
                None => continue,
            };
            if self.sources.len() >= MAX_SOURCES && !self.sources.contains_key(&source_id) {
                continue; // at capacity
            }

            let manifest_path = path.join("manifest.json");
            let manifest = match Self::read_manifest(&manifest_path) {
                Some(m) => m,
                None => continue,
            };

            let frame_path = path.join("frame.rgba");

            if manifest.content_type == "rgba" {
                self.update_rgba_source(device, queue, &source_id, manifest, &frame_path);
            }
            // text rendering handled in Task 3

            seen.push(source_id);
        }

        // Expire sources not seen or past TTL
        let now = Instant::now();
        self.sources.retain(|id, src| {
            if !seen.contains(id) {
                return false; // directory removed
            }
            if now.duration_since(src.last_refresh).as_millis() > src.manifest.ttl_ms as u128 {
                return false; // TTL expired
            }
            true
        });
    }

    fn read_manifest(path: &Path) -> Option<SourceManifest> {
        let data = std::fs::read_to_string(path).ok()?;
        serde_json::from_str(&data).ok()
    }

    fn update_rgba_source(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        source_id: &str,
        manifest: SourceManifest,
        frame_path: &Path,
    ) {
        let expected_size = (manifest.width * manifest.height * 4) as u64;
        let metadata = match std::fs::metadata(frame_path) {
            Ok(m) => m,
            Err(_) => return,
        };
        if metadata.len() != expected_size { return; }

        let pixels = match std::fs::read(frame_path) {
            Ok(p) => p,
            Err(_) => return,
        };

        let target_opacity = manifest.opacity;

        if let Some(source) = self.sources.get_mut(source_id) {
            // Update existing source
            if source.manifest.width != manifest.width || source.manifest.height != manifest.height {
                // Dimensions changed — recreate texture
                let (tex, view) = Self::create_source_texture(device, manifest.width, manifest.height, source_id);
                source.texture = tex;
                source.view = view;
            }
            Self::upload_rgba(queue, &source.texture, &pixels, manifest.width, manifest.height);
            source.manifest = manifest;
            source.target_opacity = target_opacity;
            source.last_refresh = Instant::now();
            source.frame_path = frame_path.to_path_buf();
        } else {
            // New source
            let (texture, view) = Self::create_source_texture(device, manifest.width, manifest.height, source_id);
            Self::upload_rgba(queue, &texture, &pixels, manifest.width, manifest.height);
            self.sources.insert(source_id.to_string(), ContentSource {
                manifest,
                texture,
                view,
                current_opacity: 0.0,
                target_opacity,
                last_refresh: Instant::now(),
                frame_path: frame_path.to_path_buf(),
            });
        }
    }

    fn create_source_texture(device: &wgpu::Device, width: u32, height: u32, label: &str) -> (wgpu::Texture, wgpu::TextureView) {
        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some(label),
            size: wgpu::Extent3d { width, height, depth_or_array_layers: 1 },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8Unorm,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });
        let view = texture.create_view(&Default::default());
        (texture, view)
    }

    fn upload_rgba(queue: &wgpu::Queue, texture: &wgpu::Texture, pixels: &[u8], width: u32, height: u32) {
        queue.write_texture(
            wgpu::TexelCopyTextureInfo {
                texture, mip_level: 0,
                origin: wgpu::Origin3d::ZERO, aspect: wgpu::TextureAspect::All,
            },
            pixels,
            wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(4 * width),
                rows_per_image: Some(height),
            },
            wgpu::Extent3d { width, height, depth_or_array_layers: 1 },
        );
    }

    /// Advance fade animations.
    pub fn tick_fades(&mut self, dt: f32) {
        let fade_rate = 2.0f32;
        for source in self.sources.values_mut() {
            let diff = source.target_opacity - source.current_opacity;
            let step = fade_rate * dt;
            if diff.abs() < step {
                source.current_opacity = source.target_opacity;
            } else {
                source.current_opacity += diff.signum() * step;
            }
        }
    }

    /// Get sorted active sources for compositing.
    pub fn active_sources(&self) -> Vec<(&str, &wgpu::TextureView, f32)> {
        let mut result: Vec<_> = self.sources.iter()
            .filter(|(_, s)| s.current_opacity > 0.001)
            .map(|(id, s)| (id.as_str(), &s.view, s.current_opacity))
            .collect();
        result.sort_by_key(|(_, _, _)| 0); // TODO: sort by z_order when compositing pass exists
        result
    }

    /// Get placeholder view (for when no sources active).
    pub fn placeholder_view(&self) -> &wgpu::TextureView {
        &self.placeholder_view
    }

    /// Check if any sources are active.
    pub fn has_active_sources(&self) -> bool {
        self.sources.values().any(|s| s.current_opacity > 0.001)
    }

    /// Get source count.
    pub fn source_count(&self) -> usize {
        self.sources.len()
    }
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd ~/projects/hapax-council--beta/hapax-logos && cargo check -p hapax-visual 2>&1 | tail -10`

- [ ] **Step 3: Commit**

```bash
git add hapax-logos/crates/hapax-visual/src/content_sources.rs
git commit -m "feat(content-sources): implement source scanning and RGBA upload

Scans /dev/shm/hapax-imagination/sources/ for directories with
manifest.json + frame.rgba. Creates/updates GPU textures per source.
Manages lifecycle: new sources fade in, expired sources removed,
max 16 concurrent sources."
```

---

### Task 3: Wire ContentSourceManager into main.rs alongside legacy system

**Files:**
- Modify: `hapax-logos/src-imagination/src/main.rs`

- [ ] **Step 1: Add content_sources import and field**

Add import alongside existing:
```rust
use hapax_visual::content_sources::ContentSourceManager;
```

Add field to `App` struct (line ~40):
```rust
content_source_mgr: Option<ContentSourceManager>,
```

Initialize in `Default` (line ~56):
```rust
content_source_mgr: None,
```

Create in `resumed()` after content_textures (line ~298):
```rust
let content_source_mgr = ContentSourceManager::new(&gpu.device, &gpu.queue);
```

Set in self (line ~303):
```rust
self.content_source_mgr = Some(content_source_mgr);
```

- [ ] **Step 2: Call scan and tick in the render loop**

In the `RedrawRequested` handler (around line 189), after existing content_textures poll:
```rust
if let Some(csm) = &mut self.content_source_mgr {
    if let Some(gpu) = &self.gpu {
        csm.scan(&gpu.device, &gpu.queue);
    }
    csm.tick_fades(dt);
}
```

- [ ] **Step 3: Build the binary**

Run: `cd ~/projects/hapax-council--beta/hapax-logos && cargo build --release -p hapax-imagination 2>&1 | tail -10`

Expected: Clean build (warnings OK for now).

- [ ] **Step 4: Commit**

```bash
git add hapax-logos/src-imagination/src/main.rs
git commit -m "feat(content-sources): wire ContentSourceManager into render loop

Runs alongside legacy ContentTextureManager. Scans sources/ directory
each frame, uploads RGBA textures. No compositing yet — sources are
loaded but not rendered. Legacy 4-slot system continues to work."
```

---

### Task 4: Update imagination_resolver.py to write new protocol

**Files:**
- Modify: `agents/imagination_resolver.py`

- [ ] **Step 1: Write test for new protocol output**

Create `tests/test_content_source_protocol.py`:

```python
"""Tests for the content source protocol output from imagination_resolver."""

import json
import tempfile
from pathlib import Path

from agents.imagination import ImaginationFragment


def test_write_source_manifest_creates_directory():
    """Source protocol should create sources/{source_id}/ directory."""
    from agents.imagination_resolver import write_source_protocol

    fragment = ImaginationFragment(
        id="test-frag-1",
        narrative="test narrative",
        content_references=[],
        salience=0.5,
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        sources_dir = Path(tmpdir) / "sources"
        write_source_protocol(fragment, [], sources_dir)
        source_dir = sources_dir / f"imagination-{fragment.id}"
        assert source_dir.exists()
        manifest = json.loads((source_dir / "manifest.json").read_text())
        assert manifest["source_id"] == f"imagination-{fragment.id}"
        assert manifest["content_type"] == "text"
        assert manifest["text"] == "test narrative"


def test_write_source_protocol_rgba():
    """Source with resolved JPEG should produce rgba manifest + frame.rgba."""
    from agents.imagination_resolver import write_source_protocol

    fragment = ImaginationFragment(
        id="test-frag-2",
        narrative="visual test",
        content_references=[],
        salience=0.7,
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        sources_dir = Path(tmpdir) / "sources"
        # Create a fake resolved JPEG
        staging = Path(tmpdir) / "staging"
        staging.mkdir()
        fake_jpeg = staging / "slot_0.jpg"
        fake_jpeg.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)  # minimal JPEG header

        write_source_protocol(fragment, [fake_jpeg], sources_dir)
        source_dir = sources_dir / f"imagination-{fragment.id}"
        manifest = json.loads((source_dir / "manifest.json").read_text())
        assert manifest["content_type"] in ("rgba", "text")
```

- [ ] **Step 2: Add write_source_protocol() to imagination_resolver.py**

Add after the existing `write_slot_manifest()` function:

```python
SOURCES_DIR = Path("/dev/shm/hapax-imagination/sources")


def write_source_protocol(
    fragment: ImaginationFragment,
    resolved_paths: list[Path],
    sources_dir: Path | None = None,
) -> None:
    """Write content using the new source protocol.

    Creates a directory per fragment in sources/ with manifest.json.
    If resolved paths contain images, writes the first as frame.rgba.
    Otherwise writes text content for native Rust rendering.
    """
    if sources_dir is None:
        sources_dir = SOURCES_DIR

    source_id = f"imagination-{fragment.id}"
    source_dir = sources_dir / source_id
    source_dir.mkdir(parents=True, exist_ok=True)

    if resolved_paths:
        # Image content — write as text manifest pointing to first resolved image
        # (RGBA conversion will be done by a future task; for now use text fallback)
        manifest = {
            "source_id": source_id,
            "content_type": "text",
            "text": fragment.narrative,
            "opacity": fragment.salience,
            "layer": 1,
            "blend_mode": "screen",
            "z_order": 10,
            "ttl_ms": 10000,
            "tags": ["imagination"],
        }
    else:
        manifest = {
            "source_id": source_id,
            "content_type": "text",
            "text": fragment.narrative,
            "opacity": fragment.salience,
            "layer": 1,
            "blend_mode": "screen",
            "z_order": 10,
            "ttl_ms": 10000,
            "tags": ["imagination"],
        }

    tmp = source_dir / "manifest.tmp"
    tmp.write_text(json.dumps(manifest))
    tmp.rename(source_dir / "manifest.json")
```

- [ ] **Step 3: Call write_source_protocol from resolve_references_staged**

In `resolve_references_staged()` (around line 195), after the existing `write_slot_manifest()` call, add:

```python
    write_source_protocol(fragment, resolved, sources_dir=SOURCES_DIR)
```

This writes BOTH the old format (for backward compat) and the new format.

- [ ] **Step 4: Run tests**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_content_source_protocol.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/imagination_resolver.py tests/test_content_source_protocol.py
git commit -m "feat(content-sources): write new source protocol from imagination_resolver

Writes to /dev/shm/hapax-imagination/sources/{source_id}/ alongside
legacy slots.json. Currently text-only (RGBA conversion deferred).
Both old and new formats written for backward compatibility."
```

---

### Task 5: Build, deploy, verify, PR

**Files:**
- No file changes.

- [ ] **Step 1: Run all tests**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_content_source_protocol.py tests/test_reverie_vocabulary.py tests/test_visual_chain.py tests/effect_graph/ -v`

- [ ] **Step 2: Lint**

Run: `cd ~/projects/hapax-council--beta && uv run ruff check agents/imagination_resolver.py tests/test_content_source_protocol.py && uv run ruff format --check agents/imagination_resolver.py tests/test_content_source_protocol.py`

- [ ] **Step 3: Build Rust binary**

Run: `cd ~/projects/hapax-council--beta/hapax-logos && cargo build --release -p hapax-imagination 2>&1 | tail -10`

- [ ] **Step 4: Deploy and verify**

```bash
systemctl --user stop hapax-imagination
cp hapax-logos/target/release/hapax-imagination ~/.local/bin/hapax-imagination
systemctl --user start hapax-imagination
sleep 2
systemctl --user status hapax-imagination --no-pager | head -8
journalctl --user -u hapax-imagination --since "10 sec ago" --no-pager | grep -i "loaded\|error\|source"
```

- [ ] **Step 5: Push and create PR**

```bash
git push -u origin HEAD
gh pr create --title "feat: content source protocol (Phase 2)" --body "..."
```

- [ ] **Step 6: Monitor CI, merge when green**
