# Imagination Surface Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the wgpu visual render pipeline from Tauri's in-process bridge into a standalone `hapax-imagination` binary with its own winit window, UDS IPC, and systemd unit.

**Architecture:** Create a `hapax-visual` library crate containing all GPU/render code. The `hapax-imagination` binary depends on this crate and owns the winit window + UDS server. Tauri drops its winit/wgpu dependencies and talks to the binary via UDS for control, `/dev/shm` for data (unchanged).

**Tech Stack:** Rust (wgpu 24, winit 0.30, tokio, serde_json), Unix domain sockets, systemd

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `hapax-logos/crates/hapax-visual/Cargo.toml` | Create | Library crate manifest |
| `hapax-logos/crates/hapax-visual/src/lib.rs` | Create | Re-export all visual modules |
| `hapax-logos/crates/hapax-visual/src/*.rs` | Move | gpu, compositor, content_layer, control (renamed from state), output, postprocess, state, techniques |
| `hapax-logos/crates/hapax-visual/src/techniques/*.rs` | Move | 6 shader techniques |
| `hapax-logos/crates/hapax-visual/src/shaders/*.wgsl` | Move | All WGSL shaders |
| `hapax-logos/src-imagination/Cargo.toml` | Create | Binary crate manifest |
| `hapax-logos/src-imagination/src/main.rs` | Create | winit event loop + render + UDS server |
| `hapax-logos/src-imagination/src/ipc.rs` | Create | JSON message protocol |
| `hapax-logos/src-imagination/src/window_state.rs` | Create | Persistence to JSON |
| `hapax-logos/src-tauri/Cargo.toml` | Modify | Remove winit/wgpu/pollster/bytemuck/glam, add hapax-visual as optional |
| `hapax-logos/src-tauri/src/main.rs` | Modify | Remove `spawn_visual_surface`, add UDS client init |
| `hapax-logos/src-tauri/src/visual/mod.rs` | Modify | Remove bridge, add client |
| `hapax-logos/src-tauri/src/visual/client.rs` | Create | UDS client for imagination binary |
| `hapax-logos/src-tauri/src/visual/control.rs` | Modify | `toggle_visual_window` uses UDS client |
| `hapax-logos/src-tauri/src/visual/bridge.rs` | Delete | Replaced by standalone binary |
| `systemd/hapax-imagination.service` | Create | Systemd unit |

---

### Task 1: Create hapax-visual library crate

**Files:**
- Create: `hapax-logos/crates/hapax-visual/Cargo.toml`
- Create: `hapax-logos/crates/hapax-visual/src/lib.rs`

- [ ] **Step 1: Create crate directory structure**

```bash
cd ~/projects/hapax-council/hapax-logos
mkdir -p crates/hapax-visual/src/techniques
mkdir -p crates/hapax-visual/src/shaders
```

- [ ] **Step 2: Write Cargo.toml**

Create `hapax-logos/crates/hapax-visual/Cargo.toml`:

```toml
[package]
name = "hapax-visual"
version = "0.1.0"
edition = "2021"

[dependencies]
wgpu = "24"
winit = "0.30"
bytemuck = { version = "1", features = ["derive"] }
glam = "0.29"
notify = "7"
pollster = "0.4"
log = "0.4"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
turbojpeg = "1"
```

- [ ] **Step 3: Write lib.rs**

Create `hapax-logos/crates/hapax-visual/src/lib.rs`:

```rust
pub mod compositor;
pub mod content_layer;
pub mod control;
pub mod gpu;
pub mod output;
pub mod postprocess;
pub mod state;
pub mod techniques;
```

- [ ] **Step 4: Verify the crate structure exists**

```bash
ls crates/hapax-visual/src/
```

Expected: `lib.rs techniques/`

- [ ] **Step 5: Commit**

```bash
git add crates/hapax-visual/
git commit -m "feat(visual): scaffold hapax-visual library crate"
```

---

### Task 2: Move render code to hapax-visual crate

**Files:**
- Move: `src-tauri/src/visual/{gpu,compositor,content_layer,output,postprocess,state}.rs` → `crates/hapax-visual/src/`
- Move: `src-tauri/src/visual/techniques/` → `crates/hapax-visual/src/techniques/`
- Move: `src-tauri/src/visual/shaders/` → `crates/hapax-visual/src/shaders/`
- Keep: `src-tauri/src/visual/{bridge,control,http_server,mod}.rs` (Tauri-specific)

- [ ] **Step 1: Move source files**

```bash
cd ~/projects/hapax-council/hapax-logos

# Move core render modules
for f in gpu.rs compositor.rs content_layer.rs output.rs postprocess.rs state.rs; do
  cp src-tauri/src/visual/$f crates/hapax-visual/src/$f
done

# Move techniques directory
cp -r src-tauri/src/visual/techniques/* crates/hapax-visual/src/techniques/

# Move shaders
cp -r src-tauri/src/visual/shaders/* crates/hapax-visual/src/shaders/

# Copy techniques mod.rs
cp src-tauri/src/visual/techniques/mod.rs crates/hapax-visual/src/techniques/mod.rs 2>/dev/null || true
```

- [ ] **Step 2: Fix internal imports in moved files**

In each moved `.rs` file, replace `use super::` and `use crate::visual::` references with `use crate::` since they're now at the crate root.

For example, in `crates/hapax-visual/src/compositor.rs`, change:
```rust
use super::gpu::GpuContext;
```
to:
```rust
use crate::gpu::GpuContext;
```

Apply this pattern across all moved files. The `super::` prefix mapped to the old `visual` module; now they're siblings in the crate root.

- [ ] **Step 3: Fix shader include paths**

The techniques load shaders with `include_str!`. Paths need updating since the shaders moved relative to the source files.

In each technique file, shader includes like:
```rust
include_str!("../shaders/gradient.wgsl")
```
should become:
```rust
include_str!("../shaders/gradient.wgsl")
```

The relative path from `techniques/*.rs` to `shaders/*.wgsl` is the same (`../shaders/`) so these should not need changes. Verify by checking the directory structure matches.

- [ ] **Step 4: Verify crate compiles**

```bash
cd ~/projects/hapax-council/hapax-logos/crates/hapax-visual
cargo check 2>&1 | head -30
```

Expected: Compiles (or known errors from missing techniques/mod.rs — fix if needed).

- [ ] **Step 5: Commit**

```bash
git add crates/hapax-visual/
git commit -m "feat(visual): move render pipeline to hapax-visual crate"
```

---

### Task 3: Create IPC protocol module

**Files:**
- Create: `hapax-logos/src-imagination/Cargo.toml`
- Create: `hapax-logos/src-imagination/src/ipc.rs`

- [ ] **Step 1: Create binary crate scaffold**

```bash
cd ~/projects/hapax-council/hapax-logos
mkdir -p src-imagination/src
```

- [ ] **Step 2: Write Cargo.toml**

Create `hapax-logos/src-imagination/Cargo.toml`:

```toml
[package]
name = "hapax-imagination"
version = "0.1.0"
edition = "2021"

[[bin]]
name = "hapax-imagination"
path = "src/main.rs"

[dependencies]
hapax-visual = { path = "../crates/hapax-visual" }
winit = "0.30"
tokio = { version = "1", features = ["full"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
log = "0.4"
env_logger = "0.11"
pollster = "0.4"
dirs = "6"
```

- [ ] **Step 3: Write ipc.rs**

Create `hapax-logos/src-imagination/src/ipc.rs`:

```rust
//! Newline-delimited JSON protocol over Unix domain sockets.

use serde::{Deserialize, Serialize};

// --- Inbound commands ---

#[derive(Debug, Deserialize)]
#[serde(tag = "type")]
#[serde(rename_all = "lowercase")]
pub enum Command {
    Window {
        action: WindowAction,
    },
    Render {
        action: RenderAction,
    },
    Status,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WindowAction {
    Fullscreen,
    Maximized,
    Windowed {
        x: i32,
        y: i32,
        w: u32,
        h: u32,
    },
    Borderless {
        monitor: usize,
    },
    Hide,
    Show,
    AlwaysOnTop {
        enabled: bool,
    },
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RenderAction {
    SetFps { fps: u32 },
    Pause,
    Resume,
}

// --- Outbound responses ---

#[derive(Debug, Serialize)]
#[serde(tag = "type")]
#[serde(rename_all = "lowercase")]
pub enum Response {
    Status {
        visible: bool,
        mode: String,
        monitor: usize,
        fps: f32,
        frame_count: u64,
        dimensions: [u32; 2],
    },
    Ack {
        #[serde(rename = "for")]
        for_type: String,
    },
    Error {
        message: String,
    },
    FrameStats {
        frame_time_ms: f32,
        stance: String,
        warmth: f32,
        fps: f32,
    },
}

/// Parse a single line of JSON into a Command.
pub fn parse_command(line: &str) -> Result<Command, String> {
    serde_json::from_str(line).map_err(|e| format!("invalid command: {e}"))
}

/// Serialize a response to a JSON line (with trailing newline).
pub fn serialize_response(resp: &Response) -> String {
    let mut s = serde_json::to_string(resp).unwrap_or_else(|_| r#"{"type":"error","message":"serialize failed"}"#.to_string());
    s.push('\n');
    s
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_fullscreen_command() {
        let cmd = parse_command(r#"{"type":"window","action":"fullscreen"}"#).unwrap();
        assert!(matches!(cmd, Command::Window { action: WindowAction::Fullscreen }));
    }

    #[test]
    fn parse_windowed_command() {
        let cmd = parse_command(r#"{"type":"window","action":"windowed","x":100,"y":200,"w":1920,"h":1080}"#).unwrap();
        assert!(matches!(cmd, Command::Window { action: WindowAction::Windowed { x: 100, y: 200, w: 1920, h: 1080 } }));
    }

    #[test]
    fn parse_status_command() {
        let cmd = parse_command(r#"{"type":"status"}"#).unwrap();
        assert!(matches!(cmd, Command::Status));
    }

    #[test]
    fn parse_render_pause() {
        let cmd = parse_command(r#"{"type":"render","action":"pause"}"#).unwrap();
        assert!(matches!(cmd, Command::Render { action: RenderAction::Pause }));
    }

    #[test]
    fn serialize_ack() {
        let resp = Response::Ack { for_type: "window".into() };
        let s = serialize_response(&resp);
        assert!(s.contains(r#""type":"ack""#));
        assert!(s.ends_with('\n'));
    }

    #[test]
    fn serialize_status() {
        let resp = Response::Status {
            visible: true,
            mode: "fullscreen".into(),
            monitor: 0,
            fps: 60.0,
            frame_count: 1000,
            dimensions: [2560, 1440],
        };
        let s = serialize_response(&resp);
        assert!(s.contains("2560"));
    }

    #[test]
    fn parse_invalid_returns_error() {
        assert!(parse_command("not json").is_err());
    }
}
```

- [ ] **Step 4: Verify tests pass**

```bash
cd ~/projects/hapax-council/hapax-logos/src-imagination
cargo test 2>&1 | tail -15
```

Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src-imagination/
git commit -m "feat(imagination): add IPC protocol with tests"
```

---

### Task 4: Create window state persistence

**Files:**
- Create: `hapax-logos/src-imagination/src/window_state.rs`

- [ ] **Step 1: Write window_state.rs**

Create `hapax-logos/src-imagination/src/window_state.rs`:

```rust
//! Persist and restore window position, size, and mode.

use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct WindowState {
    pub mode: WindowMode,
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
    pub monitor: usize,
    pub always_on_top: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum WindowMode {
    Windowed,
    Maximized,
    Fullscreen,
    Borderless,
}

impl Default for WindowState {
    fn default() -> Self {
        Self {
            mode: WindowMode::Windowed,
            x: 0,
            y: 0,
            width: 1920,
            height: 1080,
            monitor: 0,
            always_on_top: false,
        }
    }
}

fn state_path() -> PathBuf {
    let config_dir = dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from("/tmp"))
        .join("hapax-imagination");
    config_dir.join("window.json")
}

impl WindowState {
    pub fn load() -> Self {
        let path = state_path();
        match std::fs::read_to_string(&path) {
            Ok(data) => serde_json::from_str(&data).unwrap_or_default(),
            Err(_) => Self::default(),
        }
    }

    pub fn save(&self) {
        let path = state_path();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).ok();
        }
        if let Ok(json) = serde_json::to_string_pretty(self) {
            std::fs::write(&path, json).ok();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    #[test]
    fn default_state() {
        let s = WindowState::default();
        assert_eq!(s.width, 1920);
        assert_eq!(s.height, 1080);
        assert!(!s.always_on_top);
        assert_eq!(s.mode, WindowMode::Windowed);
    }

    #[test]
    fn roundtrip_json() {
        let state = WindowState {
            mode: WindowMode::Fullscreen,
            x: 100,
            y: 200,
            width: 2560,
            height: 1440,
            monitor: 1,
            always_on_top: true,
        };
        let json = serde_json::to_string(&state).unwrap();
        let back: WindowState = serde_json::from_str(&json).unwrap();
        assert_eq!(state, back);
    }

    #[test]
    fn deserialize_corrupt_returns_default() {
        let result: Result<WindowState, _> = serde_json::from_str("not json");
        assert!(result.is_err());
        // load() would return default on error
    }
}
```

- [ ] **Step 2: Run tests**

```bash
cd ~/projects/hapax-council/hapax-logos/src-imagination
cargo test 2>&1 | tail -15
```

Expected: 10 tests pass (7 ipc + 3 window_state).

- [ ] **Step 3: Commit**

```bash
git add src-imagination/src/window_state.rs
git commit -m "feat(imagination): add window state persistence with tests"
```

---

### Task 5: Create main.rs — winit event loop + UDS server

**Files:**
- Create: `hapax-logos/src-imagination/src/main.rs`

- [ ] **Step 1: Write main.rs**

Create `hapax-logos/src-imagination/src/main.rs`. This is the largest file — it hosts the winit event loop, renders via hapax-visual, and runs a tokio UDS server on a background thread.

The structure follows the existing `bridge.rs` pattern closely. Key differences:
- Window is created from `WindowState::load()` (persisted size/position)
- UDS server runs on a tokio runtime in a background thread
- Window commands arrive via a `std::sync::mpsc` channel from the UDS server to the winit thread
- Frame stats are sent back via another channel

The main.rs should:

1. Initialize `env_logger`
2. Load `WindowState`
3. Create winit `EventLoop` with `with_any_thread(true)` (Wayland)
4. In `resumed()`: create window from saved state, init `GpuContext`, init all techniques/compositor/content_layer/postprocess/shm_output/state_reader (identical to bridge.rs lines 277-299)
5. Spawn tokio runtime on background thread for UDS server at `$XDG_RUNTIME_DIR/hapax-imagination.sock`
6. UDS server: accept connections, read newline-delimited JSON, parse via `ipc::parse_command`, send `WindowAction` commands through channel, respond with `ipc::Response`
7. In `window_event()` handler: process resize (propagate to all techniques), close, redraw
8. In render: identical to bridge.rs `render()` method (lines 89-257), but instead of emitting Tauri events, send `FrameStats` through the stats channel for the UDS server to relay

Window commands received from the channel are applied in the event loop:
- `Fullscreen` → `window.set_fullscreen(Some(Fullscreen::Borderless(None)))`
- `Maximized` → `window.set_maximized(true)`
- `Windowed{x,y,w,h}` → `window.set_outer_position()`, `window.request_inner_size()`
- `Borderless{monitor}` → `window.set_fullscreen(Some(Fullscreen::Borderless(monitor)))`
- `Hide/Show` → `window.set_visible()`
- `AlwaysOnTop` → `window.set_window_level(WindowLevel::AlwaysOnTop/Normal)`

On mode change, save `WindowState`.

The implementation should closely follow bridge.rs but replace `AppHandle<R>` with the channel-based communication. Read the existing bridge.rs at `hapax-logos/src-tauri/src/visual/bridge.rs` for the exact render loop, technique initialization, and content layer logic.

- [ ] **Step 2: Create a stub main.rs that compiles**

Start with a minimal main.rs that proves the crate structure works:

```rust
mod ipc;
mod window_state;

fn main() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();
    log::info!("hapax-imagination starting");

    let state = window_state::WindowState::load();
    log::info!("Window state: {:?}", state);

    // Full implementation in next step
    log::info!("hapax-imagination exiting (stub)");
}
```

- [ ] **Step 3: Verify it compiles and runs**

```bash
cd ~/projects/hapax-council/hapax-logos/src-imagination
cargo build 2>&1 | tail -10
cargo run 2>&1 | head -5
```

Expected: Compiles, prints startup messages, exits.

- [ ] **Step 4: Commit stub**

```bash
git add src-imagination/src/main.rs
git commit -m "feat(imagination): stub main.rs — compiles with hapax-visual crate"
```

- [ ] **Step 5: Implement full main.rs**

Replace stub with full implementation. This is the core task — the implementer should read `hapax-logos/src-tauri/src/visual/bridge.rs` and port the `VisualApp` struct and its render loop, replacing:
- `AppHandle<R>` → `std::sync::mpsc::Sender<ipc::Response>` for stats
- `static WINDOW_VISIBLE` → receive `WindowAction` from `mpsc::Receiver`
- `spawn_visual_surface()` → direct `EventLoop::run_app()` in main
- Tauri event emit → channel send

Add UDS server:
- Bind `$XDG_RUNTIME_DIR/hapax-imagination.sock` (remove stale socket first)
- Accept one connection at a time (single operator)
- Read lines, parse, dispatch to window command channel
- Write responses back

- [ ] **Step 6: Verify it compiles**

```bash
cd ~/projects/hapax-council/hapax-logos/src-imagination
cargo build 2>&1 | tail -10
```

Expected: Compiles.

- [ ] **Step 7: Commit**

```bash
git add src-imagination/src/main.rs
git commit -m "feat(imagination): full main.rs — winit render loop + UDS server"
```

---

### Task 6: Create Tauri UDS client

**Files:**
- Create: `hapax-logos/src-tauri/src/visual/client.rs`
- Modify: `hapax-logos/src-tauri/src/visual/mod.rs`
- Modify: `hapax-logos/src-tauri/src/visual/control.rs`

- [ ] **Step 1: Write client.rs**

Create `hapax-logos/src-tauri/src/visual/client.rs`:

```rust
//! UDS client for communicating with the hapax-imagination binary.

use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::sync::Mutex;
use std::time::Duration;

static CONNECTION: Mutex<Option<UnixStream>> = Mutex::new(None);

fn socket_path() -> String {
    let runtime_dir = std::env::var("XDG_RUNTIME_DIR")
        .unwrap_or_else(|_| format!("/run/user/{}", unsafe { libc::getuid() }));
    format!("{}/hapax-imagination.sock", runtime_dir)
}

fn connect() -> Option<UnixStream> {
    let path = socket_path();
    UnixStream::connect(&path)
        .ok()
        .map(|s| {
            s.set_read_timeout(Some(Duration::from_secs(2))).ok();
            s.set_write_timeout(Some(Duration::from_secs(2))).ok();
            s
        })
}

fn get_or_connect() -> Option<UnixStream> {
    let mut guard = CONNECTION.lock().ok()?;
    if guard.is_none() {
        *guard = connect();
    }
    // Clone the stream for this call (UnixStream implements try_clone)
    guard.as_ref().and_then(|s| s.try_clone().ok())
}

/// Send a JSON command and read the response line.
pub fn send_command(json: &str) -> Result<String, String> {
    let mut stream = get_or_connect().ok_or("imagination binary not connected")?;

    let mut msg = json.to_string();
    if !msg.ends_with('\n') {
        msg.push('\n');
    }

    stream
        .write_all(msg.as_bytes())
        .map_err(|e| {
            // Connection broken — clear cached connection
            if let Ok(mut guard) = CONNECTION.lock() {
                *guard = None;
            }
            format!("write failed: {e}")
        })?;

    let mut reader = BufReader::new(&stream);
    let mut response = String::new();
    reader
        .read_line(&mut response)
        .map_err(|e| {
            if let Ok(mut guard) = CONNECTION.lock() {
                *guard = None;
            }
            format!("read failed: {e}")
        })?;

    Ok(response)
}

/// Convenience: send a window command.
pub fn window_command(action: &str) -> Result<String, String> {
    send_command(&format!(r#"{{"type":"window","action":"{}"}}"#, action))
}

/// Convenience: request status.
pub fn status() -> Result<String, String> {
    send_command(r#"{"type":"status"}"#)
}

/// Check if imagination binary is reachable.
pub fn is_connected() -> bool {
    status().is_ok()
}
```

Note: This uses `libc::getuid()` — add `libc` to `src-tauri/Cargo.toml` dependencies if not already present. Alternatively, use `std::env::var("XDG_RUNTIME_DIR")` with a fallback that doesn't need libc.

- [ ] **Step 2: Update mod.rs**

Replace `hapax-logos/src-tauri/src/visual/mod.rs`:

```rust
pub mod client;
pub mod control;
pub mod http_server;
```

(Removes `bridge`, `compositor`, `content_layer`, `gpu`, `output`, `postprocess`, `state`, `techniques` — all moved to `hapax-visual` crate.)

- [ ] **Step 3: Update control.rs — toggle_visual_window**

In `hapax-logos/src-tauri/src/visual/control.rs`, replace:

```rust
#[tauri::command]
pub fn toggle_visual_window(visible: bool) -> bool {
    super::bridge::set_window_visible(visible);
    visible
}
```

With:

```rust
#[tauri::command]
pub fn toggle_visual_window(visible: bool) -> bool {
    let action = if visible { "show" } else { "hide" };
    match super::client::window_command(action) {
        Ok(_) => visible,
        Err(e) => {
            log::warn!("Failed to toggle imagination window: {}", e);
            false
        }
    }
}
```

- [ ] **Step 4: Update main.rs — remove spawn_visual_surface**

In `hapax-logos/src-tauri/src/main.rs`, remove lines 127-133:

```rust
            // Spawn the wgpu visual surface on a dedicated thread
            // Skip if HAPAX_NO_VISUAL=1 (useful when visual surface conflicts with Wayland)
            if std::env::var("HAPAX_NO_VISUAL").unwrap_or_default() != "1" {
                visual::bridge::spawn_visual_surface(app.handle().clone());
            } else {
                log::info!("Visual surface disabled (HAPAX_NO_VISUAL=1)");
            }
```

Replace with:

```rust
            // Visual surface runs as separate hapax-imagination binary (systemd)
            // Check connectivity at startup
            if visual::client::is_connected() {
                log::info!("Imagination surface connected via UDS");
            } else {
                log::warn!("Imagination surface not available — visual commands will fail gracefully");
            }
```

- [ ] **Step 5: Update Cargo.toml — remove visual dependencies**

In `hapax-logos/src-tauri/Cargo.toml`, remove these dependencies:

```toml
wgpu = "24"
winit = "0.30"
bytemuck = { version = "1", features = ["derive"] }
glam = "0.29"
pollster = "0.4"
```

Keep: `notify` (may be used elsewhere), `turbojpeg` (remove if only used by visual), `axum` (used by http_server).

Check if `turbojpeg` is used outside `visual/output.rs`. If not, remove it too.

- [ ] **Step 6: Verify Tauri compiles**

```bash
cd ~/projects/hapax-council/hapax-logos/src-tauri
cargo check 2>&1 | head -30
```

Fix any remaining import errors. The http_server.rs should still compile — it only reads files from `/dev/shm`, no GPU dependencies.

- [ ] **Step 7: Commit**

```bash
git add src-tauri/
git commit -m "feat(tauri): replace in-process visual bridge with UDS client"
```

---

### Task 7: Delete bridge.rs and clean up

**Files:**
- Delete: `hapax-logos/src-tauri/src/visual/bridge.rs`
- Delete: moved source files from `src-tauri/src/visual/` (gpu.rs, compositor.rs, etc.)

- [ ] **Step 1: Delete bridge.rs**

```bash
cd ~/projects/hapax-council/hapax-logos
rm src-tauri/src/visual/bridge.rs
```

- [ ] **Step 2: Delete moved render files**

Only delete files that were moved to `crates/hapax-visual/` and are no longer imported by `src-tauri`:

```bash
rm src-tauri/src/visual/gpu.rs
rm src-tauri/src/visual/compositor.rs
rm src-tauri/src/visual/content_layer.rs
rm src-tauri/src/visual/output.rs
rm src-tauri/src/visual/postprocess.rs
rm src-tauri/src/visual/state.rs
rm -rf src-tauri/src/visual/techniques/
rm -rf src-tauri/src/visual/shaders/
```

- [ ] **Step 3: Verify Tauri still compiles**

```bash
cd ~/projects/hapax-council/hapax-logos/src-tauri
cargo check 2>&1 | head -20
```

Expected: Clean compile.

- [ ] **Step 4: Verify imagination binary still compiles**

```bash
cd ~/projects/hapax-council/hapax-logos/src-imagination
cargo build 2>&1 | tail -10
```

Expected: Clean compile.

- [ ] **Step 5: Commit**

```bash
git add -A src-tauri/src/visual/
git commit -m "chore: delete bridge.rs and moved render files from src-tauri"
```

---

### Task 8: Create systemd unit

**Files:**
- Create: `systemd/hapax-imagination.service`

- [ ] **Step 1: Write service file**

Create `hapax-logos/../systemd/hapax-imagination.service` (in the council root):

```ini
[Unit]
Description=Hapax Imagination — GPU visual surface
After=hapax-secrets.service
Requires=hapax-secrets.service

[Service]
Type=simple
ExecStart=%h/.local/bin/hapax-imagination
Restart=always
RestartSec=2
MemoryMax=4G
Environment=XDG_RUNTIME_DIR=%t
Environment=__NV_DISABLE_EXPLICIT_SYNC=1
Environment=RUST_LOG=info

[Install]
WantedBy=default.target
```

- [ ] **Step 2: Commit**

```bash
git add systemd/hapax-imagination.service
git commit -m "feat(systemd): add hapax-imagination.service"
```

---

### Task 9: Workspace Cargo.toml and build verification

**Files:**
- Create or modify: workspace-level Cargo configuration

- [ ] **Step 1: Create workspace Cargo.toml**

Currently `hapax-logos/` has no workspace Cargo.toml — `src-tauri/Cargo.toml` is the only crate. Create `hapax-logos/Cargo.toml`:

```toml
[workspace]
members = [
    "src-tauri",
    "crates/hapax-visual",
    "src-imagination",
]
resolver = "2"
```

Note: `src-tauri/Cargo.toml` may need `[workspace]` removed if it has one, or this may conflict with Tauri's build system. Check Tauri's expectations — `tauri-build` may require the crate to be the workspace root. If so, add workspace members to `src-tauri/Cargo.toml` instead.

- [ ] **Step 2: Build entire workspace**

```bash
cd ~/projects/hapax-council/hapax-logos
cargo build --workspace 2>&1 | tail -20
```

Expected: All three crates compile.

- [ ] **Step 3: Run all tests**

```bash
cargo test --workspace 2>&1 | tail -20
```

Expected: IPC tests (7) + window_state tests (3) = 10 tests pass.

- [ ] **Step 4: Install binary**

```bash
cargo build --release --bin hapax-imagination
cp target/release/hapax-imagination ~/.local/bin/
```

- [ ] **Step 5: Commit**

```bash
git add hapax-logos/Cargo.toml
git commit -m "feat: add workspace Cargo.toml for hapax-visual + hapax-imagination"
```

---

### Task 10: Integration test and PR

- [ ] **Step 1: Test the imagination binary runs**

```bash
~/.local/bin/hapax-imagination &
sleep 2
# Send a status command via socat
echo '{"type":"status"}' | socat - UNIX-CONNECT:$XDG_RUNTIME_DIR/hapax-imagination.sock
# Should get a JSON status response
kill %1
```

- [ ] **Step 2: Test Tauri connectivity**

```bash
# Start imagination binary
~/.local/bin/hapax-imagination &
sleep 2

# Start Tauri in dev
cd ~/projects/hapax-council/hapax-logos
./scripts/dev.sh &
sleep 10

# Check Tauri logs for "Imagination surface connected via UDS"
# Toggle window via Tauri invoke (from browser console or command relay)
kill %1 %2
```

- [ ] **Step 3: Install systemd unit**

```bash
cp ~/projects/hapax-council/systemd/hapax-imagination.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable hapax-imagination
systemctl --user start hapax-imagination
systemctl --user status hapax-imagination
```

- [ ] **Step 4: Create feature branch and PR**

```bash
cd ~/projects/hapax-council
git push -u origin feat/imagination-surface
gh pr create --title "feat: extract imagination surface to standalone binary" --body "$(cat <<'PREOF'
## Summary

Extract wgpu visual render pipeline from Tauri in-process bridge to standalone `hapax-imagination` binary.

- **hapax-visual** library crate: all GPU/render code (6 techniques, compositor, content layer, postprocess, shm output)
- **hapax-imagination** binary: winit window + UDS server + render loop
- **Tauri UDS client**: replaces in-process bridge calls with socket commands
- **Systemd unit**: independent lifecycle, GPU memory capped
- **Window management**: fullscreen, borderless, multi-monitor, always-on-top, persisted across restarts

## Test plan

- [ ] `cargo test --workspace` in hapax-logos/
- [ ] hapax-imagination binary starts, renders to window, accepts UDS commands
- [ ] Tauri connects via UDS, toggle_visual_window works
- [ ] systemd service starts/stops/restarts cleanly
- [ ] shm frame path still works (HTTP frame server on :8053)
PREOF
)"
```

- [ ] **Step 5: Monitor CI, fix failures, merge when green**
