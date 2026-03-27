use bytemuck::{Pod, Zeroable};
use wgpu::util::DeviceExt;

use crate::visual::gpu::GpuContext;

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
pub struct CompositeUniforms {
    pub opacity_gradient: f32,
    pub opacity_voronoi: f32,
    pub opacity_rd: f32,
    pub opacity_wave: f32,
    pub opacity_physarum: f32,
    pub opacity_feedback: f32,
    pub _pad0: f32,
    pub _pad1: f32,
}

impl Default for CompositeUniforms {
    fn default() -> Self {
        Self {
            opacity_gradient: 1.0,
            opacity_voronoi: 0.25,
            opacity_rd: 0.40,
            opacity_wave: 0.3,
            opacity_physarum: 0.15,
            opacity_feedback: 0.20,
            _pad0: 0.0,
            _pad1: 0.0,
        }
    }
}

/// Offscreen composite output format (needs to be copyable for feedback + post-process).
pub const COMPOSITE_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8Unorm;

pub struct Compositor {
    pipeline: wgpu::RenderPipeline,
    uniform_buf: wgpu::Buffer,
    bind_group_layout: wgpu::BindGroupLayout,
    sampler: wgpu::Sampler,
    /// Offscreen composite target (for feedback capture + post-process input)
    pub composite_texture: wgpu::Texture,
    pub composite_view: wgpu::TextureView,
}

impl Compositor {
    pub fn new(gpu: &GpuContext, width: u32, height: u32) -> Self {
        let shader = gpu
            .device
            .create_shader_module(wgpu::ShaderModuleDescriptor {
                label: Some("composite.wgsl"),
                source: wgpu::ShaderSource::Wgsl(include_str!("shaders/composite.wgsl").into()),
            });

        let uniform_buf = gpu.device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("composite uniforms"),
            contents: bytemuck::bytes_of(&CompositeUniforms::default()),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });

        let sampler = gpu.device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("composite sampler"),
            mag_filter: wgpu::FilterMode::Nearest,
            min_filter: wgpu::FilterMode::Nearest,
            ..Default::default()
        });

        let bind_group_layout =
            gpu.device
                .create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                    label: Some("composite bgl"),
                    entries: &[
                        // Uniforms
                        bgl_buffer(0),
                        // Gradient
                        bgl_texture(1, false),
                        // R-D
                        bgl_texture(2, false),
                        // Voronoi
                        bgl_texture(3, false),
                        // Wave (R32Float — not filterable)
                        bgl_texture(4, false),
                        // Physarum (R32Float — not filterable)
                        bgl_texture(5, false),
                        // Feedback
                        bgl_texture(6, false),
                        // Sampler
                        wgpu::BindGroupLayoutEntry {
                            binding: 7,
                            visibility: wgpu::ShaderStages::FRAGMENT,
                            ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::NonFiltering),
                            count: None,
                        },
                    ],
                });

        let pipeline_layout =
            gpu.device
                .create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
                    label: Some("composite pipeline layout"),
                    bind_group_layouts: &[&bind_group_layout],
                    push_constant_ranges: &[],
                });

        let pipeline = gpu
            .device
            .create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                label: Some("composite pipeline"),
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
                        format: COMPOSITE_FORMAT,
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

        let (composite_texture, composite_view) = Self::create_composite_texture(&gpu.device, width, height);

        Self {
            pipeline,
            uniform_buf,
            bind_group_layout,
            sampler,
            composite_texture,
            composite_view,
        }
    }

    fn create_composite_texture(device: &wgpu::Device, width: u32, height: u32) -> (wgpu::Texture, wgpu::TextureView) {
        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("composite output"),
            size: wgpu::Extent3d { width, height, depth_or_array_layers: 1 },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: COMPOSITE_FORMAT,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT
                | wgpu::TextureUsages::TEXTURE_BINDING
                | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let view = texture.create_view(&Default::default());
        (texture, view)
    }

    pub fn create_frame_bind_group(
        &self,
        device: &wgpu::Device,
        gradient_view: &wgpu::TextureView,
        rd_view: &wgpu::TextureView,
        voronoi_view: &wgpu::TextureView,
        wave_view: &wgpu::TextureView,
        physarum_view: &wgpu::TextureView,
        feedback_view: &wgpu::TextureView,
    ) -> wgpu::BindGroup {
        device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("composite frame bg"),
            layout: &self.bind_group_layout,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: self.uniform_buf.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::TextureView(gradient_view),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: wgpu::BindingResource::TextureView(rd_view),
                },
                wgpu::BindGroupEntry {
                    binding: 3,
                    resource: wgpu::BindingResource::TextureView(voronoi_view),
                },
                wgpu::BindGroupEntry {
                    binding: 4,
                    resource: wgpu::BindingResource::TextureView(wave_view),
                },
                wgpu::BindGroupEntry {
                    binding: 5,
                    resource: wgpu::BindingResource::TextureView(physarum_view),
                },
                wgpu::BindGroupEntry {
                    binding: 6,
                    resource: wgpu::BindingResource::TextureView(feedback_view),
                },
                wgpu::BindGroupEntry {
                    binding: 7,
                    resource: wgpu::BindingResource::Sampler(&self.sampler),
                },
            ],
        })
    }

    /// Render composite to offscreen texture.
    pub fn render(
        &self,
        encoder: &mut wgpu::CommandEncoder,
        bind_group: &wgpu::BindGroup,
    ) {
        let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("composite pass"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: &self.composite_view,
                resolve_target: None,
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                    store: wgpu::StoreOp::Store,
                },
            })],
            depth_stencil_attachment: None,
            ..Default::default()
        });
        pass.set_pipeline(&self.pipeline);
        pass.set_bind_group(0, bind_group, &[]);
        pass.draw(0..3, 0..1);
    }

    /// Update layer opacities from control overrides.
    pub fn update_opacities(&self, queue: &wgpu::Queue, opacities: &std::collections::HashMap<String, f32>) {
        if opacities.is_empty() {
            return;
        }
        let defaults = CompositeUniforms::default();
        let uniforms = CompositeUniforms {
            opacity_gradient: *opacities.get("gradient").unwrap_or(&defaults.opacity_gradient),
            opacity_voronoi: *opacities.get("voronoi").unwrap_or(&defaults.opacity_voronoi),
            opacity_rd: *opacities.get("rd").unwrap_or(&defaults.opacity_rd),
            opacity_wave: *opacities.get("wave").unwrap_or(&defaults.opacity_wave),
            opacity_physarum: *opacities.get("physarum").unwrap_or(&defaults.opacity_physarum),
            opacity_feedback: *opacities.get("feedback").unwrap_or(&defaults.opacity_feedback),
            _pad0: 0.0,
            _pad1: 0.0,
        };
        queue.write_buffer(&self.uniform_buf, 0, bytemuck::bytes_of(&uniforms));
    }

    pub fn resize(&mut self, device: &wgpu::Device, width: u32, height: u32) {
        let (texture, view) = Self::create_composite_texture(device, width, height);
        self.composite_texture = texture;
        self.composite_view = view;
    }
}

// Helper functions for bind group layout entries
fn bgl_buffer(binding: u32) -> wgpu::BindGroupLayoutEntry {
    wgpu::BindGroupLayoutEntry {
        binding,
        visibility: wgpu::ShaderStages::FRAGMENT,
        ty: wgpu::BindingType::Buffer {
            ty: wgpu::BufferBindingType::Uniform,
            has_dynamic_offset: false,
            min_binding_size: None,
        },
        count: None,
    }
}

fn bgl_texture(binding: u32, filterable: bool) -> wgpu::BindGroupLayoutEntry {
    wgpu::BindGroupLayoutEntry {
        binding,
        visibility: wgpu::ShaderStages::FRAGMENT,
        ty: wgpu::BindingType::Texture {
            sample_type: wgpu::TextureSampleType::Float { filterable },
            view_dimension: wgpu::TextureViewDimension::D2,
            multisampled: false,
        },
        count: None,
    }
}
