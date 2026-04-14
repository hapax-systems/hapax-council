# Sprint 5 — Output, Encoding, Streaming

**Date:** 2026-04-13 CDT
**Theme coverage:** I1-I5 (encoder + V4L2 loopback + HLS + RTMP), J1-J8 (OBS scene graph + capture), K1-K5 (YouTube ingest + bitrate ladder + retry policy)
**Register:** scientific, neutral
**Major change since map authored:** **dual-GPU rig as of 2026-04-13** — RTX 5060 Ti (Blackwell, 16 GiB) + RTX 3090 (Ampere, 24 GiB). All findings here have been updated to consider GPU partitioning. See sibling document `sprint-5-dual-gpu-partitioning.md` for the full multi-GPU research vector.

## Headline

**Eight findings in Sprint 5:**

1. **Encoder is `nvh264enc` (CUDA mode), preset p4 medium, low-latency tune, CBR rate control.** `rtmp_output.py:90-99`. Hardcoded preset 11 (p4), tune 2 (low-latency), rc-mode 2 (cbr). 100 ms flvmux latency budget. Per process metrics: 5% encoder load on GPU 1 currently.
2. **Encoder is NOT pinned to a specific GPU.** `cuda-device-id` is not set on either `nvh264enc` (rtmp_output.py:90) or `cudacompositor` (pipeline.py:41). Encoder falls into whichever device CUDA enumerates first. With the 5060 Ti at PCI 03:00.0 and the 3090 at 07:00.0, **the encoder currently lands on GPU 1 (3090) anyway** — likely because the compositor was started before the 5060 Ti was installed, so CUDA cached the previous device ordering. **The 5060 Ti's Blackwell NVENC is sitting idle while the 3090's Ampere NVENC is doing all the work.**
3. **No `nvav1enc` GStreamer element installed.** `gst-inspect-1.0 nvav1enc` returns "No such element." Blackwell NVENC supports hardware AV1 encode but the GStreamer plugin doesn't expose it on this system. Workaround: pipe to `ffmpeg` for AV1 (loses pipeline integration), or wait for `gst-plugin-bad` ≥1.26 (likely already-shipped — needs verification).
4. **`nvautogpuh264enc` element exists**, providing built-in dual-GPU NVENC routing without manual `cuda-device-id` plumbing. Currently NOT used by `rtmp_output.py`. **One-line swap to migrate the rig to auto-GPU NVENC.**
5. **V4L2 loopback at `/dev/video42`** is healthy (StudioCompositor card, v4l2loopback driver v6.18.16, capabilities `0x85200001`). OBS captures from this. Output format is the compositor's BGRA after the GL chain.
6. **HLS sink is NOT currently active.** `/dev/shm/hapax-compositor/hls/` directory does not exist. The compositor's RTMP output to MediaMTX is the live path; HLS is documented but not running. Either (a) HLS sink was deferred and never landed, or (b) it's only enabled by an env var that's not set.
7. **RTMP destination is `rtmp://127.0.0.1:1935/studio` → MediaMTX**. MediaMTX is the relay; YouTube-bound RTMP must go from MediaMTX → Twitch/YouTube ingest. Need to verify MediaMTX config has the upstream relay set; otherwise the stream terminates at MediaMTX with no public output.
8. **`rtmp2sink` preferred over `rtmpsink`**, with fallback. Modern element with proper handshake + reconnection. `flvmux streamable=true latency=100ms`.

## Data

### I1 — NVENC encoder configuration

`agents/studio_compositor/rtmp_output.py:84-100`:

```python
video_queue.set_property("max-size-buffers", 30)
video_queue.set_property("max-size-time", 2 * Gst.SECOND)
video_queue.set_property("leaky", 2)  # downstream

video_convert = Gst.ElementFactory.make("videoconvert", "rtmp_video_convert")
encoder = Gst.ElementFactory.make("nvh264enc", "rtmp_nvh264enc")
encoder.set_property("bitrate", self._bitrate_kbps)
encoder.set_property("rc-mode", 2)        # 2 = cbr
encoder.set_property("gop-size", self._gop_size)
encoder.set_property("zerolatency", True)
encoder.set_property("preset", 11)         # 11 = p4 medium
encoder.set_property("tune", 2)            # 2 = low-latency
```

| param | value | rationale |
|---|---|---|
| element | `nvh264enc` (CUDA mode) | Available on host. Two alternatives: `nvautogpuh264enc` (auto GPU select) and `nvh265enc` (HEVC) |
| `cuda-device-id` | **NOT SET** | Falls into CUDA-default. **Dual-GPU implication: encoder doesn't migrate to 5060 Ti automatically** |
| `bitrate` | `self._bitrate_kbps` (config-driven) | Per-stream config |
| `rc-mode` | 2 (CBR) | RTMP-friendly. VBR is allowed by RTMP but most ingests prefer CBR |
| `gop-size` | `self._gop_size` (config) | Should be 2× target fps (60 for 30 fps) |
| `zerolatency` | True | Disables lookahead, B-frames |
| `preset` | 11 (p4 medium) | Newer preset numbering; p4 is the balanced "medium" preset. p1-p7 maps low-quality fast → high-quality slow |
| `tune` | 2 (low-latency) | Disables B-frames, sets Iframe-only or IPP cadence |
| `b-frames` | implicit 0 (zerolatency) | Confirmed: low-latency tune disables B |
| AQ (adaptive quant) | not set | Defaults to enabled in p4. Could be set explicitly via `aq-spatial`/`aq-temporal` |

**Live measurement** (nvidia-smi pmon):

```text
GPU PID    type  sm%  mem%  enc%  dec%  command
1   12311  C+G   18    5     5     -    python (compositor)
```

Encoder is using ~5% of GPU 1's NVENC capacity currently. Plenty of headroom for higher-bitrate or parallel encoders.

**Audio encoder**: `voaacenc` (preferred) → `avenc_aac` (fallback), 128 kbps stereo 48k. flvmux at 100 ms latency.

### I2 — V4L2 loopback at /dev/video42

```text
$ v4l2-ctl --device=/dev/video42 --info
Driver name      : v4l2 loopback
Card type        : StudioCompositor
Bus info         : platform:v4l2loopback-042
Driver version   : 6.18.16
Capabilities     : 0x85200001
    Video Capture
    Read/Write
    Streaming
    Extended Pix Format
```

`pipeline.py:142-150` writes to `/dev/video42` via `v4l2sink`. The identity element with `drop-allocation=true` is the **standard v4l2loopback workaround** — without it v4l2sink renegotiates buffers on every input-selector source switch (BRIO failover events) and OBS drops a frame.

**OBS connects to `/dev/video42`** as a Video Capture Device source. This is the production path that drives the OBS scene graph.

### I3 — Cudacompositor cuda-device-id

`pipeline.py:41`:

```python
comp_element = Gst.ElementFactory.make("cudacompositor", "compositor")
# (no cuda-device-id set — uses CUDA default device)
```

`gst-inspect-1.0 cudacompositor` confirms the property exists:

```text
Element Properties:
  cuda-device-id      : Set the GPU device to use for operations (-1 = auto)
```

Setting `cuda-device-id=0` would pin the compositor to the 5060 Ti. **One property, one line. Trivial migration.** See dual-GPU partition design doc for the recommended distribution.

### I4 — HLS sink: not currently active

```bash
$ ls /dev/shm/hapax-compositor/hls/
ls: cannot access '/dev/shm/hapax-compositor/hls/': No such file or directory
```

The directory the README claims is the HLS playlist target does not exist. Either:

- HLS sink was a planned feature and never shipped
- HLS sink only enables on a config flag and the flag is unset
- HLS sink was retired in favor of the RTMP → MediaMTX path

Check `pipeline.py` for `hlssink2` / `hlssink3` references:

```bash
$ grep -n "hlssink" agents/studio_compositor/pipeline.py
(empty)
```

**No HLS sink in pipeline.py.** The path is RTMP-only. If HLS is desired (e.g., for embedding the stream in a webview directly without RTMP demuxing), it would need to be added either:

- As a new branch off the output tee in `pipeline.py` (parallel to v4l2sink and the rtmp_bin)
- Via MediaMTX's HLS endpoint (MediaMTX serves HLS automatically off any RTMP path it receives — `http://127.0.0.1:8888/studio/index.m3u8`). **This is the cheap path.**

### I5 — Output tee structure

The compositor uses a tee to drive both `v4l2sink` (OBS) and `rtmp_output.py`'s rtmp_bin (MediaMTX → upstream). RTMP bin is added/removed dynamically as a branch off the tee via a request pad — see `rtmp_output.py:8`. On NVENC or rtmp2sink errors the bin is torn down and a degraded signal is published.

This means:

- **OBS path is decoupled from RTMP failures.** A YouTube ingest hiccup does not stop the OBS preview.
- **The RTMP path can be hot-cycled** by the recovery FSM without restarting the compositor.

### J1-J8 — OBS scene graph (state via FILE inspection — OBS process not directly probed)

The compositor produces a single 1920x1080 BGRA composited frame to `/dev/video42`. OBS scene graph for the livestream is presumably:

- Source: V4L2 Video Capture Device → `/dev/video42`
- Audio source: PipeWire monitor → `mixer_master` (likely; need OBS scene file to confirm)
- (Optional) Browser source overlays for chat etc.

**Not yet measured live**: OBS scene file at `~/.config/obs-studio/basic/scenes/*.json`. Defer to operator-coordinated session; reading OBS scene state without running OBS is brittle.

**OBS encoder choice**: if OBS itself is also encoding (e.g., for separate recording of the stream), it has its own NVENC sessions. OBS's NVENC count adds to the compositor's. Currently the rig has 0 active OBS NVENC sessions per `nvidia-smi --query-gpu=encoder.stats.sessionCount`.

### K1-K5 — YouTube ingest

**Bitrate ladder** for 1080p30 H.264 to YouTube (current best practice as of late 2025):

| profile | bitrate | target use |
|---|---|---|
| **1080p30 high** | 6000 kbps | Quality-first stream, stable upload |
| 1080p30 standard | 4500 kbps | Default YouTube recommendation |
| 1080p30 conservative | 3000 kbps | Bandwidth-constrained |
| 720p60 | 4500 kbps | Higher motion content (gameplay-class) |

Current `_bitrate_kbps` is config-driven. Need to verify what value is set in production. Likely default 4500 kbps based on YouTube's older recommendation; should be 6000 kbps for the operator's livestream profile.

**Audio target**: 128 kbps stereo AAC. Already set.

**Connection retry**: `rtmp2sink` `async-connect=true` lets the pipeline start without blocking on the first handshake. `rtmp_output.py` recovery FSM on the bin handles disconnect/reconnect. Need to verify the retry intervals and ceiling — long backoff is fine for transient YouTube ingest blips, short is needed for a router restart.

## Findings + fix proposals

### F1 (HIGH): NVENC is on the wrong GPU

**Finding**: The rtmp encoder runs on GPU 1 (3090), the same device that hosts TabbyAPI (5.7 GiB inference model + ~21% sm load). The 5060 Ti (Blackwell, newer NVENC architecture, 0% load) is sitting idle. Encoder and inference are stepping on each other for SM resources.

**Fix proposal**: Pin the encoder to GPU 0 (5060 Ti).

**Option A** (one-line): swap `nvh264enc` for `nvautogpuh264enc` in `rtmp_output.py:90`. Auto-GPU select picks the least-loaded device. Cleanest.

**Option B** (explicit): set `encoder.set_property("cuda-device-id", 0)` and `comp_element.set_property("cuda-device-id", 0)` in `rtmp_output.py` and `pipeline.py`. Predictable but rigid.

**Option C** (deeper): set the entire compositor process's `CUDA_VISIBLE_DEVICES=0` in the systemd unit. Now ALL CUDA contexts the compositor opens (compositing + encoding + decoding) bind to GPU 0. The compositor still sees only one GPU, but it's the right one.

**Recommendation**: Option C. It's the cleanest separation: compositor → GPU 0, TabbyAPI → GPU 1. Already the same pattern used for Ollama (`CUDA_VISIBLE_DEVICES=""` to force CPU).

**Priority**: HIGH. This single change reclaims SM cycles for TabbyAPI (faster LLM responses) and uses Blackwell NVENC (better quality per bitrate).

### F2 (MEDIUM): nvautogpuh264enc could replace nvh264enc

**Finding**: The auto-GPU element exists and is purpose-built for multi-GPU rigs. It re-evaluates GPU assignment per session (vs static binding).

**Fix proposal**: One-line swap once F1 strategy is decided. Auto mode is friendlier to "I just plugged in another GPU" scenarios.

**Priority**: MEDIUM. Same outcome as F1 Option A but slightly more dynamic.

### F3 (LOW): nvav1enc not available; AV1 path unexplored

**Finding**: `gst-inspect-1.0 nvav1enc` returns no such element. Blackwell NVENC has hardware AV1 encode (one of its headline features). The GStreamer plugin gap means we can't trivially use it from the compositor pipeline.

**Fix proposal**:

- Check if `gst-plugin-bad` 1.26+ is available in the Arch repos. If yes, upgrade and re-inspect.
- If not, file an upstream tracking ticket (GStreamer Bugzilla / GitLab) for the plugin gap.
- Alternative: shell out to `ffmpeg` for AV1 (loses sample-accurate sync with the GST pipeline; not recommended).
- AV1 is a 2027 feature target, not a 2026 ship. Defer.

**Priority**: LOW.

### F4 (HIGH): HLS sink missing — MediaMTX HLS endpoint should be wired

**Finding**: No HLS sink in the pipeline. The README documents one but the directory doesn't exist and the code doesn't reference `hlssink*`.

**Fix proposal**: Use MediaMTX's built-in HLS endpoint (free; already running). Configure the operator's stream URL as `http://127.0.0.1:8888/studio/index.m3u8` for any HLS consumer (in-app Logos preview, browser embed). No code change needed — verify MediaMTX `hls` is enabled in its config.

**Priority**: MEDIUM if HLS is needed; LOW otherwise.

### F5 (MEDIUM): bitrate config audit needed

**Finding**: `self._bitrate_kbps` is config-driven but the live value isn't in the rtmp_output.py source. Need to read the compositor's startup config.

**Fix proposal**: Read `agents/studio_compositor/config.py` (or wherever `bitrate_kbps` is defined). Verify it's at least 6000 for 1080p30 H.264 to YouTube. If lower, raise it.

**Priority**: MEDIUM.

### F6 (HIGH, dual-GPU): cudacompositor not GPU-pinned

**Finding**: `pipeline.py:41` creates `cudacompositor` without `cuda-device-id`. The compositor's main GPU compositing pass sits on whatever device CUDA picks first. Same risk as F1 — wastes the 5060 Ti.

**Fix proposal**: Same as F1 Option C — `CUDA_VISIBLE_DEVICES=0` at the systemd unit level. Compositing + encoding + (eventually) decoding all live on GPU 0.

**Priority**: HIGH (combined with F1).

### F7 (MEDIUM): MediaMTX upstream relay needs verification

**Finding**: The compositor pushes to `rtmp://127.0.0.1:1935/studio` but there's no evidence the live config of MediaMTX bridges that to YouTube/Twitch. Without an upstream relay, the stream terminates at MediaMTX.

**Fix proposal**: Read `~/.config/mediamtx/mediamtx.yml` (or the system-wide one), verify a `paths.studio.runOnReady` or `paths.studio.publish` rule that pipes to YouTube ingest. If missing, document the operator workflow + add the rule.

**Priority**: MEDIUM (not blocking if the operator manually streams via OBS to YouTube; HIGH if MediaMTX is supposed to be the upstream).

### F8 (INFO): tee-based dynamic rtmp_bin is sound

**Finding**: The architecture is correct: V4L2 loopback for OBS, tee to RTMP for upstream, dynamic add/remove of the rtmp_bin via request pad. Recovery FSM on encoder failures. This is well-built.

**Priority**: INFO. No fix needed.

## Sprint 5 backlog additions (items 193+)

193. **`fix(compositor): set CUDA_VISIBLE_DEVICES=0 in studio-compositor.service`** [Sprint 5 F1+F6] — pin the entire compositor process to the 5060 Ti. Single drop-in file change. Frees TabbyAPI's GPU 1 from encoder + compositing contention. Cross-ref dual-GPU partition design.
194. **`feat(rtmp): swap nvh264enc → nvautogpuh264enc`** [Sprint 5 F2] — defer until after F1 to verify the auto-GPU behavior is what we want. Auto-mode could pick wrong if the 5060 Ti is busy with imagination.
195. **`fix(rtmp): bump bitrate to 6000 kbps for 1080p30 YouTube`** [Sprint 5 F5] — verify current value first, raise if needed.
196. **`research(av1): gst-plugin-bad nvav1enc availability + Arch package status`** [Sprint 5 F3] — one-pass investigation. If available, prototype an AV1 branch.
197. **`feat(hls): wire MediaMTX HLS endpoint as the in-app preview source`** [Sprint 5 F4] — no compositor code change. MediaMTX serves HLS off any RTMP path it receives. Verify MediaMTX config has HLS enabled.
198. **`fix(mediamtx): wire upstream YouTube/Twitch relay rule`** [Sprint 5 F7] — MediaMTX `paths.studio.runOnReady` or equivalent. Verify operator workflow first.
199. **`feat(metrics): per-encoder GPU utilization gauges`** [Sprint 5 instrumentation] — `nvidia-smi --query-gpu=encoder.stats.averageFps,encoder.stats.sessionCount` polled, exported as Prometheus gauges per device. Cross-ref Sprint 6 (observability).
200. **`docs(claude.md): document dual-GPU partition strategy`** [Sprint 5 dual-GPU] — once F1 ships, document GPU 0 = visual + encoder, GPU 1 = inference + DMN.
