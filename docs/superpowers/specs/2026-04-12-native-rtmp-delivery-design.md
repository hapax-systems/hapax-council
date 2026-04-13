# Native GStreamer RTMP Delivery — Design (Camera Epic Phase 5)

**Filed:** 2026-04-12
**Status:** Formal design. Implementation in Phase 5 of the camera resilience epic.
**Epic:** `docs/superpowers/plans/2026-04-12-camera-247-resilience-epic.md`
**Closes:** epic A7 (native GStreamer RTMP, eliminate OBS as the broadcast encoder).
**Depends on:** Phase 2 (hot-swap architecture) merged so the composite pipeline topology is known-stable.

## Purpose

Add a native GStreamer RTMP output branch to the studio compositor's composite pipeline so the livestream flows glass → compositor → H.264 encode → RTMP without requiring OBS Studio as an intermediate encoder. Add a local MediaMTX relay between the compositor and YouTube to decouple capture from last-mile delivery. Close delivery-layer gap G5 from the research brief (OBS as SPOF, v4l2 loopback as SPOF). Make the `studio.toggle_livestream` affordance operational.

The present topology: compositor → `/dev/video42` v4l2 loopback → OBS → RTMP → YouTube. OBS is the only RTMP encoder; v4l2loopback is a kernel module that must be loaded; the OBS process is an external dependency that the compositor cannot monitor or restart. Any OBS crash, module unload, configuration error, or resource contention takes the stream down.

New topology: compositor → `nvh264enc` → `flvmux` → `rtmp2sink` → local MediaMTX on `127.0.0.1:1935` → MediaMTX `runOnReady` ffmpeg relay → YouTube RTMP endpoint. OBS remains available as a parallel consumer of the existing v4l2 loopback for operator-driven scene composition, but the 24/7 livestream no longer depends on it.

## Requirements

- **R1.** Compositor publishes H.264 video + AAC audio as RTMP to `rtmp://127.0.0.1:1935/studio` via `rtmp2sink`.
- **R2.** MediaMTX accepts the stream on `127.0.0.1:1935` and invokes `ffmpeg` via `runOnReady` to push to YouTube's RTMP ingest endpoint.
- **R3.** Stream key is loaded from `pass show streaming/youtube-stream-key` at MediaMTX launch time; never committed to repo.
- **R4.** RTMP output bin is a `GstBin` with its own error handling. Encoder errors are bounded to the RTMP bin and trigger a rebuild-in-place without restarting the composite pipeline or interrupting v4l2 loopback / HLS outputs.
- **R5.** The `studio.toggle_livestream` affordance handler starts/stops the RTMP bin. It is consent-gated via the existing unified semantic recruitment pipeline.
- **R6.** Existing OBS path via `/dev/video42` v4l2 loopback is **preserved** — OBS can still consume the composite as a virtual camera.
- **R7.** Existing HLS output to `/dev/shm/hapax-compositor/hls/` is preserved.
- **R8.** Stream latency: glass-to-YouTube ingest ≤ 3 seconds sustained. YouTube adds its own ~5–15 s to viewer latency; we target low-latency broadcast settings but do not control the YouTube side.
- **R9.** Bitrate: 6 Mbps CBR for 1080p30 (YouTube's recommended mid-range).
- **R10.** On MediaMTX crash, systemd restarts it; the compositor's `rtmp2sink` reconnects automatically.
- **R11.** On compositor restart, MediaMTX stays running; the YouTube stream may glitch for a few seconds but does not require operator intervention.

## Architecture

### Topology (new)

```
┌─── studio-compositor process ──────────────────────────────────────────┐
│                                                                         │
│   per-camera producer pipelines ─► composite pipeline ─► compositor    │
│                                              │                          │
│                                              ▼                          │
│                                            tee                          │
│                                    ┌─────────┼─────────┬─────────┐     │
│                                    │         │         │         │     │
│                                    ▼         ▼         ▼         ▼     │
│                               v4l2sink    HLS sink   RTMP bin   NDI   │
│                              (unchanged) (unchanged) (NEW P5)  (future)│
│                                                      │                  │
│                              ┌───────────────────────┤                  │
│                              │                       │                  │
│                              ▼                       ▼                  │
│                   rtmp2sink                    (audio branch)           │
│                   location=rtmp://127.0.0.1:  nvh264enc → h264parse ─┐  │
│                   1935/studio                                         │  │
│                              ▲                                        │  │
│                              │                                        ▼  │
│                              └────────── flvmux ◄───── aac_h264  ─────┘  │
│                                                      pipewiresrc → voaacenc │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                 │ rtmp://127.0.0.1:1935/studio
                 ▼
┌─── mediamtx.service (systemd user unit, new in P5) ─────────────────┐
│                                                                      │
│   [rtmp listener :1935]  ──►  path "studio" ──► runOnReady:         │
│                                                  ffmpeg -re -i -    │
│                                                  -c copy -f flv    │
│                                                  rtmp://a.rtmp.youtube.com/ │
│                                                  live2/$KEY         │
│                                                                      │
│   [metrics :9998]  ──►  /metrics (Prometheus scrape)                │
└──────────────────────────────────────────────────────────────────────┘
                 │ rtmp
                 ▼
         YouTube Live ingest
```

### Why MediaMTX as a relay

Research (§5.3 and §6.3 of the research brief, confirmed in agent 2) found MediaMTX is the best-supported multi-protocol relay for this use case:

1. **Decouples compositor restart from stream continuity.** Compositor can restart without MediaMTX dropping the YouTube connection — MediaMTX holds the upstream TCP open for a few seconds of buffering.
2. **Native Prometheus metrics on port 9998.** Exports per-path byte counts, client counts, session duration, connection state — feeds directly into the Phase 4 observability stack without additional code.
3. **Single Go binary, no runtime deps.** `mediamtx-bin` from AUR installs a single binary.
4. **`runOnReady` is the canonical pattern for "accept stream, push to another endpoint."** Documented and battle-tested.
5. **Easy swap between primary and backup YouTube endpoints** via config edit.

### Why `nvh264enc` and not `nvcudah264enc`

Verified at Phase 1 install check: `gst-inspect-1.0 nvcudah264enc` returns "No such element or plugin" on this CachyOS build (GStreamer 1.28.2, gst-plugins-bad 1.28.1). `gst-inspect-1.0 nvh264enc` succeeds and shows a fully-documented property surface. The encoder factory name is `nvh264enc` (NVENC H.264 Video Encoder CUDA Mode).

Research from agent 1 noted that `nvcudah264enc` uses a newer NVENC SDK preset enum (p1..p7 + tuning-info) while `nvh264enc` uses the legacy `hq/hp/low-latency/...` preset enum. Phase 5 uses `nvh264enc` exclusively; the newer preset enum is not applicable here.

`nvautogpuh264enc` is also available as an alternative auto-selecting factory, but for a known-good single-GPU setup we specify `nvh264enc` directly for predictability.

### Why `rtmp2sink` and not `rtmpsink`

Research (agent 1 § 3.3) confirmed `rtmp2sink` (from `libgstrtmp2.so`) is the maintained native-GStreamer RTMP implementation, while `rtmpsink` (from `libgstrtmp.so` using librtmp) is the legacy path. Both are installed on this build. `rtmp2sink` is the preferred choice.

**Caveat:** `rtmp2sink` does NOT support `rtmps://`, `rtmpe://`, or `rtmpt://`. For plain RTMP (which the local MediaMTX accepts), `rtmp2sink` is fine. The MediaMTX-to-YouTube leg uses plain RTMP too (YouTube's `a.rtmp.youtube.com/live2/KEY` is plain RTMP; RTMPS uses `a.rtmps.youtube.com/live2/KEY` — different host). If operator wants RTMPS to YouTube, the MediaMTX `runOnReady` ffmpeg command switches to `rtmps://...`; the compositor → MediaMTX leg stays plain RTMP.

## Component design

### RtmpOutputBin

`agents/studio_compositor/rtmp_output.py` (new file).

Wraps the video encoder + audio encoder + mux + RTMP sink as a single `GstBin` that can be attached to and detached from the composite pipeline's tee.

```python
from __future__ import annotations

import logging
import threading
from typing import Optional

from gi.repository import Gst, GLib

log = logging.getLogger(__name__)


class RtmpOutputBin:
    """RTMP output as a detachable GstBin."""

    def __init__(
        self,
        *,
        video_tee: Gst.Element,
        audio_target: Optional[str] = "hapax-broadcast-sink",
        rtmp_location: str = "rtmp://127.0.0.1:1935/studio",
        bitrate_kbps: int = 6000,
        gop_size: int = 60,
    ) -> None:
        self._video_tee = video_tee
        self._audio_target = audio_target
        self._rtmp_location = rtmp_location
        self._bitrate_kbps = bitrate_kbps
        self._gop_size = gop_size

        self._bin: Gst.Bin | None = None
        self._video_tee_pad: Gst.Pad | None = None
        self._state_lock = threading.RLock()
        self._rebuild_count = 0

    def build_and_attach(self, composite_pipeline: Gst.Pipeline) -> bool:
        """Construct the bin and splice it into the composite via tee pad."""
        with self._state_lock:
            if self._bin is not None:
                return True  # already attached

            self._bin = Gst.Bin.new("rtmp_output_bin")

            # Video path: tee -> queue -> videoconvert -> nvh264enc -> h264parse
            video_queue = Gst.ElementFactory.make("queue", "rtmp_video_queue")
            video_queue.set_property("max-size-buffers", 30)
            video_queue.set_property("max-size-time", 2 * Gst.SECOND)
            video_queue.set_property("leaky", 2)  # downstream

            video_convert = Gst.ElementFactory.make("videoconvert", "rtmp_video_convert")

            encoder = Gst.ElementFactory.make("nvh264enc", "rtmp_nvh264enc")
            encoder.set_property("bitrate", self._bitrate_kbps)
            encoder.set_property("rc-mode", 2)  # 2 = CBR (verify with gst-inspect-1.0 at install)
            encoder.set_property("gop-size", self._gop_size)
            encoder.set_property("zerolatency", True)
            encoder.set_property("preset", 4)  # 4 = low-latency-hq (verify at install)

            h264_parse = Gst.ElementFactory.make("h264parse", "rtmp_h264parse")
            h264_parse.set_property("config-interval", -1)

            # Audio path: pipewiresrc -> audioconvert -> audioresample -> voaacenc -> aacparse
            audio_src = Gst.ElementFactory.make("pipewiresrc", "rtmp_audio_src")
            if self._audio_target:
                audio_src.set_property("target-object", self._audio_target)

            audio_convert = Gst.ElementFactory.make("audioconvert", "rtmp_audio_convert")
            audio_resample = Gst.ElementFactory.make("audioresample", "rtmp_audio_resample")
            audio_caps = Gst.ElementFactory.make("capsfilter", "rtmp_audio_caps")
            audio_caps.set_property(
                "caps",
                Gst.Caps.from_string("audio/x-raw,rate=48000,channels=2,format=S16LE"),
            )
            audio_encoder = Gst.ElementFactory.make("voaacenc", "rtmp_voaacenc")
            audio_encoder.set_property("bitrate", 128000)
            aac_parse = Gst.ElementFactory.make("aacparse", "rtmp_aacparse")

            # Mux + sink
            mux = Gst.ElementFactory.make("flvmux", "rtmp_flvmux")
            mux.set_property("streamable", True)
            mux.set_property("latency", 100_000_000)  # 100 ms

            sink = Gst.ElementFactory.make("rtmp2sink", "rtmp_sink")
            sink.set_property("location", self._rtmp_location)
            sink.set_property("async-connect", True)

            # Add all elements to the bin
            for el in [
                video_queue, video_convert, encoder, h264_parse,
                audio_src, audio_convert, audio_resample, audio_caps,
                audio_encoder, aac_parse,
                mux, sink,
            ]:
                if el is None:
                    log.error("rtmp bin: failed to create element")
                    self._bin = None
                    return False
                self._bin.add(el)

            # Link video path
            video_queue.link(video_convert)
            video_convert.link(encoder)
            encoder.link(h264_parse)
            h264_parse.link_pads("src", mux, "video")

            # Link audio path
            audio_src.link(audio_convert)
            audio_convert.link(audio_resample)
            audio_resample.link(audio_caps)
            audio_caps.link(audio_encoder)
            audio_encoder.link(aac_parse)
            aac_parse.link_pads("src", mux, "audio")

            # Link mux to sink
            mux.link(sink)

            # Expose a ghost sink pad on the bin for the video queue input
            video_queue_sink_pad = video_queue.get_static_pad("sink")
            ghost_pad = Gst.GhostPad.new("video_sink", video_queue_sink_pad)
            ghost_pad.set_active(True)
            self._bin.add_pad(ghost_pad)

            # Add the bin to the composite pipeline
            composite_pipeline.add(self._bin)

            # Request a new tee src pad and link to the bin's ghost sink pad
            tee_src_pad = self._video_tee.get_request_pad("src_%u")
            if tee_src_pad is None:
                log.error("rtmp bin: failed to request tee pad")
                composite_pipeline.remove(self._bin)
                self._bin = None
                return False
            self._video_tee_pad = tee_src_pad

            if tee_src_pad.link(ghost_pad) != Gst.PadLinkReturn.OK:
                log.error("rtmp bin: failed to link tee pad")
                self._video_tee.release_request_pad(tee_src_pad)
                composite_pipeline.remove(self._bin)
                self._bin = None
                self._video_tee_pad = None
                return False

            # Sync bin state to composite pipeline state (PLAYING)
            self._bin.sync_state_with_parent()

            log.info("rtmp bin attached; rebuild_count=%d", self._rebuild_count)
            return True

    def detach_and_teardown(self, composite_pipeline: Gst.Pipeline) -> None:
        """Remove the bin from the pipeline cleanly."""
        with self._state_lock:
            if self._bin is None:
                return

            # Block the tee pad, then unlink, then remove
            if self._video_tee_pad is not None:
                self._video_tee_pad.add_probe(
                    Gst.PadProbeType.BLOCK_DOWNSTREAM,
                    lambda pad, info: Gst.PadProbeReturn.OK,
                )
                self._video_tee_pad.unlink(self._bin.get_static_pad("video_sink"))
                self._video_tee.release_request_pad(self._video_tee_pad)
                self._video_tee_pad = None

            self._bin.set_state(Gst.State.NULL)
            composite_pipeline.remove(self._bin)
            self._bin = None
            log.info("rtmp bin detached")

    def rebuild_in_place(self, composite_pipeline: Gst.Pipeline) -> bool:
        """Tear down and rebuild. Called from bus error handler on encoder fault."""
        with self._state_lock:
            self._rebuild_count += 1
            self.detach_and_teardown(composite_pipeline)
            return self.build_and_attach(composite_pipeline)

    def is_attached(self) -> bool:
        with self._state_lock:
            return self._bin is not None
```

### Bus error routing

The RTMP bin is a child of the composite pipeline, so its errors DO propagate to the composite bus. To bound the error scope, the compositor's bus message handler inspects the error's `msg.src` element name: if it starts with `rtmp_` (matching any element name in the RTMP bin), the error is routed to `RtmpOutputBin.rebuild_in_place()` via `GLib.idle_add` and the error is **not** propagated to the normal "compositor has died" fallback.

Pseudocode in `compositor.py::_on_bus_message`:

```python
if msg.type == Gst.MessageType.ERROR:
    err, debug = msg.parse_error()
    src = msg.src.get_name() if msg.src else "(unknown)"
    if src.startswith("rtmp_"):
        log.error("RTMP bin error: src=%s err=%s debug=%s", src, err, debug)
        GLib.idle_add(self._rtmp_bin.rebuild_in_place, self._pipeline)
        metrics.RTMP_ENCODER_ERRORS_TOTAL.labels(endpoint="youtube").inc()
        metrics.RTMP_BIN_REBUILDS_TOTAL.labels(endpoint="youtube").inc()
        return True  # consume — do not propagate to default handler
    # ... existing error handling for non-RTMP sources ...
```

The "consume the error" pattern is critical: without the explicit return-true to the bus watch, the composite pipeline would still die on RTMP encoder failures. Since all RTMP bin elements are named with a `rtmp_` prefix, filtering by source name is reliable.

### Affordance handler wiring

The `studio.toggle_livestream` affordance is already registered in `STUDIO_AFFORDANCES` and consent-gated via `AffordancePipeline._consent_allows` (documented in `CLAUDE.md § Stream-as-affordance`). The current handler is a stub. Phase 5 fills in the real implementation:

```python
# agents/studio_compositor/affordance_handlers.py (modified or new)
def handle_toggle_livestream(
    *,
    compositor: "StudioCompositor",
    activate: bool,
    reason: str,
) -> AffordanceResult:
    if activate:
        if compositor.rtmp_bin.is_attached():
            return AffordanceResult(success=True, message="already live")
        ok = compositor.rtmp_bin.build_and_attach(compositor.pipeline)
        if ok:
            metrics.RTMP_CONNECTED.labels(endpoint="youtube").set(1)
            ntfy("Livestream started", f"Reason: {reason}", "default", "rocket")
            return AffordanceResult(success=True, message="rtmp bin attached")
        return AffordanceResult(success=False, message="rtmp bin build failed")
    else:
        if not compositor.rtmp_bin.is_attached():
            return AffordanceResult(success=True, message="already off")
        compositor.rtmp_bin.detach_and_teardown(compositor.pipeline)
        metrics.RTMP_CONNECTED.labels(endpoint="youtube").set(0)
        ntfy("Livestream stopped", f"Reason: {reason}", "default", "stop_sign")
        return AffordanceResult(success=True, message="rtmp bin detached")
```

The consent gate prevents unauthorized recruitment of the affordance; when the gate is closed, the handler is never invoked. This is structural — the gate is enforced at `AffordancePipeline.select`, not inside the handler.

### Audio source

`pipewiresrc target-object="hapax-broadcast-sink"` taps a pre-configured PipeWire filter-chain node. The compositor does not own the PipeWire topology — `config/pipewire/` already has filter-chain configs per `CLAUDE.md § Voice FX Chain`. Phase 5 adds a new filter-chain config for the broadcast audio mix if none exists, or reuses an existing one. The target object name is configurable via env var `HAPAX_BROADCAST_AUDIO_TARGET` for testing.

If the PipeWire node does not exist, `pipewiresrc` fails at build time. The bin build returns False. No stream starts. Operator sees a clear error.

## MediaMTX configuration

### Install

Phase 1 installs `mediamtx-bin` from AUR:

```bash
paru -S mediamtx-bin
```

Verify: `mediamtx --version` returns a version string.

### Config file

`config/mediamtx.yml` (new, repo-tracked):

```yaml
# Studio livestream RTMP relay — feeds YouTube via ffmpeg sidecar.
# Run as: mediamtx /path/to/config/mediamtx.yml
# Stream key injected at launch time by scripts/mediamtx-start.sh.

rtmp: yes
rtmpAddress: 127.0.0.1:1935

hls: no
webrtc: no
srt: no
api: no

metrics: yes
metricsAddress: 127.0.0.1:9998

logLevel: info
logDestinations: [stdout]

paths:
  studio:
    source: publisher
    runOnReady: >
      ffmpeg -hide_banner -loglevel warning
      -re -i rtmp://127.0.0.1:1935/studio
      -c copy
      -f flv rtmp://a.rtmp.youtube.com/live2/${HAPAX_YOUTUBE_STREAM_KEY}
    runOnReadyRestart: yes
```

Key settings:
- `rtmp: yes, rtmpAddress: 127.0.0.1:1935` — RTMP listener on loopback only. The compositor (also on localhost) publishes here.
- `hls: no, webrtc: no, srt: no` — no other protocols. Smaller attack surface.
- `metrics: yes, metricsAddress: 127.0.0.1:9998` — Prometheus scrape endpoint.
- `paths.studio.source: publisher` — the compositor is the publisher.
- `runOnReady` — when the stream is published, invoke ffmpeg to push it to YouTube. `runOnReadyRestart: yes` respawns ffmpeg if it exits (e.g., brief YouTube disconnect).
- `${HAPAX_YOUTUBE_STREAM_KEY}` — injected from the environment by the wrapper script. Never committed.

### Wrapper script

`scripts/mediamtx-start.sh` (new):

```bash
#!/usr/bin/env bash
# Launch MediaMTX with the YouTube stream key loaded from pass.
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
CONFIG="${REPO_ROOT}/config/mediamtx.yml"

if [[ ! -f "$CONFIG" ]]; then
    echo "ERROR: MediaMTX config not found at $CONFIG" >&2
    exit 1
fi

# Load stream key from pass
if ! HAPAX_YOUTUBE_STREAM_KEY=$(pass show streaming/youtube-stream-key 2>/dev/null); then
    echo "ERROR: pass show streaming/youtube-stream-key failed" >&2
    exit 1
fi
export HAPAX_YOUTUBE_STREAM_KEY

exec mediamtx "$CONFIG"
```

### systemd unit

`systemd/units/mediamtx.service` (new):

```ini
[Unit]
Description=MediaMTX RTMP relay for studio livestream → YouTube
After=network-online.target hapax-secrets.service
Wants=network-online.target
PartOf=studio-compositor.service

[Service]
Type=simple
WorkingDirectory=%h/projects/hapax-council
ExecStart=%h/projects/hapax-council/scripts/mediamtx-start.sh
Restart=on-failure
RestartSec=5s
StartLimitBurst=10
StartLimitIntervalSec=600
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=%h
SyslogIdentifier=mediamtx
OnFailure=notify-failure@%n.service

[Install]
WantedBy=default.target
```

- `PartOf=studio-compositor.service` — stopping the compositor stops MediaMTX too. Starting them is independent (MediaMTX comes up on boot; compositor connects when it starts).
- `After=network-online.target hapax-secrets.service` — needs networking and the secrets dir to exist.
- `Restart=on-failure, RestartSec=5s` — 5 s recovery from any crash.
- `%h` resolves to `$HOME` at unit instantiation — no literal paths.

### YouTube endpoint choice

Primary: `rtmp://a.rtmp.youtube.com/live2/${KEY}` — plain RTMP, low overhead.

Backup (documented, not auto-configured): `rtmps://a.rtmps.youtube.com/live2/${KEY}` — RTMPS, TLS-encrypted, slightly higher overhead. Operator can edit `config/mediamtx.yml` to switch; change is a single line.

The YouTube backup stream key (from YouTube Studio's "Go Live" settings) is ignored in Phase 5 — no primary/backup failover. Deferred to "later" if operator ever needs it.

## Data flow (live)

1. Camera frame reaches composite's compositor element (from alpha Phase 2 hot-swap path).
2. Compositor element outputs a single 1920×1080 NV12 frame at 30 fps.
3. `tee` branches the frame to: v4l2sink (unchanged), HLS sink (unchanged), RTMP bin.
4. RTMP bin's video path: `queue → videoconvert → nvh264enc (CBR 6 Mbps, GOP 60, zerolatency) → h264parse`.
5. `flvmux` muxes video + audio into FLV container.
6. `rtmp2sink` writes the muxed bytes to `rtmp://127.0.0.1:1935/studio`.
7. MediaMTX accepts the publish on path `studio`, transitions to "ready" state.
8. MediaMTX's `runOnReady` hook fires, invoking `ffmpeg -re -i rtmp://127.0.0.1:1935/studio -c copy -f flv rtmp://a.rtmp.youtube.com/live2/$KEY`.
9. ffmpeg reads the muxed FLV from MediaMTX and streams it (without re-encoding) to YouTube's ingest endpoint.
10. YouTube ingests, processes, encodes for viewers.

Audio flow (parallel):
1. Operator speaks or audio is generated elsewhere in the system.
2. Routed through the existing PipeWire filter chain to a broadcast-sink capture node (configured separately, see `config/pipewire/voice-fx-*.conf` patterns).
3. `pipewiresrc target-object="hapax-broadcast-sink"` reads from the capture node at 48 kHz stereo.
4. `audioconvert → audioresample → capsfilter → voaacenc → aacparse` encodes at 128 kbps AAC.
5. Muxed into flvmux alongside video.

### End-to-end latency budget

| Segment | Latency |
|---------|---------|
| Camera → composite (Phase 2) | ≤ 200 ms |
| Composite → encoded h264 | ~30 ms (one frame + encoder lookahead) |
| flvmux + rtmp2sink → MediaMTX | ~30 ms |
| MediaMTX → ffmpeg passthrough → YouTube ingest | ~100 ms |
| **Glass-to-YouTube ingest** | **~360 ms** |
| YouTube ingest → viewer | 5–15 s (uncontrollable) |

R8 (≤ 3 s glass-to-ingest) is comfortably met. Viewer latency is a YouTube concern.

## Error model

| Error | Scope | Recovery |
|-------|-------|----------|
| `nvh264enc` fails (CUDA context lost, NVENC session limit, OOM) | RTMP bin bus message with `rtmp_nvh264enc` source | Bus handler calls `RtmpOutputBin.rebuild_in_place()`. Bin torn down, rebuilt. Composite unaffected. |
| `rtmp2sink` disconnects (MediaMTX dead, network blip) | RTMP bin bus error | Same as above — rebuild the bin. `rtmp2sink async-connect=TRUE` handles initial connect asynchronously, but once connected, disconnects are surfaced as errors. |
| `pipewiresrc` cannot find target | Bin build fails at `build_and_attach` time | `handle_toggle_livestream` returns failure; operator sees the error via affordance result. Bin is not added to the pipeline. |
| `voaacenc` errors | RTMP bin bus | Rebuild bin. |
| `flvmux` errors | RTMP bin bus | Rebuild bin. |
| MediaMTX process crashes | Not visible to compositor directly | systemd restarts MediaMTX in ≤ 5 s. rtmp2sink reconnect kicks in via `async-connect`. |
| MediaMTX ffmpeg sidecar crashes (YouTube disconnected) | Not visible to compositor | `runOnReadyRestart: yes` respawns ffmpeg. YouTube ingest resumes; viewer sees brief dropout. |
| YouTube ingest rejects the stream (bad key, rate limit) | ffmpeg logs + MediaMTX logs | Operator must fix (rotate stream key, wait for rate limit). Compositor keeps sending to MediaMTX, which keeps trying to relay. |
| Composite pipeline dies | Everything dies | systemd restarts compositor. Since `mediamtx.service` is not `BindsTo=` compositor, MediaMTX keeps running. New compositor reconnects. |

### Rebuild safety

`RtmpOutputBin.rebuild_in_place()` is the critical recovery path. It must be safe to call repeatedly. The design uses:
- A reentrant lock (`_state_lock`) to prevent concurrent rebuilds.
- `detach_and_teardown` is idempotent (bails out if already detached).
- Rebuild count is tracked in the metric `studio_rtmp_bin_rebuilds_total{endpoint="youtube"}`.
- If rebuilds fail 5 times in a row, the affordance is marked degraded and a high-priority ntfy fires. After that, the bin stays detached until the next `toggle_livestream` affordance invocation.

## Bitrate and quality settings (nvh264enc properties — verification required)

Research from agent 1 gave a reference table based on older gst-plugins-bad nvbaseenc.c source. Phase 5 installs Phase 1 and runs `gst-inspect-1.0 nvh264enc` to verify the actual property surface on this build (GStreamer 1.28.2). The tentative values:

| Property | Value | Meaning |
|----------|-------|---------|
| `bitrate` | 6000 | kbps, mid-range of YouTube 1080p30 recommended 4500–9000 |
| `rc-mode` | 2 (cbr) | Constant bitrate — YouTube expects steady bitrate |
| `preset` | 4 (low-latency-hq) | Low-latency preset with high quality bias |
| `gop-size` | 60 | Keyframe every 2 s at 30 fps — YouTube recommends 2–4 s |
| `zerolatency` | True | Disable B-frames and other latency-adding features |
| `qp-min`, `qp-max` | -1 (preset default) | Let the preset pick |

**Verification step at Phase 5 start:** `gst-inspect-1.0 nvh264enc | grep -A 2 -E "bitrate|rc-mode|preset|gop-size|zerolatency"` to confirm enum values match what the design specifies. Any discrepancy is documented in the PR body and the design doc updated.

## Thread safety

- The affordance handler is called from the GLib main loop thread (via the unified recruitment pipeline running in the same process).
- Bus error messages arrive on the GLib main loop thread.
- `RtmpOutputBin._state_lock` is a reentrant lock; all public methods take it.
- `build_and_attach` and `detach_and_teardown` manipulate GStreamer state — safe from the main loop thread only. `rebuild_in_place` is invoked via `GLib.idle_add` from the bus handler, so it also runs on the main loop thread.
- Prometheus metrics updates are thread-safe via `prometheus_client`'s internal locking.

## Test strategy

Unit tests (no real NVENC, no real RTMP):

- `test_rtmp_bin_builds_with_fake_encoder` — substitute `fakesink` for `rtmp2sink` and `identity` for `nvh264enc`, verify bin construction + attach + detach round-trip.
- `test_rtmp_bin_rebuild_idempotent` — call `rebuild_in_place` three times, verify `_rebuild_count` == 3 and the bin is attached after the last call.
- `test_rtmp_bus_error_routing` — post a fake `GST_MESSAGE_ERROR` with `src.get_name() == "rtmp_nvh264enc"`, verify the bus handler routes to `rebuild_in_place`.
- `test_affordance_handler_success` — call `handle_toggle_livestream(activate=True)`, verify `build_and_attach` called.
- `test_affordance_handler_idempotent` — call twice with activate=True, second call returns "already live" without double-building.

Integration tests (gated `@pytest.mark.rtmp`, manual):

- `test_real_rtmp_to_local_mediamtx` — start MediaMTX, start compositor, build RTMP bin, `ffprobe rtmp://127.0.0.1:1935/studio` sees video + audio streams.
- `test_mediamtx_metrics_visible` — `curl http://127.0.0.1:9998/metrics` shows `rtmp_conns_bytes_received` non-zero.
- `test_rtmp_to_fake_youtube` — redirect MediaMTX `runOnReady` to a local `rtmp://127.0.0.1:19350/test` sink (via `nginx-rtmp` or another MediaMTX instance), verify bytes arrive.
- `test_real_rtmp_to_youtube_with_disposable_key` — operator-manual only; requires a disposable YouTube stream key. Verify the stream appears in YouTube Studio's preview within 30 s of affordance trigger.
- `test_nvh264enc_rebuild_under_fake_error` — inject a fake NVENC error via a test fixture, verify the bin rebuilds and streaming resumes.

## Rollback

Phase 5 is the only phase with a genuine "what if it breaks the stream" concern. The rollback path:

1. Revert the Phase 5 PR. The compositor goes back to the existing OBS-via-v4l2-loopback path.
2. `systemctl --user stop mediamtx.service && systemctl --user disable mediamtx.service`.
3. OBS resumes RTMP push to YouTube via its existing configuration.

The existing OBS path is preserved throughout Phase 5 — the RTMP bin is additive, not a replacement. A quick A/B comparison is possible during smoke testing: run both paths in parallel (compositor pushes to local MediaMTX, OBS pushes to YouTube from v4l2 loopback), compare latency and quality, keep whichever works.

## Acceptance criteria

- MediaMTX installed and running as a systemd user service.
- `config/mediamtx.yml` committed to repo with the `runOnReady` pattern.
- `scripts/mediamtx-start.sh` installs and loads stream key from pass.
- `agents/studio_compositor/rtmp_output.py` shipped with unit tests.
- Composite pipeline's `tee` has a new request pad for the RTMP bin.
- Bus error handler routes `rtmp_*` errors to `rebuild_in_place`.
- `studio.toggle_livestream` affordance handler fills in with real activation logic.
- Compositor + MediaMTX running; `ffprobe rtmp://127.0.0.1:1935/studio` sees video and audio.
- With a disposable YouTube stream key, the stream appears in YouTube Studio's preview within 30 s of affordance activation.
- Prometheus metrics exposed: `studio_rtmp_bytes_total`, `studio_rtmp_connected`, `studio_rtmp_encoder_errors_total`, `studio_rtmp_bin_rebuilds_total`, `studio_rtmp_bitrate_bps`.
- OBS path via `/dev/video42` still works for operator-driven scene composition.
- Existing tests pass.

## Risks

1. **nvh264enc property enum values differ from agent 1's research.** Mitigation: verify at Phase 5 start with `gst-inspect-1.0 nvh264enc`. Update design doc if enums differ.
2. **PipeWire broadcast audio sink doesn't exist or isn't routable.** Mitigation: audio path is configurable via env var; operator can point at a different PipeWire target. Failing that, the bin builds without audio via a `-a` flag that substitutes `audiotestsrc` (documented fallback for debugging).
3. **rtmp2sink connect blocks the composite pipeline on network slowdown.** Mitigation: `async-connect=TRUE` keeps the connect off the streaming thread. Verified in rtmp2 source.
4. **YouTube rejects the stream (bad key, geo block, rate limit).** Mitigation: surface MediaMTX's ffmpeg stderr as a logged warning. Operator sees failure signal immediately.
5. **MediaMTX runOnReady hook fails silently if ffmpeg binary is missing.** Mitigation: `scripts/mediamtx-start.sh` verifies `ffmpeg --version` before launching MediaMTX.
6. **Consumer GPU NVENC session limit (5–8 concurrent sessions).** Mitigation: we use 1. Acceptable. Document in `CLAUDE.md` the NVENC session budget.
7. **Bin teardown on pad-probe block races composite pipeline processing.** Mitigation: pad block is downstream-only; upstream continues flowing. The downstream probe waits until current frame is out, then unlinks. Well-tested GStreamer pattern.
8. **SPR (single point of relay).** MediaMTX becomes a new SPOF — if it dies, YouTube stops. Mitigation: systemd Restart=on-failure with 5 s recovery. For full dual-path, future work adds a second encoder + second relay.

## Open questions

1. **Should the RTMP bin be started automatically on compositor boot, or only via affordance?** Current design: only via affordance (consent-gated). Rationale: the compositor should not autonomously start broadcasting. Operator confirms the decision.
2. **Is Phase 5 bitrate dynamic based on network conditions?** No — CBR fixed 6 Mbps. Future work could add congestion-aware bitrate via `nvh264enc`'s `bitrate` property hot-update.
3. **Should audio be muxed into RTMP at all?** Yes — a silent stream is broken. If PipeWire isn't available, the fallback `audiotestsrc` emits silence as a valid track to keep YouTube happy.
4. **Stream title / description / privacy setting?** Not Phase 5's concern. YouTube side of the broadcast is configured via YouTube Studio by the operator.

## References

### Internal

- `docs/superpowers/plans/2026-04-12-camera-247-resilience-epic.md`
- `docs/superpowers/specs/2026-04-12-compositor-hot-swap-architecture-design.md` (Phase 2)
- `docs/superpowers/specs/2026-04-12-v4l2-prometheus-exporter-design.md` (Phase 4)
- `CLAUDE.md § Stream-as-affordance` — the `studio.toggle_livestream` affordance
- `CLAUDE.md § Voice FX Chain` — PipeWire filter-chain patterns

### External

- [bluenviron/mediamtx](https://github.com/bluenviron/mediamtx)
- [mediamtx-bin AUR package](https://aur.archlinux.org/packages/mediamtx-bin)
- [MediaMTX metrics docs](https://mediamtx.org/docs/usage/metrics)
- [MediaMTX runOnReady YouTube restream discussion](https://github.com/bluenviron/mediamtx/discussions/2709)
- [GStreamer nvh264enc documentation](https://gstreamer.freedesktop.org/documentation/nvcodec/nvh264enc.html)
- [GStreamer rtmp2sink documentation](https://gstreamer.freedesktop.org/documentation/rtmp2/rtmp2sink.html)
- [GStreamer flvmux documentation](https://gstreamer.freedesktop.org/documentation/flv/flvmux.html)
- [YouTube Live encoder settings](https://support.google.com/youtube/answer/2853702)
- [YouTube Live Ingestion Protocol Comparison](https://developers.google.com/youtube/v3/live/guides/ingestion-protocol-comparison)
- [GStreamer rtmp2 cheat sheet](https://github.com/matthew1000/gstreamer-cheat-sheet/blob/master/rtmp.md)
