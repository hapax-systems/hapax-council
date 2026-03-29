# Imagination Surface Extraction

**Date:** 2026-03-28
**Queue Item:** TBD (alpha-proposed)
**Status:** Design approved

## Overview

Extract the visual render pipeline from Tauri's in-process bridge into a standalone binary (`hapax-imagination`). The imagination window becomes a first-class, independently-managed GPU surface with its own lifecycle, flexible window management, and bidirectional IPC with Tauri.

## Drivers

1. **Independent lifecycle** — imagination window survives Tauri webview crashes, can run standalone for demos
2. **Flexible display** — multi-monitor placement, fullscreen, borderless, always-on-top, dynamic resolution
3. **Architecture alignment** — separate binary with socket IPC matches hapax-voice pattern; filesystem-as-bus for data, sockets for control

## Binary & Process Lifecycle

**New binary:** `hapax-imagination` — standalone Rust binary in `hapax-logos/src-imagination/`. Owns a winit window, wgpu render pipeline, and a UDS server. Installed to `~/.local/bin/hapax-imagination`.

**Systemd unit:** `hapax-imagination.service` — `Type=simple`, `Restart=always`, `After=hapax-secrets.service`. Runs independently of Tauri. GPU memory limit via `MemoryMax=`.

**Tauri relationship:** Tauri is a client of the imagination window, not its parent. On startup, Tauri connects to the UDS. If the socket is unavailable, Tauri operates without the imagination window (graceful degradation — the shm frame path still works for the webview background).

**Build:** Separate Cargo binary target in the existing `hapax-logos/` workspace, sharing the `hapax-visual` library crate. `cargo build --bin hapax-imagination`.

## Window Management

**Dynamic resolution:** winit window uses the current monitor's native resolution. On startup, query via `window.current_monitor()` and size to match. On monitor change (drag to different screen), handle `ScaleFactorChanged` and `Moved` events — resize all techniques, compositor, shm output to new dimensions.

**Window modes** (commanded via UDS):

| Mode | Behavior |
|------|----------|
| `windowed(x, y, w, h)` | Positioned, decorated |
| `maximized` | Maximized on current monitor |
| `fullscreen` | Exclusive fullscreen on current monitor |
| `borderless(monitor_id)` | Borderless fullscreen on specified monitor |
| `hide` / `show` | Visibility toggle |
| `always_on_top(bool)` | Overlay mode |

**Persistence:** Window state (position, size, mode, monitor) saved to `~/.config/hapax-imagination/window.json` on every mode change. Restored on startup. Falls back to primary monitor if saved monitor is unavailable.

## IPC Protocol

**Socket:** `$XDG_RUNTIME_DIR/hapax-imagination.sock` (UDS, stream mode).

**Protocol:** Newline-delimited JSON, same pattern as hapax-voice's hotkey socket.

### Commands (Tauri → imagination)

```json
{"type": "window", "action": "fullscreen"}
{"type": "window", "action": "windowed", "x": 100, "y": 100, "w": 1920, "h": 1080}
{"type": "window", "action": "borderless", "monitor": 0}
{"type": "window", "action": "maximized"}
{"type": "window", "action": "hide"}
{"type": "window", "action": "show"}
{"type": "window", "action": "always_on_top", "enabled": true}
{"type": "render", "action": "set_fps", "fps": 30}
{"type": "render", "action": "pause"}
{"type": "render", "action": "resume"}
{"type": "status"}
```

### Responses (imagination → Tauri)

```json
{"type": "status", "visible": true, "mode": "fullscreen", "monitor": 0, "fps": 30.1, "frame_count": 12400, "dimensions": [2560, 1440]}
{"type": "ack", "for": "window"}
{"type": "error", "message": "invalid monitor index"}
```

### Events (imagination → Tauri, unsolicited)

```json
{"type": "frame_stats", "frame_time_ms": 16.2, "stance": "Ambient", "warmth": 0.45, "fps": 61.0}
```

Emitted every 300 frames, replacing the current in-process Tauri event emit.

### Data path (unchanged)

Stimmung, imagination fragments, control.json — all via `/dev/shm` files. The UDS is for control and status only. This preserves the filesystem-as-bus architecture.

## Code Extraction & Shared Crate

### New library crate: `crates/hapax-visual/`

Contains all render pipeline code shared between the imagination binary and any future consumer:

- `gpu.rs` — `GpuContext` (takes `Arc<Window>`, creates wgpu surface/device/queue)
- `compositor.rs` — 6-layer compositor
- `content_layer.rs` — imagination texture pool (4 slots), 9-dimension WGSL shader
- `control.rs` — control.json reader
- `output.rs` — `ShmOutput` (JPEG to `/dev/shm`)
- `postprocess.rs` — post-processing pipeline
- `state.rs` — `StateReader` (polls stimmung, control, imagination state)
- `techniques/` — gradient, reaction_diff, voronoi, wave, physarum, feedback
- `shaders/` — all .wgsl files

### New binary: `src-imagination/`

```
src-imagination/
  src/
    main.rs            # winit event loop, render loop, UDS server
    ipc.rs             # socket protocol parsing/handling
    window_state.rs    # persistence to ~/.config/hapax-imagination/window.json
```

### Tauri side: `src-tauri/src/visual/`

```
src-tauri/src/visual/
  mod.rs              # re-exports + client
  http_server.rs      # serves shm frames (no GPU dependency)
  client.rs           # new UDS client for commanding imagination binary
```

### Workspace layout

```
hapax-logos/
  Cargo.toml          # workspace members: src-tauri, crates/hapax-visual, src-imagination
  crates/
    hapax-visual/
      Cargo.toml
      src/
        lib.rs         # pub mod gpu, compositor, techniques, etc.
  src-tauri/           # existing Tauri app
  src-imagination/     # new standalone binary
    Cargo.toml
    src/
```

## Tauri Integration

Existing Tauri commands become UDS client calls:

| Tauri command | Current | New |
|--------------|---------|-----|
| `toggle_visual_window` | `set_window_visible()` in-process | UDS `{"type":"window","action":"show/hide"}` |
| `set_visual_layer_param` | writes `control.json` | writes `control.json` (unchanged) |
| `get_visual_surface_state` | reads in-process state | UDS `{"type":"status"}` |
| `set_visual_stance` | writes stance file | writes stance file (unchanged) |
| `visual_ping` | checks thread alive | UDS `{"type":"status"}` with timeout |
| `set_window_position` | not implemented | UDS `{"type":"window","action":"windowed",...}` |
| `set_window_fullscreen` | not implemented | UDS `{"type":"window","action":"fullscreen"}` |
| `set_window_always_on_top` | not implemented | UDS `{"type":"window","action":"always_on_top",...}` |

**Frame stats relay:** Imagination binary emits `frame_stats` over UDS every 300 frames. Tauri client receives these and re-emits as Tauri events (`visual:frame-stats`) for the webview — same consumer interface, different transport.

**Graceful degradation:** If the UDS is unavailable, Tauri commands return an error. The webview shows an "imagination offline" indicator. The shm frame path still works if the binary is running but the socket dies.

## Kill List

### Deleted from `src-tauri/`

| Item | Reason |
|------|--------|
| `src/visual/bridge.rs` (392 lines) | Replaced by standalone binary |
| `winit` dependency in `src-tauri/Cargo.toml` | Moves to `hapax-visual` crate + `src-imagination` |
| `pollster` dependency | Used for `block_on(GpuContext::new())` in bridge |
| `spawn_visual_surface()` call in `main.rs` | Binary manages its own lifecycle |

### Moved to `crates/hapax-visual/`

`gpu.rs`, `compositor.rs`, `content_layer.rs`, `control.rs`, `output.rs`, `postprocess.rs`, `state.rs`, `techniques/`, `shaders/`

### Stays in `src-tauri/src/visual/`

`http_server.rs` (serves shm frames, no GPU dependency), `mod.rs` (re-exports + client)

## Systemd

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

[Install]
WantedBy=default.target
```

## Testing

- **IPC protocol:** Unit tests for JSON message parsing/serialization in `ipc.rs`
- **Window state persistence:** Unit test JSON round-trip in `window_state.rs`
- **Integration:** Launch binary, send UDS commands, verify responses
- **Render pipeline:** Pure GPU code — no unit tests (same as today)

## Acceptance Criteria

1. `hapax-imagination` binary runs standalone, renders to its own window
2. Window placement, mode, and size controllable via UDS commands
3. Window state persists across restarts
4. Tauri commands (`toggle_visual_window`, etc.) work via UDS client
5. `winit` removed from `src-tauri/Cargo.toml`
6. shm frame path continues to work (HTTP frame server reads from `/dev/shm`)
7. systemd unit starts/stops/restarts cleanly

## Constraints

- **NVIDIA + Wayland:** `__NV_DISABLE_EXPLICIT_SYNC=1` must be set in the systemd unit (same webkit2gtk bug workaround as Tauri)
- **GPU budget:** RTX 3090 shared with Ollama, voice, compositor. `MemoryMax=4G` on the systemd unit.
- **Single operator:** One imagination window, one consumer (Tauri). No multi-client UDS.
- **Beta convergence:** Beta's content layer (PR #395) and vocal imagination spec (PR #396) feed data into the imagination bus via `/dev/shm`. The extraction preserves this interface — `StateReader` and `ContentLayer` move to the shared crate unchanged.
