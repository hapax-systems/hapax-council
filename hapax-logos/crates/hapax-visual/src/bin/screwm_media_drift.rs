//! screwm_media_drift — GPU media-drift service.
//!
//! Spec: docs/superpowers/specs/2026-05-30-screwm-gpu-drift-port-design.md.
//!
//! Headless wgpu on the 5060 Ti. For each configured slot: read the producer's
//! *raw* (undrifted) BGRA from `/dev/shm`, apply `media_drift.wgsl` driven by the
//! live `DriftState`, and write the *drifted* BGRA back to the slot path the
//! DarkPlaces engine blits — replacing the producers' Python numpy drift.
//!
//! Config (env `HAPAX_SCREWM_DRIFT_SLOTS`, comma list): `name:WxH[:intensity]`,
//! e.g. `ward-atlas:2048x2304,cam-brio-operator:1280x720`. Paths derive from the
//! name: in = `quake-live-<name>.raw.bgra`, out = `quake-live-<name>.bgra`.

use std::borrow::Cow;
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use hapax_visual::media_drift::{load_drift_state, DriftUniforms, ReceiverClass};
use serde::{Deserialize, Serialize};

const SHADER_SRC: &str = include_str!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../agents/shaders/nodes/media_drift.wgsl"
));
const SHM_DIR: &str = "/dev/shm/hapax-compositor";
const TEX_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Bgra8Unorm;

fn align_up(v: u32, a: u32) -> u32 {
    (v + a - 1) & !(a - 1)
}

#[derive(Debug, Clone, PartialEq)]
struct SlotConfig {
    name: String,
    raw_path: PathBuf,
    out_path: PathBuf,
    width: u32,
    height: u32,
    class: ReceiverClass,
    intensity: f32,
}

impl SlotConfig {
    /// Parse one `name:WxH[:intensity]` spec.
    fn parse(spec: &str) -> Result<Self, String> {
        let mut parts = spec.split(':');
        let name = parts
            .next()
            .ok_or_else(|| format!("slot spec {spec:?} is empty"))?
            .trim()
            .to_ascii_lowercase();
        if name.is_empty() {
            return Err(format!("slot spec {spec:?} has an empty name"));
        }
        let (w, h) = {
            let dims = parts
                .next()
                .ok_or_else(|| format!("slot {name:?} must include WxH dimensions"))?;
            let (ws, hs) = dims
                .split_once('x')
                .ok_or_else(|| format!("slot {name:?} dimensions must use WxH"))?;
            let width: u32 = ws
                .trim()
                .parse()
                .map_err(|_| format!("slot {name:?} width must be an integer"))?;
            let height: u32 = hs
                .trim()
                .parse()
                .map_err(|_| format!("slot {name:?} height must be an integer"))?;
            if width == 0 || height == 0 {
                return Err(format!("slot {name:?} dimensions must be positive"));
            }
            (width, height)
        };
        let intensity = parts
            .next()
            .map(|s| {
                s.trim()
                    .parse::<f32>()
                    .map_err(|_| format!("slot {name:?} intensity must be numeric"))
            })
            .transpose()?
            .unwrap_or(1.0);
        if !intensity.is_finite() || intensity <= 0.0 {
            return Err(format!("slot {name:?} intensity must be positive"));
        }
        if parts.next().is_some() {
            return Err(format!("slot {name:?} has too many ':' fields"));
        }
        Ok(Self {
            raw_path: PathBuf::from(format!("{SHM_DIR}/quake-live-{name}.raw.bgra")),
            out_path: PathBuf::from(format!("{SHM_DIR}/quake-live-{name}.bgra")),
            class: ReceiverClass::from_name(&name),
            name,
            width: w,
            height: h,
            intensity,
        })
    }
}

fn parse_slot_configs(spec: &str) -> Result<Vec<SlotConfig>, String> {
    let mut seen = BTreeSet::new();
    let mut slots = Vec::new();
    for part in spec
        .split(',')
        .map(str::trim)
        .filter(|part| !part.is_empty())
    {
        let slot = SlotConfig::parse(part)?;
        if !seen.insert(slot.name.clone()) {
            return Err(format!("duplicate media-drift slot {:?}", slot.name));
        }
        slots.push(slot);
    }
    Ok(slots)
}

fn receiver_class_name(class: ReceiverClass) -> &'static str {
    match class {
        ReceiverClass::Camera => "camera",
        ReceiverClass::Oarb => "oarb",
        ReceiverClass::Ticker => "ticker",
        ReceiverClass::Atlas => "atlas",
        ReceiverClass::Reverie => "reverie",
        ReceiverClass::Other => "other",
    }
}

fn stable_short_hash(bytes: &[u8]) -> String {
    let mut hash = 0xcbf29ce484222325u64;
    for byte in bytes {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    format!("{hash:016x}")
}

fn unix_ms_now() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
}

fn tmp_path_for(path: &Path) -> PathBuf {
    let mut tmp = path.as_os_str().to_os_string();
    tmp.push(".tmp");
    PathBuf::from(tmp)
}

fn atomic_write(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    let tmp = tmp_path_for(path);
    std::fs::write(&tmp, bytes).and_then(|_| std::fs::rename(&tmp, path))
}

fn read_complete_frame(path: &Path, expected_bytes: usize) -> Option<Vec<u8>> {
    match std::fs::read(path) {
        Ok(bytes) if bytes.len() == expected_bytes => Some(bytes),
        _ => None,
    }
}

fn producer_sidecar_path_for(raw_path: &Path) -> PathBuf {
    raw_path.with_extension("json")
}

#[derive(Debug, Clone, Default, Deserialize, PartialEq)]
struct ProducerRawSidecar {
    #[serde(default)]
    source: String,
    #[serde(default)]
    renderer: String,
    #[serde(default)]
    drift_renderer: String,
    #[serde(default)]
    frame_id: Option<u64>,
    #[serde(default)]
    frames: Option<u64>,
    #[serde(default)]
    updated_at: Option<f64>,
    #[serde(default)]
    observed_at: Option<f64>,
    #[serde(default)]
    gpu_drift: bool,
    #[serde(default)]
    gpu_drift_raw_output: String,
    #[serde(default)]
    gpu_drift_final_output: String,
    #[serde(default)]
    gpu_drift_output_owner: String,
    #[serde(default)]
    drift_input_hash: String,
    #[serde(default)]
    preflip_y: Option<bool>,
}

fn read_producer_raw_sidecar(path: &Path) -> Option<ProducerRawSidecar> {
    let bytes = std::fs::read(path).ok()?;
    let value: serde_json::Value = serde_json::from_slice(&bytes).ok()?;
    if !value.is_object() {
        return None;
    }
    serde_json::from_value(value).ok()
}

fn path_claim_matches(claim: &str, expected: &Path) -> bool {
    !claim.is_empty() && Path::new(claim) == expected
}

#[derive(Debug, Clone, PartialEq, Serialize)]
struct ProducerSidecarMetadata {
    producer_sidecar_path: String,
    producer_sidecar_present: bool,
    producer_source: String,
    producer_renderer: String,
    producer_drift_renderer: String,
    producer_frame_id: Option<u64>,
    producer_frames: Option<u64>,
    producer_updated_at_unix_s: Option<f64>,
    producer_observed_at_unix_s: Option<f64>,
    producer_gpu_drift: bool,
    producer_raw_output: String,
    producer_final_output: String,
    producer_output_owner: String,
    producer_input_hash: String,
    producer_preflip_y: Option<bool>,
    producer_raw_output_matches_raw_path: bool,
    producer_final_output_matches_output_path: bool,
    producer_output_owner_matches: bool,
    producer_input_hash_matches_raw: bool,
}

impl ProducerSidecarMetadata {
    fn absent(sidecar_path: &Path) -> Self {
        Self {
            producer_sidecar_path: sidecar_path.display().to_string(),
            producer_sidecar_present: false,
            producer_source: String::new(),
            producer_renderer: String::new(),
            producer_drift_renderer: String::new(),
            producer_frame_id: None,
            producer_frames: None,
            producer_updated_at_unix_s: None,
            producer_observed_at_unix_s: None,
            producer_gpu_drift: false,
            producer_raw_output: String::new(),
            producer_final_output: String::new(),
            producer_output_owner: String::new(),
            producer_input_hash: String::new(),
            producer_preflip_y: None,
            producer_raw_output_matches_raw_path: false,
            producer_final_output_matches_output_path: false,
            producer_output_owner_matches: false,
            producer_input_hash_matches_raw: false,
        }
    }

    fn from_sidecar(
        sidecar_path: &Path,
        sidecar: Option<&ProducerRawSidecar>,
        raw_path: &Path,
        output_path: &Path,
        input_hash: &str,
    ) -> Self {
        let Some(sidecar) = sidecar else {
            return Self::absent(sidecar_path);
        };
        Self {
            producer_sidecar_path: sidecar_path.display().to_string(),
            producer_sidecar_present: true,
            producer_source: sidecar.source.clone(),
            producer_renderer: sidecar.renderer.clone(),
            producer_drift_renderer: sidecar.drift_renderer.clone(),
            producer_frame_id: sidecar.frame_id,
            producer_frames: sidecar.frames,
            producer_updated_at_unix_s: sidecar.updated_at,
            producer_observed_at_unix_s: sidecar.observed_at,
            producer_gpu_drift: sidecar.gpu_drift,
            producer_raw_output: sidecar.gpu_drift_raw_output.clone(),
            producer_final_output: sidecar.gpu_drift_final_output.clone(),
            producer_output_owner: sidecar.gpu_drift_output_owner.clone(),
            producer_input_hash: sidecar.drift_input_hash.clone(),
            producer_preflip_y: sidecar.preflip_y,
            producer_raw_output_matches_raw_path: path_claim_matches(
                &sidecar.gpu_drift_raw_output,
                raw_path,
            ),
            producer_final_output_matches_output_path: path_claim_matches(
                &sidecar.gpu_drift_final_output,
                output_path,
            ),
            producer_output_owner_matches: sidecar.gpu_drift_output_owner == "screwm_media_drift",
            producer_input_hash_matches_raw: !sidecar.drift_input_hash.is_empty()
                && sidecar.drift_input_hash == input_hash,
        }
    }
}

#[derive(Debug, Serialize)]
struct SlotMetadata {
    slot: String,
    w: u32,
    h: u32,
    stride: u32,
    frame_id: u64,
    receiver_class: &'static str,
    receiver_class_code: u32,
    raw_path: String,
    output_path: String,
    meta_path: String,
    intensity: f32,
    drift_state_intensity: f32,
    input_hash: String,
    output_hash: String,
    drift_changed: bool,
    observed_at_unix_ms: u128,
    #[serde(flatten)]
    producer: ProducerSidecarMetadata,
}

/// Per-slot GPU resources: input texture, output render target, uniform buffer,
/// bind group, and a padded readback staging buffer.
struct SlotGpu {
    cfg: SlotConfig,
    in_tex: wgpu::Texture,
    out_tex: wgpu::Texture,
    out_view: wgpu::TextureView,
    uniform: wgpu::Buffer,
    bind_group: wgpu::BindGroup,
    staging: wgpu::Buffer,
    bytes_per_row: u32,
    padded_bytes_per_row: u32,
    expected_bytes: usize,
    frame: u64,
    last_input_hash: String,
    last_drift_state_intensity: f32,
    last_producer_sidecar_path: PathBuf,
    last_producer_sidecar: Option<ProducerRawSidecar>,
}

impl SlotGpu {
    fn new(
        device: &wgpu::Device,
        bgl: &wgpu::BindGroupLayout,
        sampler: &wgpu::Sampler,
        cfg: SlotConfig,
    ) -> Self {
        let size = wgpu::Extent3d {
            width: cfg.width,
            height: cfg.height,
            depth_or_array_layers: 1,
        };
        let in_tex = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("media-drift in"),
            size,
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: TEX_FORMAT,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });
        let out_tex = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("media-drift out"),
            size,
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: TEX_FORMAT,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let out_view = out_tex.create_view(&wgpu::TextureViewDescriptor::default());
        let in_view = in_tex.create_view(&wgpu::TextureViewDescriptor::default());
        let uniform = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("media-drift uniform"),
            size: std::mem::size_of::<DriftUniforms>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("media-drift bind"),
            layout: bgl,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: uniform.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::TextureView(&in_view),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: wgpu::BindingResource::Sampler(sampler),
                },
            ],
        });
        let bytes_per_row = cfg.width * 4;
        let padded_bytes_per_row = align_up(bytes_per_row, 256);
        let staging = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("media-drift staging"),
            size: (padded_bytes_per_row * cfg.height) as u64,
            usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let producer_sidecar_path = producer_sidecar_path_for(&cfg.raw_path);
        Self {
            expected_bytes: (cfg.width * cfg.height * 4) as usize,
            cfg,
            in_tex,
            out_tex,
            out_view,
            uniform,
            bind_group,
            staging,
            bytes_per_row,
            padded_bytes_per_row,
            frame: 0,
            last_input_hash: String::new(),
            last_drift_state_intensity: 0.0,
            last_producer_sidecar_path: producer_sidecar_path,
            last_producer_sidecar: None,
        }
    }

    /// Encode one slot pass into a command buffer.
    ///
    /// Returns `None` if the producer has not written a complete raw frame yet.
    /// Readback is intentionally drained later so all slots can submit together
    /// and share one `device.poll(Maintain::Wait)` per tick.
    fn encode(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        pipeline: &wgpu::RenderPipeline,
        state: &hapax_visual::media_drift::DriftState,
        now: f32,
    ) -> Option<wgpu::CommandBuffer> {
        let raw = read_complete_frame(&self.cfg.raw_path, self.expected_bytes)?;
        self.last_input_hash = stable_short_hash(&raw);
        self.last_drift_state_intensity = state.intensity();
        self.last_producer_sidecar = read_producer_raw_sidecar(&self.last_producer_sidecar_path);

        queue.write_texture(
            wgpu::TexelCopyTextureInfo {
                texture: &self.in_tex,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            &raw,
            wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(self.bytes_per_row),
                rows_per_image: Some(self.cfg.height),
            },
            wgpu::Extent3d {
                width: self.cfg.width,
                height: self.cfg.height,
                depth_or_array_layers: 1,
            },
        );

        let u = DriftUniforms::new(
            state,
            self.cfg.class,
            now,
            self.frame as f32,
            self.cfg.intensity,
            self.cfg.width,
            self.cfg.height,
        );
        queue.write_buffer(&self.uniform, 0, bytemuck::bytes_of(&u));

        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
            label: Some("media-drift enc"),
        });
        {
            let mut pass = enc.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("media-drift pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &self.out_view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
            });
            pass.set_pipeline(pipeline);
            pass.set_bind_group(0, &self.bind_group, &[]);
            pass.draw(0..3, 0..1);
        }
        enc.copy_texture_to_buffer(
            wgpu::TexelCopyTextureInfo {
                texture: &self.out_tex,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::TexelCopyBufferInfo {
                buffer: &self.staging,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(self.padded_bytes_per_row),
                    rows_per_image: Some(self.cfg.height),
                },
            },
            wgpu::Extent3d {
                width: self.cfg.width,
                height: self.cfg.height,
                depth_or_array_layers: 1,
            },
        );
        Some(enc.finish())
    }

    fn finish_readback(&mut self) -> bool {
        let mapped = self.staging.slice(..).get_mapped_range();
        let mut out = Vec::with_capacity(self.expected_bytes);
        if self.padded_bytes_per_row == self.bytes_per_row {
            out.extend_from_slice(&mapped[..self.expected_bytes]);
        } else {
            for row in 0..self.cfg.height {
                let s = (row * self.padded_bytes_per_row) as usize;
                out.extend_from_slice(&mapped[s..s + self.bytes_per_row as usize]);
            }
        }
        drop(mapped);
        self.staging.unmap();

        let output_hash = stable_short_hash(&out);
        if atomic_write(&self.cfg.out_path, &out).is_err() {
            return false;
        }

        let frame_id = self.frame + 1;
        let meta_path = self.cfg.out_path.with_extension("json");
        let producer = ProducerSidecarMetadata::from_sidecar(
            &self.last_producer_sidecar_path,
            self.last_producer_sidecar.as_ref(),
            &self.cfg.raw_path,
            &self.cfg.out_path,
            &self.last_input_hash,
        );
        let metadata = SlotMetadata {
            slot: self.cfg.name.clone(),
            w: self.cfg.width,
            h: self.cfg.height,
            stride: self.bytes_per_row,
            frame_id,
            receiver_class: receiver_class_name(self.cfg.class),
            receiver_class_code: self.cfg.class.as_u32(),
            raw_path: self.cfg.raw_path.display().to_string(),
            output_path: self.cfg.out_path.display().to_string(),
            meta_path: meta_path.display().to_string(),
            intensity: self.cfg.intensity,
            drift_state_intensity: self.last_drift_state_intensity,
            input_hash: self.last_input_hash.clone(),
            output_hash: output_hash.clone(),
            drift_changed: self.last_input_hash != output_hash,
            observed_at_unix_ms: unix_ms_now(),
            producer,
        };
        if let Ok(bytes) = serde_json::to_vec(&metadata) {
            let _ = atomic_write(&meta_path, &bytes);
        }
        self.frame = frame_id;
        true
    }
}

fn pick_adapter(instance: &wgpu::Instance) -> wgpu::Adapter {
    let want = std::env::var("HAPAX_SCREWM_DRIFT_GPU").unwrap_or_else(|_| "5060".to_string());
    let adapters = instance.enumerate_adapters(wgpu::Backends::VULKAN);
    for a in &adapters {
        if a.get_info()
            .name
            .to_lowercase()
            .contains(&want.to_lowercase())
        {
            log::info!("media-drift GPU: {} (matched '{want}')", a.get_info().name);
            return a.clone();
        }
    }
    let fallback = adapters
        .into_iter()
        .next()
        .expect("no Vulkan adapter for media-drift");
    log::warn!(
        "media-drift: no adapter matched '{want}', using {}",
        fallback.get_info().name
    );
    fallback
}

async fn run() {
    let spec = std::env::var("HAPAX_SCREWM_DRIFT_SLOTS").unwrap_or_default();
    let slots = match parse_slot_configs(&spec) {
        Ok(slots) => slots,
        Err(err) => {
            log::error!("invalid HAPAX_SCREWM_DRIFT_SLOTS: {err}");
            return;
        }
    };
    if slots.is_empty() {
        log::error!(
            "HAPAX_SCREWM_DRIFT_SLOTS empty — nothing to drift; set e.g. 'ward-atlas:2048x2304'"
        );
        return;
    }
    let game_data = std::env::var("HAPAX_SCREWM_DRIFT_GAME_DATA")
        .map(PathBuf::from)
        .unwrap_or_else(|_| dirs_home().join(".darkplaces/screwm/data"));
    let fps: f32 = std::env::var("HAPAX_SCREWM_DRIFT_FPS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(20.0);

    let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor {
        backends: wgpu::Backends::VULKAN,
        ..Default::default()
    });
    let adapter = pick_adapter(&instance);
    let (device, queue) = adapter
        .request_device(
            &wgpu::DeviceDescriptor {
                label: Some("screwm-media-drift"),
                required_features: wgpu::Features::empty(),
                required_limits: wgpu::Limits::default(),
                ..Default::default()
            },
            None,
        )
        .await
        .expect("media-drift: request_device failed");

    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("media_drift.wgsl"),
        source: wgpu::ShaderSource::Wgsl(Cow::Borrowed(SHADER_SRC)),
    });
    let bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("media-drift bgl"),
        entries: &[
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
            wgpu::BindGroupLayoutEntry {
                binding: 1,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 2,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                count: None,
            },
        ],
    });
    let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
        label: Some("media-drift layout"),
        bind_group_layouts: &[&bgl],
        push_constant_ranges: &[],
    });
    let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some("media-drift pipeline"),
        layout: Some(&layout),
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
                format: TEX_FORMAT,
                blend: None,
                write_mask: wgpu::ColorWrites::ALL,
            })],
            compilation_options: Default::default(),
        }),
        primitive: wgpu::PrimitiveState::default(),
        depth_stencil: None,
        multisample: wgpu::MultisampleState::default(),
        multiview: None,
        cache: None,
    });
    let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
        label: Some("media-drift sampler"),
        address_mode_u: wgpu::AddressMode::ClampToEdge,
        address_mode_v: wgpu::AddressMode::ClampToEdge,
        address_mode_w: wgpu::AddressMode::ClampToEdge,
        mag_filter: wgpu::FilterMode::Linear,
        min_filter: wgpu::FilterMode::Linear,
        ..Default::default()
    });

    let slot_names = slots
        .iter()
        .map(|slot| slot.name.as_str())
        .collect::<Vec<_>>()
        .join(", ");
    let mut gpus: Vec<SlotGpu> = slots
        .into_iter()
        .map(|c| SlotGpu::new(&device, &bgl, &sampler, c))
        .collect();
    log::info!(
        "media-drift live: {} slot(s) [{}] @ {fps}fps, game_data={}",
        gpus.len(),
        slot_names,
        game_data.display()
    );

    let start = Instant::now();
    let period = Duration::from_secs_f32(1.0 / fps.max(1.0));
    loop {
        let tick = Instant::now();
        let state = load_drift_state(&game_data);
        let now = start.elapsed().as_secs_f32();
        let mut ready = Vec::new();
        let mut commands = Vec::new();
        for (idx, g) in gpus.iter_mut().enumerate() {
            if let Some(command) = g.encode(&device, &queue, &pipeline, &state, now) {
                ready.push(idx);
                commands.push(command);
            }
        }

        if !commands.is_empty() {
            queue.submit(commands);
            let mut waits = Vec::with_capacity(ready.len());
            for idx in ready {
                let (tx, rx) = std::sync::mpsc::channel();
                gpus[idx]
                    .staging
                    .slice(..)
                    .map_async(wgpu::MapMode::Read, move |r| {
                        let _ = tx.send(r);
                    });
                waits.push((idx, rx));
            }
            device.poll(wgpu::Maintain::Wait);
            for (idx, rx) in waits {
                if rx.recv().map(|r| r.is_err()).unwrap_or(true) {
                    gpus[idx].staging.unmap();
                    continue;
                }
                gpus[idx].finish_readback();
            }
        }
        if let Some(rem) = period.checked_sub(tick.elapsed()) {
            std::thread::sleep(rem);
        }
    }
}

fn dirs_home() -> PathBuf {
    std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/root"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;
    use std::fs;
    use tempfile::tempdir;

    #[test]
    fn slot_config_parse_derives_paths_and_receiver_class() {
        let slots =
            parse_slot_configs(" ward-atlas:2048x2304:1.3, ticker-grounding:1344x176 ").unwrap();
        assert_eq!(slots.len(), 2);

        let atlas = &slots[0];
        assert_eq!(atlas.name, "ward-atlas");
        assert_eq!(
            atlas.raw_path,
            Path::new(SHM_DIR).join("quake-live-ward-atlas.raw.bgra")
        );
        assert_eq!(
            atlas.out_path,
            Path::new(SHM_DIR).join("quake-live-ward-atlas.bgra")
        );
        assert_eq!(atlas.width, 2048);
        assert_eq!(atlas.height, 2304);
        assert_eq!(atlas.class, ReceiverClass::Atlas);
        assert_eq!(atlas.intensity, 1.3);

        let ticker = &slots[1];
        assert_eq!(ticker.name, "ticker-grounding");
        assert_eq!(
            ticker.raw_path,
            Path::new(SHM_DIR).join("quake-live-ticker-grounding.raw.bgra")
        );
        assert_eq!(
            ticker.out_path,
            Path::new(SHM_DIR).join("quake-live-ticker-grounding.bgra")
        );
        assert_eq!(ticker.class, ReceiverClass::Ticker);
        assert_eq!(ticker.intensity, 1.0);
    }

    #[test]
    fn slot_config_parse_rejects_malformed_duplicate_or_non_positive_entries() {
        for spec in [
            "ward-atlas",
            "ward-atlas:2048",
            "ward-atlas:0x2304",
            "ward-atlas:2048x0",
            "ward-atlas:2048x2304:0",
            "ward-atlas:2048x2304:nan",
            "ward-atlas:2048x2304:1.0:extra",
            "ward-atlas:2048x2304, ward-atlas:2048x2304",
        ] {
            assert!(
                parse_slot_configs(spec).is_err(),
                "spec should be rejected: {spec}"
            );
        }
    }

    #[test]
    fn frame_reader_requires_exact_frame_size_without_side_effects() {
        let dir = tempdir().unwrap();
        let frame = dir.path().join("slot.raw.bgra");
        fs::write(&frame, vec![1u8; 15]).unwrap();

        assert!(read_complete_frame(&frame, 16).is_none());
        assert!(read_complete_frame(&dir.path().join("missing.raw.bgra"), 16).is_none());

        fs::write(&frame, vec![2u8; 16]).unwrap();
        assert_eq!(read_complete_frame(&frame, 16).unwrap(), vec![2u8; 16]);
    }

    #[test]
    fn producer_sidecar_path_derives_raw_json_sibling() {
        let raw_path = Path::new("/tmp/quake-live-ward-atlas.raw.bgra");
        assert_eq!(
            producer_sidecar_path_for(raw_path),
            Path::new("/tmp/quake-live-ward-atlas.raw.json")
        );
    }

    #[test]
    fn producer_raw_sidecar_reader_is_tolerant() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("slot.raw.json");

        assert!(read_producer_raw_sidecar(&path).is_none());

        fs::write(&path, b"{not-json").unwrap();
        assert!(read_producer_raw_sidecar(&path).is_none());

        fs::write(&path, br#"["not", "an", "object"]"#).unwrap();
        assert!(read_producer_raw_sidecar(&path).is_none());

        fs::write(
            &path,
            br#"{
                "source": "ticker",
                "renderer": "cairo-pango",
                "drift_renderer": "quake-media-drift-v1",
                "frames": 42,
                "gpu_drift": true,
                "gpu_drift_raw_output": "/tmp/quake-live-ticker.raw.bgra",
                "gpu_drift_final_output": "/tmp/quake-live-ticker.bgra",
                "gpu_drift_output_owner": "screwm_media_drift",
                "drift_input_hash": "abc123",
                "preflip_y": true,
                "updated_at": 123.5
            }"#,
        )
        .unwrap();

        let sidecar = read_producer_raw_sidecar(&path).unwrap();
        assert_eq!(sidecar.source, "ticker");
        assert_eq!(sidecar.renderer, "cairo-pango");
        assert_eq!(sidecar.drift_renderer, "quake-media-drift-v1");
        assert_eq!(sidecar.frames, Some(42));
        assert!(sidecar.gpu_drift);
        assert_eq!(
            sidecar.gpu_drift_raw_output,
            "/tmp/quake-live-ticker.raw.bgra"
        );
        assert_eq!(sidecar.preflip_y, Some(true));
        assert_eq!(sidecar.updated_at, Some(123.5));
    }

    #[test]
    fn producer_sidecar_metadata_records_claim_matches() {
        let sidecar_path = Path::new("/tmp/quake-live-ward-atlas.raw.json");
        let raw_path = Path::new("/tmp/quake-live-ward-atlas.raw.bgra");
        let output_path = Path::new("/tmp/quake-live-ward-atlas.bgra");
        let sidecar = ProducerRawSidecar {
            source: "ward-atlas".to_string(),
            renderer: "quake-live-ward-atlas-source".to_string(),
            drift_renderer: "quake-media-drift-v1".to_string(),
            frame_id: Some(7),
            frames: None,
            updated_at: None,
            observed_at: Some(456.25),
            gpu_drift: true,
            gpu_drift_raw_output: raw_path.display().to_string(),
            gpu_drift_final_output: output_path.display().to_string(),
            gpu_drift_output_owner: "screwm_media_drift".to_string(),
            drift_input_hash: "input-hash".to_string(),
            preflip_y: None,
        };

        let metadata = ProducerSidecarMetadata::from_sidecar(
            sidecar_path,
            Some(&sidecar),
            raw_path,
            output_path,
            "input-hash",
        );
        assert!(metadata.producer_sidecar_present);
        assert_eq!(metadata.producer_source, "ward-atlas");
        assert_eq!(metadata.producer_renderer, "quake-live-ward-atlas-source");
        assert_eq!(metadata.producer_drift_renderer, "quake-media-drift-v1");
        assert_eq!(metadata.producer_frame_id, Some(7));
        assert_eq!(metadata.producer_observed_at_unix_s, Some(456.25));
        assert!(metadata.producer_gpu_drift);
        assert!(metadata.producer_raw_output_matches_raw_path);
        assert!(metadata.producer_final_output_matches_output_path);
        assert!(metadata.producer_output_owner_matches);
        assert!(metadata.producer_input_hash_matches_raw);

        let mut mismatched = sidecar;
        mismatched.gpu_drift_raw_output = "/tmp/other.raw.bgra".to_string();
        mismatched.gpu_drift_final_output = "/tmp/other.bgra".to_string();
        mismatched.gpu_drift_output_owner = "producer".to_string();
        mismatched.drift_input_hash = "stale-hash".to_string();
        let metadata = ProducerSidecarMetadata::from_sidecar(
            sidecar_path,
            Some(&mismatched),
            raw_path,
            output_path,
            "input-hash",
        );
        assert!(!metadata.producer_raw_output_matches_raw_path);
        assert!(!metadata.producer_final_output_matches_output_path);
        assert!(!metadata.producer_output_owner_matches);
        assert!(!metadata.producer_input_hash_matches_raw);

        let absent =
            ProducerSidecarMetadata::from_sidecar(sidecar_path, None, raw_path, output_path, "");
        assert!(!absent.producer_sidecar_present);
        assert_eq!(
            absent.producer_sidecar_path,
            "/tmp/quake-live-ward-atlas.raw.json"
        );
    }

    #[test]
    fn stable_hash_and_atomic_write_are_deterministic() {
        assert_eq!(stable_short_hash(b"abc"), "e71fa2190541574b");
        assert_eq!(stable_short_hash(b"abc"), stable_short_hash(b"abc"));
        assert_ne!(stable_short_hash(b"abc"), stable_short_hash(b"abcd"));

        let dir = tempdir().unwrap();
        let path = dir.path().join("quake-live-slot.json");
        let tmp = tmp_path_for(&path);
        atomic_write(&path, br#"{"ok":true}"#).unwrap();
        assert_eq!(fs::read_to_string(&path).unwrap(), r#"{"ok":true}"#);
        assert!(!tmp.exists());
    }

    #[test]
    fn slot_metadata_serializes_gpu_output_audit_fields() {
        let sidecar_path = Path::new("/tmp/quake-live-ward-atlas.raw.json");
        let raw_path = Path::new("/tmp/quake-live-ward-atlas.raw.bgra");
        let output_path = Path::new("/tmp/quake-live-ward-atlas.bgra");
        let sidecar = ProducerRawSidecar {
            source: "ward-atlas".to_string(),
            renderer: "quake-live-ward-atlas-source".to_string(),
            drift_renderer: "quake-media-drift-v1".to_string(),
            frame_id: Some(8),
            frames: None,
            updated_at: None,
            observed_at: Some(777.0),
            gpu_drift: true,
            gpu_drift_raw_output: raw_path.display().to_string(),
            gpu_drift_final_output: output_path.display().to_string(),
            gpu_drift_output_owner: "screwm_media_drift".to_string(),
            drift_input_hash: "input".to_string(),
            preflip_y: Some(false),
        };
        let meta = SlotMetadata {
            slot: "ward-atlas".to_string(),
            w: 2048,
            h: 2304,
            stride: 8192,
            frame_id: 9,
            receiver_class: receiver_class_name(ReceiverClass::Atlas),
            receiver_class_code: ReceiverClass::Atlas.as_u32(),
            raw_path: "/tmp/quake-live-ward-atlas.raw.bgra".to_string(),
            output_path: "/tmp/quake-live-ward-atlas.bgra".to_string(),
            meta_path: "/tmp/quake-live-ward-atlas.json".to_string(),
            intensity: 1.3,
            drift_state_intensity: 0.52,
            input_hash: "input".to_string(),
            output_hash: "output".to_string(),
            drift_changed: true,
            observed_at_unix_ms: 123,
            producer: ProducerSidecarMetadata::from_sidecar(
                sidecar_path,
                Some(&sidecar),
                raw_path,
                output_path,
                "input",
            ),
        };
        let value: Value = serde_json::from_slice(&serde_json::to_vec(&meta).unwrap()).unwrap();
        assert_eq!(value["slot"], "ward-atlas");
        assert_eq!(value["w"], 2048);
        assert_eq!(value["h"], 2304);
        assert_eq!(value["stride"], 8192);
        assert_eq!(value["frame_id"], 9);
        assert_eq!(value["receiver_class"], "atlas");
        assert_eq!(value["receiver_class_code"], ReceiverClass::Atlas.as_u32());
        assert_eq!(value["raw_path"], "/tmp/quake-live-ward-atlas.raw.bgra");
        assert_eq!(value["output_path"], "/tmp/quake-live-ward-atlas.bgra");
        assert_eq!(value["meta_path"], "/tmp/quake-live-ward-atlas.json");
        assert_eq!(value["drift_state_intensity"], 0.52);
        assert_eq!(value["input_hash"], "input");
        assert_eq!(value["output_hash"], "output");
        assert_eq!(value["drift_changed"], true);
        assert_eq!(
            value["producer_sidecar_path"],
            "/tmp/quake-live-ward-atlas.raw.json"
        );
        assert_eq!(value["producer_sidecar_present"], true);
        assert_eq!(value["producer_source"], "ward-atlas");
        assert_eq!(value["producer_renderer"], "quake-live-ward-atlas-source");
        assert_eq!(value["producer_drift_renderer"], "quake-media-drift-v1");
        assert_eq!(value["producer_frame_id"], 8);
        assert_eq!(value["producer_observed_at_unix_s"], 777.0);
        assert_eq!(value["producer_gpu_drift"], true);
        assert_eq!(value["producer_raw_output"], raw_path.display().to_string());
        assert_eq!(
            value["producer_final_output"],
            output_path.display().to_string()
        );
        assert_eq!(value["producer_output_owner"], "screwm_media_drift");
        assert_eq!(value["producer_input_hash"], "input");
        assert_eq!(value["producer_preflip_y"], false);
        assert_eq!(value["producer_raw_output_matches_raw_path"], true);
        assert_eq!(value["producer_final_output_matches_output_path"], true);
        assert_eq!(value["producer_output_owner_matches"], true);
        assert_eq!(value["producer_input_hash_matches_raw"], true);
    }
}

fn main() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();
    pollster::block_on(run());
}
