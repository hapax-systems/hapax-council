# Livestream Performance — End-to-End Research Map

**Author:** beta
**Date:** 2026-04-13 CDT
**Status:** meta-research — this document names what to research, not what was researched
**Register:** scientific, neutral (per `feedback_scientific_register.md`)

## Target state

Buttery-smooth 1080p30 livestream with:

- **Rock-steady frame pacing.** 30.000 ± 0.1 fps at every stage of the pipeline. Zero visible frame drops. Zero stutters. Zero micro-freezes. p99 frame-time ≤ 34 ms.
- **Reliability.** 24/7 operation without manual intervention. All component failures are detected within 1 tick and either self-heal or fail loudly. No "alive but silent" zombie states.
- **Perfect audio reactivity.** Visual effects track audio with perceived latency ≤ 50 ms. Smooth envelopes, no pops, no clicks, no jitter. BPM locking, transient detection, per-band modulation.
- **Clean audio ducking.** TTS plays while music auto-ducks. Operator speech auto-ducks music. Side-chain envelopes match the musical material.
- **Stable encoder output.** NVENC produces consistent bitrate at configured quality, no keyframe stalls, no reconnects.
- **Observable everywhere.** Every stage has a Prometheus metric surface. Every failure is surfaced in Grafana within 30 s.

## Scope boundaries

**In scope**

- Capture (USB cameras, PipeWire audio)
- Kernel/driver (v4l2, uvc, usbcore, NVIDIA)
- GStreamer compositor pipeline
- Effect graph + WGSL shaders + Rust imagination
- Cairo overlay sources + shared-memory RGBA feeds
- Audio capture + analysis + reactivity + ducking
- V4L2 loopback + OBS integration + NVENC encoding
- YouTube/RTMP ingest + MediaMTX
- Cross-system integration (compositor <-> daimonion <-> imagination <-> VLA)
- Observability (Prometheus + Grafana + systemd journals)
- Reliability (watchdogs, supervisors, restart cascades)

**Out of scope**

- Voice daemon conversational behavior (LLM tiering, salience routing — covered by queues 022-026)
- Axiom governance (covered by queue 025 Phase 1)
- Qdrant consent gates (covered by queue 026 Phase 4)
- SDLC pipeline (covered by queue 026 Phase 6)
- Operator UX for the Obsidian plugin + logos app
- Hardware procurement decisions (cameras, PSU, cables — research only, no buy recommendations)

**Cross-referenced but not duplicated**

- Queue 022 Phase 1 hardware topology — extend with this map's physical/thermal work
- Queue 024 FINDING-H scrape gap — prerequisite for most observability work here
- BETA-FINDING-L task supervisor — prerequisite for reliability work
- BETA-FINDING-Q imagination crash storm — prerequisite for effect graph work

## Methodology

Each research topic in this map has:

- **Topic ID** (e.g. C3.2 = Theme C, area 3, subtopic 2)
- **Research question** — one sentence, specific
- **Why it matters** — link to the target state
- **Priority** — P0 (blocks target state) / P1 (high impact) / P2 (important) / P3 (nice-to-have)
- **Depth estimate** — hours to land a research-grade answer
- **Depends on** — prior research or fixes that must ship first
- **Method sketch** — specific tools, probe commands, reproduction path

The map covers **16 themes** (A-P) with roughly **130 research topics**. Execution is sequential within dependency chains but many themes can run in parallel.

## The 16 themes

- **A.** Physical + hardware reliability
- **B.** Kernel + capture layer
- **C.** GStreamer camera pipeline
- **D.** Compositor + layout + surface registry
- **E.** Effect graph + shaders + imagination
- **F.** Audio capture + PipeWire graph
- **G.** Audio analysis + reactivity
- **H.** Audio ducking + routing
- **I.** Output encoding + V4L2 loopback
- **J.** OBS integration + scene graph
- **K.** Streaming ingest (YouTube + MediaMTX)
- **L.** GPU budget + contention
- **M.** Latency budgets (per-stage + end-to-end)
- **N.** Observability end-to-end
- **O.** Reliability + recovery + watchdogs
- **P.** Control surface + interactions + audio-visual linkage

Plus cross-cutting concerns: **Q** content layer integrity, **R** cross-system integration — these are rolled into other themes rather than broken out.

---

## Theme A — Physical + hardware reliability

The whole pipeline starts with six USB cameras, an audio interface, and a GPU. Physical reliability bugs propagate silently into every downstream layer. Queue 022 Phase 1 shipped the initial camera topology map; this theme extends it.

| # | topic | research question | priority | depth | depends on |
|---|---|---|---|---|---|
| **A1** | **USB bus topology audit** | Does every camera own enough USB 3.0 bandwidth? Are any sharing a xHCI companion with audio or another camera? | P0 | 2 h | q022 P1 |
| A1.1 | xHCI companion mapping | `lsusb -tv` + `/sys/bus/usb/devices/*/speed` per camera; identify shared-bus conflicts | P0 | 30 m | — |
| A1.2 | BRIO 43B0576A USB 2.0 root cause | Why does bus 5-4 negotiate only 480M? Cable, port, or device? Swap protocol to test. | P1 | 1 h | A1.1 |
| A1.3 | USB bandwidth under 6-camera load | Can all 6 cameras sustain MJPEG 1920x1080@30 simultaneously? Headroom on each bus? | P0 | 1 h | A1.1 |
| A1.4 | C920 082d PID coverage in udev | Older C920 PID is not in `70-studio-cameras.rules` Phase 3 reconfigure. Add it. | P2 | 30 m | q022 P1 |
| **A2** | **Thermal + PSU headroom** | Under full livestream load, are any components (GPU, CPU, chipset, USB hub) thermal-throttled or brownout-risk? | P1 | 2 h | — |
| A2.1 | GPU thermal profile | `nvidia-smi --query-gpu=temperature.gpu --loop=1` during a 30-min livestream. Cap, throttle events, fan curve. | P1 | 1 h | — |
| A2.2 | CPU thermal profile | `sensors` + per-core temps during sustained compositor + tabbyapi + daimonion + imagination load | P1 | 1 h | — |
| A2.3 | USB hub self-heating + external power | Which cameras are on powered hubs? Is any hub running hot? | P2 | 30 m | — |
| A2.4 | PSU headroom | Peak wattage observed vs PSU capacity. Any margin for a second GPU, NVENC encoder accelerator, or additional cameras? | P2 | 30 m | — |
| **A3** | **Cable + connector fatigue** | Which cables are old / bent / recently unplugged? Is BRIO bus 5-4 a cable issue? | P2 | 1 h | A1.2 |
| A3.1 | USB cable swap protocol | Step-by-step operator procedure: swap BRIO 43B0576A cable + port, re-measure speed, re-run test | P2 | 30 m | A1.2 |
| A3.2 | Connector stress + EMI | Are the braided-cable bundles causing USB link instability? Separate test with isolated cables. | P3 | 30 m | A3.1 |
| **A4** | **NVIDIA driver + Vulkan + wgpu stability** | Cross-ref BETA-FINDING-Q (65 imagination crashes/24h). Is the crash driver-related or app-side? | P0 | 3 h | BETA-FINDING-Q |
| A4.1 | Driver version + wgpu-24.0.5 compatibility | Which NVIDIA driver is installed? Known wgpu validation-error patterns against this pair? | P0 | 1 h | — |
| A4.2 | Vulkan validation layer testing | Run imagination under `VK_LOADER_DEBUG=all` + validation layers. Does the fragment shader mismatch reproduce? | P0 | 1 h | A4.1 |
| A4.3 | Driver downgrade feasibility | Is there a known-good driver version from prior session history? | P2 | 30 m | — |
| **A5** | **Host kernel interrupt + scheduling** | Does the compositor's GStreamer streaming thread see scheduling jitter under load? | P1 | 2 h | — |
| A5.1 | IRQ affinity audit | `/proc/interrupts` — are USB IRQs pinned? Are they on the same core as audio? | P1 | 1 h | — |
| A5.2 | RT priority + niceness audit | `chrt -p $(pgrep studio-compositor)` — what RT class is the compositor running at? What about PipeWire? | P1 | 30 m | — |
| A5.3 | kworker + softirq cost | Is kernel housekeeping stealing CPU from the render thread? | P2 | 30 m | — |

---

## Theme B — Kernel + capture layer

The path from the v4l2 driver to the first GStreamer buffer. If kernel drops frames here, nothing downstream can recover them.

| # | topic | research question | priority | depth | depends on |
|---|---|---|---|---|---|
| **B1** | **v4l2 kernel drop characterization** | Is the `studio_camera_kernel_drops_total` counter telling the truth? Does it catch every dropped frame? | P0 | 2 h | q022 P4 |
| B1.1 | v4l2 sequence gap detection | `v4l2src` buffer offset = kernel sequence number. Walk a 10-min trace and compare against GStreamer's `studio_camera_frames_total`. | P0 | 1 h | — |
| B1.2 | ioctl VIDIOC_DQBUF timing | When the driver has a frame ready, how fast does userspace pull it? Is there a timing gap? | P1 | 1 h | B1.1 |
| B1.3 | mmap vs userptr vs dmabuf | Which I/O method does v4l2src use today? What's the cost of each? | P2 | 1 h | — |
| **B2** | **USB bus bandwidth contention** | Can 6 MJPEG streams + audio + other USB devices coexist without frame loss? | P0 | 2 h | A1.3 |
| B2.1 | Bus utilization per xHCI | Which xHCI host controllers are saturated? Per-bus bandwidth math. | P0 | 1 h | A1.1 |
| B2.2 | MJPEG vs YUYV bandwidth tradeoff | MJPEG is ~4x smaller than YUYV but CPU decodes. YUYV is uncompressed but fits worse on USB 2.0. Which wins for each bus? | P1 | 1 h | — |
| B2.3 | Resolution downscale cost | Would dropping brio-room to 1280x720 free enough USB bandwidth? Cross-check with perceptual impact. | P2 | 30 m | B2.1 |
| **B3** | **Buffer pool sizing** | Does every GStreamer v4l2src have enough kernel buffers allocated? Are we double-buffering or pentuple-buffering? | P1 | 1 h | — |
| B3.1 | `v4l2src num-buffers` property audit | What's set today? What's the kernel default? | P1 | 30 m | — |
| B3.2 | Pool exhaustion detection | Grep for "Failed to allocate a buffer" in the journal (already seen in brio-room fault at 17:00:47 in queue 023). Is this a pool-size issue? | P0 | 1 h | q023 P4 |
| **B4** | **USB power management** | `power/control=auto` on BRIOs (known from q022). Which device is autosuspending? Does it correlate with fault events? | P1 | 2 h | — |
| B4.1 | power.control drift investigation | Every BRIO reverts to `auto` despite udev rule setting `on`. Kernel reassertion path? | P1 | 1 h | q022 P1 |
| B4.2 | autosuspend_delay_ms effective value | `cat /sys/bus/usb/devices/*/power/autosuspend_delay_ms` — what's live? | P2 | 15 m | B4.1 |
| B4.3 | Resume latency after suspend | If a camera autosuspends, how long does it take to resume? Does it drop frames? | P2 | 30 m | B4.1 |
| **B5** | **udev rule reliability** | Does `studio-camera-reconfigure@%k.service` fire correctly on every device attach? Any races at boot? | P2 | 1 h | — |
| B5.1 | Reconfigure service trigger timing | `journalctl --user -u studio-camera-reconfigure@*.service` — has it fired for every camera this boot? | P2 | 30 m | — |
| B5.2 | udev at boot race | Does the compositor try to open cameras before udev's reconfigure hook completes? | P2 | 30 m | B5.1 |

---

## Theme C — GStreamer camera pipeline

From the kernel buffer into the compositor's producer pipelines. The per-camera FSM, interpipesrc hot-swap, and fallback logic all live here.

| # | topic | research question | priority | depth | depends on |
|---|---|---|---|---|---|
| **C1** | **Per-camera sub-pipeline steady state** | For each of 6 cameras, what is the true frame cadence — mean, stddev, drift — over a 10-min window? | P0 | 3 h | q022 P2 |
| C1.1 | brio-operator 27.97 fps deficit | Queue 022 measured it; reproduce now that Option A landed. Is it still 28? Hardware root cause? | P0 | 2 h | q022 P2 |
| C1.2 | Other cameras steady state | brio-room, brio-synths, c920-desk, c920-room, c920-overhead — any similar deficits? | P0 | 1 h | — |
| C1.3 | Producer thread starvation test | Pin the producer thread to a dedicated core. Does brio-operator recover to 30? | P1 | 1 h | C1.1 |
| **C2** | **interpipesrc hot-swap** | What's the latency + atomicity of a camera -> fallback swap? Any visible flash? | P1 | 2 h | — |
| C2.1 | Swap latency measurement | Instrumented swap: write a test harness that forces a swap and measures downstream-frame delay | P1 | 1 h | — |
| C2.2 | Swap-during-render race | If a swap fires mid-frame, is the current frame completed with the old source or the new one? | P1 | 1 h | C2.1 |
| C2.3 | Fallback pipeline state drift | Does the fallback pipeline's `testsrc` pattern drift out of sync with the primary's timebase? | P2 | 1 h | — |
| **C3** | **State machine timing** | Queue 023 Phase 4 measured class-A fault timing via natural experiment. Extend to classes B/C/D under alpha coordination. | P1 | 3 h | q023 P4 |
| C3.1 | Class B USBDEVFS_RESET timing | Per the queue 023 plan, run 3 reps on c920-desk + tabulate dwell times | P1 | 1 h | q023 P4 |
| C3.2 | Class C watchdog element trip | When the GStreamer `watchdog` element fires, how long to recover? Is the fallback engaged in time? | P1 | 1 h | q023 P4 |
| C3.3 | Class D MediaMTX kill + restart | Requires MediaMTX active. Full reconnect timing on the native RTMP bin. | P2 | 1 h | q023 P4, I4 |
| C3.4 | Backoff ceiling tuning | Queue 023 found `BACKOFF_CEILING_S = 60.0`. Is that right for brio-room (slow physical reset) vs c920 (fast)? | P2 | 30 m | C3.1 |
| **C4** | **Format negotiation** | Which formats are each camera negotiating? Is the pipeline forcing MJPEG or letting the camera pick? | P2 | 1 h | — |
| C4.1 | Format debug | Run with `GST_DEBUG=v4l2src:5` on each sub-pipeline. What format gets picked, at what rate? | P2 | 30 m | — |
| C4.2 | MJPEG decode cost | Is the compositor decoding MJPEG to NV12/YUV on the CPU or in GPU? Where's the decode cost? | P2 | 30 m | — |
| **C5** | **Pre-roll buffer sizing** | Does `queue max-size-buffers=...` trade off latency for smoothness? What's set today? | P1 | 2 h | — |
| C5.1 | Queue elements in the pipeline | Enumerate every `queue` / `queue2` in the composite pipeline. What's the sizing strategy? | P1 | 1 h | — |
| C5.2 | Latency vs smoothness tradeoff curve | For one camera, measure p99 jitter at 1-buffer vs 3-buffer vs 10-buffer queue depths | P2 | 1 h | C5.1 |
| **C6** | **Camera pipeline error classification** | Queue 023 surfaced "Could not read from resource" and "Failed to allocate a buffer" as separate error classes. What others exist? | P2 | 1 h | q023 P4 |

---

## Theme D — Compositor + layout + surface registry

The GStreamer compositor element does the final blend. The source registry manages what feeds in. This is where frame-rate stability either holds or breaks.

| # | topic | research question | priority | depth | depends on |
|---|---|---|---|---|---|
| **D1** | **Composite element performance** | What's the frame-time cost of the main `compositor` (or `glvideomixer`) element vs its inputs? | P0 | 3 h | — |
| D1.1 | Main mixer element identity | Read `agents/studio_compositor/compositor.py` — is it `glvideomixer`, `compositor`, or `nvcompositor`? | P0 | 15 m | — |
| D1.2 | Per-source blend cost | For each registered source (6 cameras + reverie + cairo overlays), what's the per-frame blend cost on the mixer? | P0 | 2 h | D1.1 |
| D1.3 | Alpha blending cost | Does the mixer do alpha compositing on every pass or only where needed? | P1 | 30 m | — |
| D1.4 | GLES vs Vulkan mixer | Can the mixer be swapped to a Vulkan-backed version for lower cost? | P2 | 1 h | A4 |
| **D2** | **Source registry overhead** | Queue 025 Phase 3 reframed FINDING-I and found the BudgetTracker dead. What else in the source registry is dormant? | P2 | 2 h | q026 P2 |
| D2.1 | SurfaceKind + Assignment overhead | Per-source, what's the cost of the type check + layout lookup + binding? | P2 | 1 h | — |
| D2.2 | Natural-size vs canvas-size scaling | Does every source render at natural size and scale at blend time? | P2 | 30 m | — |
| **D3** | **Cairo source runner** | The `CairoSourceRunner` renders Python cairo content off the streaming thread. How much CPU does it burn? How consistent is its cadence? | P1 | 3 h | — |
| D3.1 | Per-runner cadence trace | For each active cairo runner (token_pole, album_overlay, overlay_zones, sierpinski, stream_overlay), measure tick time + frame delivery | P1 | 2 h | — |
| D3.2 | Cached surface blit cost | The GStreamer cairooverlay draw callback blits the cached surface. How fast is that blit? | P1 | 30 m | — |
| D3.3 | Runner thread contention | Are multiple runners competing for the GIL? Would separate processes help? | P2 | 1 h | D3.1 |
| **D4** | **Shared-memory RGBA ingestion** | `reverie.rgba` from hapax-imagination is the main SHM source. What's its latency + jitter? | P1 | 2 h | — |
| D4.1 | reverie.rgba write cadence | Measure mtime updates on `/dev/shm/hapax-sources/reverie.rgba` vs compositor read cadence | P1 | 1 h | — |
| D4.2 | Read lock contention | Does the compositor wait for the writer, or does it pick up stale frames? | P1 | 1 h | D4.1 |
| D4.3 | Add more SHM sources? | Would a browser source (overlay graphics from React) work as an SHM feed? Performance tradeoff? | P3 | 2 h | — |
| **D5** | **Layout hot-reload** | Editing `config/compositor-layouts/default.json` should round-trip in <=2 s (AC-5). Is it? | P2 | 1 h | q025 P6 |
| D5.1 | LayoutFileWatcher latency | Time from file save -> live layout change | P2 | 30 m | — |
| D5.2 | LayoutAutoSaver correctness | After a runtime mutation, does the on-disk JSON match? | P2 | 30 m | — |
| **D6** | **Source z-order + occlusion** | When a camera is fully covered by a cairo overlay, does the compositor skip the camera's blend? | P2 | 1 h | — |
| D6.1 | Occlusion optimization | Does the mixer implement occlusion culling? Profile with + without a fully-overlapping source | P2 | 1 h | — |
| **D7** | **Main output assembly cost** | How long does it take to assemble one 1920x1080 frame from all sources? | P0 | 2 h | D1.2 |
| D7.1 | Per-frame end-to-end timing | Instrument the composite pipeline with `GstLatencyTracer` and pull per-frame latency | P0 | 1 h | — |
| D7.2 | Frame-time jitter p50/p95/p99 | 10-min trace, histogram the frame-time distribution | P0 | 1 h | D7.1 |

---

## Theme E — Effect graph + shaders + imagination

This is where the biggest performance drain (and the biggest creative value) lives. Shader cost, texture pool efficiency, hot-reload stability, WGSL correctness.

| # | topic | research question | priority | depth | depends on |
|---|---|---|---|---|---|
| **E1** | **Effect graph activation cost** | Queue 023 observed "Slot N (name): setting fragment" log spam during graph activation. What's the per-slot activation cost? | P1 | 2 h | — |
| E1.1 | Slot-by-slot fragment compile time | Instrument `activate_plan` -> `setting fragment` log + time each | P1 | 1 h | — |
| E1.2 | 24-slot plan vs simpler plans | Queue 023 saw PID 3145327 jump 1.3->4.4 GB during a 24-slot activation. Reproduce. | P0 | 1 h | q023 P1 |
| E1.3 | Plan activation GPU vs CPU | Is the cost on the shader-compile side (CPU + NVIDIA driver) or GPU upload? | P1 | 30 m | E1.1 |
| **E2** | **Per-node shader performance** | 54 node types per CLAUDE.md. Which ones are cheap? Which are expensive? Which are in the hot path? | P0 | 4 h | — |
| E2.1 | Node catalog + cost tier | Enumerate every node in `agents/effect_graph/` + classify by observed GPU cost | P0 | 2 h | — |
| E2.2 | Individual node profiling | Use wgpu `Query::Timestamp` (when added per E6.3) to measure per-node ms on a 10-min live session | P0 | 2 h | E6.3 |
| E2.3 | Bottleneck identification | Rank the top 5 most expensive nodes when active in a typical chain | P0 | 1 h | E2.2 |
| **E3** | **WGSL compiler -> runtime pipeline** | From Python's `wgsl_compiler.py` to the Rust `DynamicPipeline` hot-reload — what's the latency of a plan change? | P2 | 2 h | — |
| E3.1 | Compiler -> SHM write time | `agents/effect_graph/wgsl_compiler.py` produces WGSL + execution plan. How long? | P2 | 1 h | — |
| E3.2 | SHM write -> Rust hot-reload | From file write to live pipeline swap | P2 | 1 h | — |
| **E4** | **glfeedback Rust plugin** | The Rust GStreamer element does temporal feedback. What's its per-frame cost? | P1 | 2 h | — |
| E4.1 | Plugin frame cost | Profile the `glfeedback::filter_texture` path under typical + worst-case accumulator sizes | P1 | 1 h | — |
| E4.2 | Shader recompile events | Queue 023 saw "shader_dirty detected — recompiling" firing multiple times per second. Is this normal? | P1 | 1 h | — |
| **E5** | **Uniform buffer update path** | `uniforms.json` + per-node param bridge. What's the update latency? Who writes it? | P1 | 2 h | — |
| E5.1 | Uniform write cadence | Who writes `/dev/shm/hapax-imagination/uniforms.json`? How often? | P1 | 30 m | — |
| E5.2 | Uniform -> GPU upload timing | From JSON write to next frame's GPU upload | P1 | 30 m | E5.1 |
| E5.3 | Dynamic param bridge correctness | The param_order positional walk — any mismatch risk? (Cross-ref BETA-FINDING-Q root cause.) | P0 | 1 h | BETA-FINDING-Q |
| **E6** | **Texture pool efficiency** | Queue 026 Phase 3 found `pool_metrics.reuse_ratio = 0.0`. Investigate the acquire/release path. | P1 | 3 h | q026 P3 |
| E6.1 | Pool acquire/release trace | Instrument the `TransientTexturePool` to log every acquire + release with a size signature | P1 | 2 h | — |
| E6.2 | Size key collision analysis | Why is `bucket_count=1` but `total_textures=14`? Same key, but no reuse? | P1 | 1 h | E6.1 |
| E6.3 | Per-pass timing instrumentation | wgpu `Query::Timestamp` to measure per-pass ms. Expose in `pool_metrics.json`. | P1 | 2 h | — |
| **E7** | **Shader hot-reload safety** | BETA-FINDING-Q: 65 validation crashes/24h. Need a manifest-gated safe hot-reload. | P0 | 4 h | BETA-FINDING-Q |
| E7.1 | WGSL struct field order validation | Compare shader's declared `@group(2) Params` against the plan's `pass.param_order` before wgpu load | P0 | 2 h | — |
| E7.2 | Fallback panic handler | Roll back to previous-good shader on wgpu validation error instead of process exit | P0 | 2 h | E7.1 |
| E7.3 | Rollback counter metric | `hapax_imagination_shader_rollback_total{pass}` counter | P1 | 30 m | E7.2 |
| **E8** | **Preset chain performance** | 28 presets per CLAUDE.md. 8 of 24 slots used in the chain observed in q023. What's the cost curve? | P1 | 3 h | — |
| E8.1 | Preset catalog + slot counts | Enumerate every preset, count its slots, classify by complexity | P1 | 1 h | — |
| E8.2 | Preset transition cost | Switching from preset A to preset B — how long? | P1 | 1 h | E1 |
| E8.3 | Chain activation vs single preset | Is a chain of 8 presets more expensive than one preset with 8 nodes? | P2 | 1 h | — |
| **E9** | **Reverie mixer + 5-channel system** | Operator wants dynamic technique selection, not fixed pipeline. What does the mixer cost when switching channels? | P2 | 2 h | — |
| E9.1 | Reverie channel switch cost | Per the `project_reverie_adaptive` memory, RD/Physarum/Voronoi are target channels. Cost of switching in + out | P2 | 1 h | — |
| **E10** | **Content layer compositing** | `content_layer.wgsl` reads material_id + slot salience from custom uniforms. What's the rendering cost by material type? | P2 | 2 h | — |
| E10.1 | Per-material (water/fire/earth/air/void) cost | Profile each material's render cost | P2 | 1 h | — |

---

## Theme F — Audio capture + PipeWire graph

The full audio input chain. Yeti XLR, contact mic, mixer inputs, OBS virtual audio. Latency, jitter, and graph topology.

| # | topic | research question | priority | depth | depends on |
|---|---|---|---|---|---|
| **F1** | **PipeWire graph topology** | How many nodes, how many links? What's the full graph today? | P0 | 2 h | — |
| F1.1 | `pw-dump` full graph inventory | Enumerate every node, port, link. Classify by type (source/sink/filter/client). | P0 | 1 h | — |
| F1.2 | Graph latency walk | For each source -> sink path, compute total buffer latency from link metadata | P1 | 1 h | F1.1 |
| F1.3 | Unused nodes | Which nodes exist but have no live links? Dead subscribers? | P2 | 30 m | F1.1 |
| **F2** | **Audio input inventory** | What physical + virtual sources feed the council today? | P0 | 2 h | — |
| F2.1 | Physical inputs | Yeti mic, contact mic, Studio 24c line inputs 1-8, any USB audio devices | P0 | 1 h | — |
| F2.2 | Virtual inputs | PipeWire loopback nodes, ALSA capture, any filter-chain sinks | P0 | 1 h | F1.1 |
| F2.3 | OBS virtual audio | How does OBS pull audio? Monitor-of-sink, direct node subscription? | P1 | 1 h | — |
| **F3** | **Input -> Python latency** | From PCM samples arriving at the hardware to Python reading them | P0 | 2 h | — |
| F3.1 | `pw-cat --record` startup + first-sample latency | Cold start + first-sample time for the contact mic path | P0 | 1 h | — |
| F3.2 | Buffer period cascade | hw_params period_size -> PipeWire buffer -> Python chunk — where does each layer add latency? | P0 | 1 h | F3.1 |
| F3.3 | Contact mic PyAudio workaround | CLAUDE.md mentions a PyAudio limitation for contact mic. What's the workaround? Is there a cleaner path? | P2 | 1 h | — |
| **F4** | **Sample rate + buffer size** | Queue 023 measured `clock.quantum=128` = 2.67 ms @ 48 kHz. Is that the floor? Can we go lower? | P2 | 2 h | q023 P5 |
| F4.1 | Quantum optimization | 64 frames = 1.33 ms minimum. Xrun risk at 64? Measure xrun count vs quantum. | P2 | 1 h | — |
| F4.2 | Sample rate audit | Everything on 48 kHz? Any 44.1 kHz holdouts that force a resample? | P2 | 30 m | — |
| **F5** | **Echo cancellation** | `agents/hapax_daimonion/echo_canceller.py`. Path latency + quality. | P1 | 2 h | — |
| F5.1 | AEC delay | Processing delay of the echo canceller | P1 | 1 h | — |
| F5.2 | AEC effectiveness | Measurement: play TTS -> record back via Yeti -> compute suppression in dB | P1 | 1 h | — |
| **F6** | **Multi-mic fusion** | `project_multi_mic_pipeline` memory mentions target speaker extraction. Current state? | P2 | 2 h | — |
| F6.1 | Fusion algorithm inventory | What signals are merged? Which algorithm? | P2 | 1 h | — |
| F6.2 | Fusion latency budget | How much latency does fusion add on top of raw capture? | P2 | 1 h | F6.1 |

---

## Theme G — Audio analysis + reactivity

This is half of the "perfect audio reactivity" target. Real-time feature extraction + modulation of visual effect parameters.

| # | topic | research question | priority | depth | depends on |
|---|---|---|---|---|---|
| **G1** | **Feature extraction pipeline** | Where does real-time audio analysis live today? | P0 | 3 h | — |
| G1.1 | Audio analysis code inventory | `shared/audio_*`, `agents/*/audio_*`, `agents/hapax_daimonion/audio_*` — all audio analysis paths | P0 | 1 h | — |
| G1.2 | Real-time vs offline paths | Which analyses run per-frame (low latency) vs on complete utterances (high latency)? | P0 | 1 h | G1.1 |
| G1.3 | Feature aggregation point | Where are extracted features aggregated and re-published? `/dev/shm/hapax-*`? | P0 | 1 h | G1.2 |
| **G2** | **RMS + envelope** | Per-channel RMS envelope with configurable attack/release. Is this running today? | P0 | 2 h | — |
| G2.1 | Current envelope shape | `contact_mic.py` or similar has envelope math — what attack/release constants? | P0 | 1 h | — |
| G2.2 | Per-band envelope | Is the envelope on the full signal or on frequency bands? | P0 | 1 h | G2.1 |
| **G3** | **Spectral centroid + band analysis** | FFT + band classification. What does the current implementation look like? | P1 | 3 h | — |
| G3.1 | FFT window + overlap | Current FFT size, window, overlap — matches perceptual needs? | P1 | 1 h | — |
| G3.2 | Frequency band definitions | Bass / low-mid / mid / high-mid / high — are they defined? Used where? | P1 | 1 h | — |
| G3.3 | Spectral centroid + roll-off | For music reactivity, these are the canonical features. Are they exposed? | P1 | 1 h | — |
| **G4** | **Beat detection + BPM** | For BPM-locked visual effects. Is there any beat tracking today? | P1 | 3 h | — |
| G4.1 | BPM tracking algorithm | Onset detection + autocorrelation, or a library (librosa / madmom / beats)? | P1 | 1 h | — |
| G4.2 | BPM locking to visuals | If BPM is exposed, what effects consume it? | P1 | 1 h | G4.1 |
| G4.3 | Phase tracking | Per-beat phase for effects that fire on downbeat vs upbeat | P2 | 1 h | G4.1 |
| **G5** | **Transient detection** | Drum hits, sharp attacks. Separated from smooth music? | P1 | 2 h | — |
| G5.1 | Transient detector state | Is there an onset detector today? Where? | P1 | 1 h | — |
| G5.2 | Transient -> visual flash | If a transient fires, does any effect pulse in response? | P1 | 1 h | G5.1 |
| **G6** | **Audio -> visual modulation path** | From extracted features to shader uniforms. What's the wire? | P0 | 3 h | — |
| G6.1 | Feature publisher code paths | Who writes audio features to `/dev/shm/hapax-*`? How often? | P0 | 1 h | G1.3 |
| G6.2 | Compositor + imagination consumer paths | Who reads those features and feeds them into uniforms? | P0 | 1 h | G6.1 |
| G6.3 | End-to-end audio -> visual latency | From hardware mic sample to GPU uniform update — the full budget. Target <50 ms. | P0 | 2 h | F3, G6.2 |
| **G7** | **Audio-reactive preset catalog** | Which of the 28 presets actually react to audio? Which don't? What reacts to what? | P0 | 2 h | — |
| G7.1 | Per-preset reactivity map | For each preset, identify audio-driven uniforms + their source features | P0 | 1 h | — |
| G7.2 | Reactivity gaps | Presets designed to be reactive but with dead audio wiring | P0 | 1 h | G7.1 |
| **G8** | **Perceptual latency budget** | Target: audio event -> visible on-stream <= 50 ms (below human perception of a-v misalignment). | P0 | 2 h | M |
| G8.1 | Total budget breakdown | Hardware -> analysis -> SHM write -> compositor read -> GPU upload -> encode -> RTMP -> viewer | P0 | 1 h | M5 |
| G8.2 | Where is most of the budget spent? | Identify the largest individual stage | P0 | 1 h | G8.1 |

---

## Theme H — Audio ducking + routing

The second half of "perfect audio reactivity." Auto-ducking music when TTS or operator speaks. Mixing for the stream.

| # | topic | research question | priority | depth | depends on |
|---|---|---|---|---|---|
| **H1** | **TTS ducking design** | When daimonion speaks, music should duck. Where would this gate live? | P0 | 3 h | — |
| H1.1 | Current TTS <-> music interaction | Does anything duck music today? `voice-fx-*.conf` — is ducking in there? | P0 | 1 h | — |
| H1.2 | PipeWire sidechain implementation | Can filter-chain's `ladspa` / `lv2` plugin do sidechain compression from TTS bus -> music bus? | P0 | 2 h | F1, H1.1 |
| **H2** | **Mic ducking design** | When operator speaks on Yeti, music ducks. Same pattern as H1, different trigger. | P0 | 2 h | H1 |
| H2.1 | Yeti VAD -> duck envelope | Operator-speech VAD drives a ducking envelope on music | P0 | 1 h | — |
| H2.2 | Hysteresis + release tuning | When operator stops, music comes back. How fast? | P0 | 1 h | H2.1 |
| **H3** | **Sidechain envelope shape** | Target attack/release for ducking. Musical not mechanical. | P1 | 2 h | — |
| H3.1 | Envelope attack | Target: 10-50 ms (faster than human speech onset) | P1 | 30 m | — |
| H3.2 | Envelope release | Target: 200-500 ms (covers natural speech pauses without pumping) | P1 | 30 m | — |
| H3.3 | Soft-knee compression | Not just "on/off" — gradual ducking as speech amplitude rises | P1 | 1 h | — |
| **H4** | **Stream audio mix for OBS** | What does OBS see? One mixed track, or separate tracks? | P1 | 2 h | J6 |
| H4.1 | OBS audio track layout | One monitored track + N unmonitored tracks? Operator preferences? | P1 | 1 h | — |
| H4.2 | Track assignments | Mic -> track 1, TTS -> track 2, music -> track 3, sfx -> track 4 — is this the layout? | P1 | 1 h | H4.1 |
| H4.3 | Per-track levels + EQ | Does OBS apply filters, or is everything pre-mixed upstream? | P2 | 1 h | H4.2 |
| **H5** | **Music source** | Where does music come from? `agents/studio_compositor/youtube_player.py`? Anything else? | P1 | 2 h | — |
| H5.1 | Music source inventory | YouTube player, local files, Spotify via MediaMTX, anything else? | P1 | 1 h | — |
| H5.2 | Music routing | Music PipeWire node -> where? Via filter chain or direct to OBS? | P1 | 1 h | H5.1 |
| **H6** | **End-to-end ducking latency** | Target: operator speaks -> music fully ducked within 30-50 ms. Measure. | P0 | 2 h | H2, G8 |
| **H7** | **TTS output path** | After PR #751, TTS flows through daimonion UDS -> PipeWire. What's the path end-to-end? | P1 | 2 h | — |
| H7.1 | TTS output node inventory | `hapax-voice-fx-capture` + friends — what's the full chain? | P1 | 1 h | — |
| H7.2 | TTS latency from UDS response to speaker | PR #751 had a short-text bug; now fixed in PR #762. Re-measure. | P1 | 1 h | H7.1 |

---

## Theme I — Output + encoding

From the compositor's final output to bytes on the wire. V4L2 loopback, NVENC, HLS, RTMP.

| # | topic | research question | priority | depth | depends on |
|---|---|---|---|---|---|
| **I1** | **V4L2 loopback (/dev/video42)** | The compositor writes to a v4l2loopback device. OBS reads from it. What's the format + bandwidth cost? | P0 | 2 h | — |
| I1.1 | v4l2loopback format | NV12? YUY2? 1920x1080@30? Confirm. | P0 | 30 m | — |
| I1.2 | Zero-copy path | Is the compositor doing a GL->CPU copy to push to v4l2sink? That's expensive. | P0 | 1 h | — |
| I1.3 | Format negotiation with OBS | Does OBS pick the same format the compositor writes? Any re-negotiation? | P1 | 1 h | I1.1 |
| **I2** | **NVENC settings** | Compositor's native RTMP bin uses NVENC p4 low-latency per CLAUDE.md. Is that the right preset? | P1 | 3 h | — |
| I2.1 | NVENC preset tradeoff | p1 fastest -> p7 highest quality. Current is p4. At 1920x1080@30 with 6 Mbps budget, is p4 the sweet spot? | P1 | 1 h | — |
| I2.2 | rate-control mode | CBR / VBR / constqp — which is set? Which matches YouTube's ingest requirements? | P1 | 1 h | — |
| I2.3 | Keyframe interval | Typical 2 s (60 frames at 30fps). Confirm. Impact on viewer seek + reconnect. | P1 | 30 m | — |
| I2.4 | B-frames enabled? | NVENC supports B-frames; do they help here? Latency impact. | P2 | 30 m | — |
| I2.5 | Bitrate audit | What's the configured bitrate? Matches the network upstream? | P1 | 30 m | — |
| **I3** | **HLS playlist generation** | The compositor produces HLS in addition to V4L2. Who consumes it? | P2 | 1 h | — |
| I3.1 | HLS consumer identification | Is anyone actually reading the HLS playlist? OBS? A separate archive? | P2 | 30 m | — |
| I3.2 | HLS overhead if unused | If no consumer, is the HLS output dead weight on the compositor? | P2 | 30 m | I3.1 |
| **I4** | **Native RTMP bin vs MediaMTX relay** | Two output paths. Which one is live? MediaMTX is off per q023 P5. | P1 | 2 h | q023 P5 |
| I4.1 | Current RTMP path | Is the compositor pushing RTMP directly, or through MediaMTX? | P1 | 1 h | — |
| I4.2 | MediaMTX bring-up decision | If MediaMTX is the intended path, why is it off? | P1 | 1 h | — |
| **I5** | **Color space + gamma** | BT.709 everywhere? Any BT.601 holdouts? | P2 | 1 h | — |
| I5.1 | Color space negotiation audit | GStreamer caps + NVENC profile — confirm BT.709 end-to-end | P2 | 1 h | — |

---

## Theme J — OBS integration + scene graph

The operator's control surface. Scene graph, source types, filters, browser sources, encoder pass-through.

| # | topic | research question | priority | depth | depends on |
|---|---|---|---|---|---|
| **J1** | **Scene graph inventory** | How many scenes are configured? What's in each? | P0 | 2 h | — |
| J1.1 | Scene list + composition | Dump the OBS scene collection; for each scene, list the sources | P0 | 1 h | — |
| J1.2 | Scene transition config | Cut? Fade? Custom? Which transitions does the operator use most? | P1 | 30 m | — |
| **J2** | **V4L2 source latency** | OBS reads from /dev/video42. What's the compositor -> OBS frame latency? | P0 | 2 h | I1 |
| J2.1 | Measurement method | Insert a timestamp signal in the compositor output, read it in OBS via a browser source or text | P0 | 1 h | — |
| J2.2 | OBS frame buffer depth | OBS's internal buffering on V4L2 input — how deep? | P1 | 30 m | — |
| **J3** | **OBS -> YouTube encoder** | OBS re-encodes before pushing to YouTube? Or does it pass-through? | P0 | 2 h | I2 |
| J3.1 | OBS encoder settings | Dump OBS profile settings. Match to YouTube ingest recommendations. | P0 | 1 h | — |
| J3.2 | Double-encode cost | If compositor -> NVENC -> OBS -> NVENC again, that's double the quality loss + latency. Avoid it. | P0 | 1 h | J3.1 |
| J3.3 | Single-encode architecture | Can OBS forward the NVENC stream directly without re-encoding? | P1 | 1 h | J3.2 |
| **J4** | **OBS browser sources** | Any browser overlays in use? What do they cost? | P2 | 1 h | — |
| J4.1 | Browser source inventory | List all browser sources + their URLs | P2 | 30 m | — |
| J4.2 | Per-browser CPU cost | CEF is expensive. How much do active browser sources cost? | P2 | 1 h | J4.1 |
| **J5** | **OBS filter chain** | Per-source filters (color correction, chroma key, LUT). What's active? | P2 | 1 h | — |
| **J6** | **OBS audio routing** | Track assignments, monitor settings, per-source audio. | P1 | 2 h | H4 |
| J6.1 | Audio source list | Yeti, desktop audio, TTS, music — each on which track? | P1 | 1 h | — |
| J6.2 | Monitor config | What the operator hears locally vs what goes to stream | P1 | 1 h | J6.1 |
| **J7** | **Scene switch latency** | Operator-triggered scene change -> on-stream visible. How fast? | P1 | 1 h | — |
| **J8** | **OBS plugin audit** | What plugins are installed? Any unused? Any known-flaky? | P2 | 1 h | — |

---

## Theme K — Streaming ingest (YouTube + MediaMTX)

From OBS's RTMP push to the viewer. Wide-area network concerns.

| # | topic | research question | priority | depth | depends on |
|---|---|---|---|---|---|
| **K1** | **YouTube ingest settings** | Live stream vs unlisted vs public; DVR enabled; latency mode | P2 | 1 h | — |
| K1.1 | Low-latency vs ultra-low-latency | YouTube offers both. Which is the current config? | P2 | 30 m | — |
| K1.2 | DVR window | Does the operator want DVR (rewinding) enabled? Latency tradeoff. | P2 | 30 m | — |
| **K2** | **RTMP reconnect resilience** | If the RTMP connection drops, how fast does OBS reconnect? | P1 | 2 h | — |
| K2.1 | Reconnect timing | Measure by killing MediaMTX mid-stream (or equivalent) | P1 | 1 h | — |
| K2.2 | Frame buffering during reconnect | Does OBS buffer frames for post-reconnect flush, or drop? | P1 | 1 h | K2.1 |
| **K3** | **Stream health metrics** | YouTube's health API + OBS's stats. What does "healthy" look like today? | P1 | 2 h | — |
| K3.1 | Current health readout | Dump live stream stats from the OBS stats window during a test stream | P1 | 1 h | — |
| K3.2 | Dropped frames attribution | When frames drop, can we tell whether it's network, encoder, or source? | P1 | 1 h | K3.1 |
| **K4** | **Network + upstream bandwidth** | Is the home upstream a bottleneck? Periodic bandwidth test. | P1 | 1 h | — |
| **K5** | **Secrets hygiene** | Stream key rotation, pass-store location | P3 | 30 m | — |

---

## Theme L — GPU budget + contention

The 3090 is shared by TabbyAPI, hapax-imagination, hapax-dmn, hapax-daimonion, the compositor (via NVENC), and occasionally browser/OBS.

| # | topic | research question | priority | depth | depends on |
|---|---|---|---|---|---|
| **L1** | **VRAM breakdown** | Per-process VRAM use, aggregated. Where's the 24 GB going? | P0 | 2 h | — |
| L1.1 | Live nvidia-smi process map | `nvidia-smi --query-compute-apps=pid,used_memory` — snapshot during typical livestream load | P0 | 1 h | — |
| L1.2 | Per-process caps | Which processes have a hard VRAM cap vs growing over time? | P0 | 1 h | L1.1 |
| **L2** | **Compute contention** | When TabbyAPI inference runs, does compositor NVENC stall? When imagination renders, does TabbyAPI slow? | P0 | 3 h | — |
| L2.1 | Concurrent-load test | Trigger a large TabbyAPI inference while the compositor is active + imagination is rendering. Measure frame drops. | P0 | 2 h | — |
| L2.2 | Scheduling priority | Can TabbyAPI be de-prioritized so it yields to the compositor? | P1 | 1 h | L2.1 |
| **L3** | **NVENC concurrent-encode limit** | Consumer GPUs have a concurrent NVENC session cap. What is it on 3090? What uses sessions? | P1 | 1 h | — |
| L3.1 | Sessions in use | Who holds NVENC sessions? | P1 | 30 m | — |
| L3.2 | Session cap + headroom | Is there margin for another encoder (e.g., a separate recording output)? | P1 | 30 m | L3.1 |
| **L4** | **Thermal throttling** | Under sustained load, does the GPU throttle? At what temp? | P1 | 1 h | A2.1 |
| **L5** | **GPU context switch cost** | Multiple CUDA contexts (TabbyAPI + imagination wgpu + NVENC). Context-switch overhead? | P2 | 2 h | L2 |

---

## Theme M — Latency budgets (per-stage + end-to-end)

Map every stage's cost. Identify the fattest links. Compare against target budgets.

| # | topic | research question | priority | depth | depends on |
|---|---|---|---|---|---|
| **M1** | **Camera -> compositor input** | Kernel -> v4l2src -> first queue -> mixer input pad | P0 | 2 h | B, C |
| M1.1 | Per-camera end-to-end ingest latency | Insert a known-timestamp reference signal, measure at each stage | P0 | 2 h | — |
| **M2** | **Compositor -> effect chain output** | Mixer -> effect chain -> final output pad | P0 | 2 h | D, E |
| M2.1 | Effect chain pass count x per-pass latency | Sum of (pass count x pass cost) | P0 | 1 h | E2 |
| M2.2 | GstLatencyTracer measurement | Run `GST_TRACERS="latency" GST_DEBUG=GST_TRACER:7` on the compositor for 60 s | P0 | 1 h | — |
| **M3** | **Effect chain -> v4l2sink (OBS input)** | Writing to `/dev/video42` | P0 | 1 h | I1 |
| **M4** | **OBS -> YouTube RTMP ingest** | OBS encode + network push + YouTube acceptance | P1 | 2 h | J3, K |
| **M5** | **End-to-end: camera -> viewer** | Operator moves hand -> viewer sees hand. The "mouth to ear" for video. | P0 | 3 h | M1-M4 |
| M5.1 | Anchor measurement | Use a high-contrast visual clap (LED + screen pattern) + external clock | P0 | 2 h | — |
| **M6** | **Audio: mic -> analysis -> visual -> encoder -> ingest** | Target: <50 ms mic-to-visual, <1 s mic-to-ingest | P0 | 3 h | G8, H, J |
| **M7** | **Control: operator -> scene change -> on-stream** | Voice command, keyboard shortcut, or window.__logos call -> on-stream effect | P1 | 2 h | P |

---

## Theme N — Observability end-to-end

Every stage needs a metric surface. Grafana dashboards, Prometheus alerts, log sampling.

| # | topic | research question | priority | depth | depends on |
|---|---|---|---|---|---|
| **N1** | **Per-stage metric surface** | What exists today + what's missing? | P0 | 3 h | q024 FINDING-H |
| N1.1 | Prometheus scrape gap fix | Close the FINDING-H compositor + node-exporter gap (in flight per alpha's current session) | P0 | 30 m | q024 P2 |
| N1.2 | Metric coverage audit | For each pipeline stage, is there at least one Prometheus gauge/counter? | P0 | 2 h | N1.1 |
| N1.3 | New metric tickets | For uncovered stages, file tickets for new counters | P0 | 1 h | N1.2 |
| **N2** | **Grafana dashboard completeness** | `studio-cameras.json` is the compositor dashboard. What else is needed? | P1 | 3 h | N1.1 |
| N2.1 | Current dashboard audit | Dump every Grafana dashboard + check if its queries produce data | P1 | 1 h | — |
| N2.2 | Missing dashboards | Per-node shader timing dashboard, per-camera health dashboard, audio reactivity dashboard, ducking state dashboard | P1 | 2 h | N2.1 |
| **N3** | **Alert rules** | Dead scrape, compositor OOM, imagination crash, audio sample underruns | P1 | 2 h | — |
| N3.1 | Alert rule catalog | Define alerts for every "shouldn't happen" state | P1 | 1 h | — |
| N3.2 | Alert delivery path | ntfy? Email? Desktop notification? | P1 | 1 h | N3.1 |
| **N4** | **Frame-time histograms** | Instead of just mean fps, full p50/p95/p99 histograms with tails | P0 | 2 h | — |
| N4.1 | Histogram metric on compositor | `studio_compositor_frame_time_seconds` histogram | P0 | 1 h | — |
| N4.2 | Histogram on effect chain passes | Per-pass timing from E6.3 | P1 | 1 h | E6.3 |
| **N5** | **Audio-level metering** | RMS, peak, LUFS for each audio source + the stream mix | P1 | 2 h | — |
| N5.1 | Per-source metering | Yeti, contact mic, TTS, music, stream mix | P1 | 1 h | — |
| N5.2 | LUFS integration | Stream-output LUFS compliance (broadcast norm: -14 LUFS) | P2 | 1 h | N5.1 |
| **N6** | **Log sampling** | For high-volume events (shader recompile, frame deliver), sample vs log-all | P2 | 1 h | — |

---

## Theme O — Reliability + recovery

Watchdogs, task supervision, restart orchestration. Everything that keeps the stream alive when a component crashes.

| # | topic | research question | priority | depth | depends on |
|---|---|---|---|---|---|
| **O1** | **Watchdog coverage** | Which components have a watchdog? Which don't? | P0 | 2 h | — |
| O1.1 | Compositor sd_notify watchdog | Already present (Type=notify + WatchdogSec=60 per CLAUDE.md). Is it actually firing WATCHDOG=1? | P0 | 1 h | — |
| O1.2 | OBS watchdog | OBS has no built-in watchdog. Does systemd own it? Is there a per-scene-healthy check? | P1 | 1 h | — |
| O1.3 | PipeWire watchdog | If PipeWire hangs, who notices? | P1 | 1 h | — |
| O1.4 | TabbyAPI watchdog | Model serving stall -> detection + restart | P2 | 1 h | — |
| **O2** | **Restart cascade order** | When the compositor restarts, what downstream consumers need to follow? | P1 | 2 h | — |
| O2.1 | Dependency graph | systemd After= + Requires= audit for the studio stack | P1 | 1 h | — |
| O2.2 | Cold-start penalty | Per component, time from stop -> live | P1 | 1 h | — |
| **O3** | **Graceful degradation** | When one camera dies, what happens to the stream? When reverie dies? When TTS dies? | P1 | 3 h | — |
| O3.1 | Per-component failure cascade | Walk each component's failure -> what's visible on stream | P1 | 2 h | — |
| O3.2 | Degraded-mode banner | Does the stream surface "we're running degraded" somewhere visible? | P1 | 1 h | — |
| **O4** | **Task supervisor implementation** | BETA-FINDING-L fix. Design in queue 026 Phase 1. | P0 | 3 h | BETA-FINDING-L, q026 P1 |
| **O5** | **Rebuild-services coverage** | Cross-ref queue 025 Phase 6: 19 daemons not covered. Fix. | P1 | 2 h | q025 P6 |
| **O6** | **systemd restart storm detection** | If a service restarts N times in M minutes, alert | P2 | 1 h | — |
| **O7** | **Imagination crash storm remediation** | BETA-FINDING-Q. RUST_BACKTRACE (PR #768 landed) + manifest validation + fallback panic handler. | P0 | 4 h | BETA-FINDING-Q |

---

## Theme P — Control surface + interactions

How the operator drives the stream in real time. Scene changes, preset switches, voice commands, keyboard shortcuts.

| # | topic | research question | priority | depth | depends on |
|---|---|---|---|---|---|
| **P1** | **Command registry end-to-end latency** | Voice command "scene.switch studio" -> on-stream visible. Full budget. | P1 | 2 h | — |
| P1.1 | Voice -> command latency | daimonion STT -> tool call -> command registry -> compositor effect | P1 | 2 h | — |
| P1.2 | Keyboard shortcut latency | Logos keyboard adapter -> command registry -> compositor | P1 | 1 h | — |
| P1.3 | MCP call latency | External MCP -> command relay -> compositor | P2 | 1 h | — |
| **P2** | **Preset selection UI** | Chain builder + sequence programmer. What's the interaction cost? | P2 | 2 h | — |
| P2.1 | Chain builder latency | Drag-drop preset chain -> graph-mutation write -> compositor activation | P2 | 1 h | — |
| P2.2 | Sequence programmer cost | Timed auto-cycling through presets | P2 | 1 h | P2.1 |
| **P3** | **Keyboard shortcut audit** | `hapax-logos/src/lib/keyboardAdapter.ts` — what's bound? | P2 | 1 h | — |
| **P4** | **MIDI control surface** | OXI One + hardware mixer. What CCs are wired? | P2 | 2 h | — |
| P4.1 | CC -> effect-param mapping | What does each MIDI CC control? | P2 | 1 h | — |
| P4.2 | Hardware mixer audio routing | PreSonus Studio 24c -> PipeWire inputs | P2 | 1 h | F2.1 |
| **P5** | **Chat -> effect trigger (ChatReactor)** | Keyword detection + 30 s cooldown + preset switch | P2 | 1 h | — |
| P5.1 | Trigger catalog | Which keywords fire which presets today? | P2 | 1 h | — |
| **P6** | **Scene switch latency** | OBS -> YouTube delay for a scene change | P1 | 1 h | J7 |

---

## Cross-cutting concerns

These thread through every theme.

### Content integrity (Q)

- Sierpinski renderer (YouTube frames + Pango markdown) — cost per frame
- Token pole + album overlay — Cairo source cost
- Overlay zones (lyrics, status, credits) — Pango markdown cost
- Stream overlay (banners, alerts) — Cairo source cost
- YouTube player — network fetch cost
- Obsidian content rotation — file watch cost

These are already in Theme D (D3 Cairo source runner). Listed here for visibility.

### Cross-system integration (R)

- Compositor <-> imagination: reverie.rgba SHM handoff (Theme D4)
- Compositor <-> daimonion: TTS UDS, chat reactor, director loop (Theme H, G)
- Compositor <-> VLA: stimmung reads, exploration feed (Theme G, N)
- daimonion <-> operator: voice lifecycle (out of scope here, covered in queues 022-026)

## Research execution sequencing proposal

If the operator green-lights execution, the sensible order is:

### Sprint 1 — Foundations + unblockers (week 1)

Parallelizable. Ship while alpha is wrapping PRs from round 5 backlog.

- **O4** (task supervisor, BETA-FINDING-L) — alpha is already on this from queue 026 P1
- **O7** (imagination crash storm, BETA-FINDING-Q) — critical prerequisite for effect graph work; PR #768 landed step 1 (RUST_BACKTRACE)
- **N1.1** (scrape gap fix, queue 024 FINDING-H) — alpha's current session
- **A1.1 + A1.3** (USB topology + bandwidth) — baseline for everything downstream
- **L1.1** (VRAM breakdown) — foundation for cost modeling

### Sprint 2 — Performance baseline (week 1-2)

Depends on sprint 1's unblockers.

- **C1** (per-camera steady state) — the reference for frame pacing
- **D7** (main output assembly cost) — compositor frame-time baseline
- **E2** (per-node shader cost) — effect graph baseline
- **E6 + E7** (texture pool + hot-reload safety) — imagination stability
- **M5** (end-to-end camera-to-viewer) — the headline metric

### Sprint 3 — Audio reactivity (week 2)

The second target-state half.

- **F1 + F2** (PipeWire graph, audio inputs)
- **G1-G6** (analysis pipeline + modulation path)
- **G7** (preset reactivity map)
- **G8 / M6** (audio -> visual latency budget)

### Sprint 4 — Ducking + routing (week 2-3)

Depends on sprint 3.

- **H1 + H2** (TTS + mic ducking design)
- **H4** (stream mix for OBS)
- **H6** (end-to-end ducking latency)

### Sprint 5 — Output + streaming (week 3)

- **I1-I5** (V4L2 loopback, NVENC, HLS, RTMP, color space)
- **J1-J8** (OBS integration)
- **K1-K4** (YouTube ingest + resilience)

### Sprint 6 — Observability + reliability (week 3-4)

- **N1-N6** (metric surface + dashboards + alerts)
- **O1-O3, O5-O6** (watchdogs + graceful degradation)

### Sprint 7 — Polish + integration (week 4+)

- **P1-P6** (control surface latency)
- **L2-L5** (GPU contention)
- **A2-A5** (physical/thermal/driver — defer unless sprint 1 flagged concerns)

**Total:** ~4 weeks of focused research at full pace, or ~8 weeks sharing time with other work. Priorities within each sprint are P0 first, P1 next, P2 as time permits, P3 deferred.

## Dependencies + unblock prerequisites

Before serious performance research can land on conclusions, the following fixes need to ship (most already in alpha's backlog from round 5):

1. **BETA-FINDING-L task supervisor** — without this, the daimonion could be in a zombie state during measurement and the data would be wrong
2. **BETA-FINDING-Q imagination crash fix** — without this, the imagination daemon resets state every 22 minutes, contaminating any multi-hour measurement. PR #768 shipped step 1.
3. **FINDING-H scrape gap fix (queue 024)** — without this, Prometheus-based observability is blind
4. **BETA-FINDING-K consent reader fix** — shipped (PR #761)
5. **BETA-FINDING-M `_no_work_data` fix** — shipped (merged, per alpha session convergence)

These are in alpha's round 5+ work queue. Research should start in parallel with alpha shipping these.

## Methodology notes

Every topic's research pass should produce:

1. **Evidence.** Reproduction commands + live measurements, not assumed numbers
2. **Baseline.** Current-state values for every metric
3. **Target.** What the ideal value would be, with justification
4. **Gap analysis.** Where current != target, name the gap
5. **Fix proposal.** If a fix exists, specify it with line-level precision
6. **Backlog item.** Add to the cumulative backlog (items 168+)
7. **Dashboard candidate.** If the finding warrants a live metric, propose the series shape

Scientific register throughout (per `feedback_scientific_register.md`). Neutral, impartial. Facts + citations + reproduction commands + `[inferred]` flags where inference replaces measurement.

## What's intentionally NOT in this map

- **Content creative decisions.** What the effects should look like aesthetically is not a performance question.
- **Model routing + LLM behavior.** Covered by queues 022-026.
- **Governance axioms.** Covered by queue 025 Phase 1.
- **Session management / voice daemon lifecycle.** Covered by queue 022-025 Phase 3 + 5.
- **Obsidian plugin** (except as it relates to content rotation into the compositor's ground surface).
- **Hardware procurement recommendations.** Research characterizes, doesn't spec out new purchases.
- **Stream-production value-judgments.** Whether to add a specific effect or scene, how to handle sponsor integrations, etc.

## Next action

This is the map. Nothing in it has been executed yet.

**Operator decision point**: approve the map, adjust priorities, or request a different structure. On approval, execution sequencing above kicks off starting with sprint 1. Sprint 1 is parallelizable with alpha's ongoing round-5 backlog execution; later sprints depend on sprint 1's unblockers landing first.
