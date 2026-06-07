//! screwm_media_drift — GPU media-drift service.
//!
//! Spec: docs/superpowers/specs/2026-05-30-screwm-gpu-drift-port-design.md.
//!
//! Headless wgpu on the 5060 Ti. For each configured slot: read the producer's
//! *raw* (undrifted) BGRA from `/dev/shm`, apply `media_drift.wgsl` driven by the
//! live `DriftState`, and write the *drifted* BGRA back to the slot path the
//! DarkPlaces engine blits — replacing the producers' Python numpy drift.
//!
//! Config (env `HAPAX_SCREWM_DRIFT_SLOTS`, comma list):
//! `name:WxH[:intensity][:projection[:rawWxH[:RRGGBB]]]`, e.g.
//! `ward-atlas:2048x2304,yt:2048x1024:1.6:sphere-front:1820x1024:0c0b0d`.
//! Paths derive from the name: in = `quake-live-<name>.raw.bgra`, out =
//! `quake-live-<name>.bgra`.

use std::borrow::Cow;
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use blake2::digest::{Update, VariableOutput};
use blake2::Blake2sVar;
use hapax_visual::media_drift::{load_drift_state, DriftUniforms, ReceiverClass};
use serde::{Deserialize, Serialize};

const SHADER_SRC: &str = include_str!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../agents/shaders/nodes/media_drift.wgsl"
));
const SHM_DIR: &str = "/dev/shm/hapax-compositor";
const TEX_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Bgra8Unorm;
const DEFAULT_PROJECTION_BACKGROUND_RGB: [f32; 3] = [
    0x0c as f32 / 255.0,
    0x0b as f32 / 255.0,
    0x0d as f32 / 255.0,
];

fn align_up(v: u32, a: u32) -> u32 {
    (v + a - 1) & !(a - 1)
}

#[derive(Debug, Clone, PartialEq)]
enum ProjectionKind {
    Flat,
    SphereFront,
}

impl ProjectionKind {
    fn parse(value: &str) -> Result<Self, String> {
        match value.trim().to_ascii_lowercase().as_str() {
            "flat" => Ok(Self::Flat),
            "sphere-front" => Ok(Self::SphereFront),
            other => Err(format!("unknown projection kind {other:?}")),
        }
    }

    fn as_u32(&self) -> u32 {
        match self {
            Self::Flat => 0,
            Self::SphereFront => 1,
        }
    }

    fn as_str(&self) -> &'static str {
        match self {
            Self::Flat => "flat",
            Self::SphereFront => "sphere-front",
        }
    }

    fn requires_raw_dims(&self) -> bool {
        matches!(self, Self::SphereFront)
    }
}

#[derive(Debug, Clone, PartialEq)]
struct SlotConfig {
    name: String,
    raw_path: PathBuf,
    out_path: PathBuf,
    width: u32,
    height: u32,
    raw_width: u32,
    raw_height: u32,
    class: ReceiverClass,
    intensity: f32,
    projection: ProjectionKind,
    projection_background_rgb: [f32; 3],
}

impl SlotConfig {
    /// Parse one `name:WxH[:intensity]` spec.
    fn parse(spec: &str) -> Result<Self, String> {
        let fields: Vec<&str> = spec.split(':').map(str::trim).collect();
        if fields.is_empty() {
            return Err(format!("slot spec {spec:?} is empty"));
        }
        let name = fields[0].to_ascii_lowercase();
        if name.is_empty() {
            return Err(format!("slot spec {spec:?} has an empty name"));
        }
        if fields.len() < 2 {
            return Err(format!("slot {name:?} must include WxH dimensions"));
        }
        let (w, h) = parse_dims(&name, fields[1], "output")?;
        let mut raw_width = w;
        let mut raw_height = h;
        let mut intensity = 1.0;
        let mut projection = ProjectionKind::Flat;
        let mut projection_background_rgb = DEFAULT_PROJECTION_BACKGROUND_RGB;
        let mut idx = 2;

        if idx < fields.len() {
            match fields[idx].parse::<f32>() {
                Ok(parsed_intensity) => {
                    intensity = parsed_intensity;
                    idx += 1;
                }
                Err(_) => {}
            }
        }
        if !intensity.is_finite() || intensity <= 0.0 {
            return Err(format!("slot {name:?} intensity must be positive"));
        }

        if idx < fields.len() {
            projection = ProjectionKind::parse(fields[idx])?;
            idx += 1;
            if projection.requires_raw_dims() {
                let raw_dims = fields
                    .get(idx)
                    .ok_or_else(|| format!("slot {name:?} projection requires raw WxH"))?;
                (raw_width, raw_height) = parse_dims(&name, raw_dims, "raw")?;
                idx += 1;
                if let Some(background) = fields.get(idx) {
                    projection_background_rgb = parse_hex_rgb(&name, background)?;
                    idx += 1;
                }
            }
        }
        if idx != fields.len() {
            return Err(format!("slot {name:?} has too many ':' fields"));
        }
        Ok(Self {
            raw_path: PathBuf::from(format!("{SHM_DIR}/quake-live-{name}.raw.bgra")),
            out_path: PathBuf::from(format!("{SHM_DIR}/quake-live-{name}.bgra")),
            class: ReceiverClass::from_name(&name),
            name,
            width: w,
            height: h,
            raw_width,
            raw_height,
            intensity,
            projection,
            projection_background_rgb,
        })
    }
}

fn parse_dims(slot_name: &str, dims: &str, label: &str) -> Result<(u32, u32), String> {
    let (ws, hs) = dims
        .split_once('x')
        .ok_or_else(|| format!("slot {slot_name:?} {label} dimensions must use WxH"))?;
    let width: u32 = ws
        .trim()
        .parse()
        .map_err(|_| format!("slot {slot_name:?} {label} width must be an integer"))?;
    let height: u32 = hs
        .trim()
        .parse()
        .map_err(|_| format!("slot {slot_name:?} {label} height must be an integer"))?;
    if width == 0 || height == 0 {
        return Err(format!(
            "slot {slot_name:?} {label} dimensions must be positive"
        ));
    }
    Ok((width, height))
}

fn parse_hex_rgb(slot_name: &str, value: &str) -> Result<[f32; 3], String> {
    let text = value.trim().trim_start_matches('#');
    if text.len() != 6 || !text.chars().all(|ch| ch.is_ascii_hexdigit()) {
        return Err(format!(
            "slot {slot_name:?} projection background must be 6-digit RGB"
        ));
    }
    let parse_pair = |range: std::ops::Range<usize>| -> Result<f32, String> {
        u8::from_str_radix(&text[range], 16)
            .map(|value| value as f32 / 255.0)
            .map_err(|_| format!("slot {slot_name:?} projection background is invalid RGB"))
    };
    Ok([parse_pair(0..2)?, parse_pair(2..4)?, parse_pair(4..6)?])
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
    let mut hasher = Blake2sVar::new(8).expect("blake2s supports 8-byte output");
    hasher.update(bytes);
    let mut digest = [0u8; 8];
    hasher
        .finalize_variable(&mut digest)
        .expect("digest buffer has requested length");
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
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

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct RawSignature {
    len: u64,
    modified_ns: u128,
}

fn raw_signature(path: &Path, expected_bytes: usize) -> Option<RawSignature> {
    let meta = std::fs::metadata(path).ok()?;
    if meta.len() != expected_bytes as u64 {
        return None;
    }
    let modified_ns = meta
        .modified()
        .ok()
        .and_then(|modified| modified.duration_since(UNIX_EPOCH).ok())
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    Some(RawSignature {
        len: meta.len(),
        modified_ns,
    })
}

fn producer_sidecar_path_for(raw_path: &Path) -> PathBuf {
    raw_path.with_extension("json")
}

#[derive(Debug, Clone, Default, Deserialize, PartialEq)]
struct ProducerRawSidecar {
    #[serde(default)]
    source: String,
    #[serde(default)]
    camera_role: String,
    #[serde(default)]
    camera_configured_device: String,
    #[serde(default)]
    camera_runtime_device: String,
    #[serde(default)]
    camera_runtime_format: String,
    #[serde(default)]
    camera_runtime_size: String,
    #[serde(default)]
    camera_runtime_fps: Option<f64>,
    #[serde(default)]
    camera_runtime_substitute: Option<bool>,
    #[serde(default)]
    camera_runtime_substitute_reason: String,
    #[serde(default)]
    fallback_reason: String,
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
    producer_camera_role: String,
    producer_camera_configured_device: String,
    producer_camera_runtime_device: String,
    producer_camera_runtime_format: String,
    producer_camera_runtime_size: String,
    producer_camera_runtime_fps: Option<f64>,
    producer_camera_runtime_substitute: Option<bool>,
    producer_camera_runtime_substitute_reason: String,
    producer_fallback_reason: String,
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
            producer_camera_role: String::new(),
            producer_camera_configured_device: String::new(),
            producer_camera_runtime_device: String::new(),
            producer_camera_runtime_format: String::new(),
            producer_camera_runtime_size: String::new(),
            producer_camera_runtime_fps: None,
            producer_camera_runtime_substitute: None,
            producer_camera_runtime_substitute_reason: String::new(),
            producer_fallback_reason: String::new(),
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
            producer_camera_role: sidecar.camera_role.clone(),
            producer_camera_configured_device: sidecar.camera_configured_device.clone(),
            producer_camera_runtime_device: sidecar.camera_runtime_device.clone(),
            producer_camera_runtime_format: sidecar.camera_runtime_format.clone(),
            producer_camera_runtime_size: sidecar.camera_runtime_size.clone(),
            producer_camera_runtime_fps: sidecar.camera_runtime_fps,
            producer_camera_runtime_substitute: sidecar.camera_runtime_substitute,
            producer_camera_runtime_substitute_reason: sidecar
                .camera_runtime_substitute_reason
                .clone(),
            producer_fallback_reason: sidecar.fallback_reason.clone(),
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
    raw_w: u32,
    raw_h: u32,
    stride: u32,
    raw_stride: u32,
    frame_id: u64,
    receiver_class: &'static str,
    receiver_class_code: u32,
    projection: &'static str,
    projection_code: u32,
    raw_path: String,
    output_path: String,
    meta_path: String,
    intensity: f32,
    drift_state_intensity: f32,
    input_hash: String,
    output_hash: String,
    hash_full: bool,
    hash_every_frames: u64,
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
    prev_tex: wgpu::Texture,
    prev_view: wgpu::TextureView,
    uniform: wgpu::Buffer,
    bind_group: wgpu::BindGroup,
    staging: wgpu::Buffer,
    raw_bytes_per_row: u32,
    bytes_per_row: u32,
    padded_bytes_per_row: u32,
    expected_bytes: usize,
    output_expected_bytes: usize,
    hash_every_frames: u64,
    frame: u64,
    last_raw_signature: Option<RawSignature>,
    last_input_hash: String,
    last_output_hash: String,
    last_hash_full: bool,
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
        hash_every_frames: u64,
    ) -> Self {
        let raw_size = wgpu::Extent3d {
            width: cfg.raw_width,
            height: cfg.raw_height,
            depth_or_array_layers: 1,
        };
        let out_size = wgpu::Extent3d {
            width: cfg.width,
            height: cfg.height,
            depth_or_array_layers: 1,
        };
        let in_tex = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("media-drift in"),
            size: raw_size,
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: TEX_FORMAT,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });
        let out_tex = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("media-drift out"),
            size: out_size,
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: TEX_FORMAT,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let prev_tex = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("media-drift previous"),
            size: out_size,
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: TEX_FORMAT,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT
                | wgpu::TextureUsages::TEXTURE_BINDING
                | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });
        let out_view = out_tex.create_view(&wgpu::TextureViewDescriptor::default());
        let prev_view = prev_tex.create_view(&wgpu::TextureViewDescriptor::default());
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
                wgpu::BindGroupEntry {
                    binding: 3,
                    resource: wgpu::BindingResource::TextureView(&prev_view),
                },
            ],
        });
        let raw_bytes_per_row = cfg.raw_width * 4;
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
            expected_bytes: (cfg.raw_width * cfg.raw_height * 4) as usize,
            output_expected_bytes: (cfg.width * cfg.height * 4) as usize,
            hash_every_frames,
            cfg,
            in_tex,
            out_tex,
            out_view,
            prev_tex,
            prev_view,
            uniform,
            bind_group,
            staging,
            raw_bytes_per_row,
            bytes_per_row,
            padded_bytes_per_row,
            frame: 0,
            last_raw_signature: None,
            last_input_hash: String::new(),
            last_output_hash: String::new(),
            last_hash_full: false,
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
        let signature = raw_signature(&self.cfg.raw_path, self.expected_bytes)?;
        if self.last_raw_signature == Some(signature) {
            return None;
        }
        let raw = read_complete_frame(&self.cfg.raw_path, self.expected_bytes)?;
        self.last_raw_signature = Some(signature);
        let next_frame = self.frame + 1;
        self.last_hash_full = next_frame == 1
            || self.hash_every_frames <= 1
            || next_frame % self.hash_every_frames == 0;
        if self.last_hash_full {
            self.last_input_hash = stable_short_hash(&raw);
        }
        self.last_drift_state_intensity = state.intensity();

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
                bytes_per_row: Some(self.raw_bytes_per_row),
                rows_per_image: Some(self.cfg.raw_height),
            },
            wgpu::Extent3d {
                width: self.cfg.raw_width,
                height: self.cfg.raw_height,
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
            self.cfg.projection.as_u32(),
            self.cfg.raw_width,
            self.cfg.raw_height,
            self.cfg.projection_background_rgb,
        );
        queue.write_buffer(&self.uniform, 0, bytemuck::bytes_of(&u));

        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
            label: Some("media-drift enc"),
        });
        if self.frame == 0 {
            let _clear_prev = enc.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("media-drift clear previous"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &self.prev_view,
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
        }
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
        enc.copy_texture_to_texture(
            wgpu::TexelCopyTextureInfo {
                texture: &self.out_tex,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::TexelCopyTextureInfo {
                texture: &self.prev_tex,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
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
        let mut out = Vec::with_capacity(self.output_expected_bytes);
        if self.padded_bytes_per_row == self.bytes_per_row {
            out.extend_from_slice(&mapped[..self.output_expected_bytes]);
        } else {
            for row in 0..self.cfg.height {
                let s = (row * self.padded_bytes_per_row) as usize;
                out.extend_from_slice(&mapped[s..s + self.bytes_per_row as usize]);
            }
        }
        drop(mapped);
        self.staging.unmap();

        let output_hash = if self.last_hash_full {
            stable_short_hash(&out)
        } else {
            self.last_output_hash.clone()
        };
        if atomic_write(&self.cfg.out_path, &out).is_err() {
            return false;
        }
        if self.last_hash_full {
            self.last_output_hash = output_hash.clone();
        }

        self.last_producer_sidecar = read_producer_raw_sidecar(&self.last_producer_sidecar_path);
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
            raw_w: self.cfg.raw_width,
            raw_h: self.cfg.raw_height,
            stride: self.bytes_per_row,
            raw_stride: self.cfg.raw_width * 4,
            frame_id,
            receiver_class: receiver_class_name(self.cfg.class),
            receiver_class_code: self.cfg.class.as_u32(),
            projection: self.cfg.projection.as_str(),
            projection_code: self.cfg.projection.as_u32(),
            raw_path: self.cfg.raw_path.display().to_string(),
            output_path: self.cfg.out_path.display().to_string(),
            meta_path: meta_path.display().to_string(),
            intensity: self.cfg.intensity,
            drift_state_intensity: self.last_drift_state_intensity,
            input_hash: self.last_input_hash.clone(),
            output_hash: output_hash.clone(),
            hash_full: self.last_hash_full,
            hash_every_frames: self.hash_every_frames,
            drift_changed: if self.last_hash_full {
                self.last_input_hash != output_hash
            } else {
                true
            },
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
    let hash_every_frames: u64 = std::env::var("HAPAX_SCREWM_DRIFT_FULL_HASH_EVERY_N")
        .ok()
        .and_then(|s| s.parse().ok())
        .filter(|v| *v > 0)
        .unwrap_or(10);

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
            wgpu::BindGroupLayoutEntry {
                binding: 3,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
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
        .map(|c| SlotGpu::new(&device, &bgl, &sampler, c, hash_every_frames))
        .collect();
    log::info!(
        "media-drift live: {} slot(s) [{}] @ {fps}fps, full_hash_every={} frame(s), game_data={}",
        gpus.len(),
        slot_names,
        hash_every_frames,
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

    const SYNTHS_IR_CONFIGURED_DEVICE: &str =
        "/dev/v4l/by-id/usb-046d_Logitech_BRIO_9726C031-video-index2";
    const SYNTHS_IR_SUBSTITUTE_RAW_PATH: &str =
        "/dev/shm/hapax-compositor/quake-live-cam-c920-desk.raw.bgra";
    const SYNTHS_IR_SUBSTITUTE_REASON: &str = "ir_endpoint_unavailable:c920_desk_rgb_substitute";
    const SYNTHS_IR_FALLBACK_REASON: &str =
        "camera_substitute_forced:ir_endpoint_unavailable:c920_desk_rgb_substitute:raw:c920-desk";

    fn synths_substitute_sidecar(
        source: &str,
        renderer: &str,
        raw_path: &Path,
        output_path: &Path,
        frame_id: Option<u64>,
        observed_at: Option<f64>,
        input_hash: &str,
        preflip_y: Option<bool>,
    ) -> ProducerRawSidecar {
        ProducerRawSidecar {
            source: source.to_string(),
            camera_role: "brio-synths-ir".to_string(),
            camera_configured_device: SYNTHS_IR_CONFIGURED_DEVICE.to_string(),
            camera_runtime_device: SYNTHS_IR_SUBSTITUTE_RAW_PATH.to_string(),
            camera_runtime_format: "raw-bgra".to_string(),
            camera_runtime_size: "1280x720".to_string(),
            camera_runtime_fps: Some(6.0),
            camera_runtime_substitute: Some(true),
            camera_runtime_substitute_reason: SYNTHS_IR_SUBSTITUTE_REASON.to_string(),
            fallback_reason: SYNTHS_IR_FALLBACK_REASON.to_string(),
            renderer: renderer.to_string(),
            drift_renderer: "quake-media-drift-v1".to_string(),
            frame_id,
            frames: None,
            updated_at: None,
            observed_at,
            gpu_drift: true,
            gpu_drift_raw_output: raw_path.display().to_string(),
            gpu_drift_final_output: output_path.display().to_string(),
            gpu_drift_output_owner: "screwm_media_drift".to_string(),
            drift_input_hash: input_hash.to_string(),
            preflip_y,
        }
    }

    #[test]
    fn slot_config_parse_derives_paths_and_receiver_class() {
        let slots = parse_slot_configs(
            " yt:2048x1024:1.6:sphere-front:1820x1024:0c0b0d, ward-atlas:2048x2304:1.3, ticker-grounding:1344x176, ir-brio-operator:340x340 ",
        )
        .unwrap();
        assert_eq!(slots.len(), 4);

        let atlas = &slots[0];
        assert_eq!(atlas.name, "yt");
        assert_eq!(atlas.width, 2048);
        assert_eq!(atlas.height, 1024);
        assert_eq!(atlas.raw_width, 1820);
        assert_eq!(atlas.raw_height, 1024);
        assert_eq!(atlas.class, ReceiverClass::Oarb);
        assert_eq!(atlas.intensity, 1.6);
        assert_eq!(atlas.projection, ProjectionKind::SphereFront);
        assert_eq!(atlas.projection.as_u32(), 1);
        assert_eq!(
            atlas.projection_background_rgb,
            DEFAULT_PROJECTION_BACKGROUND_RGB
        );

        let atlas = &slots[1];
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
        assert_eq!(atlas.raw_width, 2048);
        assert_eq!(atlas.raw_height, 2304);
        assert_eq!(atlas.class, ReceiverClass::Atlas);
        assert_eq!(atlas.intensity, 1.3);
        assert_eq!(atlas.projection, ProjectionKind::Flat);

        let ticker = &slots[2];
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

        let ir = &slots[3];
        assert_eq!(ir.name, "ir-brio-operator");
        assert_eq!(
            ir.raw_path,
            Path::new(SHM_DIR).join("quake-live-ir-brio-operator.raw.bgra")
        );
        assert_eq!(
            ir.out_path,
            Path::new(SHM_DIR).join("quake-live-ir-brio-operator.bgra")
        );
        assert_eq!(ir.class, ReceiverClass::Camera);
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
            "yt:2048x1024:sphere-front",
            "yt:2048x1024:sphere-front:0x1024",
            "yt:2048x1024:sphere-front:1820x1024:not-rgb",
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
    fn raw_signature_tracks_complete_frame_rewrites() {
        let dir = tempdir().unwrap();
        let frame = dir.path().join("slot.raw.bgra");

        assert!(raw_signature(&frame, 16).is_none());
        fs::write(&frame, vec![1u8; 15]).unwrap();
        assert!(raw_signature(&frame, 16).is_none());

        fs::write(&frame, vec![2u8; 16]).unwrap();
        let first = raw_signature(&frame, 16).unwrap();
        std::thread::sleep(Duration::from_millis(2));
        fs::write(&frame, vec![3u8; 16]).unwrap();
        let second = raw_signature(&frame, 16).unwrap();

        assert_eq!(first.len, 16);
        assert_eq!(second.len, 16);
        assert_ne!(first, second);
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

        let payload = format!(
            r#"{{
                "source": "ticker",
                "camera_role": "brio-synths-ir",
                "camera_configured_device": "{SYNTHS_IR_CONFIGURED_DEVICE}",
                "camera_runtime_device": "{SYNTHS_IR_SUBSTITUTE_RAW_PATH}",
                "camera_runtime_format": "raw-bgra",
                "camera_runtime_size": "1280x720",
                "camera_runtime_fps": 6,
                "camera_runtime_substitute": true,
                "camera_runtime_substitute_reason": "{SYNTHS_IR_SUBSTITUTE_REASON}",
                "fallback_reason": "{SYNTHS_IR_FALLBACK_REASON}",
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
            }}"#
        );
        fs::write(&path, payload).unwrap();

        let sidecar = read_producer_raw_sidecar(&path).unwrap();
        assert_eq!(sidecar.source, "ticker");
        assert_eq!(sidecar.camera_role, "brio-synths-ir");
        assert_eq!(
            sidecar.camera_configured_device,
            SYNTHS_IR_CONFIGURED_DEVICE
        );
        assert_eq!(sidecar.camera_runtime_device, SYNTHS_IR_SUBSTITUTE_RAW_PATH);
        assert_eq!(sidecar.camera_runtime_format, "raw-bgra");
        assert_eq!(sidecar.camera_runtime_size, "1280x720");
        assert_eq!(sidecar.camera_runtime_fps, Some(6.0));
        assert_eq!(sidecar.camera_runtime_substitute, Some(true));
        assert_eq!(
            sidecar.camera_runtime_substitute_reason,
            SYNTHS_IR_SUBSTITUTE_REASON
        );
        assert_eq!(sidecar.fallback_reason, SYNTHS_IR_FALLBACK_REASON);
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
        let sidecar = synths_substitute_sidecar(
            "ward-atlas",
            "quake-live-ward-atlas-source",
            raw_path,
            output_path,
            Some(7),
            Some(456.25),
            "input-hash",
            None,
        );

        let metadata = ProducerSidecarMetadata::from_sidecar(
            sidecar_path,
            Some(&sidecar),
            raw_path,
            output_path,
            "input-hash",
        );
        assert!(metadata.producer_sidecar_present);
        assert_eq!(metadata.producer_source, "ward-atlas");
        assert_eq!(metadata.producer_camera_role, "brio-synths-ir");
        assert_eq!(
            metadata.producer_camera_configured_device,
            SYNTHS_IR_CONFIGURED_DEVICE
        );
        assert_eq!(
            metadata.producer_camera_runtime_device,
            SYNTHS_IR_SUBSTITUTE_RAW_PATH
        );
        assert_eq!(metadata.producer_camera_runtime_format, "raw-bgra");
        assert_eq!(metadata.producer_camera_runtime_size, "1280x720");
        assert_eq!(metadata.producer_camera_runtime_fps, Some(6.0));
        assert_eq!(metadata.producer_camera_runtime_substitute, Some(true));
        assert_eq!(
            metadata.producer_camera_runtime_substitute_reason,
            SYNTHS_IR_SUBSTITUTE_REASON
        );
        assert_eq!(metadata.producer_fallback_reason, SYNTHS_IR_FALLBACK_REASON);
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
        assert_eq!(stable_short_hash(b"abc"), "972e9d2cd6de6402");
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
        let sidecar = synths_substitute_sidecar(
            "ward-atlas",
            "quake-live-ward-atlas-source",
            raw_path,
            output_path,
            Some(8),
            Some(777.0),
            "input",
            Some(false),
        );
        let meta = SlotMetadata {
            slot: "ward-atlas".to_string(),
            w: 2048,
            h: 2304,
            raw_w: 2048,
            raw_h: 2304,
            stride: 8192,
            raw_stride: 8192,
            frame_id: 9,
            receiver_class: receiver_class_name(ReceiverClass::Atlas),
            receiver_class_code: ReceiverClass::Atlas.as_u32(),
            projection: ProjectionKind::Flat.as_str(),
            projection_code: ProjectionKind::Flat.as_u32(),
            raw_path: "/tmp/quake-live-ward-atlas.raw.bgra".to_string(),
            output_path: "/tmp/quake-live-ward-atlas.bgra".to_string(),
            meta_path: "/tmp/quake-live-ward-atlas.json".to_string(),
            intensity: 1.3,
            drift_state_intensity: 0.52,
            input_hash: "input".to_string(),
            output_hash: "output".to_string(),
            hash_full: true,
            hash_every_frames: 10,
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
        assert_eq!(value["raw_w"], 2048);
        assert_eq!(value["raw_h"], 2304);
        assert_eq!(value["stride"], 8192);
        assert_eq!(value["raw_stride"], 8192);
        assert_eq!(value["frame_id"], 9);
        assert_eq!(value["receiver_class"], "atlas");
        assert_eq!(value["receiver_class_code"], ReceiverClass::Atlas.as_u32());
        assert_eq!(value["projection"], "flat");
        assert_eq!(value["projection_code"], 0);
        assert_eq!(value["raw_path"], "/tmp/quake-live-ward-atlas.raw.bgra");
        assert_eq!(value["output_path"], "/tmp/quake-live-ward-atlas.bgra");
        assert_eq!(value["meta_path"], "/tmp/quake-live-ward-atlas.json");
        assert_eq!(value["drift_state_intensity"], 0.52);
        assert_eq!(value["input_hash"], "input");
        assert_eq!(value["output_hash"], "output");
        assert_eq!(value["hash_full"], true);
        assert_eq!(value["hash_every_frames"], 10);
        assert_eq!(value["drift_changed"], true);
        assert_eq!(
            value["producer_sidecar_path"],
            "/tmp/quake-live-ward-atlas.raw.json"
        );
        assert_eq!(value["producer_sidecar_present"], true);
        assert_eq!(value["producer_source"], "ward-atlas");
        assert_eq!(value["producer_camera_role"], "brio-synths-ir");
        assert_eq!(
            value["producer_camera_configured_device"],
            SYNTHS_IR_CONFIGURED_DEVICE
        );
        assert_eq!(
            value["producer_camera_runtime_device"],
            SYNTHS_IR_SUBSTITUTE_RAW_PATH
        );
        assert_eq!(value["producer_camera_runtime_format"], "raw-bgra");
        assert_eq!(value["producer_camera_runtime_size"], "1280x720");
        assert_eq!(value["producer_camera_runtime_fps"], 6.0);
        assert_eq!(value["producer_camera_runtime_substitute"], true);
        assert_eq!(
            value["producer_camera_runtime_substitute_reason"],
            SYNTHS_IR_SUBSTITUTE_REASON
        );
        assert_eq!(value["producer_fallback_reason"], SYNTHS_IR_FALLBACK_REASON);
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
