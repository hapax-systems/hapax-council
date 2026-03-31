# Phase 3: Bridge Content Sources into Rendering — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make content from `ContentSourceManager` actually visible on the Reverie surface by bridging its textures into the existing `content_layer` shader's 4 texture slots.

**Architecture:** The `DynamicPipeline::create_input_bind_group()` already resolves `content_slot_N` names to texture views from `ContentTextureManager`. We add `ContentSourceManager` as an alternative provider: if it has active sources, its texture views are used for the content slots. The content_layer shader (Bachelard materialization, material quality, immensity) renders them identically — it doesn't care where the textures come from.

**Tech Stack:** Rust (wgpu, content_sources.rs, dynamic_pipeline.rs, main.rs)

**Spec:** `docs/superpowers/specs/2026-03-31-reverie-adaptive-compositor-design.md` §6 (Compositing Engine)

**Scope note:** This is the pragmatic bridge, not the full layer refactor. The full plan.json v2 layer model (satellite insertion, N-source compositing beyond 4 slots) is Phase 3b, a future session.

---

### Task 1: Add slot_view() method to ContentSourceManager

**Files:**
- Modify: `hapax-logos/crates/hapax-visual/src/content_sources.rs`

The `DynamicPipeline` calls `content_textures.slot_view(idx)` to get texture views for content_slot_0..3. We need `ContentSourceManager` to provide the same interface.

- [ ] **Step 1: Add slot_view() and slot_opacities() methods**

Add to `ContentSourceManager`:

```rust
/// Get texture view for a content slot (maps active sources to slot indices by z_order).
/// Returns placeholder if no source at that index.
pub fn slot_view(&self, index: usize) -> &wgpu::TextureView {
    let mut sorted: Vec<&ContentSource> = self.sources.values()
        .filter(|s| s.current_opacity > 0.001)
        .collect();
    sorted.sort_by_key(|s| s.manifest.z_order);
    if let Some(source) = sorted.get(index) {
        &source.view
    } else {
        &self.placeholder_view
    }
}

/// Get opacities for up to 4 content slots (matching ContentTextureManager interface).
pub fn slot_opacities(&self) -> [f32; 4] {
    let mut sorted: Vec<&ContentSource> = self.sources.values()
        .filter(|s| s.current_opacity > 0.001)
        .collect();
    sorted.sort_by_key(|s| s.manifest.z_order);
    let mut opacities = [0.0f32; 4];
    for (i, source) in sorted.iter().take(4).enumerate() {
        opacities[i] = source.current_opacity;
    }
    opacities
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd ~/projects/hapax-council--beta/hapax-logos && cargo check -p hapax-visual 2>&1 | tail -5`

- [ ] **Step 3: Commit**

```bash
git add hapax-logos/crates/hapax-visual/src/content_sources.rs
git commit -m "feat(content-sources): add slot_view() and slot_opacities() for pipeline bridge

Maps active sources to 4 content slots by z_order, matching the
ContentTextureManager interface. Enables DynamicPipeline to read
from either provider transparently."
```

---

### Task 2: Pass ContentSourceManager to DynamicPipeline::render()

**Files:**
- Modify: `hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs`
- Modify: `hapax-logos/src-imagination/src/main.rs`

The render() method currently takes `content_textures: Option<&ContentTextureManager>`. We add `content_sources: Option<&ContentSourceManager>` and prefer it when it has active sources.

- [ ] **Step 1: Update render() signature**

In `dynamic_pipeline.rs`, add the import:
```rust
use crate::content_sources::ContentSourceManager;
```

Update the `render()` method signature (around line 543-554) to add the new parameter:
```rust
pub fn render(
    &mut self,
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    surface_view: &wgpu::TextureView,
    _surface_format: wgpu::TextureFormat,
    state_reader: &StateReader,
    dt: f32,
    time: f32,
    content_slot_opacities: [f32; 4],
    content_textures: Option<&ContentTextureManager>,
    content_sources: Option<&ContentSourceManager>,
) {
```

- [ ] **Step 2: Update create_input_bind_group to prefer content_sources**

In `create_input_bind_group()` (around line 1111-1121), change the content slot resolution:

```rust
// Binding 2..N: content slot textures
for (i, name) in content_inputs.iter().enumerate() {
    let idx: usize = name.strip_prefix("content_slot_")
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);
    // Prefer ContentSourceManager when it has active sources
    let slot_view = if content_sources.map(|cs| cs.has_active_sources()).unwrap_or(false) {
        content_sources.unwrap().slot_view(idx)
    } else {
        content_textures
            .map(|ct| ct.slot_view(idx))
            .unwrap_or_else(|| self.textures.get("final").map(|t| &t.view).unwrap())
    };
    entries.push(wgpu::BindGroupEntry {
        binding: (2 + i) as u32,
        resource: wgpu::BindingResource::TextureView(slot_view),
    });
}
```

Also update `create_input_bind_group` signature to accept the new parameter:
```rust
fn create_input_bind_group(
    &self,
    device: &wgpu::Device,
    inputs: &[String],
    content_textures: Option<&ContentTextureManager>,
    content_sources: Option<&ContentSourceManager>,
) -> wgpu::BindGroup {
```

And update both call sites in `render()` (around lines 738 and 789) to pass `content_sources`.

- [ ] **Step 3: Update slot_opacities to prefer content_sources**

In `render()` (around line 561), after `uniform_data.slot_opacities = content_slot_opacities;` — this is already passed from main.rs. We need to update main.rs to merge opacities from both systems.

- [ ] **Step 4: Update main.rs to pass content_sources to render()**

In `main.rs`, update the render call (around line 209-219):

```rust
if let Some(pipeline) = &mut self.dynamic_pipeline {
    let legacy_opacities = self.content_textures.as_ref()
        .map(|ct| ct.slot_opacities()).unwrap_or([0.0; 4]);
    let source_opacities = self.content_source_mgr.as_ref()
        .map(|cs| cs.slot_opacities()).unwrap_or([0.0; 4]);
    // Use whichever has higher opacities (prefer new system when active)
    let opacities = if source_opacities.iter().any(|&o| o > 0.001) {
        source_opacities
    } else {
        legacy_opacities
    };
    pipeline.render(
        &gpu.device,
        &gpu.queue,
        &view,
        gpu.format,
        &self.state_reader,
        dt,
        time,
        opacities,
        self.content_textures.as_ref(),
        self.content_source_mgr.as_ref(),
    );
}
```

- [ ] **Step 5: Build**

Run: `cd ~/projects/hapax-council--beta/hapax-logos && cargo build --release -p hapax-imagination 2>&1 | tail -10`

- [ ] **Step 6: Commit**

```bash
git add hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs hapax-logos/src-imagination/src/main.rs
git commit -m "feat(content-sources): bridge ContentSourceManager into render pipeline

DynamicPipeline::render() accepts ContentSourceManager alongside
legacy ContentTextureManager. Content slot resolution prefers new
sources when active, falls back to legacy. Both systems coexist."
```

---

### Task 3: Deploy, verify with a test source, PR

**Files:**
- No code changes.

- [ ] **Step 1: Deploy new binary**

```bash
systemctl --user stop hapax-imagination
cp ~/projects/hapax-council--beta/hapax-logos/target/release/hapax-imagination ~/.local/bin/hapax-imagination
systemctl --user start hapax-imagination
sleep 2
systemctl --user status hapax-imagination --no-pager | head -8
```

- [ ] **Step 2: Write a test source to verify the protocol works end-to-end**

```bash
mkdir -p /dev/shm/hapax-imagination/sources/test-source
# Create a small 64x64 red RGBA buffer
python3 -c "
import json, struct
w, h = 64, 64
pixels = b''
for y in range(h):
    for x in range(w):
        pixels += struct.pack('BBBB', 255, 0, 0, 200)  # red, semi-transparent
with open('/dev/shm/hapax-imagination/sources/test-source/frame.rgba', 'wb') as f:
    f.write(pixels)
with open('/dev/shm/hapax-imagination/sources/test-source/manifest.json', 'w') as f:
    json.dump({'source_id': 'test-source', 'content_type': 'rgba', 'width': 64, 'height': 64, 'opacity': 0.8, 'layer': 1, 'blend_mode': 'screen', 'z_order': 0, 'ttl_ms': 30000, 'tags': ['test']}, f)
print('Test source written')
"
```

Wait a few seconds for the scanner to pick it up, then check the frame:
```bash
sleep 3
stat /dev/shm/hapax-visual/frame.jpg | grep Modify
# Visually inspect the frame for a red rectangle
```

- [ ] **Step 3: Clean up test source**

```bash
rm -rf /dev/shm/hapax-imagination/sources/test-source
```

- [ ] **Step 4: Run lint and tests**

```bash
cd ~/projects/hapax-council--beta && uv run ruff check agents/ tests/ && uv run pytest tests/test_content_source_protocol.py tests/test_reverie_vocabulary.py tests/test_visual_chain.py -v
```

- [ ] **Step 5: Push and create PR**

```bash
git push -u origin HEAD
gh pr create --title "feat: bridge content sources into render pipeline (Phase 3)" --body "..."
```

- [ ] **Step 6: Monitor CI, merge when green**
