# Camera 24/7 Resilience — Epic Plan

**Filed:** 2026-04-12
**Status:** Active implementation plan. All phases to ship in a single session.
**Owner:** alpha
**Research backing:** `docs/superpowers/specs/2026-04-12-camera-247-resilience-research.md`
**Design docs:**
- `docs/superpowers/specs/2026-04-12-compositor-hot-swap-architecture-design.md` (Phase 2)
- `docs/superpowers/specs/2026-04-12-camera-recovery-state-machine-design.md` (Phase 3)
- `docs/superpowers/specs/2026-04-12-v4l2-prometheus-exporter-design.md` (Phase 4)
- `docs/superpowers/specs/2026-04-12-native-rtmp-delivery-design.md` (Phase 5)

## Goal

Make the six USB studio cameras (3 BRIO + 3 C920) feed a 24/7 livestream that stays live through any single-camera fault, any cascade on a shared USB hub, any GStreamer element error, and any encoder fault, with sub-30 s mean time to recovery for transient faults and sub-5 min for hard faults. Eliminate OBS as a broadcast SPOF. Expose per-camera health as Prometheus metrics. Ship every change tonight.

## Non-goals

- Root-cause repair of the TS4 USB3.2 Gen2 hub chain. That is documented as hardware-investigation-first in `docs/research/2026-04-12-brio-usb-robustness.md`; this plan assumes the hardware stays marginal and builds software that contains the damage.
- Pi NoIR substitution for any livestream slot. Deferred.
- Moving systemd units off alpha's worktree (architectural follow-up from the FU-6 retirement). Deferred.
- Multi-destination / backup ingest streams. Single YouTube RTMP endpoint.
- Any change to the Cairo overlay rendering, director loop, or FX chain — they ride on top of the new pipeline unchanged.

## Operating assumptions

- GStreamer 1.28.2 on CachyOS (verified by `gst-inspect-1.0 --version`).
- NVENC path: `nvh264enc` (CUDA Mode) is the present-day encoder factory. `nvcudah264enc` is not available in this build; verified by `gst-inspect-1.0 nvcudah264enc` returning "No such element or plugin". The design doc for Phase 5 uses `nvh264enc` as the primary element.
- `watchdog` element is available in `gst-plugins-bad` 1.28.2 and already installed. Verified by `gst-inspect-1.0 watchdog`.
- `rtmp2sink` and `flvmux` are available (`libgstrtmp2.so` present in `/usr/lib/gstreamer-1.0/`).
- `gst-plugin-interpipe` is not currently installed. Available via AUR. Phase 1 installs it from source or via the AUR package.
- `python-prometheus_client` is not currently installed; available in `extra`.
- `python-sdnotify` is not currently installed; pure-Python fallback via pip / uv.
- `python-pyudev 0.24.4` is already installed.
- MediaMTX is not installed; AUR package `mediamtx-bin` is the canonical install.

## Phase map

| Phase | Scope | Design doc | PR count | Blocking |
|-------|-------|------------|----------|----------|
| 1 | Dependencies + quick wins (watchdog elements, autosuspend, ntfy, systemd tweaks, sd_notify) | none — small-diff changes | 1 | — |
| 2 | Hot-swap architecture (gst-interpipe refactor, per-camera sub-pipelines, fallback producers) | `2026-04-12-compositor-hot-swap-architecture-design.md` | 1 | Phase 1 |
| 3 | Recovery state machine + udev / pyudev integration | `2026-04-12-camera-recovery-state-machine-design.md` | 1 | Phase 2 |
| 4 | Observability — v4l2 frame counters, Prometheus exporter, Grafana dashboard | `2026-04-12-v4l2-prometheus-exporter-design.md` | 1 | Phase 2 |
| 5 | Native GStreamer RTMP + MediaMTX local relay (epic A7) | `2026-04-12-native-rtmp-delivery-design.md` | 1 | Phase 2 |
| 6 | Test harness (USBDEVFS_RESET sim, unit + integration tests, CLAUDE.md + systemd/README updates) | none | 1 | Phase 3 |

Six PRs total. Phase 2 is the architectural spine; Phases 3–5 depend on it but are independent of each other and could in principle ship in parallel. Tonight, sequence Phase 2 → 3 → 4 → 5 → 6 serially so each builds on a verified predecessor.

## Dependency install manifest

Run before Phase 1 begins. All commands executable from alpha's worktree.

```bash
# From official Arch repos — pacman
sudo pacman -S --needed \
    python-prometheus_client \
    gst-plugin-fallbackswitch       # Kept as fallback path in case interpipe AUR build fails

# From AUR — paru (or makepkg directly)
paru -S gst-plugin-interpipe mediamtx-bin

# Python package via uv (sdnotify is pure-python, no native extension)
cd ~/projects/hapax-council
uv add sdnotify

# Verify
gst-inspect-1.0 interpipesrc        # Must succeed
gst-inspect-1.0 fallbackswitch      # Must succeed
gst-inspect-1.0 watchdog            # Already works
gst-inspect-1.0 nvh264enc           # Already works
gst-inspect-1.0 rtmp2sink           # Already works
mediamtx --version                  # Must succeed
python3 -c "import prometheus_client, sdnotify, pyudev; print('OK')"
```

If `gst-plugin-interpipe` AUR build fails, Phase 2 has a documented fallback in its design doc (§ Alternatives) that uses `fallbackswitch` plus an `appsink → appsrc` Python bridge. Architecture is equivalent; implementation is larger.

## Phase 1 — Dependencies + quick wins

**Scope:** all low-risk, small-diff changes that make the system more resilient without architectural change.

### 1.1 Install dependencies

Execute the manifest above. Verify each `gst-inspect-1.0` succeeds. Log output to `/tmp/camera-epic-phase1-install.log` for the PR body.

### 1.2 Watchdog element per camera branch

Modify `agents/studio_compositor/cameras.py::add_camera_branch` to insert a `watchdog` element immediately after `capsfilter`, before `jpegdec`. Name it deterministically: `watchdog_{role}`. Timeout 2000 ms.

```python
watchdog = Gst.ElementFactory.make("watchdog", f"watchdog_{role}")
watchdog.set_property("timeout", 2000)  # ms — NOT nanoseconds
```

The watchdog fires `GST_MESSAGE_ERROR` with domain `GST_STREAM_ERROR` and code `GST_STREAM_ERROR_FAILED`. This will tear down the entire pipeline by default. That is the present-day behavior of Phase 1 — the architectural fix for error containment is Phase 2.

In Phase 1, add a bus-message handler in `agents/studio_compositor/compositor.py::_on_bus_message` that intercepts the error, extracts the source element name, sets the per-camera status to "offline", schedules a reconnect via the existing `try_reconnect_camera` path, and **returns True to stop propagation**. Without the return-true guard, the pipeline dies. The interception is brittle — it's the Phase 1 bridge until Phase 2 gives us real error scoping.

### 1.3 USB autosuspend udev rule

Create `systemd/udev/70-studio-cameras.rules` (new directory, repo-tracked):

```udev
# Disable USB autosuspend for studio cameras. USB autosuspend is a known
# contributor to webcam disappearance in 24/7 deployments. BRIO + C920 are not
# power-budget-constrained devices; nothing to gain from suspend.
ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="046d", ATTR{idProduct}=="085e", ATTR{power/control}="on"
ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="046d", ATTR{idProduct}=="08e5", ATTR{power/control}="on"
```

Install script `scripts/studio-install-udev-rules.sh` that copies to `/etc/udev/rules.d/70-studio-cameras.rules` and runs `udevadm control --reload-rules && udevadm trigger`. The `studio-compositor.service` gets a new `ExecStartPre=` pointing at this script (idempotent; no-op if file is already current).

### 1.4 ntfy on every state transition

Add to `agents/studio_compositor/state.py` a notifier function that fires on every `_camera_status[role]` transition. Throttled per (role, new_state) pair via a small state file at `/dev/shm/hapax-compositor/last-ntfy-{role}.txt` — same pattern as FU-6b's `$STATE_DIR/last-notified-${KEY}-sha`. Notification body: "Camera {role} is now {state} ({elapsed_seconds}s since last transition)". Priority `high` for offline, `default` for online.

### 1.5 Raise systemd restart limits

`systemd/units/studio-compositor.service`:

```ini
StartLimitBurst=20
StartLimitIntervalSec=3600
```

(was `5/300`). The 5/300 value was empirically exhausted in under three minutes once reconnect loops went rampant. Twenty restarts per hour is a budget for genuine infrastructure churn while still stopping a runaway loop.

### 1.6 Type=notify + WatchdogSec

Update `studio-compositor.service` to `Type=notify`, `NotifyAccess=main`, `WatchdogSec=60s`. Add a module-level systemd notifier in `agents/studio_compositor/__main__.py`:

```python
import sdnotify
_sd = sdnotify.SystemdNotifier()

def send_ready():
    _sd.notify("READY=1")

def send_watchdog():
    _sd.notify("WATCHDOG=1")

def send_status(msg: str):
    _sd.notify(f"STATUS={msg}")
```

Wire `send_ready()` once the pipeline reaches PLAYING state. Wire a `GLib.timeout_add_seconds(20, ...)` callback that sends `WATCHDOG=1` if at least one camera has posted a frame in the last 20 seconds — this is **liveness = frames are flowing**, not "process is running". If no camera has frames, systemd SIGABRTs the service, which triggers Restart=on-failure.

Threshold: "at least one camera has frames in the last 20 s" is intentionally lax. The system is failsafe at the slot level (Phase 2); the systemd watchdog is a last-resort sanity check that the whole compositor hasn't wedged.

### 1.7 Residual silent-failure sweep (bundled in this PR)

The research brief flagged four residual silent-failure sites in the compositor. Fix them here while we're in the file:

- `agents/studio_compositor/director_loop.py:121-122` — LLM key retrieval bare-except → log `exc_info=True`.
- `agents/studio_compositor/director_loop.py:134-135` — album info read bare-except → log warning.
- `agents/studio_compositor/director_loop.py:146-147` — snapshot b64 bare-except → log warning.
- `agents/studio_compositor/compositor.py:126-127` — FX source switch bare-except → `log.exception`.
- `systemd/units/studio-camera-setup.sh:51,59` — `2>/dev/null || true` → redirect to `$STATE_DIR/v4l2-ctl.log` and log warning on nonzero return.

### 1.8 Smoke test

```bash
# Terminal 1
journalctl --user -fu studio-compositor.service

# Terminal 2
sudo systemctl --user restart studio-compositor.service
sleep 5
systemctl --user status studio-compositor.service
# Expect: active, Type=notify, status "6 cameras live"

# Terminal 3 — simulate a camera going silent
# This requires root. Operator executes:
sudo modprobe -r uvcvideo && sleep 3 && sudo modprobe uvcvideo
# Expect: watchdog fires in journalctl for all 6 cameras, ntfy notifications arrive,
# cameras reconnect within ~30 s after modprobe reloads uvcvideo.
```

### 1.9 Rollback

Revert the PR. The udev rule install is idempotent but not auto-removed — document in PR body that rollback includes `sudo rm /etc/udev/rules.d/70-studio-cameras.rules && sudo udevadm control --reload-rules`.

### 1.10 Gate criteria

- `systemctl --user status studio-compositor.service` shows `Active: active (running)` with status `6 cameras live` (or n/6 if some are offline pre-test).
- `journalctl --user -u studio-compositor.service` shows at least one `watchdog fired for role=...` event in response to the smoke-test disconnect.
- `ntfy` notification received on disconnect and on reconnect.
- No `StartLimitBurst` exhaustion in a 1-hour soak test.

## Phase 2 — Hot-swap architecture

Full design in `docs/superpowers/specs/2026-04-12-compositor-hot-swap-architecture-design.md`. Summary:

- Each camera runs in its own `GstPipeline` (not a `GstBin` — a full separate Pipeline) with terminal `interpipesink name=cam_{role}`.
- Each camera has a paired fallback pipeline: `videotestsrc pattern=ball is-live=true ! textoverlay text="CAMERA {role} OFFLINE" ! ... ! interpipesink name=fb_{role}`.
- The composite pipeline contains six `interpipesrc listen-to=cam_{role}` elements feeding `compositor`. Switching to fallback is a single `set_property("listen-to", "fb_{role}")` call.
- A `CameraPipelineManager` owns all six camera + six fallback + one composite pipelines. Error messages from camera sub-pipelines are bounded to that pipeline and routed to the supervisor thread, which tears down and rebuilds the affected camera pipeline without disturbing anyone else.

**Files created:**
- `agents/studio_compositor/camera_pipeline.py` — single camera producer pipeline
- `agents/studio_compositor/fallback_pipeline.py` — single slot fallback producer
- `agents/studio_compositor/pipeline_manager.py` — orchestration across sub-pipelines
- `tests/studio_compositor/test_camera_pipeline.py` — new unit tests

**Files modified:**
- `agents/studio_compositor/cameras.py` — `add_camera_branch` becomes a thin adapter over `CameraPipelineManager`
- `agents/studio_compositor/compositor.py` — pipeline construction now delegates camera ingestion
- `agents/studio_compositor/state.py` — `try_reconnect_camera` replaced by the state machine delivered in Phase 3 (stub here)

**Gate:** compositor starts cleanly, all six cameras appear in the composite, manually killing one camera (e.g., `sudo sh -c 'echo 0 > /sys/bus/usb/devices/1-9/authorized'`) swaps that slot to its fallback within 2 s, re-authorizing restores within 10 s. No service restart. No loss of audio, overlays, or other cameras.

## Phase 3 — Recovery state machine + udev integration

Full design in `docs/superpowers/specs/2026-04-12-camera-recovery-state-machine-design.md`. Summary:

- `CameraStateMachine` class, one instance per camera, with states `HEALTHY`, `DEGRADED`, `OFFLINE`, `RECOVERING`, `DEAD`.
- Transitions driven by: watchdog-element bus errors, frame-flow timeout observations, pyudev device-remove/add events, manual operator commands.
- Exponential backoff on reconnection: 1 s, 2 s, 4 s, 8 s, 16 s, 32 s, 60 s (ceiling), with `DEAD` after 10 consecutive failures, requiring operator intervention to exit.
- `pyudev.glib.MonitorObserver` subscribes to `video4linux` subsystem events and routes them into the state machine via a GLib signal.
- Udev rule `70-studio-cameras.rules` extended to include `TAG+="systemd"` for systemd-device-unit integration and to re-run `v4l2-ctl` configuration via `RUN+=` on `add`.

**Files created:**
- `agents/studio_compositor/camera_state_machine.py` — state machine
- `agents/studio_compositor/udev_monitor.py` — pyudev wrapper
- `tests/studio_compositor/test_camera_state_machine.py` — state-machine unit tests (pure Python, no GStreamer)

**Files modified:**
- `systemd/udev/70-studio-cameras.rules` — add `TAG+="systemd"`, `RUN+=...`, add `remove` handling
- `agents/studio_compositor/pipeline_manager.py` (from Phase 2) — wire state machines in
- `scripts/studio-install-udev-rules.sh` — also installs a systemd-per-role template unit `studio-camera-reconfigure@.service` that runs v4l2-ctl for one specific device node

**Gate:** physically unplug a camera (or use `echo 0 > /sys/bus/usb/devices/X/authorized`), wait, re-plug (or `echo 1`). State machine transitions `HEALTHY → OFFLINE → RECOVERING → HEALTHY` visible in journalctl with the right backoff timings. No manual compositor restart required. `v4l2-ctl` runs automatically on re-plug (confirm by checking that focus / exposure are re-applied).

## Phase 4 — Observability stack

Full design in `docs/superpowers/specs/2026-04-12-v4l2-prometheus-exporter-design.md`. Summary:

- Metrics exposed from inside the compositor process via `prometheus_client.start_http_server(9482, addr="0.0.0.0")`.
- Frame counters sourced from `GstBuffer.offset` (which equals `v4l2_buffer.sequence` for v4l2src sources per GStreamer 1.28 semantics), tapped via a pad probe on each camera sub-pipeline's `interpipesink` sink pad.
- Metric set: `studio_camera_frames_total`, `studio_camera_kernel_drops_total`, `studio_camera_last_frame_age_seconds`, `studio_camera_state`, `studio_camera_reconnect_attempts_total`, `studio_camera_transitions_total`, `studio_compositor_pipeline_restarts_total`, `studio_rtmp_bytes_total`, `studio_rtmp_connected`.
- Docker Prometheus container scrapes `host.docker.internal:9482` via `extra_hosts: [host.docker.internal:host-gateway]`.
- Grafana dashboard at `grafana/dashboards/studio-cameras.json` with six Stat panels (one per camera), a USB error time series, and a reconnect histogram.

**Files created:**
- `agents/studio_compositor/metrics.py` — prometheus_client initialization and per-camera counter registration
- `grafana/dashboards/studio-cameras.json` — committed dashboard JSON
- `tests/studio_compositor/test_metrics.py` — unit tests for metric update logic

**Files modified:**
- `agents/studio_compositor/pipeline_manager.py` — pad probe wiring
- `agents/studio_compositor/camera_state_machine.py` — emits state-transition signals for the state metric
- Existing docker-compose entry for Prometheus — add the studio scrape job
- `agents/studio_compositor/__main__.py` — call `start_http_server` on boot

**Gate:** `curl http://127.0.0.1:9482/metrics` returns valid Prometheus exposition format with non-zero `studio_camera_frames_total{role=...}` for active cameras. Grafana dashboard imports cleanly and shows live values for all six cameras.

## Phase 5 — Native RTMP + MediaMTX relay

Full design in `docs/superpowers/specs/2026-04-12-native-rtmp-delivery-design.md`. Summary:

- New output bin attached to the composite pipeline's `tee`: `queue → videoconvert → cudaupload → cudaconvert → nvh264enc → h264parse → flvmux → rtmp2sink`.
- MediaMTX runs as a user-scope systemd unit, accepts RTMP on `127.0.0.1:1935/studio`, pushes to YouTube via ffmpeg `runOnReady`.
- YouTube stream key retrieved from `pass show streaming/youtube-stream-key` at MediaMTX launch time.
- `studio.toggle_livestream` affordance handler in the compositor drives the RTMP bin: add on toggle-on, remove on toggle-off.
- Audio: source from PipeWire via `pipewiresrc target-object="hapax-broadcast-sink"`, encoded via `voaacenc bitrate=128000`, muxed into `flvmux`.
- Encoder errors on the RTMP bin are bounded (the bin is a GstBin with its own error handler); on fire, the bin is removed, rebuilt, and re-attached within 5 s without restarting the composite pipeline.

**Files created:**
- `agents/studio_compositor/rtmp_output.py` — RTMP bin builder + error handler
- `systemd/units/mediamtx.service` — MediaMTX user unit
- `config/mediamtx.yml` — MediaMTX configuration with `runOnReady` ffmpeg relay to YouTube
- `scripts/mediamtx-start.sh` — wrapper that loads the stream key from `pass` and templates `mediamtx.yml`
- `tests/studio_compositor/test_rtmp_output.py` — unit tests

**Files modified:**
- `agents/studio_compositor/compositor.py` — adds the RTMP branch to the `tee`
- `agents/studio_compositor/pipeline_manager.py` — manages the RTMP bin lifecycle
- `config/affordances/studio_toggle_livestream.yaml` — handler class pointer
- `docs/superpowers/handoff/` entries — no (this is a PR change, not a session handoff)

**Gate:** `systemctl --user start mediamtx.service` starts cleanly, `curl http://127.0.0.1:9998/metrics` returns MediaMTX Prometheus metrics, compositor can be told to start the RTMP bin via an affordance trigger, `ffprobe rtmp://127.0.0.1:1935/studio` sees frames, and (with a disposable test YouTube stream key) the stream appears in YouTube Studio's "Go Live" preview within 30 s. Live smoke test against real YouTube optional — the design doc covers the exact manual sequence.

## Phase 6 — Test harness + documentation

**Scope:**

- `scripts/studio-simulate-usb-disconnect.sh` — helper using `USBDEVFS_RESET` via Python `fcntl.ioctl` to reset a named camera. Runs without root if the operator is in the `plugdev` group (which is the case on CachyOS).
- `scripts/studio-smoke-test.sh` — end-to-end test: start compositor, wait for `READY=1`, curl metrics, simulate disconnect, verify fallback swap, simulate reconnect, verify recovery. Exits non-zero on any gate failure.
- Unit tests for state machine (pure Python, fast), integration tests for camera pipeline (GStreamer, skip on CI without cameras via `@pytest.mark.camera`).
- `CLAUDE.md § Studio Compositor` — rewrite to describe the new architecture: interpipe sub-pipelines, state machine, fallback producers, RTMP branch, metrics exporter, MediaMTX relay.
- `systemd/README.md` — add the new services and dependencies.
- `docs/research/2026-04-12-brio-usb-robustness.md` — append a cross-reference to this epic.

**Files created:**
- `scripts/studio-simulate-usb-disconnect.sh`
- `scripts/studio-smoke-test.sh`
- `tests/studio_compositor/test_camera_pipeline_integration.py`

**Files modified:**
- `CLAUDE.md` (hapax-council)
- `systemd/README.md`
- `docs/research/2026-04-12-brio-usb-robustness.md` (append section)

**Gate:** `scripts/studio-smoke-test.sh` exits 0. CI passes (unit tests only; integration tests gated behind `@pytest.mark.camera`).

## Cross-phase concerns

### Thread model

GStreamer streaming threads (one per branch) must never block on Python-level locks. The pipeline manager, state machine, and metrics code all run on either the GLib main loop thread or a dedicated supervisor thread. The watchdog bus handler runs on the GLib main loop thread (standard `add_signal_watch` pattern). Pad probes execute on streaming threads — they must only call thread-safe operations (`prometheus_client` counters are thread-safe internally). The state machine's `on_bus_error` is called from the GLib main loop thread; external triggers (pyudev signal, operator command) are marshaled to the main loop via `GLib.idle_add`.

Reference: [GStreamer MT-refcounting](https://gstreamer.freedesktop.org/documentation/additional/design/MT-refcounting.html).

### GPU budget

Six v4l2src + six jpegdec + one compositor (CUDA) is the current baseline. Phase 2 multiplies the `GstPipeline` instance count by 12 (6 cameras + 6 fallbacks) plus 1 composite, but the number of active CUDA kernels stays roughly constant — each fallback pipeline is CPU-only (`videotestsrc` is CPU). The composite pipeline is where CUDA happens. Phase 5 adds `nvh264enc` which is a new NVENC session — consumer NVIDIA GPUs cap at 5–8 NVENC sessions; we are using 1. Acceptable.

VRAM: the current compositor uses ~1.5 GB VRAM for CUDA compositing + textures (measured from prior sessions' telemetry). `nvh264enc` adds ~200–400 MB for encoder state. Reverie uses ~3 GB. TabbyAPI Qwen 9B EXL3 uses ~10 GB. Total projected: ~15–16 GB of 24 GB. Acceptable, but add a VRAM check to the smoke test.

### Error containment boundaries

- **Camera sub-pipeline errors:** contained to that pipeline. The supervisor thread watches each camera pipeline's bus on its own dedicated signal watch.
- **Composite pipeline errors:** propagate to the compositor process. If the composite pipeline dies, the service dies and systemd restarts it. The design intent is that composite pipeline errors should be rare and always bug-worthy.
- **RTMP bin errors:** contained to the RTMP bin. On fire, the bin is removed from the composite and rebuilt. The composite pipeline keeps running, streaming HLS and V4L2 loopback output unaffected.
- **MediaMTX errors:** contained to the MediaMTX process. Systemd restarts it. The compositor's RTMP sink disconnects cleanly and reconnects on MediaMTX return.

### Consent

The `studio.toggle_livestream` affordance is already consent-gated (`CLAUDE.md § Stream-as-affordance`). The consent contract check runs in `AffordancePipeline._consent_allows` before the affordance is recruited. Phase 5's RTMP output respects this — the RTMP bin is only added to the pipeline when the affordance handler is invoked by the recruitment pipeline, which only happens inside a valid consent window.

The consent gate is the only interface between cognition and broadcast. The compositor never adds the RTMP bin autonomously.

### Backwards compatibility

- OBS remains available as a parallel output path via the existing v4l2 loopback (`/dev/video42`). It is no longer the only RTMP encoder but nothing actively breaks it.
- HLS output to `/dev/shm/hapax-compositor/hls/` is preserved.
- `studio.toggle_livestream` affordance shape unchanged — only the handler changes.
- `scripts/chat-monitor.py` preset-reactor hook unaffected.
- Director loop unaffected.
- Reverie unaffected (separate render path).

### Rollback

Each phase's PR is independently revertable. Dependency installations (pacman and AUR) are not reverted automatically; the PR body documents the manual uninstall commands if needed. Config files (`mediamtx.yml`, udev rule) are removed as part of the revert script.

## Execution order tonight

1. **Prep:** install all dependencies (Phase 1 § 1.1). Verify every element and module imports. Commit nothing yet — this is environment setup.
2. **Phase 1 PR.** Small-diff changes to watchdog wiring, udev rule, ntfy, systemd unit, sd_notify, residual silent-failure sweep. Ship, monitor CI, merge.
3. **Phase 2 PR.** Write the hot-swap architecture design doc. Implement. Smoke test manually on hardware. Ship, monitor CI, merge.
4. **Phase 3 PR.** Write the recovery state machine design doc. Implement. Manually test unplug/replug. Ship, monitor CI, merge.
5. **Phase 4 PR.** Write the Prometheus exporter design doc. Implement. Curl metrics endpoint. Ship, monitor CI, merge.
6. **Phase 5 PR.** Write the native RTMP design doc. Implement. Smoke test with disposable YouTube stream key. Ship, monitor CI, merge.
7. **Phase 6 PR.** Scripts, tests, docs. Ship, merge.
8. **Session handoff.** Document what shipped, what didn't, any surprises.

Each phase's PR must be fully green (CI passing, smoke test passing) before the next phase starts. The relay protocol hook already enforces this ("work-resolution-gate" blocks edits when open PRs exist).

Estimated time per phase (realistic, not optimistic):
- Phase 1: 60–90 min
- Phase 2: 120–180 min (biggest risk)
- Phase 3: 90 min
- Phase 4: 90 min
- Phase 5: 120 min
- Phase 6: 60 min

Total: roughly 9–12 hours of focused work. If any phase slips significantly, operator steering requested on whether to keep going or stop at the current boundary.

## References

### Internal
- `docs/superpowers/specs/2026-04-12-camera-247-resilience-research.md` — research brief
- `docs/research/2026-04-12-brio-usb-robustness.md` — hardware root cause
- `docs/superpowers/handoff/2026-04-12-alpha-fu6-handoff.md` — prior session retirement
- `CLAUDE.md § Studio Compositor` — current architecture
- `CLAUDE.md § Stream-as-affordance` — consent-gated livestream affordance

### External (new this session)
- [gst-interpipe Dynamic Switching](https://developer.ridgerun.com/wiki/index.php/GstInterpipe_-_Dynamic_Switching)
- [GStreamer MT-refcounting](https://gstreamer.freedesktop.org/documentation/additional/design/MT-refcounting.html)
- [GstBuffer documentation](https://gstreamer.freedesktop.org/documentation/gstreamer/gstbuffer.html)
- [GStreamer fallbackswitch](https://gstreamer.freedesktop.org/documentation/fallbackswitch/fallbackswitch.html)
- [GStreamer watchdog source](https://github.com/GStreamer/gst-plugins-bad/blob/master/gst/debugutils/gstwatchdog.c)
- [sd_notify(3)](https://www.freedesktop.org/software/systemd/man/latest/sd_notify.html)
- [python-cysystemd on Arch](https://archlinux.org/packages/extra/x86_64/python-cysystemd/)
- [bb4242/sdnotify on GitHub](https://github.com/bb4242/sdnotify)
- [pyudev.glib API docs](https://pyudev.readthedocs.io/en/latest/api/pyudev.glib.html)
- [MediaMTX metrics docs](https://mediamtx.org/docs/usage/metrics)
- [MediaMTX restream-to-YouTube discussion](https://github.com/bluenviron/mediamtx/discussions/2709)
- [prometheus/client_python on GitHub](https://github.com/prometheus/client_python)
- [V4L2 dropped-frame detection gist](https://gist.github.com/SebastianMartens/7d63f8300a0bcf0c7072a674b3ea4817)
- [YouTube Live Ingestion Protocol Comparison](https://developers.google.com/youtube/v3/live/guides/ingestion-protocol-comparison)
- [YouTube encoder settings](https://support.google.com/youtube/answer/2853702)
