# Visual Surface in Webview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Display the wgpu visual surface inside the Tauri webview at 30fps via JPEG frame serving over local HTTP.

**Architecture:** The wgpu render loop encodes JPEG frames via turbojpeg and writes them atomically to `/dev/shm`. A small axum HTTP server inside the Tauri process serves the latest frame. A React component fetches frames at 30fps via `requestAnimationFrame` and displays them as a fullscreen background behind the terrain UI.

**Tech Stack:** turbojpeg (libjpeg-turbo), axum 0.8, React 19, existing wgpu 24 pipeline

**Spec:** `docs/superpowers/specs/2026-03-27-visual-surface-webview-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `hapax-logos/src-tauri/Cargo.toml` | Add turbojpeg, axum deps |
| Modify | `hapax-logos/src-tauri/src/visual/output.rs` | Add JPEG encoding after BGRA write |
| Create | `hapax-logos/src-tauri/src/visual/http_server.rs` | Axum HTTP frame server on :8053 |
| Modify | `hapax-logos/src-tauri/src/visual/mod.rs` | Export http_server module |
| Modify | `hapax-logos/src-tauri/src/visual/bridge.rs` | Add window visibility toggle via AtomicBool |
| Modify | `hapax-logos/src-tauri/src/visual/control.rs` | Add toggle_visual_window command |
| Modify | `hapax-logos/src-tauri/src/main.rs` | Register new commands, start HTTP server |
| Modify | `hapax-logos/src-tauri/tauri.conf.json` | Add img-src for :8053 to CSP |
| Create | `hapax-logos/src/components/visual/VisualSurface.tsx` | 30fps frame display component |
| Create | `hapax-logos/src/components/visual/__tests__/VisualSurface.test.tsx` | Tests |
| Modify | `hapax-logos/src/components/terrain/TerrainLayout.tsx` | Mount VisualSurface behind AmbientShader |

---

## Task 1: Add turbojpeg JPEG encoding to ShmOutput

**Files:**
- Modify: `hapax-logos/src-tauri/Cargo.toml`
- Modify: `hapax-logos/src-tauri/src/visual/output.rs`

- [ ] **Step 1: Add turbojpeg dependency**

In `hapax-logos/src-tauri/Cargo.toml`, add to `[dependencies]`:
```toml
turbojpeg = "1"
```

- [ ] **Step 2: Verify turbojpeg builds**

Run: `cd hapax-logos/src-tauri && cargo check 2>&1 | tail -5`
Expected: Compiles. If `libturbojpeg` is missing, install with `sudo pacman -S libjpeg-turbo`.

- [ ] **Step 3: Add JPEG encoding to write_frame()**

In `hapax-logos/src-tauri/src/visual/output.rs`, add these constants after the existing ones:

```rust
const JPEG_FILE: &str = "/dev/shm/hapax-visual/frame.jpg";
const JPEG_TMP_FILE: &str = "/dev/shm/hapax-visual/frame.jpg.tmp";
const JPEG_QUALITY: i32 = 80;
```

Add a `write_jpeg` method to `ShmOutput`:

```rust
    /// Encode BGRA pixels to JPEG and write atomically to /dev/shm.
    fn write_jpeg(&self, bgra_data: &[u8]) {
        // Convert BGRA to RGB for turbojpeg (strip alpha, swap B/R)
        let pixel_count = (self.width * self.height) as usize;
        let mut rgb = Vec::with_capacity(pixel_count * 3);
        for i in 0..pixel_count {
            let base = i * 4;
            if base + 2 < bgra_data.len() {
                rgb.push(bgra_data[base + 2]); // R (was at offset 2 in BGRA)
                rgb.push(bgra_data[base + 1]); // G
                rgb.push(bgra_data[base]);     // B (was at offset 0 in BGRA)
            }
        }

        let image = turbojpeg::Image {
            pixels: &rgb,
            width: self.width as usize,
            pitch: self.width as usize * 3,
            height: self.height as usize,
            format: turbojpeg::PixelFormat::RGB,
        };

        match turbojpeg::compress(image, JPEG_QUALITY, turbojpeg::Subsamp::Sub2x2) {
            Ok(jpeg_data) => {
                // Atomic write: tmp file then rename
                if let Ok(mut f) = fs::File::create(JPEG_TMP_FILE) {
                    if f.write_all(&jpeg_data).is_ok() {
                        fs::rename(JPEG_TMP_FILE, JPEG_FILE).ok();
                    }
                }
            }
            Err(e) => {
                log::warn!("JPEG encode failed: {}", e);
            }
        }
    }
```

- [ ] **Step 4: Call write_jpeg after writing BGRA**

In the `write_frame()` method, after the BGRA write and before `drop(data)` (line 125), add the JPEG encoding call. The `data` variable holds the mapped staging buffer with BGRA pixels.

After the BGRA write block (the `if padded_bytes_per_row == bytes_per_row` block), before `drop(data)`:

```rust
        // Encode and write JPEG for webview consumption
        if padded_bytes_per_row == bytes_per_row {
            self.write_jpeg(&data);
        } else {
            // buf was already built with stripped padding — reuse it
            self.write_jpeg(&buf);
        }
```

Note: this requires restructuring the existing write_frame slightly. The `buf` variable (built in the padding-strip branch) needs to be accessible to the JPEG call. Restructure to always build `clean_data` (either the raw mapped data or the stripped version), write BGRA from it, then write JPEG from it.

Full replacement for the `write_frame` method body after mapping succeeds:

```rust
        let data = slice.get_mapped_range();

        // Build clean pixel data (strip padding if needed)
        let clean_data: std::borrow::Cow<[u8]> = if padded_bytes_per_row == bytes_per_row {
            std::borrow::Cow::Borrowed(&data)
        } else {
            let mut buf = Vec::with_capacity((bytes_per_row * height) as usize);
            for row in 0..height {
                let start = (row * padded_bytes_per_row) as usize;
                let end = start + bytes_per_row as usize;
                buf.extend_from_slice(&data[start..end]);
            }
            std::borrow::Cow::Owned(buf)
        };

        // Write raw BGRA
        if let Ok(mut file) = fs::File::create(OUTPUT_FILE) {
            file.write_all(&clean_data).ok();
        }

        // Encode and write JPEG for webview consumption
        self.write_jpeg(&clean_data);

        drop(data);
        self.staging_buffer.unmap();
```

- [ ] **Step 5: Build and verify**

Run: `cd hapax-logos/src-tauri && cargo check 2>&1 | tail -5`
Expected: Compiles with no new errors.

- [ ] **Step 6: Commit**

```bash
cd ~/projects/hapax-council
git add hapax-logos/src-tauri/Cargo.toml hapax-logos/src-tauri/Cargo.lock hapax-logos/src-tauri/src/visual/output.rs
git commit -m "feat: add turbojpeg JPEG encoding to ShmOutput"
```

---

## Task 2: Create HTTP frame server

**Files:**
- Create: `hapax-logos/src-tauri/src/visual/http_server.rs`
- Modify: `hapax-logos/src-tauri/src/visual/mod.rs`
- Modify: `hapax-logos/src-tauri/src/main.rs`
- Modify: `hapax-logos/src-tauri/Cargo.toml`
- Modify: `hapax-logos/src-tauri/tauri.conf.json`

- [ ] **Step 1: Add axum dependency**

In `hapax-logos/src-tauri/Cargo.toml`, add:
```toml
axum = "0.8"
```

- [ ] **Step 2: Create http_server.rs**

```rust
// hapax-logos/src-tauri/src/visual/http_server.rs
//! HTTP server for serving visual surface frames to the webview.
//!
//! Serves the latest JPEG frame from /dev/shm/hapax-visual/frame.jpg
//! on a local port (default 8053). The webview fetches frames at 30fps
//! via requestAnimationFrame.

use axum::{http::StatusCode, response::IntoResponse, routing::get, Router};

const FRAME_PATH: &str = "/dev/shm/hapax-visual/frame.jpg";

async fn serve_frame() -> impl IntoResponse {
    match tokio::fs::read(FRAME_PATH).await {
        Ok(data) => (
            StatusCode::OK,
            [
                ("content-type", "image/jpeg"),
                ("cache-control", "no-store"),
            ],
            data,
        )
            .into_response(),
        Err(_) => StatusCode::SERVICE_UNAVAILABLE.into_response(),
    }
}

async fn serve_stats() -> impl IntoResponse {
    // Read the latest state.json for basic stats
    let path = "/dev/shm/hapax-visual/state.json";
    match tokio::fs::read_to_string(path).await {
        Ok(json) => (
            StatusCode::OK,
            [("content-type", "application/json")],
            json,
        )
            .into_response(),
        Err(_) => (
            StatusCode::OK,
            [("content-type", "application/json")],
            "{}".to_string(),
        )
            .into_response(),
    }
}

/// Start the frame server on a background tokio task.
pub fn start_frame_server() {
    let port: u16 = std::env::var("HAPAX_VISUAL_HTTP_PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(8053);

    tauri::async_runtime::spawn(async move {
        let app = Router::new()
            .route("/frame", get(serve_frame))
            .route("/stats", get(serve_stats));

        let addr = format!("127.0.0.1:{}", port);
        let listener = match tokio::net::TcpListener::bind(&addr).await {
            Ok(l) => l,
            Err(e) => {
                log::error!("Visual frame server failed to bind on {}: {}", addr, e);
                return;
            }
        };

        log::info!("Visual frame server listening on http://{}", addr);

        if let Err(e) = axum::serve(listener, app).await {
            log::error!("Visual frame server error: {}", e);
        }
    });
}
```

- [ ] **Step 3: Export module and start server**

In `hapax-logos/src-tauri/src/visual/mod.rs`, add:
```rust
pub mod http_server;
```

In `hapax-logos/src-tauri/src/main.rs`, in the `setup()` closure, add after the visual surface spawn:
```rust
            // Start HTTP frame server for webview visual surface display
            visual::http_server::start_frame_server();
```

- [ ] **Step 4: Update CSP in tauri.conf.json**

Change the CSP line to allow image fetches from :8053:
```json
"csp": "default-src 'self'; img-src 'self' blob: data: http://127.0.0.1:8053; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-eval'"
```

- [ ] **Step 5: Build and verify**

Run: `cd hapax-logos/src-tauri && cargo check 2>&1 | tail -5`
Expected: Compiles.

- [ ] **Step 6: Commit**

```bash
cd ~/projects/hapax-council
git add hapax-logos/src-tauri/Cargo.toml hapax-logos/src-tauri/Cargo.lock \
  hapax-logos/src-tauri/src/visual/http_server.rs \
  hapax-logos/src-tauri/src/visual/mod.rs \
  hapax-logos/src-tauri/src/main.rs \
  hapax-logos/src-tauri/tauri.conf.json
git commit -m "feat: add axum HTTP frame server for visual surface"
```

---

## Task 3: Add winit window visibility toggle

**Files:**
- Modify: `hapax-logos/src-tauri/src/visual/bridge.rs`
- Modify: `hapax-logos/src-tauri/src/visual/control.rs`
- Modify: `hapax-logos/src-tauri/src/main.rs`

- [ ] **Step 1: Add shared visibility flag to bridge.rs**

Add a module-level `AtomicBool` and expose it:

```rust
use std::sync::atomic::{AtomicBool, Ordering};

static WINDOW_VISIBLE: AtomicBool = AtomicBool::new(true);

/// Set visual window visibility. Called from Tauri command.
pub fn set_window_visible(visible: bool) {
    WINDOW_VISIBLE.store(visible, Ordering::Relaxed);
}
```

- [ ] **Step 2: Check visibility flag in the render loop**

In `VisualApp::render()`, at the top (after the `let Some(window) = &self.window` check at line 89), add:

```rust
        // Toggle window visibility from Tauri command
        let should_be_visible = WINDOW_VISIBLE.load(Ordering::Relaxed);
        window.set_visible(should_be_visible);
```

Note: calling `set_visible` every frame when the state hasn't changed is a no-op in winit — it's safe and avoids tracking previous state.

- [ ] **Step 3: Add Tauri command in control.rs**

```rust
#[tauri::command]
pub fn toggle_visual_window(visible: bool) -> bool {
    super::bridge::set_window_visible(visible);
    visible
}
```

- [ ] **Step 4: Register command in main.rs**

Add to the `invoke_handler`:
```rust
visual::control::toggle_visual_window,
```

- [ ] **Step 5: Build and verify**

Run: `cd hapax-logos/src-tauri && cargo check 2>&1 | tail -5`
Expected: Compiles.

- [ ] **Step 6: Commit**

```bash
cd ~/projects/hapax-council
git add hapax-logos/src-tauri/src/visual/bridge.rs \
  hapax-logos/src-tauri/src/visual/control.rs \
  hapax-logos/src-tauri/src/main.rs
git commit -m "feat: add toggle_visual_window command for winit visibility"
```

---

## Task 4: Create VisualSurface React component

**Files:**
- Create: `hapax-logos/src/components/visual/VisualSurface.tsx`
- Create: `hapax-logos/src/components/visual/__tests__/VisualSurface.test.tsx`

- [ ] **Step 1: Write tests**

```typescript
// hapax-logos/src/components/visual/__tests__/VisualSurface.test.tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import { VisualSurface } from "../VisualSurface";

// Mock usePageVisible
vi.mock("../../../hooks/usePageVisible", () => ({
  usePageVisible: vi.fn(() => true),
}));

describe("VisualSurface", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Mock fetch to return a blob
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(new Blob(["fake-jpeg"], { type: "image/jpeg" }), {
        status: 200,
      }),
    );
    // Mock URL.createObjectURL/revokeObjectURL
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:mock-url");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    cleanup();
  });

  it("renders an img element with visual-surface class", () => {
    const { container } = render(<VisualSurface />);
    const img = container.querySelector("img.visual-surface");
    expect(img).not.toBeNull();
  });

  it("has fixed positioning styles", () => {
    const { container } = render(<VisualSurface />);
    const img = container.querySelector("img.visual-surface") as HTMLImageElement;
    expect(img.style.position).toBe("fixed");
    expect(img.style.pointerEvents).toBe("none");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd hapax-logos && pnpm test -- src/components/visual/__tests__/VisualSurface.test.tsx --run`
Expected: FAIL — module not found.

- [ ] **Step 3: Create VisualSurface.tsx**

```typescript
// hapax-logos/src/components/visual/VisualSurface.tsx
import { useEffect, useRef } from "react";
import { usePageVisible } from "../../hooks/usePageVisible";

const FRAME_URL = "http://127.0.0.1:8053/frame";
const MIN_FRAME_MS = 33; // ~30fps

/**
 * Displays the wgpu visual surface as a fullscreen background image.
 * Fetches JPEG frames from the Rust HTTP server at 30fps.
 */
export function VisualSurface() {
  const imgRef = useRef<HTMLImageElement>(null);
  const prevUrlRef = useRef<string | null>(null);
  const visible = usePageVisible();

  useEffect(() => {
    if (!visible) return;

    let active = true;
    let lastFrame = 0;

    const tick = async (now: number) => {
      if (!active) return;

      if (now - lastFrame >= MIN_FRAME_MS) {
        lastFrame = now;
        try {
          const res = await fetch(FRAME_URL);
          if (res.ok) {
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            if (prevUrlRef.current) {
              URL.revokeObjectURL(prevUrlRef.current);
            }
            prevUrlRef.current = url;
            if (imgRef.current) {
              imgRef.current.src = url;
            }
          }
        } catch {
          // Frame server not available yet — skip
        }
      }

      if (active) {
        requestAnimationFrame(tick);
      }
    };

    requestAnimationFrame(tick);

    return () => {
      active = false;
      if (prevUrlRef.current) {
        URL.revokeObjectURL(prevUrlRef.current);
        prevUrlRef.current = null;
      }
    };
  }, [visible]);

  return (
    <img
      ref={imgRef}
      className="visual-surface"
      alt=""
      style={{
        position: "fixed",
        inset: 0,
        width: "100%",
        height: "100%",
        objectFit: "cover",
        zIndex: -1,
        pointerEvents: "none",
      }}
    />
  );
}
```

- [ ] **Step 4: Run tests**

Run: `cd hapax-logos && pnpm test -- src/components/visual/__tests__/VisualSurface.test.tsx --run`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd ~/projects/hapax-council
git add hapax-logos/src/components/visual/VisualSurface.tsx \
  hapax-logos/src/components/visual/__tests__/VisualSurface.test.tsx
git commit -m "feat: add VisualSurface component for 30fps frame display"
```

---

## Task 5: Mount VisualSurface in TerrainLayout

**Files:**
- Modify: `hapax-logos/src/components/terrain/TerrainLayout.tsx`

- [ ] **Step 1: Import VisualSurface**

Add import at top of TerrainLayout.tsx (after existing imports, around line 20):
```typescript
import { VisualSurface } from "../visual/VisualSurface";
```

- [ ] **Step 2: Mount before AmbientShader**

In the return JSX (around line 188), insert `<VisualSurface />` before the `<AmbientShader>` component:

```tsx
      <div
        className="h-screen w-screen overflow-hidden relative"
        style={{ fontFamily: "'JetBrains Mono', monospace", background: "#1d2021" }}
      >
        {/* z-(-1): wgpu visual surface (JPEG frames from Rust) */}
        <VisualSurface />

        {/* z-0: Ambient shader background */}
        <AmbientShader
```

The VisualSurface sits at `z-index: -1` (behind AmbientShader at z-0). When the visual surface is running, it provides the ambient background. AmbientShader continues to work as a lightweight fallback when the visual surface is off.

- [ ] **Step 3: Run all tests**

Run: `cd hapax-logos && pnpm test --run`
Expected: All pass (the VisualSurface component is self-contained, no test coupling).

- [ ] **Step 4: Commit**

```bash
cd ~/projects/hapax-council
git add hapax-logos/src/components/terrain/TerrainLayout.tsx
git commit -m "feat: mount VisualSurface behind terrain UI"
```

---

## Task 6: Push and create PR

- [ ] **Step 1: Run full test suite**

Run: `cd hapax-logos && pnpm test --run && cd src-tauri && cargo check`
Expected: All frontend tests pass, Rust compiles.

- [ ] **Step 2: Push and create PR**

```bash
cd ~/projects/hapax-council
git push origin feat/tauri-only-runtime
gh pr edit 377 --title "feat: Tauri-only runtime + visual surface in webview" --body "$(cat <<'EOF'
## Summary

### Tauri-only runtime (Phases 1-5)
- Rewrite API client to invoke-only (61 invoke calls, zero fetch)
- Replace SSE with Tauri event streams
- Move command relay from FastAPI to Rust WebSocket server (:8052)
- Strip Vite proxy, tighten CSP, remove browser CORS
- Wire control.json into compositor for layer opacity control
- Remove all IS_TAURI guards

### Visual surface in webview
- turbojpeg JPEG encoding in wgpu render loop (every 2 frames, ~3-5ms)
- Axum HTTP frame server on :8053 serves latest JPEG
- VisualSurface React component fetches at 30fps via requestAnimationFrame
- Mounted behind terrain UI in TerrainLayout
- Winit window toggle command (show/hide for dual-monitor effects)

## Test plan
- [ ] `pnpm test --run` passes
- [ ] `cargo check` passes
- [ ] `cargo tauri dev` shows visual surface behind terrain UI
- [ ] Layer opacity control via control.json works
- [ ] `toggle_visual_window` hides/shows the winit window
- [ ] Frame server responds on http://127.0.0.1:8053/frame

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Dependency Graph

```
Task 1 (turbojpeg encoding)
  ↓
Task 2 (HTTP frame server)
  ↓
Task 3 (winit window toggle) — independent of Tasks 1-2, but ordered for clean commits
  ↓
Task 4 (VisualSurface component)
  ↓
Task 5 (mount in TerrainLayout)
  ↓
Task 6 (push + PR)
```
