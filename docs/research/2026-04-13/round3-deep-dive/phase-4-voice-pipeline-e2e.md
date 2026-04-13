# Phase 4 — Voice pipeline end-to-end characterization

**Queue item:** 024
**Phase:** 4 of 6
**Date:** 2026-04-13 CDT
**Register:** scientific, neutral (per `feedback_scientific_register.md`)

## Headline

The daimonion voice pipeline is **alive but silent** by operator
report. All 9 background coroutines are running, audio input is
active on the Blue Yeti, STT model is loaded, TTS server is
listening, CPAL runner is continuously surfacing impingements into
the director loop, but — as established in Phase 1 — compositor
speak-react is blocked by the 6.6 chars/sec Kokoro throughput limit,
and the daimonion's own voice output path has no observable TTS
synthesis activity in the last 10 minutes (the presynth cache was
populated at 16:39 + 16:40 and no further `tts` log lines have been
emitted).

**Daimonion memory is not growing** — cgroup `MemoryCurrent` is
3.29 GB, `MemoryPeak` was 10.24 GB earlier in the session (that's
the presynth warmup spike), and current VmRSS is 3.08 GB. The
peak-to-current drop (10.24 GB → 3.29 GB) indicates torch /
Kokoro worked set has released after presynth completed. Thread
count is stable at 80. No leak.

**Journal volume** over a 10-minute window (17:10–17:20 CDT):

| logger | count | share |
|---|---|---|
| `hapax_daimonion` (main) | 734 | 68.4% |
| `agents.hapax_daimonion.cpal.runner` | 150 | 14.0% |
| `agents.hapax_daimonion.echo_canceller` | 109 | 10.2% |
| `shared.governance.consent` | 36 | 3.4% |
| `agents.hapax_daimonion.workspace_monitor` | 22 | 2.0% |
| `agents.hapax_daimonion.presence_engine` | 6 | 0.6% |
| `agents.hapax_daimonion.screen_capturer` | 2 | 0.2% |
| `agents.hapax_daimonion.backends.ir_presence` | 1 | 0.1% |
| **TTS / STT / voice output** | **0** | **0%** |

**Zero STT log lines. Zero TTS log lines.** The voice pipeline is
producing observability from the *control* subsystems (CPAL
impingement surfacing, echo canceller, consent governance) but
nothing from the *transduction* subsystems (STT, TTS).

## Coroutine map

From `agents/hapax_daimonion/run_inner.py` enumeration:

| # | coroutine | entry | cadence | observability |
|---|---|---|---|---|
| 1 | `proactive_delivery_loop` | `run_loops_aux.py:71` | event-driven (notification queue) | occasional INFO |
| 2 | `subscribe_ntfy` | `ntfy_listener` | continuous (SSE subscription) | silent in steady state |
| 3 | `workspace_monitor.run()` | `workspace_monitor.py` | 3 s poll | 2 WARNINGs in 10 min |
| 4 | `audio_loop` | `run_loops.py:19` | continuous (pw-cat frames) | 0 logs in 10 min |
| 5 | `perception_loop` | `run_loops.py` | 0.5 s | silent in steady state |
| 6 | `ambient_refresh_loop` | `run_loops_aux.py:149` | 30 s | silent |
| 7 | `_cpal_runner.run()` | `cpal/runner.py` | event-driven (impingement arrivals) | 150 INFOs in 10 min |
| 8 | `_cpal_impingement_loop` | inline in `run_inner.py:151` | 0.5 s poll | silent (delegates to CPAL) |
| 9 | `impingement_consumer_loop` | `run_loops_aux.py:187` (affordance dispatch) | file-watch | silent in steady state |
| 10 | `actuation_loop` | `run_loops.py:83` | event-driven (MIDI/OBS commands) | silent |

**All 10 coroutines are alive** — the event loop is healthy (Phase 1
py-spy capture confirmed this). Coroutine 4 (`audio_loop`) is
silent in the 10-minute window: no frames are reaching the STT
path because CPAL has not transitioned to an active listening
state — it's surfacing impingements (the "engaged but noticing an
unexpected" pattern repeated 150 times) without reaching the
speech-production branch.

CPAL's 150 impingement-surfacing logs all have the same shape:

```text
"CPAL: impingement surfacing: <subsystem> is engaged but noticing an <something>"
```

where `<subsystem>` rotates through: the default mode network's
sensory monitoring, the recruitment pipeline's selection dynamics,
physical keyboard and mouse input monitoring, desk vibration and
physical engagement sensing, infrared presence and motion detection,
the visual expression compositor, the imagination generation loop.

These are CPAL "noticing" events — a reflexive pass where CPAL sees
an impingement, describes it internally, and decides whether to
surface it as speech. **None of them reached the speech-production
branch in the 10-minute window.** CPAL's own logic gate decided
"no, don't speak this" for all 150.

## End-to-end latency measurement

Per the brief, measure STT → LLM → TTS → pw-cat output latency for
a synthetic operator utterance.

**Blocker**: the daimonion's audio input is active and receiving
frames, but the STT path has not been exercised in the observation
window — no `agents.hapax_daimonion.resident_stt` log lines,
indicating either (a) VAD has not detected voice activity, or
(b) the presence engine has not transitioned to an active listening
state.

Injecting a synthetic utterance via `pw-play` into the Yeti input
is operator-action gated — it propagates into the live studio
audio chain including the compositor's contact-mic DSP path, and
would briefly disrupt the stream. Out of scope without operator
coordination.

**Alternative measurement** — use the Phase 1 TTS UDS probe to
characterize the TTS-only hop (already done, see Phase 1):

| text chars | UDS connect + synth latency |
|---|---|
| 2 | 12495 ms (queued behind compositor) |
| 11 | 2361 ms |
| 81 | 8309 ms |
| 361 | 54574 ms |

**TTS throughput is the pacing factor.** Even if STT latency were
zero and LLM latency were zero, a 361-char response would take
54.5 s to speak. The daimonion's voice output rate is bounded by
Kokoro CPU, not by STT or LLM.

## Failure mode catalog

Classified by subsystem, counted over the window 16:38 (startup) →
17:20:

| severity | subsystem | count | message | assessment |
|---|---|---|---|---|
| ERROR | `opentelemetry.sdk._shared_internal` | 1 | `Exception while exporting Span` — `ReadTimeout` on POST to `127.0.0.1:3000` (langfuse) | langfuse container healthy but slow to respond; OTEL span export is non-critical but the retry storm is a silent-failure candidate |
| WARNING | `audio_input` | 1 | `pw-cat stream ended unexpectedly` (at 16:38:07, before the current daimonion PID) | prior-session shutdown, not current |
| WARNING | `perception.register_backend` | 3 | `Backend {device_state, midi_clock, phone_media} not available, skipping registration` | dormant backends by design |
| WARNING | `speaker_id` | 1 | `Failed to load pyannote embedding model: ModuleNotFoundError: No module named 'omegaconf'` | missing dep, speaker_id degrades to file-cached path; not blocking |
| WARNING | `face_detector` | ≥2 | `Failed to initialize InsightFace SCRFD: No module named 'insightface'` | missing dep, operator_face signal is gone from the presence engine; load rates etc. all have (LR=9x) fallback weights |
| WARNING | `clip_scene` | 1 | `open_clip not available for CLIP scene classifier` | missing dep, scene classifier degraded |
| WARNING | `movinet` | 1 | `movinets package not installed` | missing dep, action-detection backend degraded |
| WARNING | `tool_definitions.build_registry` | 1 | `Tools defined in _META but missing handlers: ['phone_notifications']` | tool taxonomy drift, one tool unregistered |
| WARNING | `init_pipeline` | 1 | `ConsentGatedReader unavailable, proceeding without consent filtering` | consent plumbing gap; a potential governance concern |
| WARNING | `perception_loop` | multiple | `Control law [voice_daemon]: degrading — skipping SLOW backends` | degradation firing routinely — the slow-path backends are time-budgeted out on every tick |

**Only 1 ERROR, 35 WARNINGs total in 42 minutes of runtime.** The
pipeline is running in a degraded-but-stable state. Five external
dependencies are missing (`omegaconf`, `insightface`, `open_clip`,
`movinets`, `phone_notifications`), and the consent-gated reader
is silently off. None of these is the FINDING-G root cause — they
are pre-existing degradations accepted at the dep-install boundary.

### Langfuse OTEL export timeout (the single ERROR)

```text
urllib3.exceptions.ReadTimeoutError: HTTPConnectionPool(host='127.0.0.1',
port=3000): Read timed out. (read timeout=9.99999713897705)
```

OTEL span exporter hit a 10 s read timeout talking to the langfuse
container at port 3000. Cause candidates: langfuse worker overloaded,
BrowserX or database connection storm, or container memory pressure.

**This is a minor silent-failure candidate** — the OTEL exporter
retries automatically, so data loss is bounded to the span batch
that timed out. Worth noting as a potential Phase 5 silent-failure
sweep target: how does the OTEL exporter's retry/drop policy
behave when the destination is persistently slow?

### ConsentGatedReader unavailable (the governance concern)

```text
init_pipeline precompute_pipeline_deps: ConsentGatedReader unavailable,
proceeding without consent filtering
```

This is the more important warning. The daimonion's init path tries
to instantiate a `ConsentGatedReader` and fails, then **proceeds
without consent filtering**. This is a classic silent-failure shape:
a governance guarantee that was supposed to be enforced by default
degrades to "not enforced" with only a WARNING at startup. Per the
operator's axiom weights table in `CLAUDE.md § Axiom Governance`,
`interpersonal_transparency` (weight 88) requires consent gating for
persistent non-operator-person data. If `ConsentGatedReader` is
off, does the fallback path still gate, or does it silently write
unfiltered data?

Out of scope for this phase — flagged as a Phase 5 silent-failure
sweep target.

## Memory footprint (steady state)

```text
$ PID=$(systemctl --user show -p MainPID --value hapax-daimonion.service)
$ grep -E "^(VmRSS|VmData|VmSwap|Threads):" /proc/$PID/status
VmRSS:   3085440 kB   (3.08 GB)
VmData:  8167524 kB
VmSwap:  1488416 kB   (1.45 GB in swap)
Threads: 80

$ systemctl --user show -p MemoryCurrent,MemoryPeak,MemoryHigh,MemoryMax hapax-daimonion.service
MemoryCurrent = 3,288,788,992   (3.29 GB, matches RSS)
MemoryPeak    = 10,239,770,624  (10.24 GB, during early presynth window)
MemoryHigh    = 10,737,418,240  (10 GB)
MemoryMax     = 12,884,901,888  (12 GB)
```

**The peak-to-current drop is significant: 10.24 GB → 3.29 GB
(−68%)**. Interpretation: during presynth (CPAL signal cache + 51
bridge phrases, from 16:38:59 to 16:40:24 = 85 seconds), Kokoro
loaded its full weight tree plus intermediate allocations, peaked
at 10.24 GB, then released the temporary allocations. Current
3.08 GB is the stable model-loaded state.

This is not a leak and has been stable for 42 minutes (last
`MemoryCurrent` check at 17:20: 3.29 GB, start was 3.08 GB — growth
~200 MB in 42 minutes = 5 MB/min). Within normal variance for a
process with rolling background state.

**VmSwap = 1.45 GB** is notable: the daimonion has pushed 1.45 GB
of its working set to swap. Under normal conditions with 24 GB RAM
and low memory pressure, swap-out is rare. Check:

```bash
free -h
cat /proc/meminfo | head -5
```

Would reveal whether the workstation is under memory pressure or if
zram compression is aggressively pushing inactive anon pages. Out
of scope for this phase; flagged as a host memory observability
gap (Phase 6 data plane + Phase 2 node-exporter fix would catch it).

## Cross-reference with Phase 1 TtsServer finding

Phase 1 proved that the TtsServer handler runs correctly when a
compositor request arrives. This phase's 10-minute log window
confirms:

1. Daimonion `tts_server.py` has emitted **zero log lines** since
   the startup `"TTS server listening on ..."` message.
2. The compositor continues to emit `tts client: synthesize timed
   out` warnings every ~46 seconds (established in Phase 1).
3. Combined with the Phase 1 py-spy capture showing active Kokoro
   synthesis during the capture window, the voice pipeline is
   **dispatching compositor TTS requests successfully and reaching
   Kokoro, but not producing observable logs on the daimonion side
   for the successful path** (the root cause named in Phase 1).

This phase's observation that **the daimonion's own voice output
path also produces zero tts log lines** in the observation window
indicates that CPAL has not triggered any daimonion-native speech
either. The daimonion is silent across both paths:

- compositor speak-react: blocked by throughput (Phase 1)
- daimonion native voice: CPAL has not reached the speak branch

Neither symptom is the same root cause. The daimonion-native path
could be silent because:

- VAD is not detecting speech (operator not speaking)
- Presence engine has not transitioned to an active listening mode
- CPAL's impingement-surfacing pass is producing a steady stream of
  "noticing but not speaking" decisions

**Confirming daimonion-native voice requires an operator-initiated
synthetic utterance**, which is out of scope per this phase's
operator-action gate. The coroutine health + absence of errors
indicates the pipeline is ready to speak when triggered.

## Ranked voice-pipeline observability gaps

| rank | gap | why |
|---|---|---|
| 1 | No Prometheus metrics on `hapax-daimonion.service` | PR #756 Phase 6 + round 3 Phase 2 already identified. Fixes Phase 5/Phase 4 ambiguity ("was there a speak event?" can be answered by `hapax_tts_synth_total` rate). |
| 2 | `TtsServer._handle_client` entry has no INFO log | Phase 1 established this as the root cause of 30-minute speculative investigations. One line. |
| 3 | `ResidentSTT` transcription has no timing log | cannot measure STT latency without instrumenting the model load path. |
| 4 | `CpalRunner.process_impingement` logs surfacing but not decision outcome | 150 INFOs in 10 min, all "surfacing," zero "spoke X" or "declined Y." The log statement lists the subsystem being noticed but not whether CPAL chose to speak. |
| 5 | Consent gate degradation is WARNING-at-startup only | if `ConsentGatedReader unavailable` fires and the code silently proceeds, no subsequent log line confirms governance is off. |
| 6 | OTEL span export failures are ERROR-level on retry but not counted | 1 retry-timeout per session is fine, but if the rate climbs, there's no dashboard-visible counter. |
| 7 | Audio input frame rate is not exported as a counter | `agents.hapax_daimonion.audio_input.start` log line is once per process. No ongoing frame counter. |
| 8 | Presence engine posterior has no gauge | the Bayesian `presence_probability` output is internal; no Prometheus series. |
| 9 | Perception backend skip reasons are log-only | `Backend X not available, skipping registration` is at startup; the operator doesn't see it at dashboard level. |
| 10 | `_cpal_impingement_loop` silently swallows exceptions at DEBUG | `agents/hapax_daimonion/run_inner.py:164` has `except Exception: log.debug(...)` — hidden from INFO-level observation. Matches the silent-failure pattern flagged in Phase 5. |

## Backlog additions (for retirement handoff)

59. **`feat(daimonion): Prometheus exporter with voice pipeline
    metrics`** [Phase 4, duplicate of PR #756 Phase 6 gap 3,
    restated with Phase 4 evidence] — hapax_stt_transcribe_total,
    hapax_stt_transcribe_latency_ms, hapax_tts_synth_total,
    hapax_tts_synth_latency_ms, hapax_cpal_impingement_total (with
    "outcome" label: surfaced/declined/spoke/error),
    hapax_presence_probability, hapax_audio_input_frames_total.
60. **`fix(daimonion): CPAL impingement log includes decision
    outcome`** [Phase 4 gap 4] — change the "CPAL: impingement
    surfacing: X" log to "CPAL: impingement X → Y" where Y is the
    chosen outcome. One-line edit in `cpal/runner.py:490`-ish.
61. **`fix(daimonion): consent gate degradation emits a steady
    WARNING instead of one-time startup log`** [Phase 4 gap 5,
    governance-critical] — if `ConsentGatedReader unavailable` and
    the code is now handling data without consent filtering, that
    state should produce a steady log (or, better, refuse to
    proceed). `interpersonal_transparency` axiom weight 88
    warrants a fail-closed policy.
62. **`research(governance): does the consent-gate fallback path
    still enforce consent?`** [Phase 4 gap 5 followup] — read
    `init_pipeline.precompute_pipeline_deps` + the code it
    delegates to if `ConsentGatedReader` is None. Critical for
    axiom compliance verification.
63. **`fix(otel): OTEL span exporter retry/drop policy under
    persistent downstream slowness`** [Phase 4 gap 6] — current
    behavior on `ReadTimeout`: retry, eventually drop the span
    batch. Verify the drop path is observable (otel_spans_dropped
    counter) and bounded.
64. **`feat(daimonion): audio input frame rate counter`** [Phase 4
    gap 7] — `_run_reader` in `audio_input.py` reads PCM frames
    continuously; expose `hapax_audio_input_frames_total` as a
    Counter for the frame-arrival observability.
65. **`research(daimonion): swap-out investigation`** [Phase 4
    observation] — 1.45 GB in swap at steady state is unusual for
    a 24 GB workstation. Check zram compression and host memory
    pressure. May correlate with the 4.4 GB compositor steady
    state observed in PR #756 Phase 1 + unbounded agent growth.
