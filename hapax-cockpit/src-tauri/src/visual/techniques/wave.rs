use bytemuck::{Pod, Zeroable};
use wgpu::util::DeviceExt;

use crate::visual::gpu::GpuContext;


#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
struct WaveParams {
    c_sq: f32,
    damping: f32,
    width: u32,
    height: u32,
}

/// Pending wave event to inject energy at a position.
pub struct WaveEvent {
    pub x: f32, // normalized 0-1
    pub y: f32,
    pub amplitude: f32,
    pub radius: u32,
}

pub struct WaveTechnique {
    pipeline: wgpu::ComputePipeline,
    textures: [wgpu::Texture; 3], // prev, curr, next — rotate each frame
    views: [wgpu::TextureView; 3],
    uniform_buf: wgpu::Buffer,
    bgl: wgpu::BindGroupLayout,
    width: u32,
    height: u32,
    phase: usize, // which texture is "prev" (0, 1, or 2)
    pending_events: Vec<WaveEvent>,
}

impl WaveTechnique {
    pub fn new(gpu: &GpuContext, width: u32, height: u32) -> Self {
        let shader = gpu.device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("wave.wgsl"),
            source: wgpu::ShaderSource::Wgsl(include_str!("../shaders/wave.wgsl").into()),
        });

        let uniform_buf = gpu.device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("wave params"),
            contents: bytemuck::bytes_of(&WaveParams {
                c_sq: 16.0,
                damping: 0.15,
                width,
                height,
            }),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });

        let bgl = gpu.device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("wave bgl"),
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
                // prev
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
                // curr
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
                // next (write)
                wgpu::BindGroupLayoutEntry {
                    binding: 3,
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

        let pl = gpu.device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("wave pl"),
            bind_group_layouts: &[&bgl],
            push_constant_ranges: &[],
        });

        let pipeline = gpu.device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("wave pipeline"),
            layout: Some(&pl),
            module: &shader,
            entry_point: Some("main"),
            compilation_options: Default::default(),
            cache: None,
        });

        let (textures, views) = Self::create_textures(&gpu.device, width, height);

        Self {
            pipeline,
            textures,
            views,
            uniform_buf,
            bgl,
            width,
            height,
            phase: 0,
            pending_events: Vec::new(),
        }
    }

    fn create_textures(device: &wgpu::Device, width: u32, height: u32) -> ([wgpu::Texture; 3], [wgpu::TextureView; 3]) {
        let desc = wgpu::TextureDescriptor {
            label: Some("wave tex"),
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
        let t = [
            device.create_texture(&desc),
            device.create_texture(&desc),
            device.create_texture(&desc),
        ];
        let v = [
            t[0].create_view(&Default::default()),
            t[1].create_view(&Default::default()),
            t[2].create_view(&Default::default()),
        ];
        (t, v)
    }

    /// Inject a wave event (called from main loop when signals change).
    pub fn inject_event(&mut self, event: WaveEvent) {
        self.pending_events.push(event);
    }

    /// Flush pending events by writing energy into the current texture.
    pub fn flush_events(&mut self, queue: &wgpu::Queue) {
        if self.pending_events.is_empty() {
            return;
        }

        // Read-modify-write is expensive on GPU textures. For simplicity,
        // we'll write small patches of energy. This overwrites existing values
        // in the patch area, which is acceptable for visual purposes.
        let curr_idx = (self.phase + 1) % 3;

        for event in self.pending_events.drain(..) {
            let cx = (event.x * self.width as f32) as i32;
            let cy = (event.y * self.height as f32) as i32;
            let r = event.radius as i32;


            let x0 = (cx - r).max(0) as u32;
            let y0 = (cy - r).max(0) as u32;
            let x1 = ((cx + r + 1) as u32).min(self.width);
            let y1 = ((cy + r + 1) as u32).min(self.height);
            let pw = x1 - x0;
            let ph = y1 - y0;

            if pw == 0 || ph == 0 {
                continue;
            }

            let mut data = vec![0.0f32; (pw * ph) as usize];
            for py in 0..ph {
                for px in 0..pw {
                    let dx = (x0 + px) as f32 - cx as f32;
                    let dy = (y0 + py) as f32 - cy as f32;
                    let dist = (dx * dx + dy * dy).sqrt() / r as f32;
                    if dist <= 1.0 {
                        let falloff = 1.0 - dist * dist; // quadratic falloff
                        data[(py * pw + px) as usize] = event.amplitude * falloff;
                    }
                }
            }

            queue.write_texture(
                wgpu::TexelCopyTextureInfo {
                    texture: &self.textures[curr_idx],
                    mip_level: 0,
                    origin: wgpu::Origin3d { x: x0, y: y0, z: 0 },
                    aspect: wgpu::TextureAspect::All,
                },
                bytemuck::cast_slice(&data),
                wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(pw * 4),
                    rows_per_image: Some(ph),
                },
                wgpu::Extent3d { width: pw, height: ph, depth_or_array_layers: 1 },
            );
        }
    }

    /// Run one wave simulation step.
    pub fn step(&mut self, encoder: &mut wgpu::CommandEncoder, gpu: &GpuContext) {
        let prev_idx = self.phase;
        let curr_idx = (self.phase + 1) % 3;
        let next_idx = (self.phase + 2) % 3;

        let bg = gpu.device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("wave step bg"),
            layout: &self.bgl,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: self.uniform_buf.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::TextureView(&self.views[prev_idx]),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: wgpu::BindingResource::TextureView(&self.views[curr_idx]),
                },
                wgpu::BindGroupEntry {
                    binding: 3,
                    resource: wgpu::BindingResource::TextureView(&self.views[next_idx]),
                },
            ],
        });

        let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
            label: Some("wave step"),
            ..Default::default()
        });
        pass.set_pipeline(&self.pipeline);
        pass.set_bind_group(0, &bg, &[]);
        pass.dispatch_workgroups((self.width + 7) / 8, (self.height + 7) / 8, 1);
        drop(pass);

        // Rotate: next becomes curr for the next frame
        self.phase = (self.phase + 1) % 3;
    }

    /// Get the current output texture view (the "curr" after stepping).
    pub fn output_view(&self) -> &wgpu::TextureView {
        let curr_idx = (self.phase + 1) % 3;
        &self.views[curr_idx]
    }

    pub fn resize(&mut self, gpu: &GpuContext, width: u32, height: u32) {
        self.width = width;
        self.height = height;
        let (textures, views) = Self::create_textures(&gpu.device, width, height);
        self.textures = textures;
        self.views = views;
        self.phase = 0;
    }
}
