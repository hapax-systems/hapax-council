# Audio Pathways Complete Audit — Design

**Status:** 🟣 SPEC (provisionally approved 2026-04-18)
**Last updated:** 2026-04-18
**Source:** [`docs/superpowers/research/2026-04-18-homage-follow-on-dossier.md`](../research/2026-04-18-homage-follow-on-dossier.md) §2 — Task #134
**Index:** [active-work-index](../plans/2026-04-18-active-work-index.md)
**Priority:** HIGH (unblocks Rode #133; closes phantom-VAD loop)

---

## 1. Goal

Deliver a complete, documented, observable audio topology for hapax-council that (a) eliminates the YouTube-crossfeed → phantom-VAD → unintended ducking cycle, (b) makes echo-cancellation first-class, and (c) provides the authoritative runbook that Rode Wireless Pro integration (#133) layers onto.

---

## 2. Current State (2026-04-18)

### Input sources
- **Blue Yeti** (`alsa_input.usb-Blue_Microphones_Yeti...`) — operator primary.
- **PreSonus Studio 24c** (`alsa_input.usb-PreSonus_Studio_24c...`) — Cortado contact mic (mono-fallback).
- **AmbientAudioBackend** (derived, not a source) — room energy signal.
- **YouTube sink** (`hapax-ytube-ducked`) — distinct from speaker sink.

### Output sinks
- Main speakers (default sink).
- `hapax-ytube-ducked` (VLC/YouTube output; ducked during operator speech).
- Kokoro TTS output (default sink).

### Ducking
- Triggered by VAD (Silero) detecting speech on Yeti input.
- Ducks `hapax-ytube-ducked` volume to 20% for ~2 s after VAD signal ends.

### Gap: Echo cancellation
- `echo_cancel_capture` is the WirePlumber node name but **no `module-echo-cancel` pass runs**.
- Yeti picks up YouTube audio from room speakers (crossfeed).
- Silero VAD detects the crossfeed as "speech" → ducking triggers on phantom operator speech.
- Conversation STT transcribes YouTube content and treats it as operator intent.
- **Loop:** YouTube speech → ducking → Yeti quiet → VAD clears → YouTube un-ducks → loop.

---

## 3. Architecture (Target State)

### 3.1 Echo cancellation pass

Enable PipeWire `module-echo-cancel` on the Yeti input chain, referencing the default sink as the reference signal. This produces a new virtual source `echo_cancel_capture` that is now a real cancelled source, consumed by:
- Silero VAD
- Conversation STT
- Multi-mic discovery (`multi_mic.py`)

PipeWire config snippet:

```
context.modules = [
  { name = libpipewire-module-echo-cancel
    args = {
      library.name = aec/libspa-aec-webrtc
      node.name = echo_cancel_capture
      capture.props = { node.name = echo_cancel_capture }
      source.props = { node.name = yeti_cancelled; media.class = Audio/Source }
      sink.props = { node.name = echo_cancel_sink; media.class = Audio/Sink }
      playback.props = { node.name = yeti_cancelled_playback }
      aec.method = webrtc
    }
  }
]
```

### 3.2 Ducking trigger refactor

Current: `VAD == speech → duck`.
Target: `(VAD == speech) AND (operator-voice-embedding match > 0.75) → duck`.

- Uses existing speaker-diarization or voice-embedding path.
- Requires enrolled operator voice embedding (`/dev/shm/hapax-perception/operator-voice-embedding.npy`).
- Fallback: if embedding unavailable, fall back to VAD-only (current behavior) but log a warning.

### 3.3 Source priority (for Rode #133 hand-off)

`audio_input_source` in `hapax_daimonion/config.py` extends from single string to ordered list:

```python
audio_input_source: list[str] = [
    "rode_wireless_primary",
    "yeti_primary",
    "echo_cancel_capture",  # fallback if both hardware sources drop
]
```

Daimonion picks first available source from PipeWire at startup. Source hot-swap deferred to #133.

---

## 4. File-Level Plan

### New files
- `docs/runbooks/audio-topology.md` — canonical audio runbook; topology diagram, source/sink inventory, ducking rules, diagnostic commands.
- `scripts/audio-topology-check.sh` — diagnostic script enumerating live PipeWire graph vs expected topology; prints deltas.
- `tests/hapax_daimonion/test_ducking_trigger.py` — verify ducking requires both VAD AND voice-embedding match.

### Modified files
- `/etc/pipewire/pipewire.conf.d/hapax-echo-cancel.conf` — new PipeWire config enabling echo-cancel.
- `agents/hapax_daimonion/audio_input.py` — consume `echo_cancel_capture` virtual source instead of raw Yeti.
- `agents/hapax_daimonion/vad.py` — ducking-trigger gate on voice-embedding match.
- `agents/hapax_daimonion/config.py` — `audio_input_source` becomes `list[str]`.
- `shared/director_observability.py` — metrics for ducking triggers, echo-cancel state.

---

## 5. Observability

- `hapax_audio_ducking_triggered_total{reason}` — Counter; `reason ∈ {vad_and_embedding, vad_only_fallback, manual}`.
- `hapax_audio_echo_cancel_active` — Gauge (0 or 1).
- `hapax_audio_phantom_vad_detected_total` — Counter; increments when VAD fires but embedding match < 0.4 (likely YouTube crossfeed).
- `hapax_audio_source_active{source_name}` — Gauge per PipeWire source.

Grafana panel: ratio of `vad_and_embedding` to `vad_only_fallback` should trend toward 100% after embedding rollout.

---

## 6. Test Strategy

1. **Unit:** voice-embedding match function, threshold at 0.75.
2. **Integration:** ducking trigger: feed VAD=true + embedding_match=0.9 → assert duck; VAD=true + embedding_match=0.3 → assert no duck.
3. **Topology smoke:** `audio-topology-check.sh` enumerates live PipeWire graph, asserts `echo_cancel_capture` virtual source present.
4. **Regression:** play YouTube at audible room level, speak over it, assert duck fires; stop speaking, wait 3 s, speak again, assert no residual phantom ducking.

---

## 7. Open Questions

Q1. Operator voice embedding: enroll fresh or reuse existing speaker-ID? The existing face-ReID and voice-ID paths are separate; need to confirm voice embedding is already maintained. **Default:** fresh enrollment if no existing embedding found.

Q2. WebRTC AEC vs Speex AEC? **Default:** WebRTC (better for non-stationary noise, Rode's lavalier will move through the room).

Q3. Should Kokoro TTS output also feed the echo-cancel reference signal? Relevant for when Hapax is speaking through speakers and the Yeti picks up its own voice. **Default:** YES, merge into the reference signal.

---

## 8. Implementation Order

1. Write `audio-topology.md` runbook + topology diagram (documents current state as baseline).
2. Write `audio-topology-check.sh` and run against live system to verify baseline.
3. Enable echo-cancel PipeWire module (staged: verify on dev session first).
4. Wire daimonion input to `echo_cancel_capture` virtual source.
5. Add Prometheus metrics; verify echo_cancel_active gauge.
6. Enroll operator voice embedding.
7. Implement ducking-trigger gate.
8. Run regression test (YouTube crossfeed scenario).
9. Deploy Rode integration (#133) on the extended source list.

---

## 9. Rollback

- PipeWire echo-cancel: remove drop-in config file, reload wireplumber.
- Daimonion source: revert `audio_input_source` to single-string default.
- Voice-embedding gate: `audio_ducking_use_embedding_gate: false` in config.

---

## 10. Related

- **Dossier §2 #134** (source)
- **Follow-on #133** (Rode Wireless Pro): layers onto extended source list; this spec's §3.3 is the handoff point.
- **Voice pipeline:** `agents/hapax_daimonion/cpal/runner.py`
- **VAD:** `agents/hapax_daimonion/vad.py`
