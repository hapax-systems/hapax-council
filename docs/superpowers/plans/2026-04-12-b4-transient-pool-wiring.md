# B4 — Wire TransientTexturePool into DynamicPipeline

**Date:** 2026-04-12
**Status:** Approved plan, not yet implemented
**Owner:** beta
**Source:** 2026-04-12 work-stream split, item B4. Handoff reference: `docs/superpowers/handoff/2026-04-12-session-handoff.md`.

---

## 1. Problem

`hapax-logos/crates/hapax-visual/src/transient_pool.rs` shipped standalone in PR #670 (F1 of the compositor unification epic) as a bucketed allocator for recyclable intermediate textures. The wgpu executor in `dynamic_pipeline.rs` still allocates its intermediate textures inline via `device.create_texture(...)` and stores them in `HashMap<String, PoolTexture>`. The pool is unused at runtime. This is the largest remaining unclosed loop from that epic.

## 2. Current state

- **Pool:** `TransientTexturePool<T>` exists at `transient_pool.rs` with `new`, `begin_frame`, `acquire_tracked`, `get`, `clear`, `reuse_ratio`, and per-bucket telemetry accessors. 12 unit tests cover bookkeeping. No production caller.
- **Allocator today:** `DynamicPipeline::ensure_texture()` (line ~1150 of `dynamic_pipeline.rs`) creates textures directly with a name as the key and stores them in `self.textures: HashMap<String, PoolTexture>`. Called during plan reload, not per-frame. `ensure_temporal_texture()` handles `@accum_*` feedback textures in a parallel map (`self.temporal_textures`) that is deliberately excluded from pooling — they must persist across frames.
- **Call sites:** `self.textures.get|contains_key|keys|values|remove|insert` appears at 18 locations in `dynamic_pipeline.rs`: bind group construction, blit source selection, resize handling, and plan reload. Every site either looks up a `PoolTexture` by name or enumerates the map.
- **Python side:** The doc-comment in `transient_pool.rs` references `CompiledFrame.transient_textures` with Python-side `pool_key` computation, but `agents/effect_graph/` does not emit any `pool_key` yet — that part of the data plane is aspirational.

## 3. Scope of this PR

Minimal, correct wiring that replaces `HashMap<String, PoolTexture>` with a pool-backed slot-map, preserves current behavior, and adds per-plan observability. Non-goals (explicitly deferred):

- Python-side `pool_key` emission from `CompiledFrame`. The Rust side will compute a single pool key from `(width, height, format)` until Python catches up.
- Per-frame recycling via `begin_frame()`. Under the current plan model each named intermediate holds its slot for the lifetime of the loaded plan; adding frame-level recycling requires changing when textures are acquired (per-frame instead of per-plan) and is a separate refactor.
- Temporal textures (`@accum_*`) — these stay in `self.temporal_textures` as a plain `HashMap`, unchanged.

## 4. Design

### 4.1 Struct changes

```rust
pub struct DynamicPipeline {
    passes: Vec<DynamicPass>,

    // New: the pool owns the textures now.
    intermediate_pool: TransientTexturePool<PoolTexture>,
    // Single pool key for all intermediates, computed at new() time from
    // (width, height, TEXTURE_FORMAT). Same descriptor → same bucket.
    intermediate_pool_key: u64,
    // Name → slot, rebuilt on resize/reload, queried on every bind group
    // construction. Replaces `textures: HashMap<String, PoolTexture>`.
    intermediate_slots: HashMap<String, usize>,

    // Temporal textures stay as they are — they are intentionally NOT
    // pooled (they persist across frames and are cleared, not recycled).
    temporal_textures: HashMap<String, PoolTexture>,

    // ... rest unchanged
}
```

### 4.2 Pool key

```rust
fn compute_pool_key(width: u32, height: u32, format: wgpu::TextureFormat) -> u64 {
    use std::collections::hash_map::DefaultHasher;
    use std::hash::{Hash, Hasher};
    let mut hasher = DefaultHasher::new();
    (width, height, format as u32).hash(&mut hasher);
    hasher.finish()
}
```

All intermediates in the current executor share `(width, height, TEXTURE_FORMAT)`, so every `ensure_texture` call produces the same key and every slot lands in the same bucket. When Python later emits per-stage `pool_key` values, this helper can be replaced by a plan-driven lookup.

### 4.3 Allocator rewrite

```rust
fn ensure_texture(&mut self, device: &wgpu::Device, name: &str) {
    if self.intermediate_slots.contains_key(name) {
        return;
    }
    let key = self.intermediate_pool_key;
    let width = self.width;
    let height = self.height;
    let slot = self.intermediate_pool.acquire_tracked(key, || {
        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some(name),
            size: wgpu::Extent3d { width, height, depth_or_array_layers: 1 },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: TEXTURE_FORMAT,
            usage: wgpu::TextureUsages::TEXTURE_BINDING
                | wgpu::TextureUsages::RENDER_ATTACHMENT
                | wgpu::TextureUsages::COPY_SRC
                | wgpu::TextureUsages::COPY_DST
                | wgpu::TextureUsages::STORAGE_BINDING,
            view_formats: &[],
        });
        let view = texture.create_view(&Default::default());
        PoolTexture { texture, view }
    });
    self.intermediate_slots.insert(name.to_string(), slot);
}
```

Note: `ensure_texture` is NOT called per-frame. Without a matching `begin_frame()` reset, the pool's `in_use` counter grows monotonically for the life of the plan. That is intentional — when the plan reloads we want the old slots to stay put (so already-compiled passes keep their bindings) and only the *new* textures in the plan to acquire fresh slots. A `clear()` on the pool is only called on full viewport resize.

### 4.4 Lookup helpers

Two method helpers centralize pool access:

```rust
impl DynamicPipeline {
    fn get_intermediate(&self, name: &str) -> Option<&PoolTexture> {
        let slot = *self.intermediate_slots.get(name)?;
        self.intermediate_pool.get(self.intermediate_pool_key, slot)
    }

    fn intermediate_names(&self) -> impl Iterator<Item = &String> {
        self.intermediate_slots.keys()
    }

    fn any_intermediate(&self) -> Option<&PoolTexture> {
        // Fallback used by the blit path when nothing has been rendered yet.
        self.intermediate_slots
            .values()
            .next()
            .and_then(|&slot| self.intermediate_pool.get(self.intermediate_pool_key, slot))
    }
}
```

### 4.5 Call site migration (18 sites)

Mechanical replacement in `dynamic_pipeline.rs`:

| Current | Rewritten |
|---|---|
| `self.textures.get(name)` | `self.get_intermediate(name)` |
| `self.textures.contains_key(name)` | `self.intermediate_slots.contains_key(name)` |
| `self.textures.keys()` | `self.intermediate_names()` |
| `self.textures.values().next()` | `self.any_intermediate()` |
| `self.textures.remove(name)` | `self.intermediate_slots.remove(name)` (pool bucket is not shrunk; the slot leaks until `clear()` on next resize — acceptable because plan reload usually re-acquires the same names) |
| `self.textures.insert(name, pt)` | Only appears inside `ensure_texture`, replaced by the `acquire_tracked` path in §4.3. |

Every site is a lookup or a bulk-map operation; none constructs a fresh `PoolTexture` outside `ensure_texture`, so the rewrite is a pure access-path substitution.

### 4.6 Resize

`handle_resize()` currently drops every texture in `self.textures` and recreates them via `ensure_texture`. Rewrite to:

```rust
self.intermediate_pool.clear();
self.intermediate_slots.clear();
for name in texture_names {
    self.ensure_texture(device, &name);
}
```

Temporal textures continue to be handled by their own explicit loop.

### 4.7 Observability

Expose three counters via a `pool_metrics()` method returning a small struct:

```rust
pub struct PoolMetrics {
    pub bucket_count: usize,
    pub total_textures: usize,
    pub total_acquires: u64,
    pub total_allocations: u64,
    pub reuse_ratio: f64,
}
```

Call from the render loop (once per N frames) and publish via whatever metrics surface the compositor already uses (`budget_signal.py` / Prometheus exporter). Wiring through to Prometheus is a separate small follow-up; this PR adds the struct and the method so the counters are readable from Rust.

## 5. Tests

1. **Unit test — single plan load acquires slots in one bucket.** Construct a minimal `DynamicPipeline`, load a plan with three intermediates, assert `pool.bucket_count() == 1`, `pool.total_allocations() == 3`, `intermediate_slots.len() == 3`.
2. **Unit test — plan reload reuses existing slots.** Load a plan with texture names A, B. Reload with the same names — `total_allocations` stays at 2, `total_acquires` stays at 2 (the `contains_key` guard short-circuits). Reload with A, B, C — allocations go to 3.
3. **Unit test — resize clears the pool.** Load a plan, call `handle_resize`, assert `pool.bucket_count() == 0` and then assert the names are re-acquired after the post-resize `ensure_texture` loop.
4. **Unit test — lookup helper matches HashMap baseline.** For a fixture plan with names {A, B, C}, `get_intermediate(A).unwrap().texture.size()` matches the expected `wgpu::Extent3d`.
5. **Integration test — render one frame.** Load the vocabulary preset, render a single frame, verify no wgpu validation errors and that the output surface receives the blit.

Tests 1–4 use a headless wgpu adapter created in a test helper. Test 5 is already within the reach of existing render-path tests (if any exist) — if none do, this PR adds a small headless render test.

## 6. Risk

- **Borrow checker:** `get_intermediate` returns `&PoolTexture` with a borrow tied to `&self.intermediate_pool`. Any site that needs `&mut self` while holding a `&PoolTexture` will fail. The explorer pass found no such site in `dynamic_pipeline.rs`, but this must be re-verified during the edit.
- **Bind group lifetime:** Bind groups are recreated per-frame and hold no long-lived borrow. Safe.
- **Slot leak on plan shrink:** If a plan goes from {A, B, C} to {A, B}, the C slot stays in the bucket until the next `clear()`. This wastes one texture's memory until resize. Acceptable; Python will emit correct pool keys later and the bucket can be trimmed then.
- **Pool key collision:** Two different descriptors hashing to the same `u64` would merge buckets. Not a real risk with a 64-bit hash and a small number of distinct descriptors (currently one).

## 7. Out of scope / follow-ups

| Item | Why deferred |
|---|---|
| Per-frame `begin_frame()` recycling | Requires restructuring `render()` to re-acquire textures every frame; needs plan-driven lifetime analysis. |
| Python-side `pool_key` emission | Requires `CompiledFrame` / plan format v3 changes; ripples through the compile phase and existing tests. |
| Prometheus export of `PoolMetrics` | A one-line addition in the metrics surface; easier after the struct exists. |
| Temporal-texture pooling | Explicit non-goal from Phase 4c — temporal textures need different semantics (persist + clear, not recycle). |

## 8. Estimated size

Roughly 120–180 lines of Rust touch spread across `dynamic_pipeline.rs` (struct + 18 call-site rewrites + helpers + ensure_texture) and ~80 lines of new unit tests. One file touched in production, one in tests.

## 9. Sources

- `hapax-logos/crates/hapax-visual/src/transient_pool.rs` — pool implementation
- `hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs` — executor
- `docs/superpowers/plans/2026-04-12-compositor-unification-epic.md` — epic reference
- `docs/superpowers/handoff/2026-04-12-session-handoff.md` — B4 framing
- `~/.cache/hapax/relay/context/2026-04-12-work-stream-split.md` — work-stream split
