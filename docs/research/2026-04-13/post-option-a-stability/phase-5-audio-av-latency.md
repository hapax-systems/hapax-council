# Phase 5 — Audio + A/V latency

**Queue item:** 023
**Phase:** 5 of 6
**Date:** 2026-04-13 CDT
**Register:** scientific, neutral (per `feedback_scientific_register.md`)
**Prior work:** Queue 022 Phase 5 partially deferred with steady-state audio captured only. This phase addresses the post-PR-751 speak-react parity claim from the brief and extends the audio observations with live evidence of the daimonion TTS UDS path.

## Headline

The brief framed Phase 5 as a three-part measurement: (a) full
operator-speech-to-RTMP latency, (b) A/V sync delta at the RTMP
output, (c) post-pipewire-restart recovery time. Plus a post-PR-751
angle: confirm speak-react parity latency after TTS delegation to
daimonion via UDS.

One of those four parts resolved decisively in this phase, and it
did **not** resolve in the direction the brief expected.

**The post-PR-751 speak-react parity claim is refuted.** The
daimonion TTS UDS delegation path is currently hanging every
compositor TTS request. Between 17:00:17 CDT and 17:16:02 CDT, the
compositor logged **15 consecutive `tts client: synthesize timed out
after 30.0s` warnings** across two compositor PIDs (2913194 and
3145327), with a 100 % failure rate and an inter-timeout cadence of
~46 seconds (the LLM-to-TTS director-loop cycle period). During the
same window, the daimonion's journal recorded **zero** `tts_server`,
`tts client`, or UDS-handler log lines — not at `INFO`, not at
`WARNING`. The socket file exists on disk and daimonion itself is
alive and producing CPAL impingement-surfacing logs continuously.
This is consistent with either an asyncio lock-contention deadlock
on the daimonion side of the UDS server, a wedged socket-accept
loop, or a JSON-header parse path that hangs on partial reads.

The other three parts of the original Phase 5 measurement are
**deferred** because:

- `mediamtx.service` does not exist as a user systemd unit. The
  system-level `mediamtx.service` is `disabled`. The compositor's
  native RTMP bin targets `rtmp://127.0.0.1:1935/studio` and
  `studio_rtmp_connected` has no value line in the `:9482` scrape
  (the Gauge is defined but never `.set()` — the bin has not been
  constructed). Without MediaMTX running or a working RTMP target,
  end-to-end speech-to-RTMP measurement has no consumer.
- Operator-action (clap, flash) is required for ground-truth
  timestamp anchoring of the A/V sync delta, and the operator is
  not driving this session.
- Pipewire-restart recovery can be exercised in principle, but
  forcing a pipewire restart under a live studio stream without
  coordination risks propagating audio dropouts to any external
  listener. Same operator-coordination gate as the queue 022
  deferral.

This phase files the live daimonion TTS regression alert, captures
steady-state audio + Kokoro synthesis latency numbers that do not
require MediaMTX, and defers the three brief-items with a
reproduction plan for the next session.

## Live evidence

### Daimonion TTS UDS regression — full timeline

```text
16:38:59  hapax-daimonion: "Kokoro TTS ready (voice=af_heart)"
16:38:59  hapax-daimonion: "TTS server listening on /run/user/1000/hapax-daimonion-tts.sock"
16:39:19  hapax-daimonion: "Signal cache: 12/12 presynthesized in 20.1s (0 failed)"
16:40:24  hapax-daimonion: "Pre-synthesized 51/51 bridge phrases in 65.2s"
...
[no tts_server or tts client log lines from daimonion side for the rest of the window]
...
17:00:17  studio-compositor[2913194]: WARN  tts client: synthesize timed out after 30.0s
17:00:17  studio-compositor[2913194]: INFO  _do_speak_and_advance: Now playing slot 1
17:00:33  studio-compositor[2913194]: INFO  _speak_activity REACT [react]: "The screen gives us the state's performance..."
17:01:03  studio-compositor[2913194]: WARN  tts client: synthesize timed out after 30.0s
17:01:03  studio-compositor[2913194]: INFO  _do_speak_and_advance: Now playing slot 2
17:01:18  studio-compositor[2913194]: INFO  _speak_activity REACT [react]: "The screen gives us the manual..."
17:01:23  studio-compositor[2913194]: Signal 15 received, shutting down  [restart]
17:01:40  studio-compositor[3145327] starts
17:02:39  studio-compositor[3145327]: WARN  tts client: synthesize timed out after 30.0s
17:03:25  studio-compositor[3145327]: WARN  tts client: synthesize timed out after 30.0s
17:04:11  studio-compositor[3145327]: WARN  tts client: synthesize timed out after 30.0s
17:04:57  studio-compositor[3145327]: WARN  tts client: synthesize timed out after 30.0s
17:05:52  studio-compositor[3145327]: WARN  tts client: synthesize timed out after 30.0s
17:07:44  studio-compositor[3145327]: WARN  tts client: synthesize timed out after 30.0s
17:08:31  studio-compositor[3145327]: WARN  tts client: synthesize timed out after 30.0s
17:09:17  studio-compositor[3145327]: WARN  tts client: synthesize timed out after 30.0s
17:11:13  studio-compositor[3145327]: WARN  tts client: synthesize timed out after 30.0s
17:12:04  studio-compositor[3145327]: WARN  tts client: synthesize timed out after 30.0s
17:12:50  studio-compositor[3145327]: WARN  tts client: synthesize timed out after 30.0s
17:13:38  studio-compositor[3145327]: WARN  tts client: synthesize timed out after 30.0s
17:14:26  studio-compositor[3145327]: WARN  tts client: synthesize timed out after 30.0s
17:15:13  studio-compositor[3145327]: WARN  tts client: synthesize timed out after 30.0s
17:16:02  studio-compositor[3145327]: WARN  tts client: synthesize timed out after 30.0s
17:16:22  studio-compositor[3145327]: Signal 15 received, shutting down  [restart]
```

**Measurement.** 15 synthesize timeouts in 16 minutes of runtime,
across two PIDs. Zero successful synthesize calls observed. Director
loop `_do_speak_and_advance` advances through slots regardless
(the exception-tolerant error path returns empty PCM bytes, and the
state machine treats empty bytes as a silent "play"). The director
loop's LLM-generated REACT text is logged but **never voiced** —
downstream viewers of the stream see the shader state change without
audible narration.

**Cadence.** ~46 s between consecutive timeouts. Composition:
30 s TTS timeout + ~8 s LLM round-trip + ~8 s other director
activity. The compositor's director loop is running at roughly
0.65x its designed cadence because of the synchronous 30 s block
on every TTS call.

**Socket file state.**

```text
$ ls -la /run/user/1000/hapax-daimonion-tts.sock
srw------- 1 hapax hapax 0 Apr 13 16:38 /run/user/1000/hapax-daimonion-tts.sock
```

Socket exists, mtime matches daimonion startup, no subsequent
modifications.

**Daimonion-side blindness.** The daimonion's journal grep for any
TTS or UDS log line since startup returns zero matches:

```text
$ journalctl --user -u hapax-daimonion.service --since "16:40" \
    --no-pager | grep -cE 'tts_server|tts client'
0
```

Yet daimonion itself is alive: CPAL's `process_impingement` log lines
are fired continuously throughout the window. The process is not
hung. The logging subsystem is working. Only the TTS-UDS code path
is producing no output.

### Three plausible root causes (ordered by likelihood)

1. **asyncio lock contention on the shared `TTSManager`.** CPAL's
   voice loop (`cpal.runner.CpalRunner.process_impingement`) synthesizes
   its own phrases via the same `TTSManager` singleton that the new
   `TtsServer` UDS handler uses. If CPAL is holding the manager's
   lock for a long phrase and an inbound UDS request arrives, the
   UDS handler blocks waiting for the lock. If the wait exceeds
   30 s (because CPAL is in a long-running presynthesis queue or
   stuck on its own lock somewhere), the compositor-side timeout
   fires and the request never returns. The alpha-written
   implementation plan in `alpha.yaml:inherited_tickets` line
   ~119 mentions "asyncio.Lock serializes synthesize calls (shared
   with CPAL voice loop's existing TTSManager usage)" — **this is
   exactly the lock-ordering shape that produces this class of
   failure.**

2. **Socket-accept loop wedged.** `start_unix_server`'s handler
   coroutine stays alive for every client connection. If a prior
   client death (e.g., the 17:01:23 compositor SIGTERM mid-request)
   left a coroutine partially reading from a dead socket, the
   handler could be awaiting on `read()` forever while the
   `start_unix_server` accept loop continues accepting new clients
   that can never get served because there is no worker rotation.

3. **JSON-header parse hanging on partial reads.** The wire format
   is "JSON header + binary PCM body". If the header parse uses
   `readline()` or equivalent, a missing newline from the compositor
   side would hang the read forever. Ruled out for the compositor
   side because its `tts_client.synthesize` has an explicit 30 s
   timeout — but the daimonion side may not have a corresponding
   timeout.

**Recommendation to alpha** (already logged at
`convergence.log:2026-04-13T17:16:45`):

1. Verify: add a `log.info(...)` at the top of the daimonion
   `TtsServer._handle_client` coroutine and observe whether the
   log line ever fires when the compositor retries.
2. Verify: check whether the shared `TTSManager` uses
   `asyncio.Lock` (which the UDS handler can `await`) or
   `threading.Lock` (which would be a classic lock-from-wrong-context
   bug in a mixed sync/async codebase).
3. Verify: instrument the handler with a hard timeout on the header
   read so an incomplete client send does not block the handler
   forever.

**Severity.** This blocks the main operator value of PR #751 — the
whole point of Option A was to keep speak-react working at parity
latency after moving TTS out-of-process. Parity latency is currently
**infinite**. The compositor is still saying the LLM output text in
its log stream, but the operator hears silence. **HIGH severity
regression**, worth a hot-fix session.

### Kokoro CPU TTS synthesis baseline (steady state)

Even though the UDS path is broken, Kokoro itself is working. The
presynthesis logs from daimonion startup give an accurate
per-phrase synthesis cost for comparison against any future fix:

| workload | phrases | total time | avg per phrase |
|---|---|---|---|
| CPAL signal cache presynth | 12 | 20.1 s | 1.68 s |
| Bridge phrase presynth | 51 | 65.2 s | 1.28 s |

**Interpretation.** Kokoro 82 M on CPU averages ~1.3–1.7 s per
typical phrase. The compositor's 30 s timeout is 17× the typical
phrase synthesis time, so the timeouts are not caused by Kokoro
being slow. They are caused by something preventing the request
from reaching Kokoro in the first place.

Reproduction command for Kokoro steady-state synthesis cost:

```bash
# Check daimonion journal for presynth completion logs
journalctl --user -u hapax-daimonion.service --since "boot" \
  --no-pager | grep -iE 'presynthesiz'
```

### Pipewire buffer size (steady state)

```text
$ pw-metadata -n settings | grep -i quantum
update: id:0 key:'clock.quantum'         value:'128' type:''
update: id:0 key:'clock.min-quantum'     value:'64'  type:''
update: id:0 key:'clock.max-quantum'     value:'1024' type:''
update: id:0 key:'clock.force-quantum'   value:'0'   type:''
```

Current quantum: **128 frames**. At 48 kHz, that's a **~2.67 ms**
nominal audio period. Min 64 / max 1024 means pipewire can switch
between 1.33 ms and 21.33 ms periods as clients come and go.
128 is the current steady value with the studio audio pipeline
active.

This is a usefully small number for live audio — a 2.67 ms period
means the minimum possible end-to-end latency for a tight audio path
is on the order of 2–3 buffer cycles + codec delay = ~10 ms floor.
Matches the design budget for live livestream audio.

### RTMP output state

Compositor configuration from `agents/studio_compositor/pipeline.py:202`
and `rtmp_output.py:40`:

```python
rtmp_location = "rtmp://127.0.0.1:1935/studio"
```

Live scrape:

```text
$ curl -s http://127.0.0.1:9482/metrics | grep studio_rtmp_connected
# HELP studio_rtmp_connected 1 if rtmp2sink is currently connected
# TYPE studio_rtmp_connected gauge
[no value line]
```

The `studio_rtmp_connected` Gauge has been defined by `metrics.py`
but never `.set()` on any label. This means the native RTMP output
bin is not currently constructed — the compositor has not even
tried to reach MediaMTX. This is consistent with the MediaMTX-is-
inactive observation from queue 022 Phase 5.

`mediamtx.service` state:

```text
$ systemctl --user status mediamtx.service
Unit mediamtx.service could not be found.

$ systemctl status mediamtx.service
mediamtx.service: disabled
```

System-level unit exists but is disabled. No user-level unit. A
`mediamtx` process was briefly seen at PID 3285772 during the
audit window but was gone at recheck; likely an ad-hoc operator
invocation and not a persistent service. Unless the operator
starts MediaMTX manually, the compositor's RTMP path is a cold
sink.

## Deferred measurements

The three "headline numbers" the brief asked for are deferred:

1. **Operator-speech-to-RTMP latency** — requires (a) working TTS
   delegation (regression blocker above), (b) MediaMTX up to
   receive the stream, (c) a RTMP consumer to timestamp the output.
   Earliest executable once PR #751 regression is fixed and
   operator agrees to an in-session MediaMTX bring-up.
2. **A/V sync delta at RTMP output** — needs the same three
   preconditions + an operator clap/flash event for ground-truth
   anchoring.
3. **Post-pipewire-restart recovery** — operator-action gated;
   beta should not intentionally restart pipewire without operator
   acknowledgment since it propagates to every audio client on the
   workstation.

**Reproduction plan for the next session.** When the TTS regression
is fixed and MediaMTX is up:

```bash
# 1. Convergence log: bringing MediaMTX up for Phase 5
# 2. Start MediaMTX
pass show streaming/youtube-stream-key  # get disposable key
sudo systemctl start mediamtx.service
sleep 2
# 3. Verify compositor sees it
curl -s http://127.0.0.1:9482/metrics | grep studio_rtmp_connected
# expected: studio_rtmp_connected{endpoint="rtmp://127.0.0.1:1935/studio"} 1.0

# 4. Operator says a test utterance, noting the wall-clock time
#    (use `date +%s.%N` at the end of speech or a visible screen
#    flash for t0 anchoring).
# 5. Record the RTMP output with ffmpeg, measure the first audio
#    sample's pts against t0:
ffmpeg -i rtmp://127.0.0.1:1935/studio -c:a copy -c:v copy -t 10 /tmp/rtmp-sample.mkv
ffprobe -show_packets -select_streams a /tmp/rtmp-sample.mkv | head -5

# 6. For A/V sync: count video frames from operator clap (VLA
#    camera pipeline finds the clap frame) and audio samples from
#    the contact mic to compute delta at the compositor input,
#    then re-measure at the RTMP output and compare deltas.

# 7. For pipewire restart, with operator ack:
systemctl --user restart pipewire.service
# measure: time until daimonion TTS reaches output again,
# time until compositor audio pipeline reconnects
```

## Backlog additions (for retirement handoff)

1. **`fix(daimonion): TTS UDS server hangs on every compositor
   request (PR #751 regression)`** — HIGH severity. 15 consecutive
   30 s timeouts observed on the compositor side with zero
   daimonion-side log evidence. Root cause likely asyncio lock
   contention on the shared `TTSManager`. Requires a dedicated
   session with alpha to trace. This is the **most load-bearing
   fix in the post-Option-A backlog** — the whole point of PR #751
   was to preserve speak-react at parity latency and that claim
   does not currently hold.
2. **`feat(daimonion): add structured logging at
   `TtsServer._handle_client` entry + per-phase log inside the
   handler`** — whatever the root cause, the daimonion side should
   be observable at its own request boundary. Even a single
   `log.info("tts request accepted")` on client connect would have
   made this research a 5 minute trace instead of a 30 minute
   speculative session.
3. **`feat(compositor): fall through to CPU-local Kokoro fallback
   if the daimonion UDS timeout fires 3× in a row`** — the
   architectural intent of Option A was UDS delegation, but a
   single daimonion restart during stream time should not silence
   the compositor's speak-react path for minutes at a time. Add a
   shallow retry budget + fallback path to a locally-hosted mini
   Kokoro instance or a pre-recorded "audio fallback" silence
   signal so viewers notice the loss of narration rather than a
   locked pipeline.
4. **`research(compositor): reproduce the A/V latency measurement
   plan once TTS is fixed`** — the commands in this doc are the
   reproduction. Run them.
5. **`fix(monitoring): add `compositor_tts_client_timeout_total`
   counter`** — 15 timeouts over 16 minutes went completely
   unobserved from the monitoring stack's perspective. This class
   of silent failure is exactly the observability gap Phase 6
   listed. A one-line Counter in `tts_client.py` would have turned
   the problem into a Prometheus-visible rate.
6. **`chore(compositor): unify the "RTMP native bin not constructed"
   vs "MediaMTX not running" confusion`** — queue 022 + this phase
   both find that `studio_rtmp_connected` has no value and the
   service isn't running. The compositor should either log a
   startup message documenting its decision ("native RTMP path
   skipped: MediaMTX not reachable at $URL") or expose a state
   gauge `studio_rtmp_bin_state` with values {unbuilt, connecting,
   connected, failed}.
