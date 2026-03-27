//! Bridge between Tauri and the hapax-visual wgpu renderer.
//!
//! Spawns the visual surface on a dedicated thread with its own winit event loop.
//! Communicates back to Tauri via events (frame stats, stance changes).

use std::sync::Arc;
use std::time::Instant;
use tauri::{AppHandle, Emitter, Runtime};
use winit::application::ApplicationHandler;
use winit::event::WindowEvent;
use winit::event_loop::{ActiveEventLoop, ControlFlow, EventLoop};
use winit::window::{Window, WindowId};

use super::compositor::Compositor;
use super::gpu::GpuContext;
use super::output::ShmOutput;
use super::postprocess::PostProcess;
use super::state::StateReader;
use super::techniques::feedback::FeedbackTechnique;
use super::techniques::gradient::GradientTechnique;
use super::techniques::physarum::PhysarumTechnique;
use super::techniques::reaction_diff::ReactionDiffTechnique;
use super::techniques::voronoi::VoronoiTechnique;
use super::techniques::wave::WaveTechnique;

/// Frame stats emitted to the webview every 300 frames.
#[derive(Clone, serde::Serialize)]
pub struct FrameStats {
    pub frame_time_ms: f32,
    pub stance: String,
    pub warmth: f32,
    pub feed_rate: f32,
    pub fps: f32,
}

struct VisualApp<R: Runtime> {
    app_handle: AppHandle<R>,
    gpu: Option<GpuContext>,
    window: Option<Arc<Window>>,
    gradient: Option<GradientTechnique>,
    reaction_diff: Option<ReactionDiffTechnique>,
    voronoi: Option<VoronoiTechnique>,
    wave: Option<WaveTechnique>,
    physarum: Option<PhysarumTechnique>,
    feedback: Option<FeedbackTechnique>,
    compositor: Option<Compositor>,
    postprocess: Option<PostProcess>,
    shm_output: Option<ShmOutput>,
    state_reader: StateReader,
    start_time: Instant,
    last_frame: Instant,
    frame_count: u64,
    voronoi_computed: bool,
}

impl<R: Runtime> VisualApp<R> {
    fn new(app_handle: AppHandle<R>) -> Self {
        Self {
            app_handle,
            gpu: None,
            window: None,
            gradient: None,
            reaction_diff: None,
            voronoi: None,
            wave: None,
            physarum: None,
            feedback: None,
            compositor: None,
            postprocess: None,
            shm_output: None,
            state_reader: StateReader::new(),
            start_time: Instant::now(),
            last_frame: Instant::now(),
            frame_count: 0,
            voronoi_computed: false,
        }
    }

    fn render(&mut self) {
        let Some(gpu) = &self.gpu else { return };
        let Some(gradient) = &self.gradient else { return };
        let Some(rd) = &mut self.reaction_diff else { return };
        let Some(voronoi) = &self.voronoi else { return };
        let Some(wave) = &mut self.wave else { return };
        let Some(physarum) = &self.physarum else { return };
        let Some(feedback_tech) = &self.feedback else { return };
        let Some(compositor) = &self.compositor else { return };
        let Some(postprocess) = &self.postprocess else { return };
        let Some(window) = &self.window else { return };

        let now = Instant::now();
        let dt = now.duration_since(self.last_frame).as_secs_f32();
        self.last_frame = now;
        let time = now.duration_since(self.start_time).as_secs_f32();

        self.state_reader.poll(dt);

        let output = match gpu.surface.get_current_texture() {
            Ok(t) => t,
            Err(wgpu::SurfaceError::Lost | wgpu::SurfaceError::Outdated) => return,
            Err(e) => {
                log::error!("Surface error: {}", e);
                return;
            }
        };

        let surface_view = output
            .texture
            .create_view(&wgpu::TextureViewDescriptor::default());

        gradient.update_uniforms(&gpu.queue, &self.state_reader.smoothed, time);
        rd.update_params(&gpu.queue, &self.state_reader.smoothed, dt);
        physarum.update_params(&gpu.queue, &self.state_reader.smoothed, time);
        postprocess.update_uniforms(&gpu.queue, time);
        compositor.update_opacities(&gpu.queue, &self.state_reader.smoothed.layer_opacities);

        wave.flush_events(&gpu.queue);

        let mut encoder = gpu
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                label: Some("frame"),
            });

        feedback_tech.process(&mut encoder, gpu);
        gradient.render(&mut encoder);
        rd.step(&mut encoder, 8);

        if !self.voronoi_computed {
            voronoi.compute(&mut encoder, gpu);
            self.voronoi_computed = true;
        }

        wave.step(&mut encoder, gpu);
        physarum.step(&mut encoder, gpu);

        let frame_bg = compositor.create_frame_bind_group(
            &gpu.device,
            &gradient.view,
            rd.output_view(),
            &voronoi.color_view,
            wave.output_view(),
            physarum.output_view(),
            &feedback_tech.output_view,
        );
        compositor.render(&mut encoder, &frame_bg);

        feedback_tech.capture_frame(&mut encoder, &compositor.composite_texture);

        if let Some(shm) = &self.shm_output {
            if self.frame_count % 2 == 0 {
                shm.copy_to_staging(&mut encoder, &compositor.composite_texture);
            }
        }

        postprocess.render(&mut encoder, &surface_view, &compositor.composite_view, &gpu.device);

        gpu.queue.submit(std::iter::once(encoder.finish()));
        output.present();

        if let Some(shm) = &self.shm_output {
            if self.frame_count % 2 == 0 {
                gpu.device.poll(wgpu::Maintain::Wait);
                shm.write_frame();
            }
        }

        self.frame_count += 1;
        if self.frame_count % 300 == 0 {
            let stats = FrameStats {
                frame_time_ms: dt * 1000.0,
                stance: format!("{:?}", self.state_reader.smoothed.stance),
                warmth: self.state_reader.smoothed.color_warmth,
                feed_rate: rd.current_f(),
                fps: 1.0 / dt,
            };
            // Emit to webview — fire-and-forget, ok if nobody is listening
            let _ = self.app_handle.emit("visual:frame-stats", &stats);

            log::info!(
                "frame_time: {:.2}ms | stance: {:?} | warmth: {:.2} | F: {:.4}",
                dt * 1000.0,
                self.state_reader.smoothed.stance,
                self.state_reader.smoothed.color_warmth,
                rd.current_f(),
            );
        }

        window.request_redraw();
    }
}

impl<R: Runtime> ApplicationHandler for VisualApp<R> {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        if self.window.is_some() {
            return;
        }

        let attrs = Window::default_attributes()
            .with_title("hapax-visual")
            .with_inner_size(winit::dpi::LogicalSize::new(1920, 1080));

        let window = Arc::new(event_loop.create_window(attrs).unwrap());
        let gpu = pollster::block_on(GpuContext::new(window.clone()));

        let size = window.inner_size();
        let w = size.width.max(1);
        let h = size.height.max(1);

        let gradient = GradientTechnique::new(&gpu, w, h);
        let reaction_diff = ReactionDiffTechnique::new(&gpu, w, h);
        let voronoi = VoronoiTechnique::new(&gpu, w, h);
        let wave = WaveTechnique::new(&gpu, w, h);
        let physarum = PhysarumTechnique::new(&gpu, w, h);
        let feedback = FeedbackTechnique::new(&gpu, w, h);
        let compositor = Compositor::new(&gpu, w, h);
        let postprocess = PostProcess::new(&gpu);
        let shm_output = ShmOutput::new(&gpu.device, w, h);

        self.window = Some(window.clone());
        self.gpu = Some(gpu);
        self.gradient = Some(gradient);
        self.reaction_diff = Some(reaction_diff);
        self.voronoi = Some(voronoi);
        self.wave = Some(wave);
        self.physarum = Some(physarum);
        self.feedback = Some(feedback);
        self.compositor = Some(compositor);
        self.postprocess = Some(postprocess);
        self.shm_output = Some(shm_output);

        window.request_redraw();
    }

    fn window_event(&mut self, event_loop: &ActiveEventLoop, _id: WindowId, event: WindowEvent) {
        match event {
            WindowEvent::CloseRequested => {
                event_loop.exit();
            }
            WindowEvent::Resized(size) => {
                let w = size.width.max(1);
                let h = size.height.max(1);
                if let Some(gpu) = &mut self.gpu {
                    gpu.resize(w, h);
                }
                if let Some(gradient) = &mut self.gradient {
                    if let Some(gpu) = &self.gpu {
                        gradient.resize(&gpu.device, w, h);
                    }
                }
                if let Some(rd) = &mut self.reaction_diff {
                    if let Some(gpu) = &self.gpu {
                        rd.resize(gpu, w, h);
                    }
                }
                if let Some(voronoi) = &mut self.voronoi {
                    if let Some(gpu) = &self.gpu {
                        voronoi.resize(gpu, w, h);
                        self.voronoi_computed = false;
                    }
                }
                if let Some(wave) = &mut self.wave {
                    if let Some(gpu) = &self.gpu {
                        wave.resize(gpu, w, h);
                    }
                }
                if let Some(physarum) = &mut self.physarum {
                    if let Some(gpu) = &self.gpu {
                        physarum.resize(gpu, w, h);
                    }
                }
                if let Some(feedback) = &mut self.feedback {
                    if let Some(gpu) = &self.gpu {
                        feedback.resize(gpu, w, h);
                    }
                }
                if let Some(compositor) = &mut self.compositor {
                    if let Some(gpu) = &self.gpu {
                        compositor.resize(&gpu.device, w, h);
                    }
                }
                if let Some(shm) = &mut self.shm_output {
                    if let Some(gpu) = &self.gpu {
                        shm.resize(&gpu.device, w, h);
                    }
                }
            }
            WindowEvent::RedrawRequested => {
                self.render();
            }
            _ => {}
        }
    }
}

/// Spawn the visual surface on a dedicated thread.
///
/// The thread creates its own winit event loop and wgpu context.
/// Frame stats are emitted back to Tauri via `visual:frame-stats` events.
pub fn spawn_visual_surface<R: Runtime>(app_handle: AppHandle<R>) {
    std::thread::Builder::new()
        .name("hapax-visual".into())
        .spawn(move || {
            // Ensure shm directories exist
            std::fs::create_dir_all("/dev/shm/hapax-compositor").ok();
            std::fs::create_dir_all("/dev/shm/hapax-stimmung").ok();

            use winit::platform::wayland::EventLoopBuilderExtWayland;
            let event_loop = EventLoop::builder().with_any_thread(true).build().unwrap();
            event_loop.set_control_flow(ControlFlow::Poll);

            let mut app = VisualApp::new(app_handle);
            if let Err(e) = event_loop.run_app(&mut app) {
                log::error!("Visual surface event loop exited with error: {}", e);
            }
        })
        .expect("Failed to spawn visual surface thread");
}
