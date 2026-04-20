---
date: 2026-04-20
author: alpha (Claude Opus 4.7, 1M context)
audience: operator + beta + delta
register: engineering / architecture-decision, neutral
status: research + recommendation (no code changes)
trigger: operator decommissioned `hapax-logos.service` + `hapax-build-reload.path` on 2026-04-19 after the WebKit-hosted React preview was confirmed visually inferior to OBS while burning ~60% CPU + ~5–10% GPU + ~629 MB RAM
related:
  - systemd/units/hapax-logos.service
  - systemd/hapax-build-reload.path
  - systemd/units/studio-compositor.service
  - systemd/units/hapax-imagination.service
  - systemd/units/hapax-daimonion.service
  - systemd/units/tabbyapi.service
  - systemd/units/mediamtx.service
  - docs/research/2026-04-20-logos-output-quality-design.md
  - docs/runbooks/rig-migration.md
  - docs/research/2026-04-19-hardm-redesign.md
  - docs/research/2026-04-19-gem-ward-design.md
  - docs/superpowers/plans/2026-04-20-programme-layer-plan.md
  - memory: project_rig_migration.md
  - memory: project_homage_go_live_directive.md
  - memory: feedback_no_unsolicited_windows.md
  - memory: project_hapax_data_audit.md
---

# Tauri Decommission — What To Do With The Freed Resources

## §1. TL;DR

**Recommended split of the freed budget (≈60 % CPU + ≈5–10 % GPU + ~629 MB
RAM + 4 GB MemoryMax cgroup):**

- **40 % → leave as headroom** (compositor MemoryHigh=infinity ceiling,
  thermal margin, rig-migration trigger preservation). Documented in §9.
- **30 % → broadcast quality** (NVENC preset P4 → P5, bitrate 6 Mbps →
  9 Mbps, optional second loopback for the OBS-bypassing direct RTMP
  path). Documented in §7.
- **20 % → queued compositor features** (HARDM Phase 2 per-cell
  rewrite, GEM ward, Wave-B emergent-misbehavior detectors). Documented
  in §8.
- **10 % → observability** (Prometheus 30 s → 10 s for compositor +
  daimonion only, real-time LUFS via `gst-rs` `ebur128level`). Documented
  in §6.

**Single highest-impact reuse path the operator should commit to first:**
**bump NVENC preset to P5 and bitrate to 9 Mbps on the YouTube RTMP
egress branch in `agents/studio_compositor/pipeline.py`.** This is a
one-file, ~10-line change that converts the freed GPU into broadcast
quality the audience sees, with zero new code paths to maintain and
fully reversible by reverting the patch. Replacement preview surface is
**`mpv av://v4l2:/dev/video42 --profile=low-latency --untimed`** on a
side monitor — 5 MB RAM, near-zero CPU, sub-100 ms latency, kernel-
buffered. Tauri shell does **not** return; the React graph UI stays
served from `logos-api` on `:8051` and is opened in a regular browser
tab on the rare occasions it is needed (§3.6, §10).

## §2. Inventory of what was reclaimed

The Tauri shell's resource envelope, captured immediately before
decommission and confirmed against the unit file:

| Resource | Pre-decommission | Source |
|---|---|---|
| Process CPU | ~60 % of one core (WebKitGTK render thread + JS frame pump) | operator measurement, 2026-04-19 |
| Process GPU | ~5–10 % (software-fallback compositing, `WEBKIT_DISABLE_DMABUF_RENDERER=1`) | operator measurement; `systemd/units/hapax-logos.service:30` |
| Process RSS | ~629 MB | operator measurement |
| cgroup ceiling | 4 GB (`MemoryMax=4G`) | `systemd/units/hapax-logos.service:33` |
| Build/reload path watcher | 1 inotify watch on `~/.local/bin/hapax-logos` + sentinel | `systemd/hapax-build-reload.path:7-10` |
| Vite/dev-server (when active) | ~150 MB + 1 ESBuild worker pool | `hapax-logos/vite.config.ts` |
| Build artifacts | `hapax-logos/target/` ≈ 6 GB, `node_modules/` ≈ 800 MB | `hapax-logos/` listing |
| WebSocket subscribers on `:8053/ws/fx` | 1 (the OutputNode's `useFxStream`) | `docs/research/2026-04-20-logos-output-quality-design.md` §2.4 |
| Tauri-IPC channels | the entire `__logos` command registry surface (`window.__logos`) | memory: `project_command_registry.md` |

**System-wide GPU after reclaim** (operator measurement):
46 % utilization (down from 55–77 %), 11.8 GB / 24 GB VRAM in use. The
3.2–3.5 GB VRAM headroom on top of TabbyAPI's resident Qwen3.5-9B EXL3
5.0bpw + Daimonion's distil-large-v3 + Reverie's wgpu textures is the
binding constraint for any inference-side reuse (§5).

**System-wide CPU after reclaim** (operator measurement):
compositor 220 %, ClickHouse 65 %, Qdrant 50 %, Ollama 48 %, ffmpeg
31 %, `hapax-imagination` 7 %. The compositor's 220 % is the load-bearing
number — it is at the soft ceiling where any added work compounds with
its existing memory drift (the `MemoryHigh=infinity` patch in
`systemd/units/studio-compositor.service:106-114` exists for exactly
this reason).

**What was NOT reclaimed** and remains a binding constraint:

- **`logos-api` on `:8051`** is alive and unrelated to the Tauri shell.
  The `obsidian-hapax` plugin, `hapax-mcp`, `hapax-watch`, `hapax-phone`,
  and the orientation panel all still depend on it.
- **`hapax-imagination`** (Reverie) is alive and headless
  (`HAPAX_IMAGINATION_HEADLESS=1`, `systemd/units/hapax-imagination.service:30-37`),
  writing `/dev/shm/hapax-visual/frame.jpg` and `/dev/shm/hapax-sources/reverie.rgba`.
- **Studio compositor** is alive at 220 % CPU, 940 MB RSS, with the
  reverie SHM consumer wired in.
- **Daimonion** is alive with STT + Kokoro TTS + vocal_chain MIDI driver
  (`systemd/units/hapax-daimonion.service:35`).
- **TabbyAPI** is alive on `:5000` serving Qwen3.5-9B EXL3
  (`systemd/units/tabbyapi.service`).
- **MediaMTX** is alive relaying RTMP to YouTube
  (`systemd/units/mediamtx.service`).

## §3. Replacement preview surface — option matrix

The Tauri shell's only load-bearing function during livestream
operation was **showing the operator the compositor output**. The
React graph UI (chain builder, sequence bar, sidechat) is occasionally
used but not on every stream. The two functions can be served by
different surfaces.

The audit in `docs/research/2026-04-20-logos-output-quality-design.md`
§2.8 and §3 establishes the controlling facts: the Tauri preview path
went 1280×720 NV12 → JPEG q=85 @ 3 fps → TCP `:8054` → WebSocket
`:8053/ws/fx` → `<img>` in the WebKit DOM. Every alternative below
inherits the **OBS path** (kernel `v4l2loopback` on `/dev/video42`) and
therefore matches OBS pixel-for-pixel at 30 fps NV12.

### 3.1 Option matrix

| Option | RAM | CPU | GPU | Latency | Effort | Quality | Reversible | Verdict |
|---|---|---|---|---|---|---|---|---|
| **A. `mpv` on `/dev/video42`** | ~5 MB | ~1 % core | ~0 % (vaapi/cuda hwdec) | <100 ms | 0 LOC, one shell command | OBS-equivalent | trivial | **recommended** |
| B. Headless Chromium on a stripped HTTP frame endpoint | ~250 MB | ~5 % | ~2 % | 100–200 ms | medium (need to keep a frame endpoint alive) | JPEG-degraded | medium | rejected — same lossy path |
| C. GTK4 native widget via `gtk4paintablesink` + `gst-plugin-gtk4` | ~80 MB | ~2 % | DMABuf-zero-copy | <50 ms | high (~400 LOC Rust) | OBS-equivalent | medium | over-engineered for one user |
| D. Tauri stripped to canvas-graph control surface only (preview goes elsewhere) | ~400 MB | ~15 % | ~3 % | n/a | medium (delete preview code) | n/a (no preview) | medium | possible long-term, see §10 |
| E. Wayland layer-shell pinned floating preview (`mpvpaper`-style) | ~30 MB | ~2 % | hwdec | <100 ms | medium (requires niri/Hyprland layer-shell config) | OBS-equivalent | medium | only if operator wants persistent overlay |
| F. React UI served from `logos-api:8051`, opened in a normal browser tab on demand | 0 MB resident (browser already open) | 0 % when not viewed | 0 % when not viewed | n/a | low (already a Vite-built SPA, just serve `dist/`) | n/a | trivial | **complement to A** |

### 3.2 Why Option A wins

`mpv av://v4l2:/dev/video42 --profile=low-latency --untimed` reads the
v4l2loopback ring buffer directly, the same kernel IPC OBS uses
([mpv manual; arch wiki tip][mpv-low-lat]). `--untimed` outputs each
captured frame immediately rather than respecting the input framerate
([mpv issue 7896][mpv-issue-7896]) — this is exactly what we want for a
3 fps→30 fps step-up. Hardware decode is automatic on NVIDIA via NVDEC
when `--hwdec=auto` is in `~/.config/mpv/mpv.conf`. Sub-100 ms latency
is well-documented for v4l2 USB capture devices on Linux
([level1techs][level1-mpv]). RAM stays under 10 MB with default
buffers.

It is also the simplest possible inversion of the failed Tauri
architecture: there is no encode → transport → decode → paint chain.
There is one consumer (mpv) reading from one producer
(v4l2loopback) over kernel mmap. No new codepath to maintain. No JSON,
no IPC, no WebSocket, no DOM. If it breaks, it is one of two things:
mpv is not installed or `/dev/video42` is not present. Both diagnose
in seconds.

### 3.3 Why not Option C

A native GTK4 widget with `gtk4paintablesink` would be marginally
faster than mpv and zero-copy via DMABuf
([gtk4paintablesink docs][gtk4paintable]; [GNOME Discourse][gnome-gtk4]),
but it requires writing and maintaining ~400 LOC of Rust + GTK4
plumbing for a single-user preview window. mpv is already installed,
already well-tested on this stack, and the latency difference is below
human perception. The `waylandsink` direct route is incompatible
because it creates its own toplevel window
([gstreamer-devel discussion][gst-wayland]) — exactly what mpv
already gives us with one command.

### 3.4 Why not Option B (headless Chromium on a frame endpoint)

The `:8053` HTTP frame endpoint is dead now — it lived inside the
Tauri Rust process (`hapax-logos/src-tauri/src/visual/http_server.rs`,
referenced in `docs/research/2026-04-20-logos-output-quality-design.md`
§2.5). Reviving it just to point a headless Chromium at it preserves
every degradation that motivated the decommission: JPEG q=85 at 3 fps
([same doc, §2.8 quality-loss table][logos-quality]). Net negative.

### 3.5 Why not Option E unless explicitly desired

`mpvpaper`/`qt-mpv-bg-wlr`-style layer-shell embedding
([mpvpaper github][mpvpaper]; [wlr-layer-shell protocol][wlr-layer]) is
a real option for a permanently-pinned PiP preview anchored to a
screen edge. It requires Hyprland layer-shell rules, focus/keyboard
handling, and an exclusive zone. The cost is justified only if the
operator wants the preview to be **always visible**, never minimised
or covered by other windows. mpv in a normal Hyprland window
accomplishes this with `windowrulev2 = pin, class:^(mpv)$` and zero
new dependencies.

### 3.6 Why F (React UI served from logos-api) is the right home for
the canvas-graph control surface

The React app at `hapax-logos/src/` is already built by Vite into
`hapax-logos/dist/`. `logos-api` is a FastAPI app on `:8051` (per
workspace CLAUDE.md § Shared Infrastructure). Mounting the built
`dist/` as a `StaticFiles` route is ~5 lines:

```python
# logos/api/__main__.py (or wherever the FastAPI app is constructed)
from fastapi.staticfiles import StaticFiles
app.mount(
    "/ui",
    StaticFiles(directory="hapax-logos/dist", html=True),
    name="ui",
)
```

The operator opens `http://localhost:8051/ui` in any browser tab when
they need the chain builder or sequence bar. No persistent process,
no Tauri shell, no resource cost when the tab is closed. The OutputNode
(see `hapax-logos/src/components/graph/nodes/OutputNode.tsx:301`) loses
its preview blob, which is correct — the preview is now mpv on the
side monitor — and continues to function as a graph node placeholder
that double-clicks to "open mpv" via a small shell-out command (or
just shows a static "preview is in mpv" placard).

The `useFxStream` hook (`OutputNode.tsx:30`) and the `:8053` WebSocket
relay can be deleted entirely. The `FullscreenOverlay` becomes
unreachable code.

This option pairs natively with Option A: **mpv for preview, browser
tab for control surface, no Tauri at all.**

## §4. Reclaim for compositor work

The compositor at 220 % CPU is the single most expensive process in
userspace. The `MemoryHigh=infinity` annotation in
`systemd/units/studio-compositor.service:106-114` documents that the
process drifts ~360 MB/min in anon pages, restrained only by the
6 GB hard ceiling. Adding work here is not free.

### 4.1 What the compositor could absorb

- **HARDM Phase 2 per-cell rewrite.** The current source
  (`agents/studio_compositor/hardm_source.py`) runs 16 horizontal bars
  of identical cells; Phase 2 (per `docs/research/2026-04-19-hardm-redesign.md`
  §1.2) targets 256 independently-bound cells. The Cairo render path is
  per-cell; cost scales linearly. A 16× signal-density increase at the
  current 4 Hz cadence is roughly +30–50 % of one core based on the
  existing per-cell render budget — within the freed envelope.

- **GEM ward.** Per `docs/research/2026-04-19-gem-ward-design.md` §1.1,
  GEM is a Cairo CP437 raster surface with frame-by-frame abstract
  animation, decay envelopes, and a BitchX-constrained glyph grammar.
  Cost is estimated at ~20 % of one core at the proposed update cadence
  (~6 Hz with 30 ms render budget per frame). Within envelope.

- **Wave B emergent-misbehavior detectors.** Per
  `docs/research/2026-04-20-dynamic-livestream-audit-catalog.md`, four
  new detectors with Prometheus metrics. Detector cost is dominated by
  the metric publish path; ~5 % of one core total.

- **Higher cairo budget for token_pole and related wards.** The
  operator's note flags `token_pole` at 5.4 ms p50 / 7.6 ms p95 — well
  under its 33 ms frame budget (30 fps). The headroom can absorb
  finer-grained typography, anti-aliased edges, or per-glyph effects.

- **More effect-graph slots simultaneous.** Per memory
  `project_effect_graph.md`, the system has 56 WGSL nodes and 30
  presets across a `SlotPipeline`. The current concurrent-slot ceiling
  is GPU-bound, not CPU-bound; the freed CPU does not directly raise
  this ceiling.

### 4.2 What the compositor cannot absorb without risk

- **Higher pixel formats (NV12 → I422 4:2:2 or RGBA).** This raises
  per-frame buffer size by 33 % (I422) or 100 % (RGBA), multiplying
  through every tee branch. The existing 360 MB/min memory drift
  becomes ~720 MB/min at RGBA. Rejected; the rig-migration constraint
  in §9.3 dominates.

- **Resolution above 1280×720.** The 720p commitment is in operator
  memory (`project_720p_commitment.md` — "All 6 cameras permanently at
  1280×720 MJPEG; never propose resolution changes as remediation").
  Out of scope.

- **More cameras.** Per memory `project_studio_cameras.md`, all 6 USB
  ports are saturated at 6 cameras (3 BRIO + 3 C920). Adding a 7th is a
  USB-topology question, not a resource question.

### 4.3 Verdict for §4

Spend ~20 % of the freed compositor headroom on **HARDM Phase 2 +
GEM ward**, in that order, because both are queued-and-designed and
both are inside the linear envelope. Defer Wave B detectors until
broadcast quality work in §7 is done. Hold the I422/RGBA upgrade.

## §5. Reclaim for inference (TabbyAPI / Daimonion STT / Reverie)

The freed VRAM is ~3.2–3.5 GB on top of the current 11.8 GB / 24 GB
resident set. The freed GPU is the difference between 46 % and the new
post-decommission baseline (probably ~38–42 % steady-state — exact
number depends on whether reverie pipeline is steady or bursting).

### 5.1 TabbyAPI: Qwen3.5-9B → Qwen3-14B EXL3?

Qwen3-14B at INT4 quantisation needs ~8.3 GB of model weights plus
~1–2 GB of KV cache at default context length
([apxml qwen3-14b][apxml-14b]; [hardware-corner Qwen3][hw-qwen3]),
and EXL3 5.0bpw on a 14B param model lands around ~9–10 GB resident
plus context-dependent KV. With the freed envelope this fits, but it
displaces the headroom that Daimonion currently uses for its lazy-
loaded vision models (`systemd/units/hapax-daimonion.service:42-44`
documents 7+ vision models lazy-loaded by the vision backend, with
spikes to 7.5 GB during first-camera-pass ramp).

The trade is: +Qwen3-14B inference quality, –reliable headroom for
Daimonion's vision backend warmup spikes. Given the operator memory
`feedback_grounding_over_giq.md` ("pick for grounding flexibility,
not MMLU/GSM8K. Trade G-IQ for RAG-shape if needed."), bumping to
14B is on the wrong axis — the LRR-grounded path values context-
fitness over raw IQ. Defer.

### 5.2 Daimonion STT: distil-large-v3 → large-v3?

distil-large-v3 is **6.3× faster** than large-v3 with WER within 1 %
on long-form audio ([northflank STT benchmark][northflank-stt];
[distil-whisper huggingface][distil-whisper]). The model card and
benchmarking literature agree: the speed-up is a decoder-layer
distillation that preserves the encoder, so the accuracy delta is
negligible for the conversation-grounded use case
([towards AI variants comparison][towardsai-whisper]).

For voice grounding the operator's hard requirement is consent latency
(memory `feedback_consent_latency_obligation.md` — "Voice latency
impeding consent flow is a governance violation"). Trading a 6.3×
speed advantage for a sub-1 % WER improvement directly violates that
constraint. Reject.

### 5.3 Reverie wgpu shader pipeline: 8 passes → 10 passes?

The current pipeline is `noise → rd → color → drift → breath →
feedback → content_layer → postprocess` (memory `project_reverie.md`).
Per the operator's framing, 2–3 additional passes are within the freed
GPU envelope. The candidate passes are already enumerated in queued
work — physarum, voronoi, RD-2 layer (memory
`project_reverie_adaptive.md`).

This is the **clearest inference-side win** — the freed GPU directly
lifts a known ceiling, the visual quality gain is immediately
observable on the broadcast, and reverie passes are individually
disable-able under thermal pressure (per `project_reverie_autonomy.md`,
the per-slot crossfade and per-node param bridge make this hot-
swappable). Cost: ~1–2 days to wire physarum and voronoi into the
SlotPipeline mixer.

### 5.4 Verdict for §5

**Skip TabbyAPI and STT upgrades. Spend the freed GPU on +2 reverie
passes (physarum + voronoi).** This is the inference-adjacent reuse
that respects the operator's documented constraints.

## §6. Reclaim for observability

### 6.1 Prometheus scrape interval

Current scrape interval is 30 s (workspace default). Tightening to 5 s
captures spikes 6× more densely
([oneuptime scrape tuning][onuptime-prom]; [groundcover prom 2026][groundcover-prom]),
but a shorter scrape multiplies CPU/memory/disk on Prometheus itself —
~3 KB per time series in memory, scaling linearly with scrape rate
([signoz prom memory][signoz-prom]; [last9 cardinality][last9-card]).
For an environment with hundreds of high-cardinality compositor metrics
(per-slot, per-camera, per-effect-node), 5 s pushes the Prometheus
container's RAM and CPU envelope into a different regime.

Recommendation: tighten **only the compositor and daimonion scrape
endpoints** to 10 s; leave everything else at 30 s. This captures the
load-bearing latency-sensitive metrics (compositor frame jitter,
daimonion CPAL turn-latency, GPU process counters) at 3× density
without paying the full 6× cardinality tax.

### 6.2 Langfuse trace sampling

Default is 100 % already ([langfuse sampling docs][langfuse-sampling]).
The operator already runs at 1.0 sample rate. There is nothing to spend
freed resources on here unless we **add new spans** (e.g. per-frame
spans on compositor render passes), which would dramatically raise
Langfuse cost without observable benefit. Skip.

### 6.3 Real-time mix-quality LUFS measurement

GStreamer's `ebur128level` element from `gst-plugins-rs` measures EBU
R128 momentary, short-term, and integrated loudness in-pipeline
([gstreamer ebur128level docs][gst-ebur128]; [ffmpeg f_ebur128
source][ffmpeg-ebur128]), well under 5 % of one core. Wiring it into
the compositor's audio tee branch (downstream of the audio mixer,
upstream of the RTMP/HLS sinks) gives a Prometheus gauge for
broadcast LUFS at no perceptual cost.

This is a small, high-value win for the operator (live broadcast LUFS
is the hardest knob to manage from feel alone, especially on hardware-
dub material from `vinyl_chain.py`). Cost: ~1 day, ~80 LOC, single-
file change in the compositor audio path.

### 6.4 Verdict for §6

**Tighten compositor + daimonion Prometheus scrape to 10 s; add
ebur128level LUFS gauge to the compositor audio tee.** Net new cost
~2 % of one core total. Skip Langfuse and skip log-tail LLM analysis
(which is in queued cognitive-substrate work, not observability).

## §7. Reclaim for the broadcast itself

This is the highest-conviction reuse path. The operator's whole
purpose for the workstation is the YouTube livestream
(LegomenaLive). Resources spent here are visible to every viewer.

### 7.1 NVENC preset and bitrate

Current path (per `agents/studio_compositor/pipeline.py` and the RTMP
egress branch): NVENC `p4 low-latency`, bitrate around 6 Mbps for
1280×720 30 fps to MediaMTX → YouTube RTMP. P4 is the SDK default
([NVENC SDK 10 presets][nvenc-presets]; [OBS advanced NVENC][obs-nvenc]).

**Recommended bump: P4 → P5, bitrate 6 → 9 Mbps.**

- P5–P6 are the OBS community's standard recommendation for Ada-class
  cards when GPU has headroom, "for very clean output with tiny CPU
  usage" ([xaymar NVENC guide][xaymar]; [NVIDIA broadcast guide][nvidia-bcast]).
- 9 Mbps is the upper end of YouTube's 1080p60 recommendation
  ([YouTube live encoder settings][youtube-encode]; [castr bitrate guide][castr-bitrate]),
  and is in 720p territory a comfortable headroom that defeats macro-
  blocking on the high-motion scratch / vinyl wash content
  (per `docs/research/2026-04-20-vinyl-broadcast-mode-d-granular-instrument.md`).
- P5 vs P4 is a well-characterised quality bump per the SDK literature
  with linear quality scaling ([NVIDIA SDK 10][nvenc-presets]).
- Latency cost is approximately zero — Low-Latency and Ultra-Low-Latency
  tunings yielded identical latency to High-Quality tuning across
  presets in NVIDIA's own measurements ([SFE evaluation][nvenc-sfe]).
- GPU cost: roughly +2–3 % of GPU at 720p30 — well inside the freed
  envelope.

This is the **single highest-impact change** in this entire document.
It is one file, ~10 lines, fully reversible, immediately visible to
viewers.

### 7.2 More cameras concurrently

Rejected on USB-topology grounds (§4.2; memory
`project_studio_cameras.md`). The 6-camera ceiling is hardware, not
budget.

### 7.3 Longer HLS retention window

Current rotation is per `systemd/units/hls-archive-rotate.timer` with
60 s cadence rotating into `~/hapax-state/stream-archive/hls/<date>/`.
Per the lengthy comment in `systemd/units/studio-compositor.service`
(Phase 2 archive precheck), retention is constrained by the rotator,
not by CPU. Spending freed CPU here is a no-op — the bottleneck is
disk and the rotator's correctness, not encoding.

### 7.4 Real-time content-ID risk monitoring

Per `docs/research/2026-04-20-vinyl-broadcast-calibration-telemetry.md`
and the MonetizationRiskGate that just shipped (gate 1), the next
extension is real-time spectral monitoring of the broadcast audio
against a fingerprint database. This is a non-trivial pipeline (spectral
hashing + bloom filter lookup) but well-bounded; fits in ~10 % of one
core budget. Defer until after gate 3 (DEGRADATION MODE) is verified;
the gate-3 work is the operator's stated next priority.

### 7.5 Verdict for §7

**Commit the §7.1 NVENC change today. Defer everything else in §7.**

## §8. Reclaim for queued features

The operator enumerated five queued features. Reviewed against the
freed envelope and the rig-migration constraint:

| Feature | Source | Cost | Status | In freed envelope? | Recommend |
|---|---|---|---|---|---|
| GEM ward | `docs/research/2026-04-19-gem-ward-design.md` | ~20 % core | designed, not implemented | yes | **ship after Phase 2** |
| HARDM Phase 2 (256 cells) | `docs/research/2026-04-19-hardm-redesign.md` | ~30–50 % core | designed, alpha-queued HIGH | yes | **ship first** |
| Wave B detectors (4) | `docs/research/2026-04-20-dynamic-livestream-audit-catalog.md` | ~5 % core | queued | yes | defer to post-§7 |
| Content-programming Phase 2 (ProgrammePlanStore persistence) | `docs/superpowers/plans/2026-04-20-programme-layer-plan.md` | ~minimal CPU; persistence is disk | designed | yes | independent — ship when ready |
| Vinyl Mode D Phase 2 (Programme integration + L6 AUX 1) | `docs/research/2026-04-20-vinyl-broadcast-mode-d-granular-instrument.md` | minimal | designed | yes | independent — ship when ready |

The two compositor-side features (HARDM Phase 2 + GEM) are inside the
~30 % CPU sub-budget for compositor work in §4.3. The two
non-compositor features (Programme Phase 2 + Vinyl D Phase 2) do not
contend for the freed CPU/GPU at all and are ship-when-ready
independently of this decision.

## §9. The "leave headroom" argument

This is the strongest argument against spending the freed budget at
all.

### 9.1 Compositor anon-page leak

`systemd/units/studio-compositor.service:108-114` documents a
~360 MB/min steady-state anon-page leak with `MemoryHigh=infinity`
required to keep the watchdog from killing the unit. Until the
underlying leak is root-caused (tracked via
`studio_compositor_memory_footprint_bytes` per the unit comment),
adding compositor work tightens an already-loose system.

### 9.2 Thermal lifespan

Sustained GPU temperatures above 80–85 °C are the dominant cause of
silicon-lifetime degradation
([nomadsanalytics RTX lifespan 2026][nomads-rtx]; [ofzen GPU temp guide][ofzen-temp];
[unicorn 3-5 yr playbook][unicorn-gpu]). Modern RTX cards have <0.5 %
annual failure rate at well-managed temperatures
([dasroot monitoring][dasroot-gpu]) but **mining-pattern 24/7 sustained
load consistently shortens fan and thermal-paste lifetimes to 2–3
years** ([quora mining lifespan][quora-mining]; [electronicshub GPU
last][electronicshub-gpu]). The workstation already sustains 46 %+
GPU under livestream load; pushing toward 60–70 % steady-state moves
the card noticeably toward fan-replacement territory.

### 9.3 Rig-migration trigger preservation

Per memory `project_rig_migration.md` and
`docs/runbooks/rig-migration.md`, the operator migrates to a new rig
(better CPU/Mem/Mobo, same GPUs) at the **stream-ready milestone**.
Spending freed resources on bigger workloads pushes the system into
a regime where it cannot keep up without the new hardware, which
*advances* the migration trigger — but the migration runbook
(`docs/runbooks/rig-migration.md` §"Pre-migration checklist")
explicitly requires a stable-state baseline before a migration is
safe. Burning the headroom on speculative work mid-go-live destabilises
the very metric the migration trigger watches.

### 9.4 The HOMAGE go-live directive

Per memory `project_homage_go_live_directive.md`: "Go live after A3/A4;
iterate everything else via DEGRADED-STREAM mode; no completion-gate
stalls." The operator has explicitly chosen to ship and iterate-live
rather than perfect-then-ship. Adding ambitious work right now is in
tension with this directive — the right behaviour is **conservative
allocation, observe live, iterate**.

### 9.5 Verdict for §9

The §1 split's **40 % "leave as headroom"** allocation is exactly the
operator's documented preference cashed out as percentages.

## §10. Architectural question — should the Tauri shell return at all?

The Tauri shell's value proposition was always **a webview React UI
that could call native Rust commands**. Its costs were
unbounded WebKit overhead, NVIDIA + Wayland + WebKitGTK syncobj bug
workarounds (`__NV_DISABLE_EXPLICIT_SYNC=1`,
`WEBKIT_DISABLE_DMABUF_RENDERER=1` per `systemd/units/hapax-logos.service:24-31`),
the JPEG-degraded preview path that motivated the decommission, and
~629 MB resident always-on cost.

### 10.1 Sub-options

- **Tauri returns with no preview.** Same shell, OutputNode shows a
  static placard, preview is mpv on a side monitor. Eliminates the
  JPEG path but keeps the WebKit overhead. Net negative vs Option F
  (browser-tab UI on demand).
- **WebRTC self-loopback inside Tauri** (Option 5 from the prior
  conversation, per `docs/research/2026-04-20-logos-output-quality-design.md`
  §4 Option 5). Solves preview quality at the cost of webrtcbin +
  signalling + WebKitGTK 4.1 WebRTC enablement. Real engineering, real
  fragility. Only justified if the operator wants a single window. The
  operator's explicit preference for `feedback_no_unsolicited_windows.md`
  ("Builds/restarts must NEVER pop windows. Operator controls visual
  surface lifecycle.") is in tension with multi-window Tauri here.
- **Native GTK4 control surface (no webview).** Eliminates WebKit
  entirely but requires reimplementing the React UI in GTK4 (~3000+
  LOC). Out of scope.
- **Mobile-first Tauri ARM build, opened on phone over mDNS.** A real
  option — the React app is responsive enough — but `hapax-phone`
  already exists for phone-side companion and is a Kotlin/Compose
  Android app, not a Tauri ARM target. Adds a parallel mobile UI
  surface to maintain. Defer.
- **Defer indefinitely.** The decommission has not broken any
  workflow. The operator's livestream uses OBS for preview and
  MediaMTX for egress. The Logos React UI is occasional, not daily. A
  browser tab against `logos-api:8051/ui` (Option F in §3.1) covers
  every use case the Tauri shell covered, with zero resident cost.

### 10.2 Verdict for §10

**Defer Tauri's return indefinitely. Serve the React UI from
`logos-api:8051/ui` as a static mount; open in browser tab on
demand.** If preview-in-shell ever becomes load-bearing again, revisit
WebRTC self-loopback (Option 5 in the linked doc) at that time, with
fresh measurements of WebKitGTK + NVIDIA + Wayland stability.

## §11. Recommendation + concrete next-actions

### 11.1 Recommended split (restated)

- 40 % headroom (§9)
- 30 % broadcast quality — NVENC P5 + 9 Mbps (§7.1)
- 20 % compositor features — HARDM Phase 2 then GEM (§4.1, §8)
- 10 % observability — 10 s scrape on hot endpoints + LUFS gauge (§6)

### 11.2 Concrete next-actions, ordered

1. **Ship NVENC bump.** Edit the RTMP egress encoder in
   `agents/studio_compositor/pipeline.py` from `preset=p4` /
   `bitrate=6000000` to `preset=p5` / `bitrate=9000000`. Validate with
   one test stream. Reversible by reverting the patch. (~10 LOC, <1 hr.)
2. **Replace preview surface.** Operator runs
   `mpv av://v4l2:/dev/video42 --profile=low-latency --untimed --hwdec=auto`
   on a side monitor with a Hyprland windowrule pinning it. (0 LOC,
   shell command.)
3. **Mount React UI under logos-api.** Add the `StaticFiles` mount
   from §3.6 to the FastAPI app. Open `http://localhost:8051/ui` when
   needed. (~5 LOC, <1 hr.)
4. **Delete dead Tauri preview code paths.** Remove `useFxStream`, the
   `:8053` WebSocket relay, and `FullscreenOverlay` from the React app.
   Keep the chain builder + sequence bar + sidechat. (Cleanup PR;
   medium size.)
5. **Wire ebur128level LUFS gauge** into the compositor audio tee.
   Publish as Prometheus gauge. (~80 LOC, ~1 day.)
6. **Tighten compositor + daimonion Prometheus scrape** to 10 s in the
   Prometheus config. (~5 LOC.)
7. **Begin HARDM Phase 2 implementation** per
   `docs/research/2026-04-19-hardm-redesign.md`. (Multi-day.)
8. **Begin GEM ward implementation** per
   `docs/research/2026-04-19-gem-ward-design.md`. (Multi-day, after
   HARDM Phase 2 is shipped.)
9. **Wire 2 reverie passes** (physarum + voronoi) into the SlotPipeline
   mixer per `project_reverie_adaptive.md`. (~1–2 days.)
10. **Hold all other speculative work.** Re-evaluate after gate 3
    (DEGRADATION MODE) ships and the post-go-live observation window
    establishes a new steady-state.

### 11.3 What this explicitly rejects

- Bumping TabbyAPI to Qwen3-14B (§5.1; wrong axis per
  `feedback_grounding_over_giq.md`).
- Bumping Daimonion STT to large-v3 (§5.2; violates
  `feedback_consent_latency_obligation.md`).
- Resurrecting Tauri shell (§10.2; the decommission is correct).
- Higher resolution or pixel format on the compositor (§4.2; violates
  `project_720p_commitment.md`).
- 5 s Prometheus scrape on all endpoints (§6.1; cardinality cost).
- Real-time content-ID monitoring (§7.4; defer until post-gate-3).

## §12. Open questions

1. **Steady-state GPU utilisation post-decommission.** Operator
   measurement is "46 %", but this includes whatever transient load was
   present. A 24 h baseline measurement with the Tauri shell off and no
   added workloads would establish the true freed-GPU number, which
   bounds §5.3 (reverie passes) and §7.1 (NVENC headroom).

2. **MediaMTX RTMP throughput at 9 Mbps.** Current path is
   `studio-compositor → mediamtx → YouTube`. The mediamtx config
   (`scripts/mediamtx-start.sh`) needs verification that it does not
   re-encode and that it can passthrough 9 Mbps without buffering. A
   one-stream test answers this.

3. **HARDM Phase 2 publisher CPU.** The current publisher
   (`scripts/hardm-publish-signals.py`) collapses 16 columns into 1
   value per row. Phase 2 needs ~256 independent signal computations.
   The publisher cost may be larger than the consumer cost if signal
   sources require new collection paths.

4. **Browser tab persistence for the React UI.** If the operator opens
   the `:8051/ui` tab and forgets it, the app polls the WebSocket at
   `:8051` periodically and drives a continuous (small) load. Worth
   confirming this is acceptable, or whether the UI should self-pause
   when not focused.

5. **Reverie crossfade behaviour at 9 vs 8 active passes.** The
   per-slot crossfade in `project_reverie_autonomy.md` is documented
   for the current 8-pass topology. Adding 2 passes may or may not
   require recalibration.

6. **Whether the operator wants any preview-in-Logos at all.** The
   §10.2 recommendation defers Tauri indefinitely. If the operator's
   future workflow involves "a single tiled control surface with
   embedded preview", we revisit Option 5 (WebRTC self-loopback) at
   that time, but the question remains open.

## §13. Sources

### 13.1 Codebase

- `systemd/units/hapax-logos.service` (decommissioned unit; `MemoryMax=4G` cgroup, WebKit env workarounds, lines 24–33)
- `systemd/hapax-build-reload.path` (decommissioned path watcher, lines 7–10)
- `systemd/units/hapax-build-reload.service` (decommissioned reload service)
- `systemd/units/studio-compositor.service` (220 % CPU steady, `MemoryMax=6G` `MemoryHigh=infinity`, lines 88–114)
- `systemd/units/hapax-imagination.service` (headless mode env `HAPAX_IMAGINATION_HEADLESS=1`, lines 30–37)
- `systemd/units/hapax-daimonion.service` (12 GB MemoryMax, distil-large-v3 + Kokoro + 7+ vision models, lines 35–44)
- `systemd/units/tabbyapi.service` (Qwen3.5-9B EXL3 5.0bpw on `:5000`)
- `systemd/units/mediamtx.service` (RTMP relay to YouTube)
- `agents/studio_compositor/pipeline.py` (RTMP egress encoder; the file to edit per §7.1 / §11.1.1)
- `agents/studio_compositor/snapshots.py` (decommissioned `:8053/ws/fx` JPEG branch reference)
- `agents/studio_compositor/hardm_source.py` (HARDM 16×16 grid producer, Phase 2 target)
- `hapax-logos/src/components/graph/nodes/OutputNode.tsx:301` (decommissioned preview consumer)
- `hapax-logos/src-tauri/src/visual/fx_relay.rs:37` (decommissioned TCP→WS relay)
- `hapax-logos/src-tauri/src/visual/http_server.rs:56` (decommissioned `:8053/fx` endpoint)
- `agents/hapax_daimonion/cpal/production_stream.py` (CPAL voice lifecycle reference)
- `shared/qdrant_schema.py` (canonical Qdrant collections schema, referenced in CLAUDE.md)
- `config/compositor-layouts/default.json` (HARDM placement, surface bindings)

### 13.2 Repository docs

- `docs/research/2026-04-20-logos-output-quality-design.md` §2.8 quality-loss table; §3 OBS baseline; §4 Option 5 (WebRTC) [logos-quality]
- `docs/research/2026-04-19-hardm-redesign.md` §1.1–§1.5 (Phase 2 design)
- `docs/research/2026-04-19-gem-ward-design.md` §1.1–§1.4 (GEM design)
- `docs/superpowers/plans/2026-04-20-programme-layer-plan.md` §0 (Programme layer scope)
- `docs/research/2026-04-20-vinyl-broadcast-mode-d-granular-instrument.md` (Vinyl Mode D)
- `docs/research/2026-04-20-vinyl-broadcast-calibration-telemetry.md` (MonetizationRiskGate context)
- `docs/research/2026-04-20-dynamic-livestream-audit-catalog.md` (Wave B detectors)
- `docs/runbooks/rig-migration.md` §pre-migration checklist (rig-migration trigger preservation)
- `docs/research/2026-04-19-delta-alpha-coordination-protocol.md` (queue and gate references)

### 13.3 Operator memory

- `project_rig_migration.md` — rig migration at stream-ready milestone
- `project_homage_go_live_directive.md` — go live after A3/A4; iterate via DEGRADED-STREAM
- `project_720p_commitment.md` — never propose resolution changes as remediation
- `project_studio_cameras.md` — 6-camera USB ceiling
- `project_hardm_anti_anthropomorphization.md` — HARDM anti-face invariant
- `project_reverie.md` — 7-pass wgpu pipeline (now 8); per-node param bridge complete
- `project_reverie_autonomy.md` — per-slot crossfade, hot-swap
- `project_reverie_adaptive.md` — 5-channel mixer; physarum/voronoi/RD as targets
- `project_effect_graph.md` — 56 WGSL nodes, 30 presets, SlotPipeline
- `project_command_registry.md` — `window.__logos` API surface (becomes browser-tab API after §11.1.3)
- `project_tauri_only.md` — prior Tauri-only migration context
- `project_hapax_data_audit.md` — VRAM and inference accounting
- `feedback_grounding_over_giq.md` — pick for grounding flexibility, not MMLU/GSM8K
- `feedback_consent_latency_obligation.md` — voice latency is governance violation
- `feedback_no_unsolicited_windows.md` — operator controls visual surface lifecycle
- `feedback_director_grounding.md` — fix director speed via quant/prompt, not model swap
- `feedback_grounding_exhaustive.md` — every move is grounding or outsourced-by-grounding

### 13.4 External

- mpv low-latency v4l2 preview command [mpv-low-lat]: <https://mpv.io/manual/stable/>
- mpv v4l2 av:// untimed behaviour [mpv-issue-7896]: <https://github.com/mpv-player/mpv/issues/7896>
- mpv arch wiki tip on low-latency v4l2 capture [mpv-arch]: <https://wiki.archlinux.org/title/Mpv>
- Level1Techs forum on low-latency mpv v4l2 capture preview [level1-mpv]: <https://forum.level1techs.com/t/low-latency-preview-applications-for-a-v4l2-usb-capture-device-aspect-ratio-problems/174332>
- gtk4paintablesink GStreamer documentation [gtk4paintable]: <https://gstreamer.freedesktop.org/documentation/gtk4/index.html>
- gst-plugin-gtk4 crate [gst-plugin-gtk4]: <https://lib.rs/crates/gst-plugin-gtk4>
- GNOME Discourse: GTK4 GStreamer sink [gnome-gtk4]: <https://discourse.gnome.org/t/creating-gstreamer-sink-for-widget-in-gtk4-application/13220>
- GStreamer-devel: waylandsink overlay limitations [gst-wayland]: <https://discourse.gstreamer.org/t/embedding-gstreamer-into-wayland-window/3661>
- mpvpaper (wlr-layer-shell video) [mpvpaper]: <https://github.com/GhostNaN/mpvpaper>
- wlr-layer-shell protocol reference [wlr-layer]: <https://wayland.app/protocols/wlr-layer-shell-unstable-v1>
- NVIDIA Video Codec SDK 10 presets blog [nvenc-presets]: <https://developer.nvidia.com/blog/introducing-video-codec-sdk-10-presets/>
- OBS Advanced NVENC options [obs-nvenc]: <https://obsproject.com/kb/advanced-nvenc-options>
- Xaymar high-quality NVENC streaming guide [xaymar]: <https://www.xaymar.com/guides/obs/high-quality-streaming/nvenc/>
- NVIDIA NVENC OBS guide [nvidia-bcast]: <https://www.nvidia.com/en-us/geforce/guides/broadcasting-guide/>
- NVENC SFE (Split-Frame Encoding) evaluation, latency findings [nvenc-sfe]: <https://arxiv.org/html/2511.18687v1>
- YouTube live encoder bitrate / resolution recommendations [youtube-encode]: <https://support.google.com/youtube/answer/2853702?hl=en>
- Castr YouTube bitrate guide [castr-bitrate]: <https://castr.com/blog/best-bitrate-for-youtube/>
- Distil-Whisper large-v3 model card (6.3× speed, <1 % WER delta) [distil-whisper]: <https://huggingface.co/distil-whisper/distil-large-v3>
- Northflank STT benchmarks 2026 [northflank-stt]: <https://northflank.com/blog/best-open-source-speech-to-text-stt-model-in-2026-benchmarks>
- Towards AI Whisper variants comparison [towardsai-whisper]: <https://towardsai.net/p/machine-learning/whisper-variants-comparison-what-are-their-features-and-how-to-implement-them>
- apxml Qwen3-14B specs and VRAM [apxml-14b]: <https://apxml.com/models/qwen3-14b>
- Hardware-Corner Qwen3 hardware requirements [hw-qwen3]: <https://www.hardware-corner.net/guides/qwen3-hardware-requirements/>
- Prometheus scrape interval tuning (oneuptime) [onuptime-prom]: <https://oneuptime.com/blog/post/2026-02-09-prometheus-scrape-intervals-tuning/view>
- Groundcover Prometheus scraping efficiency 2026 [groundcover-prom]: <https://www.groundcover.com/learn/observability/prometheus-scraping>
- Signoz: Prometheus high memory usage [signoz-prom]: <https://signoz.io/guides/why-does-prometheus-consume-so-much-memory/>
- Last9: high cardinality metrics in Prometheus [last9-card]: <https://last9.io/blog/how-to-manage-high-cardinality-metrics-in-prometheus/>
- Langfuse sampling docs [langfuse-sampling]: <https://langfuse.com/docs/observability/features/sampling>
- GStreamer ebur128level element docs [gst-ebur128]: <https://gstreamer.freedesktop.org/documentation/rsaudiofx/ebur128level.html>
- FFmpeg f_ebur128 source reference [ffmpeg-ebur128]: <https://ffmpeg.org/doxygen/3.1/f__ebur128_8c_source.html>
- nomadsanalytics RTX lifespan 2026 guide [nomads-rtx]: <https://nomadsanalytics.com/how-long-do-gpus-last-rtx-lifespan/>
- ofzenandcomputing GPU temp guide 2026 [ofzen-temp]: <https://www.ofzenandcomputing.com/best-graphics-cards-gpus-temps/>
- Unicorn Platform: 3-5 yr GPU lifecycle playbook [unicorn-gpu]: <https://unicornplatform.com/blog/how-long-should-a-gpu-actually-last-expect-3-5-years/>
- dasroot: GPU monitoring (temperature, usage, longevity) [dasroot-gpu]: <https://dasroot.net/posts/2026/03/monitoring-gpu-health-temperature-usage-longevity/>
- Quora: 100 % utilisation lifespan discussion [quora-mining]: <https://www.quora.com/Is-it-safe-to-keep-the-GPU-on-100-utilization-for-a-very-long-time>
- ElectronicsHub: how long do graphics cards last [electronicshub-gpu]: <https://www.electronicshub.org/how-long-do-graphics-cards-last/>
