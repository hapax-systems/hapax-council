use std::collections::HashMap;
use std::path::Path;

use bytemuck::{Pod, Zeroable};
use wgpu::util::DeviceExt;

use crate::compositor::COMPOSITE_FORMAT;
use crate::gpu::GpuContext;

const MAX_SLOTS: usize = 4;

// --- Per-slot fade state ---

#[derive(Debug, Clone)]
struct SlotState {
    active: bool,
    opacity: f32,
    target_opacity: f32,
    fade_rate: f32, // per second
    source: String,
}

impl Default for SlotState {
    fn default() -> Self {
        Self {
            active: false,
            opacity: 0.0,
            target_opacity: 0.0,
            fade_rate: 2.0,
            source: String::new(),
        }
    }
}

// --- GPU uniform struct (must match WGSL) ---

#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
struct ContentUniforms {
    slot_opacities: [f32; 4],
    // 9 dimensions
    intensity: f32,
    tension: f32,
    depth: f32,
    coherence: f32,
    spectral_color: f32,
    temporal_distortion: f32,
    degradation: f32,
    pitch_displacement: f32,
    formant_character: f32,
    // time + padding
    time: f32,
    _pad0: f32,
    _pad1: f32,
}

impl Default for ContentUniforms {
    fn default() -> Self {
        Self {
            slot_opacities: [0.0; 4],
            intensity: 0.0,
            tension: 0.0,
            depth: 0.0,
            coherence: 0.0,
            spectral_color: 0.0,
            temporal_distortion: 0.0,
            degradation: 0.0,
            pitch_displacement: 0.0,
            formant_character: 0.0,
            time: 0.0,
            _pad0: 0.0,
            _pad1: 0.0,
        }
    }
}

// --- JPEG decode via turbojpeg ---

fn decode_jpeg_to_rgba(path: &Path) -> Option<(Vec<u8>, u32, u32)> {
    let data = std::fs::read(path).ok()?;
    let mut decompressor = turbojpeg::Decompressor::new().ok()?;
    let header = decompressor.read_header(&data).ok()?;
    let w = header.width as u32;
    let h = header.height as u32;

    let mut pixels = vec![0u8; (w * h * 4) as usize];
    let image = turbojpeg::Image {
        pixels: pixels.as_mut_slice(),
        width: w as usize,
        height: h as usize,
        pitch: (w * 4) as usize,
        format: turbojpeg::PixelFormat::RGBA,
    };

    decompressor.decompress(&data, image).ok()?;
    Some((pixels, w, h))
}

// --- Content layer ---

pub struct ContentLayer {
    pipeline: wgpu::RenderPipeline,
    uniform_buf: wgpu::Buffer,
    bind_group_layout: wgpu::BindGroupLayout,
    sampler: wgpu::Sampler,
    slots: [SlotState; MAX_SLOTS],
    slot_textures: [wgpu::Texture; MAX_SLOTS],
    slot_views: [wgpu::TextureView; MAX_SLOTS],
    placeholder_view: wgpu::TextureView,
    _placeholder_texture: wgpu::Texture,
    pub output_texture: wgpu::Texture,
    pub output_view: wgpu::TextureView,
    pub current_fragment_id: String,
    pub is_continuation: bool,
}

impl ContentLayer {
    pub fn new(gpu: &GpuContext, width: u32, height: u32) -> Self {
        let shader = gpu
            .device
            .create_shader_module(wgpu::ShaderModuleDescriptor {
                label: Some("content_layer.wgsl"),
                source: wgpu::ShaderSource::Wgsl(
                    include_str!("shaders/content_layer.wgsl").into(),
                ),
            });

        let uniform_buf = gpu.device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("content layer uniforms"),
            contents: bytemuck::bytes_of(&ContentUniforms::default()),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });

        let sampler = gpu.device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("content layer sampler"),
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            ..Default::default()
        });

        let bind_group_layout =
            gpu.device
                .create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                    label: Some("content layer bgl"),
                    entries: &[
                        // 0: uniforms
                        wgpu::BindGroupLayoutEntry {
                            binding: 0,
                            visibility: wgpu::ShaderStages::FRAGMENT,
                            ty: wgpu::BindingType::Buffer {
                                ty: wgpu::BufferBindingType::Uniform,
                                has_dynamic_offset: false,
                                min_binding_size: None,
                            },
                            count: None,
                        },
                        // 1: composite input
                        bgl_texture(1),
                        // 2-5: slot textures
                        bgl_texture(2),
                        bgl_texture(3),
                        bgl_texture(4),
                        bgl_texture(5),
                        // 6: sampler
                        wgpu::BindGroupLayoutEntry {
                            binding: 6,
                            visibility: wgpu::ShaderStages::FRAGMENT,
                            ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                            count: None,
                        },
                    ],
                });

        let pipeline_layout =
            gpu.device
                .create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
                    label: Some("content layer pipeline layout"),
                    bind_group_layouts: &[&bind_group_layout],
                    push_constant_ranges: &[],
                });

        let pipeline = gpu
            .device
            .create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                label: Some("content layer pipeline"),
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

        // 1x1 black placeholder texture
        let (placeholder_texture, placeholder_view) = create_placeholder(&gpu.device, &gpu.queue);

        // Initialize slot textures as placeholders
        let mut slot_textures: Vec<wgpu::Texture> = Vec::new();
        let mut slot_views: Vec<wgpu::TextureView> = Vec::new();
        for _ in 0..MAX_SLOTS {
            let (tex, view) = create_placeholder(&gpu.device, &gpu.queue);
            slot_textures.push(tex);
            slot_views.push(view);
        }

        let (output_texture, output_view) = create_output_texture(&gpu.device, width, height);

        Self {
            pipeline,
            uniform_buf,
            bind_group_layout,
            sampler,
            slots: Default::default(),
            slot_textures: slot_textures.try_into().unwrap_or_else(|_| unreachable!()),
            slot_views: slot_views.try_into().unwrap_or_else(|_| unreachable!()),
            placeholder_view,
            _placeholder_texture: placeholder_texture,
            output_texture,
            output_view,
            current_fragment_id: String::new(),
            is_continuation: false,
        }
    }

    /// Upload a JPEG image to a texture slot.
    pub fn upload_to_slot(
        &mut self,
        gpu: &GpuContext,
        slot: usize,
        path: &Path,
        salience: f32,
        source: &str,
    ) {
        if slot >= MAX_SLOTS {
            return;
        }
        let Some((rgba, w, h)) = decode_jpeg_to_rgba(path) else {
            log::warn!("content_layer: failed to decode JPEG {:?}", path);
            return;
        };

        let texture = gpu.device.create_texture(&wgpu::TextureDescriptor {
            label: Some("content slot texture"),
            size: wgpu::Extent3d {
                width: w,
                height: h,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8UnormSrgb,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });

        gpu.queue.write_texture(
            wgpu::TexelCopyTextureInfo {
                texture: &texture,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            &rgba,
            wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(4 * w),
                rows_per_image: Some(h),
            },
            wgpu::Extent3d {
                width: w,
                height: h,
                depth_or_array_layers: 1,
            },
        );

        let view = texture.create_view(&Default::default());
        self.slot_textures[slot] = texture;
        self.slot_views[slot] = view;

        self.slots[slot] = SlotState {
            active: true,
            opacity: 0.0,
            target_opacity: salience.clamp(0.0, 1.0),
            fade_rate: 2.0,
            source: source.to_string(),
        };
    }

    /// Begin fading out all slots.
    pub fn fade_out_all(&mut self) {
        for slot in &mut self.slots {
            slot.target_opacity = 0.0;
        }
    }

    /// Advance per-slot fade animations.
    pub fn tick_fades(&mut self, dt: f32) {
        for slot in &mut self.slots {
            if !slot.active && slot.opacity <= 0.001 {
                continue;
            }
            let diff = slot.target_opacity - slot.opacity;
            let step = slot.fade_rate * dt;
            if diff.abs() < step {
                slot.opacity = slot.target_opacity;
            } else {
                slot.opacity += diff.signum() * step;
            }
            // Deactivate fully faded-out slots
            if slot.opacity <= 0.001 && slot.target_opacity <= 0.001 {
                slot.active = false;
                slot.opacity = 0.0;
            }
        }
    }

    /// Write uniform buffer from dimensional state.
    pub fn update_uniforms(
        &self,
        queue: &wgpu::Queue,
        dimensions: &HashMap<String, f32>,
        time: f32,
    ) {
        let dim = |name: &str| *dimensions.get(name).unwrap_or(&0.0);
        let uniforms = ContentUniforms {
            slot_opacities: [
                self.slots[0].opacity,
                self.slots[1].opacity,
                self.slots[2].opacity,
                self.slots[3].opacity,
            ],
            intensity: dim("intensity"),
            tension: dim("tension"),
            depth: dim("depth"),
            coherence: dim("coherence"),
            spectral_color: dim("spectral_color"),
            temporal_distortion: dim("temporal_distortion"),
            degradation: dim("degradation"),
            pitch_displacement: dim("pitch_displacement"),
            formant_character: dim("formant_character"),
            time,
            _pad0: 0.0,
            _pad1: 0.0,
        };
        queue.write_buffer(&self.uniform_buf, 0, bytemuck::bytes_of(&uniforms));
    }

    /// Render content layer onto the composite texture.
    pub fn render(
        &self,
        encoder: &mut wgpu::CommandEncoder,
        composite_view: &wgpu::TextureView,
        device: &wgpu::Device,
    ) {
        // Build bind group each frame (slot textures may change)
        let bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("content layer bg"),
            layout: &self.bind_group_layout,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: self.uniform_buf.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::TextureView(composite_view),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: wgpu::BindingResource::TextureView(
                        if self.slots[0].active {
                            &self.slot_views[0]
                        } else {
                            &self.placeholder_view
                        },
                    ),
                },
                wgpu::BindGroupEntry {
                    binding: 3,
                    resource: wgpu::BindingResource::TextureView(
                        if self.slots[1].active {
                            &self.slot_views[1]
                        } else {
                            &self.placeholder_view
                        },
                    ),
                },
                wgpu::BindGroupEntry {
                    binding: 4,
                    resource: wgpu::BindingResource::TextureView(
                        if self.slots[2].active {
                            &self.slot_views[2]
                        } else {
                            &self.placeholder_view
                        },
                    ),
                },
                wgpu::BindGroupEntry {
                    binding: 5,
                    resource: wgpu::BindingResource::TextureView(
                        if self.slots[3].active {
                            &self.slot_views[3]
                        } else {
                            &self.placeholder_view
                        },
                    ),
                },
                wgpu::BindGroupEntry {
                    binding: 6,
                    resource: wgpu::BindingResource::Sampler(&self.sampler),
                },
            ],
        });

        // Render to our own output texture, reading from composite
        let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("content layer pass"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: &self.output_view,
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
        pass.set_bind_group(0, &bind_group, &[]);
        pass.draw(0..3, 0..1);
    }

    /// Resize the output texture on window resize.
    pub fn resize(&mut self, device: &wgpu::Device, width: u32, height: u32) {
        let (texture, view) = create_output_texture(device, width, height);
        self.output_texture = texture;
        self.output_view = view;
    }
}

// --- Helpers ---

fn bgl_texture(binding: u32) -> wgpu::BindGroupLayoutEntry {
    wgpu::BindGroupLayoutEntry {
        binding,
        visibility: wgpu::ShaderStages::FRAGMENT,
        ty: wgpu::BindingType::Texture {
            sample_type: wgpu::TextureSampleType::Float { filterable: true },
            view_dimension: wgpu::TextureViewDimension::D2,
            multisampled: false,
        },
        count: None,
    }
}

fn create_placeholder(device: &wgpu::Device, queue: &wgpu::Queue) -> (wgpu::Texture, wgpu::TextureView) {
    let texture = device.create_texture(&wgpu::TextureDescriptor {
        label: Some("content placeholder"),
        size: wgpu::Extent3d {
            width: 1,
            height: 1,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: wgpu::TextureFormat::Rgba8UnormSrgb,
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
        &[0u8, 0, 0, 255],
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

fn create_output_texture(
    device: &wgpu::Device,
    width: u32,
    height: u32,
) -> (wgpu::Texture, wgpu::TextureView) {
    let texture = device.create_texture(&wgpu::TextureDescriptor {
        label: Some("content layer output"),
        size: wgpu::Extent3d {
            width,
            height,
            depth_or_array_layers: 1,
        },
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
