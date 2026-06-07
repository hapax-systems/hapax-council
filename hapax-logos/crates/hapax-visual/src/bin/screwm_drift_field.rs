//! screwm_drift_field — GPU drift-field producer for the Screwm DarkPlaces engine.
//!
//! Single-pass headless wgpu producer on the 5060 Ti (NOT a second DynamicPipeline —
//! that would collide on the reverie pipeline's hardcoded plan dir + lacks a public
//! readback). It reads the live reverie substrate `/dev/shm/hapax-sources/reverie.rgba`
//! (RGBA, written by hapax-imagination), runs `screwm_drift_field.wgsl` to encode a
//! 256x256 BGRA "drift field" (channels centered at 0.5 = neutral), and atomic-writes
//! `/dev/shm/hapax-compositor/quake-drift-field.bgra`. The engine
//! (R_HapaxDriftField_Update) ingests it and the HAPAXDRIFT fragment stage samples it by
//! world XY to drive endless-variety drift on flagged surfaces.
//!
//! Env: HAPAX_SCREWM_DRIFT_GPU (default "5060"), HAPAX_DRIFT_FIELD_SIZE (256),
//! HAPAX_DRIFT_FIELD_FPS (20), HAPAX_DRIFT_FIELD_IN_W/IN_H (960/540).

use std::borrow::Cow;
use std::time::{Duration, Instant, UNIX_EPOCH};

use blake2::digest::{Update, VariableOutput};
use blake2::Blake2sVar;

const REVERIE_IN: &str = "/dev/shm/hapax-sources/reverie.rgba";
const OUT_PATH: &str = "/dev/shm/hapax-compositor/quake-drift-field.bgra";
const CURRENCY_PATH: &str = "/dev/shm/hapax-compositor/quake-drift-currency.bgra";
const IN_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8Unorm; // reverie is RGBA
const OUT_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Bgra8Unorm; // engine reads BGRA directly
const SHADER_SRC: &str = include_str!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/shaders/screwm_drift_field.wgsl"
));

fn align_up(v: u32, a: u32) -> u32 {
    (v + a - 1) & !(a - 1)
}

fn env_u32(key: &str, default: u32) -> u32 {
    std::env::var(key)
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(default)
}

fn stable_short_hash(bytes: &[u8]) -> [u8; 8] {
    let mut h = Blake2sVar::new(8).expect("blake2s supports 8-byte output");
    h.update(bytes);
    let mut d = [0u8; 8];
    h.finalize_variable(&mut d).expect("digest length");
    d
}

/// (len, mtime_ns) signature for change-detecting the reverie input cheaply.
fn input_sig(path: &str) -> Option<(u64, u128)> {
    let m = std::fs::metadata(path).ok()?;
    let ns = m
        .modified()
        .ok()?
        .duration_since(UNIX_EPOCH)
        .ok()?
        .as_nanos();
    Some((m.len(), ns))
}

fn atomic_write(path: &str, bytes: &[u8]) -> std::io::Result<()> {
    let tmp = format!("{path}.tmp");
    std::fs::write(&tmp, bytes).and_then(|_| std::fs::rename(&tmp, path))
}

/// Map a finished staging buffer, de-pad rows, and atomic-write to `path` when changed.
fn drain_target(
    device: &wgpu::Device,
    staging: &wgpu::Buffer,
    bytes_per_row: u32,
    padded_bytes_per_row: u32,
    size: u32,
    path: &str,
    last_hash: &mut [u8; 8],
) {
    let (tx, rx) = std::sync::mpsc::channel();
    staging.slice(..).map_async(wgpu::MapMode::Read, move |r| {
        let _ = tx.send(r);
    });
    device.poll(wgpu::Maintain::Wait);
    if rx.recv().map(|r| r.is_ok()).unwrap_or(false) {
        let mapped = staging.slice(..).get_mapped_range();
        let mut out = Vec::with_capacity((bytes_per_row * size) as usize);
        if padded_bytes_per_row == bytes_per_row {
            out.extend_from_slice(&mapped[..(bytes_per_row * size) as usize]);
        } else {
            for row in 0..size {
                let s = (row * padded_bytes_per_row) as usize;
                out.extend_from_slice(&mapped[s..s + bytes_per_row as usize]);
            }
        }
        drop(mapped);
        staging.unmap();
        let h = stable_short_hash(&out);
        if h != *last_hash && atomic_write(path, &out).is_ok() {
            *last_hash = h;
        }
    } else {
        staging.unmap();
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
            log::info!("drift-field GPU: {} (matched '{want}')", a.get_info().name);
            return a.clone();
        }
    }
    let fb = adapters
        .into_iter()
        .next()
        .expect("no Vulkan adapter for drift-field");
    log::warn!(
        "drift-field: no adapter matched '{want}', using {}",
        fb.get_info().name
    );
    fb
}

async fn run() {
    let in_w = env_u32("HAPAX_DRIFT_FIELD_IN_W", 960);
    let in_h = env_u32("HAPAX_DRIFT_FIELD_IN_H", 540);
    let size = env_u32("HAPAX_DRIFT_FIELD_SIZE", 256);
    let fps: f32 = std::env::var("HAPAX_DRIFT_FIELD_FPS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(20.0);
    let in_bytes = (in_w as usize) * (in_h as usize) * 4;

    let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor {
        backends: wgpu::Backends::VULKAN,
        ..Default::default()
    });
    let adapter = pick_adapter(&instance);
    let (device, queue) = adapter
        .request_device(
            &wgpu::DeviceDescriptor {
                label: Some("screwm-drift-field"),
                required_features: wgpu::Features::empty(),
                required_limits: wgpu::Limits::default(),
                ..Default::default()
            },
            None,
        )
        .await
        .expect("drift-field: request_device failed");

    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("screwm_drift_field.wgsl"),
        source: wgpu::ShaderSource::Wgsl(Cow::Borrowed(SHADER_SRC)),
    });
    let bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("drift-field bgl"),
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
    let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
        label: Some("drift-field layout"),
        bind_group_layouts: &[&bgl],
        push_constant_ranges: &[],
    });
    let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some("drift-field pipeline"),
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
            targets: &[
                Some(wgpu::ColorTargetState {
                    format: OUT_FORMAT,
                    blend: None,
                    write_mask: wgpu::ColorWrites::ALL,
                }),
                Some(wgpu::ColorTargetState {
                    format: OUT_FORMAT,
                    blend: None,
                    write_mask: wgpu::ColorWrites::ALL,
                }),
            ],
            compilation_options: Default::default(),
        }),
        primitive: wgpu::PrimitiveState::default(),
        depth_stencil: None,
        multisample: wgpu::MultisampleState::default(),
        multiview: None,
        cache: None,
    });
    let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
        label: Some("drift-field sampler"),
        address_mode_u: wgpu::AddressMode::ClampToEdge,
        address_mode_v: wgpu::AddressMode::ClampToEdge,
        address_mode_w: wgpu::AddressMode::ClampToEdge,
        mag_filter: wgpu::FilterMode::Linear,
        min_filter: wgpu::FilterMode::Linear,
        ..Default::default()
    });

    let in_tex = device.create_texture(&wgpu::TextureDescriptor {
        label: Some("drift-field in"),
        size: wgpu::Extent3d {
            width: in_w,
            height: in_h,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: IN_FORMAT,
        usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
        view_formats: &[],
    });
    let in_view = in_tex.create_view(&wgpu::TextureViewDescriptor::default());
    let out_tex = device.create_texture(&wgpu::TextureDescriptor {
        label: Some("drift-field out"),
        size: wgpu::Extent3d {
            width: size,
            height: size,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: OUT_FORMAT,
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
        view_formats: &[],
    });
    let out_view = out_tex.create_view(&wgpu::TextureViewDescriptor::default());
    let cur_tex = device.create_texture(&wgpu::TextureDescriptor {
        label: Some("drift-currency out"),
        size: wgpu::Extent3d {
            width: size,
            height: size,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: OUT_FORMAT,
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
        view_formats: &[],
    });
    let cur_view = cur_tex.create_view(&wgpu::TextureViewDescriptor::default());
    let bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("drift-field bg"),
        layout: &bgl,
        entries: &[
            wgpu::BindGroupEntry {
                binding: 0,
                resource: wgpu::BindingResource::TextureView(&in_view),
            },
            wgpu::BindGroupEntry {
                binding: 1,
                resource: wgpu::BindingResource::Sampler(&sampler),
            },
        ],
    });

    let bytes_per_row = size * 4;
    let padded_bytes_per_row = align_up(bytes_per_row, 256);
    let staging = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("drift-field staging"),
        size: (padded_bytes_per_row * size) as u64,
        usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    });
    let cur_staging = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("drift-currency staging"),
        size: (padded_bytes_per_row * size) as u64,
        usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    });

    log::info!("drift-field live: reverie {in_w}x{in_h} -> field {size}x{size} @ {fps}fps -> {OUT_PATH}");
    let period = Duration::from_secs_f32(1.0 / fps.max(1.0));
    let mut last_sig: Option<(u64, u128)> = None;
    let mut last_out_hash = [0u8; 8];
    let mut last_cur_hash = [0u8; 8];

    loop {
        let tick = Instant::now();
        let sig = input_sig(REVERIE_IN);
        let changed = match (sig, last_sig) {
            (Some(s), Some(p)) => s != p,
            (Some(_), None) => true,
            _ => false,
        };
        if changed {
            if let Ok(raw) = std::fs::read(REVERIE_IN) {
                if raw.len() == in_bytes {
                    last_sig = sig;
                    queue.write_texture(
                        wgpu::TexelCopyTextureInfo {
                            texture: &in_tex,
                            mip_level: 0,
                            origin: wgpu::Origin3d::ZERO,
                            aspect: wgpu::TextureAspect::All,
                        },
                        &raw,
                        wgpu::TexelCopyBufferLayout {
                            offset: 0,
                            bytes_per_row: Some(in_w * 4),
                            rows_per_image: Some(in_h),
                        },
                        wgpu::Extent3d {
                            width: in_w,
                            height: in_h,
                            depth_or_array_layers: 1,
                        },
                    );
                    let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
                        label: Some("drift-field enc"),
                    });
                    {
                        let mut pass = enc.begin_render_pass(&wgpu::RenderPassDescriptor {
                            label: Some("drift-field pass"),
                            color_attachments: &[
                                Some(wgpu::RenderPassColorAttachment {
                                    view: &out_view,
                                    resolve_target: None,
                                    ops: wgpu::Operations {
                                        load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                                        store: wgpu::StoreOp::Store,
                                    },
                                }),
                                Some(wgpu::RenderPassColorAttachment {
                                    view: &cur_view,
                                    resolve_target: None,
                                    ops: wgpu::Operations {
                                        load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                                        store: wgpu::StoreOp::Store,
                                    },
                                }),
                            ],
                            depth_stencil_attachment: None,
                            timestamp_writes: None,
                            occlusion_query_set: None,
                        });
                        pass.set_pipeline(&pipeline);
                        pass.set_bind_group(0, &bind_group, &[]);
                        pass.draw(0..3, 0..1);
                    }
                    enc.copy_texture_to_buffer(
                        wgpu::TexelCopyTextureInfo {
                            texture: &out_tex,
                            mip_level: 0,
                            origin: wgpu::Origin3d::ZERO,
                            aspect: wgpu::TextureAspect::All,
                        },
                        wgpu::TexelCopyBufferInfo {
                            buffer: &staging,
                            layout: wgpu::TexelCopyBufferLayout {
                                offset: 0,
                                bytes_per_row: Some(padded_bytes_per_row),
                                rows_per_image: Some(size),
                            },
                        },
                        wgpu::Extent3d {
                            width: size,
                            height: size,
                            depth_or_array_layers: 1,
                        },
                    );
                    enc.copy_texture_to_buffer(
                        wgpu::TexelCopyTextureInfo {
                            texture: &cur_tex,
                            mip_level: 0,
                            origin: wgpu::Origin3d::ZERO,
                            aspect: wgpu::TextureAspect::All,
                        },
                        wgpu::TexelCopyBufferInfo {
                            buffer: &cur_staging,
                            layout: wgpu::TexelCopyBufferLayout {
                                offset: 0,
                                bytes_per_row: Some(padded_bytes_per_row),
                                rows_per_image: Some(size),
                            },
                        },
                        wgpu::Extent3d {
                            width: size,
                            height: size,
                            depth_or_array_layers: 1,
                        },
                    );
                    queue.submit(Some(enc.finish()));

                    drain_target(
                        &device,
                        &staging,
                        bytes_per_row,
                        padded_bytes_per_row,
                        size,
                        OUT_PATH,
                        &mut last_out_hash,
                    );
                    drain_target(
                        &device,
                        &cur_staging,
                        bytes_per_row,
                        padded_bytes_per_row,
                        size,
                        CURRENCY_PATH,
                        &mut last_cur_hash,
                    );
                }
            }
        }
        if let Some(rem) = period.checked_sub(tick.elapsed()) {
            std::thread::sleep(rem);
        }
    }
}

fn main() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();
    pollster::block_on(run());
}
