# Cortado MKIII contact mic DSP drift check

**Date:** 2026-04-15
**Author:** beta (queue #233, identity verified via `hapax-whoami`)
**Scope:** static audit of contact mic DSP module + empirical verification against the live PipeWire graph. Flag any drift between design, code, and reality.
**Branch:** `beta-phase-4-bootstrap`

---

## 0. Summary

**Verdict: DSP code is correct + CALIBRATED. Hardware path is BROKEN (silent failure, cross-references queue #230 Studio 24c absence). Cross-modal IR fusion helper is DEAD CODE.** Six findings:

1. ✅ **DSP thresholds are calibrated + documented** (`_ONSET_THRESHOLD=0.157`, `_IDLE_THRESHOLD=0.116`, `_TYPING_MIN_ONSET_RATE=1.0`, etc., all calibrated 2026-03-25 with the source comments preserving the provenance). Not drifted per se — values are static + well-justified.
2. 🔴 **Contact mic is returning NULL AUDIO** — empirical RMS = 0.000000 over a 2.9s live sample. `perception-state.json` shows `desk_energy: 5e-324` (float underflow = effectively zero) persistent across 3 consecutive perception ticks (9 seconds of observation).
3. 🔴 **Root cause: Studio 24c absence (cross-refs queue #230).** The `10-contact-mic.conf` PipeWire drop-in explicitly targets `alsa_input.usb-PreSonus_Studio_24c_SC1E24390244-00.analog-stereo` which does not exist on the rig. The contact_mic PipeWire virtual source still exists (loopback module loaded), it just has no upstream audio producer.
4. 🟡 **Exploration tracker HAS detected the failure.** `/dev/shm/hapax-exploration/contact_mic.json` shows `chronic_error: 1.0` + `stagnation_duration: 5922.6s` (**~98.7 minutes** of consistent error=1.0). But **no downstream alert** is wired to this signal — the silent failure has been propagating for ~100 minutes without any operator notification.
5. 🔴 **`contact_mic_ir.py::_classify_activity_with_ir` is DEAD CODE.** The cross-modal fusion helper (turntable+sliding→scratching, mpc-pads+tapping→pad-work) that CLAUDE.md § Bayesian Presence Detection promises is **never called in production**. `ContactMicBackend._capture_loop` at line 443 calls `_classify_activity()` directly, bypassing the IR fusion helper entirely. The helper has a unit test (`test_contact_mic_ir_fusion.py`, 75 LOC) but no production wire-up.
6. 🟡 **Control-law degrade doesn't fire on silent audio.** The backend's "empty audio buffer" control law at lines 476-499 triggers on `len(energy_buffer) == 0` — but with all-zero samples, the buffer is populated (just with zeros), so the degrade never fires. The code thinks "I'm getting samples, everything is fine" while the samples are mathematically null.

**Severity:**
- **HIGH** for findings 2-4 (silent failure of a high-LR presence signal for ~100 minutes, undetected by any alerting path)
- **MEDIUM** for finding 5 (documented feature is absent from production — a false CLAUDE.md claim)
- **LOW** for findings 1 + 6 (calibration is current; control-law is a conservative design choice)

## 1. File inventory

```
agents/hapax_daimonion/backends/contact_mic.py     520 LOC
agents/hapax_daimonion/backends/contact_mic_ir.py   29 LOC   ← DEAD CODE
tests/hapax_daimonion/test_contact_mic_backend.py   313 LOC
tests/hapax_daimonion/test_contact_mic_ir_fusion.py  75 LOC
```

### 1.1 Recent commit history

```
$ git log --oneline -10 -- agents/hapax_daimonion/backends/contact_mic.py
436964372 feat: migrate contact mic from PyAudio to pw-cat + wire into presence
cab0af0e9 feat(exploration): hardening — auto-emission, adaptive std_dev, SEEKING affordance
e7449eeb6 feat(exploration): wire remaining components — dmn_pulse, contact_mic, reverie, stimmung
839704210 fix(voice): disable contact mic PyAudio backend (SEGV crash)
efd0f4da4 feat: SCM gap closure — fortress decoupling, sheaf rename, consent ingestion, 14 control laws
88689cc75 feat: SCM completion — all 14 ControlSignals + IFC perception writer
adf9dbc62 fix(daimonion): fix undefined device_idx, silent thread death, and degraded state in contact_mic
bd54b64d0 refactor: rename hapax-voice to hapax-daimonion (600 files)
...
533 feat: contact microphone integration + scratch detection (initial)
```

The most recent functional change was `436964372` — the pw-cat migration. Since then it's been stable. No threshold re-calibration commits; the `# calibrated 2026-03-25` comments are honest.

## 2. DSP constants audit

```python
# scripts/run_rifts_benchmark.py — no wait, agents/hapax_daimonion/backends/contact_mic.py:28-55
_FFT_SIZE = 512
_SAMPLE_RATE = 16000            # perception DSP rate (recorder uses 48kHz)
_RMS_SMOOTHING = 0.3            # exponential smoothing alpha
_ONSET_THRESHOLD = 0.157        # calibrated 2026-03-25 (midpoint silence p95 / typing mean)
_ONSET_MIN_INTERVAL_S = 0.08    # 80ms minimum between onsets
_GESTURE_WINDOW_S = 0.5         # max gesture classification window
_GESTURE_TIMEOUT_S = 0.3        # wait-after-last-onset before classifying
_DOUBLE_TAP_MIN_IOI = 0.08      # double tap inter-onset minimum
_DOUBLE_TAP_MAX_IOI = 0.25      # double tap inter-onset maximum
_IDLE_THRESHOLD = 0.116         # calibrated 2026-03-25 (2x silence p95)
_TYPING_MIN_ONSET_RATE = 1.0    # calibrated (60% of observed 1.6/sec)
_TAPPING_MIN_ONSET_RATE = 1.6   # calibrated (60% of observed 2.7/sec)
_DRUMMING_MIN_ENERGY = 0.4      # between tapping mean 0.33 and drumming mean 0.54
_DRUMMING_MAX_CENTROID = 219.0  # 1.5x drumming centroid mean 146 Hz
_SCRATCH_AUTOCORR_THRESHOLD = 0.9  # effectively disabled (camera-primary)
_SCRATCH_MIN_ENERGY = 0.03      # 50% of scratch RMS mean 0.058
_SCRATCH_MIN_LAG = 2            # ~64ms at 32ms frames (~16 Hz)
_SCRATCH_MAX_LAG = 16           # ~512ms at 32ms frames (~2 Hz)
_ENERGY_BUFFER_SIZE = 60        # ~1.9s of history at 32ms frames
```

**Audit verdict:** every threshold has a source-comment-documented calibration rationale. `_ONSET_THRESHOLD` and `_IDLE_THRESHOLD` are explicitly anchored to 2026-03-25 calibration data; `_TYPING_MIN_ONSET_RATE` and `_TAPPING_MIN_ONSET_RATE` reference observed onset rates (1.6/sec for typing, 2.7/sec for tapping); `_DRUMMING_MIN_ENERGY` is set between the tapping + drumming means. These values are static + reasonable for the Cortado MKIII mounted under the desk — not drifted.

**One caveat:** the "2026-03-25 calibration" was performed ~3 weeks ago. The operator's typing patterns, key switches, or desk mount may have changed since then. Without a live Cortado signal to re-measure (see §3), any re-calibration is blocked on hardware restoration.

**No drift flagged** for the thresholds themselves — they are correct for the last-measured operator state.

## 3. Hardware path — BROKEN (silent failure)

### 3.1 Empirical RMS measurement

```
$ timeout 3 pw-cat --record --target 'Contact Microphone' \
    --format s16 --rate 16000 --channels 1 /tmp/contact_mic_sample.raw
$ ls -la /tmp/contact_mic_sample.raw
-rw-r--r-- 1 hapax hapax 92958 Apr 15 16:12 /tmp/contact_mic_sample.raw

$ python3 -c "
import numpy as np
data = open('/tmp/contact_mic_sample.raw', 'rb').read()
samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
rms = float(np.sqrt(np.mean(samples**2)))
peak = float(np.max(np.abs(samples)))
print(f'samples={len(samples)}  duration={len(samples)/16000:.2f}s')
print(f'RMS={rms:.6f}  peak={peak:.6f}')
print(f'RMS > _IDLE_THRESHOLD (0.116)? {rms > 0.116}')
"
samples=46479  duration=2.90s
RMS=0.000000  peak=0.000000
RMS > _IDLE_THRESHOLD (0.116)? False
```

**46479 samples of bitwise zero.** Not "quiet" — mathematically null. The PipeWire virtual source is producing samples (pw-cat reads 2.9s without timeout), but every byte in the int16 PCM stream is 0x00.

### 3.2 Persistence across perception ticks

```
$ for i in 1 2 3; do python3 -c "...read perception-state.json..." ; sleep 3 ; done
tick 1: energy=5e-324  activity='idle'  onset=0.00  tap='none'  centroid=0.00
tick 2: energy=5e-324  activity='idle'  onset=0.00  tap='none'  centroid=0.00
tick 3: energy=5e-324  activity='idle'  onset=0.00  tap='none'  centroid=0.00
```

**`5e-324` is Python's `float('5e-324')` = the smallest positive subnormal float**, effectively zero after rounding. The DSP code computes `float(np.sqrt(np.mean(samples**2)))` and the result is the minimum representable positive number. Every tick. Persistent across 9 seconds of sampling.

### 3.3 Root cause — 10-contact-mic.conf targets Studio 24c (absent per #230)

```
$ cat ~/.config/pipewire/pipewire.conf.d/10-contact-mic.conf | head -25
context.modules = [
    # Contact microphone (Cortado MKIII) — left channel (Input 1)
    {
        name = libpipewire-module-loopback
        args = {
            node.description = "Contact Microphone (Cortado)"
            capture.props = {
                audio.position = [ FL ]
                stream.dont-remix = true
                node.target = "alsa_input.usb-PreSonus_Studio_24c_SC1E24390244-00.analog-stereo"
                node.passive = true
            }
            playback.props = {
                node.name = "contact_mic"
                node.description = "Contact Microphone (Cortado)"
                media.class = "Audio/Source"
                audio.position = [ MONO ]
            }
        }
    }
    # Mixer master output — right channel (Input 2)
    { ... same target.object ... }
```

The PipeWire loopback module creates the `contact_mic` virtual source by reading **FL channel** of the ALSA input `alsa_input.usb-PreSonus_Studio_24c_SC1E24390244-00.analog-stereo`. Same for the `mixer_master` virtual source (FR channel). Both PipeWire loopbacks target a sink that **does not exist** per queue #230 §5.

**PipeWire behavior when `node.target` doesn't resolve:** the loopback module still instantiates the virtual source (creating `contact_mic` as a valid routable node) but the capture side has no input, so every sample is zero-filled. No error is logged. No warning is emitted. The sink appears in `pactl list short sources` as active. Downstream consumers (the DSP backend, the voice-fx chain, the pw-cat CLI) all see a working source producing silence.

**This is the silent failure pattern in its canonical form:** every layer reports "nominal" while the upstream signal is gone.

## 4. Exploration tracker HAS detected the failure

```
$ cat /dev/shm/hapax-exploration/contact_mic.json | python3 -m json.tool
{
    "component": "contact_mic",
    "timestamp": 1776287618.3559067,
    "mean_habituation": 0.1666,
    "max_novelty_edge": "desk_activity",
    "max_novelty_score": 0.8334,
    "error_improvement_rate": 0.0,
    "chronic_error": 1.0,
    "mean_trace_interest": 0.0,
    "stagnation_duration": 5922.6,
    "local_coherence": 0.5,
    "dwell_time_in_coherence": 0.0,
    "boredom_index": 0.55,
    "curiosity_index": 1.0
}
```

**Key readings:**

- **`chronic_error: 1.0`** — maximum. The exploration tracker's error feed (line 354: `feed_error(0.0 if energy > 0.001 else 1.0)`) has been receiving `1.0` every tick for the full observation window.
- **`stagnation_duration: 5922.6 seconds = 98.7 minutes`** — the tracker has been in stagnation for ~100 minutes. "Stagnation" here means "state has not escaped the error regime for this duration."
- **`error_improvement_rate: 0.0`** — no progress; the error rate is not dropping.
- **`curiosity_index: 1.0`** — maxed.
- **`boredom_index: 0.55`** — elevated, but not saturated.

**The system KNOWS the contact mic has been broken for 98 minutes.** The exploration tracker is correctly measuring + publishing the degradation. But no alert wires `chronic_error >= 1.0 for >60s` to any operator-facing surface — no ntfy push, no Grafana alert rule, no health monitor escalation. **The silent failure is observable but unobserved.**

Cross-references:

- Queue #220 presence engine LR tuning (blocked on stale watch HR) — same silent-failure theme, different signal
- Queue #206 PresenceEngine calibration audit — also static, did not catch this
- Queue #230 voice FX chain verification — established the Studio 24c absence

**Three queue items in the same session, all pointing at the same root cause.** The operator has been running on a degraded presence-signal substrate for days (queue #220 watch HR stale for 9+ days; queue #233 contact mic stagnant for 98+ minutes and likely much longer).

## 5. Dead-code finding — `contact_mic_ir.py::_classify_activity_with_ir`

### 5.1 The helper itself (29 LOC)

```python
# agents/hapax_daimonion/backends/contact_mic_ir.py
"""Cross-modal fusion: contact mic DSP + IR hand zone disambiguation."""

from agents.hapax_daimonion.backends.contact_mic import _classify_activity


def _classify_activity_with_ir(
    energy: float,
    onset_rate: float,
    centroid: float,
    autocorr_peak: float = 0.0,
    ir_hand_zone: str = "none",
    ir_hand_activity: str = "none",
) -> str:
    """Classify desk activity with IR hand zone disambiguation.

    Base classification from DSP metrics, then refine with IR context:
    - turntable zone + sliding/tapping → scratching
    - mpc-pads zone + tapping energy → pad-work
    """
    base = _classify_activity(energy, onset_rate, centroid, autocorr_peak)
    if base == "idle":
        return "idle"
    if ir_hand_zone == "turntable" and ir_hand_activity in ("sliding", "tapping"):
        return "scratching"
    if ir_hand_zone == "mpc-pads" and base in ("tapping", "active"):
        return "pad-work"
    return base
```

### 5.2 Call-site grep

```
$ grep -rn '_classify_activity_with_ir\|contact_mic_ir' agents/
agents/hapax_daimonion/backends/contact_mic_ir.py:8:def _classify_activity_with_ir(
```

**Only one hit: the function's own definition.** No production code imports or calls it. Confirmed by cross-checking:

```
$ grep -rn 'classify_activity\|classify_gesture' agents/hapax_daimonion/
agents/hapax_daimonion/backends/contact_mic.py:130:def _classify_activity(
agents/hapax_daimonion/backends/contact_mic.py:443:  activity = _classify_activity(smoothed_energy, onset_rate, centroid, autocorr_peak)
agents/hapax_daimonion/backends/contact_mic_ir.py:22:  base = _classify_activity(energy, onset_rate, centroid, autocorr_peak)
```

`ContactMicBackend._capture_loop` at line 443 calls `_classify_activity()` **directly** — bypassing the IR fusion helper. The fusion helper itself calls `_classify_activity()` as its base classifier, but nothing calls the fusion helper.

### 5.3 CLAUDE.md § Bayesian Presence Detection is factually wrong

```
**Contact mic:** Cortado MKIII on PreSonus Studio 24c Input 2 (48V phantom).
Captured via `pw-cat --record --target "Contact Microphone"` at 16kHz mono
int16. DSP: RMS energy, onset detection, spectral centroid, autocorrelation,
gesture classification. Provides `desk_activity` (idle/typing/tapping/
drumming/active), `desk_energy`, `desk_onset_rate`, `desk_tap_gesture`.
...
`contact_mic_ir.py::_classify_activity_with_ir()` provides cross-modal
fusion (turntable zone + contact mic DSP = scratching, mpc-pads + tapping =
pad-work).
```

The second paragraph is **false**. The helper exists but is dead code. The cross-modal fusion feature is advertised in CLAUDE.md but absent from the runtime path.

**Operator-visible impact:** when the operator is DJ-scratching on the turntable, the system should classify `desk_activity="scratching"` but instead returns the base class (`typing`, `tapping`, `active`, or — currently — `idle` due to the hardware path break). The scratching classification never fires in production.

### 5.4 Why it's dead

Possible explanations:

1. **The fusion was prototyped but never wired** — the test file suggests someone planned to integrate it, but the `_capture_loop` was never updated to call the fusion helper
2. **The fusion was wired then removed** — not in git blame; `contact_mic_ir.py` was introduced and the capture loop has never called it
3. **Intentional design: fusion happens elsewhere** — but grep for `contact_mic_ir` or `_classify_activity_with_ir` in all of `agents/` returns only the definition; there is no elsewhere
4. **Expected to be called by a future refactor** — possible, but CLAUDE.md already claims the behavior is in place

Most likely explanation is #1 — prototype + test shipped, production wiring forgotten. Classic "dead future".

## 6. Control-law degrade doesn't fire on silent audio

```python
# contact_mic.py:476-499
if len(energy_buffer) == 0:
    _cm_err += 1
    _cm_ok = 0
else:
    _cm_err = 0
    _cm_ok += 1

if _cm_err >= 3 and not _cm_deg:
    self._cache.update(desk_activity="unknown")
    _cm_deg = True
    log.warning(
        "Control law [contact_mic]: degrading — skipping DSP, activity=unknown"
    )
```

The degrade trigger is `len(energy_buffer) == 0`. With the silent-audio failure mode, the buffer is populated — every tick appends `smoothed_energy` (which is ~5e-324) to `energy_buffer`. The buffer length grows to its max (60) and stays there. **The condition never evaluates True.**

Cross-check with the journal — no "Control law [contact_mic]: degrading" messages appear in the last hour:

```
$ journalctl --user -u hapax-daimonion.service --since '1 hour ago' | grep 'Control law \[contact_mic\]'
(empty)
```

**The backend is "working as designed" given the silent-audio input.** From its perspective, samples are flowing, DSP is running, results are being cached. There's no indication of failure.

### 6.1 Proposed fix (non-urgent)

Add a secondary degrade trigger: **"N consecutive ticks with RMS < silence-floor"**. Silence floor could be `_IDLE_THRESHOLD / 100 = 0.00116` or an absolute like `1e-6`. If the mic has been reporting effectively-zero energy for N ticks (say 30, = ~1 minute), something upstream is broken — log + push a stimmung degrade signal.

```python
# sketch
_SILENCE_FLOOR = 1e-6
_SILENCE_STAGNATION_TICKS = 30

if smoothed_energy < _SILENCE_FLOOR:
    _silent_ticks += 1
else:
    _silent_ticks = 0
if _silent_ticks >= _SILENCE_STAGNATION_TICKS and not _silence_alerted:
    log.warning(
        "Contact mic silent for %d ticks (RMS < %.6f) — upstream likely broken",
        _silent_ticks, _SILENCE_FLOOR,
    )
    _silence_alerted = True
```

**Not proposing this as a queue item yet** — the exploration tracker already catches this via `chronic_error` (see §4). The fix is downstream: wire `chronic_error >= 1.0 for >60s` on ANY component to a stimmung signal that the operator sees (health-monitor path, ntfy push, Grafana alert). This would cover contact_mic, watch_hr, and any other silent-failure signal in one shot.

## 7. Tests

```
tests/hapax_daimonion/test_contact_mic_backend.py   313 LOC  (unit tests for DSP functions, cache, classification)
tests/hapax_daimonion/test_contact_mic_ir_fusion.py  75 LOC  (unit tests for the dead _classify_activity_with_ir)
```

**Good unit-test coverage.** The test files cover:

- `_compute_rms()` with synthetic sine waves + silence
- `_compute_spectral_centroid()` with known frequencies
- `_detect_onsets()` with synthesized onset patterns
- `_classify_activity()` with pre-computed DSP tuples across all 5 activity classes
- `_classify_gesture()` with 2-onset and 3-onset bursts
- Thread-safe cache read/write
- `_classify_activity_with_ir()` fusion logic (DEAD-CODE TESTS — the helper is tested but its output is never observed in production)

**Gap:** no integration test validates end-to-end PipeWire → DSP → presence_probability. A future test could mock pw-cat with a fixture WAV and validate the backend produces the expected `desk_activity` classifications. Out of scope for this audit.

## 8. Recommended follow-ups

### 8.1 #240 — Wire or delete `_classify_activity_with_ir`

```yaml
id: "240"
title: "Wire or delete dead _classify_activity_with_ir fusion helper"
assigned_to: beta
status: offered
depends_on: []
priority: low
description: |
  Queue #233 found contact_mic_ir.py::_classify_activity_with_ir is
  defined + unit-tested but NEVER called from production. CLAUDE.md
  § Bayesian Presence Detection claims cross-modal fusion is active;
  the claim is false.
  
  Two paths:
  
  PATH A (wire it in): update ContactMicBackend._capture_loop at
  line 443 to call _classify_activity_with_ir instead of
  _classify_activity, and feed it ir_hand_zone + ir_hand_activity
  from a shared ring buffer (perception-state.json). Requires a small
  refactor to give the capture thread access to IR state.
  
  PATH B (delete it): rm contact_mic_ir.py + test file + update
  CLAUDE.md to remove the scratching/pad-work claim.
  
  Beta's recommendation: PATH A. The cross-modal fusion is a real
  design goal (CLAUDE.md § Unified Semantic Recruitment emphasizes
  multi-signal composition), and scratching detection is operator-
  relevant for the livestream workflow. Path A is ~30 LOC including
  a thread-safe IR state read.
  
  Blocker: contact mic hardware path must be restored first (see
  #241) so the fusion has non-zero input to operate on.
size_estimate: "~45 min for Path A, ~10 min for Path B"
```

### 8.2 #241 — Restore contact mic hardware path (operator-facing)

```yaml
id: "241"
title: "Restore contact mic hardware path — Studio 24c or alternative"
assigned_to: operator
status: offered
depends_on: []
priority: medium
description: |
  Queue #233 confirmed empirically that the contact mic is producing
  NULL AUDIO (RMS=0.0 for 2.9s of sample). Root cause is queue #230's
  Studio 24c absence: the 10-contact-mic.conf PipeWire drop-in targets
  alsa_input.usb-PreSonus_Studio_24c_SC1E24390244-00.analog-stereo
  which does not exist on the rig.
  
  Exploration tracker has been reporting chronic_error=1.0 for the
  contact_mic component for >98 minutes (visible at
  /dev/shm/hapax-exploration/contact_mic.json).
  
  Operator actions:
  1. Determine whether Studio 24c was intentionally disconnected
     (see also #231a from queue #230 closure)
  2. If available to reconnect: plug the 24c back in + verify
     `lsusb | grep PreSonus` + restart pipewire
  3. If not available: either
     a. Update 10-contact-mic.conf to target an alternate audio
        interface (ALC1220 motherboard mic-in, USB audio adapter,
        etc.), OR
     b. Disable the contact mic backend via a feature flag + update
        the PresenceEngine DEFAULT_SIGNAL_WEIGHTS to drop desk_active
  4. Verify: pw-cat record 2s, RMS should be > 0 when operator types
size_estimate: "~10-30 min operator inspection + reconfig"
```

### 8.3 #242 — Alert on chronic_error >= 1.0 for any exploration component

```yaml
id: "242"
title: "Alert on chronic_error >= 1.0 stagnation across exploration components"
assigned_to: beta
status: offered
depends_on: []
priority: low
description: |
  Queue #233 found contact_mic has chronic_error=1.0 +
  stagnation_duration=5922s with NO downstream alert. The exploration
  tracker is correctly publishing the degradation to
  /dev/shm/hapax-exploration/contact_mic.json but nothing consumes
  this signal as a "component is broken" alert.
  
  Same pattern applies to watch_hr (queue #220), and likely other
  components with chronic errors that beta's audit hasn't examined.
  
  Actions:
  1. Add a health-monitor rule: for each /dev/shm/hapax-exploration/
     *.json, check if chronic_error >= 1.0 AND
     stagnation_duration > 60 seconds
  2. If true: emit ntfy push + log warning + set a stimmung flag
  3. Rate-limit to once per component per hour
  4. Add matching Prometheus metric:
     hapax_exploration_stagnation_alert_total{component="..."}
     (queue #224 PresenceEngine Prometheus work set the precedent)
  
  This is complementary to queue #224 — it adds a generic
  observability layer to ALL exploration-tracked components, not
  just presence signals.
size_estimate: "~60 min implementation + test"
```

### 8.4 #243 — Secondary degrade trigger for silent audio

```yaml
id: "243"
title: "Contact mic backend: degrade on persistent silence (not just empty buffer)"
assigned_to: beta
status: offered
depends_on: []
priority: low
description: |
  Queue #233 found the existing control-law degrade trigger
  (len(energy_buffer) == 0) does NOT fire on silent-audio failures
  because the buffer is populated with zero samples. Add a secondary
  trigger: N consecutive ticks with smoothed_energy < _SILENCE_FLOOR
  (proposed: 30 ticks, ~1 minute, floor 1e-6).
  
  On trigger, log a warning + update desk_activity to "unknown" so
  the Bayesian presence engine's positive-only signal correctly
  returns None (rather than a false False negative).
  
  This is additive safety; the main alerting path is #242.
size_estimate: "~20 min implementation + test"
```

## 9. Non-drift observations

- **The DSP is correct given the input.** If the contact mic was actually producing typing audio, the backend would correctly classify `desk_activity="typing"` and publish a non-zero `desk_energy`. The bug is 100% upstream at the hardware layer.
- **Calibration constants are honest** — each has a 2026-03-25 provenance comment tied to a specific measurement. No silent drift; just a ~3-week staleness.
- **Tests don't catch the silent failure** because they mock the audio input with synthesized samples. A PipeWire-based integration test would be needed to catch upstream-null failures. Out of scope for queue #233.
- **This is the third cross-reference to the Studio 24c absence.** Queue #230 found the hardware missing; queue #233 confirms the operational impact; the CLAUDE.md § Bayesian Presence Detection desk_active signal claim (18x LR) is effectively non-functional right now. All three close roughly the same silent-failure observability gap.
- **The `desk_active` signal has LR 18x in the PresenceEngine** — one of the three strongest signals. With it silently returning "idle" → positive-only signal contributes None → the Bayesian presence posterior runs on a reduced evidence set. This compounds with queue #220 (watch HR stale for 9 days) — TWO of the strongest presence signals are silently degraded.

## 10. Cross-references

- Queue spec: `queue/233-beta-contact-mic-dsp-drift-check.yaml`
- Backend source: `agents/hapax_daimonion/backends/contact_mic.py` (520 LOC)
- Dead fusion helper: `agents/hapax_daimonion/backends/contact_mic_ir.py` (29 LOC, unused)
- Tests: `tests/hapax_daimonion/test_contact_mic_backend.py` + `test_contact_mic_ir_fusion.py`
- PipeWire config: `~/.config/pipewire/pipewire.conf.d/10-contact-mic.conf`
- Exploration tracker output: `/dev/shm/hapax-exploration/contact_mic.json`
- Perception snapshot: `~/.cache/hapax-daimonion/perception-state.json` (desk_* fields)
- Queue #230 voice FX chain verification: `docs/research/2026-04-15-voice-fx-chain-pipewire-verification.md` (commit `e82c32840`) — established the Studio 24c absence
- Queue #220 presence engine LR tuning: `docs/research/2026-04-15-presence-engine-lr-tuning-live-data.md` (commit `a5349edd8`) — sibling silent-failure finding for watch HR
- Queue #206 presence engine signal calibration audit: `docs/research/2026-04-15-presence-engine-signal-calibration-audit.md`
- Queue #224 PresenceEngine Prometheus observability (commit `954494ea5`) — sets the precedent for #242's alert layer
- CLAUDE.md § Bayesian Presence Detection — contains the false cross-modal fusion claim flagged in §5.3

— beta, 2026-04-15T21:15Z (identity: `hapax-whoami` → `beta`)
