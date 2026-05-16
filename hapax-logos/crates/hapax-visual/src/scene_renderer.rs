//! 3D scene renderer for compositor Phase 1.
//!
//! Renders dynamically-built scene nodes (from `ContentSourceManager`
//! state) in 3D space using a perspective camera. Each content source
//! becomes a textured quad at its z-plane depth.
//!
//! Gated behind `HAPAX_IMAGINATION_3D_PROOF=1`. When disabled, this
//! module is compiled but never instantiated — zero runtime cost.

use bytemuck::{Pod, Zeroable};
use glam::Vec3;

use crate::content_sources::ContentSourceManager;
use crate::scene::{build_proof_scene, build_scene_from_sources, Camera3D, SceneNode};

const SCENE_QUAD_WGSL: &str = include_str!("shaders/scene_quad.wgsl");
// GRID_SHADER_VERSION: 1778811160
const SCENE_GRID_WGSL: &str = include_str!("shaders/scene_grid.wgsl");
const MAX_GRID_SHADOW_OCCLUDERS: usize = 16;

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
    _pad: [f32; 2],
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
    _pad: [f32; 2],
    occluders: [GridOccluderData; MAX_GRID_SHADOW_OCCLUDERS],
}

/// Maximum number of scene nodes we can render per frame.
const MAX_SCENE_NODES: usize = 128;
/// Content quads are translucent compositing surfaces. They must be drawn
/// back-to-front without writing depth, otherwise alpha-transparent regions
/// become invisible occluding panes.
const CONTENT_QUAD_DEPTH_WRITE_ENABLED: bool = false;

fn build_live_scene_from_active(
    active: &[(&str, f32, i32, u32, u32)],
    time: f32,
) -> Vec<SceneNode> {
    if active.is_empty() {
        Vec::new()
    } else {
        build_scene_from_sources(active, time)
    }
}

fn vec4(v: Vec3, w: f32) -> [f32; 4] {
    [v.x, v.y, v.z, w]
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
        .filter(|node| node.opacity > 0.04 && node.scale.x > 0.02 && node.scale.y > 0.02)
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

pub struct SceneRenderer {
    camera: Camera3D,
    render_pipeline: wgpu::RenderPipeline,
    uniform_buffer: wgpu::Buffer,
    uniform_align: u32,
    uniform_bind_group_layout: wgpu::BindGroupLayout,
    uniform_bind_group: wgpu::BindGroup,
    texture_bind_group_layout: wgpu::BindGroupLayout,
    sampler: wgpu::Sampler,
    output_texture: wgpu::Texture,
    output_view: wgpu::TextureView,
    depth_texture: wgpu::Texture,
    depth_view: wgpu::TextureView,
    /// Placeholder 1x1 white texture for nodes without content sources.
    placeholder_texture: wgpu::Texture,
    placeholder_view: wgpu::TextureView,
    width: u32,
    height: u32,
    // Grid rendering
    grid_pipeline: wgpu::RenderPipeline,
    grid_uniform_buffer: wgpu::Buffer,
    grid_uniform_bind_group: wgpu::BindGroup,
}

impl SceneRenderer {
    pub fn new(device: &wgpu::Device, queue: &wgpu::Queue, width: u32, height: u32) -> Self {
        let camera = Camera3D::new(width, height);

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
            ..Default::default()
        });

        // Shader module
        let shader_module = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("scene_quad"),
            source: wgpu::ShaderSource::Wgsl(SCENE_QUAD_WGSL.into()),
        });

        // Pipeline layout
        let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("scene pipeline layout"),
            bind_group_layouts: &[&uniform_bind_group_layout, &texture_bind_group_layout],
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

        // Depth texture for proper occlusion
        let depth_texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("scene depth"),
            size: wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
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
            multisample: wgpu::MultisampleState::default(),
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

        let grid_pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("grid pipeline layout"),
            bind_group_layouts: &[&grid_uniform_bgl],
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
                depth_compare: wgpu::CompareFunction::Less,
                stencil: wgpu::StencilState::default(),
                bias: wgpu::DepthBiasState::default(),
            }),
            multisample: wgpu::MultisampleState::default(),
            multiview: None,
            cache: None,
        });

        log::info!(
            "SceneRenderer initialized: {}x{}, fov={:.0}°",
            width,
            height,
            camera.fov_y_radians.to_degrees()
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
            output_texture,
            output_view,
            depth_texture,
            depth_view,
            placeholder_texture,
            placeholder_view,
            width,
            height,
            grid_pipeline,
            grid_uniform_buffer,
            grid_uniform_bind_group,
        }
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
        // Build scene from live content sources
        let scene = if let Some(mgr) = content_source_mgr {
            let active = mgr.active_source_info();
            build_live_scene_from_active(&active, time)
        } else {
            build_proof_scene()
        };

        // Update camera with orbital drift
        self.camera.apply_orbital_drift(time);
        let view = self.camera.view_matrix();
        let proj = self.camera.projection_matrix();
        let (occluders, occluder_count) = grid_shadow_occluders(&scene);

        let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
            label: Some("scene render encoder"),
        });

        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("scene render pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &self.output_view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color {
                            r: 0.0,
                            g: 0.0,
                            b: 0.0,
                            a: 0.0,
                        }),
                        store: wgpu::StoreOp::Store,
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
                    _pad: [0.0; 2],
                    occluders,
                };
                queue.write_buffer(&self.grid_uniform_buffer, 0, bytemuck::bytes_of(&grid_data));
                pass.set_pipeline(&self.grid_pipeline);
                pass.set_bind_group(0, &self.grid_uniform_bind_group, &[]);
                pass.draw(0..48, 0..1); // Room grids + visible light marker + volumetric rays
            }

            // ── Draw content quads ───────────────────────────────────
            pass.set_pipeline(&self.render_pipeline);

            // Sort nodes back-to-front for proper alpha blending
            let mut sorted_indices: Vec<usize> = (0..scene.len()).collect();
            sorted_indices.sort_by(|a, b| {
                scene[*a]
                    .position
                    .z
                    .partial_cmp(&scene[*b].position.z)
                    .unwrap_or(std::cmp::Ordering::Equal)
            });

            // Pre-upload ALL node uniforms before the render pass draws
            let mut draw_list: Vec<(u32, wgpu::BindGroup)> = Vec::new();
            for (slot, &idx) in sorted_indices.iter().enumerate() {
                let node = &scene[idx];
                if node.opacity < 0.001 {
                    continue;
                }
                if slot >= MAX_SCENE_NODES {
                    break;
                }

                let uniform_data = SceneUniformData {
                    model: node.model_matrix().to_cols_array_2d(),
                    view: view.to_cols_array_2d(),
                    projection: proj.to_cols_array_2d(),
                    opacity: node.opacity,
                    shader_kind: node.shader.as_f32(),
                    _pad: [0.0; 2],
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

                draw_list.push((slot as u32 * self.uniform_align, tex_bind_group));
            }

            // Now draw with dynamic offsets — each draw uses its own uniform slice
            for (dyn_offset, tex_bg) in &draw_list {
                pass.set_bind_group(0, &self.uniform_bind_group, &[*dyn_offset]);
                pass.set_bind_group(1, tex_bg, &[]);
                pass.draw(0..6, 0..1);
            }
        }

        queue.submit(std::iter::once(encoder.finish()));

        &self.output_view
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
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn live_empty_sources_do_not_render_proof_quads() {
        let scene = build_live_scene_from_active(&[], 0.0);

        assert!(
            scene.is_empty(),
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
}
