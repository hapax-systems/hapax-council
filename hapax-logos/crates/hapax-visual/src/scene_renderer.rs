//! 3D scene renderer for compositor Phase 0 proof of concept.
//!
//! Renders `SceneNode` quads in 3D space using a perspective camera,
//! outputs to an intermediate texture that can be used as input to the
//! existing 2D post-process chain (DynamicPipeline).
//!
//! Gated behind `HAPAX_IMAGINATION_3D_PROOF=1`. When disabled, this
//! module is compiled but never instantiated — zero runtime cost.

use bytemuck::{Pod, Zeroable};
use glam::Mat4;
use wgpu::util::DeviceExt;

use crate::scene::{build_proof_scene, Camera3D, SceneNode};

const SCENE_QUAD_WGSL: &str = include_str!("shaders/scene_quad.wgsl");

/// GPU-side uniform data for a single quad draw call.
/// Must match the `SceneUniforms` struct in `scene_quad.wgsl`.
#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
struct SceneUniformData {
    model: [[f32; 4]; 4],
    view: [[f32; 4]; 4],
    projection: [[f32; 4]; 4],
    opacity: f32,
    _pad: [f32; 3],
}

pub struct SceneRenderer {
    scene: Vec<SceneNode>,
    camera: Camera3D,
    render_pipeline: wgpu::RenderPipeline,
    uniform_buffer: wgpu::Buffer,
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
}

impl SceneRenderer {
    pub fn new(device: &wgpu::Device, queue: &wgpu::Queue, width: u32, height: u32) -> Self {
        let scene = build_proof_scene();
        let camera = Camera3D::new(width, height);

        // Uniform buffer (per-quad, updated each draw call)
        let uniform_data = SceneUniformData {
            model: Mat4::IDENTITY.to_cols_array_2d(),
            view: camera.view_matrix().to_cols_array_2d(),
            projection: camera.projection_matrix().to_cols_array_2d(),
            opacity: 1.0,
            _pad: [0.0; 3],
        };

        let uniform_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("scene uniform buffer"),
            contents: bytemuck::bytes_of(&uniform_data),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });

        let uniform_bind_group_layout =
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: Some("scene uniform bgl"),
                entries: &[wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::VERTEX | wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                }],
            });

        let uniform_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("scene uniform bg"),
            layout: &uniform_bind_group_layout,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: uniform_buffer.as_entire_binding(),
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
                depth_write_enabled: true,
                depth_compare: wgpu::CompareFunction::Less,
                stencil: wgpu::StencilState::default(),
                bias: wgpu::DepthBiasState::default(),
            }),
            multisample: wgpu::MultisampleState::default(),
            multiview: None,
            cache: None,
        });

        // Placeholder texture (1x1 white)
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
            &[255u8, 255, 255, 128], // Semi-transparent white
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

        log::info!(
            "SceneRenderer initialized: {}x{}, {} nodes, fov={:.0}°",
            width,
            height,
            scene.len(),
            camera.fov_y_radians.to_degrees()
        );

        Self {
            scene,
            camera,
            render_pipeline,
            uniform_buffer,
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
        }
    }

    /// Render the 3D scene. Returns a reference to the output texture view
    /// for downstream consumption (ShmOutput or DynamicPipeline input).
    pub fn render(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        time: f32,
        content_source_mgr: Option<&crate::content_sources::ContentSourceManager>,
    ) -> &wgpu::TextureView {
        // Update camera with orbital drift
        self.camera.apply_orbital_drift(time);
        let view = self.camera.view_matrix();
        let proj = self.camera.projection_matrix();

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
                            r: 0.02,
                            g: 0.02,
                            b: 0.04,
                            a: 1.0,
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

            pass.set_pipeline(&self.render_pipeline);

            // Sort nodes back-to-front for proper alpha blending
            let mut sorted_indices: Vec<usize> = (0..self.scene.len()).collect();
            sorted_indices.sort_by(|a, b| {
                self.scene[*a]
                    .position
                    .z
                    .partial_cmp(&self.scene[*b].position.z)
                    .unwrap_or(std::cmp::Ordering::Equal)
            });

            for &idx in &sorted_indices {
                let node = &self.scene[idx];
                if node.opacity < 0.001 {
                    continue;
                }

                // Update uniform buffer with this node's matrices
                let uniform_data = SceneUniformData {
                    model: node.model_matrix().to_cols_array_2d(),
                    view: view.to_cols_array_2d(),
                    projection: proj.to_cols_array_2d(),
                    opacity: node.opacity,
                    _pad: [0.0; 3],
                };
                queue.write_buffer(&self.uniform_buffer, 0, bytemuck::bytes_of(&uniform_data));

                // Get texture for this node
                let tex_view = if let Some(src_idx) = node.content_source_index {
                    if let Some(mgr) = content_source_mgr {
                        mgr.slot_view(src_idx)
                    } else {
                        &self.placeholder_view
                    }
                } else {
                    &self.placeholder_view
                };

                // Create per-node texture bind group
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

                pass.set_bind_group(0, &self.uniform_bind_group, &[]);
                pass.set_bind_group(1, &tex_bind_group, &[]);
                pass.draw(0..6, 0..1); // 6 vertices = 2 triangles = 1 quad
            }
        }

        queue.submit(std::iter::once(encoder.finish()));

        &self.output_view
    }

    /// Width of the output texture.
    pub fn width(&self) -> u32 {
        self.width
    }

    /// Height of the output texture.
    pub fn height(&self) -> u32 {
        self.height
    }

    /// Direct access to the output texture for GPU readback.
    pub fn output_texture(&self) -> &wgpu::Texture {
        &self.output_texture
    }
}
