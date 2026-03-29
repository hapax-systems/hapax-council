use bytemuck::{Pod, Zeroable};
use wgpu::util::DeviceExt;

use crate::gpu::GpuContext;
use crate::state::{SmoothedParams, Stance};

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
struct RDParams {
    f: f32,
    k: f32,
    du: f32,
    dv: f32,
    dt: f32,
    width: u32,
    height: u32,
    _pad: u32,
}

pub struct ReactionDiffTechnique {
    pipeline: wgpu::ComputePipeline,
    textures: [wgpu::Texture; 2],
    views: [wgpu::TextureView; 2],
    bind_groups: [wgpu::BindGroup; 2],
    uniform_buf: wgpu::Buffer,
    bind_group_layout: wgpu::BindGroupLayout,
    width: u32,
    height: u32,
    ping: usize, // current read texture index
    /// Smoothed F/k parameters for lerping between stances
    current_f: f32,
    current_k: f32,
}

impl ReactionDiffTechnique {
    pub fn new(gpu: &GpuContext, width: u32, height: u32) -> Self {
        let shader = gpu
            .device
            .create_shader_module(wgpu::ShaderModuleDescriptor {
                label: Some("reaction_diff.wgsl"),
                source: wgpu::ShaderSource::Wgsl(
                    include_str!("../shaders/reaction_diff.wgsl").into(),
                ),
            });

        let uniform_buf = gpu.device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("rd params"),
            contents: bytemuck::bytes_of(&RDParams {
                f: 0.037,
                k: 0.062,
                du: 0.2097,
                dv: 0.105,
                dt: 1.0,
                width,
                height,
                _pad: 0,
            }),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });

        let bind_group_layout =
            gpu.device
                .create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                    label: Some("rd bgl"),
                    entries: &[
                        // Uniform params
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
                        // Source texture (read)
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
                        // Dest texture (write)
                        wgpu::BindGroupLayoutEntry {
                            binding: 2,
                            visibility: wgpu::ShaderStages::COMPUTE,
                            ty: wgpu::BindingType::StorageTexture {
                                access: wgpu::StorageTextureAccess::WriteOnly,
                                format: wgpu::TextureFormat::Rgba16Float,
                                view_dimension: wgpu::TextureViewDimension::D2,
                            },
                            count: None,
                        },
                    ],
                });

        let pipeline_layout =
            gpu.device
                .create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
                    label: Some("rd pipeline layout"),
                    bind_group_layouts: &[&bind_group_layout],
                    push_constant_ranges: &[],
                });

        let pipeline = gpu
            .device
            .create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
                label: Some("rd pipeline"),
                layout: Some(&pipeline_layout),
                module: &shader,
                entry_point: Some("main"),
                compilation_options: Default::default(),
                cache: None,
            });

        let textures = Self::create_textures(&gpu.device, width, height);
        let views = [
            textures[0].create_view(&Default::default()),
            textures[1].create_view(&Default::default()),
        ];

        let bind_groups = Self::create_bind_groups(
            &gpu.device,
            &bind_group_layout,
            &uniform_buf,
            &views,
        );

        // Initialize with seed pattern
        Self::seed_texture(&gpu.queue, &textures[0], width, height);

        Self {
            pipeline,
            textures,
            views,
            bind_groups,
            uniform_buf,
            bind_group_layout,
            width,
            height,
            ping: 0,
            current_f: 0.037,
            current_k: 0.062,
        }
    }

    fn create_textures(device: &wgpu::Device, width: u32, height: u32) -> [wgpu::Texture; 2] {
        let desc = wgpu::TextureDescriptor {
            label: Some("rd texture"),
            size: wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba16Float,
            usage: wgpu::TextureUsages::TEXTURE_BINDING
                | wgpu::TextureUsages::STORAGE_BINDING
                | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        };
        [device.create_texture(&desc), device.create_texture(&desc)]
    }

    fn create_bind_groups(
        device: &wgpu::Device,
        layout: &wgpu::BindGroupLayout,
        uniform_buf: &wgpu::Buffer,
        views: &[wgpu::TextureView; 2],
    ) -> [wgpu::BindGroup; 2] {
        // bg[0]: read tex[0], write tex[1]
        // bg[1]: read tex[1], write tex[0]
        [
            device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some("rd bg 0"),
                layout,
                entries: &[
                    wgpu::BindGroupEntry {
                        binding: 0,
                        resource: uniform_buf.as_entire_binding(),
                    },
                    wgpu::BindGroupEntry {
                        binding: 1,
                        resource: wgpu::BindingResource::TextureView(&views[0]),
                    },
                    wgpu::BindGroupEntry {
                        binding: 2,
                        resource: wgpu::BindingResource::TextureView(&views[1]),
                    },
                ],
            }),
            device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some("rd bg 1"),
                layout,
                entries: &[
                    wgpu::BindGroupEntry {
                        binding: 0,
                        resource: uniform_buf.as_entire_binding(),
                    },
                    wgpu::BindGroupEntry {
                        binding: 1,
                        resource: wgpu::BindingResource::TextureView(&views[1]),
                    },
                    wgpu::BindGroupEntry {
                        binding: 2,
                        resource: wgpu::BindingResource::TextureView(&views[0]),
                    },
                ],
            }),
        ]
    }

    fn seed_texture(queue: &wgpu::Queue, texture: &wgpu::Texture, width: u32, height: u32) {
        // Initialize: U=1.0, V=0.0 everywhere, with scattered V=1.0 seed squares
        let size = (width * height) as usize;
        let mut data = vec![[1.0f32, 0.0f32, 0.0f32, 1.0f32]; size];

        // Seed: several small squares of V=1.0 scattered across the canvas
        let seeds = [
            (0.3, 0.3),
            (0.5, 0.5),
            (0.7, 0.4),
            (0.4, 0.7),
            (0.6, 0.6),
            (0.2, 0.6),
            (0.8, 0.3),
            (0.5, 0.2),
            (0.3, 0.8),
        ];
        let seed_radius = 8i32;
        for (sx, sy) in seeds {
            let cx = (sx * width as f32) as i32;
            let cy = (sy * height as f32) as i32;
            for dy in -seed_radius..=seed_radius {
                for dx in -seed_radius..=seed_radius {
                    let x = (cx + dx).clamp(0, width as i32 - 1) as u32;
                    let y = (cy + dy).clamp(0, height as i32 - 1) as u32;
                    let idx = (y * width + x) as usize;
                    data[idx] = [1.0, 1.0, 0.0, 1.0]; // U=1, V=1
                }
            }
        }

        // Convert to half-float (Rgba16Float) — we need to write as bytes
        // Actually, we can write f32 data and let wgpu handle the conversion
        // if we use write_texture with the right bytes_per_row.
        // Rgba16Float = 8 bytes per pixel. We need to convert f32 → f16.
        // Simpler: use a staging approach with Rgba32Float and copy, but our texture is Rgba16Float.
        // Let's just use half crate... or write raw f16 bytes.
        // For simplicity, let's convert manually.
        let mut f16_data: Vec<u8> = Vec::with_capacity(size * 8);
        for pixel in &data {
            for &val in pixel {
                let half = f32_to_f16(val);
                f16_data.extend_from_slice(&half.to_le_bytes());
            }
        }

        queue.write_texture(
            wgpu::TexelCopyTextureInfo {
                texture,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            &f16_data,
            wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(width * 8), // 4 channels × 2 bytes
                rows_per_image: Some(height),
            },
            wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
        );
    }

    /// Get the current output texture view (for compositor sampling).
    pub fn output_view(&self) -> &wgpu::TextureView {
        // After N steps, the result is in textures[ping ^ 1] if N is odd,
        // or textures[ping] if N is even. We track ping to point at the latest output.
        &self.views[self.ping]
    }

    /// Update F/k parameters based on stance, with smoothing.
    pub fn update_params(&mut self, queue: &wgpu::Queue, params: &SmoothedParams, dt: f32) {
        let (target_f, target_k) = match params.stance {
            Stance::Nominal => (0.037, 0.062),
            Stance::Cautious => (0.032, 0.058),
            Stance::Degraded => (0.025, 0.052),
            Stance::Critical => (0.015, 0.048),
        };

        let alpha = 1.0 - (-dt / 2.0_f32).exp();
        self.current_f += (target_f - self.current_f) * alpha;
        self.current_k += (target_k - self.current_k) * alpha;

        let rd_params = RDParams {
            f: self.current_f,
            k: self.current_k,
            du: 0.2097,
            dv: 0.105,
            dt: 1.0,
            width: self.width,
            height: self.height,
            _pad: 0,
        };
        queue.write_buffer(&self.uniform_buf, 0, bytemuck::bytes_of(&rd_params));
    }

    /// Run N compute steps per frame, ping-ponging textures.
    pub fn step(&mut self, encoder: &mut wgpu::CommandEncoder, steps: u32) {
        for _ in 0..steps {
            let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
                label: Some("rd step"),
                ..Default::default()
            });
            pass.set_pipeline(&self.pipeline);
            pass.set_bind_group(0, &self.bind_groups[self.ping], &[]);
            pass.dispatch_workgroups(
                (self.width + 7) / 8,
                (self.height + 7) / 8,
                1,
            );
            drop(pass);
            self.ping = 1 - self.ping;
        }
    }

    pub fn current_f(&self) -> f32 {
        self.current_f
    }

    pub fn resize(&mut self, gpu: &GpuContext, width: u32, height: u32) {
        self.width = width;
        self.height = height;
        self.textures = Self::create_textures(&gpu.device, width, height);
        self.views = [
            self.textures[0].create_view(&Default::default()),
            self.textures[1].create_view(&Default::default()),
        ];
        self.bind_groups = Self::create_bind_groups(
            &gpu.device,
            &self.bind_group_layout,
            &self.uniform_buf,
            &self.views,
        );
        Self::seed_texture(&gpu.queue, &self.textures[0], width, height);
        self.ping = 0;
    }
}

/// Convert f32 to IEEE 754 half-precision (f16).
fn f32_to_f16(val: f32) -> u16 {
    let bits = val.to_bits();
    let sign = (bits >> 16) & 0x8000;
    let exp = ((bits >> 23) & 0xFF) as i32 - 127 + 15;
    let frac = bits & 0x007FFFFF;

    if exp <= 0 {
        if exp < -10 {
            return sign as u16;
        }
        let frac = (frac | 0x00800000) >> (1 - exp);
        return (sign | (frac >> 13)) as u16;
    } else if exp >= 31 {
        return (sign | 0x7C00) as u16; // infinity
    }
    (sign | ((exp as u32) << 10) | (frac >> 13)) as u16
}
