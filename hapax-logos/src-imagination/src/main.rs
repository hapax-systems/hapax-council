//! hapax-imagination — standalone wgpu visual surface with UDS control.
//!
//! Main thread: winit event loop driving the GPU render pipeline.
//! Background thread: tokio runtime running a Unix domain socket server
//! for external control (window management, render commands, status queries).

mod ipc;
mod window_state;

use std::sync::mpsc;
use std::sync::Arc;
use std::time::Instant;

use winit::application::ApplicationHandler;
use winit::event::WindowEvent;
use winit::event_loop::{ActiveEventLoop, ControlFlow, EventLoop};
use winit::window::{Window, WindowId};

use hapax_visual::dynamic_pipeline::DynamicPipeline;
use hapax_visual::gpu::GpuContext;
use hapax_visual::state::StateReader;

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

    dynamic_pipeline: Option<DynamicPipeline>,
    state_reader: StateReader,

    start_time: Instant,
    last_frame: Instant,
    frame_count: u64,
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
            dynamic_pipeline: None,
            state_reader: StateReader::new(),
            start_time: Instant::now(),
            last_frame: Instant::now(),
            frame_count: 0,
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

        if let Some(pipeline) = &mut self.dynamic_pipeline {
            pipeline.render(
                &gpu.device,
                &gpu.queue,
                &surface_view,
                gpu.format,
                &self.state_reader,
                dt,
                time,
            );
        }

        output.present();

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
                "frame_time: {:.2}ms | stance: {:?} | warmth: {:.2}",
                dt * 1000.0,
                self.state_reader.smoothed.stance,
                self.state_reader.smoothed.color_warmth,
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

        let dynamic_pipeline = DynamicPipeline::new(&gpu.device, &gpu.queue, w, h);

        self.window = Some(window.clone());
        self.gpu = Some(gpu);
        self.dynamic_pipeline = Some(dynamic_pipeline);

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
                if let Some(pipeline) = &mut self.dynamic_pipeline {
                    if let Some(gpu) = &self.gpu {
                        pipeline.resize(&gpu.device, w, h);
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
