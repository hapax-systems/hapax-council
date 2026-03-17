use bytemuck::{Pod, Zeroable};
use wgpu::util::DeviceExt;

use crate::visual::gpu::GpuContext;
use crate::visual::state::SmoothedParams;

const AGENT_COUNT: u32 = 5_000_000;

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
struct AgentParams {
    width: u32,
    height: u32,
    agent_count: u32,
    sensor_angle: f32,
    sensor_dist: f32,
    turn_speed: f32,
    move_speed: f32,
    deposit_amount: f32,
    time: f32,
    _pad0: u32,
    _pad1: u32,
    _pad2: u32,
}

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
struct TrailParams {
    width: u32,
    height: u32,
    decay_rate: f32,
    _pad: u32,
}

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
struct Agent {
    x: f32,
    y: f32,
    angle: f32,
    _pad: f32,
}

pub struct PhysarumTechnique {
    agent_pipeline: wgpu::ComputePipeline,
    trail_pipeline: wgpu::ComputePipeline,
    agent_buffer: wgpu::Buffer,
    agent_params_buf: wgpu::Buffer,
    trail_params_buf: wgpu::Buffer,
    // Two trail textures: one for reading (trail_map), one for writing deposits,
    // then blur+decay writes to trail_out which becomes next frame's trail_map.
    trail_textures: [wgpu::Texture; 2],
    trail_views: [wgpu::TextureView; 2],
    agent_bgl: wgpu::BindGroupLayout,
    trail_bgl: wgpu::BindGroupLayout,
    width: u32,
    height: u32,
    ping: usize,
}

impl PhysarumTechnique {
    pub fn new(gpu: &GpuContext, width: u32, height: u32) -> Self {
        let agent_shader = gpu.device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("physarum_agents.wgsl"),
            source: wgpu::ShaderSource::Wgsl(include_str!("../shaders/physarum_agents.wgsl").into()),
        });
        let trail_shader = gpu.device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("physarum_trail.wgsl"),
            source: wgpu::ShaderSource::Wgsl(include_str!("../shaders/physarum_trail.wgsl").into()),
        });

        let agent_params_buf = gpu.device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("physarum agent params"),
            contents: bytemuck::bytes_of(&AgentParams {
                width,
                height,
                agent_count: AGENT_COUNT,
                sensor_angle: 0.3927,
                sensor_dist: 9.0,
                turn_speed: 0.3,
                move_speed: 1.0,
                deposit_amount: 5.0,
                time: 0.0,
                _pad0: 0,
                _pad1: 0,
                _pad2: 0,
            }),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });

        let trail_params_buf = gpu.device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("physarum trail params"),
            contents: bytemuck::bytes_of(&TrailParams {
                width,
                height,
                decay_rate: 0.02,
                _pad: 0,
            }),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });

        // Agent storage buffer
        let agents = Self::init_agents(width, height);
        let agent_buffer = gpu.device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("physarum agents"),
            contents: bytemuck::cast_slice(&agents),
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
        });

        // Trail textures (R32Float)
        let (trail_textures, trail_views) = Self::create_trail_textures(&gpu.device, width, height);

        // Agent bind group layout
        let agent_bgl = gpu.device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("physarum agent bgl"),
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
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Storage { read_only: false },
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
                // trail_map (read texture)
                wgpu::BindGroupLayoutEntry {
                    binding: 2,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Float { filterable: false },
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    },
                    count: None,
                },
                // deposit_map (storage texture read_write)
                wgpu::BindGroupLayoutEntry {
                    binding: 3,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::StorageTexture {
                        access: wgpu::StorageTextureAccess::ReadWrite,
                        format: wgpu::TextureFormat::R32Float,
                        view_dimension: wgpu::TextureViewDimension::D2,
                    },
                    count: None,
                },
            ],
        });

        // Trail blur bind group layout
        let trail_bgl = gpu.device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("physarum trail bgl"),
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
                        format: wgpu::TextureFormat::R32Float,
                        view_dimension: wgpu::TextureViewDimension::D2,
                    },
                    count: None,
                },
            ],
        });

        let agent_pl = gpu.device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("physarum agent pl"),
            bind_group_layouts: &[&agent_bgl],
            push_constant_ranges: &[],
        });
        let trail_pl = gpu.device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("physarum trail pl"),
            bind_group_layouts: &[&trail_bgl],
            push_constant_ranges: &[],
        });

        let agent_pipeline = gpu.device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("physarum agent pipeline"),
            layout: Some(&agent_pl),
            module: &agent_shader,
            entry_point: Some("main"),
            compilation_options: Default::default(),
            cache: None,
        });
        let trail_pipeline = gpu.device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("physarum trail pipeline"),
            layout: Some(&trail_pl),
            module: &trail_shader,
            entry_point: Some("main"),
            compilation_options: Default::default(),
            cache: None,
        });

        Self {
            agent_pipeline,
            trail_pipeline,
            agent_buffer,
            agent_params_buf,
            trail_params_buf,
            trail_textures,
            trail_views,
            agent_bgl,
            trail_bgl,
            width,
            height,
            ping: 0,
        }
    }

    fn init_agents(width: u32, height: u32) -> Vec<Agent> {
        // Initialize agents along paths between organ positions
        let organs: &[(f32, f32)] = &[
            (0.135, 0.09),
            (0.865, 0.09),
            (0.10, 0.425),
            (0.885, 0.87),
            (0.50, 0.04),
            (0.385, 0.95),
            (0.50, 0.93),
            (0.115, 0.84),
        ];

        let mut agents = Vec::with_capacity(AGENT_COUNT as usize);
        let mut rng_state = 42u32;

        for i in 0..AGENT_COUNT {
            // Simple LCG for deterministic initialization
            rng_state = rng_state.wrapping_mul(1664525).wrapping_add(1013904223);
            let r1 = (rng_state >> 16) as f32 / 65535.0;
            rng_state = rng_state.wrapping_mul(1664525).wrapping_add(1013904223);
            let r2 = (rng_state >> 16) as f32 / 65535.0;
            rng_state = rng_state.wrapping_mul(1664525).wrapping_add(1013904223);
            let r3 = (rng_state >> 16) as f32 / 65535.0;

            // Pick two random organs and lerp between them
            let o1 = (i as usize) % organs.len();
            let o2 = ((i as usize) + 1 + (rng_state as usize >> 20) % 3) % organs.len();
            let t = r1;
            let x = (organs[o1].0 * (1.0 - t) + organs[o2].0 * t) * width as f32
                + (r2 - 0.5) * 60.0; // jitter
            let y = (organs[o1].1 * (1.0 - t) + organs[o2].1 * t) * height as f32
                + (r3 - 0.5) * 60.0;

            rng_state = rng_state.wrapping_mul(1664525).wrapping_add(1013904223);
            let angle = (rng_state >> 16) as f32 / 65535.0 * std::f32::consts::TAU;

            agents.push(Agent {
                x: x.clamp(0.0, width as f32 - 1.0),
                y: y.clamp(0.0, height as f32 - 1.0),
                angle,
                _pad: 0.0,
            });
        }
        agents
    }

    fn create_trail_textures(device: &wgpu::Device, width: u32, height: u32) -> ([wgpu::Texture; 2], [wgpu::TextureView; 2]) {
        let desc = wgpu::TextureDescriptor {
            label: Some("physarum trail"),
            size: wgpu::Extent3d { width, height, depth_or_array_layers: 1 },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::R32Float,
            usage: wgpu::TextureUsages::TEXTURE_BINDING
                | wgpu::TextureUsages::STORAGE_BINDING
                | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        };
        let t0 = device.create_texture(&desc);
        let t1 = device.create_texture(&desc);
        let v0 = t0.create_view(&Default::default());
        let v1 = t1.create_view(&Default::default());
        ([t0, t1], [v0, v1])
    }

    pub fn update_params(&self, queue: &wgpu::Queue, params: &SmoothedParams, time: f32) {
        let agent_params = AgentParams {
            width: self.width,
            height: self.height,
            agent_count: AGENT_COUNT,
            sensor_angle: 0.3927 + params.turbulence * 0.2,
            sensor_dist: 9.0,
            turn_speed: 0.3,
            move_speed: params.speed * 12.5, // 0.08 → 1.0
            deposit_amount: 5.0,
            time,
            _pad0: 0,
            _pad1: 0,
            _pad2: 0,
        };
        queue.write_buffer(&self.agent_params_buf, 0, bytemuck::bytes_of(&agent_params));

        let trail_params = TrailParams {
            width: self.width,
            height: self.height,
            decay_rate: 0.01 + (1.0 - params.brightness) * 0.04, // brighter → less decay
            _pad: 0,
        };
        queue.write_buffer(&self.trail_params_buf, 0, bytemuck::bytes_of(&trail_params));
    }

    pub fn step(&self, encoder: &mut wgpu::CommandEncoder, gpu: &GpuContext) {
        let read_idx = self.ping;
        let write_idx = 1 - self.ping;

        // Pass 1: Agent step — read trail_map[read], write deposits to trail[write]
        // First copy trail[read] to trail[write] so deposits accumulate on existing trails
        encoder.copy_texture_to_texture(
            wgpu::TexelCopyTextureInfo {
                texture: &self.trail_textures[read_idx],
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::TexelCopyTextureInfo {
                texture: &self.trail_textures[write_idx],
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

        let agent_bg = gpu.device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("physarum agent bg"),
            layout: &self.agent_bgl,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: self.agent_params_buf.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: self.agent_buffer.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: wgpu::BindingResource::TextureView(&self.trail_views[read_idx]),
                },
                wgpu::BindGroupEntry {
                    binding: 3,
                    resource: wgpu::BindingResource::TextureView(&self.trail_views[write_idx]),
                },
            ],
        });

        {
            let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
                label: Some("physarum agents"),
                ..Default::default()
            });
            pass.set_pipeline(&self.agent_pipeline);
            pass.set_bind_group(0, &agent_bg, &[]);
            pass.dispatch_workgroups((AGENT_COUNT + 255) / 256, 1, 1);
        }

        // Pass 2: Trail blur+decay — read trail[write] (with deposits), write to trail[read]
        let trail_bg = gpu.device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("physarum trail bg"),
            layout: &self.trail_bgl,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: self.trail_params_buf.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::TextureView(&self.trail_views[write_idx]),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: wgpu::BindingResource::TextureView(&self.trail_views[read_idx]),
                },
            ],
        });

        {
            let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
                label: Some("physarum trail blur"),
                ..Default::default()
            });
            pass.set_pipeline(&self.trail_pipeline);
            pass.set_bind_group(0, &trail_bg, &[]);
            pass.dispatch_workgroups((self.width + 7) / 8, (self.height + 7) / 8, 1);
        }

        // After blur, trail[read_idx] has the final result.
        // ping stays the same — read_idx is always the "clean" output.
    }

    /// Output view for the compositor (the trail map after blur+decay).
    pub fn output_view(&self) -> &wgpu::TextureView {
        &self.trail_views[self.ping]
    }

    pub fn resize(&mut self, gpu: &GpuContext, width: u32, height: u32) {
        self.width = width;
        self.height = height;
        let (textures, views) = Self::create_trail_textures(&gpu.device, width, height);
        self.trail_textures = textures;
        self.trail_views = views;

        // Re-init agents
        let agents = Self::init_agents(width, height);
        gpu.queue.write_buffer(&self.agent_buffer, 0, bytemuck::cast_slice(&agents));
    }
}
