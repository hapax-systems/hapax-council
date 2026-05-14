//! Dynamic shader graph executor.
//!
//! Replaces hardcoded techniques + compositor + postprocess with a generic pipeline
//! that reads execution plans from `/dev/shm/hapax-imagination/pipeline/plan.json`.

use std::collections::HashMap;
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;

use notify::{Event, EventKind, RecommendedWatcher, Watcher};
use serde::Deserialize;
use wgpu::util::DeviceExt;

use crate::content_sources::ContentSourceManager;
use crate::output::ShmOutput;
use crate::state::StateReader;
use crate::transient_pool::TransientTexturePool;
use crate::uniform_buffer::UniformBuffer;

/// Compute a stable bucket key for the transient texture pool from the
/// triple `(width, height, format)`. All intermediates that share the
/// same descriptor land in the same bucket and recycle GPU memory across
/// frames. The current executor uses one descriptor for every
/// intermediate, so this resolves to a single bucket per pool today.
/// When the Python compile phase emits per-stage `pool_key` values, this
/// helper can be replaced by a plan-driven lookup.
fn compute_pool_key(width: u32, height: u32, format: wgpu::TextureFormat) -> u64 {
    let mut hasher = DefaultHasher::new();
    width.hash(&mut hasher);
    height.hash(&mut hasher);
    format.hash(&mut hasher);
    hasher.finish()
}

const PLAN_DIR: &str = "/dev/shm/hapax-imagination/pipeline";
const PLAN_FILE: &str = "/dev/shm/hapax-imagination/pipeline/plan.json";
const UNIFORMS_JSON: &str = "/dev/shm/hapax-imagination/uniforms.json";
const SHARED_UNIFORMS_WGSL: &str = include_str!("shaders/uniforms.wgsl");
const SHARED_VERTEX_WGSL: &str = include_str!("shaders/fullscreen_quad.wgsl");
const TEXTURE_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8Unorm;

// --- Plan JSON schema ---

/// Top-level plan.json file. Accepts both schemas:
///
/// * **v1** (`{"version": 1, "passes": [...]}`): a flat list of
///   passes that all feed a single implicit ``"main"`` target. The
///   `targets` field is empty; `passes` carries the data.
/// * **v2** (`{"version": 2, "targets": {"main": {"passes": [...]}}}`):
///   one named target per output node. Phase 5a of the compositor
///   unification epic — see
///   docs/superpowers/specs/2026-04-12-phase-5-multi-output-design.md
///
/// `normalize_passes()` collapses both shapes into the canonical
/// per-target map the rest of the executor reasons about. Phase 5a
/// only renders the ``"main"`` target; future Phase 5b additions
/// walk every target.
#[derive(Debug, Deserialize)]
struct PlanFile {
    #[serde(default)]
    passes: Vec<PlanPass>,
    #[serde(default)]
    targets: HashMap<String, PlanTarget>,
}

#[derive(Debug, Deserialize)]
struct PlanTarget {
    #[serde(default)]
    passes: Vec<PlanPass>,
}

impl PlanFile {
    /// Return the canonical per-target passes map.
    ///
    /// For v2 plans, returns `targets` directly. For v1 plans, wraps
    /// the flat `passes` list into a synthetic ``"main"`` target.
    /// An empty plan returns an empty map (the executor renders black).
    fn passes_by_target(&self) -> HashMap<String, Vec<PlanPass>> {
        if !self.targets.is_empty() {
            return self
                .targets
                .iter()
                .map(|(k, v)| (k.clone(), v.passes.clone()))
                .collect();
        }
        if self.passes.is_empty() {
            return HashMap::new();
        }
        let mut out = HashMap::with_capacity(1);
        out.insert("main".to_string(), self.passes.clone());
        out
    }

    /// Return the active passes for the ``main`` target, or the first
    /// target alphabetically if ``main`` is absent.
    ///
    /// Phase 5a only renders one target. Phase 5b will replace this
    /// helper with a per-target render walk.
    fn main_passes(&self) -> Vec<PlanPass> {
        let map = self.passes_by_target();
        if let Some(main) = map.get("main") {
            return main.clone();
        }
        let mut keys: Vec<&String> = map.keys().collect();
        keys.sort();
        if let Some(first) = keys.first() {
            return map[*first].clone();
        }
        Vec::new()
    }
}

#[derive(Debug, Deserialize, Clone)]
struct PlanPass {
    node_id: String,
    shader: String,
    #[serde(default)]
    inputs: Vec<String>,
    #[serde(default = "default_output")]
    output: String,
    #[serde(default = "default_steps")]
    steps_per_frame: u32,
    /// Pass type from Python: "render" or "compute"
    #[serde(rename = "type", default)]
    pass_type: String,
    #[serde(default, deserialize_with = "deserialize_numeric_only")]
    uniforms: HashMap<String, f64>,
    #[serde(default)]
    param_order: Vec<String>,
    /// Whether this pass declares content slot inputs (declarative opt-in
    /// from the node manifest's requires_content_slots field). When true,
    /// the bind group layout uses the content_layer style: binding 0 = tex,
    /// binding 1 = sampler, bindings 2..N = bare content slot textures.
    /// Falls back to name-based detection (`content_slot_*` prefix) for
    /// plans written by older compilers that don't emit this field.
    #[serde(default)]
    requires_content_slots: bool,
    /// Backend dispatcher key from the node manifest. Defaults to
    /// "wgsl_render" so plans written by older compilers that don't emit
    /// this field continue to dispatch through the existing render path.
    /// Phase 3 of the compositor unification epic — see
    /// docs/superpowers/specs/2026-04-12-phase-3-executor-polymorphism-design.md
    #[serde(default = "default_backend")]
    backend: String,
    /// Slot-family routing tag (yt-content-reverie-sierpinski-separation
    /// design 2026-04-21). Only meaningful when `requires_content_slots`
    /// is true. The runtime filters `ContentSourceManager` sources by
    /// this family before binding `content_slot_*` textures, so passes
    /// tagged `youtube_pip` only see YT-slot sources and passes tagged
    /// `narrative` only see narrative sources. Defaults to `"narrative"`
    /// for backward compatibility with plans written before the field
    /// was introduced — matches the legacy global-pool behaviour for
    /// the substrate node (`content_layer`).
    #[serde(default = "default_slot_family")]
    slot_family: String,
}

fn default_output() -> String {
    "final".into()
}

fn default_steps() -> u32 {
    1
}

fn default_backend() -> String {
    "wgsl_render".into()
}

fn default_slot_family() -> String {
    "narrative".into()
}

/// Deserialize a JSON object into HashMap<String, f64>, silently skipping non-numeric values.
fn deserialize_numeric_only<'de, D>(deserializer: D) -> Result<HashMap<String, f64>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let raw: HashMap<String, serde_json::Value> = HashMap::deserialize(deserializer)?;
    Ok(raw
        .into_iter()
        .filter_map(|(k, v)| v.as_f64().map(|n| (k, n)))
        .collect())
}

// --- Uniforms JSON override ---
// The Python modulator writes a flat dict: {"node.param": val, "signal.key": val}
// We parse as HashMap and route signal.* to shared uniforms, node.* to per-pass params.
type UniformsOverride = HashMap<String, f64>;

// --- Pipeline types ---

/// A single pass in the dynamic pipeline.
struct DynamicPass {
    node_id: String,
    render_pipeline: Option<wgpu::RenderPipeline>,
    compute_pipeline: Option<wgpu::ComputePipeline>,
    uniform_bind_group: Option<wgpu::BindGroup>,
    input_bind_group_layout: Option<wgpu::BindGroupLayout>,
    params_buffer: Option<wgpu::Buffer>,
    params_bind_group: Option<wgpu::BindGroup>,
    param_order: Vec<String>,
    current_params: Vec<f32>,
    inputs: Vec<String>,
    output: String,
    steps_per_frame: u32,
    requires_content_slots: bool,
    /// Slot-family routing tag (yt-content-reverie-sierpinski-separation
    /// design 2026-04-21). Forwarded from the plan JSON; the binding
    /// builder uses it to call ``ContentSourceManager::slot_view_for_family``
    /// instead of pulling from the global source pool.
    slot_family: String,
    /// Backend dispatcher key. Phase 3a wires only "wgsl_render" — future
    /// sub-phases (3b/3c/3d) add "cairo", "text", "image_file" branches.
    backend: String,
    /// Render target this pass belongs to. Phase 5b1: every pass is
    /// tagged with the target it serves so the executor can group them
    /// for output binding. Texture names in `inputs` and `output` are
    /// already namespaced by `namespace_texture_name(name, target)`
    /// at build time. Stored for diagnostics + Phase 5b3 host wiring;
    /// the render hot path reads namespaced texture names directly.
    #[allow(dead_code)]
    target: String,
}

/// Rewrite a texture name to be target-namespaced when appropriate.
///
/// Phase 5b1: per-target intermediate textures (`layer_N`, `final`)
/// must be unique across targets. Global pseudo-textures (`@live`,
/// `@accum_*`, `content_slot_*`) and already-namespaced names
/// (anything containing ":") are returned unchanged.
/// LRR Phase 0 item 4 / FINDING-Q step 2 — compute a stable hash of the
/// raw `plan.json` contents. Used by the pre-validation gate's structured
/// log lines so the operator can grep the journal for repeat failures of
/// a specific bad plan.
///
/// Uses `DefaultHasher` over the raw string. Not cryptographic — collisions
/// are fine. Stability across runs of the same `plan_data` is the only
/// load-bearing property.
fn compute_manifest_hash(plan_data: &str) -> String {
    let mut h = DefaultHasher::new();
    plan_data.hash(&mut h);
    format!("{:016x}", h.finish())
}

/// LRR Phase 0 item 4 / FINDING-Q step 2 — validate every pass's shader
/// against naga BEFORE the wgpu hot-reload swap.
///
/// Walks `active_passes` and for each one:
///   1. Reads `<plan_dir>/<plan_pass.shader>`. Read errors are validation
///      failures (the build phase's silent `continue` on read errors was
///      the original FINDING-Q bug — pre-validation catches it).
///   2. Concatenates `SHARED_UNIFORMS_WGSL + "\n" + fragment_source`
///      (matching what the build phase will actually compile) and runs
///      `naga::front::wgsl::parse_str` on it. Naga is the same library
///      wgpu uses internally, so a successful parse here is a strong
///      predictor of a successful pipeline build.
///
/// Returns a `Vec<String>` of failure descriptions. Empty Vec means the
/// plan is safe to swap in. Each failure is "{target}/{node_id}: <reason>"
/// so the operator sees ALL broken passes in one log line, not just the
/// first one.
///
/// This function is pure (no `self`, no `&mut`, no `&wgpu::Device`) so it
/// is unit-testable without a GPU adapter.
fn validate_plan_shaders(
    plan_dir: &Path,
    active_passes: &[(String, PlanPass)],
) -> Vec<String> {
    let mut failures: Vec<String> = Vec::new();
    for (target_name, plan_pass) in active_passes {
        let shader_path = plan_dir.join(&plan_pass.shader);
        let fragment_source = match std::fs::read_to_string(&shader_path) {
            Ok(src) => src,
            Err(e) => {
                failures.push(format!(
                    "{}/{}: shader file unreadable ({:?}): {}",
                    target_name, plan_pass.node_id, shader_path, e
                ));
                continue;
            }
        };
        // Match the build phase's actual compile input: SHARED_UNIFORMS_WGSL
        // is prepended via format! at line 658 (render) / 601 (compute).
        let combined = format!("{}\n{}", SHARED_UNIFORMS_WGSL, fragment_source);
        if let Err(parse_err) = naga::front::wgsl::parse_str(&combined) {
            failures.push(format!(
                "{}/{}: WGSL parse failed: {}",
                target_name,
                plan_pass.node_id,
                parse_err.message()
            ));
        }
    }
    failures
}

fn namespace_texture_name(name: &str, target: &str) -> String {
    if name.contains(':') {
        return name.to_string();
    }
    if name.starts_with('@') {
        // @live, @smooth, @hls, @accum_* — global pseudo-textures.
        return name.to_string();
    }
    if name.starts_with("content_slot_") {
        // Content slot textures are global; populated by the
        // ContentSourceManager and shared across every target.
        return name.to_string();
    }
    format!("{}:{}", target, name)
}

/// Texture name used for the primary target's final output.
///
/// Phase 5b1: ShmOutput, the surface blit, and most fallback lookups
/// previously read `"final"` directly. With multi-target rendering
/// they read `MAIN_FINAL_TEXTURE` instead. v1 plans synthesize a
/// `"main"` target so legacy plans produce this same key.
const MAIN_FINAL_TEXTURE: &str = "main:final";

/// Named texture in the texture pool.
struct PoolTexture {
    texture: wgpu::Texture,
    view: wgpu::TextureView,
}

/// Pick any slot from the slot map whose key is not `exclude`. HashMap
/// iteration order is unspecified, so the caller must not depend on
/// which slot is returned — only that it differs from `exclude`. Used
/// by [`DynamicPipeline::any_intermediate_excluding`] to pick a
/// fallback bind-group input that won't conflict with the same pass's
/// COLOR_TARGET. Free function so it can be unit-tested without a wgpu
/// device.
fn pick_slot_excluding(slots: &HashMap<String, usize>, exclude: &str) -> Option<usize> {
    slots
        .iter()
        .find(|(name, _)| name.as_str() != exclude)
        .map(|(_, slot)| *slot)
}

/// Snapshot of intermediate texture pool state for external observability.
///
/// Returned by [`DynamicPipeline::pool_metrics`]. Closes the §4.7 follow-up
/// from the B4 plan: the underlying [`TransientTexturePool`] already tracked
/// these counters internally; this struct surfaces them so the metrics
/// pipeline (Prometheus exporter, debug overlay, audit scripts) can read
/// them without poking at private fields.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PoolMetrics {
    /// Distinct `(width, height, format)` buckets currently allocated.
    pub bucket_count: usize,
    /// Sum of `bucket.textures.len()` across every bucket — the total
    /// number of GPU textures the pool currently owns.
    pub total_textures: usize,
    /// Lifetime acquire count (every `acquire_tracked` call increments).
    pub total_acquires: u64,
    /// Lifetime fresh-allocation count. `total_acquires - total_allocations`
    /// is the reuse hit count.
    pub total_allocations: u64,
    /// `total_acquires == 0 ? 0.0 : (acquires - allocations) / acquires`.
    /// 1.0 means every acquire was a reuse; 0.0 means every acquire
    /// allocated fresh.
    pub reuse_ratio: f64,
    /// Number of distinct names mapped in `intermediate_slots`. May be
    /// less than `total_textures` if the same descriptor was acquired
    /// multiple times within a frame (each acquisition gets its own slot).
    pub slot_count: usize,
}

pub struct DynamicPipeline {
    passes: Vec<DynamicPass>,
    /// Bucketed allocator for non-temporal intermediate textures. F1 of the
    /// compositor unification epic landed this pool standalone (PR #670);
    /// B4 wires it into the executor. Today every intermediate shares one
    /// descriptor, so the pool resolves to a single bucket per
    /// `intermediate_pool_key`.
    intermediate_pool: TransientTexturePool<PoolTexture>,
    /// Single bucket key derived from `(width, height, TEXTURE_FORMAT)` at
    /// `new()` and `resize()` time. When the Python compile phase emits
    /// per-stage `pool_key` values, this collapses to a per-call lookup.
    intermediate_pool_key: u64,
    /// Name → slot index map. Replaces the old
    /// `textures: HashMap<String, PoolTexture>` lookup; the pool owns the
    /// textures themselves now and `intermediate()` resolves through this
    /// map. Names are still meaningful (e.g. `"@live"`, `"main:final"`,
    /// `"@accum_*"` callers) — the slot indirection is purely an
    /// allocation strategy.
    intermediate_slots: HashMap<String, usize>,
    /// Temporal feedback textures. Intentionally NOT pooled — they
    /// persist across frames and are cleared, not recycled. Keyed by
    /// `node_id` because `@accum_{node_id}` is the reference convention
    /// the Python compiler emits.
    temporal_textures: HashMap<String, PoolTexture>,
    uniform_buffer: UniformBuffer,
    shm_output: ShmOutput,
    pending_reload: Arc<AtomicBool>,
    _watcher: RecommendedWatcher,
    plan_dir: PathBuf,
    vertex_module: wgpu::ShaderModule,
    sampler: wgpu::Sampler,
    input_bind_group_layouts: HashMap<usize, wgpu::BindGroupLayout>,
    blit_pipeline: wgpu::RenderPipeline,
    blit_bind_group_layout: wgpu::BindGroupLayout,
    params_bind_group: wgpu::BindGroup,
    params_bind_group_layout: wgpu::BindGroupLayout,
    #[allow(dead_code)]
    surface_format: wgpu::TextureFormat,
    width: u32,
    height: u32,
    frame_count: u64,
    /// Phase 3 3D: true when an external texture was injected as @live
    /// this frame; suppresses the procedural noise fallback.
    live_texture_overridden: bool,
    /// LRR Phase 0 item 4 / FINDING-Q step 4 — counter for shader hot-reload
    /// rollback events. Incremented every time the validation gate rejects
    /// a hot-reload attempt or a runtime panic forces a rollback to the
    /// last-known-good plan. Surfaced via `shader_rollback_total()` and
    /// published over the imagination → compositor SHM bridge so
    /// `hapax_imagination_shader_rollback_total` lands on Prometheus
    /// alongside the existing `reverie_pool_*` gauges.
    ///
    /// Wrapped in `Arc` to match the existing `pending_reload` pattern;
    /// the watcher closure can clone the Arc if it ever needs to bump the
    /// counter from outside the render thread.
    ///
    /// Today (PR #788) the counter exists but no code path increments it.
    /// PR #3a wires the validation gate; PR #3b wires the runtime-panic
    /// rollback. See the spike doc at
    /// `docs/superpowers/specs/2026-04-14-lrr-phase-0-finding-q-spike-notes.md`
    /// for the design rationale and recommended PR sequence.
    shader_rollback_total: Arc<AtomicU64>,
}

impl DynamicPipeline {
    pub fn new(device: &wgpu::Device, _queue: &wgpu::Queue, width: u32, height: u32, surface_format: wgpu::TextureFormat) -> Self {
        let uniform_buffer = UniformBuffer::new(device);
        let shm_output = ShmOutput::new(device, width, height);

        // Compile shared vertex module (vertex + uniforms combined)
        let vertex_source = format!("{}\n{}", SHARED_UNIFORMS_WGSL, SHARED_VERTEX_WGSL);
        let vertex_module = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("fullscreen_quad vertex"),
            source: wgpu::ShaderSource::Wgsl(vertex_source.into()),
        });

        let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("dynamic pipeline sampler"),
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            ..Default::default()
        });

        // Blit pipeline: copies a texture to the surface
        let blit_bind_group_layout =
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: Some("blit bgl"),
                entries: &[
                    wgpu::BindGroupLayoutEntry {
                        binding: 0,
                        visibility: wgpu::ShaderStages::FRAGMENT,
                        ty: wgpu::BindingType::Texture {
                            sample_type: wgpu::TextureSampleType::Float { filterable: true },
                            view_dimension: wgpu::TextureViewDimension::D2,
                            multisampled: false,
                        },
                        count: None,
                    },
                    wgpu::BindGroupLayoutEntry {
                        binding: 1,
                        visibility: wgpu::ShaderStages::FRAGMENT,
                        ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                        count: None,
                    },
                ],
            });

        let blit_shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("blit shader"),
            source: wgpu::ShaderSource::Wgsl(BLIT_WGSL.into()),
        });

        let blit_pipeline_layout =
            device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
                label: Some("blit pipeline layout"),
                bind_group_layouts: &[&blit_bind_group_layout],
                push_constant_ranges: &[],
            });

        let blit_pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("blit pipeline"),
            layout: Some(&blit_pipeline_layout),
            vertex: wgpu::VertexState {
                module: &blit_shader,
                entry_point: Some("vs_main"),
                buffers: &[],
                compilation_options: Default::default(),
            },
            fragment: Some(wgpu::FragmentState {
                module: &blit_shader,
                entry_point: Some("main"),
                targets: &[Some(wgpu::ColorTargetState {
                    format: surface_format,
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

        // File watcher
        let pending = Arc::new(AtomicBool::new(false));
        let pending_clone = pending.clone();

        let mut watcher =
            notify::recommended_watcher(move |res: Result<Event, notify::Error>| {
                if let Ok(event) = res {
                    if matches!(event.kind, EventKind::Modify(_) | EventKind::Create(_)) {
                        pending_clone.store(true, Ordering::Relaxed);
                    }
                }
            })
            .expect("failed to create file watcher");

        // Watch plan directory (may not exist yet)
        let plan_dir = PathBuf::from(PLAN_DIR);
        std::fs::create_dir_all(&plan_dir).ok();
        watcher
            .watch(&plan_dir, notify::RecursiveMode::NonRecursive)
            .ok();

        // Dummy per-node params UBO (group 2) — 256 bytes of zeros
        let params_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("per-node params"),
            contents: &[0u8; 256],
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });
        let params_bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("per-node params layout"),
            entries: &[wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            }],
        });
        let params_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("per-node params bg"),
            layout: &params_bgl,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: params_buffer.as_entire_binding(),
            }],
        });

        let intermediate_pool_key = compute_pool_key(width, height, TEXTURE_FORMAT);

        let mut pipeline = Self {
            passes: Vec::new(),
            intermediate_pool: TransientTexturePool::new(),
            intermediate_pool_key,
            intermediate_slots: HashMap::new(),
            temporal_textures: HashMap::new(),
            uniform_buffer,
            shm_output,
            pending_reload: pending,
            _watcher: watcher,
            plan_dir,
            vertex_module,
            sampler,
            input_bind_group_layouts: HashMap::new(),
            blit_pipeline,
            blit_bind_group_layout,
            params_bind_group,
            params_bind_group_layout: params_bgl,
            surface_format,
            width,
            height,
            frame_count: 0,
            live_texture_overridden: false,
            shader_rollback_total: Arc::new(AtomicU64::new(0)),
        };

        // Try loading existing plan
        if Path::new(PLAN_FILE).exists() {
            pipeline.pending_reload.store(true, Ordering::Relaxed);
            pipeline.try_reload(device);
        }

        // Phase 5b1: ensure the main target's final texture exists even
        // with no plan loaded. The blit + ShmOutput paths read this name.
        pipeline.ensure_texture(device, MAIN_FINAL_TEXTURE);

        pipeline
    }

    /// Check for pending plan changes and reload if needed. Returns true if reloaded.
    pub fn try_reload(&mut self, device: &wgpu::Device) -> bool {
        if !self.pending_reload.swap(false, Ordering::Relaxed) {
            return false;
        }

        let plan_data = match std::fs::read_to_string(PLAN_FILE) {
            Ok(data) => data,
            Err(e) => {
                log::warn!("dynamic_pipeline: failed to read plan.json: {}", e);
                return false;
            }
        };

        let plan: PlanFile = match serde_json::from_str(&plan_data) {
            Ok(p) => p,
            Err(e) => {
                log::warn!("dynamic_pipeline: failed to parse plan.json: {}", e);
                return false;
            }
        };

        // Phase 5b1: walk every target in the v2 plan. The
        // passes_by_target() helper collapses v1 (flat passes) into
        // a synthetic "main" target, so legacy plans hit this path
        // unchanged. Each target's passes are tagged with the target
        // name and have their texture references namespaced
        // (`layer_N` → `{target}:layer_N`, `final` → `{target}:final`).
        let by_target = plan.passes_by_target();

        if by_target.values().all(|v| v.is_empty()) {
            self.passes.clear();
            log::info!("dynamic_pipeline: loaded empty plan (renders black)");
            return true;
        }

        // Build a flat list of (target, pass-with-rewritten-textures) tuples
        // so the build phase below can iterate uniformly. The render loop
        // walks the resulting flat list — texture naming carries the per-
        // target separation.
        let mut active_passes: Vec<(String, PlanPass)> = Vec::new();
        // Iterate target keys in deterministic (sorted) order so the build
        // order is reproducible across runs and matches Python's stable
        // target iteration in Phase 5a.
        let mut target_keys: Vec<String> = by_target.keys().cloned().collect();
        target_keys.sort();
        for target_name in &target_keys {
            for plan_pass in by_target.get(target_name).unwrap_or(&Vec::new()) {
                let mut rewritten = plan_pass.clone();
                rewritten.inputs = rewritten
                    .inputs
                    .into_iter()
                    .map(|n| namespace_texture_name(&n, target_name))
                    .collect();
                rewritten.output = namespace_texture_name(&rewritten.output, target_name);
                active_passes.push((target_name.clone(), rewritten));
            }
        }

        // LRR Phase 0 item 4 / FINDING-Q step 2 — pre-validation gate.
        //
        // Before any side effects (texture allocation, pool acquisition,
        // wgpu pipeline construction), validate every pass's shader file
        // via the pure helper `validate_plan_shaders`. The helper is
        // pure (takes refs, no device, no self) so it's unit-testable
        // without spinning up a wgpu adapter.
        //
        // On any failure: increment shader_rollback_total, log a
        // structured warning with the manifest hash, and return false
        // WITHOUT touching self.passes — the previous good plan keeps
        // rendering. Manifest hash is stable across runs of the same
        // plan_data so the operator can grep the journal for repeat
        // failures.
        let manifest_hash = compute_manifest_hash(&plan_data);
        let validation_failures = validate_plan_shaders(&self.plan_dir, &active_passes);
        if !validation_failures.is_empty() {
            self.shader_rollback_total.fetch_add(1, Ordering::Relaxed);
            log::warn!(
                "dynamic_pipeline: hot-reload REJECTED, manifest_hash={}, {} pass(es) failed validation: {}",
                manifest_hash,
                validation_failures.len(),
                validation_failures.join("; ")
            );
            return false;
        }

        // Collect all texture names referenced in the plan (already
        // namespaced).
        let mut texture_names: Vec<String> = Vec::new();
        for (_target, pass) in &active_passes {
            for input in &pass.inputs {
                if !texture_names.contains(input) {
                    texture_names.push(input.clone());
                }
            }
            if !texture_names.contains(&pass.output) {
                texture_names.push(pass.output.clone());
            }
        }

        // Ensure all textures exist in the pool
        for name in &texture_names {
            self.ensure_texture(device, name);
        }

        // Ensure temporal textures for feedback nodes (@accum_ inputs).
        // Temporal textures are NOT namespaced — they're keyed by node_id
        // alone, which matches the @accum_{node_id} reference convention
        // emitted by the Python compiler. Cross-target sharing of the
        // same temporal node is a known limitation; the current
        // vocabulary is single-target so this is a non-issue today.
        for (_target, pass) in &active_passes {
            if pass.inputs.iter().any(|n| n.starts_with("@accum_")) {
                self.ensure_temporal_texture(device, &pass.node_id);
            }
        }

        // Build passes
        let mut new_passes = Vec::new();
        let mut input_layouts = HashMap::new();

        for (target_name, plan_pass) in &active_passes {
            let shader_path = self.plan_dir.join(&plan_pass.shader);
            let fragment_source = match std::fs::read_to_string(&shader_path) {
                Ok(src) => src,
                Err(e) => {
                    log::warn!(
                        "dynamic_pipeline: failed to read shader {:?}: {}",
                        shader_path,
                        e
                    );
                    continue;
                }
            };

            let input_count = plan_pass.inputs.len();

            if plan_pass.pass_type == "compute" {
                // Compute pass
                let compute_source = format!("{}\n{}", SHARED_UNIFORMS_WGSL, fragment_source);
                let compute_module =
                    device.create_shader_module(wgpu::ShaderModuleDescriptor {
                        label: Some(&plan_pass.node_id),
                        source: wgpu::ShaderSource::Wgsl(compute_source.into()),
                    });

                let input_bgl = Self::get_or_create_input_layout(device, input_count, &plan_pass.inputs, &mut input_layouts);
                let storage_bgl = Self::create_storage_texture_layout(device);

                let pipeline_layout =
                    device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
                        label: Some(&format!("{} layout", plan_pass.node_id)),
                        bind_group_layouts: &[
                            &self.uniform_buffer.bind_group_layout,
                            &input_bgl,
                            &storage_bgl,
                        ],
                        push_constant_ranges: &[],
                    });

                let compute_pipeline =
                    device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
                        label: Some(&plan_pass.node_id),
                        layout: Some(&pipeline_layout),
                        module: &compute_module,
                        entry_point: Some("cs_main"),
                        compilation_options: Default::default(),
                        cache: None,
                    });

                new_passes.push(DynamicPass {
                    node_id: plan_pass.node_id.clone(),
                    render_pipeline: None,
                    compute_pipeline: Some(compute_pipeline),
                    uniform_bind_group: None,
                    input_bind_group_layout: None,
                    params_buffer: None,
                    params_bind_group: None,
                    param_order: plan_pass.param_order.clone(),
                    current_params: {
                        let mut v: Vec<f32> = plan_pass.param_order.iter()
                            .map(|name| plan_pass.uniforms.get(name).copied().unwrap_or(0.0) as f32)
                            .collect();
                        while v.len() < 4 { v.push(0.0); }
                        while !(v.len() * 4).is_multiple_of(16) { v.push(0.0); }
                        v
                    },
                    inputs: plan_pass.inputs.clone(),
                    output: plan_pass.output.clone(),
                    steps_per_frame: plan_pass.steps_per_frame,
                    requires_content_slots: plan_pass.requires_content_slots,
                    slot_family: plan_pass.slot_family.clone(),
                    backend: plan_pass.backend.clone(),
                    target: target_name.clone(),
                });
            } else {
                // Render pass
                let combined_source = format!("{}\n{}", SHARED_UNIFORMS_WGSL, fragment_source);
                let fragment_module =
                    device.create_shader_module(wgpu::ShaderModuleDescriptor {
                        label: Some(&plan_pass.node_id),
                        source: wgpu::ShaderSource::Wgsl(combined_source.into()),
                    });

                let input_bgl = Self::get_or_create_input_layout(device, input_count, &plan_pass.inputs, &mut input_layouts);

                // Conditionally include group 2 (per-node params) only if shader has scalar uniforms
                let has_params = !plan_pass.param_order.is_empty();
                let pipeline_layout = if has_params {
                    device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
                        label: Some(&format!("{} layout", plan_pass.node_id)),
                        bind_group_layouts: &[
                            &self.uniform_buffer.bind_group_layout,
                            &input_bgl,
                            &self.params_bind_group_layout,
                        ],
                        push_constant_ranges: &[],
                    })
                } else {
                    device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
                        label: Some(&format!("{} layout", plan_pass.node_id)),
                        bind_group_layouts: &[
                            &self.uniform_buffer.bind_group_layout,
                            &input_bgl,
                        ],
                        push_constant_ranges: &[],
                    })
                };
                let render_pipeline =
                    device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                        label: Some(&plan_pass.node_id),
                        layout: Some(&pipeline_layout),
                        vertex: wgpu::VertexState {
                            module: &self.vertex_module,
                            entry_point: Some("vs_main"),
                            buffers: &[],
                            compilation_options: Default::default(),
                        },
                        fragment: Some(wgpu::FragmentState {
                            module: &fragment_module,
                            entry_point: Some("main"),
                            targets: &[Some(wgpu::ColorTargetState {
                                format: TEXTURE_FORMAT,
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

                // Create per-node params buffer if shader has scalar uniforms
                let (pbuf, pbg) = if has_params {
                    let mut data: Vec<f32> = Vec::new();
                    for name in &plan_pass.param_order {
                        let val = plan_pass.uniforms.get(name).copied().unwrap_or(0.0) as f32;
                        data.push(val);
                    }
                    while data.len() < 4 { data.push(0.0); }
                    while !(data.len() * 4).is_multiple_of(16) { data.push(0.0); }

                    let buf = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                        label: Some(&format!("{} params", plan_pass.node_id)),
                        contents: bytemuck::cast_slice(&data),
                        usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                    });
                    let bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
                        label: Some(&format!("{} params bg", plan_pass.node_id)),
                        layout: &self.params_bind_group_layout,
                        entries: &[wgpu::BindGroupEntry {
                            binding: 0,
                            resource: buf.as_entire_binding(),
                        }],
                    });
                    (Some(buf), Some(bg))
                } else {
                    (None, None)
                };

                new_passes.push(DynamicPass {
                    node_id: plan_pass.node_id.clone(),
                    render_pipeline: Some(render_pipeline),
                    compute_pipeline: None,
                    uniform_bind_group: None,
                    input_bind_group_layout: None,
                    params_buffer: pbuf,
                    params_bind_group: pbg,
                    param_order: plan_pass.param_order.clone(),
                    current_params: {
                        let mut v: Vec<f32> = plan_pass.param_order.iter()
                            .map(|name| plan_pass.uniforms.get(name).copied().unwrap_or(0.0) as f32)
                            .collect();
                        while v.len() < 4 { v.push(0.0); }
                        while !(v.len() * 4).is_multiple_of(16) { v.push(0.0); }
                        v
                    },
                    inputs: plan_pass.inputs.clone(),
                    output: plan_pass.output.clone(),
                    steps_per_frame: plan_pass.steps_per_frame,
                    requires_content_slots: plan_pass.requires_content_slots,
                    slot_family: plan_pass.slot_family.clone(),
                    backend: plan_pass.backend.clone(),
                    target: target_name.clone(),
                });
            }
        }

        self.input_bind_group_layouts = input_layouts;
        let count = new_passes.len();
        self.passes = new_passes;
        log::info!("dynamic_pipeline: loaded {} passes", count);
        true
    }

    /// Render a frame: reload if pending, build uniforms, execute passes, blit to surface, shm output.
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
        content_sources: Option<&ContentSourceManager>,
    ) {
        self.try_reload(device);

        // Build uniform data from state
        let mut uniform_data =
            UniformBuffer::from_state(state_reader, time, dt, self.width, self.height);

        uniform_data.slot_opacities = content_slot_opacities;

        // Apply uniforms.json signal overrides (flat dict from Python modulator)
        // Format: {"signal.key": val, "node.param": val}
        if let Ok(data) = std::fs::read_to_string(UNIFORMS_JSON) {
            if let Ok(overrides) = serde_json::from_str::<UniformsOverride>(&data) {
                // F7 — signal.{9dim} is a dormant override hook.
                // ``signal.color_warmth`` is the only key Python
                // currently writes (``agents/reverie/_uniforms.py``);
                // the other 12 arms exist so the visual chain *could*
                // override DMN-state-sourced dimensions when the
                // reverie mixer has an opinion. The primary path for
                // the 9 dimensions is alive via
                // ``UniformBuffer::from_state`` reading from
                // ``StateReader.imagination.dimensions`` — these arms
                // would override that read on a per-frame basis if
                // anything wrote them. They are kept rather than
                // pruned because the override capability is part of
                // the chain → GPU contract; pruning would require
                // re-adding them when the visual chain wants to drive
                // a dimension directly. See F7 in the 2026-04-12
                // beta session 3 retirement handoff.
                for (key, &val) in &overrides {
                    if let Some(signal) = key.strip_prefix("signal.") {
                        let v = val as f32;
                        match signal {
                            "color_warmth" => uniform_data.color_warmth = v,
                            "speed" => uniform_data.speed = v,
                            "turbulence" => uniform_data.turbulence = v,
                            "brightness" => uniform_data.brightness = v,
                            "intensity" => uniform_data.intensity = v,
                            "tension" => uniform_data.tension = v,
                            "depth" => uniform_data.depth = v,
                            "coherence" => uniform_data.coherence = v,
                            "spectral_color" => uniform_data.spectral_color = v,
                            "temporal_distortion" => uniform_data.temporal_distortion = v,
                            "degradation" => uniform_data.degradation = v,
                            "pitch_displacement" => uniform_data.pitch_displacement = v,
                            "diffusion" => uniform_data.diffusion = v,
                            _ => {
                                if let Some(rest) = signal.strip_prefix("homage_custom_") {
                                    let mut parts = rest.splitn(2, '_');
                                    if let (Some(slot_s), Some(comp_s)) =
                                        (parts.next(), parts.next())
                                    {
                                        if let (Ok(slot), Ok(comp)) =
                                            (slot_s.parse::<usize>(), comp_s.parse::<usize>())
                                        {
                                            if slot < 8 && comp < 4 {
                                                uniform_data.custom[slot][comp] = v;
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    } else if let Some(content) = key.strip_prefix("content.") {
                        // F8: content_layer.wgsl has no @group(2) Params
                        // binding (it composites 4 content slots and
                        // reads its material/salience/intensity knobs
                        // from uniforms.custom[0]). The per-node
                        // params_buffer path skips it. Route the three
                        // content.* keys into custom[0][0..2] so
                        // Bachelard Amendment 3 (material quality) is
                        // actually reachable at runtime. Python writes
                        // these keys as floats already (see
                        // agents/reverie/_uniforms.py MATERIAL_MAP).
                        let v = val as f32;
                        match content {
                            "material" => uniform_data.custom[0][0] = v,
                            "salience" => uniform_data.custom[0][1] = v,
                            "intensity" => uniform_data.custom[0][2] = v,
                            _ => {}
                        }
                    }
                }

                // Apply per-node param overrides from uniforms.json
                for pass in &mut self.passes {
                    if pass.params_buffer.is_none() || pass.param_order.is_empty() {
                        continue;
                    }
                    let mut updated = false;
                    for (i, name) in pass.param_order.iter().enumerate() {
                        if i >= pass.current_params.len() {
                            break;
                        }
                        let key = format!("{}.{}", pass.node_id, name);
                        if let Some(&val) = overrides.get(&key) {
                            let v = val as f32;
                            if (pass.current_params[i] - v).abs() > f32::EPSILON {
                                pass.current_params[i] = v;
                                updated = true;
                            }
                        }
                    }
                    if updated {
                        if let Some(ref buf) = pass.params_buffer {
                            queue.write_buffer(buf, 0, bytemuck::cast_slice(&pass.current_params));
                        }
                    }
                }
            }
        }

        self.uniform_buffer.update(queue, &uniform_data);

        let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
            label: Some("dynamic pipeline"),
        });

        if self.passes.is_empty() {
            // No plan: clear to black
            {
                let _pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                    label: Some("clear"),
                    color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                        view: surface_view,
                        resolve_target: None,
                        ops: wgpu::Operations {
                            load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                            store: wgpu::StoreOp::Store,
                        },
                    })],
                    depth_stencil_attachment: None,
                    ..Default::default()
                });
            }
            queue.submit(std::iter::once(encoder.finish()));
            return;
        }

        // If any pass references @live but no external source populates it,
        // fill it with a procedural gradient so shaders have visible input.
        // Without this, @live resolves to a black texture and the entire
        // pipeline produces near-black output.
        // Phase 3 3D: skip noise if set_live_texture_override() was called
        // this frame — the 3D scene output is already in @live.
        let needs_live = self.passes.iter().any(|p| p.inputs.iter().any(|i| i == "@live"));
        if needs_live && !self.live_texture_overridden {
            self.ensure_texture(device, "@live");
            if let Some(live_tex) = self.intermediate("@live") {
                let w = self.width as usize;
                let h = self.height as usize;
                let mut pixels = vec![0u8; w * h * 4];
                let t = time;

                // Simple hash-based noise (cheaper than proper FBM but visually rich)
                #[inline]
                fn hash(x: f32, y: f32) -> f32 {
                    // Two-axis hash — avoids diagonal correlation from single dot product
                    let h = ((x * 127.1 + y * 311.7).sin() * 43758.547
                        + (x * 269.5 + y * 183.3).cos() * 28_461.32)
                        * 0.5;
                    h - h.floor()
                }
                #[inline]
                fn noise(x: f32, y: f32) -> f32 {
                    let ix = x.floor();
                    let iy = y.floor();
                    let fx = x - ix;
                    let fy = y - iy;
                    let sx = fx * fx * (3.0 - 2.0 * fx);
                    let sy = fy * fy * (3.0 - 2.0 * fy);
                    let a = hash(ix, iy);
                    let b = hash(ix + 1.0, iy);
                    let c = hash(ix, iy + 1.0);
                    let d = hash(ix + 1.0, iy + 1.0);
                    a + (b - a) * sx + (c - a) * sy + (a - b - c + d) * sx * sy
                }
                fn fbm(mut x: f32, mut y: f32, octaves: u32) -> f32 {
                    let mut v = 0.0f32;
                    let mut a = 0.5f32;
                    for _ in 0..octaves {
                        v += a * noise(x, y);
                        x = x * 2.0 + 100.0;
                        y = y * 2.0 + 100.0;
                        a *= 0.5;
                    }
                    v
                }

                for y in 0..h {
                    for x in 0..w {
                        let u = x as f32 / w as f32 * 4.0;
                        let v = y as f32 / h as f32 * 3.0;
                        // Three FBM layers at different scales, offsets, and time rates
                        // to produce rich, non-diagonal noise patterns
                        let n1 = fbm(u * 3.0 + t * 0.08 + 17.3, v * 2.5 - t * 0.05 + 41.7, 5);
                        let n2 = fbm(v * 2.0 + t * 0.03 + 89.1, u * 3.5 - t * 0.07 + 63.2, 4);
                        let n3 = fbm(u * 1.5 + v * 1.5 + t * 0.04 + 137.0, u * 1.0 - v * 2.0 + t * 0.02 + 211.0, 4);
                        let r = (n1 * 0.8 + n2 * 0.4 + 0.3).clamp(0.0, 1.0);
                        let g = (n2 * 0.7 + n3 * 0.3 + 0.25).clamp(0.0, 1.0);
                        let b_val = (n3 * 0.6 + n1 * 0.3 + 0.3).clamp(0.0, 1.0);
                        let idx = (y * w + x) * 4;
                        pixels[idx] = (r * 255.0) as u8;
                        pixels[idx + 1] = (g * 255.0) as u8;
                        pixels[idx + 2] = (b_val * 255.0) as u8;
                        pixels[idx + 3] = 255;
                    }
                }
                queue.write_texture(
                    wgpu::TexelCopyTextureInfo {
                        texture: &live_tex.texture,
                        mip_level: 0,
                        origin: wgpu::Origin3d::ZERO,
                        aspect: wgpu::TextureAspect::All,
                    },
                    &pixels,
                    wgpu::TexelCopyBufferLayout {
                        offset: 0,
                        bytes_per_row: Some((w * 4) as u32),
                        rows_per_image: Some(h as u32),
                    },
                    wgpu::Extent3d {
                        width: self.width,
                        height: self.height,
                        depth_or_array_layers: 1,
                    },
                );
            }
        }

        // Execute each pass
        for pass in &self.passes {
            // Backend dispatch (Phase 3a/3b). Today wgsl_render falls through
            // to the existing render/compute path below; cairo content is
            // uploaded by the Python CairoSourceRunner via ContentSourceManager
            // and consumed by content_layer/sierpinski_content (which are
            // wgsl_render passes themselves), so the cairo arm is currently
            // a no-op observer. Future sub-phases (3c text, 3d image_file)
            // add branches here. Unknown backends are logged at debug level
            // and skipped — a misconfigured manifest cannot crash the
            // pipeline.
            match pass.backend.as_str() {
                "wgsl_render" => {
                    // Existing path — falls through to the render/compute
                    // dispatch below.
                }
                "cairo" => {
                    // Phase 3b: Python CairoSourceRunner publishes RGBA via
                    // the source protocol; the wgsl pass that consumes the
                    // content reads it via content_slot_*. Nothing to do at
                    // dispatch time today.
                    log::trace!(
                        "dynamic_pipeline: cairo backend pass '{}' (no-op observer)",
                        pass.node_id,
                    );
                    continue;
                }
                other => {
                    // Audit follow-up: was `log::debug!`, which hid the
                    // fact that the pipeline JSON had referenced a
                    // backend the executor doesn't implement — the user
                    // saw a black frame with no explanation. Warn so
                    // schema-to-executor drift surfaces immediately.
                    log::warn!(
                        "dynamic_pipeline: skipping pass '{}' with unknown backend '{}' \
                         (output will be black for this pass)",
                        pass.node_id,
                        other,
                    );
                    continue;
                }
            }

            let is_temporal = pass.inputs.iter().any(|n| n.starts_with("@accum_"));

            if let Some(ref render_pipeline) = pass.render_pipeline {
                let input_bind_group = self.create_input_bind_group(
                    device,
                    &pass.inputs,
                    &pass.output,
                    pass.requires_content_slots,
                    &pass.slot_family,
                    &pass.node_id,
                    content_sources,
                );

                // Resolve output texture view
                let output_view = match self.intermediate(&pass.output) {
                    Some(tex) => &tex.view,
                    None => continue,
                };

                {
                    let mut rpass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                        label: Some(&pass.node_id),
                        color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                            view: output_view,
                            resolve_target: None,
                            ops: wgpu::Operations {
                                load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                                store: wgpu::StoreOp::Store,
                            },
                        })],
                        depth_stencil_attachment: None,
                        ..Default::default()
                    });

                    rpass.set_pipeline(render_pipeline);
                    rpass.set_bind_group(0, &self.uniform_buffer.bind_group, &[]);
                    rpass.set_bind_group(1, &input_bind_group, &[]);
                    if let Some(ref pbg) = pass.params_bind_group {
                        rpass.set_bind_group(2, pbg, &[]);
                    }
                    rpass.draw(0..3, 0..1);
                } // render pass dropped here

                // Copy output to temporal buffer for next frame's feedback
                if is_temporal {
                    if let (Some(src), Some(dst)) = (
                        self.intermediate(&pass.output),
                        self.temporal_textures.get(&pass.node_id),
                    ) {
                        let copy_size = wgpu::Extent3d {
                            width: self.width,
                            height: self.height,
                            depth_or_array_layers: 1,
                        };
                        encoder.copy_texture_to_texture(
                            src.texture.as_image_copy(),
                            dst.texture.as_image_copy(),
                            copy_size,
                        );
                    }
                }
            } else if let Some(ref compute_pipeline) = pass.compute_pipeline {
                let input_bind_group = self.create_input_bind_group(
                    device,
                    &pass.inputs,
                    &pass.output,
                    pass.requires_content_slots,
                    &pass.slot_family,
                    &pass.node_id,
                    content_sources,
                );
                let storage_bind_group =
                    self.create_storage_bind_group(device, &pass.output);

                let workgroups_x = self.width.div_ceil(8);
                let workgroups_y = self.height.div_ceil(8);

                for _ in 0..pass.steps_per_frame {
                    let mut cpass =
                        encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
                            label: Some(&pass.node_id),
                            timestamp_writes: None,
                        });

                    cpass.set_pipeline(compute_pipeline);
                    cpass.set_bind_group(0, &self.uniform_buffer.bind_group, &[]);
                    cpass.set_bind_group(1, &input_bind_group, &[]);
                    cpass.set_bind_group(2, &storage_bind_group, &[]);
                    cpass.dispatch_workgroups(workgroups_x, workgroups_y, 1);
                }
            }
        }

        // Blit the main target's final texture to the surface.
        // Phase 5b1: with multi-target rendering, the surface always
        // shows the "main" target. Other targets render their own
        // outputs accessible via get_target_output_view().
        if let Some(final_tex) = self.intermediate(MAIN_FINAL_TEXTURE) {
            let blit_bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some("blit bind group"),
                layout: &self.blit_bind_group_layout,
                entries: &[
                    wgpu::BindGroupEntry {
                        binding: 0,
                        resource: wgpu::BindingResource::TextureView(&final_tex.view),
                    },
                    wgpu::BindGroupEntry {
                        binding: 1,
                        resource: wgpu::BindingResource::Sampler(&self.sampler),
                    },
                ],
            });

            // The blit pipeline was created with TEXTURE_FORMAT but we need to render to the
            // actual surface format. Create an ad-hoc blit pass that targets surface_view.
            // For now, use a simple render pass with the existing blit pipeline if formats match,
            // otherwise clear black as fallback.
            let mut rpass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("blit to surface"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: surface_view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: None,
                ..Default::default()
            });

            // The blit pipeline targets TEXTURE_FORMAT which should match surface sRGB
            rpass.set_pipeline(&self.blit_pipeline);
            rpass.set_bind_group(0, &blit_bg, &[]);
            rpass.draw(0..3, 0..1);
        }

        // Copy the main target's final texture to SHM output every
        // other frame to save bandwidth. Phase 5b1: SHM consumers
        // (the visual surface frame.jpg path) always read the main
        // target — additional targets aren't routed through SHM.
        if self.frame_count.is_multiple_of(2) {
            if let Some(final_tex) = self.intermediate(MAIN_FINAL_TEXTURE) {
                self.shm_output
                    .copy_to_staging(&mut encoder, &final_tex.texture);
            }
        }

        queue.submit(std::iter::once(encoder.finish()));

        // Write SHM frame (every other frame)
        if self.frame_count.is_multiple_of(2) {
            self.shm_output.write_frame(device);
        }

        self.frame_count += 1;
        self.live_texture_overridden = false;
    }

    /// Return the texture view for a given target's final output, if any.
    ///
    /// Phase 5b1: future host wiring (5b3 OutputRouter) calls this to
    /// route the appropriate render target to the appropriate sink
    /// (v4l2, NDI, winit window, etc.). Returns None if the target
    /// doesn't exist in the current plan or hasn't rendered yet.
    pub fn get_target_output_view(&self, target: &str) -> Option<&wgpu::TextureView> {
        let key = format!("{}:final", target);
        self.intermediate(&key).map(|t| &t.view)
    }

    /// Return the list of target names currently present in the plan.
    ///
    /// Walks the slot map for `*:final` keys, which are the canonical
    /// "this target is live" indicator.
    pub fn target_names(&self) -> Vec<String> {
        let mut names: Vec<String> = self
            .intermediate_names()
            .filter_map(|k| k.strip_suffix(":final").map(str::to_string))
            .collect();
        names.sort();
        names
    }

    /// Snapshot of intermediate texture pool counters.
    ///
    /// Surfaces the bookkeeping `TransientTexturePool` already tracks
    /// internally so external callers (Prometheus exporter, debug
    /// overlay, audit scripts) can read them without reaching into
    /// private fields. Closes the §4.7 deferred follow-up from the
    /// B4 plan.
    ///
    /// `reuse_ratio` will report 0.0 against an empty pool — see
    /// `TransientTexturePool::reuse_ratio` for the rationale.
    pub fn pool_metrics(&self) -> PoolMetrics {
        PoolMetrics {
            bucket_count: self.intermediate_pool.bucket_count(),
            total_textures: self.intermediate_pool.total_textures(),
            total_acquires: self.intermediate_pool.total_acquires(),
            total_allocations: self.intermediate_pool.total_allocations(),
            reuse_ratio: self.intermediate_pool.reuse_ratio(),
            slot_count: self.intermediate_slots.len(),
        }
    }

    /// Phase 3 3D compositor: inject an external texture as the `@live`
    /// pseudo-texture. When set, the noise-generator fallback in
    /// `render()` is skipped and the provided texture view is used
    /// directly as shader input. The 3D SceneRenderer output feeds
    /// through the full shader vocabulary chain this way.
    ///
    /// Call with `None` to revert to the default noise `@live`.
    pub fn set_live_texture_override(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        source_texture: &wgpu::Texture,
    ) {
        self.ensure_texture(device, "@live");
        if let Some(live_tex) = self.intermediate("@live") {
            let size = wgpu::Extent3d {
                width: self.width.min(source_texture.width()),
                height: self.height.min(source_texture.height()),
                depth_or_array_layers: 1,
            };
            // GPU-side copy from the 3D scene output into @live
            let mut encoder = device.create_command_encoder(
                &wgpu::CommandEncoderDescriptor {
                    label: Some("inject @live from 3D scene"),
                },
            );
            encoder.copy_texture_to_texture(
                source_texture.as_image_copy(),
                live_tex.texture.as_image_copy(),
                size,
            );
            queue.submit(std::iter::once(encoder.finish()));
            self.live_texture_overridden = true;
        }
    }

    /// LRR Phase 0 item 4 / FINDING-Q step 4 — read the shader rollback
    /// counter. Returns the cumulative count of hot-reload validation
    /// failures + runtime-panic rollbacks since process start.
    ///
    /// Today (PR #788) this always returns 0 because no code path
    /// increments the counter yet. PR #3a wires the validation gate at
    /// `try_reload`; PR #3b wires the runtime-panic rollback. The getter
    /// exists so the imagination → compositor SHM publisher can pick up
    /// the value via a stable API once those PRs land.
    pub fn shader_rollback_total(&self) -> u64 {
        self.shader_rollback_total.load(Ordering::Relaxed)
    }

    pub fn resize(&mut self, device: &wgpu::Device, width: u32, height: u32) {
        self.width = width;
        self.height = height;

        // Recreate the bucket key for the new dimensions — the old key
        // hashed the previous (width, height) and would now miss.
        self.intermediate_pool_key = compute_pool_key(width, height, TEXTURE_FORMAT);

        // Snapshot the names before clearing the slot map, then re-acquire
        // through the pool. The pool's `clear()` drops every cached
        // texture so the new `ensure_texture` calls allocate fresh slots
        // sized for the new viewport.
        let names: Vec<String> = self.intermediate_slots.keys().cloned().collect();
        self.intermediate_pool.clear();
        self.intermediate_slots.clear();
        for name in &names {
            self.ensure_texture(device, name);
        }

        // Recreate temporal textures at new size. They are explicitly NOT
        // pooled (different lifetime semantics — persist across frames
        // and clear, not recycle).
        let temporal_names: Vec<String> = self.temporal_textures.keys().cloned().collect();
        for name in temporal_names {
            self.temporal_textures.remove(&name);
            self.ensure_temporal_texture(device, &name);
        }

        self.shm_output.resize(device, width, height);
    }

    // --- Internal helpers ---

    /// Borrow the `PoolTexture` allocated for `name`, if any. Reads
    /// through the slot indirection: `name` → slot index → pool bucket.
    /// Returns `None` if the name was never `ensure_texture`'d.
    fn intermediate(&self, name: &str) -> Option<&PoolTexture> {
        let slot = *self.intermediate_slots.get(name)?;
        self.intermediate_pool.get(self.intermediate_pool_key, slot)
    }

    /// Iterator over the names of every intermediate currently in the
    /// slot map. Order is unspecified (HashMap iteration). Used by
    /// `target_names()` and `resize()`.
    fn intermediate_names(&self) -> impl Iterator<Item = &String> + '_ {
        self.intermediate_slots.keys()
    }

    /// Return *some* intermediate texture, used as a last-resort fallback
    /// in the bind-group-construction paths when the requested name is
    /// missing and `MAIN_FINAL_TEXTURE` is also unavailable. Returns
    /// `None` if the slot map is empty (rare — happens before the first
    /// `ensure_texture` call).
    fn any_intermediate(&self) -> Option<&PoolTexture> {
        self.intermediate_slots
            .values()
            .next()
            .copied()
            .and_then(|slot| self.intermediate_pool.get(self.intermediate_pool_key, slot))
    }

    /// Like [`any_intermediate`] but skips the named slot. Used when a
    /// pass with no inputs needs a placeholder texture for binding 0 —
    /// binding the pass's own COLOR_TARGET as RESOURCE inside the same
    /// renderpass is a fatal wgpu validation error.
    fn any_intermediate_excluding(&self, exclude: &str) -> Option<&PoolTexture> {
        let slot = pick_slot_excluding(&self.intermediate_slots, exclude)?;
        self.intermediate_pool.get(self.intermediate_pool_key, slot)
    }

    fn ensure_texture(&mut self, device: &wgpu::Device, name: &str) {
        if self.intermediate_slots.contains_key(name) {
            return;
        }

        let key = self.intermediate_pool_key;
        let width = self.width;
        let height = self.height;

        // The factory closure runs synchronously inside `acquire_tracked`
        // and is dropped before the call returns, so capturing `device`
        // and `name` by reference is sound.
        let slot = self.intermediate_pool.acquire_tracked(key, || {
            let texture = device.create_texture(&wgpu::TextureDescriptor {
                label: Some(name),
                size: wgpu::Extent3d {
                    width,
                    height,
                    depth_or_array_layers: 1,
                },
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

    fn ensure_temporal_texture(&mut self, device: &wgpu::Device, node_id: &str) {
        if self.temporal_textures.contains_key(node_id) {
            return;
        }
        let label = format!("temporal_{}", node_id);
        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some(&label),
            size: wgpu::Extent3d {
                width: self.width,
                height: self.height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: TEXTURE_FORMAT,
            usage: wgpu::TextureUsages::TEXTURE_BINDING
                | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });
        let view = texture.create_view(&Default::default());
        self.temporal_textures.insert(node_id.to_string(), PoolTexture { texture, view });
    }

    fn get_or_create_input_layout(
        device: &wgpu::Device,
        input_count: usize,
        input_names: &[String],
        layouts: &mut HashMap<usize, wgpu::BindGroupLayout>,
    ) -> wgpu::BindGroupLayout {
        let has_content_slots = input_names.iter().any(|n| n.starts_with("content_slot_"));
        if !has_content_slots {
            layouts.entry(input_count).or_insert_with(|| Self::create_input_layout(device, input_count));
        }
        // Always create a fresh one to return — wgpu layouts are not Clone,
        // but two layouts created with the same descriptor are compatible.
        Self::create_input_layout_for(device, input_count, input_names)
    }

    fn create_input_layout(device: &wgpu::Device, input_count: usize) -> wgpu::BindGroupLayout {
        Self::create_input_layout_for(device, input_count, &[])
    }

    /// Create a bind group layout for group 1 inputs.
    ///
    /// Standard inputs get alternating texture/sampler pairs.
    /// Inputs named `content_slot_*` are bare textures sharing the first sampler
    /// (matches the content_layer.wgsl hand-written binding layout).
    fn create_input_layout_for(
        device: &wgpu::Device,
        input_count: usize,
        input_names: &[String],
    ) -> wgpu::BindGroupLayout {
        let has_content_slots = input_names.iter().any(|n| n.starts_with("content_slot_"));

        if has_content_slots {
            // content_layer layout: binding 0=tex, 1=sampler, 2..N=bare textures
            let mut entries = vec![
                wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Float { filterable: true },
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 1,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                    count: None,
                },
            ];
            let slot_count = input_names.iter().filter(|n| n.starts_with("content_slot_")).count();
            for i in 0..slot_count {
                entries.push(wgpu::BindGroupLayoutEntry {
                    binding: (2 + i) as u32,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Float { filterable: true },
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    },
                    count: None,
                });
            }
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: Some("content_layer input bgl"),
                entries: &entries,
            })
        } else {
            // Standard: alternating texture/sampler pairs
            let mut entries: Vec<wgpu::BindGroupLayoutEntry> = Vec::new();
            let count = input_count.max(1);
            for i in 0..count {
                entries.push(wgpu::BindGroupLayoutEntry {
                    binding: (i * 2) as u32,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Float { filterable: true },
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    },
                    count: None,
                });
                entries.push(wgpu::BindGroupLayoutEntry {
                    binding: (i * 2 + 1) as u32,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                    count: None,
                });
            }
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: Some("dynamic input bgl"),
                entries: &entries,
            })
        }
    }

    fn create_storage_texture_layout(device: &wgpu::Device) -> wgpu::BindGroupLayout {
        device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("storage texture bgl"),
            entries: &[wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::COMPUTE,
                ty: wgpu::BindingType::StorageTexture {
                    access: wgpu::StorageTextureAccess::WriteOnly,
                    format: TEXTURE_FORMAT,
                    view_dimension: wgpu::TextureViewDimension::D2,
                },
                count: None,
            }],
        })
    }

    fn create_input_bind_group(
        &self,
        device: &wgpu::Device,
        inputs: &[String],
        output_name: &str,
        requires_content_slots: bool,
        slot_family: &str,
        pass_id: &str,
        content_sources: Option<&ContentSourceManager>,
    ) -> wgpu::BindGroup {
        let input_count = inputs.len();
        // Prefer the explicit declarative flag from the plan; fall back to
        // name-based detection for backward compatibility with older plans.
        let has_content_slots = requires_content_slots
            || inputs.iter().any(|n| n.starts_with("content_slot_"));
        // Per yt-content-reverie-sierpinski-separation (2026-04-21):
        // ``slot_family`` is forwarded from the plan and used below to
        // filter ``ContentSourceManager`` sources before binding. The
        // pass_id is plumbed in so the WARN-once log line can identify
        // which pass missed its family — the spec requires "WARN once
        // per (pass_id, family) per startup".
        let _ = (slot_family, pass_id); // silence unused warnings when has_content_slots is false

        // Use cached layout from reload — fall back to fresh creation if uncached
        let owned_layout;
        let layout = if has_content_slots {
            owned_layout = Self::create_input_layout_for(device, input_count, inputs);
            &owned_layout
        } else {
            match self.input_bind_group_layouts.get(&input_count) {
                Some(cached) => cached,
                None => {
                    owned_layout = Self::create_input_layout(device, input_count);
                    &owned_layout
                }
            }
        };

        let mut entries: Vec<wgpu::BindGroupEntry> = Vec::new();

        if has_content_slots {
            // content_layer layout: binding 0=tex, 1=sampler, 2..N=bare content textures
            // First input is the pipeline texture (non-content-slot)
            let pipeline_inputs: Vec<_> = inputs.iter().filter(|n| !n.starts_with("content_slot_")).collect();
            let content_inputs: Vec<_> = inputs.iter().filter(|n| n.starts_with("content_slot_")).collect();

            // Binding 0: pipeline input texture
            let view = if let Some(name) = pipeline_inputs.first() {
                self.intermediate(name.as_str())
                    .or_else(|| self.intermediate(MAIN_FINAL_TEXTURE))
                    .map(|t| &t.view)
                    .unwrap_or_else(|| {
                        panic!(
                            "BUG: bind group input '{}' missing from intermediate pool \
                             AND '{}' fallback also missing — \
                             render() must ensure_texture() before create_bind_group(). \
                             Pool slots: {:?}",
                            name,
                            MAIN_FINAL_TEXTURE,
                            self.intermediate_names().collect::<Vec<_>>(),
                        )
                    })
            } else {
                // Same RESOURCE/COLOR_TARGET hazard as the standard branch
                // (see comment further below) — pick a fallback that is
                // not this pass's own output.
                self.any_intermediate_excluding(output_name)
                    .map(|t| &t.view)
                    .unwrap_or_else(|| {
                        panic!(
                            "BUG: bind group has no inputs and intermediate pool has no slot \
                             distinct from the pass output '{}' — every render path must \
                             pre-allocate at least one non-output intermediate texture before \
                             binding. Check ensure_texture() call sites in render().",
                            output_name,
                        )
                    })
            };
            entries.push(wgpu::BindGroupEntry {
                binding: 0,
                resource: wgpu::BindingResource::TextureView(view),
            });
            // Binding 1: shared sampler
            entries.push(wgpu::BindGroupEntry {
                binding: 1,
                resource: wgpu::BindingResource::Sampler(&self.sampler),
            });
            // Binding 2..N: content slot textures, family-filtered.
            // Phase 1B of yt-content-reverie-sierpinski-separation
            // (2026-04-21). Each slot pulls from sources whose
            // ``classify_family(source_id)`` matches this pass's
            // ``slot_family`` tag — narrative sources never bind on a
            // youtube_pip pass and vice-versa. Empty family ⇒ the
            // ContentSourceManager's transparent placeholder, NOT a
            // cross-family fallback.
            for (i, name) in content_inputs.iter().enumerate() {
                let idx: usize = name.strip_prefix("content_slot_")
                    .and_then(|s| s.parse().ok())
                    .unwrap_or(0);
                let slot_view = content_sources
                    .map(|cs| cs.slot_view_for_family(idx, slot_family))
                    .unwrap_or_else(|| {
                        self.intermediate(MAIN_FINAL_TEXTURE)
                            .map(|t| &t.view)
                            .unwrap_or_else(|| {
                                panic!(
                                    "BUG: content_slot_{} requested with no ContentSourceManager \
                                     and '{}' is also missing from the pool. \
                                     Pool slots: {:?}",
                                    idx,
                                    MAIN_FINAL_TEXTURE,
                                    self.intermediate_names().collect::<Vec<_>>(),
                                )
                            })
                    });
                entries.push(wgpu::BindGroupEntry {
                    binding: (2 + i) as u32,
                    resource: wgpu::BindingResource::TextureView(slot_view),
                });
            }
        } else {
            // Standard: alternating texture/sampler pairs
            for (i, name) in inputs.iter().enumerate() {
                let view = if let Some(node_id) = name.strip_prefix("@accum_") {
                    // Temporal accumulation input — use feedback buffer
                    self.temporal_textures
                        .get(node_id)
                        .or_else(|| self.intermediate(MAIN_FINAL_TEXTURE))
                        .map(|t| &t.view)
                        .unwrap_or_else(|| {
                            panic!(
                                "BUG: temporal accumulator '{}' missing from temporal_textures \
                                 AND '{}' is also missing from the intermediate pool. \
                                 Temporal textures: {:?}, pool: {:?}",
                                node_id,
                                MAIN_FINAL_TEXTURE,
                                self.temporal_textures.keys().collect::<Vec<_>>(),
                                self.intermediate_names().collect::<Vec<_>>(),
                            )
                        })
                } else {
                    // Phase 5b1 audit fix: this fallback was missed when
                    // the rest of the file was migrated to MAIN_FINAL_TEXTURE.
                    // The bare "final" key no longer exists in the texture
                    // pool — every final texture is target-namespaced.
                    self.intermediate(name.as_str())
                        .or_else(|| self.intermediate(MAIN_FINAL_TEXTURE))
                        .map(|t| &t.view)
                        .unwrap_or_else(|| {
                            panic!(
                                "BUG: pipeline input '{}' missing from intermediate pool \
                                 AND '{}' fallback also missing. Pool slots: {:?}",
                                name,
                                MAIN_FINAL_TEXTURE,
                                self.intermediate_names().collect::<Vec<_>>(),
                            )
                        })
                };
                entries.push(wgpu::BindGroupEntry {
                    binding: (i * 2) as u32,
                    resource: wgpu::BindingResource::TextureView(view),
                });
                entries.push(wgpu::BindGroupEntry {
                    binding: (i * 2 + 1) as u32,
                    resource: wgpu::BindingResource::Sampler(&self.sampler),
                });
            }
        }
        // If no inputs, still provide a default texture+sampler (shaders expect at least one).
        //
        // The fallback texture MUST NOT be the same texture this pass writes
        // to as COLOR_TARGET — wgpu's usage tracker treats binding the same
        // texture as both RESOURCE and COLOR_TARGET inside one renderpass as
        // a fatal validation error. The `noise` pass triggered this in
        // production: empty inputs + output=`layer_0` and HashMap iteration
        // sometimes returned the `layer_0` PoolTexture from
        // `any_intermediate()`. Per `imagination-wgpu-validation-exits`.
        if inputs.is_empty() {
            if let Some(tex) = self.any_intermediate_excluding(output_name) {
                entries.push(wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::TextureView(&tex.view),
                });
                entries.push(wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::Sampler(&self.sampler),
                });
            }
        }

        device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("dynamic input bg"),
            layout,
            entries: &entries,
        })
    }

    fn create_storage_bind_group(
        &self,
        device: &wgpu::Device,
        output_name: &str,
    ) -> wgpu::BindGroup {
        let layout = Self::create_storage_texture_layout(device);

        let view = if let Some(tex) = self.intermediate(output_name) {
            &tex.view
        } else {
            &self.intermediate(MAIN_FINAL_TEXTURE).unwrap().view
        };

        device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("storage bg"),
            layout: &layout,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: wgpu::BindingResource::TextureView(view),
            }],
        })
    }
}

/// Inline blit shader: samples a texture and outputs it.
const BLIT_WGSL: &str = r#"
struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@vertex
fn vs_main(@builtin(vertex_index) vertex_index: u32) -> VertexOutput {
    // Fullscreen triangle: 3 vertices that cover the entire viewport.
    // Vertex 0: (-1, -1), Vertex 1: (3, -1), Vertex 2: (-1, 3)
    // The GPU clips the oversized triangle to the viewport automatically.
    var out: VertexOutput;
    let x = f32(i32(vertex_index & 1u)) * 4.0 - 1.0;
    let y = f32(i32(vertex_index >> 1u)) * 4.0 - 1.0;
    out.position = vec4<f32>(x, y, 0.0, 1.0);
    out.uv = vec2<f32>((x + 1.0) * 0.5, (1.0 - y) * 0.5);
    return out;
}

@group(0) @binding(0)
var source_texture: texture_2d<f32>;
@group(0) @binding(1)
var source_sampler: sampler;

@fragment
fn main(in: VertexOutput) -> @location(0) vec4<f32> {
    return textureSample(source_texture, source_sampler, in.uv);
}
"#;

// ============================================================================
// Tests — plan.json v1 / v2 normalization (Phase 5a)
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_v1_flat_passes_format() {
        // v1 plans have a flat `passes` list and no `targets` field.
        // The executor wraps them into a synthetic "main" target so the
        // rest of the render loop can use the canonical per-target map.
        let json = r#"{
            "version": 1,
            "passes": [
                {"node_id": "noise", "shader": "noise.wgsl"}
            ]
        }"#;
        let plan: PlanFile = serde_json::from_str(json).expect("v1 plan parses");
        assert!(plan.targets.is_empty());
        assert_eq!(plan.passes.len(), 1);
        let by_target = plan.passes_by_target();
        assert_eq!(by_target.len(), 1);
        assert_eq!(by_target.get("main").unwrap().len(), 1);
        assert_eq!(plan.main_passes().len(), 1);
    }

    #[test]
    fn parses_v2_targets_format_with_main() {
        let json = r#"{
            "version": 2,
            "targets": {
                "main": {
                    "passes": [
                        {"node_id": "noise", "shader": "noise.wgsl"},
                        {"node_id": "color", "shader": "colorgrade.wgsl"}
                    ]
                }
            }
        }"#;
        let plan: PlanFile = serde_json::from_str(json).expect("v2 plan parses");
        assert!(plan.passes.is_empty());
        assert_eq!(plan.targets.len(), 1);
        let main = plan.main_passes();
        assert_eq!(main.len(), 2);
        assert_eq!(main[0].node_id, "noise");
        assert_eq!(main[1].node_id, "color");
    }

    #[test]
    fn parses_v2_with_multiple_targets_returns_main() {
        // Phase 5a: when multiple targets are present, main_passes()
        // selects "main". The other targets are loaded into the
        // PlanFile but not rendered until Phase 5b.
        let json = r#"{
            "version": 2,
            "targets": {
                "main": {"passes": [{"node_id": "a", "shader": "a.wgsl"}]},
                "hud":  {"passes": [{"node_id": "b", "shader": "b.wgsl"}]}
            }
        }"#;
        let plan: PlanFile = serde_json::from_str(json).expect("multi-target plan parses");
        assert_eq!(plan.targets.len(), 2);
        let main = plan.main_passes();
        assert_eq!(main.len(), 1);
        assert_eq!(main[0].node_id, "a");
    }

    #[test]
    fn main_passes_falls_back_to_first_target_when_main_missing() {
        // If a v2 plan has no "main" target (e.g. it's all "hud"),
        // we render the first target alphabetically as a fallback.
        let json = r#"{
            "version": 2,
            "targets": {
                "preview": {"passes": [{"node_id": "p", "shader": "p.wgsl"}]},
                "hud":     {"passes": [{"node_id": "h", "shader": "h.wgsl"}]}
            }
        }"#;
        let plan: PlanFile = serde_json::from_str(json).expect("no-main plan parses");
        let active = plan.main_passes();
        // "hud" sorts before "preview" alphabetically.
        assert_eq!(active.len(), 1);
        assert_eq!(active[0].node_id, "h");
    }

    #[test]
    fn empty_plan_has_no_passes() {
        let json = r#"{"version": 2, "targets": {}}"#;
        let plan: PlanFile = serde_json::from_str(json).expect("empty plan parses");
        assert!(plan.main_passes().is_empty());
    }

    #[test]
    fn v1_empty_passes_has_no_main_passes() {
        let json = r#"{"version": 1, "passes": []}"#;
        let plan: PlanFile = serde_json::from_str(json).expect("empty v1 plan parses");
        assert!(plan.main_passes().is_empty());
    }

    // ----- Phase 5b1: namespace_texture_name + multi-target plumbing -----

    #[test]
    fn namespace_layer_names_get_target_prefix() {
        assert_eq!(namespace_texture_name("layer_0", "main"), "main:layer_0");
        assert_eq!(namespace_texture_name("layer_5", "hud"), "hud:layer_5");
    }

    #[test]
    fn namespace_final_gets_target_prefix() {
        assert_eq!(namespace_texture_name("final", "main"), "main:final");
        assert_eq!(namespace_texture_name("final", "preview"), "preview:final");
    }

    #[test]
    fn namespace_already_namespaced_unchanged() {
        // Idempotent: a name that already contains ":" is left alone.
        assert_eq!(namespace_texture_name("main:final", "hud"), "main:final");
        assert_eq!(namespace_texture_name("main:layer_3", "hud"), "main:layer_3");
    }

    #[test]
    fn namespace_layer_source_pseudo_textures_unchanged() {
        // @live, @smooth, @hls and @accum_* are global pseudo-textures
        // and must NOT be namespaced.
        assert_eq!(namespace_texture_name("@live", "main"), "@live");
        assert_eq!(namespace_texture_name("@smooth", "hud"), "@smooth");
        assert_eq!(namespace_texture_name("@hls", "main"), "@hls");
        assert_eq!(namespace_texture_name("@accum_rd", "main"), "@accum_rd");
        assert_eq!(namespace_texture_name("@accum_feedback", "preview"), "@accum_feedback");
    }

    #[test]
    fn namespace_content_slots_unchanged() {
        // Content slots are global, populated by ContentSourceManager.
        assert_eq!(namespace_texture_name("content_slot_0", "main"), "content_slot_0");
        assert_eq!(namespace_texture_name("content_slot_3", "hud"), "content_slot_3");
    }

    #[test]
    fn main_final_constant_matches_namespacing() {
        // Sanity: the constant ShmOutput / surface blit reads from
        // matches what namespace_texture_name produces for the main
        // target's final output.
        assert_eq!(MAIN_FINAL_TEXTURE, &namespace_texture_name("final", "main"));
    }

    #[test]
    fn pass_pass_through_fields() {
        // Verify that pass-level fields (backend, requires_content_slots,
        // uniforms, param_order) survive the v2 → main_passes() round-trip.
        let json = r#"{
            "version": 2,
            "targets": {
                "main": {
                    "passes": [
                        {
                            "node_id": "noise",
                            "shader": "noise.wgsl",
                            "backend": "wgsl_render",
                            "inputs": ["@live"],
                            "output": "final",
                            "uniforms": {"amplitude": 0.5},
                            "param_order": ["amplitude"],
                            "requires_content_slots": false
                        }
                    ]
                }
            }
        }"#;
        let plan: PlanFile = serde_json::from_str(json).expect("rich v2 plan parses");
        let passes = plan.main_passes();
        assert_eq!(passes.len(), 1);
        let p = &passes[0];
        assert_eq!(p.backend, "wgsl_render");
        assert_eq!(p.inputs, vec!["@live"]);
        assert_eq!(p.output, "final");
        assert_eq!(p.uniforms.get("amplitude").copied(), Some(0.5));
        assert_eq!(p.param_order, vec!["amplitude"]);
        assert!(!p.requires_content_slots);
    }

    // ----- B4: TransientTexturePool wiring — pool-key bookkeeping -----

    #[test]
    fn pool_key_is_deterministic_for_same_inputs() {
        let k1 = compute_pool_key(1920, 1080, TEXTURE_FORMAT);
        let k2 = compute_pool_key(1920, 1080, TEXTURE_FORMAT);
        assert_eq!(k1, k2);
    }

    #[test]
    fn pool_key_distinguishes_dimensions() {
        // Different (width, height) must hash to different buckets so
        // resize() does not accidentally reuse stale slots from the prior
        // viewport size.
        let a = compute_pool_key(1920, 1080, TEXTURE_FORMAT);
        let b = compute_pool_key(1280, 720, TEXTURE_FORMAT);
        let c = compute_pool_key(1080, 1920, TEXTURE_FORMAT);
        assert_ne!(a, b);
        assert_ne!(a, c);
        assert_ne!(b, c);
    }

    #[test]
    fn pool_key_distinguishes_formats() {
        // The bucket strategy is keyed by (width, height, format). Two
        // intermediates with the same dimensions but different formats
        // must land in different buckets.
        let rgba8 = compute_pool_key(1920, 1080, wgpu::TextureFormat::Rgba8Unorm);
        let rgba16 = compute_pool_key(1920, 1080, wgpu::TextureFormat::Rgba16Float);
        assert_ne!(rgba8, rgba16);
    }

    #[test]
    fn pool_key_changes_when_only_one_dimension_changes() {
        // Bucket key changes if only width changes, only height changes,
        // or both change. Guards against a hashing strategy that
        // accidentally collapses related descriptors.
        let base = compute_pool_key(1920, 1080, TEXTURE_FORMAT);
        let wider = compute_pool_key(1921, 1080, TEXTURE_FORMAT);
        let taller = compute_pool_key(1920, 1081, TEXTURE_FORMAT);
        assert_ne!(base, wider);
        assert_ne!(base, taller);
        assert_ne!(wider, taller);
    }

    #[test]
    fn pool_metrics_struct_is_copy_and_default_safe() {
        // PoolMetrics is the surface area for external observability.
        // It must be Copy so callers can grab a snapshot without holding
        // a borrow on the pipeline, and the field set must be stable
        // enough that adding telemetry consumers does not require a
        // PoolMetrics rewrite. This test pins both invariants.
        let m = PoolMetrics {
            bucket_count: 1,
            total_textures: 8,
            total_acquires: 100,
            total_allocations: 8,
            reuse_ratio: 0.92,
            slot_count: 8,
        };
        let copy = m;
        assert_eq!(m, copy);
        // Reuse ratio derivation matches the pool's contract.
        let derived = (m.total_acquires - m.total_allocations) as f64 / m.total_acquires as f64;
        assert!((derived - m.reuse_ratio).abs() < 1e-9);
    }

    // ----- pick_slot_excluding — RESOURCE/COLOR_TARGET conflict guard -----
    //
    // Per `imagination-wgpu-validation-exits`: production logs showed
    // recurrent `Texture 'main:layer_0' RESOURCE + COLOR_TARGET` panics
    // from the bind-group fallback when a pass with empty inputs hit
    // `any_intermediate()` and HashMap iteration happened to return the
    // same slot the pass writes to. The fix is to pick a slot whose key
    // is not the pass output. These tests pin the contract of the
    // selection helper that `any_intermediate_excluding` delegates to.

    #[test]
    fn pick_slot_excluding_skips_the_named_slot() {
        let mut slots = HashMap::new();
        slots.insert("layer_0".to_string(), 0usize);
        slots.insert("layer_1".to_string(), 1usize);
        slots.insert("layer_2".to_string(), 2usize);

        // The result must never be the slot we excluded, even though
        // HashMap iteration order is randomized.
        for _ in 0..32 {
            let picked = pick_slot_excluding(&slots, "layer_0");
            assert!(picked.is_some());
            assert_ne!(picked, Some(0usize));
        }
    }

    #[test]
    fn pick_slot_excluding_returns_none_when_only_exclude_present() {
        // The empty-input pass is the only writer when the pool was
        // just initialized — there is no other slot to fall back to.
        // The bind-group code is responsible for treating None as a
        // BUG (every render path must `ensure_texture()` enough slots
        // before binding); this test only pins that we return None
        // rather than silently aliasing the output.
        let mut slots = HashMap::new();
        slots.insert("layer_0".to_string(), 0usize);
        let picked = pick_slot_excluding(&slots, "layer_0");
        assert_eq!(picked, None);
    }

    #[test]
    fn pick_slot_excluding_returns_none_for_empty_map() {
        let slots: HashMap<String, usize> = HashMap::new();
        let picked = pick_slot_excluding(&slots, "anything");
        assert_eq!(picked, None);
    }

    #[test]
    fn pick_slot_excluding_with_unknown_exclude_returns_some() {
        // If the excluded name isn't in the map at all, any slot is OK
        // — the helper picks the first iterated entry and returns it.
        let mut slots = HashMap::new();
        slots.insert("layer_0".to_string(), 7usize);
        let picked = pick_slot_excluding(&slots, "layer_99");
        assert_eq!(picked, Some(7usize));
    }

    // ----- LRR Phase 0 item 4 / FINDING-Q step 2 — pre-validation gate -----

    fn make_pass(node_id: &str, shader: &str) -> PlanPass {
        PlanPass {
            node_id: node_id.to_string(),
            pass_type: "render".to_string(),
            shader: shader.to_string(),
            inputs: Vec::new(),
            output: format!("{}_out", node_id),
            uniforms: HashMap::new(),
            param_order: Vec::new(),
            steps_per_frame: 1,
            requires_content_slots: false,
            backend: "wgsl_render".to_string(),
            slot_family: "narrative".to_string(),
        }
    }

    #[test]
    fn manifest_hash_is_stable_across_calls() {
        let a = compute_manifest_hash("hello world");
        let b = compute_manifest_hash("hello world");
        assert_eq!(a, b);
        assert_eq!(a.len(), 16);
    }

    #[test]
    fn manifest_hash_changes_with_input() {
        let a = compute_manifest_hash("hello world");
        let b = compute_manifest_hash("hello world!");
        assert_ne!(a, b);
    }

    #[test]
    fn validate_plan_shaders_passes_on_valid_wgsl() {
        let dir = tempfile::tempdir().expect("tempdir");
        // A minimal valid fragment shader matching the production
        // convention: take @location(0) uv directly and return a
        // @location(0) vec4 (no VertexOutput struct — that's defined in
        // the vertex stage which is linked separately by wgpu). The
        // pre-validation prepends SHARED_UNIFORMS_WGSL only, matching
        // the build phase's actual compile input.
        let shader_src = r#"
@fragment
fn main(@location(0) v_texcoord: vec2<f32>) -> @location(0) vec4<f32> {
    return vec4<f32>(0.0, 0.0, 0.0, 1.0);
}
"#;
        std::fs::write(dir.path().join("ok.wgsl"), shader_src).unwrap();
        let passes = vec![("main".to_string(), make_pass("ok_node", "ok.wgsl"))];
        let failures = validate_plan_shaders(dir.path(), &passes);
        assert!(failures.is_empty(), "expected no failures, got {:?}", failures);
    }

    #[test]
    fn validate_plan_shaders_fails_on_missing_file() {
        let dir = tempfile::tempdir().expect("tempdir");
        let passes = vec![("main".to_string(), make_pass("missing_node", "does-not-exist.wgsl"))];
        let failures = validate_plan_shaders(dir.path(), &passes);
        assert_eq!(failures.len(), 1);
        assert!(failures[0].contains("main/missing_node"));
        assert!(failures[0].contains("shader file unreadable"));
    }

    #[test]
    fn validate_plan_shaders_fails_on_broken_wgsl() {
        let dir = tempfile::tempdir().expect("tempdir");
        // Garbage WGSL that should fail naga parse.
        std::fs::write(
            dir.path().join("broken.wgsl"),
            "this is not valid WGSL at all !@#$%",
        )
        .unwrap();
        let passes = vec![("main".to_string(), make_pass("broken_node", "broken.wgsl"))];
        let failures = validate_plan_shaders(dir.path(), &passes);
        assert_eq!(failures.len(), 1);
        assert!(failures[0].contains("main/broken_node"));
        assert!(failures[0].contains("WGSL parse failed"));
    }

    #[test]
    fn validate_plan_shaders_collects_all_failures() {
        // Multiple failing passes → all reported, not just the first.
        let dir = tempfile::tempdir().expect("tempdir");
        std::fs::write(dir.path().join("broken1.wgsl"), "bad").unwrap();
        std::fs::write(dir.path().join("broken2.wgsl"), "also bad").unwrap();
        let passes = vec![
            ("main".to_string(), make_pass("a", "broken1.wgsl")),
            ("main".to_string(), make_pass("b", "broken2.wgsl")),
            ("main".to_string(), make_pass("c", "missing.wgsl")),
        ];
        let failures = validate_plan_shaders(dir.path(), &passes);
        assert_eq!(failures.len(), 3);
        assert!(failures.iter().any(|f| f.contains("a:")));
        assert!(failures.iter().any(|f| f.contains("b:")));
        assert!(failures.iter().any(|f| f.contains("c:")));
    }

    #[test]
    fn validate_plan_shaders_empty_input_returns_empty() {
        let dir = tempfile::tempdir().expect("tempdir");
        let failures = validate_plan_shaders(dir.path(), &[]);
        assert!(failures.is_empty());
    }

    #[test]
    fn homage_custom_signal_routes_to_uniform_custom_slot() {
        use crate::uniform_buffer::UniformData;
        use std::collections::HashMap;

        let overrides: HashMap<String, f64> = [
            ("signal.homage_custom_4_0".into(), 1.0),
            ("signal.homage_custom_4_1".into(), 180.0),
            ("signal.homage_custom_4_2".into(), 0.75),
            ("signal.homage_custom_4_3".into(), 42.5),
        ]
        .into_iter()
        .collect();

        let mut uniform_data = UniformData::default();
        assert_eq!(uniform_data.custom[4], [0.0; 4]);

        for (key, &val) in &overrides {
            if let Some(signal) = key.strip_prefix("signal.") {
                let v = val as f32;
                if let Some(rest) = signal.strip_prefix("homage_custom_") {
                    let mut parts = rest.splitn(2, '_');
                    if let (Some(slot_s), Some(comp_s)) = (parts.next(), parts.next()) {
                        if let (Ok(slot), Ok(comp)) =
                            (slot_s.parse::<usize>(), comp_s.parse::<usize>())
                        {
                            if slot < 8 && comp < 4 {
                                uniform_data.custom[slot][comp] = v;
                            }
                        }
                    }
                }
            }
        }

        assert_eq!(uniform_data.custom[4][0], 1.0);
        assert_eq!(uniform_data.custom[4][1], 180.0);
        assert_eq!(uniform_data.custom[4][2], 0.75);
        assert_eq!(uniform_data.custom[4][3], 42.5);
        // Other slots untouched.
        assert_eq!(uniform_data.custom[0], [0.0; 4]);
        assert_eq!(uniform_data.custom[7], [0.0; 4]);
    }

    #[test]
    fn homage_custom_signal_rejects_out_of_bounds() {
        use crate::uniform_buffer::UniformData;

        let mut uniform_data = UniformData::default();

        for key in &["signal.homage_custom_8_0", "signal.homage_custom_4_4", "signal.homage_custom_99_0"] {
            if let Some(signal) = key.strip_prefix("signal.") {
                let v: f32 = 999.0;
                if let Some(rest) = signal.strip_prefix("homage_custom_") {
                    let mut parts = rest.splitn(2, '_');
                    if let (Some(slot_s), Some(comp_s)) = (parts.next(), parts.next()) {
                        if let (Ok(slot), Ok(comp)) =
                            (slot_s.parse::<usize>(), comp_s.parse::<usize>())
                        {
                            if slot < 8 && comp < 4 {
                                uniform_data.custom[slot][comp] = v;
                            }
                        }
                    }
                }
            }
        }

        for s in 0..8 {
            assert_eq!(uniform_data.custom[s], [0.0; 4], "slot {s} should be untouched");
        }
    }
}
