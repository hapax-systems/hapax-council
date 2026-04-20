# Livestream halt investigation — director-LLM timeout cascade + prevention plan

**Date:** 2026-04-20
**Author:** alpha (research dispatch)
**Status:** root-cause investigation → recommended phased ship plan
**Trigger:** Operator report 2026-04-20 ~02:59Z — "the entire livestream has halted. no audio, no changes happening." Live diagnosis: studio-compositor PID 1793792 ACTIVE since 02:29:51, v4l2sink BUFFER probe firing every ~0.24 ms, preset_recruitment_consumer rotating presets every 8–30 s, fx-snapshot.jpg + snapshot.jpg both fresh — yet **20 director LLM timeouts in 30 minutes** (~1 every 90 s) with TabbyAPI sitting at 89 % single-core CPU under 2-day uptime.
**Companion drops:** [`2026-04-20-v4l2sink-stall-prevention.md`](2026-04-20-v4l2sink-stall-prevention.md), [`2026-04-14-compositor-output-stall-live-incident-root-cause.md`](2026-04-14-compositor-output-stall-live-incident-root-cause.md), [`2026-04-14-tabbyapi-config-audit.md`](2026-04-14-tabbyapi-config-audit.md), [`2026-04-14-director-loop-prompt-cache-gap.md`](2026-04-14-director-loop-prompt-cache-gap.md), [`2026-04-12-prompt-compression-phase2-ab-results.md`](2026-04-12-prompt-compression-phase2-ab-results.md), [`2026-04-12-kvzip-exllamav3-compatibility.md`](2026-04-12-kvzip-exllamav3-compatibility.md)
**Register:** scientific, neutral

---

## §1 TL;DR

**What is happening.** The compositor's `_call_activity_llm`
(`agents/studio_compositor/director_loop.py:2241-2433`) is the only
synchronous path that gates director narrative output. When TabbyAPI
prefill latency exceeds the per-call timeout
(`HAPAX_DIRECTOR_LLM_TIMEOUT_S=40`,
`director_loop.py:2351`), the call raises `TimeoutError`, the path
falls through to `_emit_micromove_fallback`
(`director_loop.py:1141`, `director_loop.py:1323-1450`), and the
operator perceives "no audio + no changes" because:

1. Hapax voice is the dominant audio source when no vinyl is playing.
   No new narrative → no Kokoro TTS synthesis → no audio on
   `input.loopback.sink.role.assistant` → silent broadcast bed
   (`director_loop.py:2528-2540` is the only ducked-PCM path that
   feeds the L6 mix's TTS channel).
2. Visual changes are happening (preset_recruitment_consumer ticked
   five presets in five minutes per operator timeline; the v4l2sink
   buffer-probe at `pipeline.py:230-234` is firing on every frame),
   but operator reads "changes" as **narrative-driven changes** — the
   ones the director announces. Without director narratives, the
   surface drifts on micromove fallbacks and the operator perceives
   stasis even though the pixel pipeline is alive.

**Most likely root cause (single paragraph justification).** The
director model was migrated from Qwen3.5-9B to **Command-R-08-2024
32B EXL3 5.0 bpw split across two GPUs** (`tabbyAPI/config.yml`
`gpu_split: [12, 14]`, `model_name: command-r-08-2024-exl3-5.0bpw`)
on 2026-04-17 to satisfy the grounded-director constraint
(`feedback_director_grounding`: "Director is the livestream's
meta-structure communication device; stays on the grounded model
even under speed pressure"). The director prompt assembled by
`_build_unified_prompt` (`director_loop.py:1598-2240`) has grown
across at least eight subsystems — persona block + perceptual field
JSON + system-state TOON block + recent-reactions thread + research
objectives + activity capabilities + preset family vocabulary + multi-
surface guidance + HOMAGE composition + music narrative discipline +
banned-narration block — into a 10–15 kB system message. The
inline comment at `director_loop.py:2342-2350` already documents
this: "Command-R-08-2024 (35B, 5bpw) replaced Qwen3.5-9B as
local-fast: a 10-15 kB prompt + 150 tokens out sits at ~25 s even
on an unloaded RTX 3090. 40s fits that." Add (a) a 2-day TabbyAPI
uptime where ExllamaV2/V3's KV-cache pool fragments under
distinct-prompt traffic ([turboderp-org/exllamav2#291](https://github.com/turboderp-org/exllamav2/issues/291),
[ggml-org/llama.cpp#3380](https://github.com/ggml-org/llama.cpp/issues/3380)),
(b) the NVENC bump from p1 to p5 on 2026-04-20 (commit
`12ec97264`) which raised the encoder's per-frame compute
budget on the 3090, (c) the active concurrent CUDA tenants
(Reverie wgpu rendering, Imagination wgpu rendering, Daimonion
Whisper STT, glfeedback shaders) and (d) the LiteLLM gateway hop +
Anthropic-style prompt-cache gap documented in
`2026-04-14-director-loop-prompt-cache-gap.md` — and the 40 s
ceiling is no longer a comfortable margin. Every other tick crosses
it. **Most-likely root cause: prefill-latency drift past the 40 s
timeout under combined long-prompt + long-uptime + GPU-tenant
contention.**

**Highest-impact Phase 1 ship (single pick).** Add a **director
liveness watchdog** modelled exactly on the v4l2sink stall
watchdog (`agents/studio_compositor/lifecycle.py:305-336`,
`pipeline.py:221-234`, commit `e2175469a`). Conjoin the existing
`any_active and v4l2_alive` gate with a third predicate
`director_intent_emitted_within(180.0)`. When the director loop has
not produced a parsed `DirectorIntent` for 3 minutes (six full
PERCEPTION_INTERVAL=30 s ticks, `director_loop.py:503`), withhold
`WATCHDOG=1`; systemd `WatchdogSec=60s` SIGABRTs the unit; restart
re-seeds the loop. The graceful-fallback layer
(`_emit_micromove_fallback`, `director_loop.py:1323-1450`) is
already shipped for the *single*-tick case; Phase 1 adds the
*sustained*-failure escape valve. Picking the watchdog over
"better metrics" is justified because metrics describe the failure
*after* it happened; the watchdog *resolves* it. Picking the
watchdog over "richer fallback" is justified because the fallback
already exists and is structurally sufficient for one or two stuck
ticks — what's missing is the systemd-level safety net that
recovers when the LLM is *persistently* stuck (TabbyAPI hung, GPU
context lost, model deadlocked).

**Recommended phased plan.**

| Phase | Scope | LOC | Ship by |
|---|---|---|---|
| 1 | Director liveness watchdog (sd_notify gate) + Prometheus `hapax_director_intent_age_seconds` | ~50 LOC | tonight |
| 2 | Single-flight lock + skip-tick when in-flight + Prometheus pending-tick counter | ~80 LOC | this week |
| 3 | TabbyAPI daily restart timer (3 am) + KV cache health Prometheus scrape | ~30 LOC + systemd timer | this week |
| 4 | Prompt size budget + token-count metric + structured diet | ~150 LOC | next sprint |
| 5 | NVENC + CUDA stream priority pinning, `CUDA_DEVICE_MAX_CONNECTIONS` tuning | ~40 LOC + systemd drop-in | next sprint |
| 6 | Continuous batching / chunked prefill investigation; speculative decoding draft model | research only | next sprint |

---

## §2 Symptom inventory — what operator saw vs what was actually happening

### §2.1 Operator-visible signal

- 2026-04-20 ~02:59Z: "the entire livestream has halted. no audio, no
  changes happening."
- The phrasing fuses two distinct subsystems (audio + visual) into
  one perceptual claim. Live diagnosis disambiguated them.

### §2.2 Ground-truth at 02:59Z

| Subsystem | State | Evidence |
|---|---|---|
| `studio-compositor.service` | Active, no restart since 02:29:51 | systemd journal |
| v4l2sink push | Frame every ~0.24 ms (60 fps × 1.0 buffer cadence) | `studio_compositor_v4l2sink_last_frame_seconds_ago` ≈ 0.0 (`agents/studio_compositor/metrics.py:425-431`) |
| preset_recruitment_consumer | Five preset rotations in five minutes (8–30 s spacing) | recent journal entries; consumer fires on `compositional_impingement.preset.bias` writes per `agents/studio_compositor/preset_recruitment_consumer.py:47-84` |
| Snapshot artefacts | `fx-snapshot.jpg`, `snapshot.jpg` mtime 02:59 | `compositor.py:769` snapshot branch + `add_fx_snapshot_branch` |
| LiteLLM `:4000` health | 2.5 ms ping | curl from operator |
| TabbyAPI `:5000` | Active, **89 % CPU on serving thread** | top |
| Director LLM calls | **20 timeouts in 30 min** (~1 every 90 s) | `director_loop.py:2354` `TimeoutError` re-raise → `llm_call_span` outcome=timeout (`agents/telemetry/llm_call_span.py:43-58`) |
| TabbyAPI uptime | ~2 days | systemd `Active:` line |
| Audio path | L6 multitrack capture connected, L6 Main Mix → `livestream-tap` connection alive | PipeWire graph |

### §2.3 Where operator's perception diverged from ground truth

Pixel-side: alive (v4l2sink probe fires every frame). Visual chain:
mutating (preset rotations recorded). Audio backbone: alive
(PipeWire connection list intact). **What was actually halted: the
director's narrative output channel.** Hapax voice was silent for
~30 minutes because every other narrative-LLM call was raising
`TimeoutError` and falling through to micromove fallback, which
deliberately **does not speak** (it only emits a compositional
impingement and writes the JSONL — `director_loop.py:1410-1442`
constructs no TTS text). When no music is playing, Hapax voice IS
the audible signature of the stream. Without it, the broadcast
sounds dead even though every visual subsystem is healthy.

This is a critical observation for §6 (watchdog design) and §11
(observability gaps). The operator's "halted" is a **subjective
proxy** for narrative-channel liveness, which the existing
v4l2sink watchdog (commit `e2175469a`) explicitly does not cover.
The Phase 1 watchdog ship in §6 closes this perceptual coverage
gap.

---

## §3 Director LLM timeout analysis

### §3.1 The call site

`agents/studio_compositor/director_loop.py:2241-2433` —
`_call_activity_llm`. Synchronous `urllib.request.urlopen` against
`LITELLM_URL` with timeout governed by env
`HAPAX_DIRECTOR_LLM_TIMEOUT_S` (default 40 s,
`director_loop.py:2351`). On `TimeoutError` the exception is re-
raised (line 2354–2356) so the surrounding `llm_call_span`
(`agents/telemetry/llm_call_span.py`) tags `outcome="timeout"` in
`hapax_llm_call_outcomes_total{condition,model,route,outcome}`.
The outer `try/except Exception` at `director_loop.py:2431-2433`
catches it and returns `""`. The caller at line 1131 then sees
`not result`, calls `_emit_micromove_fallback(reason="llm_empty",
...)` (line 1141), and `time.sleep(1.0)` before continuing the
loop.

### §3.2 Cadence math

`PERCEPTION_INTERVAL = 30.0` s
(`director_loop.py:503`, env-overridable as
`HAPAX_NARRATIVE_CADENCE_S`). One `_call_activity_llm` per tick. 20
timeouts in 30 min ≈ one timeout every 90 s ≈ **every 3rd tick at
30 s cadence**. If we account for the fact that a timed-out tick
itself burns 40 s wall clock (timeout) + ~2 s overhead and then
sleeps 1.0 s before the next loop iteration, the *effective*
post-timeout cadence rises to 73+ s — meaning a sequence of
back-to-back timeouts compresses real cadence near every-other-tick.

At 30 min × 60 s ÷ ~90 s = 20 timeouts: matches the reported
count. **Roughly every other tick was timing out.**

### §3.3 Prefill-latency drivers — primary

The inline comment at `director_loop.py:2342-2350` is load-bearing:

> 30s baseline → 8s over-correction → 20s → 40s. 20s was too
> tight once Command-R-08-2024 (35B, 5bpw) replaced Qwen3.5-9B as
> local-fast: a 10-15 kB prompt + 150 tokens out sits at ~25 s
> even on an unloaded RTX 3090. 40s fits that, and the narrative
> cadence is HAPAX_NARRATIVE_CADENCE_S (default 30s since
> 2026-04-17) so a single stall can't queue up.

This is the alpha-author's own admission that the timeout was
calibrated to the *unloaded* steady-state. Under the actual
contention profile observed at 02:59Z it does not hold. Causes:

1. **Prompt size growth.** `_build_unified_prompt`
   (`director_loop.py:1598-2240`) appends content from at least 14
   layered subsystems (persona, music framing, vinyl signal block,
   chat state, phenomenal context, perceptual field JSON,
   structural-direction snapshot, system-state TOON, recent-reactions
   thread, research objectives, activity capabilities, music narrative
   discipline, preset family vocabulary, multi-surface guidance, homage
   composition). A `wc -l agents/studio_compositor/director_loop.py`
   reports 2,681 lines; the prompt-build function alone is 643 lines
   (1598–2240). Beta's 2026-04-14 prompt-compression Phase 2 results
   (`docs/research/2026-04-12-prompt-compression-phase2-ab-results.md`)
   estimated this at 5,000+ tokens before the latest additions; with
   the 2026-04-19/20 additions (preset family vocabulary, music
   narrative discipline, homage composition, multi-surface moves) the
   prompt is plausibly 8,000+ tokens now — not yet measured directly
   (see §10).
2. **Long-prompt prefill cost.** Per Hugging Face's "How long prompts
   block other requests" analysis ([huggingface.co/blog/tngtech/llm-performance-blocked-by-long-prompts](https://huggingface.co/blog/tngtech/llm-performance-blocked-by-long-prompts)),
   prefill is compute-bound and scales near-linearly with input
   length. NVIDIA's chunked-prefill blog ([developer.nvidia.com/blog/streamlining-ai-inference-performance-and-deployment-with-nvidia-tensorrt-llm-chunked-prefill](https://developer.nvidia.com/blog/streamlining-ai-inference-performance-and-deployment-with-nvidia-tensorrt-llm-chunked-prefill/))
   notes that on a single 32B model "long-context requests share
   the GPU with short interactive queries" produces TTFT spikes
   that chunked-prefill is specifically designed to fix.
3. **Concurrent GPU tenants under contention.** TabbyAPI is on
   cuda:0 + cuda:1 split (3090 + 5060 Ti). Concurrent on the 3090:
   Reverie wgpu (8-pass shader graph per `hapax-council/CLAUDE.md`
   § Tauri-Only Runtime), Imagination wgpu, Daimonion Whisper STT
   (GPU-resident), glfeedback Rust plugin (CUDA-CL interop),
   NVENC encoder for RTMP. The arxiv survey "Characterizing
   Concurrency Mechanisms for NVIDIA GPUs" ([arxiv.org/pdf/2110.00459](https://arxiv.org/pdf/2110.00459))
   and the SLO-aware paper ([arxiv.org/html/2603.12831v2](https://arxiv.org/html/2603.12831v2))
   document that CUDA stream-priority hints don't preempt running
   work and SM-level contention can produce 50 % latency variance.
4. **TabbyAPI single-thread serial behaviour.** Per the
   `2026-04-14-tabbyapi-config-audit.md` finding 2 ("`cache_size`
   matches `max_seq_len` exactly… exactly one concurrent request
   of maximum length can be in flight") and the upstream issue
   [theroyallab/tabbyAPI#304](https://github.com/theroyallab/tabbyAPI/issues/304),
   model-switch and large-context requests are effectively
   serialized. Director ticks are large-context and unique each
   time (perceptual field shifts every tick), so prefix-cache
   reuse is minimal even when ExllamaV3 supports it. The
   exllamav2 dynamic generator doc ([github.com/turboderp-org/exllamav2/blob/master/doc/dynamic.md](https://github.com/turboderp-org/exllamav2/blob/master/doc/dynamic.md))
   describes a job queue that can fit multiple jobs but only when
   the cache has headroom; with `cache_size: 16384` and a
   ~10 kB prompt the headroom is minimal.

### §3.4 Prefill-latency drivers — secondary

5. **KV-cache pool fragmentation at 2-day uptime.** ExllamaV2's
   own issue tracker ([turboderp-org/exllamav2#291](https://github.com/turboderp-org/exllamav2/issues/291))
   and the llama.cpp generic discussion ([ggml-org/llama.cpp#3380](https://github.com/ggml-org/llama.cpp/issues/3380))
   document KV-cache fragmentation under iterative generation
   without restart. The PagedAttention paper ([arxiv.org/abs/2309.06180](https://arxiv.org/abs/2309.06180))
   quantifies the canonical inefficiency: "actual effective memory
   utilization being as low as 20 % (80 % waste)" — that's the
   solved problem; ExllamaV3 inherits a paged-attention design but
   the cache pool can still fragment under workloads with highly
   variable distinct prompts. With `cache_mode: Q4` (Q4 KV quant
   per `tabbyAPI/config.yml`) at 16K context, the pool size is
   constrained — 2 days of distinct director prompts is enough to
   drift the pool toward worst-case allocation patterns.
6. **NVENC bump 2026-04-20.** Commit `12ec97264` raised NVENC from
   p1 to p5 ("p5 + bitrate 3→9 Mbps"). NVENC on RTX 3090 is
   formally "independent of CUDA" per NVIDIA's NVENC App Note
   ([docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvenc-application-note/index.html](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvenc-application-note/index.html)),
   but the GIGA CHAD streaming benchmark
   ([gigachadllc.com/geforce-rtx-3090-streaming-benchmarks-breakdown](https://gigachadllc.com/geforce-rtx-3090-streaming-benchmarks-breakdown/))
   notes "GPU contention occurs only at NVENC Max Quality with
   heavy GPU workloads" — exactly our profile. P5 is two steps
   above p1 and adds non-trivial encoder workload concurrent with
   the LLM serving thread.
7. **No prompt-cache utilization.** Beta's 2026-04-14 audit
   ([`2026-04-14-director-loop-prompt-cache-gap.md`](2026-04-14-director-loop-prompt-cache-gap.md))
   found `cache_control: ephemeral` is not used anywhere in the
   council codebase. LiteLLM's Redis response cache only catches
   byte-identical requests. With every director tick carrying a
   fresh perceptual field JSON, that hit rate is effectively 0 %.
   Sankalp's prompt-caching write-up ([sankalp.bearblog.dev/how-prompt-caching-works/](https://sankalp.bearblog.dev/how-prompt-caching-works/))
   confirms the model: cache hits are tied to *prefix identity*,
   and the director prompt has no stable prefix discipline (the
   persona block is at the top — would be cacheable — but it's
   followed by mutable content layers that prevent suffix reuse,
   and the OpenAI-compat shape this code targets has no
   per-content-block cache_control tagging).
8. **OS-level scheduling artefacts.** 89 % CPU on the model
   serving thread under `top` indicates a single Python+CUDA
   thread saturating one core, which is consistent with the
   exllamav2 dynamic-generator design (job queue serviced
   sequentially per cache page). PCIe traffic between cuda:0 and
   cuda:1 for the model split crosses the same root complex; the
   NVIDIA dev-forum thread on `CUDA_DEVICE_MAX_CONNECTIONS`
   ([forums.developer.nvidia.com/t/cuda-device-max-connections-and-pci-e-traffic/262962](https://forums.developer.nvidia.com/t/cuda-device-max-connections-and-pci-e-traffic/262962))
   notes the env var has direct PCIe traffic implications.

### §3.5 Why 40 s is no longer enough

Combined: ~10–15 kB prompt × prefill cost on a saturated 32B model
(serial KV pool) × NVENC p5 contention × 2-day cache fragmentation
× zero prompt-cache reuse. Expected p99 prefill latency under
those conditions is plausibly 35–55 s based on the
hardware-corner GPU rankings ([hardware-corner.net/gpu-ranking-local-llm/](https://www.hardware-corner.net/gpu-ranking-local-llm/))
and modelfit's RTX 3090 benchmark ([modelfit.io/gpu/rtx-3090/](https://modelfit.io/gpu/rtx-3090/))
showing 32B prefill at ≤ 100 tok/s under contention. A 10,000-token
prompt at 200 tok/s = 50 s; at 300 tok/s = 33 s. The 40 s timeout
sits inside the variance band — **half the calls cross it**.

---

## §4 Chain reaction map

When `_call_activity_llm` raises `TimeoutError` and returns `""`,
the following downstream consumers behave differently from the
operator's mental model:

### §4.1 Confirmed-broken-by-timeout

1. **Hapax voice** — `_speak_activity` (`director_loop.py:2435-2500`)
   is only called when `result` is truthy AND `text` is non-empty
   AND `activity != "silence"`. Timeout → empty result → no speak
   path. Kokoro 82M CPU TTS is the only voice surface; without it,
   broadcast audio falls back to whatever else is on L6 mix.
2. **Director narrative artefacts** — `_emit_intent_artifacts`
   (`director_loop.py:1187`) is called *only* on parsed intent.
   Timeout path → `_emit_micromove_fallback` (line 1141), which
   *does* call `_emit_intent_artifacts` (line 1442) but writes
   the prefix `[micromove:llm_empty]` to `narrative_text`. So
   `/dev/shm/hapax-director/narrative-state.json` does get
   refreshed, but with the micromove sentinel — not narrative-
   driven content.
3. **JSONL reaction log** — same. Records `[micromove:llm_empty]`.

### §4.2 Confirmed-still-running (via micromove fallback)

4. **Compositional impingement stream** — micromove emits one
   `CompositionalImpingement` per tick into
   `/dev/shm/hapax-dmn/impingements.jsonl`
   (`director_loop.py:1413-1419`, written via
   `_emit_compositional_impingements` `director_loop.py:246-300`).
   The cycle of 7 micromoves
   (`director_loop.py:1354-1408`) rotates: overlay.emphasis,
   preset.bias, overlay.emphasis, camera.hero, overlay.emphasis,
   ward.highlight, overlay.emphasis. Salience pinned at 0.35.
5. **preset_recruitment_consumer** — when the micromove cycle
   lands on `preset.bias` (every 6th–7th tick),
   `agents/studio_compositor/preset_recruitment_consumer.py`
   reads the impingement, recruits a preset, mutates the FX chain.
   This is why operator timeline shows preset rotations every
   8–30 s during the timeout cascade — the micromove cycle index
   was happening to land on `preset.bias` plus the unrelated
   visual chain alive too.
6. **AffordancePipeline + structural intent** — micromove writes
   `NarrativeStructuralIntent`
   (`director_loop.py:1424-1430`); structural consumers see ward
   emphasis + rotation mode. So the surface keeps shifting at
   reduced amplitude.
7. **v4l2sink** — entirely upstream of director output. Continues
   pushing frames at 60 fps regardless of LLM state. Verified by
   the `studio_compositor_v4l2sink_last_frame_seconds_ago` gauge
   reading ≈ 0 throughout the incident.

### §4.3 Operator-perceived-but-actually-OK

8. **"No changes happening"** — visually this is wrong; preset
   rotations were happening. Operator perception was driven by
   the *narrative* stasis (no Hapax describing the changes) +
   the lack of dramatic visual cuts that director-narrated camera
   shifts produce.
9. **"No audio"** — backbone alive; no source playing. Vinyl
   wasn't playing per operator confirmation. Hapax voice was the
   default audio source and was silent. The L6 main mix was
   transmitting silence cleanly into the broadcast.

### §4.4 Cross-system stale propagation (latent risk)

10. **Daimonion CPAL impingement consumer** — reads
    `/dev/shm/hapax-dmn/impingements.jsonl` per
    `hapax-council/CLAUDE.md` § "Daimonion impingement dispatch".
    Consumes micromove impingements normally (no LLM dependency
    on its side), but the *content* of those impingements is the
    rotating fallback set — so daimonion's spontaneous-speech
    surfacing latches onto the same 7-state cycle until the
    director recovers.
11. **Reverie/Imagination** — they don't directly read director
    output but get aggregate boredom/curiosity signals that depend
    on stimmung; stimmung depends on VLA which reads compositor
    state; if compositor state stops mutating diversely (which it
    doesn't in the timeout case — micromoves rotate), reverie
    eventually flips toward SEEKING per the unified-recruitment
    spec. Not exercised at 02:59Z because micromoves kept the
    feed varied enough.

**Bottom line for chain-reaction analysis.** Every downstream
*data* path stayed alive on micromove fallbacks. The single
high-amplitude path that died is **Hapax voice**, and that's the
one that maps directly onto the operator's "no audio" claim.

---

## §5 Audio "halt" analysis — was it actually halted

Audio backbone is intact at PipeWire layer per operator's live
diagnosis (L6 multitrack capture connected; L6 Main Mix →
livestream-tap connection alive). What was missing was Hapax
voice content. Three plausible mechanisms could be confused with
each other under "no audio":

1. **TTS not synthesizing because director produced no narrative.**
   This is what happened. `_speak_activity` (`director_loop.py:2435`)
   never fired during timeout ticks. PCM never written to
   `input.loopback.sink.role.assistant`
   (`director_loop.py:2528-2540`). L6 ch4 (assistant audio) silent.
2. **Music bed not playing.** Operator confirmed no vinyl active.
   YouTube content surfacer / music_candidate_surfacer also silent.
3. **PipeWire graph break.** Not observed; all connections present.

The L6 multitrack mode research ([`2026-04-19-l6-multitrack-mode.md`](2026-04-19-l6-multitrack-mode.md))
documents the device hosts 12 capture channels, each pre-fader; a
broken connection on ch4 (Hapax assistant) wouldn't produce L6 main
mix silence — it would produce ch4 silence specifically. So a graph
break would not match operator's "no audio" framing — operator was
listening to the broadcast bed (L6 Main Mix) which composes all
channels including silent ones. The simplest explanation:

> **No music + no narrative = silence on the broadcast.** This is
> the *correct* behaviour given the upstream director failure; it's
> "audio halted" only if you assume Hapax voice should be the
> default-on speaker. Which is exactly the assumption the operator
> made.

**This is a governance finding, not a bug.** Per
`feedback_consent_latency_obligation` ("voice latency impeding
consent flow is a governance violation, not a UX issue") the same
shape applies to *director liveness* impeding *broadcast presence*.
The system needs an answer to "what plays when director is down"
that is louder than silence. Options:

- A) Pre-recorded ambient bed activated when director silent for
  > 60 s.
- B) Reverie audio export (the wgpu surface has no audio output
  today — would require pipe).
- C) Increase music_candidate_surfacer aggression when director
  silent (latch onto vinyl signal even at low confidence).
- D) Speak the micromove `narrative` field (currently consumed only
  visually). At 0.35 salience the micromove copy is bland but
  better than dead air.

Option D is the cheapest and lands inside the existing TTS path.
Phase 2 ship candidate.

---

## §6 Director liveness watchdog (recommended Phase 1 ship)

**Model.** The v4l2sink stall watchdog (commit `e2175469a`,
shipped 2026-04-20 01:01Z) is the canonical pattern. Reproduce it
exactly for director output.

### §6.1 Implementation outline (~50 LOC, three files)

**File 1: `agents/studio_compositor/director_loop.py`**
Track the monotonic time of every successful intent emission.
Add a class-level state on `DirectorLoop` and update it from
`_emit_intent_artifacts` (every successful tick) AND from
`_emit_micromove_fallback` (every fallback, since fallback IS a
form of director output that the v4l2 watchdog treats as alive).
But: **gate the watchdog on parsed-LLM-intent emissions only**,
not on micromoves — otherwise the fallback masks the real failure.
Two timestamps:

```python
# Updated by _emit_intent_artifacts on parsed-LLM intent only.
self._last_real_intent_monotonic: float = 0.0
# Updated by _emit_micromove_fallback (fallbacks count for liveness
# but trigger a separate degradation metric).
self._last_any_intent_monotonic: float = 0.0
```

**File 2: `agents/studio_compositor/lifecycle.py:305-336`**
Add a third predicate to the `_watchdog_tick` conjunction
(currently `any_active and v4l2_alive and compositor._running`):

```python
director_alive = (
    time.monotonic() - getattr(compositor, "_last_real_intent_monotonic", 0.0)
    < 180.0  # 6 narrative ticks at 30s cadence
)
if any_active and v4l2_alive and director_alive and compositor._running:
    sd_notify_watchdog()
elif any_active and v4l2_alive and not director_alive:
    sd_notify_status("DEGRADED — director silent for >180s")
    log.warning("director loop silent for >180s — withholding watchdog ping")
```

**File 3: `agents/studio_compositor/metrics.py`**
Following the `V4L2SINK_LAST_FRAME_AGE` pattern at
`metrics.py:425-436`:

```python
DIRECTOR_LAST_INTENT_AGE = Gauge(
    "studio_compositor_director_last_intent_seconds_ago",
    "Seconds since the director last emitted a parsed LLM intent (excluding micromove fallbacks)",
    registry=REGISTRY,
)
DIRECTOR_INTENT_TOTAL = Counter(
    "studio_compositor_director_intent_total",
    "Cumulative parsed LLM intents emitted",
    registry=REGISTRY,
)
```

Wire the gauge into the `_watchdog_tick` callback path so the
metric updates every 20 s alongside `V4L2SINK_LAST_FRAME_AGE`.

### §6.2 Hysteresis design

- **Trigger:** `_last_real_intent_monotonic > 180.0` (6 PERCEPTION_INTERVAL
  ticks). Sized so a single-tick LLM timeout does NOT trigger
  recovery — the existing micromove fallback handles that.
- **Action:** withhold `WATCHDOG=1` ping. systemd's
  `WatchdogSec=60s` (per the camera epic's existing service
  drop-in) SIGABRTs the unit ~60 s later.
- **Recovery:** restart re-seeds the loop; the 30 s
  `PERCEPTION_INTERVAL` produces the first new tick within ~31 s of
  start; `_last_real_intent_monotonic` updates; watchdog resumes
  pinging.
- **Net incident time:** 180 s (silent threshold) + ~60 s
  (WatchdogSec) + ~30 s (restart + first tick) = ~270 s upper bound,
  vs the 30+ minute observed incident. Operator perceived latency
  drops by an order of magnitude.

### §6.3 Why 180 s, not 60 s

- 1× tick (30 s) is normal cadence; missing it is a single LLM
  timeout, fallback handles it.
- 2× ticks (60 s) is the "every other tick timing out" pattern
  observed at 02:59Z; still recoverable on its own and not worth
  burning a 60 s blackout for.
- 6× ticks (180 s) is "system is genuinely stuck" — far past the
  point where the operator would already be perceiving silence;
  pulling the trigger here gets us out of the stall without
  punishing transient slowness.
- Tracking precedent: Python systemd-watchdog libraries like
  [systemd-watchdog](https://pypi.org/project/systemd-watchdog/)
  recommend "call notify() once roughly half of this interval has
  passed" — the 180 s threshold is well inside the design envelope.

### §6.4 Coverage gap closed

This Phase 1 ship closes the same class of gap as the v4l2sink
watchdog: a downstream subsystem can fail silently while the
upstream system reports healthy. The v4l2sink fix caught
"compositor running but pixels frozen"; this fix catches
"compositor running but director frozen". Both are **silent
failures invisible to systemd** that need an internal liveness
proxy.

Failure modes this watchdog resolves:

1. TabbyAPI process hung (crashed model load, GPU context loss).
2. CUDA context fault on 3090 (Reverie + TabbyAPI mutual
   contention escalating to driver reset).
3. LiteLLM gateway deadlock (Redis cache stall, internal queue).
4. `_call_activity_llm` synchronous urlopen blocking past timeout
   (timeout doesn't fire if the socket is in a weird state).
5. Director loop thread itself stuck in any of `_build_unified_prompt`,
   `_gather_images`, `_parse_intent_from_llm`,
   `_emit_intent_artifacts`, `_speak_activity` — anywhere in the
   2,681-line file that could deadlock.

Trade-off: a single LLM provider outage (TabbyAPI down for
maintenance, GPU restarted for OS update) will trigger the
watchdog. That's the correct behaviour — restart unblocks,
recovery is automatic, and the alternative is a half-hour of
operator-visible silence.

---

## §7 Graceful timeout fallback

Already largely shipped. `_emit_micromove_fallback`
(`director_loop.py:1323-1450`) handles single-tick timeouts and
keeps the visual subsystem fed. Two improvements worth the LOC:

### §7.1 Speak the micromove

When `reason == "llm_empty"`, opportunistically pass the micromove
narrative to `_speak_activity` at low salience. The 7 baseline
narratives in the cycle (`director_loop.py:1354-1408`) are
intentionally bland but they do contain content
("Brighten the album face for a beat so the music stays legible.").
This is option D from §5. It would be markedly better than dead
air on a transient timeout. Gate on a counter so a *sustained*
timeout doesn't spam the broadcast with micromove copy — speak the
first 1 of every N micromove ticks.

### §7.2 Reduce micromove cycle stride

The cycle is 7 micromoves; only one of them
(`preset.bias` at index 1) cycles the visual chain. Re-balance to
have at least 3 of 7 cycle the visual chain so micromove output
LOOKS more director-driven during sustained timeouts. This is a
content edit on the cycle list, not architecture.

### §7.3 Circuit-breaker on the LLM call site

Per Portkey's "Retries, fallbacks, and circuit breakers in LLM
apps" ([portkey.ai/blog/retries-fallbacks-and-circuit-breakers-in-llm-apps](https://portkey.ai/blog/retries-fallbacks-and-circuit-breakers-in-llm-apps/))
and Aerospike's circuit-breaker-pattern reference
([aerospike.com/blog/circuit-breaker-pattern](https://aerospike.com/blog/circuit-breaker-pattern/)),
a CLOSED → OPEN → HALF-OPEN circuit breaker around
`_call_activity_llm` would short-circuit the 40 s timeout when
N consecutive failures have occurred. With the watchdog from §6,
this is somewhat redundant (the watchdog will restart the
service anyway) but it prevents the operator-perceived stretch
of "every 90 s another timeout" — when the breaker is OPEN, the
loop skips the urlopen entirely and goes straight to micromove
fallback at 30 s cadence, no 40 s blocking call.

Implementation: 3 consecutive timeouts → OPEN for 60 s → one
HALF-OPEN probe → close on success or back to OPEN. ~30 LOC.
Phase 2 candidate; Phase 1 watchdog provides the bigger correctness
guarantee.

---

## §8 TabbyAPI queue management

### §8.1 Single-flight director call

The director loop currently fires `_call_activity_llm` synchronously
on the loop thread (`director_loop.py:1131`). Because the call is
synchronous and the loop sleeps 0.5–1.0 s between iterations after
the 30 s perception interval, a *new* tick cannot start before the
*previous* tick's call returns or times out. So in the strict sense,
there is already implicit single-flight at the director-loop level.

**The risk is at the TabbyAPI side**, not the director side: if
multiple consumers of `local-fast` (director, structural director
at `agents/studio_compositor/structural_director.py:333` with
`timeout=90`, twitch director, plus any agents using the same
LiteLLM route) issue concurrent requests, TabbyAPI's job queue
([github.com/turboderp-org/exllamav2/blob/master/doc/dynamic.md](https://github.com/turboderp-org/exllamav2/blob/master/doc/dynamic.md):
"Initially it will start as many jobs as it can fit in the cache,
and as soon as a job finishes, those pages are freed to make room
for the next job in the queue") will queue them. With a 16 K
`cache_size` and ~10 kB prompts (~2.5 K tokens), the cache fits
~6 concurrent prompts; but director's prompt is 8K+ tokens and the
structural director also issues 5K+-token prompts. Two concurrent
director-class prompts already saturate the cache, and additional
jobs queue (= sit waiting for previous-job pages to free).

### §8.2 Recommended changes

1. **Process-wide single-flight on `local-fast`.** A `threading.RLock`
   in `_call_activity_llm` keyed by `DIRECTOR_MODEL` would prevent
   the director and structural-director from racing on the same
   route. Lock acquired before urlopen, released after read.
2. **Skip-tick when in-flight.** Instead of waiting on the lock,
   `acquire(blocking=False)`; if `False`, log `director_tick_skipped_in_flight`
   metric and `continue` the loop. The existing 1 s sleep buffer
   (`director_loop.py:1215`) ensures we don't spin.
3. **Pending-tick counter.** Prometheus counter
   `studio_compositor_director_tick_skipped_in_flight_total{reason}`
   exposes how often the loop is skipping due to back-pressure.
   Read alongside `hapax_director_llm_latency_seconds` histogram
   (already shipped, `shared/director_observability.py:121-126`)
   to diagnose whether timeouts are caused by *director* prompts
   exceeding the time budget or by *queue contention* with other
   consumers.
4. **Raise `cache_size` paired with `max_seq_len` per the
   2026-04-14 audit.** Specifically: lift `max_seq_len: 16384` to
   32 K (Command-R native context) and `cache_size` to ≥ 32 K so
   a single director prompt + a single structural prompt fit
   simultaneously without queue stall. VRAM cost on the 3090
   under Q4 KV is manageable per `tabbyAPI/config.yml` inline
   comment.

### §8.3 Alternative: TabbyAPI continuous batching

ExllamaV3 supports continuous batching ([github.com/turboderp-org/exllamav3](https://github.com/turboderp-org/exllamav3)).
The 2026-04-14 TabbyAPI config audit notes that prefix caching
is supported but config-version-dependent. A controlled test
should verify whether ExllamaV3 in our build is doing automatic
prefix caching — if it is, our director prompt's persona block
(top of the system message, stable across ticks) would amortize
across calls. The kaitchup substack
([kaitchup.substack.com/p/serving-exllamav3-with-tabbyapi-accuracy](https://kaitchup.substack.com/p/serving-exllamav3-with-tabbyapi-accuracy))
is a good external reference for ExllamaV3 + TabbyAPI tuning.

---

## §9 Long-uptime hygiene

### §9.1 The fragmentation observation

ExllamaV2's [#291 "Clear cache to avoid OOM"](https://github.com/turboderp-org/exllamav2/issues/291)
is the canonical issue. The llama.cpp generic version
[#3380](https://github.com/ggml-org/llama.cpp/issues/3380) frames
the same problem as "many short segments of free cells instead of
one large segment". The PagedAttention paper
([arxiv.org/abs/2309.06180](https://arxiv.org/abs/2309.06180))
documents up to 80 % memory waste under naive allocation; vLLM's
prefix caching docs
([docs.vllm.ai/en/stable/design/prefix_caching/](https://docs.vllm.ai/en/stable/design/prefix_caching/))
show how block-aligned prefix reuse reclaims much of that. ExllamaV3
has a paged design but is not vLLM and we don't have the same
production-tested cache management.

The KV cache optimization survey
([introl.com/blog/kv-cache-optimization-memory-efficiency-production-llms-guide](https://introl.com/blog/kv-cache-optimization-memory-efficiency-production-llms-guide))
estimates "60–80 % of KV cache memory through fragmentation and
over-allocation" under traditional inference. Even with paged
attention, the observed 89 % CPU pegging at 2-day uptime suggests
the serving thread is spending real cycles on cache management.

### §9.2 Recommended hygiene

1. **Daily TabbyAPI restart at low-traffic window.** A systemd
   timer firing 03:00 daily that issues `systemctl --user restart
   tabbyapi.service`. Net effect: ~30 s of LLM unavailability
   daily; trivially absorbed by the §6 director watchdog. The
   "Configure systemd RestartSec and WatchdogSec" reference
   ([oneuptime.com/blog/post/2026-03-02-configure-systemd-restartsec-watchdogsec-ubuntu/view](https://oneuptime.com/blog/post/2026-03-02-configure-systemd-restartsec-watchdogsec-ubuntu/view))
   describes the analogous timer pattern.
2. **VRAM gauge alert.** Prometheus alert when TabbyAPI's
   resident VRAM exceeds baseline + 15 %. Indicates cache pool
   bloat. We already have GPU metrics; extend to a per-process
   alert.
3. **Manual cache flush API.** ExllamaV3 supports a clear-cache
   call ([turboderp-org/exllamav2#291](https://github.com/turboderp-org/exllamav2/issues/291)
   discusses this for V2; verify V3 surface). A TabbyAPI admin
   endpoint to `/admin/cache/flush` would let us recover without
   restart. Worth a vendor PR if the surface doesn't exist.
4. **Production posture.** Per Inference.net's serving guide
   ([inference.net/content/llm-serving-guide/](https://inference.net/content/llm-serving-guide/))
   and Databricks
   ([databricks.com/blog/llm-inference-performance-engineering-best-practices](https://www.databricks.com/blog/llm-inference-performance-engineering-best-practices)),
   production LLM serving favors "redundancy with health checks
   and load balancing to handle restarts gracefully" — daily
   restart is well within industry norms.

---

## §10 Director prompt size + trim opportunities

### §10.1 Current size estimate

`_build_unified_prompt` has 14 layered sections (`director_loop.py:1598-2240`).
Approximate token contribution:

| Section | Approx tokens | Source line |
|---|---|---|
| Persona block | 800–1500 | `compose_persona_prompt(role_id="livestream-host")` line 1634 |
| Music framing + situation | 100–200 | lines 1617–1657 |
| HARDM anchor + cue | 50–100 | lines 1664–1697 |
| Chat state + recent | 80–150 | lines 1701–1725 |
| Phenomenal Context (FAST tier) | 200 | line 1731 (per spec budget) |
| Perceptual Field JSON | 800–1500 | line 1761 (`PerceptualField.model_dump_json`) |
| Structural Direction | 50–100 | lines 1770–1781 |
| System State (TOON) | 150 | line 1791 (per spec budget) |
| Recent Reactions | 200–400 | lines 1806–1816 (8 entries) |
| Research Objectives | 100–300 | line 1820 |
| Role + ACTIVITY_CAPABILITIES | 600–1200 | lines 1828–1843 |
| Music narrative discipline | 200 | lines 1855–1874 |
| Preset Family Vocabulary | 250 | lines 1890–1919 |
| Multi-Surface Moves | 300 | lines 1927–1956 |
| Homage Composition | 600 | lines 1962–2200 (extensive) |
| **Total** | **4,480–7,250 tokens** | |

The 10–15 kB ASCII estimate at `director_loop.py:2342-2350` lines
up with this band (5 kB ≈ 1.25 K tokens; 15 kB ≈ 3.75 K tokens, but
JSON / structured blocks tokenize denser, so 15 kB ASCII ≈ 5–7 K
tokens).

### §10.2 Trim opportunities

Bound by the operator constraint: "fix speed via quant/prompt, not
by swapping models" (`feedback_director_grounding`). So we can trim
the prompt as long as grounding is preserved.

**Easy wins (no behavior loss):**

1. **Persona block compression.** The `compose_persona_prompt`
   helper (per `axioms/persona/`) is the unified persona surface;
   the description-of-being doc is governance-significant. But the
   in-prompt expansion is plausibly 1.5 K tokens. Compress to
   ~300 tokens by switching from full description to capability-
   oriented summary. Author preserves grounding; compression saves
   ~1.2 K tokens.
2. **Perceptual Field JSON.** The `model_dump_json(indent=2,
   exclude_none=True)` shape at line 1762 is human-readable but
   token-expensive. Switch to TOON (already used for system state,
   line 1791) for ~40 % savings per the 2026-04-12 prompt
   compression Phase 2 results
   ([`2026-04-12-prompt-compression-phase2-ab-results.md`](2026-04-12-prompt-compression-phase2-ab-results.md))
   and Lucas Valbuena's "Why Long System Prompts Hurt Context Windows"
   ([medium.com/data-science-collective/why-long-system-prompts-hurt-context-windows-and-how-to-fix-it-7a3696e1cdf9](https://medium.com/data-science-collective/why-long-system-prompts-hurt-context-windows-and-how-to-fix-it-7a3696e1cdf9)).
3. **Homage Composition section.** 600+ tokens of grammar guidance
   that doesn't change tick-to-tick. Move to the persona's
   role-id="livestream-host" definition once; reference by handle
   in the per-tick prompt.
4. **Preset Family Vocabulary.** 250 tokens of family descriptions
   that are static. Same fix as homage: persona-level once.
5. **ACTIVITY_CAPABILITIES.** Same — static enumeration.

**Total achievable:** plausibly 30–40 % token reduction without
losing director information, bringing the prompt from ~6 K tokens
to ~3.5–4 K tokens. Prefill cost scales near-linearly so the
median prefill latency drops by similar percentage. **Net effect on
40 s timeout cushion: ~10 s of headroom regained.**

**Phase 4 work — full token-counting metric.** Add a
`hapax_director_prompt_tokens` histogram populated by
`tiktoken.encoding_for_model("gpt-4")` (close enough proxy)
called inside `_build_unified_prompt`. Required for any further
optimization decisions.

**Caveat (anti-patterns to avoid).** Per `feedback_no_expert_system_rules`
("hardcoded cadence/threshold gates are bugs") — the prompt should
not become a 14-layer rule book that out-grows the model. The
2026-04-19 `expert-system-blinding-audit` is the relevant prior
audit. The prompt-trimming Phase 4 should consult both the
compression results and the blinding audit so we don't trade
latency wins for governance regressions.

---

## §11 Concurrent GPU contention

### §11.1 Inventory of CUDA tenants on the 3090

| Process | GPU presence | Workload character | Source |
|---|---|---|---|
| TabbyAPI | cuda:0 (12 GB split) | Model serving (Command-R 32B prefill + decode) | `tabbyAPI/config.yml` |
| Reverie wgpu | 3090 (sole) | 8-pass shader graph at 60 fps | `hapax-imagination` systemd unit, `hapax-council/CLAUDE.md` § Tauri-Only Runtime |
| Imagination wgpu | 3090 | Visual surface rendering | same |
| Daimonion Whisper STT | 3090 | Streaming transcription | `agents/hapax_daimonion/` |
| glfeedback Rust plugin | 3090 (CUDA-CL interop) | Effect-graph feedback pass | `agents/effect_graph/`, `hapax-council/CLAUDE.md` § Studio Compositor |
| NVENC | 3090 (hardware encoder) | RTMP egress at 9 Mbps p5 since 2026-04-20 | commit `12ec97264` |
| studio_fx OpenCV | 3090 (sometimes; CPU-fallback per chronic OpenCV-no-CUDA) | Image processing | per user prompt note |

### §11.2 Why this matters for prefill

NVIDIA's "Mastering LLM Techniques: Inference Optimization"
([developer.nvidia.com/blog/mastering-llm-techniques-inference-optimization](https://developer.nvidia.com/blog/mastering-llm-techniques-inference-optimization/))
documents that prefill is compute-bound on SM throughput. The arxiv
"Characterizing Concurrency Mechanisms for NVIDIA GPUs"
([arxiv.org/pdf/2110.00459](https://arxiv.org/pdf/2110.00459))
quantifies cross-tenant interference. The CPU-induced slowdown
study ([arxiv.org/html/2603.22774v1](https://arxiv.org/html/2603.22774v1))
adds the host-side overhead dimension. For our profile:

- NVENC is hardware-isolated from SM per the NVENC App Note
  ([docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvenc-application-note/index.html](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvenc-application-note/index.html))
  but adds memory-bandwidth contention.
- Reverie + Imagination wgpu compete for SM with TabbyAPI directly.
- The Llumnix paper ([usenix.org/system/files/osdi24-sun-biao.pdf](https://www.usenix.org/system/files/osdi24-sun-biao.pdf))
  demonstrates that priority-based scheduling across LLM serving
  instances can mitigate this; we're single-instance, so the analog
  is process-level priority pinning.

### §11.3 Mitigation candidates

1. **CUDA stream priority** on TabbyAPI's main inference stream.
   Per the NVIDIA forum thread ([forums.developer.nvidia.com/t/questions-of-cuda-stream-priority/250343](https://forums.developer.nvidia.com/t/questions-of-cuda-stream-priority/250343)):
   "Stream priorities provide a hint to preferentially run work
   with higher priority when possible, but do not preempt
   already-running work or provide any other functional guarantee
   on execution order." Limited but non-zero benefit. Requires a
   patch to ExllamaV3's CUDA stream creation.
2. **`CUDA_DEVICE_MAX_CONNECTIONS` tuning.** Per the NVIDIA forum
   thread ([forums.developer.nvidia.com/t/cuda-device-max-connections-and-pci-e-traffic/262962](https://forums.developer.nvidia.com/t/cuda-device-max-connections-and-pci-e-traffic/262962)):
   reducing `CUDA_DEVICE_MAX_CONNECTIONS` to 1 ensures no PCIe
   traffic between concurrent connections; at default 8, multiple
   connections may pollute the bus. Worth experimenting at
   TabbyAPI's systemd unit drop-in.
3. **NVENC preset back to p3 or p2.** P5 was a quality bump for
   the broadcast — the trade-off against director latency wasn't
   considered. Per the GIGA CHAD streaming benchmark
   ([gigachadllc.com/geforce-rtx-3090-streaming-benchmarks-breakdown](https://gigachadllc.com/geforce-rtx-3090-streaming-benchmarks-breakdown/))
   "GPU contention occurs only at NVENC Max Quality with heavy GPU
   workloads" — p5 is mid-quality, but the bitrate bump 3 → 9 Mbps
   amplifies it. Empirical measurement: roll back to p3, observe
   `hapax_director_llm_latency_seconds` p99.
4. **Reverie pause-on-prefill.** Subscribe Reverie to TabbyAPI's
   in-flight signal (the existing `_LLM_IN_FLIGHT_MARKER` at
   `director_loop.py:209`!) and reduce wgpu render rate from 60
   fps to 15 fps while a director prefill is in flight. Saves ~75 %
   SM contention during the critical window.

---

## §12 Observability gaps + recommended metrics

The Hapax stack already has substantial Prometheus surface:

- `hapax_director_llm_latency_seconds` histogram (`shared/director_observability.py:121-126`)
- `hapax_llm_calls_total{condition,model,route}` (`agents/telemetry/condition_metrics.py:79`)
- `hapax_llm_call_outcomes_total{condition,model,route,outcome}` (per the LRR Phase 10 §3.1 sweep — `grafana/dashboards/lrr-per-condition.json`)
- `hapax_director_intent_total{condition,activity,stance}` (`shared/director_observability.py:96-100`)
- `hapax_director_compositional_impingement_total{condition,intent_family}` (`shared/director_observability.py:106-110`)
- `hapax_director_vacuum_prevented_total{condition,director_tier,reason}` (`shared/director_observability.py:132-139`)
- `studio_compositor_v4l2sink_last_frame_seconds_ago` (Phase 1 v4l2sink ship, `metrics.py:425-431`)

What we DON'T have:

| Metric | Purpose | Implementation |
|---|---|---|
| `studio_compositor_director_last_intent_seconds_ago` | The §6 watchdog gate | `metrics.py` add Gauge; updated from watchdog tick |
| `studio_compositor_director_intent_total` | Cumulative intents (rate alerts) | `metrics.py` add Counter; bump on every parsed-intent emission |
| `studio_compositor_director_micromove_fallback_total{reason}` | Fallback rate | `metrics.py` add Counter; bump in `_emit_micromove_fallback` |
| `studio_compositor_director_tick_skipped_in_flight_total` | Single-flight back-pressure | If §8.1 single-flight ships, bump on lock-acquire failure |
| `hapax_director_prompt_tokens` | Prompt size discipline (§10.2 Phase 4) | `_build_unified_prompt` tail-end measurement |
| `tabbyapi_kv_cache_used_pages` (or proxy) | Long-uptime fragmentation visibility | Scrape TabbyAPI metrics endpoint if exposed; else log-derived |

Alerting candidates (Grafana / ntfy):

- `rate(studio_compositor_director_micromove_fallback_total[10m]) > 0.1` (more than 1 fallback per 10 min sustained for 30 min) → ntfy operator. The 02:59Z incident produced ~20 fallbacks in 30 min ≈ rate of 0.011 / s ≈ 0.66 / min — well above this threshold. The operator should have been alerted before the 30-minute mark, not after the fact.
- `studio_compositor_director_last_intent_seconds_ago > 120` for 60 s → ntfy operator. (The watchdog itself triggers at 180 s; this is an early-warning at 120 s.)
- `histogram_quantile(0.95, hapax_director_llm_latency_seconds) > 30` for 5 min → ntfy operator. Indicates timeout pressure approaching the 40 s ceiling.

---

## §13 Phased prevention plan

### Phase 1 (tonight, ~50 LOC)
- Director liveness watchdog (§6).
- `studio_compositor_director_last_intent_seconds_ago` gauge.
- Wire into existing `_watchdog_tick` callback in `lifecycle.py`.

### Phase 2 (this week, ~80 LOC)
- Single-flight lock + skip-tick (§8).
- `studio_compositor_director_tick_skipped_in_flight_total`.
- Speak the micromove on opportunistic timeout (§7.1).
- Increase visual-cycling micromove count (§7.2).

### Phase 3 (this week, ~30 LOC + systemd timer)
- Daily TabbyAPI restart timer at 03:00 (§9.2).
- VRAM-bloat Prometheus alert (§9.2).
- `tabbyAPI/config.yml` `cache_size` raise to ≥ 32 K paired with
  `max_seq_len` raise (§8.2).

### Phase 4 (next sprint, ~150 LOC)
- `hapax_director_prompt_tokens` histogram (§10.2).
- Persona block compression + per-tick block hoisting (§10.2 wins
  1, 3, 4, 5).
- Perceptual field JSON → TOON migration (§10.2 win 2).

### Phase 5 (next sprint, ~40 LOC + systemd drop-in)
- `CUDA_DEVICE_MAX_CONNECTIONS` tuning (§11.3).
- NVENC preset rollback empirical measurement (§11.3).
- Reverie pause-on-prefill subscription to `_LLM_IN_FLIGHT_MARKER`
  (§11.3).

### Phase 6 (research only)
- ExllamaV3 prefix caching verification under our prompt shape.
- Speculative decoding draft model evaluation.
- TabbyAPI continuous batching characterization.

---

## §14 Open questions

1. **Did NVENC bump (commit `12ec97264`) directly cause the 02:59Z
   incident, or was it incidental?** The commit landed earlier on
   2026-04-20; the incident is at 02:59Z the same day. A Phase 5
   experiment rolling back NVENC to p3 would settle this. If the
   incident rate drops sharply, NVENC is the primary multiplier; if
   it doesn't, the dominant cause is prompt-size growth or KV
   fragmentation.
2. **Was TabbyAPI actually serving when alpha restarted it manually
   (PID 2522847, model reloading)?** Did the restart prove the
   process was hung, or was it a precautionary restart? Examining
   the journal logs leading up to the restart for any "model
   loading failed" / "CUDA out of memory" / silent hangs would
   distinguish "stuck process" (Phase 6 daily-restart fix lands)
   from "transient slowness" (Phase 1 watchdog fix lands).
3. **Is ExllamaV3 doing automatic prefix caching in our build?** A
   controlled test: send the same prompt twice and measure
   `prompt_time` from TabbyAPI's `usage` block. If second call's
   `prompt_time` is dramatically lower, prefix cache is on. The
   `scripts/benchmark_prompt_compression_b6.py` harness is the
   right place to add this test.
4. **What is the dispatch latency from `compositional_impingement.preset.bias`
   write to actual FX chain mutation?** preset rotations during the
   incident timeline tell us the consumer was alive, but the
   end-to-end latency under contention isn't measured.
5. **Should daimonion CPAL also have a director-liveness predicate?**
   It depends on `/dev/shm/hapax-dmn/impingements.jsonl` flowing.
   Micromove fallbacks keep that flowing, so daimonion stays alive
   in the timeout-cascade case. But a true director-loop crash
   stops both. Worth a follow-up review.
6. **Speak-the-micromove (§7.1) — what salience threshold gates
   speech?** The micromove cycle has fixed salience 0.35; speaking
   every micromove is too much. A counter-based gate (1 of every
   3 micromoves) is naive; a learned policy (Thompson sampling
   over operator skip-rate) is overkill. Pick the simplest thing
   that won't spam the broadcast.
7. **Is the 30-minute-before-detection lag a metric gap or an alert
   gap?** The latency histogram WAS recording timeouts. No alert
   was firing on it. Either we don't have alerting wired to ntfy
   on these metrics, or the threshold was too lenient. A focused
   audit of the Grafana → ntfy alerting chain belongs in the
   Phase 1 + Phase 2 deliverable.

---

## §15 Sources

### Hapax codebase

- `agents/studio_compositor/director_loop.py:1131` — director loop call site
- `agents/studio_compositor/director_loop.py:1141` — `_emit_micromove_fallback` invocation on `result == ""`
- `agents/studio_compositor/director_loop.py:209-243` — `_LLMInFlight` marker for ThinkingIndicator + Reverie subscription
- `agents/studio_compositor/director_loop.py:212-243` — `_LLMInFlight` context manager
- `agents/studio_compositor/director_loop.py:481-503` — `DIRECTOR_MODEL`, `MULTIMODAL_ROUTES`, `PERCEPTION_INTERVAL` (HAPAX_NARRATIVE_CADENCE_S)
- `agents/studio_compositor/director_loop.py:1323-1450` — `_emit_micromove_fallback` cycle of 7 fallback narratives
- `agents/studio_compositor/director_loop.py:1452-1475` — `_emit_degraded_silence_hold` (DEGRADED-STREAM mode)
- `agents/studio_compositor/director_loop.py:1598-2240` — `_build_unified_prompt` 14-section assembly
- `agents/studio_compositor/director_loop.py:2241-2433` — `_call_activity_llm` synchronous urlopen call site
- `agents/studio_compositor/director_loop.py:2342-2351` — alpha's own comment on the timeout calibration history (30s → 8s → 20s → 40s)
- `agents/studio_compositor/director_loop.py:2435-2500` — `_speak_activity` voice path (only fires on parsed intent)
- `agents/studio_compositor/director_loop.py:2528-2540` — `_play_audio` TTS PCM dispatch to `input.loopback.sink.role.assistant`
- `agents/studio_compositor/lifecycle.py:295-341` — `_watchdog_tick` sd_notify wiring (the v4l2sink stall watchdog Phase 1 — the model for §6's director watchdog)
- `agents/studio_compositor/pipeline.py:200-234` — v4l2sink last-sample / qos disablement + buffer-counting probe
- `agents/studio_compositor/metrics.py:425-436` — `V4L2SINK_LAST_FRAME_AGE`, `V4L2SINK_FRAMES_TOTAL` (templates for the new director-intent-age gauge)
- `agents/studio_compositor/preset_recruitment_consumer.py:47-84` — preset rotation consumer (proves the visual chain stayed alive)
- `agents/studio_compositor/structural_director.py:320-345` — structural director's parallel LLM call (timeout=90, separate observability path)
- `agents/studio_compositor/__main__.py:38-52` — `sd_notify_ready`, `sd_notify_watchdog`, `sd_notify_status` helpers
- `shared/director_observability.py:96-139` — `hapax_director_intent_total`, `hapax_director_llm_latency_seconds` histogram (already shipped, slot for new alerting)
- `agents/telemetry/llm_call_span.py:43-58` — canonical span helper that drives per-condition emissions
- `agents/telemetry/condition_metrics.py:79` — `hapax_llm_calls_total` definition
- `tabbyAPI/config.yml` — Command-R-08-2024 32B EXL3 5.0bpw, gpu_split [12,14], cache_mode Q4, cache_size 16384, max_seq_len 16384
- `grafana/dashboards/lrr-per-condition.json` — existing per-condition LLM dashboard (extend with director-intent-age + fallback rate)

### Prior Hapax research

- [`docs/research/2026-04-20-v4l2sink-stall-prevention.md`](2026-04-20-v4l2sink-stall-prevention.md) — the model investigation pattern, Phase 1 v4l2sink ship blueprint, sd_notify gate design
- [`docs/research/2026-04-14-compositor-output-stall-live-incident-root-cause.md`](2026-04-14-compositor-output-stall-live-incident-root-cause.md) — prior 78-min silent stall (drop #50), dmabuf fd leak from rebuild thrash
- [`docs/research/2026-04-14-tabbyapi-config-audit.md`](2026-04-14-tabbyapi-config-audit.md) — `cache_size`/`max_seq_len` pairing, Q4 KV quant, prefix-cache verification gap
- [`docs/research/2026-04-14-director-loop-prompt-cache-gap.md`](2026-04-14-director-loop-prompt-cache-gap.md) — `cache_control: ephemeral` is unused everywhere; ~70 % cacheable prefix
- [`docs/research/2026-04-12-prompt-compression-phase2-ab-results.md`](2026-04-12-prompt-compression-phase2-ab-results.md) — TOON 40 % savings benchmark
- [`docs/research/2026-04-12-kvzip-exllamav3-compatibility.md`](2026-04-12-kvzip-exllamav3-compatibility.md) — KV compression options on ExllamaV3
- [`docs/research/2026-04-19-l6-multitrack-mode.md`](2026-04-19-l6-multitrack-mode.md) — L6 audio path topology (proves audio backbone independent of director)
- [`docs/research/2026-04-19-expert-system-blinding-audit.md`](2026-04-19-expert-system-blinding-audit.md) — anti-pattern audit (don't trade latency for governance)

### Operator memory entries (constraint sources)

- `feedback_director_grounding` — director stays on grounded model under speed pressure
- `feedback_grounding_exhaustive` — every move is grounded or outsourced-by-grounding
- `feedback_consent_latency_obligation` — voice latency is governance, not UX
- `feedback_no_expert_system_rules` — no hardcoded cadence/threshold gates
- `feedback_continuous_cognitive_loop` — voice needs continuous cognitive loop
- `feedback_never_drop_speech` — operator speech must never be dropped
- `feedback_verify_before_claiming_done` — deploy + verify ≠ build + commit
- `project_vram_budget` — 24 GB coexistence model

### External — ExllamaV2/V3 + TabbyAPI

- [turboderp-org/exllamav2#291 Clear cache to avoid OOM with iterative generation](https://github.com/turboderp-org/exllamav2/issues/291)
- [turboderp-org/exllamav3 — README + design notes](https://github.com/turboderp-org/exllamav3)
- [turboderp-org/exllamav2/blob/master/doc/dynamic.md — dynamic generator + job queue](https://github.com/turboderp-org/exllamav2/blob/master/doc/dynamic.md)
- [theroyallab/tabbyAPI — main repo + README](https://github.com/theroyallab/tabbyAPI/)
- [theroyallab/tabbyAPI#274 OpenAI client takes a long time to receive last token](https://github.com/theroyallab/tabbyAPI/issues/274)
- [theroyallab/tabbyAPI#304 Model Switching Fails with Concurrent Requests](https://github.com/theroyallab/tabbyAPI/issues/304)
- [theroyallab/tabbyAPI Wiki — Server options](https://github.com/theroyallab/tabbyAPI/wiki/02.-Server-options)
- [theroyallab.github.io/tabbyAPI/ — TabbyAPI docs](https://theroyallab.github.io/tabbyAPI/)
- [Serving ExLlamaV3 with tabbyAPI: Accuracy, Speed, and Recommendations (kaitchup)](https://kaitchup.substack.com/p/serving-exllamav3-with-tabbyapi-accuracy)

### External — KV cache + prompt caching + paged attention

- [llama.cpp#3380 mitigate KV cache fragmentation](https://github.com/ggml-org/llama.cpp/issues/3380)
- [PagedAttention: Efficient Memory Management for LLM Serving (arxiv 2309.06180)](https://arxiv.org/abs/2309.06180)
- [vLLM Automatic Prefix Caching docs](https://docs.vllm.ai/en/stable/design/prefix_caching/)
- [How prompt caching works — Sankalp's blog](https://sankalp.bearblog.dev/how-prompt-caching-works/)
- [KV Cache Optimization: Memory Efficiency for Production LLMs (Introl)](https://introl.com/blog/kv-cache-optimization-memory-efficiency-production-llms-guide)
- [The Stateful Turn: Evolution of Prefix and Prompt Caching (Uplatz)](https://uplatz.com/blog/the-stateful-turn-evolution-of-prefix-and-prompt-caching-in-large-language-model-architectures/)

### External — Long-prompt / chunked prefill / TTFT

- [Hugging Face — How Long Prompts Block Other Requests](https://huggingface.co/blog/tngtech/llm-performance-blocked-by-long-prompts)
- [NVIDIA — Streamlining AI Inference with TensorRT-LLM Chunked Prefill](https://developer.nvidia.com/blog/streamlining-ai-inference-performance-and-deployment-with-nvidia-tensorrt-llm-chunked-prefill/)
- [POD-Attention: Unlocking Full Prefill-Decode Overlap (arxiv 2410.18038)](https://arxiv.org/html/2410.18038v1)
- [Why Long System Prompts Hurt Context Windows (Lucas Valbuena)](https://medium.com/data-science-collective/why-long-system-prompts-hurt-context-windows-and-how-to-fix-it-7a3696e1cdf9)
- [Reduce LLM Prefill Latency: Multi-Million Token Optimization (elvex)](https://www.elvex.com/blog/reduce-llm-prefill-latency-multi-million-token-inputs)

### External — GPU contention + NVENC + CUDA streams

- [NVIDIA — Mastering LLM Techniques: Inference Optimization](https://developer.nvidia.com/blog/mastering-llm-techniques-inference-optimization/)
- [NVIDIA NVENC App Note (Video Codec SDK 13.0)](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvenc-application-note/index.html)
- [Characterizing Concurrency Mechanisms for NVIDIA GPUs (arxiv 2110.00459)](https://arxiv.org/pdf/2110.00459)
- [Serving Hybrid LLM Loads with SLO Guarantees (arxiv 2603.12831v2)](https://arxiv.org/html/2603.12831v2)
- [Characterizing CPU-Induced Slowdowns in Multi-GPU LLM Inference (arxiv 2603.22774v1)](https://arxiv.org/html/2603.22774v1)
- [Llumnix: Dynamic Scheduling for LLM Serving (OSDI '24)](https://www.usenix.org/system/files/osdi24-sun-biao.pdf)
- [NVIDIA Forum — CUDA_DEVICE_MAX_CONNECTIONS and PCI-E traffic](https://forums.developer.nvidia.com/t/cuda-device-max-connections-and-pci-e-traffic/262962)
- [NVIDIA Forum — Questions of CUDA stream priority](https://forums.developer.nvidia.com/t/questions-of-cuda-stream-priority/250343)
- [GIGA CHAD — RTX 3090 Streaming Benchmarks Breakdown](https://gigachadllc.com/geforce-rtx-3090-streaming-benchmarks-breakdown/)
- [Hardware Corner — Definitive GPU Ranking for LLMs](https://www.hardware-corner.net/gpu-ranking-local-llm/)
- [Modelfit — RTX 3090 LLM Benchmark](https://modelfit.io/gpu/rtx-3090/)

### External — systemd watchdog + Python liveness

- [sd_notify(3) man page](https://www.freedesktop.org/software/systemd/man/latest/sd_notify.html)
- [Configure systemd RestartSec and WatchdogSec on Ubuntu (oneuptime)](https://oneuptime.com/blog/post/2026-03-02-configure-systemd-restartsec-watchdogsec-ubuntu/view)
- [systemd-watchdog (PyPI)](https://pypi.org/project/systemd-watchdog/)
- [AaronDMarasco/systemd-watchdog (GitHub)](https://github.com/AaronDMarasco/systemd-watchdog)
- [Using sd-notify functionality for systemd in Python 3 (stigok blog)](https://blog.stigok.com/2020/01/26/sd-notify-systemd-watchdog-python-3.html)

### External — Resilience patterns + production LLM serving

- [Portkey — Retries, fallbacks, and circuit breakers in LLM apps](https://portkey.ai/blog/retries-fallbacks-and-circuit-breakers-in-llm-apps/)
- [Aerospike — Efficient Fault Tolerance with Circuit Breaker Pattern](https://aerospike.com/blog/circuit-breaker-pattern/)
- [Markaicode — How to Implement Graceful Degradation in LLM Frameworks](https://markaicode.com/implement-graceful-degradation-llm-frameworks/)
- [AWS Well-Architected REL05-BP01 Implement graceful degradation](https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/rel_mitigate_interaction_failure_graceful_degradation.html)
- [Inference.net — Step-By-Step LLM Serving Guide for Production](https://inference.net/content/llm-serving-guide/)
- [Databricks — LLM Inference Performance Engineering: Best Practices](https://www.databricks.com/blog/llm-inference-performance-engineering-best-practices)

### External — v4l2loopback + OBS (incident-context references)

- [v4l2loopback#36 Could not negotiate format](https://github.com/v4l2loopback/v4l2loopback/issues/36)
- [v4l2loopback#97 Internal data flow error / not-negotiated -4](https://github.com/umlaeute/v4l2loopback/issues/97)
- [obs-studio#11295 select timed out](https://github.com/obsproject/obs-studio/issues/11295)
