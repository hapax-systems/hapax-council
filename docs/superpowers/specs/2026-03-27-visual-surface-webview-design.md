# Visual Surface in Webview — Design Spec

**Date:** 2026-03-27
**Status:** Design approved, awaiting implementation plan
**Scope:** Display wgpu visual surface inside the Tauri webview at 30fps via HTTP frame serving

## Drivers

The wgpu visual surface currently renders on a separate winit window. This creates a disjointed UX — the shaders are not visible behind the Logos terrain UI. The PoC for GPU texture sharing (Option B) failed due to a Wayland protocol conflict (webkit2gtk and wgpu can't share a surface). This spec implements Option A: JPEG frame transfer via a local HTTP server inside the Tauri binary.

## Architecture

Three components, one data flow:

```
wgpu render loop (winit thread, existing)
  → turbojpeg encode (every 2 frames, ~3-5ms)
  → atomic write /dev/shm/hapax-visual/frame.jpg

Rust HTTP server (axum, :8053, inside Tauri process)
  → GET /frame — serves latest frame.jpg
  → GET /stats — serves FrameStats JSON

React VisualSurface component
  → requestAnimationFrame at 30fps
  → fetch blob from /frame → render on <img>
  → positioned behind terrain regions (z-index: -1)
```

## Component 1: JPEG Encoding in Render Loop

### Location

`hapax-logos/src-tauri/src/visual/output.rs` — extend `ShmOutput`

### Changes

After `write_frame()` writes raw BGRA to `frame.bgra` (every 2 frames), add:

1. Read the mapped staging buffer (already available in `write_frame`)
2. Encode to JPEG via `turbojpeg` at quality 80
3. Atomic write: write to `/dev/shm/hapax-visual/frame.jpg.tmp`, rename to `frame.jpg`

### Dependencies

Add to `Cargo.toml`:
```toml
turbojpeg = "1"
```

System dependency: `libturbojpeg` (available via `pacman -S libjpeg-turbo` on Arch/CachyOS — already installed as a transitive dependency of many packages).

### Performance Budget

- 1920×1080 BGRA → JPEG Q80: ~3-5ms with turbojpeg (hardware-accelerated SIMD)
- Budget: 33ms per encoded frame (encoding every 2 render frames at 60Hz)
- Encoding runs in the winit render thread, synchronous after GPU readback
- If profiling shows stalls, extract to a dedicated encoder thread via channel (future optimization, not in scope)

### File Layout

```
/dev/shm/hapax-visual/
  frame.bgra      (existing, raw BGRA, 8.3MB)
  frame.jpg        (new, JPEG Q80, ~120-200KB)
  frame.jpg.tmp    (transient, atomic rename target)
  state.json       (existing)
  control.json     (existing)
  snapshot.jpg     (existing, read by get_visual_surface_snapshot)
```

The `snapshot.jpg` path continues to be served by the existing `get_visual_surface_snapshot` Tauri command. `frame.jpg` is the new continuously-updated frame for the webview.

## Component 2: HTTP Frame Server

### Location

Create: `hapax-logos/src-tauri/src/visual/http_server.rs`

### Design

Axum HTTP server on `127.0.0.1:8053` (configurable via `HAPAX_VISUAL_HTTP_PORT` env var):

```
GET /frame
  → Read /dev/shm/hapax-visual/frame.jpg
  → Content-Type: image/jpeg
  → Cache-Control: no-store
  → 200 OK (or 503 if no frame available yet)

GET /stats
  → Read latest FrameStats from shared state
  → Content-Type: application/json
  → 200 OK
```

### Startup

Called from `main.rs setup()`:
```rust
visual::http_server::start_frame_server(app.handle().clone());
```

Spawns as a tokio task. Logs the listening address at startup.

### Dependencies

Add to `Cargo.toml`:
```toml
axum = "0.8"
```

(`tokio` is already present with `features = ["full"]`.)

### CSP Update

In `tauri.conf.json`, update CSP to allow image fetches from the frame server:
```
img-src 'self' blob: data: http://127.0.0.1:8053
```

### No CORS Needed

The webview loads from `tauri://localhost`. The frame server is on a different origin (`http://127.0.0.1:8053`). However, `<img>` tags are not subject to CORS — they load cross-origin images freely. The CSP `img-src` directive is the only gate.

## Component 3: Winit Window Toggle

### Location

Modify: `hapax-logos/src-tauri/src/visual/bridge.rs`
Modify: `hapax-logos/src-tauri/src/visual/control.rs`

### Design

New Tauri command:
```rust
#[tauri::command]
pub fn toggle_visual_window(visible: bool) -> bool
```

Implementation: the winit thread holds a `Arc<AtomicBool>` for visibility state. `toggle_visual_window` sets the atomic. The winit event loop checks it each frame and calls `window.set_visible(visible)`.

Default: visible (preserves current behavior).

### Use Cases

- Hide when only using webview display
- Show fullscreen on second monitor for live effects performance
- Toggle via command registry: `visual.window.toggle`

### Command Registration

Register `toggle_visual_window` in `main.rs` invoke handler. Also register in the command registry as `visual.window.toggle` with arg `{ visible: boolean }`.

## Component 4: React VisualSurface Component

### Location

Create: `hapax-logos/src/components/visual/VisualSurface.tsx`
Modify: `hapax-logos/src/pages/TerrainPage.tsx` or `TerrainLayout.tsx`

### Design

```tsx
export function VisualSurface() {
  // requestAnimationFrame loop at 30fps
  // fetch http://127.0.0.1:8053/frame as blob
  // display via <img> with blob URL
  // revoke previous blob URL on each update
  // pause when page not visible (usePageVisible hook)
}
```

### CSS Positioning

```css
.visual-surface {
  position: fixed;
  inset: 0;
  z-index: -1;
  object-fit: cover;
  pointer-events: none;
}
```

Renders behind all terrain content. UI panels with opaque backgrounds occlude it; regions with `background: transparent` show it through.

### Mounting

In `TerrainLayout.tsx`, insert as the first child before all region content:
```tsx
<VisualSurface />
<div className="terrain-regions">
  {/* existing region layout */}
</div>
```

### Frame Polling Pattern

Follow the existing `DetectionOverlay.tsx` pattern (lines 313-365):
- `requestAnimationFrame` callback
- Throttle with elapsed time check (`MIN_FRAME_MS = 33` for 30fps)
- Cleanup in `useEffect` return

### Blob URL Lifecycle

```typescript
const url = URL.createObjectURL(blob);
if (prevUrl) URL.revokeObjectURL(prevUrl);
imgRef.current.src = url;
```

### Error Handling

If `/frame` returns 503 (no frame yet) or network error, skip the frame and retry next RAF tick. No error state in the UI — the visual surface is ambient, not critical.

### Page Visibility

Use the existing `usePageVisible()` hook. When the page is hidden (tab switched), stop fetching frames entirely. Resume on visibility restore.

## What Stays the Same

- winit window stays (toggleable visibility, default visible)
- All 6 techniques, compositor, postprocess, shaders unchanged
- `ShmOutput` continues writing `frame.bgra` for external consumers
- `visual-layer-aggregator` unaffected (reads state JSON, not frames)
- `get_visual_surface_snapshot` command still works
- `control.json` → compositor opacity wiring (just shipped in Phase 4 gap fix)
- Frame stats emission via Tauri events (every 300 frames)

## Performance Characteristics

| Metric | Value |
|--------|-------|
| Encode time (turbojpeg Q80, 1920×1080) | ~3-5ms |
| Frame size (JPEG Q80) | ~120-200 KB |
| Delivery rate | 30fps (every 2 render frames) |
| Bandwidth (local HTTP) | ~4-6 MB/s |
| Webview fetch overhead | ~1-2ms per frame |
| Total frame latency | ~35-40ms (encode + write + read + render) |

## Risk Summary

| Risk | Severity | Mitigation |
|------|----------|------------|
| turbojpeg system dep missing | Low | libjpeg-turbo is ubiquitous on Linux, transitive dep of many packages |
| 30fps fetch creates GC pressure from blob URLs | Low | Revoke previous URL before creating new one (proven pattern in codebase) |
| JPEG encoding stalls render loop | Medium | 3-5ms is within budget; if it stalls, extract to encoder thread |
| Port 8053 conflict | Low | Configurable via HAPAX_VISUAL_HTTP_PORT env var |
