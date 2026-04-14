# Sprint 5b — Dual-GPU Partition Design

**Date:** 2026-04-13 CDT
**Trigger event:** Operator installed an RTX 5060 Ti alongside the existing 3090 — the rig is now dual-GPU as of today.
**Theme coverage:** L1.2 (dual-GPU VRAM partition), L1.3 (per-GPU encoder allocation), L2.1 (compute isolation), L4.1 (PCIe bandwidth), C5.1 (camera decode partitioning), all of theme **L (GPU budget)** re-derived under the new topology
**Register:** scientific, neutral

> **Note on card identity**: nvidia-smi reports `NVIDIA GeForce RTX 3090` for GPU 1 (24 GiB, Ampere sm_86). The operator referenced "4090" in conversation. Throughout this document GPUs are referenced by index (GPU 0, GPU 1) and by what nvidia-smi reports. If the older card is in fact a 4090, swap "Ampere" → "Ada Lovelace", swap sm_86 → sm_89, and re-validate the NVENC generation. The partition strategy holds either way.

## Headline

**Eight findings on the dual-GPU rig:**

1. **GPU 0 = RTX 5060 Ti (Blackwell, sm_120, 16 GiB, memory at 13.8 GHz).** PCIe 03:00.0. Currently **39 MiB used, 99% idle**. Newer NVENC architecture with hardware AV1 encode (subject to GStreamer plugin support — see Sprint 5 F3). Memory clock 13801 MHz / 14001 MHz max. Graphics clock 1792 MHz / 3210 MHz max. 13W of 180W power draw at idle.
2. **GPU 1 = RTX 3090 (Ampere, sm_86, 24 GiB GDDR6X at 9.5 GHz).** PCIe 07:00.0. Currently **12830 MiB used (52%)**. Hosts EVERY current GPU workload: TabbyAPI (5696 MiB), studio-compositor (3071 MiB), hapax-dmn (3360 MiB), hapax-imagination (302 MiB), Hyprland + Xwayland + WebKit display surfaces (~220 MiB). 201W of 420W power draw, 65% SM utilization. **This is the current bottleneck.**
3. **The 5060 Ti is being completely wasted.** 0% encoder, 0% decoder, 2% SM, 13W of 180W. The compositor's current NVENC sessions (5% on GPU 1) could move to GPU 0 immediately with `cuda-device-id=0` or `nvautogpuh264enc`.
4. **No code path currently honors GPU index.** `nvh264enc`, `cudacompositor`, the wgpu adapter for `hapax-imagination`, and TabbyAPI all rely on default-CUDA-device or `CUDA_VISIBLE_DEVICES`. There is **zero per-process GPU pinning** in the systemd unit files. This is the lever to pull.
5. **Driver 590.48.01 supports both architectures.** Pinned because of the 595.x crash regression (`feedback_nvidia_595_crash.md`). 590 is what's running; both Blackwell and Ampere are supported. CUDA 13.1.
6. **PCIe topology** is split across two host bridges (03:00.0 vs 07:00.0). Different bandwidth (PCIe gen, link width unverified). Camera USB hubs are all on different PCI devices (0c:00.3 AMD Matisse, 01:00.0 AMD 500 Series, 03:00.0 ASMedia, 05:00.0 Renesas) — none of the BRIO USB controllers shares a root complex with either GPU. Cross-host transfer is fine (PCIe spec) but it's a topological detail. Current 1920x1080 BGRA = 8.3 MB/frame at 30 fps = 250 MB/s per camera, well under PCIe 4.0 x16 (~32 GB/s).
7. **Display surface allocation** currently anchors Hyprland to GPU 1. Moving display to GPU 0 (5060 Ti) would let GPU 1 become a pure compute device. Requires Hyprland config + DisplayPort cable swap (DP from 5060 Ti to monitor).
8. **NVENC session count limit**: NVIDIA consumer cards historically cap NVENC sessions at 3-5 (driver-enforced). Blackwell 5060 Ti likely has the same limit but per-card. **Two cards → 6-10 concurrent encoder sessions across the rig.** This unlocks the parallel encoder design (separate OBS encoder + separate RTMP encoder + separate recording encoder).

## Current GPU topology

```text
$ nvidia-smi --query-gpu=index,name,memory.total,memory.used,driver_version,compute_cap,pci.bus_id --format=csv
index, name,                               total,    used,    driver,    cc,   bus_id
0,     NVIDIA GeForce RTX 5060 Ti,         16311 MiB, 39 MiB, 590.48.01, 12.0, 00000000:03:00.0
1,     NVIDIA GeForce RTX 3090,            24576 MiB, 12830 MiB, 590.48.01, 8.6, 00000000:07:00.0
```

```text
$ nvidia-smi pmon -c 1
GPU PID    type  sm%  mem%  enc%  dec%  command
0   61519  G     0    0     -     -     WebKitWebProcess         (Tauri webview, 25 MiB)
1   1488   C     21   7     -     -     python3                  (TabbyAPI, 5696 MiB)
1   3165   G     -    -     -     -     Hyprland                 (151 MiB)
1   3722   G     -    -     -     -     Xwayland                 (6 MiB)
1   4288   G     -    -     -     -     hyprpaper                (4 MiB)
1   7603   C     -    -     -     -     python                   (hapax-dmn, 3360 MiB)
1   12311  C+G   18   5     5     -     python                   (studio-compositor, 3071 MiB, NVENC running)
1   61152  C+G   -    -     -     -     hapax-imagination        (302 MiB)
1   61205  G     -    -     -     -     hapax-logos              (4 MiB)
```

**Total GPU 1 load**: 12.83 GiB / 24.58 GiB (52%), 65% SM utilization, 201 W of 420 W power.
**Total GPU 0 load**: 39 MiB / 16.31 GiB (0.2%), 2% SM utilization, 13 W of 180 W power.

## Workload-to-GPU assignment matrix

| workload | currently on | should move to | rationale | effort |
|---|---|---|---|---|
| **TabbyAPI** (Qwen3.5-9B EXL3 inference) | GPU 1 | **stay GPU 1** | 24 GiB headroom for KV cache + larger models. Ampere is fine for inference. | none |
| **studio-compositor** (cudacompositor + nvh264enc) | GPU 1 | **GPU 0** | Blackwell NVENC is newer, encoder cycles don't compete with TabbyAPI inference, 16 GiB is plenty for compositor's 3 GiB | drop-in: `CUDA_VISIBLE_DEVICES=0` in unit |
| **hapax-imagination** (wgpu Reverie pipeline) | GPU 1 | **GPU 0** | Visual chain belongs on the visual GPU. wgpu honors `WGPU_ADAPTER_NAME` or DXVK_HUD-style env vars. Frees GPU 1 of 302 MiB + visual SM | drop-in: env var in unit |
| **hapax-dmn** (cognitive substrate, 3360 MiB) | GPU 1 | **stay GPU 1 OR move to GPU 0** | Depends on whether DMN's GPU usage is inference (LLM-adjacent → GPU 1) or visual perception of frames (→ GPU 0). Need to check what the 3.3 GiB is | needs investigation |
| **Hyprland + Xwayland + hyprpaper** (display) | GPU 1 | **GPU 0** | Display compositor on the encoder GPU. 5060 Ti has DP outputs. Frees GPU 1 of ~160 MiB and removes display interrupt jitter from the compute card | physical: cable swap + Hyprland config |
| **WebKit Tauri webview** (hapax-logos) | GPU 0 (already!) | GPU 0 | Already correct — likely because WebKitGTK uses the display GPU and Hyprland's wlr-output happened to land it there. Confirm. | none |
| **OBS NVENC** (when active) | unknown | **GPU 0** | Same NVENC pool as compositor — both should be on Blackwell | OBS config: encoder = "NVENC H.264 (GPU 0)" |
| **YouTube ffmpeg decoders** (3× youtube-audio) | currently CPU-only | optional GPU 0 | Video decode on Blackwell NVDEC. CPU is fine for audio-only streams; if video frames are needed (album art, sierpinski feedback texture), move to GPU 0 | env var: `-hwaccel cuda -hwaccel_device 0` |

## Per-process GPU pinning mechanisms

### CUDA processes (CUDA_VISIBLE_DEVICES)

The cleanest, most universal mechanism. Set in the systemd unit file:

```ini
# studio-compositor.service drop-in
[Service]
Environment="CUDA_VISIBLE_DEVICES=0"
```

The process sees only GPU 0 (the 5060 Ti). All CUDA contexts the compositor opens (cudacompositor, nvh264enc, nvjpegenc) bind to GPU 0. From the compositor's perspective, there is one GPU and it's the right one. **Zero code changes needed.** Same pattern Ollama already uses (`CUDA_VISIBLE_DEVICES=""` to force CPU).

### TabbyAPI

```ini
# tabbyapi.service drop-in
[Service]
Environment="CUDA_VISIBLE_DEVICES=1"
```

Pin TabbyAPI explicitly to GPU 1. Belt and suspenders. TabbyAPI sees only the 3090.

### wgpu processes (hapax-imagination, hapax-reverie)

wgpu doesn't honor `CUDA_VISIBLE_DEVICES` (different toolkit), but it does honor:

```ini
[Service]
Environment="WGPU_ADAPTER_NAME=NVIDIA GeForce RTX 5060 Ti"
# or
Environment="WGPU_BACKEND=vulkan"
Environment="VK_DEVICE_SELECT=10de:2c05"
```

`WGPU_ADAPTER_NAME` is a substring match. `5060` would suffice. **Verify** the env var name with the wgpu version in `Cargo.toml`; older versions used `WGPU_POWER_PREFERENCE`.

Alternative (more robust): set `__NV_PRIME_RENDER_OFFLOAD=1` — NVIDIA's PRIME render offload variable.

### ffmpeg subprocesses (youtube-audio)

```bash
ffmpeg -hwaccel cuda -hwaccel_device 0 -i <url> ...
```

The `-hwaccel_device` flag selects the CUDA device by index. Add to `audio_control.py`'s subprocess args (if/when video decode is needed).

### OBS Studio

OBS exposes the encoder GPU in Settings → Output → Streaming → Encoder. The list of NVENC encoders includes `NVENC H.264 (#0)` and `NVENC H.264 (#1)` per GPU. **Manual operator setting** — no scriptable env var.

### Display surface (Hyprland)

```text
env = WLR_DRM_DEVICES,/dev/dri/card1
```

`/dev/dri/cardN` enumeration depends on PCI order. Likely:

```text
$ ls -l /dev/dri/by-path/
pci-0000:03:00.0-card → ../card1   # 5060 Ti
pci-0000:07:00.0-card → ../card0   # 3090
```

Verify before editing. After cable swap to the 5060 Ti's DisplayPort, set `WLR_DRM_DEVICES` to the 5060 Ti DRM card and restart Hyprland.

## Power, thermal, and PCIe topology

### Power budget

| GPU | TDP | current draw | headroom |
|---|---|---|---|
| 5060 Ti (GPU 0) | 180 W | 13 W (idle) | 167 W |
| 3090 (GPU 1) | 420 W | 201 W (load) | 219 W |
| **combined max** | **600 W** | **214 W** | — |

PSU rating must support 600 W of GPU draw plus CPU + RAM + USB devices + storage. Need to verify the PSU spec. **Recommended minimum: 1000 W 80+ Gold.** Operator should confirm PSU can sustain the combined load under stress (compositor encoding + TabbyAPI inference + reverie shaders all simultaneously hot).

**Sprint 7 polish item**: stress test under combined load and watch for power throttling on either card (`nvidia-smi --query-gpu=clocks_throttle_reasons.hw_power_brake_slowdown` should remain 0 throughout a 30-minute load).

### Thermal

Currently:
- 5060 Ti at 37°C (idle)
- 3090 at 60°C (load)

When the workload migration lands, expect:
- 5060 Ti to climb to ~70°C under encoding + compositing load
- 3090 to drop to ~50°C as encoder + compositing leaves

Both well within thermal envelope. **Verify case airflow** — two GPUs in series can cook the upper one if the case isn't designed for it.

### PCIe topology

```text
$ lspci | grep -E "VGA|3D|NVIDIA"
03:00.0 NVIDIA Corporation Blackwell GB203  (5060 Ti)
07:00.0 NVIDIA Corporation Ampere  GA102    (3090)
```

Need to verify `lspci -vvs 03:00.0 | grep LnkSta` returns lane width (sudo required).

**Speculation**: 5060 Ti at 03:00.0 is on the AMD chipset's nearest CPU lane (likely PCIe 5.0 x16). 3090 at 07:00.0 is on a downstream lane (PCIe 4.0 x16 if the chipset supports it; PCIe 3.0 x16 if not). **Verify with `lspci -vv`.**

## Cross-GPU coordination concerns

### Concern 1: cairo overlay textures must be uploaded to whichever GPU the compositor lives on

Cairo CPU work is GPU-agnostic. The CPU→GPU upload happens at `cairooverlay` time. When the compositor moves to GPU 0, the upload destination changes from GPU 1 to GPU 0. **No code change needed.**

### Concern 2: imagination → compositor frame transfer

Currently imagination writes a JPEG to `/dev/shm/hapax-visual/frame.jpg`. Tauri's HTTP server serves it. The compositor doesn't currently consume reverie frames as a video source.

**If reverie is added as an `external_rgba` source** (per the source-registry epic), the frames are uploaded from imagination's GPU (GPU 0 after migration) to wherever the compositor is (GPU 0 after migration). **Same GPU → no PCIe bounce. Free transfer.**

### Concern 3: TabbyAPI ↔ compositor cross-GPU IPC

TabbyAPI runs on GPU 1, compositor on GPU 0. The existing IPC is HTTP (LiteLLM gateway). No GPU memory transfer. **No concern.**

### Concern 4: P2P CUDA between cards

CUDA P2P (cudaMemcpyDeviceToDevice across GPUs) is supported on NVLink-connected pairs but consumer cards rarely have NVLink. The 5060 Ti and 3090 are unlikely to have a P2P bridge. Cross-GPU memory copies must round-trip through host RAM via cudaMemcpy. **Cost: ~10-20 GB/s** (PCIe 4.0 x16 to RAM). **Acceptable for occasional transfers, prohibitive for per-frame.** **Design constraint: never require per-frame data movement between GPU 0 and GPU 1.**

## Migration plan

### Phase 1: zero-risk reversible changes (1 hour)

1. **Snapshot current GPU state**:
   ```bash
   nvidia-smi > ~/hapax-state/dual-gpu/before-migration.txt
   nvidia-smi pmon -c 5 >> ~/hapax-state/dual-gpu/before-migration.txt
   ```
2. **Add `CUDA_VISIBLE_DEVICES=0` drop-in for studio-compositor**:
   ```bash
   systemctl --user edit studio-compositor.service
   # add:
   # [Service]
   # Environment="CUDA_VISIBLE_DEVICES=0"
   systemctl --user daemon-reload
   systemctl --user restart studio-compositor.service
   ```
3. **Verify**: `nvidia-smi pmon -c 3` should show the compositor on GPU 0.
4. **Test**: confirm `/dev/video42` still produces frames; OBS preview still works; RTMP still streams to MediaMTX.
5. **Rollback if any breakage**: remove the drop-in and restart.

### Phase 2: pin remaining workloads (2 hours)

6. **TabbyAPI explicit pin**:
   ```ini
   # tabbyapi.service drop-in
   [Service]
   Environment="CUDA_VISIBLE_DEVICES=1"
   ```
7. **hapax-imagination wgpu adapter pin**:
   ```ini
   # hapax-imagination.service drop-in
   [Service]
   Environment="WGPU_ADAPTER_NAME=5060"
   ```
8. **hapax-dmn investigate**: read the unit + the source to determine why 3.3 GiB. Decide GPU 0 or GPU 1 based on workload.

### Phase 3: physical changes (15 minutes, operator-coordinated)

9. **Cable swap**: move DisplayPort cable from 3090 to 5060 Ti.
10. **Hyprland WLR_DRM_DEVICES update**: edit `~/.config/hypr/hyprland.conf` to point at the 5060 Ti DRM card.
11. **Reboot**: cleanest path. Verify Hyprland comes up on the 5060 Ti.

### Phase 4: validate the new equilibrium (1 hour)

12. **Snapshot post-migration state**:
    ```bash
    nvidia-smi > ~/hapax-state/dual-gpu/after-migration.txt
    nvidia-smi pmon -c 30 >> ~/hapax-state/dual-gpu/after-migration.txt
    ```
13. **Compare**: GPU 0 should now host compositor + imagination + display (~5 GiB used, NVENC busy). GPU 1 should host only TabbyAPI + DMN (~9 GiB used, no encoder).
14. **Performance test**:
    - Compositor `studio_camera_frames_total` deltas should match pre-migration (no fps loss).
    - TabbyAPI tokens/sec should improve (more SM headroom).
    - Imagination shouldn't regress.
15. **Stress test**: simultaneous TabbyAPI inference + compositor recording + imagination at SEEKING-stance saturation. Watch for any throttling reasons.

## Headroom unlocked by partition

| metric | before | after | unlocked |
|---|---|---|---|
| GPU 1 free VRAM | 11.2 GiB | ~17 GiB | +5.8 GiB → bigger TabbyAPI models (Qwen3.5-32B EXL3 ~17 GiB), longer context, more KV cache |
| GPU 1 SM headroom | 35% | ~75% | +40% → faster LLM responses, room for parallel TTS GPU model |
| GPU 0 free VRAM | 16.3 GiB | ~11 GiB | -5 GiB consumed by visual workloads → still plenty for higher-res shaders, larger texture pools |
| total NVENC sessions | ~3 | ~6-10 | parallel encoders (OBS + RTMP + recording) |
| total NVDEC sessions | ~3 | ~6-10 | parallel ffmpeg video decode for richer overlays |
| NVENC quality (Blackwell vs Ampere) | Ampere | Blackwell | ~10-20% better PSNR per bitrate, AV1 hardware encode option |
| display surface jitter | shared with compute card | dedicated card | smoother Hyprland animations during heavy compute |

**The biggest single unlock is TabbyAPI getting its GPU back.** Currently it's competing with the encoder, the compositor, and imagination for SM cycles. After migration it has the 3090 to itself. **Expect 30-50% latency improvement on local LLM inference** based on Sprint 1's noted contention pattern.

## Findings + fix proposals

### F1 (HIGH): GPU 0 is 99% idle while GPU 1 is 65% loaded — fix the partition

**Finding**: As described above. The 5060 Ti is sitting unused while every workload contends for the 3090.

**Fix proposal**: Phases 1-4 of the migration plan. Phase 1 alone is the biggest win (compositor → GPU 0).

**Priority**: HIGH. **Single highest-leverage change in the entire research map.**

### F2 (HIGH): no per-process GPU pinning anywhere in the systemd units

**Finding**: All current units rely on default-CUDA-device behavior. After installing a second GPU, behavior is unpredictable until pins are added.

**Fix proposal**: Add `CUDA_VISIBLE_DEVICES` drop-ins to studio-compositor.service, tabbyapi.service, hapax-dmn.service. Add `WGPU_ADAPTER_NAME` to hapax-imagination.service.

**Priority**: HIGH. Foundational for predictable dual-GPU behavior.

### F3 (HIGH): NVENC sessions need redistribution

**Finding**: NVENC session limit per consumer card historically 3-5. With both cards, 6-10 total. Currently all on GPU 1.

**Fix proposal**: Document the per-card NVENC budget. Pin compositor's encoder to GPU 0. If OBS is also encoding, point it at GPU 0 too (or split — OBS on GPU 0, compositor on GPU 1, depending on which encoder is on the critical path).

**Priority**: HIGH for parallel encoder design (recording + streaming + OBS preview each as separate encoders).

### F4 (MEDIUM): physical display path should move to the 5060 Ti

**Finding**: Hyprland is on GPU 1, which is the high-compute card. Display interrupts and frame timing for the compositor's webview animations compete with TabbyAPI inference and compositor encoding.

**Fix proposal**: Cable swap + Hyprland config + reboot. Phase 3 of the migration plan.

**Priority**: MEDIUM. Quality-of-life improvement; not blocking.

### F5 (MEDIUM): wgpu adapter selection for hapax-imagination

**Finding**: `hapax-imagination` uses wgpu and currently lands on GPU 1 (302 MiB). wgpu adapter selection is non-trivial to control via env vars across versions.

**Fix proposal**: Verify the wgpu version in `hapax-imagination/Cargo.toml`. Check the supported env var. Set it in the systemd unit. If env vars don't work, patch `imagination/src/main.rs` to filter `Instance::enumerate_adapters()` by name.

**Priority**: MEDIUM.

### F6 (MEDIUM): hapax-dmn 3.3 GiB allocation needs investigation

**Finding**: hapax-dmn is using 3.3 GiB on GPU 1 but it's unclear what for. Could be a torch model for embedding, vision perception, or a pre-loaded LLM. Until investigated, partition placement is undecided.

**Fix proposal**: Read `agents/hapax_daimonion/__main__.py` (if exists) or grep for `cuda` / `torch.device` / `to('cuda')`. Determine the workload type and assign accordingly.

**Priority**: MEDIUM.

### F7 (MEDIUM): PCIe link width verification needed

**Finding**: Two GPUs on different PCIe slots; link widths and gens not yet measured.

**Fix proposal**:

```bash
sudo lspci -vvs 03:00.0 | grep -E "LnkSta:|LnkCap:"
sudo lspci -vvs 07:00.0 | grep -E "LnkSta:|LnkCap:"
```

Document actual gen + width. If either is degraded (e.g., 5060 Ti at PCIe 4.0 x8 instead of 5.0 x16), investigate motherboard slot allocation.

**Priority**: MEDIUM.

### F8 (HIGH): power budget validation under combined load

**Finding**: Total GPU TDP is now 600 W. PSU rating unverified. Combined-load behavior unmeasured.

**Fix proposal**: Sprint 7 stress test. Run 30 minutes of: TabbyAPI sustained inference + compositor encoding at 6 Mbps + imagination at SEEKING-stance + reverie shaders. Watch `nvidia-smi --query-gpu=power.draw,clocks_throttle_reasons.hw_power_brake_slowdown,clocks_throttle_reasons.sw_thermal_slowdown`. Power throttling means the PSU is undersized for the combined draw and either GPU clocks must be capped or the PSU upgraded.

**Priority**: HIGH. Failure mode is silent performance degradation under stress, exactly when livestream load is highest.

### F9 (RESEARCH): can the second GPU host a parallel TTS model?

**Finding**: Kokoro 82M TTS is currently CPU. With 11 GiB free on GPU 0 (post-migration), a GPU TTS model (Coqui XTTS, Bark, Tortoise, ChatTTS) could run hot on GPU 0 alongside the compositor + imagination. Cost: 2-4 GiB VRAM. Benefit: <100 ms TTS latency vs current 200-500 ms CPU latency.

**Fix proposal**: Sprint 7 spike. Pick a candidate model, measure cold-start + per-utterance latency on the 5060 Ti, decide whether to ship.

**Priority**: RESEARCH (Sprint 7 polish item).

### F10 (RESEARCH): Blackwell-specific encoder features unexplored

**Finding**: Blackwell NVENC has new features beyond Ampere: AV1 hardware encode, 4:2:2 chroma support, lower-latency mode, improved bitrate ladder. None currently used.

**Fix proposal**: After migration, audit `nvh264enc` properties on a Blackwell-bound encoder vs Ampere-bound. Some properties may be Blackwell-only. Document the available features. Decide whether to enable AV1 (when nvav1enc lands), 4:2:2 chroma (matters for color grading), or new low-latency modes.

**Priority**: RESEARCH (Sprint 7 polish item).

## Cross-sprint impact summary

The dual-GPU rig changes findings across every sprint of the research map.

### Sprint 1 (Foundations) — re-derived

- L1.1 VRAM breakdown: needs separate per-GPU breakdown in future passes. The single "12.83 GiB used" hides that all 12.83 is on GPU 1.
- F4 "compositor VRAM 3 GB worth investigating": still true, but moves to GPU 0 after migration. Re-investigate after migration to see if Blackwell allocations differ.

### Sprint 2 (Performance baseline) — re-derived

- D1.1 cudacompositor: needs `cuda-device-id=0` to land on the 5060 Ti. Currently uses CUDA default.
- F2 brio-operator fps deficit: SM contention with TabbyAPI is one of the candidate causes. After migration, re-measure brio-operator fps. **If the deficit disappears post-migration, the root cause was inference contention.** That's a P0 finding waiting to land.

### Sprint 3 (Audio reactivity) — re-derived

- No direct impact. Audio analysis is CPU. But the sidechain visual ducking (sidechain_kick → colorgrade) runs on whichever GPU the compositor lives on. After migration, dim time will be Blackwell-fast.

### Sprint 4 (Ducking + routing) — re-derived

- No direct impact. Audio routing is CPU + DSP.

### Sprint 5 (Output + streaming) — re-derived

- See Sprint 5 main doc. F1 (NVENC on wrong GPU) is the principal finding; this sub-doc is the deep dive.

### Sprint 6 (Observability) — derived in advance

- Need per-GPU metrics in Prometheus. Currently `hapax_gpu_*` (if exists) is single-GPU. Add `gpu_index` label.
- VRAM watchdog needs to honor both GPUs. If only watching GPU 0 it misses TabbyAPI OOMs.

### Sprint 7 (Polish) — derived in advance

- TTS GPU migration spike. Stress test. AV1 spike. Power budget validation. Several Sprint 7 items become more interesting with the new card.

## Sprint 5b backlog additions (items 201+)

201. **`fix(systemd): CUDA_VISIBLE_DEVICES=0 drop-in for studio-compositor.service`** [Sprint 5b F1] — phase 1 of the migration plan. Highest single leverage in the research map.
202. **`fix(systemd): CUDA_VISIBLE_DEVICES=1 drop-in for tabbyapi.service`** [Sprint 5b F2] — explicit pin for predictability.
203. **`fix(systemd): WGPU_ADAPTER_NAME drop-in for hapax-imagination.service`** [Sprint 5b F2+F5] — verify wgpu env var first.
204. **`research(hapax-dmn): identify 3.3 GiB GPU allocation purpose`** [Sprint 5b F6] — needed before pin decision.
205. **`fix(hyprland): WLR_DRM_DEVICES + DP cable swap to 5060 Ti`** [Sprint 5b F4] — operator-coordinated.
206. **`research(pcie): verify lane width + gen on both GPU slots`** [Sprint 5b F7] — `lspci -vv` audit.
207. **`research(power): PSU spec audit + 30-min combined-load stress test`** [Sprint 5b F8] — verify total draw under saturation.
208. **`research(tts-gpu): spike candidate TTS models on the 5060 Ti`** [Sprint 5b F9] — Kokoro is CPU; consider GPU upgrade path now that there's headroom.
209. **`research(av1): Blackwell NVENC AV1 + nvav1enc gst plugin status`** [Sprint 5 F3 + Sprint 5b F10] — bridge gap so AV1 can be tested.
210. **`feat(metrics): per-GPU Prometheus gauges with gpu_index label`** [Sprint 5b cross-Sprint 6] — current metrics are single-GPU.
211. **`research(brio-operator-fps): re-measure after dual-GPU migration`** [Sprint 1 F2 carry-over, Sprint 5b cross-impact] — if the 28.5 fps deficit disappears with TabbyAPI off the same GPU as the compositor, that's the root cause.
212. **`docs(claude.md): add "Dual-GPU Topology" section`** [Sprint 5b documentation] — workspace CLAUDE.md should call out the partition strategy after Phase 1 lands.
213. **`feat(rebuild-script): test both GPUs available before deploy`** [Sprint 5b reliability] — rebuild-service.sh should check that the target GPU is available before restarting a service that depends on it. Avoids failure modes where one card is missing on boot.
