# Encoder + livestream output path systematic walk

**Date:** 2026-04-14
**Author:** delta (beta role — perf research)
**Scope:** Systematic walk of every output stage downstream
of the compositor's `output_tee`. The cam-stability arc
covered the path from BRIO/C920 USB capture through the
`v4l2sink` that OBS reads. This drop covers the
parallel/downstream branches: the RTMP encoder bin, the
local HLS sink, per-camera recording branches, the
mediamtx relay, and observability across all of them.
Pairs with drop #31 (cam-stability rollup) — together they
form a complete pipeline audit from `v4l2src` through
final delivery.
**Register:** scientific, neutral
**Status:** investigation — Ring 1 + Ring 2 + Ring 3
findings catalogued; no code changed
**Companion:** drop #28/#29/#30 (camera-side walks),
drop #31 (cam-stability rollup)

## Headline

**Five output destinations from one compositor.** The
`output_tee` is a 5-way fan-out:

| # | Destination | Status today | Encoder | Notes |
|---|---|---|---|---|
| 1 | `v4l2sink → /dev/video42` | always-on | none (raw YUY2) | OBS consumes |
| 2 | `hlssink2 → ~/.cache/hapax-compositor/hls/` | **always-on, no consumer** | nvh264enc qp=26 | ~2 MB/s to disk, no reader |
| 3 | `rtmp2sink → mediamtx :1935` | **consent-gated (off now)** | nvh264enc CBR 6 Mbps | bin attached only when livestream affordance recruited |
| 4 | `splitmuxsink × 6` (per-camera) | **consent-gated (off now)** | 6× nvh264enc qp=23 | each camera gets its own encoder |
| 5 | `smooth_delay → 2 fps` | always-on | none (raw) | covered in drop #29 |

**Six findings worth shipping, six observability gaps,
two architectural questions.**

### Six findings (ranked by leverage)

1. **HLS branch writes ~2 MB/s to disk 24/7 with no
   consumer** (recording.py:79-122, models.py:58). The
   HLS sink runs by default (`HlsConfig.enabled = True`),
   producing 2-second segments at ~4 MB each into
   `~/.cache/hapax-compositor/hls/`. Live `ls` confirms
   segment 00120 with mtime 13:31, ~2 MB/s sustained
   write. **No process reads `stream.m3u8`.** The compositor
   builds segments, writes them, lets the rolling window
   delete them, and that's the entire lifecycle. **Verify
   no consumer, then disable.**
2. **HLS encoder's `qp-const=26` overrides the configured
   `bitrate: 4000`** (recording.py:93, models.py:63).
   `HlsConfig.bitrate` is dead config — it's never read.
   Actual encoder output is ~16 Mbps (4 MB / 2 s × 8).
   The config field is misleading. Either honor it
   (`rc-mode=cbr` + `bitrate=4000`) or remove it.
3. **HLS encoder GOP misaligned with mediamtx LL-HLS
   target** (recording.py:94, mediamtx.yml). The
   compositor's local HLS sink uses
   `gop-size = fps × target_duration = 30 × 2 = 60`
   frames (= 2 seconds). Mediamtx is configured
   `hlsVariant: lowLatency, hlsSegmentDuration: 1s`,
   meaning the relay wants ≤1 s segments. **When the
   RTMP bin is active and mediamtx is republishing as
   LL-HLS, the 2 s GOP forces mediamtx into 2 s
   segments — defeating the LL-HLS configuration.**
   For LL-HLS to work, the RTMP encoder needs
   `gop-size = 30` (1 s) AND the encoder's `gop-size`
   path needs to honor the config (it currently uses
   `self._gop_size = 60` hard default in
   `RtmpOutputBin.__init__`).
4. **RTMP bin audio path has zero queues**
   (rtmp_output.py:108-141). The chain is
   `pipewiresrc → audioconvert → audioresample →
   capsfilter → voaacenc → aacparse → flvmux`. No
   `queue` element anywhere. If `voaacenc` ever takes
   more than ~10 ms to encode a frame, `pipewiresrc`
   backpressures into PipeWire, which can cause
   `xruns` upstream. With `flvmux latency=100ms`, the
   A/V alignment window is tight — any audio jitter
   exceeding 100 ms causes the mux to drop video to
   wait for audio.
5. **RTMP bin video queue lacks isolation between
   `videoconvert` and `nvh264enc`** (rtmp_output.py:77-99).
   The chain is `tee → queue → videoconvert → nvh264enc
   → h264parse → flvmux`. Only the input queue exists.
   Colorspace conversion and the encoder share a thread
   so an encoder stall blocks `videoconvert`, which
   backpressures the input queue (max 30 buffers,
   `leaky=2` downstream so it drops oldest). **Adding
   a `queue` between `videoconvert` and `nvh264enc`**
   isolates these, so `videoconvert` keeps draining
   the input even if NVENC briefly stalls.
6. **`v4l2sink` writes YUY2 (16 bpp) instead of NV12
   (12 bpp)** (pipeline.py:138). Caps are explicitly
   `format=YUY2`. At 1920×1080×30 fps that's
   124 MB/s of memory bandwidth through the
   `videoconvert` + v4l2sink path. NV12 would be
   93 MB/s. **31 MB/s of memory bandwidth saved** by
   switching, with the trade-off that OBS's V4L2
   source must accept NV12 (it does — OBS V4L2 plugin
   supports NV12, YUY2, and several other formats).
   Worth verifying with a test reload of the OBS
   source after changing caps.

### Six observability gaps

The compositor exposes 60+ Prometheus metrics on
`:9482`. **Zero of them describe the output side.**

7. **`studio_rtmp_bytes_total` counter is defined
   (metrics.py:370) but never observed.** Live
   `curl :9482/metrics | grep rtmp` returns only
   HELP/TYPE lines — the counter has no value because
   the bin is consent-gated and currently off.
   Acceptable, but if the bin is ever attached, there's
   no `rtmp2sink` byte hook in the bus message handler
   to populate it.
8. **No metric for `nvh264enc` instance count, latency,
   or QP.** When per-camera recording is enabled (6
   simultaneous encoders) there's no way to tell if any
   of them are stalling.
9. **No metric for `hlssink2` segment cadence.** If the
   HLS branch falls behind, segments get longer — no
   alert.
10. **No metric for `splitmuxsink` fragment count,
    write rate, or rotation.** Per-camera recordings
    could be silently failing.
11. **No metric for `v4l2sink` write throughput or
    OBS-side consumer connection state.** v4l2loopback
    consumer-count is readable from
    `/sys/devices/virtual/video4linux/video42/format`
    but never scraped.
12. **No metric for `flvmux` audio/video drift or
    drop count.** Drop #5-style issue could happen
    in the RTMP bin and we'd never see it.

### Two architectural questions

13. **Per-camera recording at 6× nvh264enc** (recording.py:15-77)
    is consent-gated and currently off, but if it ever
    activates: 6 simultaneous encoder instances at
    1280×720 NV12 30 fps qp=23 ≈ 8-12 Mbps each =
    48-72 Mbps of NVENC work + 6 separate cudauploads
    (~248 MB/s aggregate) on top of everything else.
    Today's NVENC engine sits at 4% utilization
    (`nvidia-smi dmon`). The headroom is there — but
    has anyone measured what 6 simultaneous encoders
    do to the RTMP bin's encoder-share contention?
    NVENC engine queue is FIFO-shared across processes
    on the GPU.
14. **Mediamtx writeQueueSize 512 packets is the
    default and unchanged** (mediamtx.yml only has
    `all_others:` empty). For a 6 Mbps stream pushing
    ~150-180 packets/sec, 512 packets is ~3 seconds of
    buffering. This is fine for stable LAN consumers
    but for slow WebRTC peers or LL-HLS clients with
    intermittent connectivity, the default is tight.
    Untested under real load.

## 1. The output topology

```text
                    output_tee (post-fx)
                         │
            ┌────────────┼─────────────┬──────────────┐
            │            │             │              │
       v4l2 branch  hls branch   smooth_delay   rtmp_output_bin
       (always)    (always)     (always)        (consent gate)
            │            │             │              │
       /dev/video42  ~/.cache/    smooth_delay     mediamtx :1935
       (OBS reads)   .../hls/     2 fps            ↓
                     local        sink ⇒ 6 fb       HLS / WebRTC / SRT
                     no reader    interpipes        republish

         [pre-fx tee]  →  3 snapshot branches
         [per-cam tee] →  per-camera recording (consent gate, currently off)
```

**Live state at 13:30:**

- `studio-compositor.service` active 6 min (since 13:22:36)
- `/dev/video42` advertised as `1920×1080 YUYV 30 fps`
- HLS dir contains 16 active segments, mtime 13:30:46-13:31:21
- Mediamtx running 13 h with no active publishers
  (`curl :9997/v3/paths/list` empty)
- NVENC engine at 4% utilization
  (`nvidia-smi dmon -c 3 -s u` → enc=2-4 across 3 samples)

## 2. Branch 1 — `v4l2sink` (OBS)

`pipeline.py:128-156`:

```python
queue_v4l2 = Gst.ElementFactory.make("queue", "queue-v4l2")
queue_v4l2.set_property("leaky", 2)
queue_v4l2.set_property("max-size-buffers", 1)        # ← Ring 1 fix A pending
convert_out = Gst.ElementFactory.make("videoconvert", "convert-out")
sink_caps.set_property(
    "caps",
    Gst.Caps.from_string(
        f"video/x-raw,format=YUY2,..."                  # ← finding 6
    ),
)
identity = Gst.ElementFactory.make("identity", "v4l2-identity")
identity.set_property("drop-allocation", True)
sink = Gst.ElementFactory.make("v4l2sink", "output")
sink.set_property("device", compositor.config.output_device)
sink.set_property("sync", False)
```

**Already in cam-stability rollup:**

- Ring 1 fix A (`max-size-buffers 1 → 5`) covers cushion
- Ring 1 fix B (v4l2loopback `max_buffers 2 → 8`) covers
  kernel-side cushion

**New here:**

- **Finding 6** (YUY2 → NV12) saves 31 MB/s. Untested
  with OBS — needs operator action to reload OBS V4L2
  source after caps change.
- The pipeline relies on a `_caps_dedup_probe` to handle
  v4l2sink renegotiation on source switches
  (pipeline.py:158-178). Working as designed but is a
  defensive workaround for v4l2loopback's negotiation
  behavior.

## 3. Branch 2 — `hlssink2` (local HLS)

`recording.py:79-122`:

```python
queue.set_property("leaky", 2)
queue.set_property("max-size-buffers", 20)
queue.set_property("max-size-time", 3 * 1_000_000_000)
encoder = Gst.ElementFactory.make("nvh264enc", "hls-enc")
encoder.set_property("preset", 2)            # HQ
encoder.set_property("rc-mode", 3)           # vbr ← but qp-const overrides
encoder.set_property("qp-const", 26)         # finding 2 — bitrate config dead
encoder.set_property("gop-size", fps * hls_cfg.target_duration)  # finding 3
hls_sink.set_property("target-duration", hls_cfg.target_duration)
hls_sink.set_property("playlist-length", hls_cfg.playlist_length)
hls_sink.set_property("max-files", hls_cfg.max_files)
```

**Confirmed live state (`ls -la ~/.cache/hapax-compositor/hls/`):**

- 16 segments active (`segment00105.ts` through
  `segment00120.ts`)
- Average size ~4 MB
- Mtimes confirm 2 s segment cadence
- `stream.m3u8` mtime is fresh — sink is actively writing
- **No process reads this file** (no `inotifywait` or
  `nginx`-style consumer running locally)

**Finding 1** quantification:

- 4 MB / 2 s = **2 MB/s sustained disk write**
- 16 segments × 4 MB ≈ 64 MB rolling window
- Daily volume if uncapped: ~172 GB/day (capped by
  `max_files=15` so disk grows to ~64 MB and holds)
- 24/7 nvh264enc work for nothing
- 24/7 NVENC slot consumed (1 of N hardware encoder
  contexts on the GPU)

**The fix question:** is the local HLS branch needed at
all? Three possible consumers:

- **OBS** — unlikely; OBS reads from `/dev/video42`,
  not from a local HLS file.
- **mediamtx republishing** — no, mediamtx pulls from
  the RTMP push, not from a local file.
- **Operator's browser preview** — possible. If
  operator opens `file://~/.cache/hapax-compositor/hls/stream.m3u8`
  in a browser to verify the stream, this is the
  consumer. Worth asking.

**If unused, the fix is a 1-line config change**:
`HlsConfig.enabled: bool = False` in models.py:58. That
shuts off the entire branch and reclaims the encoder
slot + disk bandwidth + per-frame buffer pool overhead.

## 4. Branch 3 — `rtmp_output_bin` (livestream)

`rtmp_output.py:32-294`. Dynamic detachable bin attached
via `toggle_livestream(True)` from
`compositor.py:648-682`.

**Topology:**

```python
tee → queue (max-size-buffers=30, max-size-time=2s, leaky=2)
    → videoconvert
    → nvh264enc (CBR 6 Mbps, gop=60, zerolatency=true,
                  preset=11 (p4 medium), tune=2 (low-latency))
    → h264parse (config-interval=-1)
                                ↓
                              flvmux (latency=100ms)
                                ↑
        pipewiresrc → audioconvert → audioresample
                    → capsfilter (S16LE 48000 stereo)
                    → voaacenc (128 kbps)
                    → aacparse
                                ↓
                              flvmux
                                ↓
                       rtmp2sink (async-connect=true)
                                ↓
                       rtmp://127.0.0.1:1935/studio
```

**Encoder config is good:** CBR + zerolatency + p4 medium
+ low-latency tune is the right preset family for live
streaming. NVENC will cap bitrate spikes, and the encoder
won't lookahead.

**Findings:**

- **Finding 4** (audio path lacks queues) — pipewiresrc
  is backpressure-sensitive. Two queue insertions:
  - between `pipewiresrc` and `audioconvert` (decouples
    PipeWire wallclock from GStreamer thread)
  - between `voaacenc` and `aacparse` (smooths AAC
    encode jitter into flvmux)
- **Finding 5** (no queue between videoconvert and
  nvh264enc) — single insertion fixes encoder-stall
  back-propagation:
  ```python
  enc_queue = Gst.ElementFactory.make("queue", "rtmp_enc_queue")
  enc_queue.set_property("max-size-buffers", 4)
  enc_queue.set_property("leaky", 0)  # don't drop, encoder is critical
  # link: video_convert → enc_queue → encoder
  ```
- **Finding 3** (gop=60 misaligned with LL-HLS) — for
  the mediamtx LL-HLS republish case, `gop_size` should
  be `30` (1 s) not `60` (2 s). The constructor default
  in `RtmpOutputBin.__init__` (rtmp_output.py:43-49) is
  `gop_size: int = 60` — change to `30`.

**Per-bin observability gap (finding 7):**
The bin defines `studio_rtmp_bytes_total`,
`studio_rtmp_connected`, `studio_rtmp_encoder_errors_total`,
`studio_rtmp_bin_rebuilds_total`, and
`studio_rtmp_bitrate_bps` (`metrics.py:370+`). None of
them are wired to actual events. The bin doesn't add a
buffer probe to count bytes through `rtmp2sink`'s sink
pad, doesn't update `RTMP_CONNECTED` from `rtmp2sink`'s
`element-message` events, doesn't react to bus error
counts. **All five metrics are skeleton-only.**

## 5. Branch 4 — per-camera recording (`splitmuxsink`)

`recording.py:15-77`. Currently **off** because
`RecordingConfig.enabled: bool = False` (models.py:49)
AND the per-camera valve drops when
`compositor._consent_recording_allowed` is False.

If enabled:

```python
camera_tee → queue → valve → cudaupload → cudaconvert
           → caps (NV12 in CUDAMemory) → nvh264enc (preset=2 hq, qp=23)
           → h264parse → splitmuxsink (matroskamux, 5 min segments)
```

**× 6 cameras** = 6 simultaneous encoders, 6 cudauploads.

**Architectural concern (#13):**

- 6 cameras × 1280×720 NV12 30 fps cudaupload =
  ~248 MB/s of CPU→GPU PCIe traffic
- 6 nvh264enc instances at qp=23 → roughly 60-90 Mbps
  aggregate encoder output
- All 6 share one NVENC engine (the GPU has 1 NVENC
  ASIC; multiple "contexts" are time-multiplexed)
- The RTMP bin's NVENC instance + the HLS branch's
  NVENC instance also share that same engine

If recording is enabled in the same window as the
RTMP livestream, that's **8 simultaneous nvh264enc
contexts** on one NVENC engine. Today's 4% engine
utilization says headroom exists but hasn't been
load-tested.

**Fix (Ring 3):** if per-camera recording is ever
needed, consolidate into a single
`compositorsink → record_tee → 1 encoder` topology
that writes one combined MKV instead of 6 separate
files. That trades per-camera isolation for encoder
efficiency (1 NVENC slot vs 6).

## 6. Branch 5 — `smooth_delay` (covered in drop #29)

Drop #29 § 3 covered this branch in detail. Ring 1 fix
F (frame-drop probe before `gldownload`) is still
pending. No new findings here.

## 7. Mediamtx — the relay nobody talks to

`/etc/mediamtx/mediamtx.yml` is essentially default
config:

- `paths: { all_others: }` — accepts publish on any path
- `hlsVariant: lowLatency, hlsSegmentDuration: 1s,
  hlsPartDuration: 200ms` — LL-HLS configured
- `writeQueueSize: 512` — default
- `rtmp: yes :1935` — listening
- `hls: yes :8888` — listening
- `webrtc: yes :8889` — listening

**Live state:**

- Process running 13 h
- No active publishers
- No active subscribers
- Listening on 1935/8888/8889 doing nothing

**Finding 14:** `writeQueueSize=512` is fine for stable
LAN consumers but tight for slow LL-HLS clients (each
HLS part is 200 ms = ~30 packets at 6 Mbps; 512
packets ≈ 17 parts ≈ 3.4 s of buffering before drop).
For the youtube-bound livestream this is irrelevant
(the upstream of the consumer is bandwidth-rich), but
worth bumping to 2048 if web-distributed consumers
ever appear.

**Finding 3 again** (LL-HLS misalignment):
- mediamtx wants 1 s segments
- compositor's RTMP bin pushes 2 s GOP
- mediamtx will create 2 s segments anyway because
  it can only cut on keyframes from the publisher
- LL-HLS `hlsPartDuration: 200ms` is moot if the
  upstream GOP is 2 s

The fix is in the publisher (compositor's RTMP bin),
not in mediamtx.

## 8. Ring summary — bundled as PRs

### Ring 1 (drop-everything, alpha-shippable)

| # | Fix | File | Lines | Impact |
|---|---|---|---|---|
| **HLS-1** | Disable HLS branch if unused | `models.py:58` | 1 | ~2 MB/s disk write reclaimed; NVENC slot freed; HLS NVENC + queue overhead gone |
| **RTMP-1** | RTMP bin `gop_size` default 60 → 30 | `rtmp_output.py:49` | 1 | Aligns with LL-HLS, halves keyframe interval |
| **HLS-2** | Remove dead `HlsConfig.bitrate` field OR honor it | `models.py:63` + `recording.py:93` | ~3 | Config no longer misleading |

**HLS-1 risk profile:** medium. Need operator
confirmation that no consumer reads
`~/.cache/hapax-compositor/hls/stream.m3u8`. If a
preview tab is open in a browser, this would break it.
**Operator action: confirm no HLS consumer.** If
unused, ship; if used, leave on.

**RTMP-1 risk profile:** zero — only affects livestream
output GOP, mediamtx LL-HLS becomes faster.

**HLS-2 risk profile:** zero — dead config cleanup.

### Ring 2 (small refactors)

| # | Fix | File | Lines | Impact |
|---|---|---|---|---|
| **RTMP-2** | Add audio queue between `pipewiresrc` and `audioconvert` | `rtmp_output.py:108-141` | ~6 | Decouples PipeWire wallclock from GStreamer thread, prevents pw xruns |
| **RTMP-3** | Add encoder queue between `videoconvert` and `nvh264enc` | `rtmp_output.py:77-99` | ~6 | Isolates encoder stalls from `videoconvert` backpressure |
| **V4L-1** | YUY2 → NV12 v4l2sink caps + verify OBS | `pipeline.py:138` | 1 | 31 MB/s memory bandwidth saved, needs OBS reload test |

**Risk profile:** RTMP-2 and RTMP-3 are pure additions
with no behavior change. V4L-1 needs an OBS source
reload to verify NV12 negotiation works — operator
action required.

### Ring 3 (architectural — measure first)

| # | Fix | File | Effort | Impact |
|---|---|---|---|---|
| **OBS-1** | Wire all 5 RTMP metrics to actual events (buffer probe, bus message handler, rolling bitrate calc) | `rtmp_output.py` + `compositor.py` | ~30 | Output side becomes observable |
| **REC-1** | Consolidate per-camera recording into one combined-mux encoder if recording ever enabled | `recording.py` | ~50 | 6 NVENC slots → 1 if recording needed |
| **MTX-1** | Bump `mediamtx.yml writeQueueSize: 512 → 2048` if web consumers appear | `/etc/mediamtx/mediamtx.yml` | 1 | Bigger jitter buffer for slow consumers |

**OBS-1 is the biggest leverage** in this ring. The
output side is currently a black box. With ~30 lines
of probe + bus-handler wiring, all 5 skeleton metrics
become real and the next encoder problem becomes
visible in Prometheus instead of needing a journal
grep.

## 9. The observability gap in numbers

Compositor exports 60+ metrics on `:9482`. By category:

- **Source-side**: `studio_camera_*` (15 metrics) ✓
- **Cairo source freshness**: `compositor_source_frame_*`
  (35 metrics across 7 sources) ✓
- **Cost tracking**: `compositor_publish_costs_*`,
  `compositor_publish_degraded_*` (10) ✓
- **Audio DSP**: `compositor_audio_dsp_ms_*` (4) ✓
- **GLfeedback**: `compositor_glfeedback_*` (4) ✓
- **State**: `studio_compositor_*` (10) ✓

- **Encoder-side**: 0
- **RTMP egress**: 5 defined, 0 populated
- **HLS sink**: 0
- **splitmuxsink**: 0
- **v4l2sink**: 0
- **flvmux**: 0

**Coverage ratio: ~80% of input observability,
0% of output observability.** This pairs with drop
#14's observability map — the input gaps are mostly
closed; the output gaps are completely open.

## 10. Recommended ship order

1. **Today / next session**: Ring 1 (HLS-1 if unused,
   RTMP-1, HLS-2). Lowest risk, biggest immediate
   reclamation.
2. **Within a week**: Ring 2 (RTMP-2, RTMP-3, V4L-1
   with OBS reload test). Sandbox-test V4L-1 first.
3. **Background investigation**: Ring 3 OBS-1 (encoder
   metrics) — pairs naturally with Phase 10
   observability work.
4. **Deferred**: Ring 3 REC-1 (recording consolidation)
   and Ring 3 MTX-1 (mediamtx writeQueueSize) — only
   if recording is enabled or web consumers appear.
5. **Operator action**: confirm whether
   `~/.cache/hapax-compositor/hls/stream.m3u8` has a
   consumer. If no → ship HLS-1. If yes → document
   the consumer in CLAUDE.md and skip HLS-1.

## 11. Cumulative impact estimate

If alpha ships **all of Ring 1 + Ring 2** (6 fixes,
2 PRs):

- ~2 MB/s of disk write reclaimed (HLS branch off)
- ~31 MB/s of memory bandwidth reclaimed (NV12)
- 1 NVENC slot freed (HLS encoder gone)
- LL-HLS becomes actually low-latency through
  mediamtx (RTMP-1)
- RTMP bin becomes resilient to PipeWire jitter
  and encoder stalls (RTMP-2, RTMP-3)
- HLS config no longer lies (HLS-2)

If alpha then ships **Ring 3 OBS-1** (encoder
observability):

- Five existing metric skeletons become real
- Output-side problems become alertable
- Future regression in any output stage is visible
  in Prometheus

**Combined with cam-stability rollup (drop #31)
totals**: ~900 MB/s + ~33 MB/s = **~933 MB/s** of
memory bandwidth reclaimable, 1 NVENC slot freed,
~2 MB/s disk write reclaimed, plus full
input + output observability coverage. For a system
running at ~560% CPU, that's still ~10-15% of
compositor budget plus full observability.

## 12. Cross-references

- `agents/studio_compositor/pipeline.py:128-156` —
  v4l2sink branch (YUY2 caps, single-buffer queue)
- `agents/studio_compositor/recording.py:15-122` —
  per-camera recording + HLS branch
- `agents/studio_compositor/rtmp_output.py:32-294` —
  RTMP bin (audio + video + mux)
- `agents/studio_compositor/compositor.py:648-702` —
  `toggle_livestream` (consent gate for RTMP bin)
- `agents/studio_compositor/models.py:46-63` —
  `RecordingConfig`, `HlsConfig` defaults
- `agents/studio_compositor/metrics.py:370+` —
  RTMP metric skeleton (defined, not wired)
- `/etc/mediamtx/mediamtx.yml` — relay config
  (essentially default)
- Drop #28-#30 — camera-side walk
- Drop #31 — cam-stability rollup
- Drop #14 — observability gap map (input side)
- Drop #1 — BudgetTracker (the existing publish-cost
  observability)

## 13. Open questions for alpha

1. **Is `~/.cache/hapax-compositor/hls/stream.m3u8`
   read by anyone?** Affects whether HLS-1 ships.
2. **Is per-camera recording ever expected to be
   enabled?** Affects priority of REC-1.
3. **Does any client ever consume mediamtx LL-HLS or
   WebRTC?** Affects priority of RTMP-1 and MTX-1.
4. **Is OBS configured to read NV12 or YUYV from
   `/dev/video42`?** Affects feasibility of V4L-1.

These are 4 yes/no questions worth ~30 seconds of
operator time and they determine which Ring 1/2 fixes
are worth shipping vs deferring.
