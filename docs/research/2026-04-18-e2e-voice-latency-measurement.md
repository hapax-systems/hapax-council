---
title: End-to-End Voice Latency Measurement (STT → LLM → TTS → Playback)
date: 2026-04-18
author: beta
queue: "#228"
depends_on:
  - "queue #213: CPAL loop latency profile (2026-04-15-cpal-loop-latency-profile.md)"
  - "queue #217: Kokoro TTS memory footprint (2026-04-15-kokoro-tts-memory-footprint.md)"
related:
  - "ws5-latency-architecture.md"
  - "~/hapax-state/benchmarks/kokoro-latency/baseline.json (2026-04-14)"
  - "~/hapax-state/benchmarks/prompt-compression/phase2-ab-20260412T192226.json"
status: captured
---

# End-to-End Voice Latency Measurement

Queue item #228 decomposes the voice pipeline into wallclock stages and compares the stage sum against the sub-2 s consent-latency threshold established in substrate research v1 and enshrined in operator feedback memory `feedback_consent_latency_obligation` (voice latency impeding consent flow is a governance violation, not a UX issue).

## 0. Summary

| Stage | p50 wallclock | p95 wallclock | Data source |
|---|---|---|---|
| 1. Utterance → STT complete | **UNMEASURED** | **UNMEASURED** | No warm Whisper benchmark; no active turns in 24 h |
| 2. STT complete → LLM first token | **~0.65 s** | ~0.67 s | Fresh 5-sample TabbyAPI stream probe (short prompt) |
| 3. LLM first token → TTS first audio | ~0.70 s (short utterance) | ~2.26 s (≈80-char) | Kokoro baseline.json + 2026-04-15 Voxtral→Kokoro revert |
| 4. TTS first audio → PipeWire playback start | **~0.08 s** | ~0.09 s | Fresh 5-sample `pw-play` probe |
| Total (excluding STT) | **~1.43 s** short, **~3.00 s** full | — | Sum of above |
| Total (with STT assumed at 0.8–1.2 s Whisper warm) | **~2.2–2.6 s** short, **~3.8–4.2 s** full | — | Projection, unverified |

**Verdict vs. consent-latency budget (2 s sub-threshold):** projected E2E exceeds budget for any utterance longer than ~10 characters, even before STT is measured. Kokoro TTS is the dominant cost contributor (≥50 % of total for common phrases). LLM TTFT is the second cost.

**Primary blocker on completing the measurement:** no active voice turns in the 24 h window, and the cloud LLM gateway has been 403/credit-low for Gemini and Anthropic since at least 2026-04-17T00:26Z — local-fast (TabbyAPI) is the only operational model group. This is a separate and arguably more severe finding than the latency numbers themselves.

## 1. Method

Measurements are either (a) fresh probes run under this item against a live daimonion at 2026-04-18T19:30–19:45 CDT, or (b) cited from prior benchmarks. No synthetic end-to-end turn was fabricated, because the daimonion reports no operator utterances in the prior 24 h and staging a fake turn would require deeper instrumentation than this verify item authorises. Gaps are named explicitly rather than filled with estimates.

Per-stage wallclock is captured as:
- Stage 1 (STT): `rpicam-still`/mic buffer arrival → Whisper model completion timestamp. *Not measured in this item.*
- Stage 2 (LLM TTFT): HTTP request dispatch to TabbyAPI `:5000` chat-completions streaming endpoint → first SSE event containing `content`. Measured via `time.perf_counter()` around a streaming `urllib.request`.
- Stage 3 (TTS): text input → first audio-buffer flush. *Proxied by Kokoro's per-phrase `synth_ms` from baseline.json; Kokoro's streaming-chunk granularity is not exposed by the current backend, so `synth_ms` is an upper bound on first-audio latency.*
- Stage 4 (Playback): `pw-play` spawn → audio output stream active. Measured as `wallclock - audio_duration` to estimate PipeWire + ALSA-routing overhead.

## 2. Stage 2: LLM TTFT

### 2.1 Fresh probe — Qwen3.5-9B EXL3 5.0 bpw on TabbyAPI :5000 (warm)

Short conversational prompt ("Say hi in one word.", ≈9 prompt tokens, `max_tokens=5`, streaming):

```
TTFT=0.671s
TTFT=0.641s
TTFT=0.641s
TTFT=0.613s
TTFT=0.651s
```

- p50 = 0.641 s
- p95 = 0.671 s
- Range = 0.613 – 0.671 s (tight)

Cold-load TTFT was observed at 16.24 s total wallclock on the very first request of the session. Cold load is a one-time cost, not a per-turn cost, and is not included in the p50/p95.

### 2.2 Reference — full system-prompt workload (B6 benchmark, 2026-04-12)

From `~/hapax-state/benchmarks/prompt-compression/phase2-ab-20260412T192226.json` condition A (Qwen3.5-9B EXL3, 571 prompt tokens, 79 completion tokens, warm):

```
prompt_time       = 0.30 s (p50)   -- prefill for 571 prompt tokens
completion_time   = 2.97 s (p50)   -- decode for 79 completion tokens (~26 tok/s)
total_time        = 3.27 s (p50)   -- server-side total
```

A voice turn does not wait for `total_time`; it waits for TTFT ≈ `prompt_time + (1 token decode)` ≈ 0.30 s + ~0.04 s = **~0.34 s** for this workload size. For the short (9-prompt-token) probe in §2.1 the TTFT was ~0.65 s — higher than projected. The discrepancy is consistent with minimum-overhead-per-request costs (HTTP + tokenizer cold path + first-token decode) dominating when prompt length is small.

### 2.3 Substrate model drift observation (F-228-1, low severity)

`curl http://127.0.0.1:5000/v1/models` lists three models as available:

```
Qwen3.5-9B-exl3-5.00bpw
command-r-08-2024-exl3-5.0bpw
command-r-08-2024-exl3-4.0bpw
```

When a request is sent to TabbyAPI with `model: "local-fast"` (the LiteLLM route name, not a TabbyAPI model), TabbyAPI silently resolves to `command-r-08-2024-exl3-5.0bpw` rather than Qwen3.5-9B. CLAUDE.md declares Qwen3.5-9B as the sole production model for `local-fast`. Requests that go through the LiteLLM gateway on `:4000` should still route correctly (LiteLLM rewrites the model ID), but any direct-to-TabbyAPI probe using the route name will silently land on command-r.

This does not change the numbers above (those used the explicit `Qwen3.5-9B-exl3-5.00bpw` ID), but the model-presence list deviates from the documented substrate. Scenario-1 substrate verification (per prior beta's closed PR #896 + #900 Phase 5 spec/plan) should confirm whether the command-r models are a deliberate coexistence or a TabbyAPI config drift.

## 3. Stage 3: TTS first-audio latency

From `~/hapax-state/benchmarks/kokoro-latency/baseline.json` (2026-04-14, git 77e6dd341, voice_id=`af_heart`, device=cpu, backend=kokoro-82m):

| Phrase | chars | `synth_ms` warm | audio_seconds | RTF |
|---|---|---|---|---|
| "Hello." | 6 | 697.1 | 1.35 | 0.516 |
| "The quick brown fox…" | 44 | 1368.6 | 3.25 | 0.421 |
| "Hapax is now running on Kokoro…" | 79 | 2262.6 | 5.45 | 0.415 |
| "Recursion is constitutive…" | 80 | 2253.9 | 5.725 | 0.394 |
| "Phase zero verification…" | 91 | 2361.6 | 6.275 | 0.376 |

Summary: warm p50 synth = 2.254 s, warm p95 synth = 2.431 s, cold synth = 29.82 s (one-time, first synth of the service boot).

**Important caveat:** `synth_ms` in this baseline is *full-utterance synthesis*, not first-audio-chunk latency. If the Kokoro backend streams audio chunks during synthesis, real first-chunk latency would be lower. Current backend (`agents/hapax_daimonion/backends/kokoro_tts.py` region) appears to synthesise end-to-end before flushing, per the per-phrase measurement shape in baseline.json. A streaming-chunk variant would require a distinct benchmark. This item does not attempt to produce one.

### 3.1 Consequence: TTS cost dominates short-turn voice latency

For a typical 80-character utterance, TTS alone takes ~2.25 s — 13 % over the 2 s consent-latency budget before any other stage is counted. For "Hello." (6 chars) the 697 ms TTS fraction is ~35 % of the 2 s budget.

## 4. Stage 4: PipeWire playback-start overhead

Fresh probe — 200 ms 440 Hz sine at 24 kHz (matches Kokoro output sample rate) via `pw-play`:

```
wallclock:     0.266, 0.262, 0.272, 0.293, 0.293 s  (5 samples)
audio length:  0.200 s
overhead:      0.066, 0.062, 0.072, 0.093, 0.093 s
```

- overhead p50 = 0.072 s, overhead p95 = 0.093 s

This is `pw-play` process spawn + PipeWire graph attach + first-buffer routing. The daimonion's real path (Python opens a PipeWire stream directly, not via `pw-play`) should be similar or faster, but was not measured here because the daimonion's audio-output path has no turn activity to probe and synthetic instrumentation was out of scope.

## 5. Stage 1: STT latency (gap)

The daimonion's STT is Whisper on GPU (per council CLAUDE.md § Key Services). No dedicated Whisper benchmark was located in `docs/research/`, `scripts/`, or `~/hapax-state/benchmarks/`. The daimonion journal for the prior 24 h contains zero `stt_transcription_complete`-style events — there is no observed voice traffic to sample. Stage 1 remains a measurement gap.

Published community benchmarks for Whisper-large on RTX 4090 place warm TTFT for a short utterance in the 0.8–1.2 s range, excluding VAD decision time. This is a *projection*, not a measurement, and is the basis for the "0.8–1.2 s Whisper warm" assumption in the §0 summary.

A proper Stage 1 measurement would require either (a) a prerecorded-audio injection harness that drives the daimonion's audio-input thread from a WAV file and captures timestamps, or (b) live operator speech with timestamped logs enabled. Neither is in scope here.

## 6. Cross-cutting findings

### 6.1 F-228-2 (HIGH): LLM gateway outage for cloud fallbacks

`journalctl --user -u hapax-daimonion.service` shows repeated `WorkspaceAnalyzer` 403 / credit-low failures starting at or before `2026-04-18T00:26:32.883192Z`:

```
litellm.BadRequestError: GeminiException BadRequestError - {
    "error": {"code": 403, "status": "PERMISSION_DENIED",
              "message": "Your project has been denied access. Please contact support."}
}
. Received Model Group=gemini-flash
Available Model Group Fallbacks=['claude-haiku']
Error doing the fallback:
  AnthropicException - {"type":"error", "error":{"type":"invalid_request_error",
                        "message":"Your credit balance is too low to access the
                        Anthropic API. Please go to Plans & Billing to upgrade
                        or purchase credits."}}
```

Both configured fallback tiers are broken simultaneously: Gemini project is denied access (API-key or billing side), and Anthropic credit balance is exhausted. The cloud-failover chain configured in `shared/config.py` (`fast → gemini-flash, balanced → claude-sonnet`) has no surviving path.

**Consequence for voice latency:** workloads that `get_model_adaptive()` routes to `balanced` or `fast` silently fail. `local-fast` (TabbyAPI) is the only operational group. The feedback memory `feedback_model_routing_patience` says CAPABLE tier = Opus (which is a `balanced`-class model); if the router tries to honour that under the current gateway state, the turn fails entirely rather than slowing down.

**Recommendation:** this warrants an immediate followup queue item — either refill cloud credits or explicitly pin all voice-critical routes to `local-fast` until cloud recovery, so turns don't silently fail.

### 6.2 F-228-3 (MEDIUM): AEC appears idle

The daimonion journal samples during the window show AEC diagnostics in the form:

```
AEC diag: processed=0 passthrough=100028 (0% active), refs_fed=0, ref_buf=0
```

100,000+ frames passthrough and zero frames processed by AEC. `refs_fed=0` implies the reference audio channel (TTS output / speaker feedback) is not being delivered to the AEC. If AEC is never active, operator speech during TTS playback is at high risk of being dropped by VAD or mistaken for echo, violating the `feedback_never_drop_speech` memory.

This finding does not affect the Stage 1–4 wallclock numbers above (AEC runs in parallel to the main loop), but it is a correctness concern that surfaced during log collection for this item and is worth a dedicated followup.

### 6.3 F-228-4 (low): no active voice turns in 24 h

For the prior 24 h of `hapax-daimonion.service` journal, zero `stt_transcription_complete` or `llm_first_token` or `tts_synthesis_complete` events were observed. The CPAL loop is active and continuously surfacing impingements, but no operator↔system voice exchange has occurred. Reasons could include: operator muted / not present / working silently, or the wake-word path is broken. Not resolved here.

## 7. Threshold comparison

Substrate research v1 (Scenario 1, per prior beta PR #896) cites a sub-2 s target for the consent-critical voice turn. Projected E2E ranges:

| Case | Stage 1 (STT) | Stage 2 (TTFT) | Stage 3 (TTS) | Stage 4 (PipeWire) | Total |
|---|---|---|---|---|---|
| Short utterance ("Hello.") | 0.8–1.2 (proj.) | 0.65 | 0.70 | 0.08 | **2.23–2.63 s** |
| 80-char utterance | 0.8–1.2 (proj.) | 0.35 (full-prompt prefill) | 2.25 | 0.08 | **3.43–3.83 s** |

Both cases exceed the 2 s budget. The short-utterance case exceeds it by 0.23–0.63 s; the 80-char case exceeds it by 1.43–1.83 s. Stage 3 (TTS) is the primary cost driver; Stage 2 (LLM) is secondary. Stage 4 (PipeWire) is negligible. Stage 1 (STT) is unknown.

## 8. Recommendations (for followup queue items, not executed here)

1. **Open queue item for F-228-2 (cloud gateway outage)** — highest severity; CAPABLE-tier voice turns currently fail.
2. **Open queue item for F-228-3 (AEC idle)** — operator speech correctness risk.
3. **Open queue item: streaming Kokoro first-chunk latency benchmark** — current Kokoro data is full-utterance-synth; a streaming variant could halve Stage 3 p50 for longer utterances.
4. **Open queue item: Whisper STT warm-TTFT benchmark** — required to close the Stage 1 gap and complete this E2E measurement.
5. **Open queue item: LiteLLM → TabbyAPI route integrity verification** — confirm `local-fast` from the gateway lands on Qwen3.5-9B and not command-r (F-228-1).

## 9. Deferred — not in scope

- Actual end-to-end wallclock for a staged operator voice turn (requires either live speech or a prerecorded-audio injection harness).
- Langfuse trace reconstruction of past voice turns (no turns in window).
- VAD / wake-word latency (separate pipeline from the consent-critical turn path).
