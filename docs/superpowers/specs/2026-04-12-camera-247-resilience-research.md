# Camera 24/7 Resilience — Research Brief

**Filed:** 2026-04-12
**Status:** Research, not a decided plan. Operator steering required before any implementation.
**Scope:** The 6 USB cameras (3 Logitech BRIO 4K + 3 Logitech C920) and 3 Pi NoIR edges that feed the studio livestream. The objective is resilient, robust, failsafe, performant, and flexible 24/7 operation. The brief enumerates the design space and trade-offs; it does not prescribe a single path.

**Previous session:** `docs/superpowers/handoff/2026-04-12-alpha-fu6-handoff.md` (FU-6 / FU-6b build tooling retirement). This session un-retired alpha to take on the resilience question.

## 1. Problem framing

The studio runs a never-ending livestream composited from six USB webcams plus overlay content (Sierpinski triangle with YouTube frames, token pole, album cover, chat-reactive overlays). The stream is also the primary feed into the hapax perception system; every camera drop reduces both the broadcast quality and the operator-sensing signal the downstream cognitive system depends on. The cameras are therefore dual-use and both uses require continuous availability.

Observed reality as of 2026-04-12: the BRIO subset is unstable enough that two of three are offline for large fractions of the day. The kernel surfaces `device descriptor read/64, error -71` (EPROTO) on the TS4 USB3.2 Gen2 hub chain and the compositor's `try_reconnect_camera` cannot recover from signal-level USB errors. Root-cause analysis is in `docs/research/2026-04-12-brio-usb-robustness.md`. That note is hardware-focused and does not address the software architecture; this brief extends it to cover the full stack.

## 2. Requirements

Operator framing — "resilient, robust, failsafe, performant, flexible" — translated into measurable criteria:

| Property | Operational meaning |
|----------|---------------------|
| **Resilient** | Any single camera failure (USB drop, frame stall, firmware hang) is recovered automatically without restarting the compositor process. Target: sub-30 s mean time to recovery for transient failures, sub-5 min for hard failures requiring reset. |
| **Robust** | Bus saturation, re-enumeration, cable flex, or host controller distress on one bus does not cascade into the others. No single upstream fault should lose more than one camera. |
| **Failsafe** | On a fault the system shows a last-known-good frame or a test-pattern slate — never a black rectangle, frozen garbage, or a process crash. Livestream remains live. Operator receives a notification within 30 s of any camera loss. |
| **Performant** | Glass-to-stream latency ≤ 500 ms sustained. GPU budget: the compositor must stay inside the VRAM / compute headroom left by Reverie, TabbyAPI, and person-detector (see `CLAUDE.md § VRAM budget` in memory). No frame drops under load at 1920×1080 / 30 fps per source. |
| **Flexible** | Camera additions, swaps, model changes (BRIO ↔ C920 ↔ Pi NoIR ↔ HDMI-capture), and layout reconfiguration happen without editing code. A camera can go offline and rejoin without compositor restart. The stream topology must not hard-depend on OBS. |

These are not all independent. Performance and flexibility pull against each other (hot-swap machinery costs latency); failsafe and robust overlap (both require detection + substitution). The design space below is read against this matrix.

## 3. Current architecture

Factual summary, derived from the codebase exploration this session. File:line references are repo-relative.

**Ingest.** `agents/studio_compositor/cameras.py:86` builds one GStreamer sub-branch per camera: `v4l2src` → `capsfilter` (1280×720 MJPEG, or 1920×1080 for BRIO at higher modes) → `jpegdec` (CPU, libjpeg-turbo AVX2 — `nvjpegdec` rejects USB MJPEG headers) → `tee`. Devices are resolved through `/dev/v4l/by-id/usb-046d_Logitech_*` symlinks, hardcoded in `agents/studio_compositor/config.py:34`.

**Composition.** `StudioCompositor` in `agents/studio_compositor/compositor.py` owns a single GStreamer pipeline. Cameras, Cairo overlays (Sierpinski / album / overlay zones / token pole / stream status), and the director loop are all children of this pipeline. GPU compositing via CUDA if available, CPU fallback otherwise. Cairo rendering runs on background threads via `CairoSourceRunner` (`agents/studio_compositor/cairo_source.py`) with output-surface caches and per-frame budget enforcement (`agents/studio_compositor/budget.py`).

**Output.** `agents/studio_compositor/output_router.py` multiplexes to: `/dev/video42` (v4l2 loopback → OBS Studio) and an HLS playlist at `/dev/shm/hapax-compositor/hls/`. OBS is the sole RTMP encoder for delivery to YouTube. A `studio.toggle_livestream` affordance is registered in the unified semantic recruitment pipeline as consent-gated (`CLAUDE.md § Stream-as-affordance`), but the compositor-side trigger that would drive a GStreamer RTMP sink directly does not yet exist — this is the prerequisite for epic A7.

**Reconnection.** `agents/studio_compositor/state.py:73` — `try_reconnect_camera()` checks that the device symlink still exists, sets the `v4l2src` element to NULL, sleeps 500 ms, and sets it back to PLAYING. Called roughly every 30 s from the state reader loop for any camera currently flagged offline. No backoff, no retry cap, no per-camera state machine.

**systemd.** `systemd/units/studio-compositor.service`: `Type=simple`, `Restart=on-failure`, `RestartSec=10`, `StartLimitBurst=5`, `StartLimitIntervalSec=300`. No `WatchdogSec`. `ExecStartPre=systemd/units/studio-camera-setup.sh` applies v4l2-ctl settings at startup (exposure / gain / focus per model). No udev rule retriggers this script on USB re-plug.

**Pi NoIR fleet.** Separate path: `pi-edge/hapax_ir_edge.py` captures a still every ~3 s via `rpicam-still`, runs ONNX Runtime inference, and `POST`s a JSON `IrDetectionReport` to `logos/api/routes/pi.py`. This is not a video path — the Pis feed perception, not the livestream.

**Telemetry.** Status is written to `~/.cache/hapax-compositor/status.json` every ~1 s (the `_camera_status` dict — "active" / "offline"). Langfuse spans for the director loop. No native Prometheus exporter for camera health, frame flow, or USB enumeration churn. Drift detector (`agents/drift_detector/freshness.py`) checks filesystem presence of expected devices.

## 4. Failure mode catalogue

### 4.1 Observed

| # | Failure mode | File:line of current handling | Gap |
|---|---|---|---|
| F1 | BRIO USB EPROTO (error -71) — device vanishes from `/dev/v4l/by-id/` | `agents/studio_compositor/state.py:73`, `cameras.py:97` | Software reconnect cannot recover signal-level errors. Only reboot works today. Root cause is hardware (TS4 hub / cable / power). |
| F2 | Cascade disconnect — multiple devices drop in the same second on a shared hub | None. Each camera handled independently. | No hub-aware grouping. Losing a hub loses every child camera and no component knows the failures are correlated. |
| F3 | Stale `/dev/v4l/by-id/` symlink after USB re-enumeration on a different port | `systemd/units/studio-camera-setup.sh` runs once at `ExecStartPre`. Not re-fired on re-plug. | No udev rule bridges kernel re-enumeration to the compositor. After re-plug the by-id path may still point at the old, now-dangling, device node. |
| F4 | v4l2src element stuck — device present but no frames flowing (driver hang) | Not detected. `_camera_status` never transitions back to offline. | No watchdog on frame flow. GStreamer upstream issue `gst-plugins-good#879` confirms `v4l2src` does not cleanly stop on device removal. |
| F5 | Director loop 47-minute silent outage because `max_tokens=300` returned empty content | Fixed PR #692 (raised to 2048), warning retained. | Illustrative of the broader pattern: long-running silent failures are the operator's worst category. |
| F6 | Reverie vocabulary cache froze for 18 h | Fixed PR #678 (reload on `GraphValidationError`). | Same pattern as F5. Applies equally to the camera side. |

### 4.2 Latent silent failures in the camera subsystem

The code review found several bare-except-pass patterns in the compositor that mask camera-adjacent failures. None of these are the camera ingest path directly, but all of them affect the director loop's ability to notice and react to a camera fault. Flagging them as follow-up items rather than core scope.

- `agents/studio_compositor/director_loop.py:121` — LLM key retrieval `except Exception: pass`. Fails silently if `pass show litellm/master-key` errors; the director's LLM calls then fail and there is no log.
- `agents/studio_compositor/director_loop.py:134` — album info read, silent fallback to `"unknown"`.
- `agents/studio_compositor/director_loop.py:146` — snapshot base64 capture, silent fallback to `None`.
- `agents/studio_compositor/compositor.py:126` — FX source switch `except Exception: pass`, no log.
- `systemd/units/studio-camera-setup.sh:51,59` — `2>/dev/null || true` swallows v4l2-ctl failures on BRIO focus.

The session handoff audit (pass 2) already closed five layers of the silent-failure onion on the compositor. These four are the residual. Operator has flagged this category as the worst-cost type of bug. The brief notes them here but defers the fix.

### 4.3 Structural gaps

| # | Gap | Consequence |
|---|---|---|
| G1 | No hot-swap boundary between camera ingest and the compositor. All cameras are in one pipeline. | Any upstream negotiation failure taints pipeline state; recovery requires service restart. |
| G2 | No dead-frame watchdog. Element state is checked, frame flow is not. | A camera that stops delivering frames but keeps its `v4l2src` state as PLAYING is invisible to the health signal. |
| G3 | No failsafe frame source per slot. Offline slots show black. | Visible gap in the stream; viewer-facing degradation. |
| G4 | No cascade-awareness. Per-camera state, not per-hub. | Correlated failures look like six independent problems; root-cause analysis is slower. |
| G5 | Compositor is SPOF. The v4l2 loopback sink is the only broadcast surface, and OBS is the only RTMP encoder. | Any compositor crash, OBS crash, or v4l2loopback module unload takes the stream down. `StartLimitBurst=5/300s` is exhausted in <3 min if reconnect loops go rampant. |
| G6 | No Prometheus exporter for frame flow / USB enumeration. | Operator cannot see degradation over time; cannot confirm that a "fix" actually fixed anything. |
| G7 | No test harness for USB disconnect. | Regressions are only detectable in production. |

## 5. Design space

The options below are not mutually exclusive. A realistic path combines three or four of them, tiered by cost and reversibility.

### 5.1 Hardware layer

**H1 — Diagnose and fix the TS4 hub chain first.** `docs/research/2026-04-12-brio-usb-robustness.md` already has a costed investigation checklist. This is the cheapest and highest-expected-value step: if the TS4 hubs are undervolted or marginal, no amount of software will recover. External research confirms that USB 3.0 Gen2 hub chains are the dominant failure source for multi-UVC 24/7 deployments (The Good Penguin, "Multiple UVC cameras on Linux"; Arch BBS #262432 on Logitech USB 3.0 xHCI crashes). Confidence high. Trade-off: requires physical access and about $60 for a replacement industrial hub (Startech / Plugable / Anker).

**H2 — Distribute cameras across multiple host controllers.** External research (Renesas µPD720201 docs, pipci.jeffgeerling) documents the µPD720201 as the de-facto machine-vision USB card: 4 ports, full isochronous support, independent PCIe bandwidth domain per card. One PCIe card per ~2 BRIOs isolates xHCI failures and multiplies the bandwidth ceiling. Two cards adds ~$50. Trade-off: PCIe slot occupancy, driver consistency across kernel updates.

**H3 — Move to HDMI-capture isolation.** Magewell USB Capture HDMI Gen 2 is positioned for 24/7 operation and presents as a generic UVC device. Pattern: mirrorless / broadcast camera → HDMI out → Magewell → USB UVC. This puts a firmware boundary between the camera and the host: the camera can crash without taking USB down, and the Magewell can be power-cycled independently. Trade-offs: per-unit cost ($300+), camera body cost if we don't already have HDMI-out sources, and it does not help for the three existing C920s.

**H4 — Move to PoE IP cameras for a subset.** Broadcast-industry consensus is that Ethernet is structurally more reliable than USB isochronous for unattended deployment — no isochronous contention, longer cable runs, camera handles its own encoding, clean electrical isolation. Trade-offs: 1–3 s glass-to-glass latency via RTSP (vs ~200–300 ms for UVC, confirmed in Tkachenko's Pi 5 measurement series), loss of BRIO-class image quality unless buying high-end PTZs. Likely best as a complement, not a replacement.

**H5 — Icron fiber USB extenders for electrical isolation.** Icron Spectra 3022 (100 m multimode) or Raven 3124 (200 m, USB 3.1). Vendor documentation claims very low failure rate under continuous operation. Trade-off: ~$800+ per pair. Applicable if the studio layout has ground-loop or reach issues; not obviously needed for the current topology.

**Recommendation ordering for hardware layer:** H1 (do this first), H2 (do this second), H3/H4 (evaluate only after H1+H2 have been measured for a week).

### 5.2 Ingest layer (GStreamer architecture)

**I1 — Per-camera sub-pipeline with `gst-interpipe` hot-swap.** The canonical GStreamer pattern for multi-source compositors with hot-swappable sources. Each camera runs in its own `GstPipeline` feeding an `interpipesink`. A single compositor pipeline contains one `interpipesrc` per slot, switching via the `listen-to` property at runtime with no pipeline state disruption. RidgeRun (gst-interpipe maintainer) documents it as explicitly designed to handle EOS, state changes, and element swaps safely. Confidence high. Trade-off: +1 third-party dependency (LGPL, Rust-free, well-maintained), added complexity in the pipeline graph, ~300–500 LOC of Python wiring.

**I2 — `fallbackswitch` / `fallbacksrc` from `gst-plugins-rs`.** Upstream GStreamer's Rust plugin set provides `fallbackswitch` (filter that swaps to a fallback stream when the primary stops producing buffers within a configurable timeout) and `fallbacksrc` (source wrapper that handles URI retry and live conversion, can render a static image or silent audio during outages). Originally built for HLS/RTSP source resilience but architecturally applicable to v4l2 sources. Confidence high. Trade-off: requires `gst-plugins-rs` installed, more opinionated than interpipe (pick either the interpipe or the fallbackswitch path, not both).

**I3 — Dead-frame watchdog via `watchdog` element.** `gst-plugins-bad` ships a `watchdog` element that posts a `GST_RESOURCE_ERROR_BUSY` to the bus when no buffers flow for `timeout` ms. Mature, simple, and is the canonical "did the frames actually arrive" seam. Insertion is a single element per camera branch. Pattern confirmed in NVIDIA Jetson forums ("Watchdog for detecting a faulty camera"). Confidence high. Trade-off: minimal. Reports staleness but does not recover — must be combined with a bus-message handler that drives reconnect.

**I4 — Bandwidth-cap kernel patch or MJPEG budget management.** External research (AgRoboticsResearch/uvc_multi_cam_patch) documents that UVC cameras systematically over-report bandwidth via `dwMaxPayloadTransferSize`, and the kernel honours the inflated value, causing `ENOSPC` on second-camera attach. A non-upstream patch to `drivers/media/usb/uvc/uvc_video.c` caps the transfer size for compressed formats and has shipped 8 cameras on a single host successfully. Confidence high for the diagnosis, medium for the patch path (not mainline, requires kernel build). Trade-off: building and maintaining a custom kernel is a large commitment. The cheaper substitute is H2 (distribute cameras across multiple xHCI controllers) which achieves the same bandwidth budget without kernel modification.

**I5 — Per-camera v4l2 sequence / drop counter exporter.** External research confirms no off-the-shelf Prometheus exporter for v4l2 / GStreamer exists. Building one is small (~200 LOC Python): scrape `v4l2_buf->sequence` from the sink, timestamp last frame per source, expose as gauges (`frames_received_total{role=...}`, `last_frame_age_seconds{role=...}`, `usb_errors_total{bus=...}` parsed from `dmesg`). Trade-off: one net-new service. Low risk.

**Recommendation ordering for ingest layer:** I3 (do first — two-line change, immediate observability), I1 or I2 (do one of them — I1 is more mature for multi-source compositors, I2 is upstream-supported), I5 (do after I3 so metrics are meaningful), I4 only if H2 proves insufficient.

### 5.3 Recovery layer

**R1 — Per-camera state machine with exponential backoff.** Replace `try_reconnect_camera`'s fixed 30-s polling with a proper circuit-breaker / backoff-on-failure loop: fast retry first few attempts (1 s, 2 s, 4 s, 8 s), then exponential up to a 5-min ceiling, with explicit state transitions (HEALTHY → DEGRADED → OFFLINE → RECOVERING). External research on broadcast patterns (coaxion.net fallback-stream handling) confirms the principle: tight reconnect loops on a flapping device generate kernel log noise and can deepen the underlying bug. Trade-off: ~150 LOC replacement of state.py:73. Must coordinate with I3 (watchdog) and G5 (startLimitBurst).

**R2 — USBDEVFS_RESET as an escalation step.** For cameras that are "half-present" (enumerated but not streaming), `ioctl(fd, USBDEVFS_RESET, 0)` on `/dev/bus/usb/<bus>/<dev>` can force a device reset. Well-documented via `usbreset.c` reference implementation. Can clear some EPROTO states without a full reboot. Trade-off: requires `CAP_SYS_ADMIN` or a setuid helper. Not a substitute for fixing the hardware (H1).

**R3 — Udev-driven retriggering of `studio-camera-setup.sh`.** Ship a udev rule at `systemd/udev/70-studio-cameras.rules` that fires on `SUBSYSTEM=="usb"` + `ATTR{idVendor}=="046d"` + `ATTR{idProduct}=="08e5"|"085e"` `ACTION=="add"` and triggers a systemd path unit that re-runs the v4l2-ctl setup script scoped to the re-added device. Closes F3 and G1 at the hardware-event boundary. Trade-off: requires installing a system-level udev rule (not repo-tracked today).

**R4 — `systemctl reset-failed` loop guard.** The current `StartLimitBurst=5/300s` limit is too tight for a system that expects to lose cameras occasionally. Lift to `StartLimitBurst=20/3600s` and add `WatchdogSec=60` once the compositor is refactored to `Type=notify`. Trade-off: Python + PyGObject + sd_notify is some glue work but a known pattern.

**R5 — USB autosuspend disable via udev.** Kernel docs and hamwaves.com document the global `usbcore.autosuspend=-1` kernel parameter and per-device udev rules. BRIO is not a high-power-management device; disabling autosuspend costs nothing practical and removes one category of "the kernel decided to power the camera down" failures. Trade-off: adds a kernel parameter or a small udev rule.

**Recommendation ordering for recovery layer:** R5 (first — 10-minute change), R1 (second — replaces existing flawed loop), R4 (third — depends on R1 being in place), R3 (fourth — hardware-event closure), R2 (fifth — last-resort escalation, requires privilege).

### 5.4 Delivery layer

**D1 — Native GStreamer RTMP from compositor (epic A7).** Eliminates OBS as the RTMP encoder. The compositor adds a second output branch: `tee` → `queue` → `nvh264enc` → `flvmux` → `rtmp2sink` directly to YouTube. Already registered as a consent-gated affordance (`studio.toggle_livestream`) awaiting the compositor-side trigger. Confidence high. Trade-off: A7 is a substantial project; it is the listed architectural follow-up for alpha's Stream A. Costs 1–2 days of careful work including smoke tests against YouTube's ingest.

**D2 — SRT instead of RTMP.** SRT has ARQ and is structurally more robust to packet loss than RTMP. Confirmed by Norsk Video and Cloudflare Stream docs. **Critical constraint:** YouTube Live does not support SRT ingest directly — only RTMP, RTMPS, HLS, DASH (Google for Developers, "Live Ingestion Protocol Comparison"). SRT-to-YouTube workflows pass through an intermediate relay. Trade-off: adds a relay hop (MediaMTX or SRS locally) for marginal benefit unless the last-mile has measurable loss.

**D3 — Local RTMP relay (MediaMTX or SRS) as decoupler.** The compositor publishes to a local MediaMTX at `rtmp://127.0.0.1:1935/stream`; MediaMTX forwards to YouTube. Benefit: the compositor and the external-delivery hop become independently restartable. If MediaMTX is down, the compositor keeps running and the stream just stops delivering externally (degraded, not dead). MediaMTX is a single Go binary, multi-protocol, actively maintained. SRS is the higher-feature alternative. Confidence high. Trade-off: one more service to operate and monitor.

**D4 — Backup ingest with primary/backup stream keys.** YouTube provides a backup stream key; Castr/Restream/Mikulski have well-documented patterns for primary+backup failover. **Caveat from Castr docs:** "mixing different encoders or settings may cause glitches" — both encoders must be configured identically, and realistically need two independent network connections to avoid common-mode failure. Trade-off: second encoder process, second network egress. Rarely worth it for a single-machine studio unless uplink reliability is the bottleneck.

**Recommendation ordering for delivery layer:** D1 first (it is the listed epic and closes G5), D3 immediately after (decouples compositor from the external hop), D2 and D4 only if last-mile loss is measured and material.

### 5.5 Observability layer

**O1 — Native v4l2 / GStreamer Prometheus exporter.** Scrape frame counters, last-frame age, bus-message history, USB enumeration events from `/sys/kernel/debug/usb/devices` and `dmesg`. Grafana panel: one row per camera, frames/s and last-frame-age gauges, annotations for every USB disconnect. Small project (~400 LOC Python), no upstream exists, already a known gap. Confidence high. Trade-off: one new service.

**O2 — ntfy on camera offline transitions.** Today the only escalation is a notification on systemd unit failure. Per-camera offline transitions should also notify, throttled per distinct event (same pattern as FU-6b's throttled ntfy). Trade-off: minimal — one notification call at each state transition.

**O3 — Grafana "camera health" dashboard.** Panels: per-camera frame rate, per-camera last-frame age, USB enumeration count per bus, kernel error rate (parsed from `dmesg`), compositor restart count, RTMP ingest bitrate, HLS playlist age. Depends on O1. Low risk once O1 is in place.

**O4 — Test harness via `USBDEVFS_RESET` and/or uHubCtl hardware switches.** External research confirms that `USBDEVFS_RESET` simulates most but not all USB failure modes; physical VBUS-cutting hardware (YKUSH, Acroname) is required for the full surface. Simulated disconnect tests can run in CI and gate merges. Trade-off: CI environment needs privileged USB access, which is realistic for a self-hosted runner.

**Recommendation ordering for observability layer:** O2 (immediate, one line), O1 (second, prerequisite for everything else), O3 (third), O4 (last, only after a stable state is reached).

### 5.6 Pi edge layer

Current state: the Pi NoIR daemons do not feed the livestream — they POST JSON detection reports. If the perception surface ever needs live Pi video (for example, if the compositor's BRIO slots are permanently replaced by Pi camera modules with libcamera), the clean path is documented.

**P1 — MediaMTX on the Pi with native libcamera integration.** MediaMTX has first-class `rpiCameraWidth`/`rpiCameraBitrate` support, eliminating the inter-process boundary that breaks on `rpicam-vid` crash. Single Go binary per Pi. Confidence high. Trade-off: bundled libcamera may pin to a version; ArduCam-style cameras requiring custom libcamera need a from-source build.

**P2 — go2rtc as a universal relay.** Direct competitor to MediaMTX at the multi-protocol streaming layer. Differentiates on two-way codec negotiation (transcodes only when the client requires it). Either P1 or P2; not both.

**P3 — Transport choice.** Tkachenko's controlled measurement on Pi 5 + Camera v3: WebRTC ~200 ms, raw H.264/TCP ~300 ms, MJPEG/HTTP ~500 ms, RTSP ~1300 ms. WebRTC with hardware H.264 is also the lowest CPU / lowest bandwidth combo. For 24/7 stability, WebRTC via MediaMTX is the recommended path if latency matters; MJPEG/HTTP is the "ugly bulletproof" fallback with no protocol negotiation and trivial restart semantics (kig/raspivid_mjpeg_server reference). RTSP is the worst of both worlds here.

**Deferred.** The Pi edge path is not urgent. The livestream runs on the workstation-local USB cameras today. This section is for reference if the operator decides to substitute Pi video for BRIO.

## 6. Recommended phased approach (for operator review — not a decided plan)

Tiered by cost and reversibility. Each tier is independent; operator can stop at any tier and still have a materially more resilient system.

### Tier 0 — Same-day (hours of work)

Cheapest and highest expected value. These are all code changes in the compositor plus two systemd tweaks; no hardware, no new services.

1. **I3** — insert a `watchdog` element into each camera sub-branch, timeout 5000 ms. Handle the bus-error message to drive reconnect instead of only relying on element state.
2. **R5** — udev rule (or `/etc/modprobe.d/uvcvideo.conf`) disabling USB autosuspend for BRIO and C920 VIDs.
3. **O2** — ntfy on every offline/online transition, throttled per distinct event.
4. **R4** — raise `StartLimitBurst` to 20 per 3600 s in `studio-compositor.service`.
5. **H1** (parallel, operator-dependent) — execute the cheap steps in `docs/research/2026-04-12-brio-usb-robustness.md § Recommended investigation § Cheap`: swap the two offline BRIOs to the stable Renesas port, check TS4 hub power, thermal check.

Expected outcome: most transient failures are detected and surface as notifications; the compositor stops falling into `StartLimitBurst` exhaustion; autosuspend is ruled out as a cause.

### Tier 1 — This week

Medium complexity. Introduces hot-swap architecture and observability.

6. **I1** — refactor the compositor to use `gst-interpipe`. Each camera runs in its own sub-pipeline feeding an `interpipesink`; the main composite pipeline contains `interpipesrc` per slot. This is the single largest behaviour change — worth scoping as a dedicated epic with its own design doc and smoke tests.
7. **G3 via `fallbacksrc` or a manual `videotestsrc` + compositor alpha pattern** — offline slots show a last-known-good frame or a test-pattern slate instead of black.
8. **R1** — replace `try_reconnect_camera` with a per-camera state machine and exponential backoff. Depends on I1 (state is now per-sub-pipeline, not per-element).
9. **R3** — udev rule retriggers `studio-camera-setup.sh` on USB add events scoped to studio camera VIDs.
10. **O1** — ship a v4l2 Prometheus exporter. ~400 LOC Python, one new systemd unit.

Expected outcome: hot-swappable camera sources, graceful degradation on any single-camera failure, measurable frame-flow health.

### Tier 2 — This month

Structural changes that close the architectural gaps. These are each day-sized or larger.

11. **D1** — epic A7: native GStreamer RTMP from the compositor, eliminate OBS as the encoder. Close G5. The `studio.toggle_livestream` affordance becomes operational.
12. **D3** — local MediaMTX or SRS relay between the compositor and YouTube. Compositor can restart without interrupting delivery (relay buffers for a few seconds).
13. **H2** — second Renesas µPD720201 PCIe card; distribute BRIOs across two host controllers. Closes F2 (cascade) at the physical layer.
14. **O3** — Grafana dashboard on top of the O1 exporter.
15. **O4** — test harness: `USBDEVFS_RESET` simulation of USB disconnects, integrated into CI on a self-hosted runner with physical cameras.

Expected outcome: the stream is architecturally decoupled from any single process or bus. Recovery is measurable, testable, and bounded.

### Tier 3 — Not this quarter, document only

Projects that may or may not be worth doing depending on Tier 0–2 outcomes.

- **H3** — HDMI-capture isolation for high-value broadcast cameras (only if we already have or plan to buy HDMI-out camera bodies).
- **H4** — PoE IP camera substitution for one or two of the existing slots.
- **H5** — Icron fiber USB extenders (only if studio layout or ground-loop issues emerge).
- **I4** — custom kernel with UVC bandwidth cap patch (only if H2 proves insufficient and we cannot add more PCIe controllers).
- **P1/P2/P3** — Pi edge video path (only if we decide to substitute Pi camera modules for BRIO).
- Silent-failure cleanup in the director loop (`director_loop.py:121/134/146`, `compositor.py:126`, `studio-camera-setup.sh:51/59`) — operator-flagged follow-up, should be bundled into a dedicated "silent failure sweep" PR rather than mixed with this resilience work.

## 7. Open questions for operator

Steering needed before any of the above ships. Listed in priority order.

1. **H1 status.** Has the cheap hardware investigation in the BRIO USB robustness note been executed? Without that, every software-layer fix is working around a hardware fault. The first five-minute action items in that note are the highest-expected-value work in this entire brief.
2. **Tier 0 acceptance.** Is the Tier 0 set (I3 + R5 + O2 + R4 + H1) something I can ship as a single PR this session, or should each sub-item be its own PR for reviewability? My default would be a single small PR since the items are independent one-to-three-line changes, but Tier 0 item 1 (I3 watchdog wiring) is closer to 30–50 LOC and may deserve its own PR.
3. **A7 timing.** Is the A7 native RTMP work still on the roadmap? The alpha Stream A handoff lists it as "large feature, probably needs brainstorming." This brief's Tier 2 assumes A7 is in play. If A7 is deferred indefinitely, D3 (local MediaMTX relay) becomes a higher priority as a decoupling layer that works with today's OBS encoder.
4. **GPU budget.** The existing `CLAUDE.md § Studio Compositor` notes CUDA compositing "if available" with CPU fallback. Tier 1 item 6 (gst-interpipe) multiplies the number of pipelines but not the aggregate GPU load. Should be safe, but worth confirming against the VRAM budget before refactor.
5. **Pi NoIR substitution.** Is there operator interest in moving any livestream slot from a USB BRIO to a Pi camera module? If yes, P1/P2/P3 move out of Tier 3. If no, Pi remains perception-only and the video path can be deleted from the plan.
6. **Testing environment.** Does the operator want a hardware test harness (YKUSH-style VBUS switch) for CI, or is `USBDEVFS_RESET` simulation good enough? The former is physical-access-dependent; the latter is software-only.

## 8. References

### Internal (repo-relative)

- `docs/research/2026-04-12-brio-usb-robustness.md` — hardware-focused root cause analysis
- `docs/superpowers/handoff/2026-04-12-alpha-fu6-handoff.md` — prior alpha session retirement handoff
- `docs/superpowers/handoff/2026-04-12-alpha-stream-handoff-2.md` — five-layer silent-failure onion closure on the compositor
- `agents/studio_compositor/cameras.py:86,97` — camera ingest branch construction
- `agents/studio_compositor/config.py:34` — hardcoded by-id device paths
- `agents/studio_compositor/state.py:73` — current reconnect logic
- `agents/studio_compositor/compositor.py` — StudioCompositor orchestration shell
- `agents/studio_compositor/director_loop.py:121,134,146` — residual silent-failure patterns (follow-up scope)
- `agents/studio_compositor/output_router.py` — sink routing including v4l2 loopback and HLS
- `agents/studio_compositor/budget.py` — per-frame cost tracking envelope
- `systemd/units/studio-compositor.service` — current Restart / StartLimitBurst configuration
- `systemd/units/studio-camera-setup.sh` — v4l2-ctl application at service start
- `logos/api/routes/pi.py` — Pi NoIR JSON ingestion endpoint
- `pi-edge/hapax_ir_edge.py` — Pi edge daemon entry
- `shared/compositor_model.py` — SourceSchema / Assignment / Layout models
- `CLAUDE.md § Studio Compositor` — authoritative compositor architecture summary

### External (verified URLs from this session's research)

USB / kernel:
- [Linux kernel USB errors -71 and -110 — Daniel Lange](https://daniel-lange.com/archives/183-Linux-kernel-USB-errors-71-and-110.html)
- [obs-studio#9418 BRIO Ultra HD Webcam camera hangs](https://github.com/obsproject/obs-studio/issues/9418)
- [Arch BBS #262432 — USB-Controller crashes after increasing webcam resolution](https://bbs.archlinux.org/viewtopic.php?id=262432)
- [media: uvcvideo: Invert default value for nodrop — linuxtv-commits](https://www.mail-archive.com/linuxtv-commits@linuxtv.org/msg47126.html)
- [linux/drivers/media/usb/uvc/uvc_driver.c](https://github.com/torvalds/linux/blob/master/drivers/media/usb/uvc/uvc_driver.c)
- [Linux UVC FAQ — ideasonboard.org](https://www.ideasonboard.org/uvc/faq/)
- [Power Management for USB — kernel.org](https://www.kernel.org/doc/html/v4.16/driver-api/usb/power-management.html)
- [Fixing USB Autosuspend — hamwaves.com](https://hamwaves.com/usb.autosuspend/en/)

BRIO field reports:
- [OBS Forums — Logitech Brio 4k (again): lag](https://obsproject.com/forum/threads/logitech-brio-4k-again-lag.162384/)
- [OBS Forums — Logitech Brio is delayed at 4k](https://obsproject.com/forum/threads/logitech-brio-is-delayed-at-4k.85189/)
- [OBS Forums — Brio + C920 tearing/glitching](https://obsproject.com/forum/threads/logitech-brio-and-c920-webcam-screen-tearing-glitching-only-when-streaming.171762/)
- [obs-studio#2349 — Brio 4K image glitches constantly](https://github.com/obsproject/obs-studio/issues/2349)
- [BRIO firmware update support page — Logitech](https://support.logi.com/hc/en-us/articles/360023196794-How-do-I-upgrade-my-BRIO-firmware-and-what-platforms-do-you-support)

GStreamer:
- [gst-plugins-good#879 — v4l2src Doesn't Stop After Device Removed](https://gitlab.freedesktop.org/gstreamer/gst-plugins-good/-/issues/879)
- [GStreamer watchdog element](https://gstreamer.freedesktop.org/documentation/debugutilsbad/watchdog.html)
- [gst-plugins-bad gstwatchdog.c source](https://github.com/GStreamer/gst-plugins-bad/blob/master/gst/debugutils/gstwatchdog.c)
- [GStreamer fallbackswitch](https://gstreamer.freedesktop.org/documentation/fallbackswitch/fallbackswitch.html)
- [Automatic retry and fallback stream handling — coaxion.net (Sebastian Dröge / slomo)](https://coaxion.net/blog/2020/07/automatic-retry-on-error-and-fallback-stream-handling-for-gstreamer-sources/)
- [GstInterpipe — RidgeRun developer wiki](https://developer.ridgerun.com/wiki/index.php?title=GstInterpipe)
- [RidgeRun/gst-interpipe on GitHub](https://github.com/RidgeRun/gst-interpipe)
- [GStreamer nvh264enc documentation](https://gstreamer.freedesktop.org/documentation/nvcodec/nvh264enc.html)
- [Multiple Gstreamer Video Input Switching and Compositing — creativemisconfiguration](https://creativemisconfiguration.wordpress.com/2023/10/15/multiple-gstreamer-video-input-switching-and-compositing/)
- [OBS 31.1.2 Linux capture fixes — itsfoss](https://itsfoss.gitlab.io/blog/obs-studio-3112-fixes-linux-capture-issues/)

Hardware:
- [Multiple UVC cameras on Linux — The Good Penguin](https://www.thegoodpenguin.co.uk/blog/multiple-uvc-cameras-on-linux/)
- [AgRoboticsResearch/uvc_multi_cam_patch README](https://github.com/AgRoboticsResearch/uvc_multi_cam_patch/blob/main/README.md)
- [linux-uvc-devel: force lower USB bandwidth allotment](https://linux-uvc-devel.narkive.com/Y8vMik3I/force-a-lower-usb-bandwidth-allotment-compressed-streams-multiple-webcams)
- [Renesas uPD720201 product page](https://www.renesas.com/en/products/upd720201)
- [Renesas uPD720201 — pipci.jeffgeerling.com](https://pipci.jeffgeerling.com/cards_usb/renesas-UPD720201-usb3-6amlifestyle.html)
- [Icron Spectra 3022](https://www.icron.com/products/icron-brand/usb-extenders/fiber/usb-3-0-spectra-3022/)
- [Magewell USB Capture HDMI](https://www.magewell.com/capture/usb-capture)

Pi edge:
- [bluenviron/mediamtx on GitHub](https://github.com/bluenviron/mediamtx)
- [bluenviron/mediamtx-rpicamera on GitHub](https://github.com/bluenviron/mediamtx-rpicamera)
- [MediaMTX Raspberry Pi Cameras documentation](https://mediamtx.org/docs/publish/raspberry-pi-cameras)
- [AlexxIT/go2rtc on GitHub](https://github.com/AlexxIT/go2rtc)
- [Raspberry Pi 5 Video Stream Latencies — Eugene Tkachenko, Medium](https://gektor650.medium.com/comparing-video-stream-latencies-raspberry-pi-5-camera-v3-a8d5dad2f67b)
- [kig/raspivid_mjpeg_server on GitHub](https://github.com/kig/raspivid_mjpeg_server)

Delivery and ingest:
- [YouTube Live Ingestion Protocol Comparison — Google for Developers](https://developers.google.com/youtube/v3/live/guides/ingestion-protocol-comparison)
- [Delivering Live YouTube Content via RTMPS — Google for Developers](https://developers.google.com/youtube/v3/live/guides/rtmps-ingestion)
- [RTMP vs SRT for Video Ingest — Norsk Video](https://norsk.video/rtmp-vs-srt-for-video-ingest/)
- [Cloudflare Stream SRT support](https://blog.cloudflare.com/stream-now-supports-srt-as-a-drop-in-replacement-for-rtmp/)
- [Backup Ingest — Castr docs](https://docs.castr.com/en/articles/5023371-backup-ingest-how-to-use-benefits-and-limitations)
- [Backup stream for 24/7 broadcasts — Mikulski](https://mikulski.rocks/backup-stream-for-24-7/)
- [ossrs/srs on GitHub](https://github.com/ossrs/srs)

Monitoring and testing:
- [V4L2 counting dropped frames — NVIDIA Developer Forums](https://forums.developer.nvidia.com/t/v4l2-counting-dropped-frames/260083)
- [v4l-utils v4l2-ctl-streaming.cpp source](https://github.com/gjasny/v4l-utils/blob/master/utils/v4l2-ctl/v4l2-ctl-streaming.cpp)
- [Watchdog for detecting a faulty camera — NVIDIA Developer Forums](https://forums.developer.nvidia.com/t/watchdog-for-detecting-a-faulty-camera/259738)
- [USBDEVFS_RESET vs IOCTL_USB_RESET — codestudy.net](https://www.codestudy.net/blog/usbdevfs-reset-vs-ioctl-usb-reset/)
- [Linux Kernel Host Side USB API](https://www.kernel.org/doc/html/latest/driver-api/usb/usb.html)
