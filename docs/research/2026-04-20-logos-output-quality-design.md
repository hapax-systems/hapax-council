# Logos Output-Node Quality Parity — Research & Design

**Date:** 2026-04-20
**Status:** Research & Design (no code changes)
**Operator observation (verbatim, 2026-04-19):** "quality of output node as seen fullscreen via logos app is vastly inferior in quality to the output node in OBS itself"
**Related:** task #174 (nebulous scrim), task #129 (face-obscure), `docs/research/2026-04-20-nebulous-scrim-design.md`

## §1. Problem framing and disambiguation

The phrase "output node" is overloaded in the Logos app surface inventory. There are two plausible referents, and a third that can be ruled out.

### 1.1 Candidate A — `OutputNode.tsx` on the `StudioCanvas`

File: `hapax-logos/src/components/graph/nodes/OutputNode.tsx:301`

This is a node in the ReactFlow graph rendered by `StudioCanvas` (`hapax-logos/src/components/graph/StudioCanvas.tsx:32` registers it as the `output` node type). It displays the live compositor mix via a WebSocket subscription to `ws://127.0.0.1:8053/ws/fx` (`OutputNode.tsx:30`). Double-click enters borderless fullscreen via Tauri window API; a `FullscreenOverlay` component (`OutputNode.tsx:191`) uses the same `useFxStream` hook (`OutputNode.tsx:195`). The fullscreen overlay letterboxes at `objectFit: contain` (`OutputNode.tsx:261`).

This surface is driven by the **studio compositor** (GStreamer), not by Reverie. Its upstream producer writes to `/dev/shm/hapax-compositor/fx-snapshot.jpg` and pushes frames over TCP `:8054` into the `FxFrameRelay` (`hapax-logos/src-tauri/src/visual/fx_relay.rs:37`), which re-broadcasts via WebSocket. Its fallback HTTP endpoint is `GET /fx` (`hapax-logos/src-tauri/src/visual/http_server.rs:56`).

### 1.2 Candidate B — `VisualSurface.tsx` (Reverie background)

File: `hapax-logos/src/components/visual/VisualSurface.tsx:13`

This is the always-present `position: fixed; inset: 0; z-index: -1` background wash (line 50–57). It fetches `/frame` (`:8053/frame`) via `new Image()` preload every 333 ms (~3 fps, line 6), reading `/dev/shm/hapax-visual/frame.jpg` produced by the `hapax-imagination` wgpu daemon. It is never "fullscreened" in the Tauri sense — it is always the background layer under all other UI. It has no visible node, no double-click handler, no keyboard shortcut.

### 1.3 Candidate C — desktop `hapax-reverie`/`hapax-logos` rendering surfaces (ruled out)

The `hapax-imagination` and `hapax-reverie` daemons do own their own GPU rendering surfaces (winit windows / wgpu surfaces) but those surfaces are not reachable through the Logos React app — they are independent X/Wayland toplevels managed by systemd user units. Operator's language ("via logos app") rules this out.

### 1.4 Resolution: Candidate A, with near certainty

Three converging signals point at `OutputNode`:

1. **Terminology.** In the visual vocabulary the operator has been using for the past six months, "output node" is the ReactFlow node that displays the compositor's final composite. The underlying store key (`useStudioGraph.outputFullscreen`, `studioGraphStore.ts`) treats it as a first-class UI concept. The background Reverie wash is never called "output" anywhere in the codebase.

2. **"Fullscreen."** Only `OutputNode` has a fullscreen code path (`FullscreenOverlay`, `setOutputFullscreen`, `set_window_fullscreen` Tauri invoke). `VisualSurface` already occupies full viewport as the background — there is no "enter fullscreen" moment.

3. **"Output node in OBS itself."** The operator contrasts the Logos surface with "the output node in OBS itself". OBS consumes `/dev/video42` (the v4l2 loopback written by the compositor via `pipeline.py:197`). The natural comparison is between OBS's view of the compositor output and Logos's view of the compositor output — both attempting to show the same upstream producer. Reverie is not a candidate for comparison with OBS at all, because OBS never sees Reverie directly (Reverie is a compositor source via `SurfaceKind.fx_chain_input`, not an OBS source).

All remaining sections assume operator means `OutputNode` / `FullscreenOverlay`.

## §2. Current-state quality audit (OutputNode pipeline)

The path from compositor frame to pixel on the Logos fullscreen view is seven stages. Each adds latency and/or loses fidelity.

### 2.1 Stage 1 — producer (compositor egress)

File: `agents/studio_compositor/pipeline.py:162-227`

- **Resolution:** 1280×720 (`config.py:39`, `OUTPUT_WIDTH=1280`, `OUTPUT_HEIGHT=720`). The 1920×1080 → 1280×720 drop was an operator directive on 2026-04-17 ("1080p is NOT a priority at all"; `config.py:27-33`) and applies to all downstream consumers including OBS.
- **Format:** NV12 raw video, 30 fps, linked into `v4l2sink` at `/dev/video42` (`models.py:90`). This is the path OBS ingests. It is lossless.
- **Compositor tee:** a single `output_tee` fans the final composite to multiple branches — `v4l2sink` (OBS), `hls`, `fx_snapshot`, `smooth_delay`, `rtmp_output` (`pipeline.py:258-268`).

No loss occurs at this stage; all branches start from the same 1280×720 NV12 buffer.

### 2.2 Stage 2 — FX snapshot branch (Logos-facing encode)

File: `agents/studio_compositor/snapshots.py:82-240` (`add_fx_snapshot_branch`)

This branch is the Logos-facing divergence. It applies four quality-reducing transforms:

1. **Rate-limit to 3 fps** (`snapshots.py:109-114`). A `videorate` element with `max-rate=3` followed by a `capsfilter` enforcing `framerate=3/1`. This is a deliberate CPU-budget decision made in the 2026-04-17 CPU audit (`snapshots.py:103-108` comment) — jpegenc at 30 fps × 1280×720 was the single largest consumer on this branch, and downstream consumers were only polling at 3 fps anyway via `Image()` preload. The inline comment names both `VisualSurface.tsx` HTTP polling and "the OutputNode WebSocket (/ws/fx)" as 3 fps consumers. This is the **first framerate cliff**.
2. **Videoconvert** (NV12 → RGB-family for jpegenc input) at `snapshots.py:98`.
3. **JPEG encode, quality=85** (`snapshots.py:116`). q=85 is a moderately compressed setting; 1280×720 frames at q=85 typically land at 80–180 KB/frame, with visible chroma blockiness in dark regions, ringing on high-contrast overlays (token pole, stance indicator, album art text), and softening of the Sierpinski triangle YouTube content. OBS's raw NV12 has none of these artifacts.
4. **Serialization** to bytes (`snapshots.py:211`).

### 2.3 Stage 3 — transport

File: `agents/studio_compositor/snapshots.py:127-197`

A daemon thread takes each encoded frame, pushes it over TCP `127.0.0.1:8054` with a 4-byte LE length prefix, and also writes it to `/dev/shm/hapax-compositor/fx-snapshot.jpg` via atomic rename (lines 171–194). The TCP push has a 0.5 s connect timeout and a 5 s reconnect cooldown; `TCP_NODELAY=1` avoids Nagle coalescing. A single background thread with an `Event`-driven producer-consumer decouples file I/O from the GStreamer streaming thread — this was a deliberate 2026-04-17 fix for compositor stalls.

### 2.4 Stage 4 — FxFrameRelay (Rust)

File: `hapax-logos/src-tauri/src/visual/fx_relay.rs:37`

An axum-adjacent tokio task accepts TCP connections on `127.0.0.1:8054`, reads the length-prefixed framing, and broadcasts JPEG bytes to a `tokio::sync::broadcast` channel with **capacity 4** (`fx_relay.rs:14`). If a WebSocket client lags behind by more than 4 frames, it receives a `Lagged` error and skips to the latest (handled gracefully at `http_server.rs:92-94`). At 3 fps this is ~1.3 s of slack before a skip.

### 2.5 Stage 5 — WebSocket server

File: `hapax-logos/src-tauri/src/visual/http_server.rs:72-98`

`GET /ws/fx` upgrades to a WebSocket and relays each broadcasted JPEG as a binary WS message. One broadcast-channel receiver per connected client. No re-encoding.

### 2.6 Stage 6 — client-side receive and swap

File: `hapax-logos/src/components/graph/nodes/OutputNode.tsx:33-52`

`ws.onmessage` wraps the `Blob` in an object URL and assigns it to `imgRef.current.src`. A double-buffer pattern (`urlA`/`urlB`) revokes the older URL to avoid leaks. The browser decodes JPEG on the webview's image pipeline and paints into an `<img>`. No canvas upload, no pixel manipulation.

### 2.7 Stage 7 — display

File: `OutputNode.tsx:133-143` (node view) and `OutputNode.tsx:257-262` (fullscreen overlay)

- **Node view:** `objectFit: contain` — letterboxes when the node aspect ratio differs from 16:9. Explicitly chosen over `cover` to avoid cropping right-edge wards (lines 137–141 comment).
- **Fullscreen overlay:** `width: 100%; height: 100%; objectFit: contain` inside a flex container. A prior attempt used `max-width/max-height + auto` which sized the `<img>` to its *intrinsic* 1280×720 and produced large black bars on a 1920×1050 viewport (lines 240–246 comment). The current CSS fills the container, letterboxing gracefully.

### 2.8 Quality loss accounting

The comparative loss from OBS baseline is concentrated in three places.

| Stage | OBS baseline | OutputNode path | Loss |
|---|---|---|---|
| Resolution | 1280×720 NV12 | 1280×720 JPEG → same decode | **none** (since 2026-04-17) |
| Framerate | 30 fps | 3 fps | **10× reduction** (2026-04-17 CPU audit) |
| Compression | lossless NV12 | JPEG q=85 | **lossy**, visible on overlays and gradients |
| Colour subsampling | 4:2:0 (NV12) | 4:2:0 (jpegenc default) | equivalent |
| Latency | v4l2 → OBS ring buffer (~33 ms) | encode + TCP + decode + paint (~70–120 ms) | +50–90 ms |

The dominant perceptual gap is **framerate** — 3 fps is the floor at which head motion, MPC pad drumming, and chat-scroll overlays stutter into discrete positions. The secondary gap is **compression artifacts** on high-contrast overlay edges (token pole lettering, stance indicator text, Pango markdown in content zones). Resolution is not the gap.

## §3. OBS baseline — what it does right

OBS Studio's V4L2 Video Capture Device source calls `ioctl(VIDIOC_DQBUF)` against `/dev/video42`, receiving kernel-managed NV12 buffers shared via `mmap`. The chain from compositor egress to OBS pixel is:

1. GStreamer `v4l2sink` (`pipeline.py:197-219`) — qos disabled, `enable-last-sample=false`, `max-size-buffers=5` cushion upstream.
2. `v4l2loopback` kernel module — `max_buffers=2` ring, `exclusive_caps=1`.
3. OBS v4l2 source — mmap-backed DQBUF at 30 fps; NV12 → OBS internal format with GPU colorspace conversion; preview and program output composited on GPU.

There is no intermediate compression, no HTTP hop, no JPEG round-trip. The v4l2 interface is a kernel IPC that matches the compositor's egress frame cadence exactly.

### 3.1 What Tauri would need to do to match

The Tauri webview (WebKitGTK 2.50.6 on this system) cannot natively ingest `/dev/video42` — a webview is a browser origin, not a V4L2 consumer. Any parity solution must ingest v4l2 **Rust-side** and expose the frames to the webview through one of:

- **(a)** HTTP JPEG per-frame (current path, what we want to beat).
- **(b)** MJPEG multipart HTTP — `Content-Type: multipart/x-mixed-replace` with per-part `image/jpeg` boundaries, consumed by a plain `<img>` tag. Single long-lived connection, browser-decoded, no JS frame pump.
- **(c)** WebSocket raw frames (JPEG or YUV) — current `/ws/fx` but possibly at higher quality and rate.
- **(d)** `invoke()`-delivered raw buffers — Rust reads v4l2, posts NV12/RGB bytes to JS via Tauri IPC; JS uploads to a `<canvas>` or a WebGL texture. Bypasses HTTP but hits IPC serialization cost.
- **(e)** WebRTC peer connection — Rust `gstreamer-rs` + `webrtcbin` → local SDP offer → JS `RTCPeerConnection` → `<video>` tag. Hardware-accelerated decode in the webview, adaptive bitrate, 30 fps, sub-100 ms latency achievable in loopback. Requires webkitgtk_4_1 (Tauri v2 uses it; `set_enable_webrtc` is available).
- **(f)** Separate Tauri window with native GStreamer → GL window rendering. Quality matches OBS pixel-for-pixel but renders outside the webview DOM, which means the overlay HUD (chain builder, sequence bar) would need to be rendered in a separate layered window or re-composited.

## §4. Options evaluation

Each option scored against six axes: implementation cost (LOC + systems touched), expected quality gain, framerate cap, latency added above current, platform risk (Wayland/NVIDIA/webkitgtk), and compatibility with Reverie/compositor.

### Option 1 — Bump `:8053` JPEG quality and fetch cadence

Change `snapshots.py:109-116` from `max-rate=3`, `framerate=3/1`, `quality=85` to `max-rate=30`, `framerate=30/1`, `quality=95`. No transport change.

- **LOC:** ~5 lines, single file.
- **Quality gain:** small-to-moderate. q=95 nearly eliminates visible JPEG artifacts on smooth gradients and text edges. 30 fps matches OBS framerate.
- **Latency delta:** +0 ms (same path).
- **Platform risk:** low.
- **Cost:** **this is what the 2026-04-17 CPU audit explicitly rejected.** jpegenc at 1280×720×30 fps is the heaviest single element on this branch; restoring it puts ~15% of a CPU core back onto the compositor process and risks re-introducing the stalls the audit fixed. Also pushes TCP throughput from ~0.5 MB/s to ~3–5 MB/s over loopback (trivial, but raises broadcast-channel pressure at capacity=4 → potentially need capacity=16).
- **Compatibility:** zero interaction with Reverie or face-obscure.
- **Verdict:** rehabilitates resolution and mostly compression; still JPEG-lossy; pays full encode+decode cost per frame at 30 fps. A middle-ground (10 fps at q=92) is tempting but doesn't match OBS.

### Option 2 — MJPEG multipart HTTP stream

Change `:8053` to serve `multipart/x-mixed-replace;boundary=frame` on `GET /fx.mjpg`, each part `Content-Type: image/jpeg`. OutputNode consumes it by setting `<img src="http://127.0.0.1:8053/fx.mjpg">`. The browser decodes natively; no JS `onmessage` pump, no `URL.createObjectURL` churn, no double-buffer ref juggling.

- **LOC:** ~60 lines Rust (new axum handler streaming from the broadcast channel); ~5 lines React (replace `useFxStream` call with plain `<img src>`).
- **Quality gain:** moderate. Eliminates the JS frame-pump overhead (URL.createObjectURL per frame is cheap but not free — at 30 fps it's ~900 object-URL churns/min). Still JPEG-encoded upstream (same quality knob as Option 1). Framerate cap is whatever the encoder produces.
- **Latency delta:** equivalent to WebSocket — one TCP connection, multipart body framing is kernel-efficient.
- **Platform risk:** low. MJPEG over `<img>` has been in browsers since the Netscape era.
- **Compatibility:** zero interaction with Reverie. The WebSocket relay can coexist (the broadcast channel can have multiple subscribers, one MJPEG HTTP handler + existing WS handler).
- **Verdict:** removes the JS frame pump as a scaling constraint but doesn't change the underlying encode quality. Useful as a **transport simplification** but does not by itself close the quality gap. Natural companion to Option 1.

### Option 3 — Rust-side v4l2 ingest → invoke() raw buffer stream

Rust subscribes to `/dev/video42` via `v4l` crate (or gstreamer-rs with `v4l2src`), reads NV12 buffers, emits them to the webview via Tauri `invoke()` or `event::emit()`. JS uploads the NV12 buffer to a WebGL texture and does chroma reconstruction in a fragment shader on a `<canvas>`.

- **LOC:** ~300–400 Rust (v4l2 open, buffer queue, eventloop integration); ~150 JS (WebGL NV12→RGB shader, canvas lifecycle, frame scheduling).
- **Quality gain:** maximum. Matches OBS pixel-for-pixel at 30 fps NV12.
- **Latency delta:** lowest possible (no encode). IPC round-trip for each frame adds ~2–5 ms on Tauri v2.
- **Platform risk:** moderate. v4l2loopback `exclusive_caps=1` plus OBS already holding the device — two consumers on the same device have historically been flaky (the whole `interpipesrc` epic was because of this). Adding a second `open(/dev/video42)` reader while OBS is attached will either work cleanly (loopback is designed for multi-reader) or require a second loopback device (`/dev/video43`) fed by a second `v4l2sink` branch on the compositor.
- **Compatibility:** doesn't touch Reverie. Face-obscure applies upstream of the v4l2sink (see §8), so the Rust reader sees already-obscured content.
- **Verdict:** highest quality ceiling; highest cost and risk. Only worth doing if Options 1+2 still leave a visible gap. The second-loopback-device complication is a real operational cost.

### Option 4 — Separate Tauri window with GStreamer GL rendering

Spawn a second Tauri window that is *not* a webview but a GL surface fed by `gst-plugin-webrtc` or a `gtkglsink`/`glimagesink` bound to the Tauri window handle. The webview HUD (ChainBuilder, SequenceBar) sits in the main window or as a transparent overlay window.

- **LOC:** ~500+ across Rust and systemd (window plumbing, HUD separation, focus handling).
- **Quality gain:** matches OBS.
- **Latency delta:** lowest possible.
- **Platform risk:** high. Tauri v2 multiwebview is behind an unstable feature flag; the Wayland + NVIDIA + webkitgtk stack on this workstation has already cost multiple days of debugging (syncobj bug, `__NV_DISABLE_EXPLICIT_SYNC=1` workaround). A second OS-level window compounds the fragility. The entire winit window for `hapax-imagination` is isolated from Tauri precisely to avoid this surface area.
- **Compatibility:** leaves the HUD stack in a worse place. The operator specifically consolidated the studio control surface (ChainBuilder + SequenceBar) *inside* FullscreenOverlay for a reason — two windows undo that consolidation.
- **Verdict:** highest quality but highest risk and architectural regression. Rejected.

### Option 5 — WebRTC loopback (Rust `webrtcbin` → JS `RTCPeerConnection`)

Rust builds a GStreamer pipeline `v4l2src device=/dev/video42 → nvh264enc → rtph264pay → webrtcbin`, negotiates SDP with the webview's `RTCPeerConnection` over a Tauri IPC signalling channel, and the webview decodes via the platform's hardware H.264 decoder. `<video>` tag displays.

- **LOC:** ~500 Rust (webrtcbin + signalling), ~100 JS. Plus systemd/env flags for webkitgtk WebRTC enablement.
- **Quality gain:** high. H.264 at 10+ Mbps on loopback is visually indistinguishable from NV12 raw. Browser hardware decode. 30 fps, sub-frame latency achievable.
- **Latency delta:** +~50 ms initial negotiation, then steady.
- **Platform risk:** moderate-to-high. `gst-plugins-bad` dependency for `webrtcbin`; webkitgtk 4.1 `set_enable_webrtc` dance; NVIDIA-specific encoder/decoder path. But this is a well-trodden GStreamer path and the Rust `webrtcsink` / `gst-plugin-webrtc` crate is production-quality.
- **Compatibility:** doesn't touch Reverie. Interacts well with face-obscure (upstream). Second reader on `/dev/video42` same risk as Option 3.
- **Verdict:** highest quality that stays within the webview. Real implementation cost. Best long-term answer if quality demands exceed what Option 1+2 can deliver.

### 4.1 Recommendation

**Staged path: Option 2 (MJPEG transport swap) + Option 1 (quality/framerate bump), contingent on framerate/compression being the operator's actual concern.**

Rationale:

- If operator's concern is chiefly **framerate stutter** (the most likely reading of "vastly inferior"), Options 1+2 together close 80–90% of the gap with minimal risk.
- The combination preserves the current producer architecture, doesn't introduce a second v4l2 consumer, and doesn't fight the Wayland/NVIDIA/webkitgtk interaction.
- If after shipping Options 1+2 the compression artifacts remain perceptually objectionable, escalate to Option 5 (WebRTC) as a discrete follow-up. Option 5 is the only path that delivers OBS-equivalent quality inside the webview.
- Option 3 (raw buffer IPC) is theoretically lower-latency than Option 5 but pays a JS-side NV12→RGB decode cost per frame and has more JS LOC; WebRTC is the cleaner architecture.
- Option 4 is rejected outright.

The §10 open-questions list asks operator to rank framerate vs compression, which will pin whether Options 1+2 suffice or whether we escalate.

## §5. Specific pipeline components for recommended path (Options 1 + 2)

### 5.1 Producer-side (compositor) — `agents/studio_compositor/snapshots.py`

- Lines 109–114: raise `max-rate` and `framerate` caps from 3 to ≥10 (conservative) or 30 (full). Add env override `HAPAX_FX_SNAPSHOT_FPS` so we can A/B without redeploy.
- Line 116: raise `jpegenc.quality` from 85 to 92 (conservative) or 95 (full). Add env override `HAPAX_FX_SNAPSHOT_QUALITY`.
- Line 117: update the informational log line.
- Optional: switch from `jpegenc` (CPU) to `nvjpegenc` (GPU). The function docstring (lines 83–87) already mentions NVIDIA HW-JPEG as the original design intent; the CPU fallback was a deliberate 2026-04-17 simplification. Restoring `nvjpegenc` with a `jpegenc` fallback recovers CPU headroom so we can run at q=95 × 30 fps without the audit regression. ~20 LOC for the element negotiation.
- Estimate: 30–50 LOC changed.

### 5.2 Transport — `hapax-logos/src-tauri/src/visual/http_server.rs` and `fx_relay.rs`

- New handler `serve_fx_mjpeg` on `GET /fx.mjpg`. Subscribe to the broadcast channel, stream an HTTP response with `Content-Type: multipart/x-mixed-replace; boundary=frame`, per-part `--frame\r\nContent-Type: image/jpeg\r\nContent-Length: N\r\n\r\n<bytes>\r\n`. Use axum's `Sse`-style streaming (`axum::body::Body::from_stream`) over a `tokio_stream::wrappers::BroadcastStream`.
- Route registration at `http_server.rs:113-118`.
- Broadcast channel capacity at `fx_relay.rs:14` — raise from 4 to 16 to absorb 30 fps × ~0.5 s of slack on slow clients.
- Estimate: ~60 LOC new Rust, 2 LOC channel capacity change.

### 5.3 Client — `hapax-logos/src/components/graph/nodes/OutputNode.tsx`

- Keep the current WebSocket path as **fallback** (useful for the stale-detection ref). Add a mode flag.
- Replace the `<img>` `src` assignment with a static `src="http://127.0.0.1:8053/fx.mjpg"` for the fullscreen overlay and node view.
- Remove the `useFxStream` imperative loop for the MJPEG code path; the browser handles framing. Retain the `lastSuccess`/`isStale` ref but drive it off `imgRef.current.onload` events fired by each multipart part.
- Estimate: ~40 LOC changed, ~80 LOC retained as fallback.

Total: ~150 LOC across Rust and React, one Python module change.

## §6. Performance budget

### 6.1 GPU/CPU cost of the recommended path

- **Compositor CPU:** `jpegenc` at 1280×720 × 30 fps × q=95 measures at ~12–18% of one core on this workstation (historic data from the 2026-04-17 audit baseline). Swapping to `nvjpegenc` drops this to ≤2% of one core plus ~30–60 MB of intermittent VRAM pressure on the encoder. Net CPU delta vs current: +0–5% of one core if `nvjpegenc` is used, +15% if CPU fallback is hit.
- **Compositor GPU:** the compositor is already GPU-bound via `cudacompositor` + `glfeedback` + `nvh264enc` (RTMP). Adding `nvjpegenc` on a separate branch is on the same GPU context; it contends with `nvh264enc` for VRAM bandwidth but both are well under the budget ceiling. Budget pin: the Reverie pipeline consumes ~2.5 GB VRAM; adding `nvjpegenc` adds <100 MB.
- **Tauri CPU:** the webview JPEG decoder runs at ~1–2% of one core at 30 fps. Current path at 3 fps measures <0.5%. Delta: +1.5% of one core in the GUI process.
- **Network/loopback:** 30 fps × ~100 KB/frame = 3 MB/s over `127.0.0.1`, negligible.
- **Memory:** broadcast channel capacity bump 4→16 × ~100 KB = ~1.5 MB extra. Object-URL churn in the browser settles to steady state after GC.

### 6.2 What must not regress

- **Main v4l2sink branch** (`/dev/video42` → OBS → RTMP). This is the fortress. All changes happen on the `fx_snapshot` branch after the `output_tee`; v4l2sink is untouched.
- **RTMP encode latency.** `nvh264enc` on the main branch must retain GPU priority. If `nvjpegenc` contention is observable, gate the snapshot encoder to 15 fps under streaming load (detect via `HAPAX_COMPOSITOR_STREAMING=1` set by the RTMP affordance activation).
- **Reverie rendering.** Untouched — different daemon, different pipeline.
- **Compositor watchdog.** `sdnotify` heartbeat at 60 s cadence; the snapshot branch must not stall long enough to block the main loop. The existing background-sender thread pattern already decouples file I/O and TCP I/O; adding `nvjpegenc` does not change that.

### 6.3 NVIDIA-specific considerations

The workstation runs NVIDIA 590.48.01 (pinned in pacman config after the 595.58 SIGSEGV incident). `__NV_DISABLE_EXPLICIT_SYNC=1` is set in the compositor's systemd unit and `.envrc`. Any new GStreamer element that touches GL (`glupload`, `glcolorconvert`) must be tested against both the explicit-sync-disabled path and the Wayland syncobj protocol. `nvjpegenc` is a downloading encoder (GL → system memory JPEG), so it does not add new GL-side state.

## §7. Interaction with nebulous scrim (#174)

`docs/research/2026-04-20-nebulous-scrim-design.md` proposes a scrim-aware reorganization of the compositor's composite layer — atmospheric perspective, differential blur, depth-cue-driven opacity gradients across ward and camera surfaces. The scrim reading is designed to be legible *on the final composite*. If the Logos fullscreen view is to become the "proper window into the studio", it must present the scrim faithfully.

Two implications for the quality work:

1. **JPEG q=85 flattens scrim differentials.** The scrim design relies on 4–8 perceptually-distinct opacity/blur bands across a frame. JPEG q=85 quantization introduces chroma banding that visually competes with the designed bands, especially in the mid-tones where the scrim's atmospheric-perspective tier sits. q=92+ is a functional requirement for scrim legibility.
2. **3 fps drops the differential-blur reading.** The scrim's differential blur (foreground sharp, background soft, with per-element modulation by the Stimmung-surface coherence scalar) reads as *motion softness gradient* — parallax and motion blur are part of the vocabulary. Below 10 fps the differential degenerates into static blur levels indistinguishable from a still. The scrim requires ≥15 fps to read as designed; 30 fps is ideal.

Conclusion: the nebulous scrim system raises the minimum quality bar on this pipeline from "preview-grade" to "reading surface". The current 3 fps × q=85 is below scrim-legible and must be addressed as part of integration of #174.

## §8. Interaction with face-obscure (#129)

Per `docs/superpowers/plans/2026-04-18-facial-obscuring-plan.md` and `agents/studio_compositor/face_obscure_integration.py`, face-obscure runs **upstream** of the `output_tee` (i.e., before the split that feeds v4l2sink, HLS, fx_snapshot, RTMP). It pixelates every camera frame fail-CLOSED on detector failure.

Implications for Logos consumption:

- Any Logos path that consumes from the `output_tee` — the current `fx_snapshot`, a hypothetical second v4l2loopback, a hypothetical WebRTC bin — sees already-obscured faces. **No separate consent gate is needed at the Logos boundary.**
- This is why the consent gate retirement note in `CLAUDE.md` applies: visual privacy is enforced at the face-obscure pipeline, not at egress consumers.
- Options 3 and 5 (the more invasive ones) do not change the consent posture — the obscuring happens before they could possibly see the frame.
- Any future change to where face-obscure sits in the pipeline (e.g., moving it downstream of fx_snapshot to save GPU work) would break this invariant and is explicitly out of scope.

## §9. Integration sequencing

Six phases, gated by operator input at the top.

### Phase 0 — disambiguation confirmation (blocking)

Operator confirms `OutputNode` is the surface in question, and ranks framerate vs compression as the perceived gap. Decision gate: if operator says "compression artifacts are the problem", escalate directly to Phase 5 (WebRTC). If operator says "stuttering motion is the problem", proceed through Phases 1–4 first.

### Phase 1 — producer quality bump (Option 1, safe floor)

- `snapshots.py`: framerate 3→10, quality 85→92. Add env overrides.
- `fx_relay.rs`: broadcast channel capacity 4→16.
- Deploy via `hapax-compositor.service` restart. Smoke test: OutputNode at 10 fps, visible improvement, no compositor CPU regression beyond baseline.

### Phase 2 — MJPEG transport (Option 2)

- New `/fx.mjpg` handler in `http_server.rs`.
- `OutputNode.tsx` switches to `<img src="http://127.0.0.1:8053/fx.mjpg">` for fullscreen, keeps WebSocket path for node-view (preserves the stale-detection ref).
- Ship behind a feature flag (`HAPAX_LOGOS_MJPEG=1`) for one session before defaulting on.

### Phase 3 — nvjpegenc swap

- `snapshots.py`: try `nvjpegenc` first, fall back to `jpegenc`. Raises headroom to run at framerate=30 × q=95 without CPU regression.
- Measure GPU VRAM delta, compositor CPU delta, end-to-end latency.

### Phase 4 — evaluation gate

- Operator review of quality at framerate=30 × q=95 × MJPEG + nvjpegenc.
- Decision: good enough (stop) or escalate to Phase 5 (WebRTC).

### Phase 5 — WebRTC (Option 5, only if Phase 4 fails)

- Rust: `webrtcbin` pipeline, signalling channel via Tauri IPC, SDP negotiation.
- JS: `RTCPeerConnection` + `<video>` tag in `FullscreenOverlay`.
- Face-obscure and scrim invariants preserved (both upstream of new consumer).
- Add a second `v4l2sink` to `/dev/video43` if multi-reader on `/dev/video42` conflicts with OBS.

### Phase 6 — retirement

- If Phase 5 ships, the `fx_snapshot` branch becomes the *fallback* path. Keep it for the stale/degraded case and for any future use that can't consume WebRTC.
- Update `docs/logos-design-language.md` and the Tauri-Only Runtime section of the council `CLAUDE.md` to reflect the new consumption path.

## §10. Open questions for operator

1. **Surface confirmation.** Is "output node" the ReactFlow `OutputNode` (shown in the graph view and fullscreenable via Shift+F or double-click)? Or are you looking at a different surface? If different, which one.
2. **Gap character.** The gap is some mix of resolution, framerate, and compression. Which dominates the perception? "Stuttery" (framerate) or "fuzzy/blocky" (compression) or "small/cropped" (resolution)?
3. **Fullscreen vs node-view.** Is the complaint primarily about the fullscreen overlay, or about the node-view inside the graph canvas? They share the same producer, but fullscreen spans the whole display and exposes artifacts more than the ~420×260 node.
4. **Pixel parity.** Does Logos fullscreen need to match OBS pixel-for-pixel at 30 fps lossless, or is "good enough preview" acceptable? The former requires WebRTC (Phase 5); the latter is reachable with Phases 1–3.
5. **Multi-monitor.** Does the fullscreen overlay need to target a specific monitor (e.g., the secondary display while OBS runs on primary)? Current `set_window_fullscreen` uses the window's current display.
6. **Streaming-load gating.** Should the quality bump back off automatically when livestream RTMP is active (to preserve GPU for `nvh264enc`), or should Logos always get full quality regardless of stream state?
7. **Timing.** Is this fix needed for the next livestream session, or is it a slow-track polish item? Phase 1 alone is same-session shippable; Phase 5 is ≥1 week of focused work.

---

### File reference index (repo-relative)

- `hapax-logos/src/components/graph/nodes/OutputNode.tsx`
- `hapax-logos/src/components/graph/StudioCanvas.tsx`
- `hapax-logos/src/components/visual/VisualSurface.tsx`
- `hapax-logos/src-tauri/src/visual/http_server.rs`
- `hapax-logos/src-tauri/src/visual/fx_relay.rs`
- `agents/studio_compositor/snapshots.py`
- `agents/studio_compositor/pipeline.py`
- `agents/studio_compositor/config.py`
- `agents/studio_compositor/models.py`
- `docs/research/2026-04-20-nebulous-scrim-design.md`
- `docs/superpowers/plans/2026-04-18-facial-obscuring-plan.md`

### External references

- Tauri v2 WebRTC in webkitgtk_4_1: https://github.com/orgs/tauri-apps/discussions/8426
- GStreamer webrtcbin documentation: https://gstreamer.freedesktop.org/documentation/webrtc/index.html
- `gst-plugin-webrtc` (Rust): https://crates.io/crates/gst-plugin-webrtc
- Tauri + video rendering canvas/native discussion: https://github.com/tauri-apps/wry/discussions/284
- Tauri 2.0 stable release (multiwebview unstable flag): https://v2.tauri.app/blog/tauri-20/
- MJPEG-over-HTTP server reference (blueimp): https://github.com/blueimp/mjpeg-server
- Python WebSocket image streaming (PyImageStream, latency discussion): https://github.com/Bronkoknorb/PyImageStream
- webrtcsink (Rust, adaptive bitrate, multi-peer): https://mathieuduponchelle.github.io/2021-12-14-webrtcsink.html
