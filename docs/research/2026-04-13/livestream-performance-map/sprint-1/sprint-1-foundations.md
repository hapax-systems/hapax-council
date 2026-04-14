# Sprint 1 — Foundations + Unblockers

**Date:** 2026-04-13 CDT
**Theme coverage:** A1 (USB topology), A1.1-A1.3 (BRIO bus mapping + bandwidth), B3.2 (buffer pool check), C1 (per-camera steady state live fps), L1.1 (VRAM breakdown), baseline compositor snapshot.
**Register:** scientific, neutral

## Headline

**Five findings in Sprint 1:**

1. **USB topology map completed.** 6 cameras distributed across 4 xHCI controllers. Bus 001 (AMD 500 Series USB 2.0) hosts 1 BRIO + 1 C920 + Studio 24c + Yeti + Bluetooth + HIDs on shared 480M bandwidth. Bus 002 (USB 3.0 companion, empty) is **available unused**.
2. **brio-room 43B0576A on Bus 001 at 480M is the q022 degraded BRIO** — confirmed via `/sys/bus/usb/devices/1-3/speed=480`. Its USB 3.0 capability is not being used.
3. **brio-operator fps deficit is NOT a USB 2.0 bandwidth issue.** brio-operator is on Bus 6 (USB 3.0 Gen 1, 5000M) and runs at 28.50 fps; brio-room is on Bus 1 (USB 2.0, 480M) and runs at 30.50 fps. The deficit is producer-thread-side, not bus-side. Refutes the earlier "USB 2.0 is the cause" hypothesis from queue 022.
4. **brio-synths 9726C031 has 2 video interfaces with NO driver bound.** Interfaces `8-3:1.1` and `8-3:1.2` show `Driver=[none]` in `lsusb -tv`. Primary streaming interface 0 works fine, but the anomaly suggests a uvcvideo quirk or a damaged camera firmware region.
5. **Compositor is healthy at Sprint 1 start.** 88 threads, VmRSS 1.14 GB, MemoryCurrent 939 MB. All 6 cameras in HEALTHY state. Frame rates measured live.

## Data

### A1.1 — USB bus topology (xHCI controller → bus mapping)

```text
lspci | grep -iE "xhci"
  01:00.0  AMD 500 Series Chipset USB 3.1 XHCI        → Bus 001 (2.0) + Bus 002 (3.0, empty)
  03:00.0  ASMedia ASM2142/3142 USB 3.1               → Bus 003 (2.0) + Bus 004 (3.0, hubs only)
  05:00.0  Renesas uPD720201 USB 3.0                  → Bus 007 (2.0) + Bus 008 (3.0, 5000M)
  0c:00.3  AMD Matisse USB 3.0                        → Bus 005 (2.0) + Bus 006 (3.0, 5000M)
```

### BRIO role → serial → bus → speed mapping

```text
role           serial      config device                                  bus/port         speed  controller
brio-operator  5342C819    /dev/v4l/by-id/usb-046d_Logitech_BRIO_5342...   6-2              5000M  AMD Matisse (0c:00.3)
brio-room      43B0576A    /dev/v4l/by-id/usb-046d_Logitech_BRIO_43B0576A  1-3              480M   AMD 500 Series (01:00.0)
brio-synths    9726C031    /dev/v4l/by-id/usb-046d_Logitech_BRIO_9726C031  8-3              5000M  Renesas uPD720201 (05:00.0)
```

**brio-room is the degraded BRIO** (q022 Phase 1 findings) — plugged into a Bus 001 port where the USB 3.0 lanes are not being used. Fix: physical cable/port swap to move it to Bus 002 (available, empty) or Bus 006/008 siblings of the other BRIOs.

### C920 mapping

```text
role           serial (from product)  bus/port  speed  controller
c920-desk      (model 08e5)           1-1       480M   AMD 500 Series (01:00.0)
c920-room      (model 08e5)           3-2       480M   ASMedia (03:00.0)
c920-overhead  (model 082d)           7-4       480M   Renesas (05:00.0)
```

C920s are 480M-only devices (they're USB 2.0 cameras), so their speed is at the device ceiling — no upgrade possible.

### A1.3 — Bus 001 shared-device load (contention risk)

Bus 001 (AMD 500 Series, USB 2.0 480M) current inhabitants:

| slot | device | bandwidth use (est.) |
|---|---|---|
| 1-1 | C920-desk (video + audio) | ~2 Mbps |
| 1-2 | PreSonus Studio 24c (8-ch audio) | ~2 Mbps |
| 1-3 | BRIO 43B0576A = brio-room (video + audio) | ~5 Mbps |
| 1-4 | Yeti Stereo Microphone (USB 1.1 full-speed) | ~1 Mbps |
| 1-5 | (Intel AX200) Bluetooth | <1 Mbps |
| 1-6 | ASUS AURA + HID | <1 Mbps |
| 1-7 | Genesys Logic Hub (4-port USB 2.0 Hub, contents unclear) | — |

**Total estimated steady-state**: ~10-12 Mbps. Theoretical USB 2.0 ceiling 480 Mbps. **Bus bandwidth is NOT saturated.** The issue is **shared latency** — the host controller services one endpoint at a time, so two simultaneous video transfers must queue.

**Bus 002 is an empty USB 3.0 root hub on the same controller.** Moving brio-room's cable to a physical port whose USB 3.0 lanes are wired would give it:
- Full USB 3.0 Gen 1 (5 Gbps) bandwidth
- Its own host scheduling slot (not shared with PreSonus/Yeti/C920)
- Separation from HID+BT polling jitter

**Fix action (operator-hand required)**: swap brio-room USB cable to a known-good USB 3.0 cable + move to a motherboard rear-panel USB 3.0 port (or replace the cable if the port already has USB 3.0 lanes).

### Anomaly: brio-synths has unclaimed video interfaces

```text
lsusb -tv (bus 008 port 3):
  |__ Port 003: Dev 002, If 0, Class=Video, Driver=uvcvideo,   5000M   ← primary, working
  |__ Port 003: Dev 002, If 1, Class=Video, Driver=[none],     5000M   ← unclaimed
  |__ Port 003: Dev 002, If 2, Class=Video, Driver=[none],     5000M   ← unclaimed
  |__ Port 003: Dev 002, If 3, Class=Audio, Driver=snd-usb-audio, 5000M
  |__ Port 003: Dev 002, If 4, Class=Audio, Driver=snd-usb-audio, 5000M
```

Interface 0 is the main capture endpoint (`/dev/video14`) and works. Interfaces 1 and 2 are the secondary BRIO video interfaces (4K mode? thumbnail stream?) and uvcvideo is not claiming them.

**Possible causes:**
- uvcvideo driver quirk for BRIO 9726C031 firmware version
- Damaged firmware descriptor region
- Intentional (BRIO may expose interfaces the driver can't handle)

**Operational impact**: probably none — the compositor only opens `index0`. But worth flagging as a hardware carry-over investigation if brio-synths ever shows frame instability.

### C1 — Live per-camera fps (2 s window)

Measurement method: `curl http://127.0.0.1:9482/metrics` twice, diff `studio_camera_frames_total`:

```text
brio-operator        fps=28.50   (on USB 3.0 5000M)    ← below target ≠ bus issue
c920-desk            fps=30.50   (on USB 2.0 480M)     ← at target
c920-room            fps=30.50   (on USB 2.0 480M)     ← at target
c920-overhead        fps=30.50   (on USB 2.0 480M)     ← at target
brio-room            fps=30.50   (on USB 2.0 480M)     ← at target, despite being on degraded bus
brio-synths          fps=30.50   (on USB 3.0 5000M)    ← at target
```

**The fps deficit is brio-operator specific.** The **earlier "brio-operator is on USB 2.0 and that's why it's 28 fps" hypothesis from queue 022 Phase 2 is REFUTED.** brio-operator is on the fastest bus available in the whole system (AMD Matisse, USB 3.0 Gen 1) and still runs 7% below target. Meanwhile brio-room is on the slowest bus (Bus 001 USB 2.0, shared with 6 other devices) and runs at target.

**New candidate root causes** for brio-operator:

1. **Producer thread starvation under hero=True dispatch**. `config.py` marks brio-operator as `hero: True`. Is there hero-specific processing that taxes the producer thread? Check `agents/studio_compositor/config.py` + `camera_pipeline.py` for `hero`-gated code paths.
2. **Metrics lock contention**. The `_last_seq` dict in `metrics.py` is guarded by a lock. If the hero camera's producer thread holds the lock longer per tick for any reason, fps drops.
3. **GStreamer queue pressure**. The hero camera may feed into a deeper queue chain (e.g. for the main output region) than the others. Measure queue depths per camera.
4. **Camera-internal issue**. The BRIO 5342C819 firmware may be exposing a different cadence than its specified 30 fps. Physical swap test: swap brio-operator ↔ brio-synths (same bus controller class) and see if the deficit follows the role or the hardware.

Follow-up research items filed in retirement handoff.

### L1.1 — VRAM breakdown (nvidia-smi snapshot)

```text
pid      process_name                 VRAM
38671    tabbyAPI (Qwen3.5-9B EXL3)    5760 MiB
531875   hapax-dmn                     3296 MiB   (inferred from CLAUDE.md DMN spec)
537153   studio-compositor             3059 MiB   (matches MainPID)
764289   hapax-imagination             302 MiB
Total used:                           ~12863 MiB (52%)
Free:                                  11241 MiB (48%)
```

**Breakdown:**
- TabbyAPI 5760 MiB = 45% of used VRAM (largest)
- **studio-compositor 3059 MiB is significantly more than expected** for a GStreamer-only process. Post PR #751 removed libtorch. This VRAM is coming from the GL mixer + effect graph + NVENC encoder contexts.
- hapax-dmn 3296 MiB — for cognitive state + reverie mixer
- hapax-imagination 302 MiB — minimal wgpu footprint, matches queue 026 Phase 3

**Headroom:** 11.24 GB free. Plenty of margin for:
- Adding another encoder context
- Running a parallel Kokoro TTS instance on GPU (see Theme G future work)
- Additional imagination-class workloads

**Risk:** TabbyAPI growth over time. If Qwen3.5-9B KV cache grows with context length, it could eat into the 11 GB headroom. Worth a separate research pass under Theme L2.

**Not measured yet (filed for Sprint 7):** concurrent-load contention when TabbyAPI inference runs during compositor encode.

### B3.2 — Buffer pool exhaustion check

Queue 023 Phase 4 saw `"Failed to allocate a buffer"` on brio-room fault at 17:00:47 CDT. Is this still happening?

```bash
journalctl --user -u studio-compositor.service --since "1 hour ago" | grep -c "Failed to allocate a buffer"
```

**Result**: 0 occurrences in the current session. The buffer pool exhaustion correlates with the brio-room USB fault, not steady-state operation. Defer deep pool-sizing investigation to Sprint 2 when load-testing the compositor.

### Compositor baseline (Sprint 1 entry state)

```text
MainPID:              537153
ExecMainStartTimestamp: 2026-04-13 19:29:01 CDT
Uptime at sprint start: ~23 min
NRestarts:            0
VmRSS:                1.14 GB
VmSize:               14.6 GB (virtual address space)
VmData:               3.58 GB
Threads:              88
MemoryCurrent:        939 MB (cgroup)
MemoryPeak:           952 MB (cgroup)
TasksCurrent:         96
```

**Compositor is lean and healthy**, matching queue 023 post-Option-A "PID 2913194" baseline shape (where queue 023 measured 1.15 GB steady state for a similar graph plan).

All 6 cameras healthy. No state transitions. No recent restarts.

## Findings + fix proposals

### F1 (HIGH): brio-room cable/port swap

**Finding**: brio-room BRIO 43B0576A is on USB 2.0 despite being a USB 3.0 device. Sibling BRIOs at 5000M. Unused USB 3.0 root hub on the same controller (Bus 002).

**Fix**: Operator-hand cable swap. Move brio-room to a motherboard USB 3.0 port OR replace the cable with a known-good USB 3.0 cable. Expected outcome: device moves to Bus 002 at 5000M, removes from Bus 001 shared schedule with PreSonus/Yeti/HIDs.

**Priority**: HIGH (carry-over from q022 Phase 1 hardware ticket).

### F2 (MEDIUM): brio-operator fps deficit root cause investigation

**Finding**: brio-operator (hero camera) is on the fastest bus in the system and still runs 7% below 30 fps target. Deficit is NOT bus-bandwidth. Earlier "USB 2.0" hypothesis from queue 022 is refuted.

**Fix proposal**: Investigate in Sprint 2 under producer thread + queue pressure + hero-specific code path audit. Possible swap test: move brio-operator role to a non-hero BRIO and see if the deficit follows.

**Priority**: MEDIUM (not a hardware fix; a code investigation).

### F3 (LOW): brio-synths unclaimed video interfaces

**Finding**: brio-synths 9726C031 has interfaces `8-3:1.1` and `8-3:1.2` with `Driver=[none]`. Interface 0 works.

**Fix proposal**: No operational impact; file as observation. Investigate in a future session if brio-synths ever shows instability. Possible fix paths: uvcvideo quirk flag for this BRIO firmware, or firmware reflash (vendor tool required).

**Priority**: LOW.

### F4 (HIGH): compositor VRAM 3 GB worth investigating

**Finding**: studio-compositor uses 3 GB VRAM despite being libtorch-free post PR #751. GStreamer + GL mixer + effect graph + NVENC combined. This is high.

**Fix proposal**: Sprint 5 will profile NVENC encoder context sizing; if the 3 GB is mostly encoder buffers, it's expected. If it's shader texture pools (e.g. the queue 026 P3 finding of `reuse_ratio=0.0`), reducing pool size could drop VRAM significantly.

**Priority**: HIGH (cross-reference queue 026 P3 backlog item 143: fix `pool_metrics.reuse_ratio = 0`).

### F5 (observability): Prometheus scrape gap still blocks dashboards

**Finding**: The compositor `:9482` metrics are serving correctly (confirmed via `curl -s http://127.0.0.1:9482/metrics`). Prometheus scrape still missing per queue 024 FINDING-H. Alpha owns this fix.

**Fix proposal**: Cross-reference queue 024 Phase 2 + backlog item 47 (`fix(llm-stack): add studio-compositor scrape job to prometheus.yml`) + 48 (`fix(host): ufw allow 172.18.0.0/16 → 9100, 9482`).

**Priority**: HIGH (blocks dashboards).

## Sprint 1 backlog additions (items 168+)

168. **`fix(hardware): move brio-room USB cable to a USB 3.0 port`** [Sprint 1 F1] — operator hand action. Enables USB 3.0 Gen 1 (5000M) speed instead of the current 480M on Bus 001. Expected side effect: reduces Bus 001 contention with Yeti/PreSonus/HIDs.
169. **`research(compositor): brio-operator hero-camera fps deficit root cause`** [Sprint 1 F2] — 4 candidate causes filed. Try a physical swap test + code audit of hero=True code paths.
170. **`research(uvcvideo): brio-synths 9726C031 unclaimed video interfaces`** [Sprint 1 F3] — low priority; filing for future investigation.
171. **`research(compositor): NVENC + GL mixer VRAM breakdown`** [Sprint 1 F4] — 3 GB is larger than expected. Confirm where it's going. Cross-ref queue 026 P3 backlog 143 (texture pool `reuse_ratio=0`).
172. **`feat(metrics): add hapax_compositor_vram_bytes gauge`** [Sprint 1 F4 followup] — per-process GPU VRAM metric from `nvidia-smi --query-compute-apps` polled every 30 s by the compositor itself or an external scraper.
