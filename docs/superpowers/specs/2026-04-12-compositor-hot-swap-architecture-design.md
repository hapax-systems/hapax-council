# Compositor Hot-Swap Architecture — Design (Camera Epic Phase 2)

**Filed:** 2026-04-12
**Status:** Formal design. Implementation in Phase 2 of the camera resilience epic.
**Epic:** `docs/superpowers/plans/2026-04-12-camera-247-resilience-epic.md`
**Research backing:** `docs/superpowers/specs/2026-04-12-camera-247-resilience-research.md`
**Related external work:** delta's `docs/superpowers/specs/2026-04-12-compositor-source-registry-foundation-design.md` (PR #709). This document describes how the two architectures compose.

## Purpose

Refactor studio compositor camera ingestion so that any single-camera fault — USB disconnect, v4l2 stall, GStreamer element error, kernel driver hang — is contained to that camera's own pipeline scope and recovered without restarting the composite pipeline. Cameras become hot-swappable between a healthy producer and a failsafe fallback producer at runtime, with the switching decision taking at most 2 s from observable stall to fallback display.

The present compositor puts all six camera v4l2src elements in a single `GstPipeline`. Any element-level error on any camera branch tears the whole pipeline down; only systemd restart recovers. This design replaces that topology.

## Requirements

Inherited from the epic. Restated here in implementation-flavored terms.

- **R1.** A camera fault must not affect any other camera, the composite output, the RTMP encoder (Phase 5), or the Cairo overlay path.
- **R2.** When a camera fails, its slot in the composite shows a failsafe frame within 2 s (failure observation + state transition + hot-swap).
- **R3.** When a camera recovers (USB re-enumeration, operator plug-in), its slot shows live frames within 10 s.
- **R4.** Hot-swap between healthy and failsafe states is a runtime operation — zero pipeline restart, zero caps renegotiation, zero frame loss on the OTHER five cameras.
- **R5.** Camera addition, removal, or configuration change does not require touching the compositor process. Config lives in `config.py` still (alpha's scope); a later epic will migrate it to `~/.config/hapax-compositor/layouts/default.json` per delta's PR #709 design.
- **R6.** The architecture composes with delta's `Layout/SourceSchema/Assignment` model without requiring rework. Each camera is a valid future `SourceSchema` with `backend: "v4l2_camera"`.
- **R7.** Latency budget: glass-to-compositor ≤ 200 ms sustained under normal operation; glass-to-RTMP ≤ 500 ms sustained (Phase 5 concern).
- **R8.** GPU budget: no increase in CUDA VRAM usage or compositor GPU time vs the current single-pipeline topology.

## Architecture overview

Present topology:

```
┌───────────── GstPipeline "composite" (single) ─────────────┐
│  v4l2src ─ caps ─ jpegdec ┐                                 │
│  v4l2src ─ caps ─ jpegdec ┤                                 │
│  v4l2src ─ caps ─ jpegdec ┼─► compositor ─► tee ─► sinks    │
│  v4l2src ─ caps ─ jpegdec ┤                                 │
│  v4l2src ─ caps ─ jpegdec ┤                                 │
│  v4l2src ─ caps ─ jpegdec ┘                                 │
└──────────────────────────────────────────────────────────────┘
Error on any v4l2src → pipeline NULL → systemd restart cycle.
```

New topology:

```
┌─ GstPipeline "cam_brio_operator" ─┐  ┌─ GstPipeline "fb_brio_operator" ─┐
│  v4l2src ─ caps ─ watchdog ─      │  │  videotestsrc pattern=ball ─     │
│  jpegdec ─ videoconvert ─ scale ─ │  │  textoverlay "CAMERA OFFLINE" ─  │
│  caps ─ interpipesink             │  │  videoconvert ─ caps ─           │
│  name=cam_brio_operator           │  │  interpipesink name=fb_brio_operator │
└───────────────────────────────────┘  └──────────────────────────────────┘
              │                                         │
              │ (runtime listen-to switch)              │
              ▼                                         ▼
┌───────────── GstPipeline "composite" ────────────────────────┐
│  interpipesrc listen-to=cam_brio_operator ┐                   │
│  interpipesrc listen-to=cam_brio_room ────┤                   │
│  interpipesrc listen-to=cam_brio_synths ──┼─► compositor ...  │
│  interpipesrc listen-to=cam_c920_desk ────┤                   │
│  interpipesrc listen-to=cam_c920_room ────┤                   │
│  interpipesrc listen-to=cam_c920_overhead ┘                   │
└────────────────────────────────────────────────────────────────┘

(6 cameras × 2 producer pipelines each + 1 composite = 13 GstPipeline instances)
```

Error on `cam_brio_operator` → contained to that producer pipeline → supervisor tears it down and rebuilds, meanwhile the composite's consumer swaps `listen-to=fb_brio_operator` → five other cameras and the composite pipeline are unaffected.

Thirteen `GstPipeline` instances total: six camera producers, six fallback producers, one composite consumer. Each producer has a single sink element (`interpipesink`) that exports its stream under a globally-unique name. The composite's `interpipesrc` elements select which producer they consume by setting the `listen-to` string property — a thread-safe GObject property write that takes effect immediately with zero state manipulation.

### Why interpipe

Research (`docs/superpowers/specs/2026-04-12-camera-247-resilience-research.md` § 5.2, confirmed in implementation-research agent 1's report) finds `gst-interpipe` provides the "cross-pipeline bounded-error-scope + zero-cost hot-swap" primitive this design needs. It is maintained by RidgeRun, uses the standard GStreamer GObject model, and is thread-safe for the `listen-to` write by explicit design.

Alternatives considered in § Alternatives.

### Caps normalization

All camera producer pipelines emit `video/x-raw, format=NV12, width=1920, height=1080, framerate=30/1` via a trailing `videoconvert → videoscale → capsfilter`. All fallback producer pipelines emit the same caps. This means the composite's `interpipesrc allow-renegotiation=TRUE` (default) never has to actually renegotiate in steady state — the caps are already identical across every possible producer the consumer might switch to.

Camera-native capture formats (BRIO 1920×1080 MJPEG, C920 1920×1080 MJPEG) are decoded and scaled inside each producer pipeline. The composite pipeline only ever sees normalized NV12 1080p30. This is slightly more per-camera CPU than the current topology (scaling in the producer instead of the compositor), but CPU is not the binding constraint (GPU is), and keeping the composite caps stable is more important than minor CPU delta.

## Component design

### CameraPipeline

`agents/studio_compositor/camera_pipeline.py` (new file).

One instance per real camera. Owns a `Gst.Pipeline` and the watchdog + bus wiring for that one camera.

```python
class CameraPipeline:
    """Isolated GstPipeline wrapping a single v4l2 camera."""

    def __init__(self, spec: CameraSpec, *, supervisor: "PipelineManager") -> None:
        self._spec = spec
        self._supervisor = supervisor
        self._pipeline: Gst.Pipeline | None = None
        self._bus: Gst.Bus | None = None
        self._watchdog_name = f"watchdog_{spec.role}"
        self._sink_name = f"cam_{spec.role}"
        self._last_frame_monotonic = 0.0
        self._frame_count = 0
        self._kernel_drops = 0
        self._last_sequence = -1
        self._state_lock = threading.Lock()

    def build(self) -> None:
        """Construct the GstPipeline graph. Does not start streaming."""

    def start(self) -> bool:
        """Transition to PLAYING. Returns False on failure."""

    def stop(self) -> None:
        """Transition to NULL. Idempotent."""

    def is_healthy(self) -> bool:
        """True if the last frame arrived within the staleness window."""

    def teardown(self) -> None:
        """Full NULL + element dispose. Idempotent."""

    def rebuild(self) -> bool:
        """Teardown + build + start. Exponential-backoff call site (Phase 3)."""
```

Graph constructed by `build()`:

```
v4l2src device=/dev/v4l/by-id/... name=src_<role>
  ! image/jpeg,width={w},height={h},framerate={fps}/1
  ! watchdog timeout=2000 name=watchdog_<role>
  ! jpegdec name=dec_<role>
  ! videoconvert name=vc_<role>
  ! videoscale name=scale_<role>
  ! video/x-raw,format=NV12,width=1920,height=1080,framerate=30/1
  ! interpipesink name=cam_<role> sync=false async=false forward-events=false
```

Key property settings:

- `interpipesink sync=false async=false`: the producer's clock is decoupled from the consumer. Required; v4l2 cameras have their own clocks and trying to sync them to the compositor clock causes perpetual late-buffer warnings.
- `interpipesink forward-events=false`: prevents EOS propagation from producer to consumer on teardown. Without this, tearing down a camera pipeline can emit an EOS on the composite pipeline.
- `watchdog timeout=2000`: **milliseconds**, not nanoseconds — verified against `gst/debugutils/gstwatchdog.c` in gst-plugins-bad master. Fires `GST_MESSAGE_ERROR` on this pipeline's bus when no buffers flow for 2 s.

Each `CameraPipeline` has its own bus watch installed via `self._bus = self._pipeline.get_bus(); self._bus.add_signal_watch(); self._bus.connect("message", self._on_bus_message)`. Errors on this bus are handled by `_on_bus_message`, which logs, marks the pipeline unhealthy, and schedules a `GLib.idle_add` callback that drives the supervisor's `swap_to_fallback(role)`. The bus signal does NOT propagate to the composite pipeline's bus — distinct `GstPipeline` instances have distinct buses, by design.

### FallbackPipeline

`agents/studio_compositor/fallback_pipeline.py` (new file).

One instance per real camera, paired 1:1. Owns a `Gst.Pipeline` with a synthetic live source.

```
videotestsrc pattern=ball is-live=true name=fbsrc_<role>
  ! video/x-raw,format=BGRA,width=1920,height=1080,framerate=30/1
  ! textoverlay text="CAMERA {role.upper()} OFFLINE" font-desc="Sans Bold 60" halignment=center valignment=center
  ! videoconvert
  ! video/x-raw,format=NV12,width=1920,height=1080,framerate=30/1
  ! interpipesink name=fb_<role> sync=false async=false forward-events=false
```

Runs continuously from compositor start to compositor stop. CPU cost of six `videotestsrc` pipelines is minimal — `videotestsrc` is one of the cheapest GStreamer elements. The fallback pipelines never stop because the composite's `interpipesrc.listen-to` switch is only instant if the target producer is already playing.

`pattern=ball` (bouncing ball) was chosen over `pattern=smpte` (test pattern bars) because the bouncing ball is immediately recognizable as "no camera here" while the SMPTE bars look plausible as a valid broadcast frame.

### PipelineManager

`agents/studio_compositor/pipeline_manager.py` (new file).

One instance owned by `StudioCompositor`. Orchestrates all 12 producer pipelines and coordinates with the composite pipeline for hot-swap operations.

```python
class PipelineManager:
    def __init__(self, *, specs: list[CameraSpec], compositor: "StudioCompositor") -> None:
        self._compositor = compositor
        self._specs = specs
        self._cameras: dict[str, CameraPipeline] = {}
        self._fallbacks: dict[str, FallbackPipeline] = {}
        self._states: dict[str, "CameraStateMachine"] = {}
        self._interpipe_srcs: dict[str, Gst.Element] = {}
        self._lock = threading.RLock()

    def build(self) -> None:
        """Instantiate cameras and fallbacks, start them, set up state machines."""

    def register_consumer(self, role: str, interpipe_src: Gst.Element) -> None:
        """Associate a composite-pipeline interpipesrc with a camera role."""

    def swap_to_fallback(self, role: str) -> None:
        with self._lock:
            src = self._interpipe_srcs.get(role)
            if src is None:
                return
            src.set_property("listen-to", f"fb_{role}")
            self._states[role].on_swapped_to_fallback()

    def swap_to_primary(self, role: str) -> None:
        with self._lock:
            src = self._interpipe_srcs.get(role)
            if src is None:
                return
            src.set_property("listen-to", f"cam_{role}")
            self._states[role].on_swapped_to_primary()

    def get_consumer_element(self, role: str) -> Gst.Element | None:
        """Used by delta's eventual v4l2_camera backend to wrap alpha's pads."""
        return self._interpipe_srcs.get(role)

    def get_last_frame_age(self, role: str) -> float:
        """Monotonic seconds since the last frame on role. inf if never."""

    def stop(self) -> None:
        """Tear everything down."""
```

The manager holds the per-camera state machine (full spec in `camera-recovery-state-machine-design.md` for Phase 3; Phase 2 ships a stub that only tracks HEALTHY/OFFLINE transitions and drives the fixed-delay reconnect).

Hot-swap is a single GObject property write. Thread-safe by design (confirmed by GStreamer's MT-refcounting design doc and by RidgeRun's explicit statement on `listen-to` thread safety). No pipeline lock, no state change, no pad manipulation.

### StudioCompositor integration

`agents/studio_compositor/compositor.py` (modified, scoped to the camera branch section).

The camera branch section of `_build_pipeline` is rewritten. Edits are wrapped in section comments for clean merge coordination with delta's eventual PR #709 implementation:

```python
# --- ALPHA PHASE 2: CAMERA BRANCH CONSTRUCTION ---
# See docs/superpowers/specs/2026-04-12-compositor-hot-swap-architecture-design.md
# Cameras live in separate sub-pipelines managed by PipelineManager.
# The composite pipeline only contains interpipesrc consumers.
self._pipeline_manager = PipelineManager(
    specs=self._camera_specs,
    compositor=self,
)
self._pipeline_manager.build()

for cam in self._camera_specs:
    src = Gst.ElementFactory.make("interpipesrc", f"consumer_{cam.role}")
    src.set_property("listen-to", f"cam_{cam.role}")
    src.set_property("stream-sync", "restart-ts")
    src.set_property("allow-renegotiation", True)
    src.set_property("is-live", True)
    self._pipeline.add(src)
    self._pipeline_manager.register_consumer(cam.role, src)

    # Link to the existing compositor element. Same caps as before
    # (NV12 1920×1080 30fps) — the composite's compositor pads are unchanged.
    tile = layout.tile_for(cam.role)
    compositor_sink_pad = self._comp_element.get_request_pad("sink_%u")
    # ... existing compositor pad-property setup (xpos, ypos, width, height) ...
    src.get_static_pad("src").link(compositor_sink_pad)
# --- END ALPHA PHASE 2 ---
```

The Cairo source path, overlay zones, budget tracking, director loop, FX chain, tee, v4l2sink, and HLS sink are **all unchanged**. Alpha's refactor is scoped exclusively to the camera branch.

## Data flow

Per-frame, under normal operation for one camera:

1. USB bus delivers MJPEG frame to `v4l2src`. Frame sequence number set by kernel in `v4l2_buffer.sequence`.
2. `v4l2src` emits a `GstBuffer` with `offset = sequence` (GStreamer 1.28 semantics, verified via the `v4l2src` source in `gst-plugins-good`).
3. Watchdog element observes the buffer, resets its timer, passes through.
4. `jpegdec` decodes MJPEG to YUV420.
5. `videoconvert → videoscale → capsfilter` normalizes to NV12 1920×1080.
6. `interpipesink cam_<role>` receives the frame. Internally publishes to any `interpipesrc` currently listening with name `cam_<role>`.
7. Composite pipeline's `interpipesrc consumer_<role>` (if `listen-to=cam_<role>`) receives the frame into the composite's streaming thread.
8. `compositor` element places it in the correct slot of the 1920×1080 output.
9. Downstream: Cairo overlay → tee → v4l2sink + HLS sink + (Phase 5) RTMP sink.

When a camera is in fallback state:

1. `videotestsrc` in the fallback pipeline emits a bouncing ball at 30 fps.
2. `textoverlay` adds centered text.
3. `videoconvert + capsfilter` → NV12 1920×1080.
4. `interpipesink fb_<role>` publishes.
5. Composite pipeline's `interpipesrc consumer_<role>` (with `listen-to=fb_<role>`) receives the fallback frames.
6. Rest of the composite path is identical.

Latency (measured by adding a transient `identity signal-handoffs=true` between `videoconvert` and `interpipesink`): expected ≤ 20 ms glass-to-composite-entry. Hot-swap between primary and fallback is expected ≤ 1 frame (33 ms at 30 fps) because both producers are already in PLAYING.

## Error model

Error domains are strictly scoped by `GstPipeline` instance:

| Error source | Producer scope | Consumer effect |
|--------------|----------------|-----------------|
| `v4l2src` emits `GST_MESSAGE_ERROR` (EIO, EPROTO, device gone) | That camera's producer pipeline | None. Frame flow stops. |
| `watchdog` fires on that camera's producer | That camera's producer pipeline | None. Frame flow stops. |
| `jpegdec` fails on that producer | That camera's producer pipeline | None. Frame flow stops. |
| `interpipesink` itself errors | That camera's producer pipeline | None. Frame flow stops. |
| `interpipesrc` emits error in composite | Composite pipeline | **Bad case.** Would tear down composite. Mitigated by caps normalization and by `allow-renegotiation=TRUE` safety net. |
| `compositor` element or downstream error | Composite pipeline | Compositor process exits, systemd restarts. |

Producer errors are handled by `CameraPipeline._on_bus_message`, which:

1. Logs the error (role, domain, code, debug string).
2. Marks the producer unhealthy via its state machine.
3. Schedules `GLib.idle_add(lambda: pm.swap_to_fallback(role))` on the composite-pipeline main loop.
4. Schedules a reconnection attempt via the supervisor thread (Phase 3 exponential backoff; Phase 2 fixed 5 s).
5. Does **not** re-raise or propagate.

**Invariant:** no error from a camera producer pipeline ever reaches the composite pipeline's bus. This is structural (separate `GstPipeline` instances have separate buses) and is the entire reason for the refactor.

R2 (sub-2-s fault containment) is met: watchdog fires at t ≤ 2.0 s; `GLib.idle_add` dispatch is < 10 ms on the main loop; `set_property("listen-to", ...)` is sub-millisecond. Worst case ~2.01 s end-to-end.

## Threading model

- **GLib main loop thread (composite pipeline)** — handles composite bus messages, GLib idle callbacks, watchdog timers for the Type=notify heartbeat (Phase 1), Cairo overlay draw callback, director loop tick. All `interpipesrc.set_property("listen-to", ...)` calls are marshaled here via `GLib.idle_add`.
- **Per-camera GstPipeline streaming thread (×6)** — GStreamer spawns its own streaming thread per live source pipeline. Runs `v4l2src → watchdog → jpegdec → videoconvert → videoscale → interpipesink`. Always running while the camera is PLAYING.
- **Per-fallback GstPipeline streaming thread (×6)** — `videotestsrc → overlay → videoconvert → interpipesink`. Always running.
- **Composite pipeline streaming thread (×1+)** — consumes from `interpipesrc` elements, runs compositing. The `compositor`/`cudacompositor` element may spawn internal GPU threads.
- **Per-camera bus watch** — dispatches via the GLib main loop thread, not a separate thread.
- **Supervisor thread (alpha)** — spawned by `PipelineManager`, runs the reconnection backoff loop. Phase 2: fixed 5 s delay. Phase 3: exponential. Calls into GStreamer from this thread are safe at the element state-change level; `set_property` calls are marshaled through `GLib.idle_add` for strict correctness.

Reference: `CLAUDE.md § Studio Compositor` already documents that Cairo rendering is on background threads with synchronized blit on the streaming thread. The new threads added here integrate through the same GLib main loop model.

## Caps negotiation

All producers emit `video/x-raw, format=NV12, width=1920, height=1080, framerate=30/1`. Producers that can't natively produce these caps do internal conversion (`videoconvert + videoscale`). Consumers have `allow-renegotiation=TRUE` as a safety net but should never actually renegotiate in steady state.

Unit test: construct a `CameraPipeline` with `fakesrc` replacing `v4l2src` via dependency injection, emit 30 frames, assert the output at the `interpipesink` matches normalized caps exactly. Pure Python, no real cameras.

## Alternatives considered

### A. `fallbackswitch` from gst-plugins-rs (single-pipeline filter)

`gst-plugin-fallbackswitch` is in Arch `extra`, lower install friction than gst-interpipe from AUR. Single-element solution: `fallbackswitch` is a filter with priority-ranked sink pads where staleness on the active pad triggers automatic switch.

**Rejected because:** `fallbackswitch` lives inside a single pipeline and does not bound error scope. A `v4l2src` error in the primary branch still tears down the whole pipeline. This design requires error scoping first, hot-swap second; `fallbackswitch` provides only hot-swap.

**Retained as:** fallback path if `gst-plugin-interpipe` AUR build fails. The fallback-path design uses `fallbackswitch` + an `appsink → Python queue → appsrc` bridge per camera. Larger surface area, no AUR dep. Documented here; committed only if the AUR path fails at Phase 1 install.

### B. `input-selector` core element

Core GStreamer element for switching between input pads via `active-pad`.

**Rejected because:** (a) no automatic staleness detection — we'd need the watchdog elsewhere anyway; (b) lives in a single pipeline, no error scope; (c) switching requires caps match (no automatic renegotiation).

### C. Custom Python `appsink → appsrc` bridge (without fallbackswitch)

Build everything manually: each camera in a `GstPipeline` with `appsink`, Python thread pulls buffers and pushes them to a corresponding `appsrc` in the composite pipeline.

**Rejected because:** more Python code on every frame path, GIL contention at 180 calls/sec (6 cameras × 30 fps), no mature ecosystem pattern. Interpipe does exactly this in C with zero-copy pointer handoff.

**Retained as:** the fall-back-to-the-fallback if both interpipe and fallbackswitch paths fail. Would only happen if both AUR builds are broken AND the extra `gst-plugin-fallbackswitch` is unavailable — none expected.

### D. In-place rebuild of v4l2src element

What Phase 1's current reconnect logic (`try_reconnect_camera`) does: set element state to NULL, sleep 500 ms, set back to PLAYING. Works only if the device node still exists AND no error has propagated.

**Rejected because:** it's what we have today and it does not work for the observed failure modes.

## Integration with delta's PR #709

Delta's source-registry PR and alpha's hot-swap architecture are orthogonal at the file level and compatible at the architectural level.

### Shared concerns

Both architectures want:
1. Stable GStreamer endpoints that name a visual source.
2. A way to hot-swap which source feeds a given composite slot.
3. A way to observe source health at the source level.
4. A way to add and remove sources at runtime.

### Where they meet

- **Alpha's interpipesink producer pads** (`cam_<role>`, `fb_<role>`) are stable endpoints with globally-unique names. They are the cross-pipeline boundary by which "a camera's output" can be referenced from outside the camera's own pipeline. Delta's `SourceSchema` can reference a camera by these names.
- **Delta's appsrc producer pads** (one per source, fed from cairo/shm backends) are stable endpoints **inside the composite pipeline**. They are for pushing cairo/shm-originated frames INTO the composite pipeline.
- These are not duplicates. A camera does not need an appsrc because its frames arrive via `interpipesrc` from a separate pipeline. A cairo source does not need an interpipesink because its frames originate inside the compositor process and can be pushed directly to an appsrc.

### Delta's future `backend: "v4l2_camera"` wrapper

When delta's PR 1 implementation lands, adding cameras to the SourceRegistry requires a new backend. The `v4l2_camera` backend is a thin wrapper over alpha's `PipelineManager`:

```python
# Sketch for delta's PR 1 or PR 2 implementation
class V4l2CameraBackend(SourceBackend):
    """SourceRegistry backend that adapts a PipelineManager camera role."""

    def __init__(self, source_id: str, pipeline_manager: PipelineManager) -> None:
        self._source_id = source_id
        self._pm = pipeline_manager

    def get_current_surface(self) -> cairo.ImageSurface | None:
        # Cameras don't expose a cairo surface for PiP compositing —
        # their frames reach the composite via interpipesrc. Return None.
        return None

    def gst_appsrc(self) -> Gst.Element:
        # For "main layer routing," return the interpipesrc element itself.
        return self._pm.get_consumer_element(self._source_id)

    def frame_age_seconds(self) -> float:
        return self._pm.get_last_frame_age(self._source_id)
```

Phase 2 writes no code for this backend — it's delta's scope. But Phase 2's `PipelineManager` exposes the methods delta will need (`get_consumer_element`, `get_last_frame_age`).

### What Phase 2 does NOT do

- Does NOT create `layout_state.py`, `source_registry.py`, `shm_rgba_reader.py`, `command_server.py`, `cairo_sources/`.
- Does NOT touch `fx_chain.py`, `cairo_source.py`, `token_pole.py`, `album_overlay.py`, `sierpinski_renderer.py`, `shared/compositor_model.py`, `agents/effect_graph/**`.
- Does NOT touch `src-imagination/**`, `crates/hapax-visual/**`, or `hapax-imagination.service`.
- Does NOT migrate cameras into `~/.config/hapax-compositor/layouts/default.json`.
- Does NOT add runtime camera add/remove. Six cameras at build time.

### Migration path for delta's PR 1

1. Delta adds `"v4l2_camera"` to `SourceSchema.backend` literal in `shared/compositor_model.py`.
2. Delta writes `V4l2CameraBackend` wrapping alpha's `PipelineManager`.
3. Delta's `SourceRegistry.from_layout()` instantiates `V4l2CameraBackend` for each camera-kind source.
4. `default.json` adds six camera sources: `{id: "brio_operator", kind: "camera", backend: "v4l2_camera", params: {role: "brio_operator"}}` etc.
5. No edits required to alpha's files beyond possibly exporting `PipelineManager` from `agents/studio_compositor/__init__.py`.

**Expected merge conflict surface: zero beyond `compositor.py` section boundary.** Alpha's files are untouched by delta's PR 1; delta's files are untouched by alpha's Phase 2. The shared `compositor.py` edit is scoped via section comments.

## Migration plan

1. Install `gst-plugin-interpipe` from AUR (Phase 1 of the epic). Verify with `gst-inspect-1.0 interpipesrc`.
2. Create the three new files (`camera_pipeline.py`, `fallback_pipeline.py`, `pipeline_manager.py`) with unit test scaffolding.
3. Write unit tests first (TDD): fake `v4l2src` with `fakesrc`, verify producer pipeline builds and reaches PLAYING, verify `CameraPipeline.stop()` idempotent, verify `PipelineManager.swap_to_fallback` + `swap_to_primary` round-trip.
4. Modify `agents/studio_compositor/compositor.py`: scope the edit to the camera branch construction section, wrap in `# --- ALPHA PHASE 2 ---` / `# --- END ALPHA PHASE 2 ---`.
5. Modify `agents/studio_compositor/cameras.py::add_camera_branch` to delegate to `PipelineManager`. Remove the old code path entirely — no feature flag.
6. Modify `agents/studio_compositor/state.py::try_reconnect_camera` to be a stub that calls `PipelineManager.reconnect(role)`. Full state machine in Phase 3.
7. Run existing compositor test suite — all must pass unchanged.
8. Hardware smoke test: boot compositor, verify all six cameras reach composite, pull a USB cable, verify fallback appears within 2 s, plug back in, verify restoration within 10 s, verify the other five cameras unaffected throughout.
9. Open Phase 2 PR.

## Test strategy

Unit tests (pure Python, no real cameras, run in CI):

- `test_camera_pipeline_builds_with_fakesrc` — build + start + stop round-trip.
- `test_camera_pipeline_error_handling` — inject a fake error, verify the supervisor is notified and does not crash.
- `test_fallback_pipeline_always_runs` — FallbackPipeline reaches PLAYING.
- `test_pipeline_manager_swap_roundtrip` — register fake consumer, swap to fallback, swap to primary, verify `listen-to` property changes both times.
- `test_pipeline_manager_build_idempotent` — double-build is safe.
- `test_interpipesink_caps_normalization` — CameraPipeline + FallbackPipeline produce matching caps exactly.
- `test_watchdog_timeout_configurable` — watchdog property reads back 2000 after set.
- `test_swap_to_fallback_under_load` — swap 100 times in a tight loop, verify no state drift.

Integration tests (gated behind `@pytest.mark.camera`, manual):

- `test_real_camera_build` — build a CameraPipeline for each real BRIO/C920 role.
- `test_compositor_boots_with_cameras` — full StudioCompositor + PipelineManager, golden-image check.
- `test_hot_swap_on_real_unplug` — operator unplugs a camera during the test; assertion script checks fallback within 2 s.
- `test_hot_swap_on_simulated_unplug` — uses `scripts/studio-simulate-usb-disconnect.sh` (USBDEVFS_RESET) in a subprocess, same assertion.

Smoke test (Phase 6): `scripts/studio-smoke-test.sh` runs the integration tests end-to-end and exits non-zero on failure.

## Acceptance criteria

- CameraPipeline + FallbackPipeline + PipelineManager shipped with unit tests passing.
- Studio compositor boots with all six cameras visible after the refactor.
- Unplugging any one camera swaps its slot to the bouncing-ball fallback within 2 s.
- Replugging the camera restores live frames within 10 s.
- No visible disruption to the other five cameras, the Cairo overlays, the director loop, or the audio path during an unplug/replug cycle.
- `watchdog_<role>` bus errors are captured and logged per role; the composite pipeline does not terminate.
- Existing `tests/studio_compositor/` suite passes unchanged.
- Section-comment markers in `compositor.py` are intact.

## Risks

1. **AUR build of `gst-plugin-interpipe` fails on CachyOS with GStreamer 1.28.2.** Mitigation: fallback path (§ Alternatives A). Decided at Phase 1 install time.
2. **interpipe caps renegotiation misbehaves under a producer transition.** Mitigation: caps normalization. Unit test covers it.
3. **Supervisor thread racing GLib main loop.** Mitigation: all supervisor-to-GStreamer property writes go through `GLib.idle_add`.
4. **Hot-swap on a real unplug delivers one glitchy frame.** Partial mitigation: `stream-sync=restart-ts`. Full mitigation: accept one frame of glitch — the failsafe is for continuity, not broadcast-quality seamlessness.
5. **VRAM growth from 13 total pipelines.** Mitigation: only the composite pipeline touches CUDA. Producer pipelines are CPU-only. Net VRAM roughly unchanged.
6. **Merge conflict with delta's PR #709 on `compositor.py`.** Mitigation: section comments. Alpha ships first; delta rebases.

## Open questions

1. **`stream-sync` tuning.** Default `passthrough-ts`; design specifies `restart-ts` for timestamp regeneration on hot-swap. Confirm the `compositor`/`cudacompositor` element tolerates regenerated timestamps without glitching.
2. **Consumer-side vs producer-side `stream-sync`.** Design sets it on the consumer (`interpipesrc`). Verify this is correct for the multi-producer-one-consumer case.
3. **Namespace collisions.** `cam_<role>` and `fb_<role>` are globally unique among studio_compositor but live in the process-wide interpipe namespace. Document the reservation. Low risk.

## References

### Internal

- `docs/superpowers/plans/2026-04-12-camera-247-resilience-epic.md`
- `docs/superpowers/specs/2026-04-12-camera-247-resilience-research.md`
- `docs/research/2026-04-12-brio-usb-robustness.md`
- `agents/studio_compositor/cameras.py:86` — current `add_camera_branch`
- `agents/studio_compositor/state.py:73` — current `try_reconnect_camera`
- `agents/studio_compositor/compositor.py` — `StudioCompositor` shell
- `agents/studio_compositor/config.py:34` — camera specs
- `~/.cache/hapax/relay/inflections/20260412-221500-alpha-delta-composition.md` — composition analysis with delta's spec
- Delta's spec on `origin/feat/compositor-source-registry-foundation:docs/superpowers/specs/2026-04-12-compositor-source-registry-foundation-design.md`

### External

- [gst-interpipe upstream (RidgeRun)](https://github.com/RidgeRun/gst-interpipe)
- [GstInterpipe dynamic switching](https://developer.ridgerun.com/wiki/index.php/GstInterpipe_-_Dynamic_Switching)
- [gst-interpipe build and install guide](https://developer.ridgerun.com/wiki/index.php?title=GstInterpipe_-_Building_and_Installation_Guide)
- [GStreamer MT-refcounting design](https://gstreamer.freedesktop.org/documentation/additional/design/MT-refcounting.html)
- [gst-plugins-bad watchdog source](https://github.com/GStreamer/gst-plugins-bad/blob/master/gst/debugutils/gstwatchdog.c)
- [Arch gst-plugin-fallbackswitch](https://archlinux.org/packages/extra/x86_64/gst-plugin-fallbackswitch/) — fallback path
- [slomo fallback stream handling](https://coaxion.net/blog/2020/07/automatic-retry-on-error-and-fallback-stream-handling-for-gstreamer-sources/) — fallback-path background
