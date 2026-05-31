//! screwm_media_drift — GPU media-drift service.
//!
//! Spec: docs/superpowers/specs/2026-05-30-screwm-gpu-drift-port-design.md.
//!
//! Headless wgpu on the 5060 Ti. For each configured slot: read the producer's
//! *raw* (undrifted) BGRA from `/dev/shm`, apply `media_drift.wgsl` driven by the
//! live `DriftState`, and write the *drifted* BGRA back to the slot path the
//! DarkPlaces engine blits — replacing the producers' Python numpy drift.
//!
//! Config (env `HAPAX_SCREWM_DRIFT_SLOTS`, comma list): `name:WxH[:intensity]`,
//! e.g. `ward-atlas:2048x2304,cam-brio-operator:1280x720`. Paths derive from the
//! name: in = `quake-live-<name>.raw.bgra`, out = `quake-live-<name>.bgra`.

use std::borrow::Cow;
use std::path::PathBuf;
use std::time::{Duration, Instant};

use hapax_visual::media_drift::{load_drift_state, DriftUniforms, ReceiverClass};

const SHADER_SRC: &str = include_str!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../agents/shaders/nodes/media_drift.wgsl"
));
const SHM_DIR: &str = "/dev/shm/hapax-compositor";
const TEX_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Bgra8Unorm;

fn align_up(v: u32, a: u32) -> u32 {
    (v + a - 1) & !(a - 1)
}

struct SlotConfig {
    name: String,
    raw_path: PathBuf,
    out_path: PathBuf,
    width: u32,
    height: u32,
    class: ReceiverClass,
    intensity: f32,
}

impl SlotConfig {
    /// Parse one `name:WxH[:intensity]` spec.
    fn parse(spec: &str) -> Option<Self> {
        let mut parts = spec.split(':');
        let name = parts.next()?.trim().to_string();
        if name.is_empty() {
            return None;
        }
        let (w, h) = {
            let dims = parts.next()?;
            let (ws, hs) = dims.split_once('x')?;
            (ws.trim().parse().ok()?, hs.trim().parse().ok()?)
        };
        let intensity = parts
            .next()
            .and_then(|s| s.trim().parse().ok())
            .unwrap_or(1.0);
        Some(Self {
            raw_path: PathBuf::from(format!("{SHM_DIR}/quake-live-{name}.raw.bgra")),
            out_path: PathBuf::from(format!("{SHM_DIR}/quake-live-{name}.bgra")),
            class: ReceiverClass::from_name(&name),
            name,
            width: w,
            height: h,
            intensity,
        })
    }
}

/// Per-slot GPU resources: input texture, output render target, uniform buffer,
/// bind group, and a padded readback staging buffer.
struct SlotGpu {
    cfg: SlotConfig,
    in_tex: wgpu::Texture,
    out_tex: wgpu::Texture,
    out_view: wgpu::TextureView,
    uniform: wgpu::Buffer,
    bind_group: wgpu::BindGroup,
    staging: wgpu::Buffer,
    bytes_per_row: u32,
    padded_bytes_per_row: u32,
    expected_bytes: usize,
    frame: u64,
}

impl SlotGpu {
    fn new(
        device: &wgpu::Device,
        bgl: &wgpu::BindGroupLayout,
        sampler: &wgpu::Sampler,
        cfg: SlotConfig,
    ) -> Self {
        let size = wgpu::Extent3d {
            width: cfg.width,
            height: cfg.height,
            depth_or_array_layers: 1,
        };
        let in_tex = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("media-drift in"),
            size,
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: TEX_FORMAT,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });
        let out_tex = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("media-drift out"),
            size,
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: TEX_FORMAT,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let out_view = out_tex.create_view(&wgpu::TextureViewDescriptor::default());
        let in_view = in_tex.create_view(&wgpu::TextureViewDescriptor::default());
        let uniform = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("media-drift uniform"),
            size: std::mem::size_of::<DriftUniforms>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("media-drift bind"),
            layout: bgl,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: uniform.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::TextureView(&in_view),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: wgpu::BindingResource::Sampler(sampler),
                },
            ],
        });
        let bytes_per_row = cfg.width * 4;
        let padded_bytes_per_row = align_up(bytes_per_row, 256);
        let staging = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("media-drift staging"),
            size: (padded_bytes_per_row * cfg.height) as u64,
            usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        Self {
            expected_bytes: (cfg.width * cfg.height * 4) as usize,
            cfg,
            in_tex,
            out_tex,
            out_view,
            uniform,
            bind_group,
            staging,
            bytes_per_row,
            padded_bytes_per_row,
            frame: 0,
        }
    }

    /// Encode one slot pass into a command buffer.
    ///
    /// Returns `None` if the producer has not written a complete raw frame yet.
    /// Readback is intentionally drained later so all slots can submit together
    /// and share one `device.poll(Maintain::Wait)` per tick.
    fn encode(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        pipeline: &wgpu::RenderPipeline,
        state: &hapax_visual::media_drift::DriftState,
        now: f32,
    ) -> Option<wgpu::CommandBuffer> {
        let raw = match std::fs::read(&self.cfg.raw_path) {
            Ok(d) if d.len() == self.expected_bytes => d,
            _ => return None, // producer not (yet) writing raw, or wrong dims — skip
        };

        queue.write_texture(
            wgpu::TexelCopyTextureInfo {
                texture: &self.in_tex,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            &raw,
            wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(self.bytes_per_row),
                rows_per_image: Some(self.cfg.height),
            },
            wgpu::Extent3d {
                width: self.cfg.width,
                height: self.cfg.height,
                depth_or_array_layers: 1,
            },
        );

        let u = DriftUniforms::new(
            state,
            self.cfg.class,
            now,
            self.frame as f32,
            self.cfg.intensity,
            self.cfg.width,
            self.cfg.height,
        );
        queue.write_buffer(&self.uniform, 0, bytemuck::bytes_of(&u));

        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
            label: Some("media-drift enc"),
        });
        {
            let mut pass = enc.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("media-drift pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &self.out_view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
            });
            pass.set_pipeline(pipeline);
            pass.set_bind_group(0, &self.bind_group, &[]);
            pass.draw(0..3, 0..1);
        }
        enc.copy_texture_to_buffer(
            wgpu::TexelCopyTextureInfo {
                texture: &self.out_tex,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::TexelCopyBufferInfo {
                buffer: &self.staging,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(self.padded_bytes_per_row),
                    rows_per_image: Some(self.cfg.height),
                },
            },
            wgpu::Extent3d {
                width: self.cfg.width,
                height: self.cfg.height,
                depth_or_array_layers: 1,
            },
        );
        Some(enc.finish())
    }

    fn finish_readback(&mut self) -> bool {
        let mapped = self.staging.slice(..).get_mapped_range();
        let mut out = Vec::with_capacity(self.expected_bytes);
        if self.padded_bytes_per_row == self.bytes_per_row {
            out.extend_from_slice(&mapped[..self.expected_bytes]);
        } else {
            for row in 0..self.cfg.height {
                let s = (row * self.padded_bytes_per_row) as usize;
                out.extend_from_slice(&mapped[s..s + self.bytes_per_row as usize]);
            }
        }
        drop(mapped);
        self.staging.unmap();

        // Atomic write so the engine never blits a torn frame.
        let tmp = self.cfg.out_path.with_extension("bgra.tmp");
        if std::fs::write(&tmp, &out)
            .and_then(|_| std::fs::rename(&tmp, &self.cfg.out_path))
            .is_ok()
        {
            self.frame += 1;
            return true;
        }
        false
    }
}

fn pick_adapter(instance: &wgpu::Instance) -> wgpu::Adapter {
    let want = std::env::var("HAPAX_SCREWM_DRIFT_GPU").unwrap_or_else(|_| "5060".to_string());
    let adapters = instance.enumerate_adapters(wgpu::Backends::VULKAN);
    for a in &adapters {
        if a.get_info()
            .name
            .to_lowercase()
            .contains(&want.to_lowercase())
        {
            log::info!("media-drift GPU: {} (matched '{want}')", a.get_info().name);
            return a.clone();
        }
    }
    let fallback = adapters
        .into_iter()
        .next()
        .expect("no Vulkan adapter for media-drift");
    log::warn!(
        "media-drift: no adapter matched '{want}', using {}",
        fallback.get_info().name
    );
    fallback
}

async fn run() {
    let spec = std::env::var("HAPAX_SCREWM_DRIFT_SLOTS").unwrap_or_default();
    let slots: Vec<SlotConfig> = spec.split(',').filter_map(SlotConfig::parse).collect();
    if slots.is_empty() {
        log::error!(
            "HAPAX_SCREWM_DRIFT_SLOTS empty — nothing to drift; set e.g. 'ward-atlas:2048x2304'"
        );
        return;
    }
    let game_data = std::env::var("HAPAX_SCREWM_DRIFT_GAME_DATA")
        .map(PathBuf::from)
        .unwrap_or_else(|_| dirs_home().join(".darkplaces/screwm/data"));
    let fps: f32 = std::env::var("HAPAX_SCREWM_DRIFT_FPS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(20.0);

    let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor {
        backends: wgpu::Backends::VULKAN,
        ..Default::default()
    });
    let adapter = pick_adapter(&instance);
    let (device, queue) = adapter
        .request_device(
            &wgpu::DeviceDescriptor {
                label: Some("screwm-media-drift"),
                required_features: wgpu::Features::empty(),
                required_limits: wgpu::Limits::default(),
                ..Default::default()
            },
            None,
        )
        .await
        .expect("media-drift: request_device failed");

    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("media_drift.wgsl"),
        source: wgpu::ShaderSource::Wgsl(Cow::Borrowed(SHADER_SRC)),
    });
    let bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("media-drift bgl"),
        entries: &[
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
            wgpu::BindGroupLayoutEntry {
                binding: 1,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
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
    let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
        label: Some("media-drift layout"),
        bind_group_layouts: &[&bgl],
        push_constant_ranges: &[],
    });
    let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some("media-drift pipeline"),
        layout: Some(&layout),
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
                format: TEX_FORMAT,
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
    let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
        label: Some("media-drift sampler"),
        address_mode_u: wgpu::AddressMode::ClampToEdge,
        address_mode_v: wgpu::AddressMode::ClampToEdge,
        address_mode_w: wgpu::AddressMode::ClampToEdge,
        mag_filter: wgpu::FilterMode::Linear,
        min_filter: wgpu::FilterMode::Linear,
        ..Default::default()
    });

    let slot_names = slots
        .iter()
        .map(|slot| slot.name.as_str())
        .collect::<Vec<_>>()
        .join(", ");
    let mut gpus: Vec<SlotGpu> = slots
        .into_iter()
        .map(|c| SlotGpu::new(&device, &bgl, &sampler, c))
        .collect();
    log::info!(
        "media-drift live: {} slot(s) [{}] @ {fps}fps, game_data={}",
        gpus.len(),
        slot_names,
        game_data.display()
    );

    let start = Instant::now();
    let period = Duration::from_secs_f32(1.0 / fps.max(1.0));
    loop {
        let tick = Instant::now();
        let state = load_drift_state(&game_data);
        let now = start.elapsed().as_secs_f32();
        let mut ready = Vec::new();
        let mut commands = Vec::new();
        for (idx, g) in gpus.iter_mut().enumerate() {
            if let Some(command) = g.encode(&device, &queue, &pipeline, &state, now) {
                ready.push(idx);
                commands.push(command);
            }
        }

        if !commands.is_empty() {
            queue.submit(commands);
            let mut waits = Vec::with_capacity(ready.len());
            for idx in ready {
                let (tx, rx) = std::sync::mpsc::channel();
                gpus[idx]
                    .staging
                    .slice(..)
                    .map_async(wgpu::MapMode::Read, move |r| {
                        let _ = tx.send(r);
                    });
                waits.push((idx, rx));
            }
            device.poll(wgpu::Maintain::Wait);
            for (idx, rx) in waits {
                if rx.recv().map(|r| r.is_err()).unwrap_or(true) {
                    gpus[idx].staging.unmap();
                    continue;
                }
                gpus[idx].finish_readback();
            }
        }
        if let Some(rem) = period.checked_sub(tick.elapsed()) {
            std::thread::sleep(rem);
        }
    }
}

fn dirs_home() -> PathBuf {
    std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/root"))
}

fn main() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();
    pollster::block_on(run());
}
