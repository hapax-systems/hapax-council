# Garage Door Open — Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Go live on YouTube tonight — compositor video + studio audio via OBS.

**Architecture:** GStreamer compositor (30fps, 1920x1080, 28 shader presets) → v4l2 virtual camera → OBS (V4L2 capture + PipeWire audio) → NVENC H.264 → RTMP → YouTube Live.

**Tech Stack:** GStreamer, OBS Studio, PipeWire, NVENC, YouTube Live RTMP

---

## File Structure

| File | Change | Purpose |
|------|--------|---------|
| `agents/studio_compositor/models.py:73` | Modify | framerate 10→30 |
| `agents/studio_compositor/smooth_delay.py:35` | Modify | smooth delay fps 10→30 |
| OBS profile directory (user config) | Create | NVENC, bitrate, audio settings |
| OBS scene collection (user config) | Create | V4L2 + PipeWire audio sources |

Snapshot branches (`snapshots.py:27,93`) stay at 10fps — they serve perception, not streaming.

---

### Task 1: Bump compositor framerate to 30fps

**Files:**
- Modify: `agents/studio_compositor/models.py:73`
- Modify: `agents/studio_compositor/smooth_delay.py:35`

- [ ] **Step 1: Change framerate in compositor config**

In `agents/studio_compositor/models.py`, line 73, change:
```python
framerate: int = 10  # was 30 — no consumer needs >10fps. Saves ~67% compositor CPU.
```
to:
```python
framerate: int = 30  # 30fps for live streaming output
```

- [ ] **Step 2: Update smooth delay fps to match**

In `agents/studio_compositor/smooth_delay.py`, line 35, change:
```python
smooth_delay.set_property("fps", 10)  # must match pipeline framerate
```
to:
```python
smooth_delay.set_property("fps", 30)  # must match pipeline framerate
```

- [ ] **Step 3: Restart compositor and verify**

```bash
systemctl --user restart studio-compositor
sleep 15
systemctl --user status studio-compositor --no-pager | head -15
v4l2-ctl -d /dev/video42 --all 2>/dev/null | grep -E "Width|Height"
```

Expected: compositor active, v4l2 showing 1920x1080.

- [ ] **Step 4: Commit**

```bash
git add agents/studio_compositor/models.py agents/studio_compositor/smooth_delay.py
git commit -m "perf: compositor framerate 10→30fps for live streaming"
git push origin main
```

---

### Task 2: Configure OBS (profile + scene + stream key)

OBS is already installed but unconfigured (`FirstRun=true`). Since OBS scene JSON is fragile and OBS generates UUIDs on first launch, the most reliable approach is to launch OBS and configure via GUI. This takes ~2 minutes.

- [ ] **Step 1: Launch OBS**

Operator launches OBS manually from application launcher. (Do NOT launch from this terminal — `no-unsolicited-windows` rule.)

- [ ] **Step 2: Create profile**

1. Profile → New → name "StudioLive"
2. Settings → Output → Output Mode: Advanced
3. Settings → Output → Streaming tab:
   - Encoder: NVIDIA NVENC H.264 (new)
   - Rate Control: CBR
   - Bitrate: 6000 kbps
   - Keyframe Interval: 2s
   - Preset: Quality (p5)
   - Profile: high
   - Look-ahead: unchecked
   - B-frames: 2
4. Settings → Output → Audio tab:
   - Audio Bitrate: 160 kbps
5. Settings → Video:
   - Base Resolution: 1920x1080
   - Output Resolution: 1920x1080
   - FPS: 30
6. Settings → Audio:
   - Sample Rate: 48 kHz
   - Channels: Stereo
   - Disable all Global Audio Devices (we use per-source capture)
7. Settings → Advanced:
   - Color Format: NV12
   - Color Space: Rec. 709
   - Color Range: Partial
8. Apply + OK

- [ ] **Step 3: Create scene and sources**

1. Scene Collection → New → "StudioLive"
2. Scenes panel: rename default scene to "Studio Live"
3. Sources → + → **Video Capture Device (V4L2)**
   - Name: "Compositor"
   - Device: `StudioCompositor` (this is `/dev/video42`)
   - Resolution: 1920x1080
   - Leave all other defaults
4. Sources → + → **Audio Input Capture (PipeWire)**
   - Name: "Music (L-12)"
   - Device: select `mixer_master`
5. Sources → + → **Audio Input Capture (PipeWire)**
   - Name: "Voice (Yeti)"
   - Device: select `echo_cancel_source`
6. Disable Desktop Audio in Settings → Audio (set to Disabled)

- [ ] **Step 4: Set audio levels**

In OBS Audio Mixer (bottom panel):
1. **Music (L-12):** Drag slider to about -6dB (~50%). Music should be present but not overpower voice.
2. **Voice (Yeti):** Leave at 0dB (100%).
3. Play a beat + speak → watch meters:
   - Music peaks: -12dB to -6dB
   - Voice peaks: -6dB to -3dB
   - Combined never hits 0dB

- [ ] **Step 5: Configure YouTube stream key**

1. Go to https://studio.youtube.com → Create → Go Live → Stream
2. Set title, category (Science & Technology), enable DVR, enable chat
3. Set visibility to **Unlisted** (for testing)
4. Copy Stream Key
5. In OBS: Settings → Stream → Service: YouTube - RTMPS → paste Stream Key

---

### Task 3: Test stream (unlisted)

- [ ] **Step 1: Start test stream**

1. In OBS, click **Start Streaming**
2. Wait 15 seconds for YouTube to receive the feed
3. In YouTube Studio, verify:
   - Video preview shows compositor output (cameras + shader effects)
   - Audio active (speak and play music to confirm both sources)
   - Stream health: "Excellent" or "Good"
   - Resolution: 1920x1080
   - Bitrate: ~6000 kbps

- [ ] **Step 2: Verify effect switching works on stream**

While test stream is running:
```bash
# Switch to a dramatic preset
curl -s -X POST http://localhost:8051/api/studio/effect/select \
  -H 'Content-Type: application/json' -d '{"preset":"halftone_preset"}'
```
Watch YouTube preview — halftone effect should appear within ~1-2 seconds (200ms switch + YouTube ingest delay).

```bash
# Switch back to clean
curl -s -X POST http://localhost:8051/api/studio/effect/select \
  -H 'Content-Type: application/json' -d '{"preset":"clean"}'
```

- [ ] **Step 3: Check GPU load**

```bash
nvidia-smi --query-gpu=utilization.gpu,utilization.encoder,memory.used --format=csv,noheader
```

Expected: encoder utilization 5-15%, memory still within budget (~18-19GB of 24GB).

- [ ] **Step 4: Stop test stream**

1. Click "Stop Streaming" in OBS
2. Verify test VOD appears in YouTube Studio (takes ~1 minute)
3. Spot-check the VOD: video quality, audio balance, effect visibility

---

### Task 4: Go live (public)

- [ ] **Step 1: Pre-flight checklist**

Verify all of these before going public:

- [ ] Compositor running at 30fps
- [ ] OBS video feed showing cameras + effects
- [ ] OBS audio meters active for both Music and Voice
- [ ] YouTube stream key configured
- [ ] Test stream completed successfully
- [ ] No sensitive content visible on cameras (employer work, PII)
- [ ] Desired shader preset active

- [ ] **Step 2: Set visibility to Public**

In YouTube Studio: edit stream settings → Visibility → **Public**

- [ ] **Step 3: Go live**

In OBS: click **Start Streaming**.

You are live.
