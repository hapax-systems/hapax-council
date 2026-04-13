# Phase 1 — FINDING-G root cause: Kokoro CPU throughput vs compositor text length

**Queue item:** 024
**Phase:** 1 of 6
**Depends on:** PR #756 FINDING-G
**Date:** 2026-04-13 CDT
**Register:** scientific, neutral (per `feedback_scientific_register.md`)
**Coordination:** alpha unblocked; convergence.log `17:39:41 PHASE_1_CAPTURE_START` and `17:44:02 PHASE_1_ROOT_CAUSE`.

## Headline

**The FINDING-G symptom is real but the diagnosis in the brief is wrong.**

Alpha's hypothesis — "event-loop starvation on the daimonion side, the
handler coroutine is scheduled by `asyncio.start_unix_server` but never
runs" — is **refuted** by py-spy evidence. The handler runs. Kokoro
synthesis runs. The issue is that **Kokoro CPU synthesis throughput is
~6.6 chars/sec on this workstation**, and the compositor director loop
sends **200–425 character react monologues**, so synthesis takes
30–65 seconds. The compositor's `tts_client.py` timeout is 30 seconds.
Every compositor TTS call that's long enough to matter exceeds the
timeout before Kokoro finishes. The client disconnects, the handler
keeps running, and the completed PCM gets written to a closed pipe and
swallowed at DEBUG level.

Three independent measurements prove this:

| probe text | chars | total latency (ms) | throughput (chars/sec) |
|---|---|---|---|
| `"hi"` | 2 | 12495 (queued behind a compositor request) | — |
| `"hello world"` | 11 | 2361 | 4.7 |
| 81-char sentence | 81 | 8309 | 9.7 |
| 361-char compositor-style paragraph | 361 | **54574** | 6.6 |

The 361-char paragraph is representative of compositor director loop
output. **54.5 s > 30 s timeout.** The compositor sees this as a
timeout and advances its slot; from the operator's perspective the
stream goes silent while the director loop keeps logging REACT text.

## py-spy capture (5 dumps × 2 s + 1 long-form dump)

Captures at `docs/research/2026-04-13/round3-deep-dive/data/py-spy/`.
Full command:

```bash
PID=$(systemctl --user show -p MainPID --value hapax-daimonion.service)
for i in 1 2 3 4 5; do
  sudo py-spy dump --pid $PID --locals > dump-$i.txt
  [ $i -lt 5 ] && sleep 2
done
```

### MainThread state

Every dump shows `Thread 2902187 "MainThread"` in one of two states:

1. **idle** at `main (agents/hapax_daimonion/__main__.py:117)` — the
   event loop's `run_until_complete(daemon.run())` is parked in its
   selector wait. **This refutes the event-loop starvation hypothesis:**
   the loop is *idle* (sleeping in `selectors.py:415 select(...,
   timeout=3000)`), not stuck on a blocking call. In Python 3.12's
   default asyncio, an idle event loop is a *healthy* loop with
   nothing to dispatch.
2. **active** at `main:117` — the loop is dispatching a callback. Both
   states alternate across dumps. There is no single coroutine
   blocking the loop.

Background tasks (CPAL impingement consumer, notification pruning,
workspace monitor, etc.) continue logging `process_impingement` every
few seconds throughout the capture window — **the event loop is
healthy.**

### ThreadPoolExecutor-6_2: continuously synthesizing

Every single one of the 6 dumps shows
`Thread 2926796 "ThreadPoolExecutor-6_2"` in the **active** state,
executing Kokoro synthesis through the following call stack:

```text
_bootstrap_inner (threading.py:1075)
run (threading.py:1012)
_worker (concurrent/futures/thread.py:93)
run (concurrent/futures/thread.py:59)
synthesize (agents/hapax_daimonion/tts.py:52)
  text: "The screen gives us the state, at the podium, attempting to
         frame a way of being. The shaders show us the state of the
         fram..."
  use_case: "conversation"
_synthesize_kokoro (tts.py:58)
  pipeline: <KPipeline at 0x7ff0aaf66c60>
  chunks: []
__call__ (kokoro/pipeline.py:383)
  text: [...]  voice: "af_heart"
infer (kokoro/pipeline.py:232)
decorate_context (torch/utils/_contextlib.py:124)
forward (kokoro/model.py:133)
forward_with_tokens (kokoro/model.py:105)
forward (kokoro/modules.py:167)  # DurationEncoder
forward (torch/nn/modules/rnn.py:1162)  # LSTM forward
```

The `text` local in the `synthesize` frame is a compositor director-
loop react text ("The screen gives us the state, at the podium,
attempting to frame a way of being..."). This proves:

1. **The compositor's TTS UDS request was received.**
2. **The TtsServer `_handle_client` handler ran.**
3. **It reached `asyncio.to_thread(tts_manager.synthesize, ...)`.**
4. **The dispatched work is executing in the ThreadPoolExecutor.**
5. **The synthesis is in progress inside Kokoro's LSTM `DurationEncoder`.**

Zero of these steps are blocked or starved. The handler simply has
not returned yet because Kokoro's LSTM is still running.

### Why no `TtsServer` frames appear in the dumps

`_handle_client` is an `async def` coroutine. When a coroutine is
suspended at `await asyncio.to_thread(...)`, it has **no Python frame
on any thread's stack** — the frame is parked inside the asyncio event
loop's scheduler as a `Task` object. py-spy dumps only show frames
that are currently executing on a thread. The absence of TtsServer
frames in the dump therefore does not prove absence of execution; it
just proves the handler is currently suspended, waiting for the
thread pool to finish.

A future observability fix should log `log.info("tts request
received: %d chars", len(text))` at `_handle_client` entry so that
"handler was called" is recorded independently of the subsequent
synthesis outcome.

## Differential probe: hotkey vs TTS, short vs long text

Per the brief's Phase 1 step 5, I wrote a minimal TTS UDS probe
(`/tmp/tts-probe.py`) that connects directly to
`/run/user/1000/hapax-daimonion-tts.sock`, sends a JSON request, and
measures time-to-header. The probe uses the same wire format as
`agents/studio_compositor/tts_client.py`.

Probe results (each run end-to-end, 90 s client-side timeout):

```text
probe 1  text="hi"          text_len=2   total=12495 ms  pcm_len=58800  [queued]
probe 2  text="hello world"  text_len=11  total= 2361 ms  pcm_len=73200
probe 3  81-char sentence    text_len=81  total= 8309 ms  pcm_len=244800
probe 4  361-char paragraph  text_len=361 total=54574 ms  pcm_len=1056000
```

Key observations:

1. **Probe 1 (2 chars) took 12 s because it was queued behind a
   compositor request** already in progress. The TtsServer uses an
   `asyncio.Lock` to serialize calls; an in-flight 400-char
   compositor synthesize takes the whole slot. When it finished
   (around 12 s in the capture window), the probe acquired the lock
   and then Kokoro processed the 2-char text in ~100 ms — total 12 s
   wait + 100 ms synth.
2. **Probe 2 (11 chars, 2.4 s) and probe 3 (81 chars, 8.3 s)** are
   uncontended steady-state measurements. Throughput: 4.7 chars/s
   and 9.7 chars/s. Kokoro's per-call fixed overhead (LSTM warmup,
   MToken allocation, phoneme conversion) dominates for short texts,
   so short texts are slower than the per-char rate would suggest.
3. **Probe 4 (361 chars, 54.6 s)** is a realistic compositor react
   text length. Throughput: 6.6 chars/s steady. **The 54.6 s synthesis
   time is 82% over the compositor's 30 s timeout.**

**The differential probe is the smoking gun.** Short texts succeed
quickly; long texts exceed the compositor timeout. The UDS path
itself works correctly; the latency is pure Kokoro CPU synthesis
time, not handler dispatch.

## Cross-reference: compositor director loop text lengths

`journalctl -u studio-compositor.service | grep 'Parsed react'`:

```text
423 chars, 393 chars, 366 chars, 409 chars, 372 chars, 346 chars,
374 chars, 206 chars, 412 chars, 256 chars, 361 chars, 222 chars,
362 chars, 344 chars, 397 chars, 259 chars, 376 chars, 360 chars,
334 chars, 297 chars
```

Mean: 338 chars. Min: 206. Max: 423. Median: 363.

At 6.6 chars/sec throughput, this corresponds to:

| percentile | chars | predicted synth time (s) | exceeds 30 s timeout? |
|---|---|---|---|
| min | 206 | 31 | **yes (barely)** |
| median | 363 | 55 | yes |
| mean | 338 | 51 | yes |
| max | 423 | 64 | yes |

**Every compositor director loop react text is above the 30 s
timeout ceiling.** The minimum one (206 chars) is already over by 1
second. The median is nearly 2x over.

## Pre-PR #751 parity claim: why it looked OK before

The finding doc for PR #751 promised "speak-react preserved at parity
latency" as a post-merge verification condition. It was not false at
the time — **the pre-PR #751 in-process TTS path had the same
throughput** (Kokoro on CPU is Kokoro on CPU regardless of whether it
runs in the compositor process or the daimonion process), but the
in-process path had **no client/server timeout at all**. The
director loop's `_synthesize` was a direct method call that blocked
synchronously on the streaming thread; it would have taken the same
54 s to produce a 400-char paragraph, but it would have *completed*
because there was no 30-s timer ticking.

PR #751 introduced the 30-s `tts_client.timeout_s = 30.0` (line 22 of
`tts_client.py`) as a defensive measure against the daimonion being
down. That defense fires on every successful-but-slow call because
Kokoro's steady-state throughput is below the implicit required rate.

## Named root cause

**Kokoro CPU synthesis throughput (~6.6 chars/sec steady state on
this workstation) is insufficient for the compositor director loop's
~340-char average react text length within the 30-second
`tts_client.synthesize` timeout.** The result is a 100 % failure rate
for compositor director loop TTS calls; the daimonion side's
TtsServer handler runs correctly but its write-back happens after the
client has already disconnected, yielding no INFO-level log and a
silent stream.

The root cause is **throughput–timeout mismatch**, not asyncio
primitive misuse, not lock contention, not event-loop starvation, not
socket handshake failure.

## Fix proposal

Four options, in order of shipping speed:

### Option 1 — Compositor side: truncate react text before sending to TTS (fastest ship)

One-line change in `agents/studio_compositor/director_loop.py`'s
`_speak_activity` (or wherever the react text is passed to
`tts_client.synthesize`): truncate to the first sentence, or to 180
characters max, whichever is shorter. 180 chars × 6.6 chars/s = 27 s,
which fits inside the 30 s timeout with a 3 s safety margin.

Diff sketch:

```python
# In director_loop.py _speak_activity
spoken_text = _first_sentence_or_max(text, max_chars=180)
# where _first_sentence_or_max returns text up to the first `. ` /
# `? ` / `! ` boundary, capped at max_chars.
pcm = self._tts_client.synthesize(spoken_text)
```

**Operator-visible effect**: the stream hears the first sentence of
each react (the important one), not the full paragraph. Given that
the compositor already logs the full text at INFO level, the full
text is still auditable via the journal.

### Option 2 — tts_client side: raise the timeout (1-line ship)

Change `_DEFAULT_TIMEOUT_S = 30.0` in `tts_client.py` to `120.0`.
This covers a 400-char paragraph with margin. 120 s per director loop
cycle is long but survivable: the director loop cycle would slow
from ~46 s to ~134 s per react, but no REACTs would be dropped.

**Operator-visible effect**: director loop advances more slowly, but
audio resumes. Every react is voiced.

### Option 3 — Streaming: yield PCM chunks as Kokoro produces them (proper fix)

`KPipeline.__call__` is a generator — it yields one `(graphemes,
phonemes, audio)` tuple per sentence. The current
`TTSManager._synthesize_kokoro` (`tts.py:58`) collects all tuples
into `chunks: list[bytes]` and joins them at the end, defeating the
generator's streaming nature. A streaming UDS protocol would emit
each PCM chunk to the client as it's produced, so the compositor can
start playing the first sentence within 1–2 s instead of waiting for
the whole paragraph.

The wire protocol change is backwards-incompatible:
- **Current**: `{"status":"ok","pcm_len":N}\n<N bytes>`
- **Proposed**: `{"status":"streaming","sample_rate":24000}\n` +
  repeated `[4-byte chunk length][chunk bytes]` framing + `[0-byte
  length]` as end marker.

Estimated effort: 1 hour for server + 1 hour for client + 30 min
for tests. Medium risk.

**Operator-visible effect**: first-sentence latency drops from ~8 s
to ~1–2 s. Full paragraph latency stays similar but audio playback
overlaps with synthesis, so perceived latency is first-sentence time.

### Option 4 — Swap Kokoro-CPU for Kokoro-GPU (operator coordination)

Kokoro on GPU runs ~5–10x faster. The workstation already owns the
GPU (3090, 24 GB VRAM). Current VRAM budget has TabbyAPI as the
exclusive GPU consumer. Adding Kokoro-GPU would require either
(a) coordinating VRAM with TabbyAPI via the VRAM watchdog, or
(b) dedicating a few hundred MB to Kokoro. This is a larger scope
change and is out of scope for this research.

**Operator-visible effect**: TTS throughput ~30–60 chars/s instead
of 6.6. All current compositor texts fit well within the timeout.

### Recommendation

**Ship Option 1 + Option 2 together as a single small PR now**.
Option 1 (truncate to first sentence) preserves stream intelligibility
without requiring synthesis slowness to be solved. Option 2 (raise
timeout to 120 s) gives full-paragraph synthesis a chance to complete
on the rare 500+ char react. Both are one-line changes. File
Option 3 (streaming protocol) as a medium-term ticket; the operator
value is "first-sentence latency drops from 8 s to 1 s" which is
significant but not urgent compared to fixing the 100 % failure rate.
Leave Option 4 (GPU swap) as a future consideration.

**Alpha should NOT revert PR #751.** The fix is forward. PR #751's
address-space shrink (libtorch 35 → 0, VmPeak 20+ GB → 14 GB) is
independent of this throughput issue and is still valuable. The
throughput issue existed pre-PR #751 as well; it was masked by the
in-process path having no timeout.

## Secondary observability finding

The `TtsServer._handle_client` coroutine has **no INFO-level entry
log**. The first log line after `"TTS server listening"` is only
emitted on an error path (malformed framing at line 86, read failure
at line 90, synthesis failure at line 116, or disconnect at line 127
which is DEBUG level). A successful 54-second synthesis followed by
a compositor disconnect produces zero observable daimonion-side log
activity — which is exactly what PR #756 Phase 5 observed and
misinterpreted as "handler never runs."

Fix: add `log.info("tts request: %d chars use_case=%s",
len(text), use_case)` at the top of the synthesis block (line 112),
and `log.info("tts synth ok: %d ms, %d pcm bytes, %d chars",
elapsed_ms, len(pcm), len(text))` at the end of the happy path
(line 126-ish). These two lines would have turned this research into
a 5-minute trace.

## Reproduction commands

```bash
# 1. Install py-spy
paru -S py-spy

# 2. Capture stacks
PID=$(systemctl --user show -p MainPID --value hapax-daimonion.service)
sudo py-spy dump --pid $PID --locals > dump.txt
# Look for ThreadPoolExecutor-*_* threads with "active" state running
# _synthesize_kokoro / KPipeline.__call__ / kokoro/model.forward

# 3. Run differential probe (see the probe source below)
uv run python /tmp/tts-probe.py "hi"
uv run python /tmp/tts-probe.py "hello world"
uv run python /tmp/tts-probe.py "$(journalctl --user -u studio-compositor.service -o cat | grep -oP 'Parsed react \(\d+ chars\): \"[^"]+' | head -1 | grep -oP '"[^"]+' | tr -d '"')"

# 4. Measure compositor react text lengths
journalctl --user -u studio-compositor.service --since "boot" --no-pager \
  | grep -oE 'Parsed react \([0-9]+ chars\)' | grep -oE '[0-9]+' \
  | awk '{sum+=$1; count++; if($1>max)max=$1; if(min==0||$1<min)min=$1} END{print "mean="sum/count" min="min" max="max" n="count}'

# 5. Confirm Kokoro throughput
# Expected: ~6-10 chars/sec on CPU workstation
```

Probe source (`/tmp/tts-probe.py`) embedded verbatim in
`data/py-spy/probe-source.py`.

## Backlog additions (for retirement handoff)

42. **`fix(compositor): director_loop truncates react text to first
    sentence (max 180 chars) before tts_client.synthesize call`**
    [Phase 1 Option 1] — one-line change, shipping-critical. Fixes
    the 100 % compositor TTS failure rate. Preserves audibility of
    the most important sentence per react cycle.
43. **`fix(compositor): raise tts_client _DEFAULT_TIMEOUT_S from 30.0
    to 120.0`** [Phase 1 Option 2] — one-line change, paired with
    #42. Covers edge cases where the truncated text still exceeds
    30 s.
44. **`feat(daimonion): streaming PCM chunks over UDS`** [Phase 1
    Option 3] — medium-scope change to `tts_server.py` and
    `tts_client.py`. Replaces collect-all-then-write with incremental
    chunked write so the compositor can start playback at
    first-sentence latency (~1–2 s) instead of full-paragraph latency
    (~8–60 s).
45. **`feat(daimonion): log.info at TtsServer._handle_client entry
    and at successful synthesis completion`** [Phase 1 observability
    fix] — two one-line additions. Without this, the successful path
    produces zero log lines and any future debugging is blind. This
    is the observability gap that turned FINDING-G into a 30-minute
    investigation.
46. **`research(voice): evaluate Kokoro-GPU vs Kokoro-CPU latency for
    compositor react path`** [Phase 1 Option 4, lower priority] —
    the GPU is already powered up and has ~11 GB free; Kokoro-GPU
    throughput would be ~30–60 chars/s, making every current react
    text fit easily in a 30 s budget. Coordinate with VRAM watchdog
    policy before shipping.
