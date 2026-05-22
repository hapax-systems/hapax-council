//! 3D scene renderer for compositor Phase 1.
//!
//! Renders dynamically-built scene nodes (from `ContentSourceManager`
//! state) in 3D space using a perspective camera. Each content source
//! becomes a textured quad at its z-plane depth.
//!
//! Gated behind `HAPAX_IMAGINATION_3D_PROOF=1`. When disabled, this
//! module is compiled but never instantiated — zero runtime cost.

use bytemuck::{Pod, Zeroable};
use glam::{Mat4, Vec3};

use crate::content_sources::{ActiveContentSourceInfo, ContentSourceManager};
use crate::scene::{
    build_proof_scene, build_scene_from_source_records_for_stream_posture_with_camera, BuiltScene,
    Camera3D, SceneNode,
};

const SCENE_QUAD_WGSL: &str = include_str!("shaders/scene_quad.wgsl");
// GRID_SHADER_VERSION: 1778811160
const SCENE_GRID_WGSL: &str = include_str!("shaders/scene_grid.wgsl");
const ENTITY_RESTORE_WGSL: &str = include_str!("shaders/entity_restore.wgsl");
const MAX_GRID_SHADOW_OCCLUDERS: usize = 16;
const DEFAULT_SCENE_SAMPLE_COUNT: u32 = 4;

/// GPU-side uniform data for a single quad draw call.
/// Must match the `SceneUniforms` struct in `scene_quad.wgsl`.
#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
struct SceneUniformData {
    model: [[f32; 4]; 4],
    view: [[f32; 4]; 4],
    projection: [[f32; 4]; 4],
    opacity: f32,
    shader_kind: f32,
    payload_pane_ordinal: f32,
    payload_mode: f32,
    local_effect_kind: f32,
    local_effect_mix: f32,
    local_effect_param_a: f32,
    local_effect_param_b: f32,
}

/// Single rectangle that can cast a soft shadow onto room planes.
/// Must match `GridOccluder` in `scene_grid.wgsl`.
#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
struct GridOccluderData {
    center: [f32; 4],
    axis_x: [f32; 4],
    axis_y: [f32; 4],
    normal: [f32; 4],
}

/// GPU-side uniform data for the grid.
/// Must match `GridUniforms` in `scene_grid.wgsl`.
#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
struct GridUniformData {
    view: [[f32; 4]; 4],
    projection: [[f32; 4]; 4],
    light_position: [f32; 4],
    light_color: [f32; 4],
    time: f32,
    occluder_count: u32,
    sphere_warmth: f32,
    _pad1: f32,
    occluders: [GridOccluderData; MAX_GRID_SHADOW_OCCLUDERS],
}

/// Maximum number of scene nodes we can render per frame.
const MAX_SCENE_NODES: usize = 128;
const ENTITY_LOCAL_EFFECT_STATE_FILE: &str = "/dev/shm/hapax-visual/entity-local-effect-state.json";
const ENTITY_LOCAL_SPATIAL_EFFECT_COUNT: u32 = 11;
/// Content quads are translucent compositing surfaces. They must be drawn
/// back-to-front without writing depth, otherwise alpha-transparent regions
/// become invisible occluding panes.
const CONTENT_QUAD_DEPTH_WRITE_ENABLED: bool = false;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum EntityLocalSpatialEffectKind {
    None,
    Mirror,
    Kaleidoscope,
    Warp,
    Fisheye,
    Transform,
    DisplacementMap,
    Droste,
    Tunnel,
    Tile,
    Drift,
    Breathing,
}

impl EntityLocalSpatialEffectKind {
    fn as_f32(self) -> f32 {
        match self {
            EntityLocalSpatialEffectKind::None => 0.0,
            EntityLocalSpatialEffectKind::Mirror => 1.0,
            EntityLocalSpatialEffectKind::Kaleidoscope => 2.0,
            EntityLocalSpatialEffectKind::Warp => 3.0,
            EntityLocalSpatialEffectKind::Fisheye => 4.0,
            EntityLocalSpatialEffectKind::Transform => 5.0,
            EntityLocalSpatialEffectKind::DisplacementMap => 6.0,
            EntityLocalSpatialEffectKind::Droste => 7.0,
            EntityLocalSpatialEffectKind::Tunnel => 8.0,
            EntityLocalSpatialEffectKind::Tile => 9.0,
            EntityLocalSpatialEffectKind::Drift => 10.0,
            EntityLocalSpatialEffectKind::Breathing => 11.0,
        }
    }

    fn name(self) -> &'static str {
        match self {
            EntityLocalSpatialEffectKind::None => "none",
            EntityLocalSpatialEffectKind::Mirror => "mirror",
            EntityLocalSpatialEffectKind::Kaleidoscope => "kaleidoscope",
            EntityLocalSpatialEffectKind::Warp => "warp",
            EntityLocalSpatialEffectKind::Fisheye => "fisheye",
            EntityLocalSpatialEffectKind::Transform => "transform",
            EntityLocalSpatialEffectKind::DisplacementMap => "displacement_map",
            EntityLocalSpatialEffectKind::Droste => "droste",
            EntityLocalSpatialEffectKind::Tunnel => "tunnel",
            EntityLocalSpatialEffectKind::Tile => "tile",
            EntityLocalSpatialEffectKind::Drift => "drift",
            EntityLocalSpatialEffectKind::Breathing => "breathing",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
struct EntityLocalSpatialEffect {
    kind: EntityLocalSpatialEffectKind,
    mix: f32,
    param_a: f32,
    param_b: f32,
}

impl EntityLocalSpatialEffect {
    fn none() -> Self {
        Self {
            kind: EntityLocalSpatialEffectKind::None,
            mix: 0.0,
            param_a: 0.0,
            param_b: 0.0,
        }
    }

    fn is_active(self) -> bool {
        self.kind != EntityLocalSpatialEffectKind::None && self.mix > 0.001
    }
}

fn smoothstep(edge0: f32, edge1: f32, x: f32) -> f32 {
    let t = ((x - edge0) / (edge1 - edge0)).clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

fn stable_label_phase(label: &str) -> f32 {
    let mut hash = 0u32;
    for byte in label.bytes() {
        hash = hash.wrapping_mul(16_777_619) ^ u32::from(byte);
    }
    (hash % 10_000) as f32 / 10_000.0
}

fn local_effect_envelope(t: f32) -> f32 {
    let fade_in = smoothstep(0.05, 0.26, t);
    let fade_out = 1.0 - smoothstep(0.74, 0.95, t);
    (fade_in * fade_out).clamp(0.0, 1.0)
}

fn entity_local_spatial_effect_for_node(
    node: &SceneNode,
    time: f32,
    sorted_ordinal: usize,
) -> EntityLocalSpatialEffect {
    if node.content_source_id.is_none()
        || node.shader != crate::scene::SceneNodeShader::Textured
        || node.opacity < 0.001
    {
        return EntityLocalSpatialEffect::none();
    }

    let label_phase = stable_label_phase(&node.label);
    let cycle = time * 0.080 + label_phase * 3.0 + sorted_ordinal as f32 * 0.173;
    let phase = cycle.fract();
    let envelope = local_effect_envelope(phase);
    if envelope <= 0.001 {
        return EntityLocalSpatialEffect::none();
    }

    let effect_index = cycle.floor() as u32 % ENTITY_LOCAL_SPATIAL_EFFECT_COUNT;
    let mix = (0.34 + 0.30 * envelope).clamp(0.0, 0.68);
    match effect_index {
        0 => EntityLocalSpatialEffect {
            kind: EntityLocalSpatialEffectKind::Mirror,
            mix,
            param_a: ((label_phase * 5.0).floor() as u32 % 2) as f32,
            param_b: 0.36 + 0.28 * phase,
        },
        1 => EntityLocalSpatialEffect {
            kind: EntityLocalSpatialEffectKind::Kaleidoscope,
            mix,
            param_a: 3.0 + ((label_phase * 7.0).floor() as u32 % 4) as f32,
            param_b: phase * std::f32::consts::TAU,
        },
        2 => EntityLocalSpatialEffect {
            kind: EntityLocalSpatialEffectKind::Warp,
            mix,
            param_a: 4.0 + ((sorted_ordinal as u32 % 5) as f32 * 1.5),
            param_b: phase * std::f32::consts::TAU,
        },
        3 => EntityLocalSpatialEffect {
            kind: EntityLocalSpatialEffectKind::Fisheye,
            mix,
            param_a: 0.20 + 0.34 * envelope,
            param_b: (phase + label_phase) * std::f32::consts::TAU,
        },
        4 => EntityLocalSpatialEffect {
            kind: EntityLocalSpatialEffectKind::Transform,
            mix,
            param_a: 0.04 + 0.08 * envelope,
            param_b: (phase * 1.7 + label_phase) * std::f32::consts::TAU,
        },
        5 => EntityLocalSpatialEffect {
            kind: EntityLocalSpatialEffectKind::DisplacementMap,
            mix,
            param_a: 0.05 + 0.13 * envelope,
            param_b: (phase * 2.0 + label_phase) * std::f32::consts::TAU,
        },
        6 => EntityLocalSpatialEffect {
            kind: EntityLocalSpatialEffectKind::Droste,
            mix,
            param_a: 0.16 + 0.26 * envelope,
            param_b: (phase + label_phase * 0.5) * std::f32::consts::TAU,
        },
        7 => EntityLocalSpatialEffect {
            kind: EntityLocalSpatialEffectKind::Tunnel,
            mix,
            param_a: 0.18 + 0.40 * envelope,
            param_b: (phase * 1.5 + label_phase) * std::f32::consts::TAU,
        },
        8 => EntityLocalSpatialEffect {
            kind: EntityLocalSpatialEffectKind::Tile,
            mix,
            param_a: 2.0 + ((sorted_ordinal as u32 + (label_phase * 5.0) as u32) % 4) as f32,
            param_b: phase,
        },
        9 => EntityLocalSpatialEffect {
            kind: EntityLocalSpatialEffectKind::Drift,
            mix,
            param_a: 0.018 + 0.042 * envelope,
            param_b: (phase * 1.3 + label_phase) * std::f32::consts::TAU,
        },
        _ => EntityLocalSpatialEffect {
            kind: EntityLocalSpatialEffectKind::Breathing,
            mix,
            param_a: 0.010 + 0.016 * envelope,
            param_b: phase * std::f32::consts::TAU,
        },
    }
}

fn sanitized_scene_sample_count(raw: Option<&str>) -> u32 {
    match raw.map(str::trim).map(str::to_ascii_lowercase).as_deref() {
        Some("0" | "1" | "off" | "false" | "disabled") => 1,
        Some("4" | "on" | "true" | "enabled") | None => DEFAULT_SCENE_SAMPLE_COUNT,
        Some(other) => {
            log::warn!(
                "Ignoring unsupported HAPAX_VISUAL_SCENE_MSAA_SAMPLES={other:?}; using {DEFAULT_SCENE_SAMPLE_COUNT}x scene MSAA"
            );
            DEFAULT_SCENE_SAMPLE_COUNT
        }
    }
}

fn configured_scene_sample_count() -> u32 {
    sanitized_scene_sample_count(
        std::env::var("HAPAX_VISUAL_SCENE_MSAA_SAMPLES")
            .ok()
            .as_deref(),
    )
}

fn build_live_scene_from_active(
    active: &[ActiveContentSourceInfo],
    time: f32,
    camera: &Camera3D,
    width: u32,
    height: u32,
) -> BuiltScene {
    if active.is_empty() {
        BuiltScene {
            nodes: Vec::new(),
            aoa_pane_sources: Vec::new(),
            rejected_pane_sources: Vec::new(),
        }
    } else {
        build_scene_from_source_records_for_stream_posture_with_camera(
            active,
            time,
            crate::content_sources::AoaPaneStreamPosture::current(),
            camera,
            width,
            height,
        )
    }
}

fn vec4(v: Vec3, w: f32) -> [f32; 4] {
    [v.x, v.y, v.z, w]
}

fn upload_heatmap(queue: &wgpu::Queue, buffer: &wgpu::Buffer) {
    const PANE_COUNT: usize = 340;
    let path = "/dev/shm/hapax-imagination/aoa-heatmap.bin";
    let raw = match std::fs::read(path) {
        Ok(data) if data.len() >= PANE_COUNT * 12 => data,
        _ => return,
    };
    let mut gpu_data = vec![0u8; PANE_COUNT * 16];
    for i in 0..PANE_COUNT {
        let src_off = i * 12;
        let dst_off = i * 16;
        gpu_data[dst_off..dst_off + 12].copy_from_slice(&raw[src_off..src_off + 12]);
    }
    queue.write_buffer(buffer, 0, &gpu_data);
}

fn read_sphere_warmth() -> f32 {
    static LAST: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(0);
    let frame = LAST.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    if frame % 30 != 0 {
        return f32::from_bits(LAST.load(std::sync::atomic::Ordering::Relaxed));
    }
    let warmth = std::fs::read_to_string("/dev/shm/hapax-compositor/color-resonance.json")
        .ok()
        .and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok())
        .and_then(|v| v.get("warmth")?.as_f64())
        .map(|w| w as f32)
        .unwrap_or(0.5);
    LAST.store(warmth.to_bits(), std::sync::atomic::Ordering::Relaxed);
    warmth
}

fn synthwave_light_color(time: f32) -> [f32; 4] {
    let palette = [
        Vec3::new(1.00, 0.08, 0.60),
        Vec3::new(0.52, 0.12, 1.00),
        Vec3::new(0.04, 0.62, 1.00),
        Vec3::new(0.08, 0.92, 0.78),
        Vec3::new(1.00, 0.34, 0.08),
    ];
    let scaled = (time * 0.032).rem_euclid(palette.len() as f32);
    let idx = scaled.floor() as usize;
    let next = (idx + 1) % palette.len();
    let t = scaled.fract();
    let smooth = t * t * (3.0 - 2.0 * t);
    let color = palette[idx].lerp(palette[next], smooth);
    [color.x, color.y, color.z, 1.0]
}

fn grid_shadow_occluders(
    scene: &[SceneNode],
) -> ([GridOccluderData; MAX_GRID_SHADOW_OCCLUDERS], u32) {
    let mut occluders = [GridOccluderData::zeroed(); MAX_GRID_SHADOW_OCCLUDERS];
    let mut candidates = scene
        .iter()
        .filter(|node| {
            node.opacity > 0.04
                && node.scale.x > 0.02
                && node.scale.y > 0.02
                && node.aoa_payload_pane_ordinal.is_none()
        })
        .collect::<Vec<_>>();

    candidates.sort_by(|a, b| {
        let b_area = b.scale.x * b.scale.y * b.opacity.max(0.01);
        let a_area = a.scale.x * a.scale.y * a.opacity.max(0.01);
        b_area
            .partial_cmp(&a_area)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    let mut count = 0usize;
    for node in candidates.into_iter().take(MAX_GRID_SHADOW_OCCLUDERS) {
        let (sin_y, cos_y) = node.rotation_y.sin_cos();
        let axis_x = Vec3::new(cos_y, 0.0, -sin_y);
        let axis_y = Vec3::Y;
        let normal = axis_x.cross(axis_y).normalize_or_zero();
        if normal.length_squared() < 0.5 {
            continue;
        }
        let half_width = (node.scale.x * 0.5).max(0.01);
        let half_height = (node.scale.y * 0.5).max(0.01);
        let strength = (node.opacity * 0.42).clamp(0.04, 0.44);
        occluders[count] = GridOccluderData {
            center: vec4(node.position, 1.0),
            axis_x: vec4(axis_x, half_width),
            axis_y: vec4(axis_y, half_height),
            normal: vec4(normal, strength),
        };
        count += 1;
    }

    (occluders, count as u32)
}

fn scene_node_view_z(view: Mat4, node: &SceneNode) -> f32 {
    (view * node.position.extend(1.0)).z
}

fn sorted_scene_indices_back_to_front(scene: &[SceneNode], view: Mat4) -> Vec<usize> {
    let mut sorted_indices: Vec<usize> = (0..scene.len()).collect();
    sorted_indices.sort_by(|a, b| {
        scene_node_view_z(view, &scene[*a])
            .partial_cmp(&scene_node_view_z(view, &scene[*b]))
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    sorted_indices
}

pub struct SceneRenderer {
    camera: Camera3D,
    render_pipeline: wgpu::RenderPipeline,
    uniform_buffer: wgpu::Buffer,
    uniform_align: u32,
    uniform_bind_group_layout: wgpu::BindGroupLayout,
    uniform_bind_group: wgpu::BindGroup,
    texture_bind_group_layout: wgpu::BindGroupLayout,
    sampler: wgpu::Sampler,
    sample_count: u32,
    output_texture: wgpu::Texture,
    output_view: wgpu::TextureView,
    _msaa_color_texture: Option<wgpu::Texture>,
    msaa_color_view: Option<wgpu::TextureView>,
    depth_texture: wgpu::Texture,
    depth_view: wgpu::TextureView,
    /// Placeholder 1x1 white texture for nodes without content sources.
    placeholder_texture: wgpu::Texture,
    placeholder_view: wgpu::TextureView,
    width: u32,
    height: u32,
    frame_count: u64,
    // Grid rendering
    grid_pipeline: wgpu::RenderPipeline,
    grid_uniform_buffer: wgpu::Buffer,
    grid_uniform_bind_group: wgpu::BindGroup,
    // Reverie sphere texture
    grid_texture_bgl: wgpu::BindGroupLayout,
    reverie_bind_group: wgpu::BindGroup,
    reverie_sampler: wgpu::Sampler,
    // AoA heatmap
    heatmap_buffer: wgpu::Buffer,
    heatmap_bind_group: wgpu::BindGroup,
    // Post-Reverie entity restoration
    entity_restore_pipeline: wgpu::RenderPipeline,
    entity_restore_bgl: wgpu::BindGroupLayout,
    entity_restore_sampler: wgpu::Sampler,
}

impl SceneRenderer {
    pub fn new(device: &wgpu::Device, queue: &wgpu::Queue, width: u32, height: u32) -> Self {
        let camera = Camera3D::new(width, height);
        let sample_count = configured_scene_sample_count();

        // Uniform buffer (per-quad, updated each draw call)
        let min_align = device.limits().min_uniform_buffer_offset_alignment as usize;
        let uniform_stride =
            ((std::mem::size_of::<SceneUniformData>() + min_align - 1) / min_align) * min_align;
        let total_buffer_size = uniform_stride * MAX_SCENE_NODES;
        let uniform_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("scene uniform buffer"),
            size: total_buffer_size as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let uniform_align = uniform_stride as u32;

        let uniform_bind_group_layout =
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: Some("scene uniform bgl"),
                entries: &[wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::VERTEX | wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: true,
                        min_binding_size: wgpu::BufferSize::new(
                            std::mem::size_of::<SceneUniformData>() as u64,
                        ),
                    },
                    count: None,
                }],
            });

        let uniform_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("scene uniform bg"),
            layout: &uniform_bind_group_layout,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: wgpu::BindingResource::Buffer(wgpu::BufferBinding {
                    buffer: &uniform_buffer,
                    offset: 0,
                    size: wgpu::BufferSize::new(std::mem::size_of::<SceneUniformData>() as u64),
                }),
            }],
        });

        // Texture bind group layout (per-quad texture + sampler)
        let texture_bind_group_layout =
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: Some("scene texture bgl"),
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
            label: Some("scene sampler"),
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            mipmap_filter: wgpu::FilterMode::Linear,
            ..Default::default()
        });

        // Shader module
        let shader_module = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("scene_quad"),
            source: wgpu::ShaderSource::Wgsl(SCENE_QUAD_WGSL.into()),
        });

        // AoA heatmap storage buffer (340 panes × vec4)
        const HEATMAP_PANE_COUNT: usize = 340;
        let heatmap_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("aoa_heatmap"),
            size: (HEATMAP_PANE_COUNT * 16) as u64,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let heatmap_bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("aoa_heatmap_bgl"),
            entries: &[wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Storage { read_only: true },
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            }],
        });
        let heatmap_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("aoa_heatmap_bg"),
            layout: &heatmap_bgl,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: heatmap_buffer.as_entire_binding(),
            }],
        });

        // Pipeline layout
        let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("scene pipeline layout"),
            bind_group_layouts: &[&uniform_bind_group_layout, &texture_bind_group_layout, &heatmap_bgl],
            push_constant_ranges: &[],
        });

        // Output texture (intermediate — feeds into 2D chain)
        let output_format = wgpu::TextureFormat::Rgba8Unorm;
        let output_texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("scene output"),
            size: wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: output_format,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT
                | wgpu::TextureUsages::TEXTURE_BINDING
                | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let output_view = output_texture.create_view(&Default::default());
        let (msaa_color_texture, msaa_color_view) = if sample_count > 1 {
            let texture = device.create_texture(&wgpu::TextureDescriptor {
                label: Some("scene msaa color"),
                size: wgpu::Extent3d {
                    width,
                    height,
                    depth_or_array_layers: 1,
                },
                mip_level_count: 1,
                sample_count,
                dimension: wgpu::TextureDimension::D2,
                format: output_format,
                usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
                view_formats: &[],
            });
            let view = texture.create_view(&Default::default());
            (Some(texture), Some(view))
        } else {
            (None, None)
        };

        // Depth texture for proper occlusion
        let depth_texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("scene depth"),
            size: wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Depth32Float,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
            view_formats: &[],
        });
        let depth_view = depth_texture.create_view(&Default::default());

        // Render pipeline with depth testing and alpha blending
        let render_pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("scene render pipeline"),
            layout: Some(&pipeline_layout),
            vertex: wgpu::VertexState {
                module: &shader_module,
                entry_point: Some("vs_main"),
                buffers: &[],
                compilation_options: Default::default(),
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader_module,
                entry_point: Some("fs_main"),
                targets: &[Some(wgpu::ColorTargetState {
                    format: output_format,
                    blend: Some(wgpu::BlendState::ALPHA_BLENDING),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
                compilation_options: Default::default(),
            }),
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::TriangleList,
                ..Default::default()
            },
            depth_stencil: Some(wgpu::DepthStencilState {
                format: wgpu::TextureFormat::Depth32Float,
                depth_write_enabled: CONTENT_QUAD_DEPTH_WRITE_ENABLED,
                depth_compare: wgpu::CompareFunction::Less,
                stencil: wgpu::StencilState::default(),
                bias: wgpu::DepthBiasState::default(),
            }),
            multisample: wgpu::MultisampleState {
                count: sample_count,
                ..Default::default()
            },
            multiview: None,
            cache: None,
        });

        // Placeholder texture (1x1 semi-transparent white)
        let placeholder_texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("scene placeholder"),
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
                texture: &placeholder_texture,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            &[255u8, 255, 255, 255],
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
        let placeholder_view = placeholder_texture.create_view(&Default::default());

        // ── Grid pipeline ──────────────────────────────────────────
        let grid_shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("scene_grid"),
            source: wgpu::ShaderSource::Wgsl(SCENE_GRID_WGSL.into()),
        });

        let grid_uniform_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("grid uniform buffer"),
            size: std::mem::size_of::<GridUniformData>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });

        let grid_uniform_bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("grid uniform bgl"),
            entries: &[wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::VERTEX | wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: wgpu::BufferSize::new(
                        std::mem::size_of::<GridUniformData>() as u64
                    ),
                },
                count: None,
            }],
        });

        let grid_uniform_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("grid uniform bg"),
            layout: &grid_uniform_bgl,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: grid_uniform_buffer.as_entire_binding(),
            }],
        });

        let grid_texture_bgl =
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: Some("grid texture bgl"),
                entries: &[
                    wgpu::BindGroupLayoutEntry {
                        binding: 0,
                        visibility: wgpu::ShaderStages::FRAGMENT,
                        ty: wgpu::BindingType::Texture {
                            multisampled: false,
                            view_dimension: wgpu::TextureViewDimension::D2,
                            sample_type: wgpu::TextureSampleType::Float { filterable: true },
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

        let reverie_sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            address_mode_u: wgpu::AddressMode::Repeat,
            address_mode_v: wgpu::AddressMode::ClampToEdge,
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            ..Default::default()
        });

        let reverie_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("grid reverie fallback bg"),
            layout: &grid_texture_bgl,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::TextureView(&placeholder_view),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::Sampler(&reverie_sampler),
                },
            ],
        });

        let grid_pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("grid pipeline layout"),
            bind_group_layouts: &[&grid_uniform_bgl, &grid_texture_bgl],
            push_constant_ranges: &[],
        });

        let grid_pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("grid render pipeline"),
            layout: Some(&grid_pipeline_layout),
            vertex: wgpu::VertexState {
                module: &grid_shader,
                entry_point: Some("vs_main"),
                buffers: &[],
                compilation_options: Default::default(),
            },
            fragment: Some(wgpu::FragmentState {
                module: &grid_shader,
                entry_point: Some("fs_main"),
                targets: &[Some(wgpu::ColorTargetState {
                    format: output_format,
                    blend: Some(wgpu::BlendState::ALPHA_BLENDING),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
                compilation_options: Default::default(),
            }),
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::TriangleList,
                ..Default::default()
            },
            depth_stencil: Some(wgpu::DepthStencilState {
                format: wgpu::TextureFormat::Depth32Float,
                depth_write_enabled: false,
                depth_compare: wgpu::CompareFunction::Always,
                stencil: wgpu::StencilState::default(),
                bias: wgpu::DepthBiasState::default(),
            }),
            multisample: wgpu::MultisampleState {
                count: sample_count,
                ..Default::default()
            },
            multiview: None,
            cache: None,
        });

        // Entity restoration pipeline (post-Reverie)
        let entity_restore_shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("entity_restore"),
            source: wgpu::ShaderSource::Wgsl(ENTITY_RESTORE_WGSL.into()),
        });
        let entity_restore_bgl =
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: Some("entity_restore_bgl"),
                entries: &[
                    wgpu::BindGroupLayoutEntry {
                        binding: 0,
                        visibility: wgpu::ShaderStages::FRAGMENT,
                        ty: wgpu::BindingType::Texture {
                            multisampled: false,
                            view_dimension: wgpu::TextureViewDimension::D2,
                            sample_type: wgpu::TextureSampleType::Float { filterable: true },
                        },
                        count: None,
                    },
                    wgpu::BindGroupLayoutEntry {
                        binding: 1,
                        visibility: wgpu::ShaderStages::FRAGMENT,
                        ty: wgpu::BindingType::Texture {
                            multisampled: false,
                            view_dimension: wgpu::TextureViewDimension::D2,
                            sample_type: wgpu::TextureSampleType::Float { filterable: true },
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
        let entity_restore_layout =
            device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
                label: Some("entity_restore_layout"),
                bind_group_layouts: &[&entity_restore_bgl],
                push_constant_ranges: &[],
            });
        let entity_restore_sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            ..Default::default()
        });
        let entity_restore_pipeline =
            device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                label: Some("entity_restore_pipeline"),
                layout: Some(&entity_restore_layout),
                vertex: wgpu::VertexState {
                    module: &entity_restore_shader,
                    entry_point: Some("vs_main"),
                    buffers: &[],
                    compilation_options: Default::default(),
                },
                fragment: Some(wgpu::FragmentState {
                    module: &entity_restore_shader,
                    entry_point: Some("fs_main"),
                    targets: &[Some(wgpu::ColorTargetState {
                        format: wgpu::TextureFormat::Rgba8UnormSrgb,
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

        log::info!(
            "SceneRenderer initialized: {}x{}, fov={:.0}°, scene_msaa={}x",
            width,
            height,
            camera.fov_y_radians.to_degrees(),
            sample_count
        );

        Self {
            camera,
            render_pipeline,
            uniform_buffer,
            uniform_align,
            uniform_bind_group_layout,
            uniform_bind_group,
            texture_bind_group_layout,
            sampler,
            sample_count,
            output_texture,
            output_view,
            _msaa_color_texture: msaa_color_texture,
            msaa_color_view,
            depth_texture,
            depth_view,
            placeholder_texture,
            placeholder_view,
            width,
            height,
            frame_count: 0,
            grid_pipeline,
            grid_uniform_buffer,
            grid_uniform_bind_group,
            grid_texture_bgl,
            reverie_bind_group,
            reverie_sampler,
            heatmap_buffer,
            heatmap_bind_group,
            entity_restore_pipeline,
            entity_restore_bgl,
            entity_restore_sampler,
        }
    }

    pub fn restore_entities(
        &self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        reverie_output: &wgpu::TextureView,
        target: &wgpu::TextureView,
    ) {
        let bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("entity_restore_bg"),
            layout: &self.entity_restore_bgl,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::TextureView(reverie_output),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::TextureView(&self.output_view),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: wgpu::BindingResource::Sampler(&self.entity_restore_sampler),
                },
            ],
        });
        let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
            label: Some("entity_restore_encoder"),
        });
        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("entity_restore_pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: target,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Load,
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: None,
                ..Default::default()
            });
            pass.set_pipeline(&self.entity_restore_pipeline);
            pass.set_bind_group(0, &bg, &[]);
            pass.draw(0..6, 0..1);
        }
        queue.submit(std::iter::once(encoder.finish()));
    }

    pub fn set_reverie_texture(&mut self, device: &wgpu::Device, view: &wgpu::TextureView) {
        self.reverie_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("grid reverie bg"),
            layout: &self.grid_texture_bgl,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::TextureView(view),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::Sampler(&self.reverie_sampler),
                },
            ],
        });
    }

    /// Render the 3D scene. Builds the scene graph dynamically from
    /// ContentSourceManager state each frame.
    pub fn render(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        time: f32,
        content_source_mgr: Option<&ContentSourceManager>,
    ) -> &wgpu::TextureView {
        self.frame_count = self.frame_count.wrapping_add(1);

        // Update camera before scene construction so AoA pane LOD gates match the drawn frame.
        self.camera.apply_orbital_drift(time);

        // Build scene from live content sources
        let scene = if let Some(mgr) = content_source_mgr {
            let active = mgr.active_source_records();
            build_live_scene_from_active(&active, time, &self.camera, self.width, self.height).nodes
        } else {
            build_proof_scene()
        };

        let view = self.camera.view_matrix();
        let proj = self.camera.projection_matrix();
        let (occluders, occluder_count) = grid_shadow_occluders(&scene);

        let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
            label: Some("scene render encoder"),
        });

        {
            let color_view = self.msaa_color_view.as_ref().unwrap_or(&self.output_view);
            let resolve_target = if self.sample_count > 1 {
                Some(&self.output_view)
            } else {
                None
            };
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("scene render pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: color_view,
                    resolve_target,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color {
                            r: 0.0,
                            g: 0.0,
                            b: 0.0,
                            a: 0.0,
                        }),
                        store: if self.sample_count > 1 {
                            wgpu::StoreOp::Discard
                        } else {
                            wgpu::StoreOp::Store
                        },
                    },
                })],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &self.depth_view,
                    depth_ops: Some(wgpu::Operations {
                        load: wgpu::LoadOp::Clear(1.0),
                        store: wgpu::StoreOp::Store,
                    }),
                    stencil_ops: None,
                }),
                ..Default::default()
            });

            // ── Draw 3D perspective grid ──────────────────────────
            {
                let grid_data = GridUniformData {
                    view: view.to_cols_array_2d(),
                    projection: proj.to_cols_array_2d(),
                    light_position: vec4(self.camera.point_light_position(time), 1.0),
                    light_color: synthwave_light_color(time),
                    time,
                    occluder_count,
                    sphere_warmth: read_sphere_warmth(),
                    _pad1: 0.0,
                    occluders,
                };
                queue.write_buffer(&self.grid_uniform_buffer, 0, bytemuck::bytes_of(&grid_data));
                pass.set_pipeline(&self.grid_pipeline);
                pass.set_bind_group(0, &self.grid_uniform_bind_group, &[]);
                pass.set_bind_group(1, &self.reverie_bind_group, &[]);
                pass.draw(0..48, 0..1); // Room grids + light + volumetric rays
            }

            // ── Upload AoA heatmap ──────────────────────────────────
            if self.frame_count % 3 == 0 {
                upload_heatmap(queue, &self.heatmap_buffer);
            }

            // ── Draw content quads ───────────────────────────────────
            pass.set_pipeline(&self.render_pipeline);
            pass.set_bind_group(2, &self.heatmap_bind_group, &[]);

            // Sort nodes back-to-front in camera space for proper alpha blending.
            let sorted_indices = sorted_scene_indices_back_to_front(&scene, view);

            // Pre-upload ALL node uniforms before the render pass draws
            let mut draw_list: Vec<(u32, wgpu::BindGroup, u32)> = Vec::new();
            let mut active_entity_local_effects = Vec::new();
            for (slot, &idx) in sorted_indices.iter().enumerate() {
                let node = &scene[idx];
                if node.opacity < 0.001 {
                    continue;
                }
                if slot >= MAX_SCENE_NODES {
                    break;
                }

                let local_effect = entity_local_spatial_effect_for_node(node, time, slot);
                let uniform_data = SceneUniformData {
                    model: node.model_matrix().to_cols_array_2d(),
                    view: view.to_cols_array_2d(),
                    projection: proj.to_cols_array_2d(),
                    opacity: node.opacity,
                    shader_kind: node.shader.as_f32(),
                    payload_pane_ordinal: node
                        .aoa_payload_pane_ordinal
                        .map_or(-1.0, |ordinal| ordinal as f32),
                    payload_mode: node
                        .aoa_payload_mode
                        .map_or(0.0, |mode| mode.shader_payload_mode()),
                    local_effect_kind: local_effect.kind.as_f32(),
                    local_effect_mix: local_effect.mix,
                    local_effect_param_a: local_effect.param_a,
                    local_effect_param_b: local_effect.param_b,
                };
                let offset = (slot as u64) * (self.uniform_align as u64);
                queue.write_buffer(
                    &self.uniform_buffer,
                    offset,
                    bytemuck::bytes_of(&uniform_data),
                );

                let tex_view = if let Some(ref source_id) = node.content_source_id {
                    if let Some(mgr) = content_source_mgr {
                        mgr.source_view(source_id).unwrap_or(&self.placeholder_view)
                    } else {
                        &self.placeholder_view
                    }
                } else {
                    &self.placeholder_view
                };

                let tex_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
                    label: Some(&format!("scene tex bg {}", node.label)),
                    layout: &self.texture_bind_group_layout,
                    entries: &[
                        wgpu::BindGroupEntry {
                            binding: 0,
                            resource: wgpu::BindingResource::TextureView(tex_view),
                        },
                        wgpu::BindGroupEntry {
                            binding: 1,
                            resource: wgpu::BindingResource::Sampler(&self.sampler),
                        },
                    ],
                });

                draw_list.push((
                    slot as u32 * self.uniform_align,
                    tex_bind_group,
                    node.shader.vertex_count(),
                ));

                if local_effect.is_active() {
                    active_entity_local_effects.push(serde_json::json!({
                        "node_label": node.label,
                        "content_source_id": node.content_source_id.as_deref(),
                        "effect": local_effect.kind.name(),
                        "effect_scope": "entity_local_scene_node",
                        "effect_family": "atmospheric",
                        "effect_binding": "source_plane_uv",
                        "effect_application_plane": "entity_field_spatial_reprojection",
                        "route_authority": "entity_local_source_plane",
                        "fourth_wall_policy": "forbid_foreground_overlay",
                        "output_plane_route": false,
                        "mix": local_effect.mix,
                        "param_a": local_effect.param_a,
                        "param_b": local_effect.param_b,
                    }));
                }
            }
            self.publish_entity_local_effect_state(&active_entity_local_effects);

            // Now draw with dynamic offsets — each draw uses its own uniform slice
            for (dyn_offset, tex_bg, vertex_count) in &draw_list {
                pass.set_bind_group(0, &self.uniform_bind_group, &[*dyn_offset]);
                pass.set_bind_group(1, tex_bg, &[]);
                pass.draw(0..*vertex_count, 0..1);
            }

            // ── AoA insphere — drawn AFTER content quads so it composites on top ──
            pass.set_pipeline(&self.grid_pipeline);
            pass.set_bind_group(0, &self.grid_uniform_bind_group, &[]);
            pass.set_bind_group(1, &self.reverie_bind_group, &[]);
            pass.draw(48..54, 0..1);
        }

        queue.submit(std::iter::once(encoder.finish()));

        &self.output_view
    }

    fn publish_entity_local_effect_state(&self, active_effects: &[serde_json::Value]) {
        if !self.frame_count.is_multiple_of(30) {
            return;
        }

        let payload = serde_json::json!({
            "schema": "entity-local-effect-state-v1",
            "frame_count": self.frame_count,
            "route": {
                "effect_scope": "entity_local_scene_node",
                "effect_binding": "source_plane_uv",
                "effect_application_plane": "entity_field_spatial_reprojection",
                "route_authority": "entity_local_source_plane",
                "fourth_wall_policy": "forbid_foreground_overlay",
                "output_plane_route": false,
            },
            "candidate_effects": [
                {
                    "name": "mirror",
                    "prior_route_authority": "entity_local_route_required",
                    "restored_route_authority": "entity_local_source_plane",
                },
                {
                    "name": "kaleidoscope",
                    "prior_route_authority": "entity_local_route_required",
                    "restored_route_authority": "entity_local_source_plane",
                },
                {
                    "name": "warp",
                    "prior_route_authority": "entity_local_route_required",
                    "restored_route_authority": "entity_local_source_plane",
                },
                {
                    "name": "fisheye",
                    "prior_route_authority": "entity_local_route_required",
                    "restored_route_authority": "entity_local_source_plane",
                },
                {
                    "name": "transform",
                    "prior_route_authority": "entity_local_route_required",
                    "restored_route_authority": "entity_local_source_plane",
                },
                {
                    "name": "displacement_map",
                    "prior_route_authority": "entity_local_route_required",
                    "restored_route_authority": "entity_local_source_plane",
                },
                {
                    "name": "droste",
                    "prior_route_authority": "entity_local_route_required",
                    "restored_route_authority": "entity_local_source_plane",
                },
                {
                    "name": "tunnel",
                    "prior_route_authority": "entity_local_route_required",
                    "restored_route_authority": "entity_local_source_plane",
                },
                {
                    "name": "tile",
                    "prior_route_authority": "entity_local_route_required",
                    "restored_route_authority": "entity_local_source_plane",
                },
                {
                    "name": "drift",
                    "prior_route_authority": "entity_local_route_required",
                    "restored_route_authority": "entity_local_source_plane",
                },
                {
                    "name": "breathing",
                    "prior_route_authority": "entity_local_route_required",
                    "restored_route_authority": "entity_local_source_plane",
                },
            ],
            "active_effect_count": active_effects.len(),
            "active_effects": active_effects,
        });

        let path = std::path::Path::new(ENTITY_LOCAL_EFFECT_STATE_FILE);
        if let Some(parent) = path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let tmp = path.with_extension("json.tmp");
        if std::fs::write(
            &tmp,
            serde_json::to_vec_pretty(&payload).unwrap_or_default(),
        )
        .is_ok()
        {
            let _ = std::fs::rename(tmp, path);
        }
    }

    pub fn width(&self) -> u32 {
        self.width
    }

    pub fn height(&self) -> u32 {
        self.height
    }

    pub fn output_texture(&self) -> &wgpu::Texture {
        &self.output_texture
    }

    pub fn sample_count(&self) -> u32 {
        self.sample_count
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn live_empty_sources_do_not_render_proof_quads() {
        let camera = Camera3D::new(1920, 1080);
        let scene = build_live_scene_from_active(&[], 0.0, &camera, 1920, 1080);

        assert!(
            scene.nodes.is_empty(),
            "live compositor startup/source gaps must not synthesize proof-scene quads"
        );
    }

    #[test]
    fn explicit_no_manager_mode_still_has_a_proof_scene() {
        assert!(
            !build_proof_scene().is_empty(),
            "proof scene remains available for explicit non-live renderer tests"
        );
    }

    #[test]
    fn translucent_content_quads_do_not_write_depth() {
        assert!(
            !CONTENT_QUAD_DEPTH_WRITE_ENABLED,
            "alpha-blended livestream quads must not turn transparent regions into occluding panes"
        );
    }

    #[test]
    fn aoa_pane_payload_nodes_do_not_cast_grid_shadows() {
        let mut payload = SceneNode::new("aoa-payload");
        payload.position = Vec3::new(5.0, 2.0, -3.0);
        payload.scale = Vec3::new(9.0, 9.0, 1.0);
        payload.opacity = 1.0;
        payload.aoa_payload_pane_ordinal = Some(12);

        let mut anchor = SceneNode::new("aoa-anchor");
        anchor.position = Vec3::new(-1.0, 0.5, -4.0);
        anchor.scale = Vec3::new(2.0, 2.0, 1.0);
        anchor.opacity = 0.8;

        let (occluders, count) = grid_shadow_occluders(&[payload, anchor.clone()]);

        assert_eq!(
            count, 1,
            "AoA pane payload passes are source-bound texture layers, not independent scroom occluders"
        );
        assert_eq!(occluders[0].center[0], anchor.position.x);
        assert_eq!(occluders[0].center[1], anchor.position.y);
        assert_eq!(occluders[0].center[2], anchor.position.z);
    }

    #[test]
    fn alpha_sort_uses_view_space_depth_after_camera_drift() {
        let mut camera = Camera3D::new(1920, 1080);
        camera.apply_orbital_drift(18.0);
        let view = camera.view_matrix();

        let mut left = SceneNode::new("left-same-world-z");
        left.position = Vec3::new(-3.0, 0.0, -4.0);
        let mut right = SceneNode::new("right-same-world-z");
        right.position = Vec3::new(3.0, 0.0, -4.0);
        let scene = vec![left, right];

        assert_eq!(
            scene[0].position.z, scene[1].position.z,
            "the regression case must be ambiguous under old world-z sorting"
        );

        let left_view_z = scene_node_view_z(view, &scene[0]);
        let right_view_z = scene_node_view_z(view, &scene[1]);
        assert!(
            (left_view_z - right_view_z).abs() > 0.01,
            "drifted camera should make same-world-z nodes differ in view-space depth"
        );

        let expected_first = if left_view_z < right_view_z { 0 } else { 1 };
        let sorted = sorted_scene_indices_back_to_front(&scene, view);

        assert_eq!(
            sorted[0], expected_first,
            "translucent scene quads must sort back-to-front by camera-space depth"
        );
    }

    #[test]
    fn scene_msaa_defaults_to_four_x_but_can_be_disabled() {
        assert_eq!(sanitized_scene_sample_count(None), 4);
        assert_eq!(sanitized_scene_sample_count(Some("4")), 4);
        assert_eq!(sanitized_scene_sample_count(Some("enabled")), 4);
        assert_eq!(sanitized_scene_sample_count(Some("1")), 1);
        assert_eq!(sanitized_scene_sample_count(Some("off")), 1);
    }

    #[test]
    fn unsupported_scene_msaa_values_fail_closed_to_default() {
        assert_eq!(sanitized_scene_sample_count(Some("2")), 4);
        assert_eq!(sanitized_scene_sample_count(Some("8")), 4);
        assert_eq!(sanitized_scene_sample_count(Some("garbage")), 4);
    }

    #[test]
    fn scene_quad_shader_uses_derivative_aware_edge_coverage() {
        assert!(
            SCENE_QUAD_WGSL.contains("fwidth"),
            "AoA and pane geometry should use derivative-aware AA, not fixed output-plane smoothing"
        );
    }

    #[test]
    fn entity_local_spatial_route_only_attaches_to_textured_content_nodes() {
        let mut textured = SceneNode::new("camera-brio");
        textured.content_source_id = Some("camera-brio".to_string());
        let effect = entity_local_spatial_effect_for_node(&textured, 12.0, 0);
        assert!(
            effect.is_active(),
            "textured source planes should be eligible for entity-local spatial treatment"
        );

        let mut aoa = SceneNode::new("aperture-of-apertures");
        aoa.shader = crate::scene::SceneNodeShader::ApertureOfApertures;
        aoa.content_source_id = Some("pane-source".to_string());
        assert_eq!(
            entity_local_spatial_effect_for_node(&aoa, 12.0, 0).kind,
            EntityLocalSpatialEffectKind::None,
            "AoA pane-local payloads need their own pane route, not the source-plane quad route"
        );

        let no_source = SceneNode::new("world-grid");
        assert_eq!(
            entity_local_spatial_effect_for_node(&no_source, 12.0, 0).kind,
            EntityLocalSpatialEffectKind::None,
            "world/grid geometry must not get a source-plane texture route"
        );
    }

    #[test]
    fn entity_local_spatial_effects_are_declared_in_quad_shader_not_fourth_wall_pipeline() {
        assert!(
            SCENE_QUAD_WGSL.contains("apply_entity_local_spatial_effect"),
            "entity-local spatial repair must live in the scene quad shader"
        );
        assert!(
            SCENE_QUAD_WGSL.contains("scene.local_effect_kind"),
            "entity-local route should be uniformed per scene entity"
        );
        assert!(
            SCENE_QUAD_WGSL.contains("textureSample(quad_texture, quad_sampler"),
            "entity-local effects must sample the bound entity texture, not composed @live"
        );
    }

    #[test]
    fn scene_quad_shader_parses_after_entity_local_effect_route_changes() {
        naga::front::wgsl::parse_str(SCENE_QUAD_WGSL)
            .expect("scene quad WGSL must parse before live compositor deployment");
    }

    #[test]
    fn entity_local_runtime_state_schema_declares_no_output_plane_route() {
        assert_eq!(
            ENTITY_LOCAL_EFFECT_STATE_FILE,
            "/dev/shm/hapax-visual/entity-local-effect-state.json"
        );
        assert_eq!(EntityLocalSpatialEffectKind::Mirror.name(), "mirror");
        assert_eq!(
            EntityLocalSpatialEffectKind::Kaleidoscope.name(),
            "kaleidoscope"
        );
        assert_eq!(EntityLocalSpatialEffectKind::Warp.name(), "warp");
    }

    #[test]
    fn entity_local_route_covers_stateless_spatial_family_without_slitscan() {
        for restored in [
            "mirror",
            "kaleidoscope",
            "warp",
            "fisheye",
            "transform",
            "displacement_map",
            "droste",
            "tunnel",
            "tile",
            "drift",
            "breathing",
        ] {
            assert!(
                SCENE_QUAD_WGSL.contains(&format!("entity_local_{}", restored)),
                "{restored} should have a source-plane entity-local route"
            );
        }
        assert!(
            !SCENE_QUAD_WGSL.contains("entity_local_slitscan"),
            "slitscan needs per-source temporal accumulators before restoration"
        );
    }

    #[test]
    fn nebulous_scroom_planes_have_persistent_material() {
        assert!(
            SCENE_GRID_WGSL.contains("scroom_material_pattern"),
            "floor, ceiling, and back wall planes need persistent room material"
        );
        assert!(
            SCENE_GRID_WGSL.contains("not to the output pane"),
            "scroom material must remain authored room geometry, not a fourth-wall overlay"
        );
    }

    #[test]
    fn nebulous_scroom_has_no_mid_field_cross_plane() {
        for forbidden in [
            "mid-field",
            "is_mid_field",
            "wp.y - 0.35",
            "0.35, lp.y * 6.5",
            "base_alpha = 0.056",
        ] {
            assert!(
                !SCENE_GRID_WGSL.contains(forbidden),
                "scroom grid must not cut a middle plane through occupied room volume"
            );
        }
    }

    #[test]
    fn scene_grid_material_is_stable_not_luma_pumped() {
        for forbidden in [
            "0.88 + 0.12 * sin",
            "0.78 + 0.22 * sin",
            "0.96 + 0.04 * sin",
            "t * 0.010",
        ] {
            assert!(
                !SCENE_GRID_WGSL.contains(forbidden),
                "scroom grid/light material must not use time-driven alpha or luma pumping"
            );
        }
    }

    #[test]
    fn scene_grid_shader_parses_after_scroom_material_changes() {
        naga::front::wgsl::parse_str(SCENE_GRID_WGSL)
            .expect("scene grid WGSL must parse before live compositor deployment");
    }
}
