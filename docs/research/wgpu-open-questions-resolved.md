# wgpu Rendering Engine: Open Questions Resolved

**Date**: 2026-03-17
**Status**: All questions answered — no hard blockers
**Depends on**: [Multi-Technique Rendering Architecture](multi-technique-rendering-architecture.md)

---

## Summary

12 technical questions researched for building a wgpu-based rendering engine on CachyOS/Hyprland with RTX 3090.

| # | Question | Status |
|---|----------|--------|
| 1 | wgpu + Wayland/Hyprland | Works (NVIDIA quirks, layer-shell needs SCTK) |
| 2 | Framebuffer readback | Solved (staging buffer, ~8MB/frame at 1080p) |
| 3 | WGSL vs GLSL | Solved (Naga transpiles, wgpu accepts GLSL directly) |
| 4 | wgpu-py prototyping | Solved (1:1 API map to Rust, offscreen works) |
| 5 | Reaction-diffusion | Solved (multiple WGSL implementations, 16x16 workgroups) |
| 6 | Physarum | Solved (Rust+wgpu implementations, 10M+ agents on 3090) |
| 7 | GStreamer bridge | Solved (shmsink/shmsrc cleanest path) |
| 8 | Multi-monitor | Solved (Hyprland window rules or SCTK layer-shell) |
| 9 | HDR | Partial (internal HDR + tonemap to sRGB, wgpu lacks HDR surfaces) |
| 10 | Build/packaging | Solved (cargo + systemd user service + /dev/shm config) |
| 11 | Hot-reload | Solved (notify crate + pipeline recreation, sub-ms) |
| 12 | Existing examples | Rich (cuneus is closest prior art) |

---

## Key Decisions Made

1. **Window management**: Use Hyprland window rules (`fullscreen, monitor DP-3, nofocus, pin`) rather than layer-shell. Simpler, no SCTK dependency.

2. **GStreamer bridge**: shmsink/shmsrc over a Unix domain socket. Decoupled processes, clean boundary.

3. **Shader language**: Write new shaders in WGSL. Port existing GLSL via Naga CLI (`naga input.glsl output.wgsl`). Use `wgpu::ShaderSource::Glsl` for shaders that resist conversion.

4. **HDR strategy**: Render internally in `Rgba16Float` for wide dynamic range. Tonemap to `Bgra8UnormSrgb` for surface output. Revisit when wgpu exposes HDR surfaces.

5. **Prototyping**: Use wgpu-py for shader iteration. Same WGSL files, same API structure, ports cleanly to Rust.

6. **Prior art**: cuneus (altunenes/cuneus) — shader engine with hot reload, compute, audio/video input, multi-pass. Study and adapt, don't clone.

---

## Caveats to Watch

1. **NVIDIA Wayland event loop freeze** (winit #3551) — may need workaround if triggered by our always-visible window. Monitor the issue.

2. **Framebuffer readback latency** — staging buffer map_async adds ~1-2ms per frame. At 60fps this is fine (16ms budget). If we later target 144fps, DMA-BUF zero-copy becomes necessary (requires raw Vulkan hal API).

3. **wgpu-py is 0.31.0** — pre-1.0, API may shift. Use for prototyping only, not production.

---

## Sources

- [winit Wayland issues](https://github.com/rust-windowing/winit/issues/3551)
- [wgpu DMA-BUF issue](https://github.com/gfx-rs/wgpu/issues/2320)
- [Naga shader compiler](https://github.com/gfx-rs/naga)
- [wgpu-py](https://github.com/pygfx/wgpu-py)
- [Gray-Scott in WebGPU (Codrops)](https://tympanus.net/codrops/2024/05/01/reaction-diffusion-compute-shader-in-webgpu/)
- [physarum-rust](https://github.com/tom-strowger/physarum-rust)
- [GStreamer shmsrc](https://gstreamer.freedesktop.org/documentation/shm/shmsrc.html)
- [Hyprland Window Rules](https://wiki.hypr.land/Configuring/Window-Rules/)
- [wgpu HDR surface issue](https://github.com/gfx-rs/wgpu/issues/2920)
- [cuneus shader engine](https://github.com/altunenes/cuneus)
- [Hot-reload WGSL shaders](https://altunenes.github.io/posts/hotreload/)
