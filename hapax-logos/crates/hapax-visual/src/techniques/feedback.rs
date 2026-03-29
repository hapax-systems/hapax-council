use bytemuck::{Pod, Zeroable};
use wgpu::util::DeviceExt;

use crate::gpu::GpuContext;

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
struct FeedbackParams {
    decay: f32,
    hue_shift: f32,
    _pad0: f32,
    _pad1: f32,
}

pub struct FeedbackTechnique {
    pipeline: wgpu::ComputePipeline,
    uniform_buf: wgpu::Buffer,
    /// Previous composited frame (Rgba8UnormSrgb)
    pub prev_texture: wgpu::Texture,
    pub prev_view: wgpu::TextureView,
    /// Output (processed feedback)
    pub output_texture: wgpu::Texture,
    pub output_view: wgpu::TextureView,
    bgl: wgpu::BindGroupLayout,
    width: u32,
    height: u32,
}

impl FeedbackTechnique {
    pub fn new(gpu: &GpuContext, width: u32, height: u32) -> Self {
        let shader = gpu.device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("feedback.wgsl"),
            source: wgpu::ShaderSource::Wgsl(include_str!("../shaders/feedback.wgsl").into()),
        });

        let uniform_buf = gpu.device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("feedback params"),
            contents: bytemuck::bytes_of(&FeedbackParams {
                decay: 0.97,
                hue_shift: 0.5,
                _pad0: 0.0,
                _pad1: 0.0,
            }),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });

        let bgl = gpu.device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("feedback bgl"),
            entries: &[
                wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 1,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Float { filterable: false },
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 2,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::StorageTexture {
                        access: wgpu::StorageTextureAccess::WriteOnly,
                        format: wgpu::TextureFormat::Rgba8Unorm,
                        view_dimension: wgpu::TextureViewDimension::D2,
                    },
                    count: None,
                },
            ],
        });

        let pl = gpu.device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("feedback pl"),
            bind_group_layouts: &[&bgl],
            push_constant_ranges: &[],
        });

        let pipeline = gpu.device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("feedback pipeline"),
            layout: Some(&pl),
            module: &shader,
            entry_point: Some("main"),
            compilation_options: Default::default(),
            cache: None,
        });

        let (prev_texture, prev_view, output_texture, output_view) =
            Self::create_textures(&gpu.device, width, height);

        Self {
            pipeline,
            uniform_buf,
            prev_texture,
            prev_view,
            output_texture,
            output_view,
            bgl,
            width,
            height,
        }
    }

    fn create_textures(
        device: &wgpu::Device,
        width: u32,
        height: u32,
    ) -> (wgpu::Texture, wgpu::TextureView, wgpu::Texture, wgpu::TextureView) {
        let desc = |label| wgpu::TextureDescriptor {
            label: Some(label),
            size: wgpu::Extent3d { width, height, depth_or_array_layers: 1 },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8Unorm,
            usage: wgpu::TextureUsages::TEXTURE_BINDING
                | wgpu::TextureUsages::STORAGE_BINDING
                | wgpu::TextureUsages::COPY_DST
                | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        };
        let prev = device.create_texture(&desc("feedback prev"));
        let out = device.create_texture(&desc("feedback output"));
        let prev_v = prev.create_view(&Default::default());
        let out_v = out.create_view(&Default::default());
        (prev, prev_v, out, out_v)
    }

    /// Process feedback from previous frame.
    pub fn process(&self, encoder: &mut wgpu::CommandEncoder, gpu: &GpuContext) {
        let bg = gpu.device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("feedback bg"),
            layout: &self.bgl,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: self.uniform_buf.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::TextureView(&self.prev_view),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: wgpu::BindingResource::TextureView(&self.output_view),
                },
            ],
        });

        let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
            label: Some("feedback pass"),
            ..Default::default()
        });
        pass.set_pipeline(&self.pipeline);
        pass.set_bind_group(0, &bg, &[]);
        pass.dispatch_workgroups((self.width + 7) / 8, (self.height + 7) / 8, 1);
    }

    /// Copy the current composited frame to prev_texture for next frame's feedback.
    /// Call after the compositor has rendered to composite_texture.
    pub fn capture_frame(
        &self,
        encoder: &mut wgpu::CommandEncoder,
        source_texture: &wgpu::Texture,
    ) {
        encoder.copy_texture_to_texture(
            wgpu::TexelCopyTextureInfo {
                texture: source_texture,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::TexelCopyTextureInfo {
                texture: &self.prev_texture,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::Extent3d {
                width: self.width,
                height: self.height,
                depth_or_array_layers: 1,
            },
        );
    }

    pub fn resize(&mut self, gpu: &GpuContext, width: u32, height: u32) {
        self.width = width;
        self.height = height;
        let (prev_texture, prev_view, output_texture, output_view) =
            Self::create_textures(&gpu.device, width, height);
        self.prev_texture = prev_texture;
        self.prev_view = prev_view;
        self.output_texture = output_texture;
        self.output_view = output_view;
    }
}
