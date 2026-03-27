# Tauri 2 Crashes on Native Wayland — GTK Protocol Error 71

## Problem

`hapax-logos` (Tauri 2 native app) crashes immediately after the webview renders its first frame on native Wayland. The crash occurs even with `HAPAX_NO_VISUAL=1` (wgpu visual surface disabled), confirming it's not related to our GPU pipeline.

## Error

```
Gdk-Message: 10:48:30.214: Error 71 (Protocol error) dispatching to Wayland display.
```

The process exits with code 1 immediately after this message. No stack trace — it's a GDK/GTK-level abort.

## Environment

- **OS:** CachyOS (Arch-based), kernel 6.18.16-1-cachyos-lts
- **Compositor:** Hyprland (Wayland)
- **GPU:** NVIDIA GeForce RTX 3090, driver 590.48.01 (open kernel module)
- **GTK:** Check with `pacman -Q gtk4 gtk3 webkit2gtk-4.1`
- **Tauri:** 2.10.3 (check `Cargo.lock` for exact version)
- **wry:** Check `Cargo.lock` — this is Tauri's webview abstraction over webkit2gtk
- **Session type:** `XDG_SESSION_TYPE=wayland`, `WAYLAND_DISPLAY=wayland-1`
- **GDK_BACKEND:** Not set (defaults to Wayland native)

## Reproduction

```bash
cd ~/projects/hapax-council/hapax-logos
HAPAX_NO_VISUAL=1 RUST_LOG=info pnpm tauri dev
```

The app compiles, Vite starts, the Rust binary launches, logs show:
```
[INFO  hapax_logos] Visual surface disabled (HAPAX_NO_VISUAL=1)
[INFO  hapax_logos::visual::http_server] Visual frame server listening on http://127.0.0.1:8053
[INFO  hapax_logos::commands::relay] Command relay listening on ws://127.0.0.1:8052
```

Then immediately:
```
Gdk-Message: 10:48:30.214: Error 71 (Protocol error) dispatching to Wayland display.
```

Process exits. The webview window may flash briefly before dying.

## Workaround

Forcing X11 (XWayland) backend works:

```bash
cd ~/projects/hapax-council/hapax-logos
GDK_BACKEND=x11 HAPAX_NO_VISUAL=1 pnpm tauri dev
```

App launches and runs correctly. There's a non-fatal `Failed to create GBM buffer of size 1270x694: Invalid argument` warning but the app functions.

## What We Know

1. **Not our code.** The crash happens with `HAPAX_NO_VISUAL=1` which skips all wgpu/winit initialization. The only Rust code running is: Tauri builder, axum HTTP server (tokio), tokio-tungstenite WebSocket server, and the directive watcher. None of these touch Wayland.

2. **The crash is in GTK/GDK.** Error 71 is `EINVAL` or a Wayland protocol error. GDK is the GTK display abstraction layer. The message comes from GDK's Wayland backend encountering an invalid protocol state.

3. **webkit2gtk is the likely trigger.** Tauri 2 on Linux uses wry, which uses webkit2gtk for the webview. webkit2gtk creates its own GL/EGL context for compositing web content. On Wayland with NVIDIA's proprietary driver, there are known compatibility issues with EGL/GBM buffer allocation.

4. **NVIDIA + Wayland + GBM is a known pain point.** The `Failed to create GBM buffer` error in the X11 workaround path suggests the NVIDIA driver's GBM implementation has issues with certain buffer configurations. On native Wayland, this may escalate to a protocol error.

5. **May be driver or webkit2gtk version specific.** The pinned NVIDIA driver (590.48.01) is older — we downgraded from 595.58 due to DF crashes (see `feedback_nvidia_595_crash.md` in memory). The combination of old driver + current webkit2gtk + Hyprland may be the trigger.

## Root Cause (Resolved)

`WAYLAND_DEBUG=1` trace reveals the exact protocol error:

```
wl_display#1.error(wp_linux_drm_syncobj_surface_v1#57, 4, "Missing acquire timeline")
```

**webkit2gtk 2.50.6** binds the `wp_linux_drm_syncobj_manager_v1` protocol and creates a syncobj surface for its DMA-BUF rendering path. However, it commits the Wayland surface without providing the required acquire timeline. Hyprland rejects this as protocol error code 4, which GDK surfaces as "Error 71 (Protocol error)".

The sequence in the trace:
1. webkit2gtk binds `wp_linux_drm_syncobj_manager_v1` and creates a syncobj surface (#57)
2. webkit2gtk creates a DMA-BUF via `zwp_linux_dmabuf_v1` — buffer allocation succeeds
3. webkit2gtk attaches the buffer and commits `wl_surface#32`
4. Hyprland rejects: syncobj surface requires an acquire timeline on commit, but none was provided
5. GDK catches the protocol error → abort

**Fix:** `__NV_DISABLE_EXPLICIT_SYNC=1` disables NVIDIA's explicit sync, preventing the protocol error while retaining GPU hardware acceleration (~21ms frame times vs ~27ms with DMABUF disabled). `WEBKIT_DISABLE_DMABUF_RENDERER=1` also works but forces software rendering.

**Applied:**
- `systemd/units/hapax-logos.service` — `Environment=__NV_DISABLE_EXPLICIT_SYNC=1`
- `.envrc` — `export __NV_DISABLE_EXPLICIT_SYNC=1` for dev workflow

**Upstream:** Known bugs: [gtk#8056](https://gitlab.gnome.org/GNOME/gtk/-/issues/8056), [tauri#10702](https://github.com/tauri-apps/tauri/issues/10702), [WebKit#280210](https://bugs.webkit.org/show_bug.cgi?id=280210). GTK3 attaches buffer to the same EGL surface without setting acquire point. No fix in any webkit2gtk release through 2.50.x. Tauri labels this `status: upstream`.

### Additional wgpu fixes (discovered during investigation)

Three wgpu validation errors were also crashing the visual surface:

1. **Physarum bind group layout** — `ReadWrite` storage texture requires `TEXTURE_ADAPTER_SPECIFIC_FORMAT_FEATURES`.
   Fix: `gpu.rs` — request the feature in `DeviceDescriptor::required_features`.

2. **Compositor sampler mismatch** — Wave and Physarum outputs are `R32Float` (non-filterable), but the compositor used a `Filtering` sampler.
   Fix: `compositor.rs` — changed to `NonFiltering` sampler with `Nearest` filter mode. All textures are composited at the same resolution, so linear filtering wasn't needed.

3. **Physarum trail texture missing `COPY_SRC`** — The trail texture was missing the `COPY_SRC` usage flag.
   Fix: `techniques/physarum.rs` — added `COPY_SRC` to usage flags.

4. **SHM staging buffer still mapped** — `write_frame()` called `map_async` but never polled the device, so the callback never fired within the 5ms timeout. Buffer stayed pending-mapped, and the next frame's `queue.submit` failed.
   Fix: `output.rs` — added `device.poll(Maintain::Wait)` after `map_async` to drive the callback.

## Investigation Path (completed)

1. **Check versions:**
   ```bash
   pacman -Q gtk4 gtk3 webkit2gtk-4.1 webkit2gtk nvidia-open-dkms
   grep -A2 'name = "wry"' ~/projects/hapax-council/hapax-logos/src-tauri/Cargo.lock
   grep -A2 'name = "tauri"' ~/projects/hapax-council/hapax-logos/src-tauri/Cargo.lock | head -5
   ```

2. **Check if this is a known Tauri issue:**
   - Search Tauri GitHub issues for "Protocol error" + "Wayland"
   - Search wry issues for "GBM" or "Error 71" or "Wayland NVIDIA"
   - Search webkit2gtk issues for similar

3. **Test with environment variables:**
   ```bash
   # Try different GL backends
   WEBKIT_DISABLE_COMPOSITING_MODE=1 pnpm tauri dev
   WEBKIT_DISABLE_DMABUF_RENDERER=1 pnpm tauri dev
   GDK_GL=gles pnpm tauri dev
   GDK_GL=ngl pnpm tauri dev
   GSK_RENDERER=cairo pnpm tauri dev

   # Try disabling hardware acceleration in webkit
   # (may need wry/tauri config change)
   ```

4. **Test with newer NVIDIA driver:**
   - Current: 590.48.01 (pinned due to DF crash)
   - If 595.x is available and DF isn't running, test temporarily

5. **Get a more detailed error:**
   ```bash
   WAYLAND_DEBUG=1 pnpm tauri dev 2>&1 | tee /tmp/wayland-debug.log
   # Then search for the last few messages before the crash
   ```

6. **Check if a minimal Tauri app also crashes:**
   ```bash
   # Create a minimal test app with cargo create-tauri-app
   # If it also crashes → platform issue, not our code
   # If it works → something in our setup triggers it
   ```

## Resolution Options

| Option | Effort | Impact |
|--------|--------|--------|
| `GDK_BACKEND=x11` in systemd unit / launcher | Low | Workaround — XWayland overhead, but functional |
| Fix via webkit2gtk env vars | Low | May resolve if it's a specific renderer path |
| Update NVIDIA driver | Medium | May fix, may break DF (test both) |
| Report upstream to Tauri/wry | Low | Long-term fix but slow |
| Pin webkit2gtk to a known-good version | Medium | Arch doesn't make this easy |

## Files Referenced

- `hapax-logos/src-tauri/src/main.rs` — Tauri app entry point
- `hapax-logos/src-tauri/tauri.conf.json` — Window config (no `transparent: true`)
- `hapax-logos/src-tauri/Cargo.toml` — Dependencies
- `hapax-logos/src-tauri/Cargo.lock` — Exact versions
- Memory: `feedback_nvidia_595_crash.md` — Prior NVIDIA driver issue
- Memory: `feedback_vrr_flicker.md` — VRR/FreeSync issues on same hardware
