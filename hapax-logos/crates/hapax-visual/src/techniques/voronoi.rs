use bytemuck::{Pod, Zeroable};
use wgpu::util::DeviceExt;

use crate::gpu::GpuContext;


// Zone spatial positions (center of each zone, normalized 0-1)
const ZONE_CENTERS: &[(f32, f32)] = &[
    (0.135, 0.09),  // context_time
    (0.865, 0.09),  // governance
    (0.10, 0.425),  // work_tasks
    (0.885, 0.87),  // health_infra
    (0.50, 0.04),   // profile_state
    (0.385, 0.95),  // ambient_sensor
    (0.50, 0.93),   // voice_session
    (0.115, 0.84),  // system_state
];

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
struct JfaParams {
    step_size: i32,
    width: u32,
    height: u32,
    seed_count: u32,
}

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
struct ColorParams {
    width: u32,
    height: u32,
    seed_count: u32,
    edge_width: f32,
}

pub struct VoronoiTechnique {
    jfa_pipeline: wgpu::ComputePipeline,
    color_pipeline: wgpu::ComputePipeline,
    jfa_textures: [wgpu::Texture; 2],
    jfa_views: [wgpu::TextureView; 2],
    color_texture: wgpu::Texture,
    pub color_view: wgpu::TextureView,
    jfa_uniform_buf: wgpu::Buffer,
    color_uniform_buf: wgpu::Buffer,
    jfa_bgl: wgpu::BindGroupLayout,
    color_bgl: wgpu::BindGroupLayout,
    width: u32,
    height: u32,
    needs_reseed: bool,
}

impl VoronoiTechnique {
    pub fn new(gpu: &GpuContext, width: u32, height: u32) -> Self {
        let jfa_shader = gpu.device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("voronoi_jfa.wgsl"),
            source: wgpu::ShaderSource::Wgsl(include_str!("../shaders/voronoi_jfa.wgsl").into()),
        });
        let color_shader = gpu.device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("voronoi_color.wgsl"),
            source: wgpu::ShaderSource::Wgsl(include_str!("../shaders/voronoi_color.wgsl").into()),
        });

        let jfa_uniform_buf = gpu.device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("jfa params"),
            contents: bytemuck::bytes_of(&JfaParams {
                step_size: 1,
                width,
                height,
                seed_count: ZONE_CENTERS.len() as u32,
            }),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });

        let color_uniform_buf = gpu.device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("voronoi color params"),
            contents: bytemuck::bytes_of(&ColorParams {
                width,
                height,
                seed_count: ZONE_CENTERS.len() as u32,
                edge_width: 8.0,
            }),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });

        // JFA bind group layout
        let jfa_bgl = gpu.device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("jfa bgl"),
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
                        format: wgpu::TextureFormat::Rg32Float,
                        view_dimension: wgpu::TextureViewDimension::D2,
                    },
                    count: None,
                },
            ],
        });

        // Color bind group layout
        let color_bgl = gpu.device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("voronoi color bgl"),
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

        let jfa_pipeline_layout = gpu.device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("jfa pl"),
            bind_group_layouts: &[&jfa_bgl],
            push_constant_ranges: &[],
        });
        let color_pipeline_layout = gpu.device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("voronoi color pl"),
            bind_group_layouts: &[&color_bgl],
            push_constant_ranges: &[],
        });

        let jfa_pipeline = gpu.device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("jfa pipeline"),
            layout: Some(&jfa_pipeline_layout),
            module: &jfa_shader,
            entry_point: Some("main"),
            compilation_options: Default::default(),
            cache: None,
        });
        let color_pipeline = gpu.device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("voronoi color pipeline"),
            layout: Some(&color_pipeline_layout),
            module: &color_shader,
            entry_point: Some("main"),
            compilation_options: Default::default(),
            cache: None,
        });

        let (jfa_textures, jfa_views, color_texture, color_view) =
            Self::create_textures(&gpu.device, width, height);

        let mut tech = Self {
            jfa_pipeline,
            color_pipeline,
            jfa_textures,
            jfa_views,
            color_texture,
            color_view,
            jfa_uniform_buf,
            color_uniform_buf,
            jfa_bgl,
            color_bgl,
            width,
            height,
            needs_reseed: true,
        };

        tech.seed(&gpu.queue);
        tech
    }

    fn create_textures(
        device: &wgpu::Device,
        width: u32,
        height: u32,
    ) -> (
        [wgpu::Texture; 2],
        [wgpu::TextureView; 2],
        wgpu::Texture,
        wgpu::TextureView,
    ) {
        let jfa_desc = wgpu::TextureDescriptor {
            label: Some("jfa texture"),
            size: wgpu::Extent3d { width, height, depth_or_array_layers: 1 },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rg32Float,
            usage: wgpu::TextureUsages::TEXTURE_BINDING
                | wgpu::TextureUsages::STORAGE_BINDING
                | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        };
        let t0 = device.create_texture(&jfa_desc);
        let t1 = device.create_texture(&jfa_desc);
        let v0 = t0.create_view(&Default::default());
        let v1 = t1.create_view(&Default::default());

        let color_tex = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("voronoi color"),
            size: wgpu::Extent3d { width, height, depth_or_array_layers: 1 },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8Unorm,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::STORAGE_BINDING,
            view_formats: &[],
        });
        let color_view = color_tex.create_view(&Default::default());

        ([t0, t1], [v0, v1], color_tex, color_view)
    }

    fn seed(&mut self, queue: &wgpu::Queue) {
        // Initialize JFA texture 0 with seed positions, -1 everywhere else
        let size = (self.width * self.height) as usize;
        let mut data = vec![-1.0f32; size * 2]; // rg32float = 2 floats per texel

        for &(nx, ny) in ZONE_CENTERS {
            let px = (nx * self.width as f32) as u32;
            let py = (ny * self.height as f32) as u32;
            // Write a small cluster for robustness
            for dy in -1i32..=1 {
                for dx in -1i32..=1 {
                    let x = (px as i32 + dx).clamp(0, self.width as i32 - 1) as u32;
                    let y = (py as i32 + dy).clamp(0, self.height as i32 - 1) as u32;
                    let idx = ((y * self.width + x) * 2) as usize;
                    data[idx] = px as f32;
                    data[idx + 1] = py as f32;
                }
            }
        }

        queue.write_texture(
            wgpu::TexelCopyTextureInfo {
                texture: &self.jfa_textures[0],
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            bytemuck::cast_slice(&data),
            wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(self.width * 8), // 2 × f32 = 8 bytes
                rows_per_image: Some(self.height),
            },
            wgpu::Extent3d {
                width: self.width,
                height: self.height,
                depth_or_array_layers: 1,
            },
        );

        self.needs_reseed = false;
    }

    /// Run JFA passes + color pass. Call once per frame (Voronoi is static until seeds move).
    pub fn compute(&self, encoder: &mut wgpu::CommandEncoder, gpu: &GpuContext) {
        let wg_x = (self.width + 7) / 8;
        let wg_y = (self.height + 7) / 8;

        // JFA passes: step_size = max_dim/2, max_dim/4, ..., 1
        let max_dim = self.width.max(self.height);
        let mut step = (max_dim / 2).next_power_of_two() as i32;
        let mut ping = 0usize;

        while step >= 1 {
            // Update step_size uniform
            let params = JfaParams {
                step_size: step,
                width: self.width,
                height: self.height,
                seed_count: ZONE_CENTERS.len() as u32,
            };
            gpu.queue.write_buffer(&self.jfa_uniform_buf, 0, bytemuck::bytes_of(&params));

            let bg = gpu.device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some("jfa step bg"),
                layout: &self.jfa_bgl,
                entries: &[
                    wgpu::BindGroupEntry {
                        binding: 0,
                        resource: self.jfa_uniform_buf.as_entire_binding(),
                    },
                    wgpu::BindGroupEntry {
                        binding: 1,
                        resource: wgpu::BindingResource::TextureView(&self.jfa_views[ping]),
                    },
                    wgpu::BindGroupEntry {
                        binding: 2,
                        resource: wgpu::BindingResource::TextureView(&self.jfa_views[1 - ping]),
                    },
                ],
            });

            let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
                label: Some("jfa pass"),
                ..Default::default()
            });
            pass.set_pipeline(&self.jfa_pipeline);
            pass.set_bind_group(0, &bg, &[]);
            pass.dispatch_workgroups(wg_x, wg_y, 1);
            drop(pass);

            ping = 1 - ping;
            step /= 2;
        }

        // Color pass: read final JFA result, write colored cells
        let color_bg = gpu.device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("voronoi color bg"),
            layout: &self.color_bgl,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: self.color_uniform_buf.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::TextureView(&self.jfa_views[ping]),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: wgpu::BindingResource::TextureView(&self.color_view),
                },
            ],
        });

        let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
            label: Some("voronoi color pass"),
            ..Default::default()
        });
        pass.set_pipeline(&self.color_pipeline);
        pass.set_bind_group(0, &color_bg, &[]);
        pass.dispatch_workgroups(wg_x, wg_y, 1);
    }

    pub fn resize(&mut self, gpu: &GpuContext, width: u32, height: u32) {
        self.width = width;
        self.height = height;
        let (jfa_textures, jfa_views, color_texture, color_view) =
            Self::create_textures(&gpu.device, width, height);
        self.jfa_textures = jfa_textures;
        self.jfa_views = jfa_views;
        self.color_texture = color_texture;
        self.color_view = color_view;
        self.seed(&gpu.queue);
    }
}
