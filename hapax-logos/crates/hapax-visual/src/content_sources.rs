//! Content source manager — scans shm for arbitrary RGBA/text content sources,
//! manages GPU textures, composites onto ground field.

use crate::aoa_panes::{
    aoa_active_pane_manifest, AoaPaneBindingMode, AoaPaneLodClass, AoaPanePrivacyClass,
};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::env;
use std::path::{Path, PathBuf};
use std::time::Instant;

const SOURCES_DIR: &str = "/dev/shm/hapax-imagination/sources";
const DEFAULT_TTL_MS: u64 = 5000;
const CAMERA_SNAPSHOT_IMPLICIT_TTL_MS: u64 = 30_000;
const LEGACY_CAIRO_IMPLICIT_TTL_MS: u64 = 10_000;
const RECRUITED_CONTENT_IMPLICIT_TTL_MS: u64 = 30_000;
const IMAGINATION_IMPLICIT_TTL_MS: u64 = 60_000;
const MAX_SOURCES: usize = 64;
const CONTENT_SOURCE_MIP_WGSL: &str = r#"
@group(0) @binding(0)
var src_texture: texture_2d<f32>;
@group(0) @binding(1)
var src_sampler: sampler;

struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@vertex
fn vs_main(@builtin(vertex_index) vi: u32) -> VertexOutput {
    var positions = array<vec2<f32>, 3>(
        vec2<f32>(-1.0, -1.0),
        vec2<f32>( 3.0, -1.0),
        vec2<f32>(-1.0,  3.0),
    );
    let p = positions[vi];

    var out: VertexOutput;
    out.position = vec4<f32>(p, 0.0, 1.0);
    out.uv = p * 0.5 + vec2<f32>(0.5, 0.5);
    return out;
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    return textureSample(src_texture, src_sampler, in.uv);
}
"#;

#[derive(Debug, Clone, Deserialize)]
pub struct SourceManifest {
    pub source_id: String,
    pub content_type: String,
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
    #[serde(default)]
    pub pane_binding: Option<AoaPaneBindingMetadata>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AoaPaneClipPolicy {
    BarycentricInsideRequired,
}

impl Default for AoaPaneClipPolicy {
    fn default() -> Self {
        Self::BarycentricInsideRequired
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AoaPaneEffectScope {
    PaneEntityOnly,
}

impl Default for AoaPaneEffectScope {
    fn default() -> Self {
        Self::PaneEntityOnly
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AoaPanePrivacyPosture {
    Unspecified,
    PublicSafe,
    PublicReviewRequired,
    PrivateOnly,
    Blocked,
}

impl Default for AoaPanePrivacyPosture {
    fn default() -> Self {
        Self::Unspecified
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AoaPaneSourcePosture {
    Synthetic,
    SystemWard,
    OperatorCamera,
    ExternalMedia,
    Unknown,
}

impl Default for AoaPaneSourcePosture {
    fn default() -> Self {
        Self::Unknown
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AoaPaneCompositionPosture {
    PaneBoundDeidentified,
    AmbientObjectView,
    StableOperatorPortrait,
    HostFraming,
    Unknown,
}

impl Default for AoaPaneCompositionPosture {
    fn default() -> Self {
        Self::Unknown
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AoaPaneStreamPosture {
    Private,
    Public,
}

impl AoaPaneStreamPosture {
    pub fn current() -> Self {
        Self::from_stream_mode_token(current_stream_mode_token().as_deref())
    }

    pub fn from_stream_mode_token(token: Option<&str>) -> Self {
        match token {
            Some("off" | "private") => Self::Private,
            Some("public" | "public_research") => Self::Public,
            _ => Self::Public,
        }
    }

    pub fn is_public(self) -> bool {
        self == Self::Public
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AoaPaneBindingMetadata {
    pub pane_id: String,
    #[serde(default = "default_aoa_pane_route")]
    pub route: String,
    #[serde(default = "default_aoa_pane_binding_mode")]
    pub mode: AoaPaneBindingMode,
    #[serde(default)]
    pub clip_policy: AoaPaneClipPolicy,
    #[serde(default)]
    pub effect_scope: AoaPaneEffectScope,
    #[serde(default)]
    pub privacy_posture: AoaPanePrivacyPosture,
    #[serde(default)]
    pub source_posture: AoaPaneSourcePosture,
    #[serde(default)]
    pub composition_posture: AoaPaneCompositionPosture,
    #[serde(default)]
    pub privacy_gate_refs: Vec<String>,
    #[serde(default)]
    pub face_obscure_upstream_ref: Option<String>,
    #[serde(default)]
    pub anti_recognition_ref: Option<String>,
    #[serde(default)]
    pub anti_recognition_passed: Option<bool>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AoaPaneBindingRejectionReason {
    InvalidRoute(String),
    UnknownPaneId(String),
    ModeNotAllowed {
        pane_id: String,
        mode: AoaPaneBindingMode,
    },
    PaneLodNotPermitted {
        pane_id: String,
        mode: AoaPaneBindingMode,
        required: AoaPaneLodClass,
        actual: AoaPaneLodClass,
    },
    PaneSubtreeConflict {
        pane_id: String,
        selected_pane_id: String,
    },
    MissingPrivacyPosture,
    PrivacyBlocked,
    PrivacyGateRefsMissing,
    PrivateOnlyInPublicMode,
    UnknownSourcePosture,
    OperatorCameraFaceObscureMissing,
    OperatorCameraAntiRecognitionMissing,
    OperatorCameraAntiRecognitionFailed,
    AntiParasocialComposition(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AoaValidatedPaneBinding {
    pub pane_id: String,
    pub pane_ordinal: u32,
    pub mode: AoaPaneBindingMode,
    pub privacy_posture: AoaPanePrivacyPosture,
    pub source_posture: AoaPaneSourcePosture,
    pub composition_posture: AoaPaneCompositionPosture,
    pub pane_privacy_class: AoaPanePrivacyClass,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ActiveContentSourceInfo {
    pub source_id: String,
    pub current_opacity: f32,
    pub z_order: i32,
    pub width: u32,
    pub height: u32,
    pub content_type: String,
    pub tags: Vec<String>,
    pub pane_binding: Option<AoaPaneBindingMetadata>,
}

impl ActiveContentSourceInfo {
    pub fn new(
        source_id: impl Into<String>,
        current_opacity: f32,
        z_order: i32,
        width: u32,
        height: u32,
    ) -> Self {
        Self {
            source_id: source_id.into(),
            current_opacity,
            z_order,
            width,
            height,
            content_type: "rgba".to_string(),
            tags: Vec::new(),
            pane_binding: None,
        }
    }

    fn from_source(id: &str, source: &ContentSource) -> Self {
        Self {
            source_id: id.to_string(),
            current_opacity: source.current_opacity,
            z_order: source.manifest.z_order,
            width: source.manifest.width,
            height: source.manifest.height,
            content_type: source.manifest.content_type.clone(),
            tags: source.manifest.tags.clone(),
            pane_binding: source.manifest.pane_binding.clone(),
        }
    }

    pub fn with_pane_binding(mut self, binding: AoaPaneBindingMetadata) -> Self {
        self.pane_binding = Some(binding);
        self
    }

    pub fn scene_tuple(&self) -> (&str, f32, i32, u32, u32) {
        (
            self.source_id.as_str(),
            self.current_opacity,
            self.z_order,
            self.width,
            self.height,
        )
    }

    pub fn validated_pane_binding(
        &self,
    ) -> Result<Option<AoaValidatedPaneBinding>, AoaPaneBindingRejectionReason> {
        self.validated_pane_binding_for_stream_posture(AoaPaneStreamPosture::current())
    }

    pub fn validated_pane_binding_for_stream_posture(
        &self,
        stream_posture: AoaPaneStreamPosture,
    ) -> Result<Option<AoaValidatedPaneBinding>, AoaPaneBindingRejectionReason> {
        self.pane_binding
            .as_ref()
            .map(|binding| validate_aoa_pane_binding_for_stream_posture(binding, stream_posture))
            .transpose()
    }
}

fn default_width() -> u32 {
    1920
}
fn default_height() -> u32 {
    1080
}
fn default_font_weight() -> u32 {
    400
}
fn default_layer() -> u32 {
    1
}
fn default_blend_mode() -> String {
    "screen".to_string()
}
fn default_opacity() -> f32 {
    1.0
}
fn default_ttl() -> u64 {
    DEFAULT_TTL_MS
}

fn default_aoa_pane_route() -> String {
    "aoa_pane".to_string()
}

fn default_aoa_pane_binding_mode() -> AoaPaneBindingMode {
    AoaPaneBindingMode::TriTextureMasked
}

fn normalized_pane_route(route: &str) -> String {
    route.trim().to_ascii_lowercase().replace(['-', ' '], "_")
}

fn current_stream_mode_token() -> Option<String> {
    if let Ok(raw) = env::var("HAPAX_STREAM_MODE") {
        return Some(raw.trim().to_ascii_lowercase());
    }
    if let Ok(path) = env::var("HAPAX_STREAM_MODE_FILE") {
        return std::fs::read_to_string(path)
            .ok()
            .map(|raw| raw.trim().to_ascii_lowercase());
    }
    let home = env::var("HOME").ok()?;
    std::fs::read_to_string(Path::new(&home).join(".cache/hapax/stream-mode"))
        .ok()
        .map(|raw| raw.trim().to_ascii_lowercase())
}

pub fn validate_aoa_pane_binding(
    binding: &AoaPaneBindingMetadata,
) -> Result<AoaValidatedPaneBinding, AoaPaneBindingRejectionReason> {
    let route = normalized_pane_route(&binding.route);
    if route != "aoa_pane" {
        return Err(AoaPaneBindingRejectionReason::InvalidRoute(
            binding.route.clone(),
        ));
    }

    if binding.privacy_posture == AoaPanePrivacyPosture::Unspecified {
        return Err(AoaPaneBindingRejectionReason::MissingPrivacyPosture);
    }
    if binding.privacy_posture == AoaPanePrivacyPosture::Blocked {
        return Err(AoaPaneBindingRejectionReason::PrivacyBlocked);
    }
    if binding.privacy_posture == AoaPanePrivacyPosture::PublicReviewRequired
        && binding.privacy_gate_refs.is_empty()
    {
        return Err(AoaPaneBindingRejectionReason::PrivacyGateRefsMissing);
    }
    if binding.source_posture == AoaPaneSourcePosture::Unknown {
        return Err(AoaPaneBindingRejectionReason::UnknownSourcePosture);
    }
    if matches!(
        binding.composition_posture,
        AoaPaneCompositionPosture::StableOperatorPortrait | AoaPaneCompositionPosture::HostFraming
    ) {
        return Err(AoaPaneBindingRejectionReason::AntiParasocialComposition(
            format!("{:?}", binding.composition_posture),
        ));
    }
    if binding.source_posture == AoaPaneSourcePosture::OperatorCamera {
        if binding
            .face_obscure_upstream_ref
            .as_deref()
            .is_none_or(str::is_empty)
        {
            return Err(AoaPaneBindingRejectionReason::OperatorCameraFaceObscureMissing);
        }
        if binding
            .anti_recognition_ref
            .as_deref()
            .is_none_or(str::is_empty)
        {
            return Err(AoaPaneBindingRejectionReason::OperatorCameraAntiRecognitionMissing);
        }
        if binding.anti_recognition_passed != Some(true) {
            return Err(AoaPaneBindingRejectionReason::OperatorCameraAntiRecognitionFailed);
        }
    }

    let manifest = aoa_active_pane_manifest();
    let pane = manifest
        .panes
        .iter()
        .find(|pane| pane.pane_id == binding.pane_id)
        .ok_or_else(|| AoaPaneBindingRejectionReason::UnknownPaneId(binding.pane_id.clone()))?;

    if !pane
        .content_eligibility
        .allowed_modes
        .contains(&binding.mode)
    {
        return Err(AoaPaneBindingRejectionReason::ModeNotAllowed {
            pane_id: binding.pane_id.clone(),
            mode: binding.mode,
        });
    }

    Ok(AoaValidatedPaneBinding {
        pane_id: pane.pane_id.clone(),
        pane_ordinal: pane.pane_ordinal,
        mode: binding.mode,
        privacy_posture: binding.privacy_posture.clone(),
        source_posture: binding.source_posture.clone(),
        composition_posture: binding.composition_posture.clone(),
        pane_privacy_class: pane.content_eligibility.privacy_class,
    })
}

pub fn validate_aoa_pane_binding_for_stream_posture(
    binding: &AoaPaneBindingMetadata,
    stream_posture: AoaPaneStreamPosture,
) -> Result<AoaValidatedPaneBinding, AoaPaneBindingRejectionReason> {
    let validated = validate_aoa_pane_binding(binding)?;
    if stream_posture.is_public() && validated.privacy_posture == AoaPanePrivacyPosture::PrivateOnly
    {
        return Err(AoaPaneBindingRejectionReason::PrivateOnlyInPublicMode);
    }
    Ok(validated)
}

fn expected_rgba_size(width: u32, height: u32) -> Option<usize> {
    width
        .checked_mul(height)?
        .checked_mul(4)
        .map(|bytes| bytes as usize)
}

fn source_mip_level_count(width: u32, height: u32) -> u32 {
    let max_dim = width.max(height).max(1);
    u32::BITS - max_dim.leading_zeros()
}

struct MipGenerator {
    pipeline: wgpu::RenderPipeline,
    bind_group_layout: wgpu::BindGroupLayout,
    sampler: wgpu::Sampler,
}

impl MipGenerator {
    fn new(device: &wgpu::Device) -> Self {
        let bind_group_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("content source mip bgl"),
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
        let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("content source mip sampler"),
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            mipmap_filter: wgpu::FilterMode::Linear,
            ..Default::default()
        });
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("content_source_mip"),
            source: wgpu::ShaderSource::Wgsl(CONTENT_SOURCE_MIP_WGSL.into()),
        });
        let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("content source mip pipeline layout"),
            bind_group_layouts: &[&bind_group_layout],
            push_constant_ranges: &[],
        });
        let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("content source mip pipeline"),
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
                    format: wgpu::TextureFormat::Rgba8Unorm,
                    blend: None,
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

        Self {
            pipeline,
            bind_group_layout,
            sampler,
        }
    }

    fn encode_mips(
        &self,
        device: &wgpu::Device,
        encoder: &mut wgpu::CommandEncoder,
        texture: &wgpu::Texture,
        width: u32,
        height: u32,
    ) -> bool {
        let mip_count = source_mip_level_count(width, height);
        if mip_count <= 1 {
            return false;
        }

        for level in 1..mip_count {
            let src_view = texture.create_view(&wgpu::TextureViewDescriptor {
                label: Some("content source mip src view"),
                base_mip_level: level - 1,
                mip_level_count: Some(1),
                ..Default::default()
            });
            let dst_view = texture.create_view(&wgpu::TextureViewDescriptor {
                label: Some("content source mip dst view"),
                base_mip_level: level,
                mip_level_count: Some(1),
                ..Default::default()
            });
            let bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some("content source mip bind group"),
                layout: &self.bind_group_layout,
                entries: &[
                    wgpu::BindGroupEntry {
                        binding: 0,
                        resource: wgpu::BindingResource::TextureView(&src_view),
                    },
                    wgpu::BindGroupEntry {
                        binding: 1,
                        resource: wgpu::BindingResource::Sampler(&self.sampler),
                    },
                ],
            });

            {
                let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                    label: Some("content source mip pass"),
                    color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                        view: &dst_view,
                        resolve_target: None,
                        ops: wgpu::Operations {
                            load: wgpu::LoadOp::Clear(wgpu::Color::TRANSPARENT),
                            store: wgpu::StoreOp::Store,
                        },
                    })],
                    ..Default::default()
                });
                pass.set_pipeline(&self.pipeline);
                pass.set_bind_group(0, &bind_group, &[]);
                pass.draw(0..3, 0..1);
            }
        }

        true
    }
}

fn rgba_frame_matches_manifest(pixels: &[u8], manifest: &SourceManifest) -> bool {
    expected_rgba_size(manifest.width, manifest.height)
        .is_some_and(|expected_size| pixels.len() == expected_size)
}

fn has_manifest_tag(manifest: &SourceManifest, tag: &str) -> bool {
    manifest.tags.iter().any(|candidate| candidate == tag)
}

fn effective_ttl_ms(manifest: &SourceManifest) -> u64 {
    let implicit_ttl = if has_manifest_tag(manifest, "camera-snapshot") {
        Some(CAMERA_SNAPSHOT_IMPLICIT_TTL_MS)
    } else if manifest.ttl_ms == 0
        && has_manifest_tag(manifest, "ward")
        && has_manifest_tag(manifest, "cairo")
    {
        Some(LEGACY_CAIRO_IMPLICIT_TTL_MS)
    } else if manifest.ttl_ms == 0
        && manifest.source_id.starts_with("content-")
        && has_manifest_tag(manifest, "recruited")
    {
        Some(RECRUITED_CONTENT_IMPLICIT_TTL_MS)
    } else if manifest.ttl_ms == 0
        && manifest.source_id.starts_with("imagination-")
        && has_manifest_tag(manifest, "imagination")
    {
        Some(IMAGINATION_IMPLICIT_TTL_MS)
    } else {
        None
    };

    match (manifest.ttl_ms, implicit_ttl) {
        (0, Some(ttl)) => ttl,
        (explicit, Some(ttl)) => explicit.min(ttl),
        (explicit, None) => explicit,
    }
}

fn modified_age_exceeds_ttl(modified: std::time::SystemTime, ttl_ms: u64) -> bool {
    if ttl_ms == 0 {
        return false;
    }
    modified.elapsed().unwrap_or_default().as_millis() > ttl_ms as u128
}

fn source_file_age_exceeds_ttl(
    manifest_path: &Path,
    frame_path: &Path,
    manifest: &SourceManifest,
) -> bool {
    let ttl_ms = effective_ttl_ms(manifest);
    if ttl_ms == 0 {
        return false;
    }

    [manifest_path, frame_path].into_iter().any(|path| {
        std::fs::metadata(path)
            .ok()
            .and_then(|metadata| metadata.modified().ok())
            .is_none_or(|modified| modified_age_exceeds_ttl(modified, ttl_ms))
    })
}

fn read_complete_rgba_frame(
    frame_path: &Path,
    source_id: &str,
    manifest: &SourceManifest,
) -> Option<Vec<u8>> {
    let expected_size = expected_rgba_size(manifest.width, manifest.height)?;

    let before_len = std::fs::metadata(frame_path).ok()?.len() as usize;
    if before_len != expected_size {
        log::debug!(
            "ContentSourceManager: skipping incomplete RGBA frame for '{}' before read - got {} bytes, expected {}",
            source_id,
            before_len,
            expected_size
        );
        return None;
    }

    let pixels = std::fs::read(frame_path).ok()?;
    if pixels.len() != expected_size {
        log::debug!(
            "ContentSourceManager: skipping incomplete RGBA frame for '{}' after read - got {} bytes, expected {}",
            source_id,
            pixels.len(),
            expected_size
        );
        return None;
    }

    let after_len = std::fs::metadata(frame_path).ok()?.len() as usize;
    if after_len != expected_size {
        log::debug!(
            "ContentSourceManager: skipping unstable RGBA frame for '{}' after read - got {} bytes, expected {}",
            source_id,
            after_len,
            expected_size
        );
        return None;
    }

    Some(pixels)
}

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
    mip_generator: MipGenerator,
}

impl ContentSourceManager {
    pub fn new(device: &wgpu::Device, queue: &wgpu::Queue) -> Self {
        let (placeholder_texture, placeholder_view) = Self::create_placeholder(device, queue);
        let mip_generator = MipGenerator::new(device);
        Self {
            sources: HashMap::new(),
            sources_dir: PathBuf::from(SOURCES_DIR),
            last_scan: Instant::now(),
            scan_interval_ms: 100,
            placeholder_view,
            _placeholder_texture: placeholder_texture,
            mip_generator,
        }
    }

    fn create_placeholder(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
    ) -> (wgpu::Texture, wgpu::TextureView) {
        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("content_source_placeholder"),
            size: wgpu::Extent3d {
                width: 1,
                height: 1,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8Unorm,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });
        queue.write_texture(
            wgpu::TexelCopyTextureInfo {
                texture: &texture,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            &[0u8, 0, 0, 0],
            wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(4),
                rows_per_image: Some(1),
            },
            wgpu::Extent3d {
                width: 1,
                height: 1,
                depth_or_array_layers: 1,
            },
        );
        let view = texture.create_view(&Default::default());
        (texture, view)
    }

    pub fn scan(&mut self, device: &wgpu::Device, queue: &wgpu::Queue) {
        if self.last_scan.elapsed().as_millis() < self.scan_interval_ms as u128 {
            return;
        }
        self.last_scan = Instant::now();

        let entries = match std::fs::read_dir(&self.sources_dir) {
            Ok(e) => e,
            Err(_) => return,
        };

        let mut seen = Vec::new();
        let mut mip_encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
            label: Some("content source mip batch encoder"),
        });
        let mut has_mip_work = false;
        for entry in entries.flatten() {
            let path = entry.path();
            if !path.is_dir() {
                continue;
            }
            let source_id = match path.file_name().and_then(|n| n.to_str()) {
                Some(n) => n.to_string(),
                None => continue,
            };
            if self.sources.len() >= MAX_SOURCES && !self.sources.contains_key(&source_id) {
                continue;
            }

            let manifest_path = path.join("manifest.json");
            let manifest = match Self::read_manifest(&manifest_path) {
                Some(m) => m,
                None => continue,
            };

            let frame_path = path.join("frame.rgba");
            if source_file_age_exceeds_ttl(&manifest_path, &frame_path, &manifest) {
                log::warn!(
                    "ContentSourceManager: expiring stale source '{}' by file age (effective ttl {}ms)",
                    source_id,
                    effective_ttl_ms(&manifest)
                );
                let _ = std::fs::remove_dir_all(&path);
                continue;
            }

            if manifest.content_type == "rgba" {
                has_mip_work |= self.update_rgba_source(
                    device,
                    queue,
                    &mut mip_encoder,
                    &source_id,
                    manifest,
                    &frame_path,
                );
            }

            seen.push(source_id);
        }
        if has_mip_work {
            queue.submit(std::iter::once(mip_encoder.finish()));
        }

        // Expire sources not seen or past TTL, clean up shm directories
        let now = Instant::now();
        let sources_dir = self.sources_dir.clone();
        self.sources.retain(|id, src| {
            let ttl_ms = effective_ttl_ms(&src.manifest);
            let keep = seen.contains(id)
                && (ttl_ms == 0
                    || now.duration_since(src.last_refresh).as_millis() <= ttl_ms as u128);
            if !keep {
                let dir = sources_dir.join(id);
                if dir.exists() {
                    let _ = std::fs::remove_dir_all(&dir);
                }
            }
            keep
        });

        // Also clean up orphaned directories not tracked by the manager
        // (e.g., from previous runs or sources that expired before being loaded)
        for id in &seen {
            if !self.sources.contains_key(id.as_str()) {
                let manifest_path = self.sources_dir.join(id).join("manifest.json");
                if let Some(manifest) = Self::read_manifest(&manifest_path) {
                    let ttl_ms = effective_ttl_ms(&manifest);
                    if ttl_ms > 0 {
                        // Check file age as proxy for staleness
                        if let Ok(metadata) = std::fs::metadata(&manifest_path) {
                            if let Ok(modified) = metadata.modified() {
                                if modified.elapsed().unwrap_or_default().as_millis()
                                    > ttl_ms as u128
                                {
                                    let dir = self.sources_dir.join(id);
                                    let _ = std::fs::remove_dir_all(&dir);
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    fn read_manifest(path: &Path) -> Option<SourceManifest> {
        let data = std::fs::read_to_string(path).ok()?;
        serde_json::from_str(&data).ok()
    }

    fn update_rgba_source(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        mip_encoder: &mut wgpu::CommandEncoder,
        source_id: &str,
        manifest: SourceManifest,
        frame_path: &Path,
    ) -> bool {
        let Some(pixels) = read_complete_rgba_frame(frame_path, source_id, &manifest) else {
            return false;
        };
        if !rgba_frame_matches_manifest(&pixels, &manifest) {
            return false;
        }

        let target_opacity = manifest.opacity;
        let mut generated_mips = false;

        if let Some(source) = self.sources.get_mut(source_id) {
            if source.manifest.width != manifest.width || source.manifest.height != manifest.height
            {
                let (tex, view) =
                    Self::create_source_texture(device, manifest.width, manifest.height, source_id);
                source.texture = tex;
                source.view = view;
            }
            if !Self::upload_rgba(
                queue,
                &source.texture,
                &pixels,
                manifest.width,
                manifest.height,
                source_id,
            ) {
                return false;
            }
            generated_mips |= self.mip_generator.encode_mips(
                device,
                mip_encoder,
                &source.texture,
                manifest.width,
                manifest.height,
            );
            source.manifest = manifest;
            source.target_opacity = target_opacity;
            source.last_refresh = Instant::now();
            source.frame_path = frame_path.to_path_buf();
        } else {
            let (texture, view) =
                Self::create_source_texture(device, manifest.width, manifest.height, source_id);
            if !Self::upload_rgba(
                queue,
                &texture,
                &pixels,
                manifest.width,
                manifest.height,
                source_id,
            ) {
                return false;
            }
            generated_mips |= self.mip_generator.encode_mips(
                device,
                mip_encoder,
                &texture,
                manifest.width,
                manifest.height,
            );
            self.sources.insert(
                source_id.to_string(),
                ContentSource {
                    manifest,
                    texture,
                    view,
                    current_opacity: 0.0,
                    target_opacity,
                    last_refresh: Instant::now(),
                    frame_path: frame_path.to_path_buf(),
                },
            );
        }
        generated_mips
    }

    fn create_source_texture(
        device: &wgpu::Device,
        width: u32,
        height: u32,
        label: &str,
    ) -> (wgpu::Texture, wgpu::TextureView) {
        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some(label),
            size: wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
            mip_level_count: source_mip_level_count(width, height),
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8Unorm,
            usage: wgpu::TextureUsages::TEXTURE_BINDING
                | wgpu::TextureUsages::COPY_DST
                | wgpu::TextureUsages::RENDER_ATTACHMENT,
            view_formats: &[],
        });
        let view = texture.create_view(&Default::default());
        (texture, view)
    }

    fn upload_rgba(
        queue: &wgpu::Queue,
        texture: &wgpu::Texture,
        pixels: &[u8],
        width: u32,
        height: u32,
        source_id: &str,
    ) -> bool {
        let Some(expected_size) = expected_rgba_size(width, height) else {
            log::warn!(
                "ContentSourceManager: skipping source '{}' with overflowing dimensions {}x{}",
                source_id,
                width,
                height
            );
            return false;
        };
        if pixels.len() != expected_size {
            log::warn!(
                "ContentSourceManager: skipping torn RGBA frame for '{}' - got {} bytes, expected {} for {}x{}",
                source_id,
                pixels.len(),
                expected_size,
                width,
                height
            );
            return false;
        }

        queue.write_texture(
            wgpu::TexelCopyTextureInfo {
                texture,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            pixels,
            wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(4 * width),
                rows_per_image: Some(height),
            },
            wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
        );
        true
    }

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

    fn source_is_visible(source: &ContentSource) -> bool {
        source.current_opacity > 0.001
    }

    fn source_is_generic_routable(source: &ContentSource) -> bool {
        Self::source_is_visible(source) && source.manifest.pane_binding.is_none()
    }

    pub fn active_sources(&self) -> Vec<(&str, &wgpu::TextureView, f32)> {
        let mut result: Vec<_> = self
            .sources
            .iter()
            .filter(|(_, s)| Self::source_is_generic_routable(s))
            .map(|(id, s)| (id.as_str(), &s.view, s.current_opacity))
            .collect();
        result.sort_by_key(|(id, _, _)| {
            self.sources
                .get(*id)
                .map(|s| s.manifest.z_order)
                .unwrap_or(0)
        });
        result
    }

    pub fn placeholder_view(&self) -> &wgpu::TextureView {
        &self.placeholder_view
    }

    /// Phase 1 3D scene: return source info tuples for dynamic scene building.
    /// Returns (source_id, current_opacity, z_order, width, height) for each
    /// active generic source. Pane-bound sources are intentionally excluded;
    /// `active_source_records` exposes them to the AoA path without letting
    /// them fall through as ordinary scene quads.
    pub fn active_source_info(&self) -> Vec<(&str, f32, i32, u32, u32)> {
        let mut result: Vec<_> = self
            .sources
            .iter()
            .filter(|(_, s)| Self::source_is_generic_routable(s))
            .map(|(id, s)| {
                (
                    id.as_str(),
                    s.current_opacity,
                    s.manifest.z_order,
                    s.manifest.width,
                    s.manifest.height,
                )
            })
            .collect();
        result.sort_by_key(|&(_, _, z, _, _)| z);
        result
    }

    /// Rich source records for scene routing. This includes pane-bound
    /// sources so the scene builder can consume them into AoA-internal records
    /// instead of re-projecting them as fourth-wall quads.
    pub fn active_source_records(&self) -> Vec<ActiveContentSourceInfo> {
        let mut result: Vec<_> = self
            .sources
            .iter()
            .filter(|(_, s)| Self::source_is_visible(s))
            .map(|(id, s)| ActiveContentSourceInfo::from_source(id, s))
            .collect();
        result.sort_by_key(|source| source.z_order);
        result
    }

    /// Phase 1 3D scene: look up a content source's texture view by source_id.
    /// Returns None if the source doesn't exist or has no texture.
    pub fn source_view(&self, source_id: &str) -> Option<&wgpu::TextureView> {
        self.sources.get(source_id).map(|s| &s.view)
    }

    /// Classify a source_id into a slot-family per the
    /// yt-content-reverie-sierpinski-separation contract (2026-04-21).
    /// `yt-slot-*` directories carry YouTube frames and route to the
    /// `youtube_pip` family (Sierpinski). Everything else (`camera-*`,
    /// `content-*`, future producers) defaults to `narrative` so it
    /// lands in Reverie's generative substrate. Conservative-by-default
    /// — new producers ship as narrative until explicitly tagged.
    pub fn classify_family(source_id: &str) -> &'static str {
        if source_id.starts_with("yt-slot-") {
            "youtube_pip"
        } else {
            "narrative"
        }
    }

    /// Get the texture view for a content slot filtered by family.
    /// Per Phase 1B of the slot-family separation: `content_slot_*`
    /// bindings on a pass tagged `slot_family="youtube_pip"` only see
    /// YT-slot sources; passes tagged `"narrative"` only see narrative
    /// sources. Returns the placeholder view when no source matches —
    /// callers never see cross-family bleed.
    pub fn slot_view_for_family(&self, index: usize, family: &str) -> &wgpu::TextureView {
        let mut sorted: Vec<&ContentSource> = self
            .sources
            .iter()
            .filter(|(id, s)| {
                Self::source_is_generic_routable(s) && Self::classify_family(id) == family
            })
            .map(|(_, s)| s)
            .collect();
        sorted.sort_by_key(|s| s.manifest.z_order);
        if let Some(source) = sorted.get(index) {
            &source.view
        } else {
            &self.placeholder_view
        }
    }

    /// Per-slot opacities filtered by family — pairs with
    /// `slot_view_for_family` so a pass's slot uniforms reflect the
    /// same source set as its bound textures.
    pub fn slot_opacities_for_family(&self, family: &str) -> [f32; 4] {
        let mut sorted: Vec<&ContentSource> = self
            .sources
            .iter()
            .filter(|(id, s)| {
                Self::source_is_generic_routable(s) && Self::classify_family(id) == family
            })
            .map(|(_, s)| s)
            .collect();
        sorted.sort_by_key(|s| s.manifest.z_order);
        let mut opacities = [0.0f32; 4];
        for (i, source) in sorted.iter().take(4).enumerate() {
            opacities[i] = source.current_opacity;
        }
        opacities
    }

    pub fn has_active_sources(&self) -> bool {
        self.sources.values().any(|s| s.current_opacity > 0.001)
    }

    pub fn source_count(&self) -> usize {
        self.sources.len()
    }

    /// Get texture view for a content slot (maps active sources to slot indices by z_order).
    pub fn slot_view(&self, index: usize) -> &wgpu::TextureView {
        let mut sorted: Vec<&ContentSource> = self
            .sources
            .values()
            .filter(|s| Self::source_is_generic_routable(s))
            .collect();
        sorted.sort_by_key(|s| s.manifest.z_order);
        if let Some(source) = sorted.get(index) {
            &source.view
        } else {
            &self.placeholder_view
        }
    }

    /// Get opacities for up to 4 content slots.
    pub fn slot_opacities(&self) -> [f32; 4] {
        let mut sorted: Vec<&ContentSource> = self
            .sources
            .values()
            .filter(|s| Self::source_is_generic_routable(s))
            .collect();
        sorted.sort_by_key(|s| s.manifest.z_order);
        let mut opacities = [0.0f32; 4];
        for (i, source) in sorted.iter().take(4).enumerate() {
            opacities[i] = source.current_opacity;
        }
        opacities
    }
}

#[cfg(test)]
mod family_classification_tests {
    use super::validate_aoa_pane_binding_for_stream_posture;
    use super::{
        effective_ttl_ms, expected_rgba_size, modified_age_exceeds_ttl, read_complete_rgba_frame,
        rgba_frame_matches_manifest, source_file_age_exceeds_ttl, source_mip_level_count,
        validate_aoa_pane_binding, AoaPaneBindingMetadata, AoaPaneBindingRejectionReason,
        AoaPaneCompositionPosture, AoaPanePrivacyPosture, AoaPaneSourcePosture,
        AoaPaneStreamPosture, ContentSourceManager, SourceManifest,
        CAMERA_SNAPSHOT_IMPLICIT_TTL_MS, CONTENT_SOURCE_MIP_WGSL,
    };
    use crate::aoa_panes::AoaPaneBindingMode;
    use std::time::{Duration, SystemTime};

    fn manifest(width: u32, height: u32) -> SourceManifest {
        SourceManifest {
            source_id: "test-source".to_string(),
            content_type: "rgba".to_string(),
            width,
            height,
            text: String::new(),
            font_weight: 400,
            layer: 1,
            blend_mode: "screen".to_string(),
            opacity: 1.0,
            z_order: 0,
            ttl_ms: 0,
            tags: Vec::new(),
            pane_binding: None,
        }
    }

    fn valid_root_binding() -> AoaPaneBindingMetadata {
        AoaPaneBindingMetadata {
            pane_id: "aoa:pane:v1:r:abd".to_string(),
            route: "aoa_pane".to_string(),
            mode: AoaPaneBindingMode::TriTextureMasked,
            clip_policy: Default::default(),
            effect_scope: Default::default(),
            privacy_posture: AoaPanePrivacyPosture::PublicReviewRequired,
            source_posture: AoaPaneSourcePosture::SystemWard,
            composition_posture: AoaPaneCompositionPosture::PaneBoundDeidentified,
            privacy_gate_refs: vec!["fixture:public-review".to_string()],
            face_obscure_upstream_ref: None,
            anti_recognition_ref: None,
            anti_recognition_passed: None,
        }
    }

    #[test]
    fn expected_rgba_size_rejects_overflow() {
        assert_eq!(expected_rgba_size(640, 360), Some(921_600));
        assert_eq!(expected_rgba_size(u32::MAX, u32::MAX), None);
    }

    #[test]
    fn source_mip_level_count_tracks_largest_dimension() {
        assert_eq!(source_mip_level_count(0, 0), 1);
        assert_eq!(source_mip_level_count(1, 1), 1);
        assert_eq!(source_mip_level_count(2, 1), 2);
        assert_eq!(source_mip_level_count(4, 4), 3);
        assert_eq!(source_mip_level_count(1920, 1080), 11);
    }

    #[test]
    fn content_source_mip_shader_parses() {
        naga::front::wgsl::parse_str(CONTENT_SOURCE_MIP_WGSL)
            .expect("content source mipmap WGSL must parse before live compositor deployment");
    }

    #[test]
    fn rgba_frame_must_match_manifest_after_read() {
        let manifest = manifest(4, 3);
        assert!(rgba_frame_matches_manifest(&vec![0; 48], &manifest));
        assert!(!rgba_frame_matches_manifest(&vec![0; 47], &manifest));
        assert!(!rgba_frame_matches_manifest(&vec![0; 49], &manifest));
    }

    #[test]
    fn complete_rgba_frame_read_rejects_torn_files() {
        let dir = tempfile::tempdir().unwrap();
        let frame_path = dir.path().join("frame.rgba");
        let manifest = manifest(4, 3);

        std::fs::write(&frame_path, vec![0u8; 47]).unwrap();
        assert!(read_complete_rgba_frame(&frame_path, "test-source", &manifest).is_none());

        std::fs::write(&frame_path, vec![0u8; 48]).unwrap();
        assert_eq!(
            read_complete_rgba_frame(&frame_path, "test-source", &manifest)
                .unwrap()
                .len(),
            48
        );
    }

    #[test]
    fn missing_pane_binding_deserializes_as_generic_source() {
        let parsed: SourceManifest = serde_json::from_str(
            r#"{
                "source_id": "ward-a",
                "content_type": "rgba",
                "width": 64,
                "height": 64
            }"#,
        )
        .unwrap();

        assert!(parsed.pane_binding.is_none());
    }

    #[test]
    fn valid_pane_binding_deserializes_and_validates_against_registry() {
        let parsed: SourceManifest = serde_json::from_str(
            r#"{
                "source_id": "ward-a",
                "content_type": "rgba",
                "width": 64,
                "height": 64,
                "pane_binding": {
                    "pane_id": "aoa:pane:v1:r:abd",
                    "route": "aoa_pane",
                    "mode": "tri_texture_masked",
                    "privacy_posture": "public_review_required",
                    "privacy_gate_refs": ["fixture:public-review"],
                    "source_posture": "system_ward"
                }
            }"#,
        )
        .unwrap();

        let binding = parsed.pane_binding.as_ref().unwrap();
        assert_eq!(binding.pane_id, "aoa:pane:v1:r:abd");
        assert_eq!(binding.source_posture, AoaPaneSourcePosture::SystemWard);

        let validated = validate_aoa_pane_binding(binding).unwrap();
        assert_eq!(validated.pane_id, "aoa:pane:v1:r:abd");
        assert_eq!(validated.pane_ordinal, 0);
        assert_eq!(validated.mode, AoaPaneBindingMode::TriTextureMasked);
    }

    #[test]
    fn missing_pane_privacy_posture_fails_closed() {
        let parsed: SourceManifest = serde_json::from_str(
            r#"{
                "source_id": "ward-a",
                "content_type": "rgba",
                "width": 64,
                "height": 64,
                "pane_binding": {
                    "pane_id": "aoa:pane:v1:r:abd",
                    "route": "aoa_pane",
                    "mode": "tri_texture_masked",
                    "source_posture": "system_ward"
                }
            }"#,
        )
        .unwrap();

        let binding = parsed.pane_binding.as_ref().unwrap();
        assert_eq!(binding.privacy_posture, AoaPanePrivacyPosture::Unspecified);
        assert_eq!(
            validate_aoa_pane_binding(binding),
            Err(AoaPaneBindingRejectionReason::MissingPrivacyPosture)
        );
    }

    #[test]
    fn invalid_pane_routes_fail_closed_before_quad_routing() {
        for route in [
            "fullscreen",
            "screen_rect",
            "canvas rect",
            "output_plane",
            "viewport_fixed",
            "post_projection_screen_coordinates",
            "overlay_zones_full",
        ] {
            let mut binding = valid_root_binding();
            binding.route = route.to_string();
            assert_eq!(
                validate_aoa_pane_binding(&binding),
                Err(AoaPaneBindingRejectionReason::InvalidRoute(
                    route.to_string()
                ))
            );
        }
    }

    #[test]
    fn unknown_pane_id_fails_closed() {
        let mut binding = valid_root_binding();
        binding.pane_id = "aoa:pane:v1:not-real:abd".to_string();

        assert_eq!(
            validate_aoa_pane_binding(&binding),
            Err(AoaPaneBindingRejectionReason::UnknownPaneId(
                "aoa:pane:v1:not-real:abd".to_string()
            ))
        );
    }

    #[test]
    fn pane_binding_carries_privacy_and_source_posture() {
        let mut binding = valid_root_binding();
        binding.privacy_posture = AoaPanePrivacyPosture::PrivateOnly;
        binding.source_posture = AoaPaneSourcePosture::OperatorCamera;
        binding.face_obscure_upstream_ref = Some("face-obscure:fixture".to_string());
        binding.anti_recognition_ref = Some("anti-recognition:fixture".to_string());
        binding.anti_recognition_passed = Some(true);

        let validated = validate_aoa_pane_binding(&binding).unwrap();
        assert_eq!(
            validated.privacy_posture,
            AoaPanePrivacyPosture::PrivateOnly
        );
        assert_eq!(
            validated.source_posture,
            AoaPaneSourcePosture::OperatorCamera
        );
    }

    #[test]
    fn public_review_pane_payloads_require_gate_refs() {
        let mut binding = valid_root_binding();
        binding.privacy_gate_refs.clear();

        assert_eq!(
            validate_aoa_pane_binding(&binding),
            Err(AoaPaneBindingRejectionReason::PrivacyGateRefsMissing)
        );
    }

    #[test]
    fn stream_posture_maps_public_research_and_unknown_to_public() {
        assert_eq!(
            AoaPaneStreamPosture::from_stream_mode_token(Some("public_research")),
            AoaPaneStreamPosture::Public
        );
        assert_eq!(
            AoaPaneStreamPosture::from_stream_mode_token(Some("unexpected")),
            AoaPaneStreamPosture::Public
        );
        assert_eq!(
            AoaPaneStreamPosture::from_stream_mode_token(None),
            AoaPaneStreamPosture::Public
        );
        assert_eq!(
            AoaPaneStreamPosture::from_stream_mode_token(Some("private")),
            AoaPaneStreamPosture::Private
        );
    }

    #[test]
    fn private_pane_payloads_fail_closed_in_public_stream_posture() {
        let mut binding = valid_root_binding();
        binding.privacy_posture = AoaPanePrivacyPosture::PrivateOnly;

        assert_eq!(
            validate_aoa_pane_binding_for_stream_posture(&binding, AoaPaneStreamPosture::Public),
            Err(AoaPaneBindingRejectionReason::PrivateOnlyInPublicMode)
        );
        assert!(validate_aoa_pane_binding_for_stream_posture(
            &binding,
            AoaPaneStreamPosture::Private
        )
        .is_ok());
    }

    #[test]
    fn operator_camera_pane_payloads_require_upstream_privacy_evidence() {
        let mut binding = valid_root_binding();
        binding.source_posture = AoaPaneSourcePosture::OperatorCamera;

        assert_eq!(
            validate_aoa_pane_binding(&binding),
            Err(AoaPaneBindingRejectionReason::OperatorCameraFaceObscureMissing)
        );
        binding.face_obscure_upstream_ref = Some("face-obscure:fixture".to_string());
        assert_eq!(
            validate_aoa_pane_binding(&binding),
            Err(AoaPaneBindingRejectionReason::OperatorCameraAntiRecognitionMissing)
        );
        binding.anti_recognition_ref = Some("anti-recognition:fixture".to_string());
        binding.anti_recognition_passed = Some(false);
        assert_eq!(
            validate_aoa_pane_binding(&binding),
            Err(AoaPaneBindingRejectionReason::OperatorCameraAntiRecognitionFailed)
        );
        binding.anti_recognition_passed = Some(true);
        assert!(validate_aoa_pane_binding(&binding).is_ok());
    }

    #[test]
    fn stable_operator_portrait_pane_payloads_are_rejected() {
        let mut binding = valid_root_binding();
        binding.composition_posture = AoaPaneCompositionPosture::StableOperatorPortrait;

        assert_eq!(
            validate_aoa_pane_binding(&binding),
            Err(AoaPaneBindingRejectionReason::AntiParasocialComposition(
                "StableOperatorPortrait".to_string()
            ))
        );
    }

    #[test]
    fn pane_bound_stale_source_files_fail_closed_by_existing_ttl_gate() {
        let dir = tempfile::tempdir().unwrap();
        let manifest_path = dir.path().join("manifest.json");
        let frame_path = dir.path().join("frame.rgba");
        let mut manifest = manifest(2, 2);
        manifest.ttl_ms = 1;
        manifest.pane_binding = Some(valid_root_binding());

        std::fs::write(&manifest_path, b"{}").unwrap();
        std::fs::write(&frame_path, vec![0u8; 16]).unwrap();
        std::thread::sleep(Duration::from_millis(5));

        assert!(
            source_file_age_exceeds_ttl(&manifest_path, &frame_path, &manifest),
            "pane-bound sources should still be expired before any binding route can render"
        );
    }

    /// yt-content-reverie-sierpinski-separation 2026-04-21:
    /// `yt-slot-*` directories MUST classify as `youtube_pip` so the
    /// Rust runtime routes YT frames into Sierpinski only.
    #[test]
    fn yt_slot_zero_classifies_as_youtube_pip() {
        assert_eq!(
            ContentSourceManager::classify_family("yt-slot-0"),
            "youtube_pip"
        );
    }

    #[test]
    fn yt_slot_double_digit_classifies_as_youtube_pip() {
        assert_eq!(
            ContentSourceManager::classify_family("yt-slot-15"),
            "youtube_pip"
        );
    }

    /// `content-*` directories (narrative_text, episodic_recall,
    /// knowledge_recall) MUST land in narrative so Reverie keeps its
    /// substrate purpose. Pre-fix they cross-bled with YT.
    #[test]
    fn content_narrative_text_classifies_as_narrative() {
        assert_eq!(
            ContentSourceManager::classify_family("content-narrative_text"),
            "narrative"
        );
    }

    #[test]
    fn content_episodic_recall_classifies_as_narrative() {
        assert_eq!(
            ContentSourceManager::classify_family("content-episodic_recall"),
            "narrative"
        );
    }

    /// `camera-*` and any other producer that pre-dates the family
    /// system defaults to narrative — conservative-by-default keeps
    /// the existing cross-bleed contained until each producer is
    /// explicitly tagged.
    #[test]
    fn camera_brio_operator_classifies_as_narrative_default() {
        assert_eq!(
            ContentSourceManager::classify_family("camera-brio-operator"),
            "narrative"
        );
    }

    #[test]
    fn unknown_prefix_classifies_as_narrative_default() {
        assert_eq!(
            ContentSourceManager::classify_family("future-producer-xyz"),
            "narrative"
        );
    }

    /// A source whose name happens to contain "yt-slot-" mid-string
    /// must NOT be misclassified — the prefix match is anchored.
    #[test]
    fn yt_slot_substring_inside_other_name_does_not_misclassify() {
        assert_eq!(
            ContentSourceManager::classify_family("camera-yt-slot-spy"),
            "narrative"
        );
    }

    #[test]
    fn camera_snapshot_zero_ttl_gets_implicit_expiry() {
        let mut manifest = manifest(640, 360);
        manifest.source_id = "visual-pool-slot-0".to_string();
        manifest.ttl_ms = 0;
        manifest.tags = vec![
            "local-visual-pool".to_string(),
            "camera-snapshot".to_string(),
        ];

        assert_eq!(effective_ttl_ms(&manifest), CAMERA_SNAPSHOT_IMPLICIT_TTL_MS);
    }

    #[test]
    fn camera_snapshot_explicit_ttl_cannot_exceed_implicit_expiry() {
        let mut manifest = manifest(640, 360);
        manifest.ttl_ms = CAMERA_SNAPSHOT_IMPLICIT_TTL_MS * 10;
        manifest.tags = vec!["camera-snapshot".to_string()];

        assert_eq!(effective_ttl_ms(&manifest), CAMERA_SNAPSHOT_IMPLICIT_TTL_MS);
    }

    #[test]
    fn non_camera_snapshot_zero_ttl_remains_persistent() {
        let manifest = manifest(640, 360);

        assert_eq!(effective_ttl_ms(&manifest), 0);
    }

    #[test]
    fn legacy_cairo_zero_ttl_gets_implicit_expiry() {
        let mut manifest = manifest(640, 360);
        manifest.tags = vec!["ward".to_string(), "cairo".to_string()];

        assert_eq!(
            effective_ttl_ms(&manifest),
            super::LEGACY_CAIRO_IMPLICIT_TTL_MS
        );
    }

    #[test]
    fn recruited_content_zero_ttl_gets_implicit_expiry() {
        let mut manifest = manifest(640, 360);
        manifest.source_id = "content-episodic_recall".to_string();
        manifest.tags = vec![
            "content".to_string(),
            "recruited".to_string(),
            "recall".to_string(),
        ];

        assert_eq!(
            effective_ttl_ms(&manifest),
            super::RECRUITED_CONTENT_IMPLICIT_TTL_MS
        );
    }

    #[test]
    fn imagination_zero_ttl_gets_implicit_expiry() {
        let mut manifest = manifest(640, 360);
        manifest.source_id = "imagination-r2".to_string();
        manifest.tags = vec!["imagination".to_string()];

        assert_eq!(
            effective_ttl_ms(&manifest),
            super::IMAGINATION_IMPLICIT_TTL_MS
        );
    }

    #[test]
    fn ttl_age_check_rejects_old_camera_snapshot_files() {
        let old = SystemTime::now() - Duration::from_millis(CAMERA_SNAPSHOT_IMPLICIT_TTL_MS + 1);
        let fresh = SystemTime::now() - Duration::from_millis(CAMERA_SNAPSHOT_IMPLICIT_TTL_MS - 1);

        assert!(modified_age_exceeds_ttl(
            old,
            CAMERA_SNAPSHOT_IMPLICIT_TTL_MS
        ));
        assert!(!modified_age_exceeds_ttl(
            fresh,
            CAMERA_SNAPSHOT_IMPLICIT_TTL_MS
        ));
    }
}
