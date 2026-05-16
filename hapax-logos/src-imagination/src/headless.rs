//! Offscreen reverie render loop — Phase 4b of the reverie source-registry
//! completion epic.
//!
//! Activated by `HAPAX_IMAGINATION_HEADLESS=1`. Owns a private
//! `wgpu::Device`, `wgpu::Queue`, and an offscreen `Rgba8UnormSrgb`
//! texture that stands in for the windowed path's surface view.
//! `DynamicPipeline::render` blits into that offscreen texture exactly
//! the way it would blit into a winit surface view, and its internal
//! `ShmOutput` continues to publish `/dev/shm/hapax-visual/frame.jpg`
//! (Tauri reads this) and `/dev/shm/hapax-sources/reverie.rgba`
//! (compositor `ShmRgbaReader` reads this). No window is ever created.
//!
//! The windowed path in `main.rs` is preserved for local-dev runs
//! without the env var. The systemd unit flips the env var on so the
//! production service no longer spawns a visible winit window.

use std::convert::Infallible;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use hapax_visual::content_sources::ContentSourceManager;
use hapax_visual::dynamic_pipeline::{DynamicPipeline, PoolMetrics};
use hapax_visual::scene_renderer::SceneRenderer;
use hapax_visual::state::StateReader;

/// Path the Python compositor's ``metrics._poll_loop`` reads to
/// populate the ``reverie_pool_*`` Prometheus gauges. JSON shape is
/// stable — the Python side hard-codes the key names in its poll loop.
/// 3D proof output directory. Only active when HAPAX_IMAGINATION_3D_PROOF=1.
const PROOF_3D_OUTPUT_DIR: &str = "/dev/shm/hapax-imagination/3d-proof";
const PROOF_3D_FRAME_PATH: &str = "/dev/shm/hapax-imagination/3d-proof/frame.jpg";

const POOL_METRICS_SHM_PATH: &str = "/dev/shm/hapax-imagination/pool_metrics.json";

impl Renderer {
    /// Write 3D proof frame to shm as JPEG for visual comparison.
    fn write_proof_frame(&mut self, scene: &SceneRenderer) {
        let width = scene.width();
        let height = scene.height();
        let padded_bpr = ((width * 4 + 255) / 256) * 256;

        // GPU readback via staging buffer
        let staging = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("proof staging"),
            size: (padded_bpr * height) as u64,
            usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });

        let mut encoder = self
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                label: Some("proof readback"),
            });
        encoder.copy_texture_to_buffer(
            wgpu::TexelCopyTextureInfo {
                texture: scene.output_texture(),
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::TexelCopyBufferInfo {
                buffer: &staging,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(padded_bpr),
                    rows_per_image: Some(height),
                },
            },
            wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
        );
        self.queue.submit(std::iter::once(encoder.finish()));

        let slice = staging.slice(..);
        slice.map_async(wgpu::MapMode::Read, |_| {});
        self.device.poll(wgpu::Maintain::Wait);

        let data = slice.get_mapped_range();
        // Unpad rows
        let bpr = (width * 4) as usize;
        let mut pixels = Vec::with_capacity(bpr * height as usize);
        for row in 0..height as usize {
            let start = row * padded_bpr as usize;
            pixels.extend_from_slice(&data[start..start + bpr]);
        }
        drop(data);
        staging.unmap();

        // JPEG compress and write
        if let Some(ref mut compressor) = self.proof_jpeg {
            let image = turbojpeg::Image {
                pixels: pixels.as_slice(),
                width: width as usize,
                pitch: bpr,
                height: height as usize,
                format: turbojpeg::PixelFormat::RGBA,
            };
            if let Ok(jpeg_data) = compressor.compress_to_vec(image) {
                if let Err(e) = write_atomic(Path::new(PROOF_3D_FRAME_PATH), &jpeg_data) {
                    log::warn!("3D proof frame write failed: {e}");
                }
            }
        }
    }
}

/// LRR Phase 0 item 4 / FINDING-Q step 4 — sibling JSON for shader
/// health (rollback counter). Separate from `pool_metrics.json` because
/// pool metrics are render-loop-frequency (1 Hz at 60 fps) while shader
/// rollbacks are event-driven (rare). Separate cadences keep both
/// writers clean. Spike notes: see
/// `docs/superpowers/specs/2026-04-14-lrr-phase-0-finding-q-spike-notes.md`.
const SHADER_HEALTH_SHM_PATH: &str = "/dev/shm/hapax-imagination/shader_health.json";

/// How often the renderer publishes pool metrics, measured in frames.
/// At the 60 fps render interval this gives roughly a 1 Hz Prometheus
/// sample cadence — cheap enough to be unconditional, dense enough that
/// reuse-ratio drift is visible on the dashboard.
const POOL_METRICS_PUBLISH_EVERY_FRAMES: u64 = 60;

/// Shader health publish cadence. Shader rollbacks are rare so we don't
/// need 1 Hz; once every ~10 seconds is plenty for Grafana alerting and
/// keeps the writer overhead negligible. Frame count is mod'd so this
/// runs alongside the pool publish without contention.
const SHADER_HEALTH_PUBLISH_EVERY_FRAMES: u64 = 600;

/// Offscreen texture format. Matches the sRGB format the winit path
/// selects from `surface.get_capabilities` — the blit pipeline built
/// inside `DynamicPipeline` expects this to match so the final blit
/// target format agrees with its pipeline descriptor.
const OFFSCREEN_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8UnormSrgb;

pub struct Renderer {
    device: wgpu::Device,
    queue: wgpu::Queue,
    width: u32,
    height: u32,
    offscreen_view: wgpu::TextureView,
    #[allow(dead_code)]
    offscreen_texture: wgpu::Texture,
    pipeline: DynamicPipeline,
    content_source_mgr: ContentSourceManager,
    state_reader: StateReader,
    start_time: Instant,
    last_frame: Instant,
    frame_count: u64,
    /// 3D scene renderer for Phase 0 proof. Only instantiated when
    /// `HAPAX_IMAGINATION_3D_PROOF=1`. When None, zero runtime cost.
    scene_renderer: Option<SceneRenderer>,
    /// Separate JPEG compressor for 3D proof output.
    proof_jpeg: Option<turbojpeg::Compressor>,
}

impl Renderer {
    /// Build a real headless renderer. Creates a private wgpu device,
    /// an offscreen target texture, and the same `DynamicPipeline` +
    /// `ContentSourceManager` + `StateReader` triple the winit path
    /// uses. `DynamicPipeline::new` internally constructs its own
    /// `ShmOutput`, so frames begin landing in `/dev/shm` as soon as
    /// `run_forever` starts ticking.
    pub async fn new(width: u32, height: u32) -> Self {
        let (device, queue) = create_headless_device().await;

        let offscreen_texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("hapax-imagination-headless-offscreen"),
            size: wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: OFFSCREEN_FORMAT,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let offscreen_view = offscreen_texture.create_view(&wgpu::TextureViewDescriptor::default());

        let pipeline = DynamicPipeline::new(&device, &queue, width, height, OFFSCREEN_FORMAT);
        let content_source_mgr = ContentSourceManager::new(&device, &queue);
        let state_reader = StateReader::new();

        log::info!(
            "headless::Renderer initialized {}x{} — DynamicPipeline + ShmOutput live, \
             no winit window",
            width,
            height
        );

        // 3D proof of concept — gated behind env var
        let scene_renderer = if std::env::var("HAPAX_IMAGINATION_3D_PROOF").as_deref() == Ok("1") {
            log::info!(
                "3D proof mode ENABLED — rendering to {}",
                PROOF_3D_OUTPUT_DIR
            );
            std::fs::create_dir_all(PROOF_3D_OUTPUT_DIR).ok();
            Some(SceneRenderer::new(&device, &queue, width, height))
        } else {
            None
        };

        let proof_jpeg = if scene_renderer.is_some() {
            turbojpeg::Compressor::new().ok().map(|mut c| {
                c.set_quality(80).ok();
                c.set_subsamp(turbojpeg::Subsamp::Sub2x2).ok();
                c
            })
        } else {
            None
        };

        let now = Instant::now();
        Self {
            device,
            queue,
            width,
            height,
            offscreen_view,
            offscreen_texture,
            pipeline,
            content_source_mgr,
            state_reader,
            start_time: now,
            last_frame: now,
            frame_count: 0,
            scene_renderer,
            proof_jpeg,
        }
    }

    /// Drive the render loop forever. A+ Stage 0 (2026-04-17): 62.5fps
    /// → 30fps tokio interval. The compositor samples reverie.rgba at
    /// 30fps into a 640x360 PiP; rendering at 62.5fps doubled wgpu work
    /// for zero visual benefit downstream. 30fps aligns imagination's
    /// output cadence with the compositor's sample rate. Override via
    /// HAPAX_IMAGINATION_INTERVAL_MS env var for future tuning.
    pub async fn run_forever(mut self) -> Infallible {
        let interval_ms: u64 = std::env::var("HAPAX_IMAGINATION_INTERVAL_MS")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(33);
        let mut interval = tokio::time::interval(Duration::from_millis(interval_ms));
        interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        log::info!(
            "headless::Renderer::run_forever started at {}x{}",
            self.width,
            self.height
        );
        loop {
            interval.tick().await;
            self.render_frame();
        }
    }

    fn render_frame(&mut self) {
        let now = Instant::now();
        let dt = now.duration_since(self.last_frame).as_secs_f32();
        self.last_frame = now;
        let time = now.duration_since(self.start_time).as_secs_f32();

        self.state_reader.poll(dt);
        self.content_source_mgr.scan(&self.device, &self.queue);
        self.content_source_mgr.tick_fades(dt);

        let opacities = self.content_source_mgr.slot_opacities();

        // HOMAGE Phase 6 - Ward↔Shader bidirectional coupling
        crate::homage_feedback::emit_shader_feedback(
            self.state_reader.smoothed.audio_energy as f64,
            0.0,  // drift
            true, // is_fresh
        );

        // 3D scene render → inject into DynamicPipeline as @live
        // Phase 3: the 3D scene output becomes the shader vocabulary's
        // input texture. Shaders process the 3D scene exactly as they
        // process the noise-generated fallback, but now with real
        // perspective-rendered content sources.
        if let Some(mut scene) = self.scene_renderer.take() {
            scene.render(
                &self.device,
                &self.queue,
                time,
                Some(&self.content_source_mgr),
            );

            // Inject 3D scene output as @live for the shader chain
            self.pipeline.set_live_texture_override(
                &self.device,
                &self.queue,
                scene.output_texture(),
            );

            // Write 3D proof frame to shm every 30 frames (~1 Hz)
            if self.frame_count.is_multiple_of(30) {
                self.write_proof_frame(&scene);
                log::info!(
                    "3D scene: {} active sources, {} total loaded",
                    self.content_source_mgr.active_source_info().len(),
                    self.content_source_mgr.source_count()
                );
            }
            self.scene_renderer = Some(scene);
        }

        // Run shader vocabulary pipeline (now with 3D scene as @live if active)
        self.pipeline.render(
            &self.device,
            &self.queue,
            &self.offscreen_view,
            OFFSCREEN_FORMAT,
            &self.state_reader,
            dt,
            time,
            opacities,
            Some(&self.content_source_mgr),
        );

        self.frame_count = self.frame_count.wrapping_add(1);
        if self.frame_count.is_multiple_of(600) {
            log::info!(
                "headless frame_count={} ({:.1}s elapsed)",
                self.frame_count,
                now.duration_since(self.start_time).as_secs_f32()
            );
        }

        // Delta post-epic retirement handoff item #3 / AC-13: publish
        // DynamicPipeline::pool_metrics() over the shared-memory bridge
        // so the compositor's Python Prometheus exporter on :9482 can
        // surface reverie_pool_* gauges. One JSON write per second at
        // the 60fps render interval.
        if self
            .frame_count
            .is_multiple_of(POOL_METRICS_PUBLISH_EVERY_FRAMES)
        {
            publish_pool_metrics(&self.pipeline.pool_metrics());
        }

        // LRR Phase 0 item 4 / FINDING-Q step 4: publish shader rollback
        // counter to a sibling JSON. The compositor's Python exporter
        // re-publishes it as `hapax_imagination_shader_rollback_total`.
        // Lower cadence than pool metrics (~10 s) because rollback events
        // are rare and the counter only changes when one fires.
        if self
            .frame_count
            .is_multiple_of(SHADER_HEALTH_PUBLISH_EVERY_FRAMES)
        {
            publish_shader_health(self.pipeline.shader_rollback_total());
        }
    }
}

/// LRR Phase 0 item 4 / FINDING-Q step 4 — write the shader rollback
/// counter to ``/dev/shm/hapax-imagination/shader_health.json`` for the
/// compositor Python exporter to re-publish as
/// ``hapax_imagination_shader_rollback_total``.
///
/// Same atomic-write pattern as ``publish_pool_metrics``. Failures are
/// swallowed with a ``log::warn`` — the render loop must not block on
/// observability writes.
fn publish_shader_health(rollback_total: u64) {
    let payload = format!("{{\"shader_rollback_total\":{}}}\n", rollback_total,);
    if let Err(e) = write_atomic(Path::new(SHADER_HEALTH_SHM_PATH), payload.as_bytes()) {
        log::warn!("publish_shader_health: write failed: {e}");
    }
}

/// Serialize ``PoolMetrics`` to ``/dev/shm/hapax-imagination/pool_metrics.json``
/// using the tmp+rename atomic-write pattern so the compositor's
/// polling reader never sees a partial document.
///
/// Failures are swallowed with a ``log::warn`` — the render loop must
/// not block on observability writes.
fn publish_pool_metrics(metrics: &PoolMetrics) {
    let payload = format!(
        "{{\"bucket_count\":{},\"total_textures\":{},\"total_acquires\":{},\
\"total_allocations\":{},\"reuse_ratio\":{:.6},\"slot_count\":{}}}\n",
        metrics.bucket_count,
        metrics.total_textures,
        metrics.total_acquires,
        metrics.total_allocations,
        metrics.reuse_ratio,
        metrics.slot_count,
    );
    if let Err(e) = write_atomic(Path::new(POOL_METRICS_SHM_PATH), payload.as_bytes()) {
        log::warn!("publish_pool_metrics: write failed: {e}");
    }
}

fn write_atomic(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let mut tmp_path: PathBuf = path.to_path_buf();
    let mut suffix = tmp_path
        .extension()
        .map(|e| e.to_string_lossy().into_owned())
        .unwrap_or_default();
    suffix.push_str(".tmp");
    tmp_path.set_extension(suffix);
    {
        let mut tmp = fs::File::create(&tmp_path)?;
        tmp.write_all(bytes)?;
        tmp.sync_all()?;
    }
    fs::rename(&tmp_path, path)?;
    Ok(())
}

/// Build a wgpu device+queue with no surface attached. Mirrors the
/// windowed `GpuContext::new` adapter/device settings so the pipeline
/// build path behaves the same as the winit path — same required
/// features, same limits, same backend.
async fn create_headless_device() -> (wgpu::Device, wgpu::Queue) {
    let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor {
        backends: wgpu::Backends::VULKAN,
        ..Default::default()
    });

    // Multi-GPU pinning: HAPAX_WGPU_ADAPTER_CONTAINS=3090 selects the adapter
    // whose name contains that substring. Needed when multiple NVIDIA dGPUs are
    // present — wgpu's HighPerformance preference alone cannot distinguish them
    // and will pick the lowest PCI-bus card, which is not necessarily the one
    // driving the display surface.
    let adapter = match std::env::var("HAPAX_WGPU_ADAPTER_CONTAINS") {
        Ok(needle) => instance
            .enumerate_adapters(wgpu::Backends::VULKAN)
            .into_iter()
            .find(|a| a.get_info().name.contains(&needle))
            .unwrap_or_else(|| panic!("headless: no adapter matching '{needle}'")),
        Err(_) => instance
            .request_adapter(&wgpu::RequestAdapterOptions {
                power_preference: wgpu::PowerPreference::HighPerformance,
                compatible_surface: None,
                force_fallback_adapter: false,
            })
            .await
            .expect("headless: no suitable GPU adapter found"),
    };

    log::info!("headless: using adapter {:?}", adapter.get_info().name);

    adapter
        .request_device(
            &wgpu::DeviceDescriptor {
                label: Some("hapax-visual-headless"),
                required_features: wgpu::Features::TEXTURE_ADAPTER_SPECIFIC_FORMAT_FEATURES,
                required_limits: wgpu::Limits::default(),
                ..Default::default()
            },
            None,
        )
        .await
        .expect("headless: failed to create device")
}
