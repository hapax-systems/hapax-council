//! hapax-imagination — standalone wgpu visual surface with UDS control.
//!
//! Main thread: winit event loop driving the GPU render pipeline.
//! Background thread: tokio runtime running a Unix domain socket server
//! for external control (window management, render commands, status queries).

mod ipc;
mod window_state;

use std::collections::HashMap;
use std::sync::mpsc;
use std::sync::Arc;
use std::time::Instant;

use winit::application::ApplicationHandler;
use winit::event::WindowEvent;
use winit::event_loop::{ActiveEventLoop, ControlFlow, EventLoop};
use winit::window::{Window, WindowId};

use hapax_visual::compositor::Compositor;
use hapax_visual::content_layer::ContentLayer;
use hapax_visual::gpu::GpuContext;
use hapax_visual::output::ShmOutput;
use hapax_visual::postprocess::PostProcess;
use hapax_visual::state::StateReader;
use hapax_visual::techniques::feedback::FeedbackTechnique;
use hapax_visual::techniques::gradient::GradientTechnique;
use hapax_visual::techniques::physarum::PhysarumTechnique;
use hapax_visual::techniques::reaction_diff::ReactionDiffTechnique;
use hapax_visual::techniques::voronoi::VoronoiTechnique;
use hapax_visual::techniques::wave::WaveTechnique;

use ipc::{Command, RenderAction, Response, WindowAction};
use window_state::{WindowMode, WindowState};

// ---------------------------------------------------------------------------
// Application state
// ---------------------------------------------------------------------------

struct ImaginationApp {
    cmd_rx: mpsc::Receiver<Command>,
    stats_tx: mpsc::Sender<Response>,

    window: Option<Arc<Window>>,
    window_state: WindowState,
    gpu: Option<GpuContext>,

    gradient: Option<GradientTechnique>,
    reaction_diff: Option<ReactionDiffTechnique>,
    voronoi: Option<VoronoiTechnique>,
    wave: Option<WaveTechnique>,
    physarum: Option<PhysarumTechnique>,
    feedback: Option<FeedbackTechnique>,
    compositor: Option<Compositor>,
    content_layer: Option<ContentLayer>,
    postprocess: Option<PostProcess>,
    shm_output: Option<ShmOutput>,
    state_reader: StateReader,

    start_time: Instant,
    last_frame: Instant,
    frame_count: u64,
    voronoi_computed: bool,
    paused: bool,
}

impl ImaginationApp {
    fn new(cmd_rx: mpsc::Receiver<Command>, stats_tx: mpsc::Sender<Response>) -> Self {
        Self {
            cmd_rx,
            stats_tx,
            window: None,
            window_state: WindowState::load(),
            gpu: None,
            gradient: None,
            reaction_diff: None,
            voronoi: None,
            wave: None,
            physarum: None,
            feedback: None,
            compositor: None,
            content_layer: None,
            postprocess: None,
            shm_output: None,
            state_reader: StateReader::new(),
            start_time: Instant::now(),
            last_frame: Instant::now(),
            frame_count: 0,
            voronoi_computed: false,
            paused: false,
        }
    }

    // -- Command processing --------------------------------------------------

    fn process_commands(&mut self) {
        while let Ok(cmd) = self.cmd_rx.try_recv() {
            match cmd {
                Command::Window { action } => {
                    self.apply_window_command(action);
                    let _ = self.stats_tx.send(Response::Ack {
                        for_type: "Window".into(),
                    });
                }
                Command::Render { action } => {
                    self.apply_render_command(action);
                    let _ = self.stats_tx.send(Response::Ack {
                        for_type: "Render".into(),
                    });
                }
                Command::Status => {
                    let (w, h) = self
                        .window
                        .as_ref()
                        .map(|win| {
                            let sz = win.inner_size();
                            (sz.width, sz.height)
                        })
                        .unwrap_or((0, 0));
                    let visible = self
                        .window
                        .as_ref()
                        .map(|win| win.is_visible().unwrap_or(true))
                        .unwrap_or(false);
                    let _ = self.stats_tx.send(Response::Status {
                        visible,
                        mode: format!("{:?}", self.window_state.mode),
                        monitor: self.window_state.monitor,
                        fps: 60, // nominal target
                        frame_count: self.frame_count,
                        dimensions: (w, h),
                    });
                }
            }
        }
    }

    fn apply_window_command(&mut self, action: WindowAction) {
        let Some(window) = &self.window else { return };
        match action {
            WindowAction::Fullscreen => {
                window.set_fullscreen(Some(winit::window::Fullscreen::Borderless(None)));
                self.window_state.mode = WindowMode::Fullscreen;
            }
            WindowAction::Maximized => {
                window.set_maximized(true);
                self.window_state.mode = WindowMode::Maximized;
            }
            WindowAction::Windowed { x, y, w, h } => {
                window.set_fullscreen(None);
                window.set_maximized(false);
                window.set_outer_position(winit::dpi::LogicalPosition::new(x, y));
                let _ = window.request_inner_size(winit::dpi::LogicalSize::new(w, h));
                self.window_state.mode = WindowMode::Windowed;
                self.window_state.x = x;
                self.window_state.y = y;
                self.window_state.width = w;
                self.window_state.height = h;
            }
            WindowAction::Borderless { monitor } => {
                let monitors: Vec<_> = window.available_monitors().collect();
                let target = monitors.get(monitor).cloned();
                window.set_fullscreen(Some(winit::window::Fullscreen::Borderless(target)));
                self.window_state.mode = WindowMode::Borderless;
                self.window_state.monitor = monitor;
            }
            WindowAction::Hide => window.set_visible(false),
            WindowAction::Show => window.set_visible(true),
            WindowAction::AlwaysOnTop { enabled } => {
                window.set_window_level(if enabled {
                    winit::window::WindowLevel::AlwaysOnTop
                } else {
                    winit::window::WindowLevel::Normal
                });
                self.window_state.always_on_top = enabled;
            }
        }
        if let Err(e) = self.window_state.save() {
            log::warn!("Failed to save window state: {}", e);
        }
    }

    fn apply_render_command(&mut self, action: RenderAction) {
        match action {
            RenderAction::SetFps { fps: _ } => {
                // TODO: variable frame rate target
                log::info!("SetFps received (not yet implemented, running at vsync)");
            }
            RenderAction::Pause => {
                self.paused = true;
                log::info!("Render paused");
            }
            RenderAction::Resume => {
                self.paused = false;
                if let Some(window) = &self.window {
                    window.request_redraw();
                }
                log::info!("Render resumed");
            }
        }
    }

    // -- Render --------------------------------------------------------------

    fn render(&mut self) {
        let Some(gpu) = &self.gpu else { return };
        let Some(gradient) = &self.gradient else { return };
        let Some(rd) = &mut self.reaction_diff else {
            return;
        };
        let Some(voronoi) = &self.voronoi else { return };
        let Some(wave) = &mut self.wave else { return };
        let Some(physarum) = &self.physarum else { return };
        let Some(feedback_tech) = &self.feedback else {
            return;
        };
        let Some(compositor) = &self.compositor else {
            return;
        };
        let Some(postprocess) = &self.postprocess else {
            return;
        };
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

        // Content layer: decode imagination fragments, modulate with 9 dimensions, screen-blend
        if let Some(content) = &mut self.content_layer {
            let new_id = &self.state_reader.imagination.id;
            if !new_id.is_empty() && *new_id != content.current_fragment_id {
                let is_continuation = self.state_reader.imagination.continuation;
                if !is_continuation {
                    content.fade_out_all();
                }
                let content_dir = std::path::Path::new("/dev/shm/hapax-imagination/content");
                for (i, cref) in self
                    .state_reader
                    .imagination
                    .content_references
                    .iter()
                    .enumerate()
                {
                    if i >= 4 {
                        break;
                    }
                    let path = match cref.kind.as_str() {
                        "camera_frame" => std::path::PathBuf::from(format!(
                            "/dev/shm/hapax-compositor/{}.jpg",
                            cref.source
                        )),
                        "file" => std::path::PathBuf::from(&cref.source),
                        _ => content_dir.join(format!("{}-{}.jpg", new_id, i)),
                    };
                    if path.exists() {
                        content.upload_to_slot(gpu, i, &path, cref.salience as f32, &cref.source);
                    }
                }
                content.current_fragment_id = new_id.clone();
                content.is_continuation = is_continuation;
            }
            content.tick_fades(dt);
            let dims: HashMap<String, f32> = self
                .state_reader
                .imagination
                .dimensions
                .iter()
                .map(|(k, v)| (k.clone(), *v as f32))
                .collect();
            content.update_uniforms(&gpu.queue, &dims, time);
            content.render(&mut encoder, &compositor.composite_view, &gpu.device);
        }

        // Final composited view: content layer output if active, else compositor
        let (final_view, final_texture) = if let Some(content) = &self.content_layer {
            (&content.output_view, &content.output_texture)
        } else {
            (&compositor.composite_view, &compositor.composite_texture)
        };

        feedback_tech.capture_frame(&mut encoder, final_texture);

        if let Some(shm) = &self.shm_output {
            if self.frame_count % 2 == 0 {
                shm.copy_to_staging(&mut encoder, final_texture);
            }
        }

        postprocess.render(&mut encoder, &surface_view, final_view, &gpu.device);

        gpu.queue.submit(std::iter::once(encoder.finish()));
        output.present();

        if let Some(shm) = &mut self.shm_output {
            if self.frame_count % 2 == 0 {
                shm.write_frame(&gpu.device);
            }
        }

        self.frame_count += 1;
        if self.frame_count % 300 == 0 {
            let stance_val = match self.state_reader.smoothed.stance {
                hapax_visual::state::Stance::Nominal => 0.0,
                hapax_visual::state::Stance::Cautious => 0.25,
                hapax_visual::state::Stance::Degraded => 0.5,
                hapax_visual::state::Stance::Critical => 1.0,
            };
            let stats = Response::FrameStats {
                frame_time_ms: (dt * 1000.0) as f64,
                stance: stance_val,
                warmth: self.state_reader.smoothed.color_warmth as f64,
                fps: if dt > 0.0 { (1.0 / dt) as u32 } else { 0 },
            };
            let _ = self.stats_tx.send(stats);

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

// ---------------------------------------------------------------------------
// ApplicationHandler
// ---------------------------------------------------------------------------

impl ApplicationHandler for ImaginationApp {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        if self.window.is_some() {
            return;
        }

        let ws = &self.window_state;
        let attrs = Window::default_attributes()
            .with_title("hapax-imagination")
            .with_inner_size(winit::dpi::LogicalSize::new(ws.width, ws.height));

        let window = Arc::new(event_loop.create_window(attrs).unwrap());

        // Apply persisted window mode
        match ws.mode {
            WindowMode::Fullscreen => {
                window.set_fullscreen(Some(winit::window::Fullscreen::Borderless(None)));
            }
            WindowMode::Maximized => {
                window.set_maximized(true);
            }
            WindowMode::Borderless => {
                let monitors: Vec<_> = window.available_monitors().collect();
                let target = monitors.get(ws.monitor).cloned();
                window.set_fullscreen(Some(winit::window::Fullscreen::Borderless(target)));
            }
            WindowMode::Windowed => {
                window
                    .set_outer_position(winit::dpi::LogicalPosition::new(ws.x, ws.y));
            }
        }
        if ws.always_on_top {
            window.set_window_level(winit::window::WindowLevel::AlwaysOnTop);
        }

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
        let content_layer = ContentLayer::new(&gpu, w, h);
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
        self.content_layer = Some(content_layer);
        self.postprocess = Some(postprocess);
        self.shm_output = Some(shm_output);

        log::info!("Visual surface initialized ({}x{})", w, h);
        window.request_redraw();
    }

    fn window_event(&mut self, event_loop: &ActiveEventLoop, _id: WindowId, event: WindowEvent) {
        match event {
            WindowEvent::CloseRequested => {
                log::info!("Close requested, exiting");
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
                if let Some(content) = &mut self.content_layer {
                    if let Some(gpu) = &self.gpu {
                        content.resize(&gpu.device, w, h);
                    }
                }
                if let Some(shm) = &mut self.shm_output {
                    if let Some(gpu) = &self.gpu {
                        shm.resize(&gpu.device, w, h);
                    }
                }

                // Update persisted window state dimensions
                self.window_state.width = w;
                self.window_state.height = h;
            }
            WindowEvent::Moved(pos) => {
                self.window_state.x = pos.x;
                self.window_state.y = pos.y;
                let _ = self.window_state.save();
            }
            WindowEvent::RedrawRequested => {
                self.process_commands();
                if !self.paused {
                    self.render();
                }
            }
            _ => {}
        }
    }
}

// ---------------------------------------------------------------------------
// UDS server
// ---------------------------------------------------------------------------

async fn run_uds_server(cmd_tx: mpsc::Sender<Command>, stats_rx: mpsc::Receiver<Response>) {
    let socket_path = format!(
        "{}/hapax-imagination.sock",
        std::env::var("XDG_RUNTIME_DIR").unwrap_or_else(|_| "/tmp".into())
    );

    // Remove stale socket
    let _ = std::fs::remove_file(&socket_path);

    let listener = tokio::net::UnixListener::bind(&socket_path).unwrap();
    log::info!("UDS server listening on {}", socket_path);

    // Wrap stats_rx in Arc<Mutex> so we can share across connection handlers
    let stats_rx = Arc::new(std::sync::Mutex::new(stats_rx));

    loop {
        match listener.accept().await {
            Ok((stream, _)) => {
                log::info!("UDS client connected");
                handle_connection(stream, &cmd_tx, &stats_rx).await;
                log::info!("UDS client disconnected");
            }
            Err(e) => {
                log::error!("UDS accept error: {}", e);
            }
        }
    }
}

async fn handle_connection(
    stream: tokio::net::UnixStream,
    cmd_tx: &mpsc::Sender<Command>,
    stats_rx: &Arc<std::sync::Mutex<mpsc::Receiver<Response>>>,
) {
    use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};

    let (reader, mut writer) = stream.into_split();
    let mut lines = BufReader::new(reader).lines();

    loop {
        // Check for any pending stats/responses to relay
        if let Ok(rx) = stats_rx.try_lock() {
            while let Ok(resp) = rx.try_recv() {
                let msg = ipc::serialize_response(&resp);
                if writer.write_all(msg.as_bytes()).await.is_err() {
                    return;
                }
            }
        }

        // Read next command with a short timeout so we can interleave stats relay
        let line = tokio::time::timeout(std::time::Duration::from_millis(50), lines.next_line())
            .await;

        match line {
            Ok(Ok(Some(text))) => {
                if text.trim().is_empty() {
                    continue;
                }
                match ipc::parse_command(&text) {
                    Ok(cmd) => {
                        let is_status = matches!(cmd, Command::Status);
                        if let Err(e) = cmd_tx.send(cmd) {
                            log::error!("Failed to send command to render thread: {}", e);
                            let resp = Response::Error {
                                message: "render thread unavailable".into(),
                            };
                            let msg = ipc::serialize_response(&resp);
                            let _ = writer.write_all(msg.as_bytes()).await;
                            return;
                        }
                        // For Status commands, wait briefly for the response
                        if is_status {
                            tokio::time::sleep(std::time::Duration::from_millis(50)).await;
                            if let Ok(rx) = stats_rx.try_lock() {
                                while let Ok(resp) = rx.try_recv() {
                                    let msg = ipc::serialize_response(&resp);
                                    if writer.write_all(msg.as_bytes()).await.is_err() {
                                        return;
                                    }
                                }
                            }
                        }
                    }
                    Err(e) => {
                        let resp = Response::Error { message: e };
                        let msg = ipc::serialize_response(&resp);
                        if writer.write_all(msg.as_bytes()).await.is_err() {
                            return;
                        }
                    }
                }
            }
            Ok(Ok(None)) => {
                // Client disconnected
                return;
            }
            Ok(Err(e)) => {
                log::warn!("UDS read error: {}", e);
                return;
            }
            Err(_) => {
                // Timeout — loop back to relay stats
                continue;
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

fn main() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    // Ensure shm directories exist
    std::fs::create_dir_all("/dev/shm/hapax-compositor").ok();
    std::fs::create_dir_all("/dev/shm/hapax-stimmung").ok();
    std::fs::create_dir_all("/dev/shm/hapax-imagination/content").ok();

    log::info!("hapax-imagination starting");

    // Channels between winit thread (main) and UDS server (background)
    let (cmd_tx, cmd_rx) = mpsc::channel::<Command>();
    let (stats_tx, stats_rx) = mpsc::channel::<Response>();

    // Spawn UDS server on a background thread with its own tokio runtime
    std::thread::Builder::new()
        .name("imagination-uds".into())
        .spawn(move || {
            let rt = tokio::runtime::Runtime::new().expect("Failed to create tokio runtime");
            rt.block_on(run_uds_server(cmd_tx, stats_rx));
        })
        .expect("Failed to spawn UDS server thread");

    // Run winit event loop on the main thread
    use winit::platform::wayland::EventLoopBuilderExtWayland;
    let event_loop = EventLoop::builder()
        .with_any_thread(true)
        .build()
        .unwrap();
    event_loop.set_control_flow(ControlFlow::Poll);

    let mut app = ImaginationApp::new(cmd_rx, stats_tx);
    if let Err(e) = event_loop.run_app(&mut app) {
        log::error!("Event loop exited with error: {}", e);
    }
}
