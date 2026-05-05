# Audio Topology Runbook

**Status:** canonical
**Last updated:** 2026-04-18
**Authority:** [`docs/superpowers/specs/2026-04-18-audio-pathways-audit-design.md`](../superpowers/specs/2026-04-18-audio-pathways-audit-design.md)
**Verify live:** `scripts/audio-topology-check.sh`

This runbook is the single source of truth for the hapax-council audio graph:
which sources feed which consumers, which sinks back which outputs, how
echo-cancel sits in the capture chain, which duckers are wired in each
direction, and the exact diagnostics to run when any piece misbehaves.

---

## 1. Input sources

| PipeWire node / name                                     | Hardware                                             | Role                                                             |
|----------------------------------------------------------|------------------------------------------------------|------------------------------------------------------------------|
| `alsa_input.usb-Blue_Microphones_Yeti...`                | Blue Yeti                                            | Operator primary voice mic (raw). Feeds `module-echo-cancel`.     |
| `alsa_input.usb-PreSonus_Studio_24c...`                  | PreSonus Studio 24c Input 2                          | Cortado MKIII contact-mic (desk DSP, presence engine).           |
| `echo_cancel_capture` *(virtual)*                        | — (derived from Yeti + default-sink reference)       | **Authoritative operator source** for VAD / STT / multi_mic.     |
| `yeti_cancelled` *(virtual, alias)*                      | — (same graph node as `echo_cancel_capture`)         | Alias exposed by `module-echo-cancel`'s `source.props`.          |
| `hapax-operator-mic-tap` *(virtual)*                     | — (tap on operator mic, LRR Phase 9 §3.8)            | Sidechain key for `hapax-ytube-ducked` compressor.               |

**AmbientAudioBackend** is derived (room-energy signal on the default sink
monitor); it is not a PipeWire source.

## 2. Output sinks

| PipeWire node / name                                     | Consumer                                                       | Notes                                                              |
|----------------------------------------------------------|----------------------------------------------------------------|--------------------------------------------------------------------|
| `alsa_output.usb-PreSonus_Studio_24c...`                 | Studio monitors (default sink)                                 | Kokoro TTS lands here when `HAPAX_TTS_TARGET` is unset.            |
| `hapax-voice-fx-capture` *(virtual, optional)*           | TTS FX chain (`hapax-voice-fx-chain.conf`)                     | Installed only if operator opts in. See `config/pipewire/README.md`. |
| `hapax-ytube-ducked` *(virtual)*                         | OBS / browser YouTube bed                                      | LADSPA sidechain; operator voice ducks the bed.                    |
| `hapax-24c-ducked` *(virtual, optional)*                 | Studio 24c backing sources (DAW returns, synth strip)          | Driven by `AudioDuckingController` FSM; ducks backing when YT audio is active. CVS #145. |
| `echo_cancel_sink` *(virtual)*                           | `module-echo-cancel` reference                                 | Receives default-sink audio so AEC knows what to subtract.         |

## 3. PipeWire graph

```
┌───────────────────────────────┐       ┌────────────────────────────────────────┐
│ Blue Yeti (raw ALSA input)    │──────▶│  libpipewire-module-echo-cancel        │
└───────────────────────────────┘       │  ├── capture.props: echo_cancel_capture│──┐
                                        │  ├── source.props: yeti_cancelled      │  │
┌───────────────────────────────┐       │  └── aec.method: webrtc                │  │
│ default sink monitor          │──────▶│  sink.props:     echo_cancel_sink      │  │
│ (Kokoro TTS + media playback) │       └────────────────────────────────────────┘  │
└───────────────────────────────┘                                                   │
                                                                                    ▼
                                                             ┌──────────────────────────────────┐
                                                             │ Silero VAD                       │
                                                             │ Whisper STT                      │
                                                             │ multi_mic.py                     │
                                                             │ AudioInputStream (pw-cat target) │
                                                             └──────────────────────────────────┘

┌───────────────────────────────┐       ┌────────────────────────────────────────┐
│ PreSonus Studio 24c Input 2   │──────▶│ Contact mic DSP (Cortado MKIII)        │
│ (Cortado contact mic)         │       │  → presence engine, desk_activity      │
└───────────────────────────────┘       └────────────────────────────────────────┘

┌───────────────────────────────┐       ┌────────────────────────────────────────┐
│ Operator mic tap              │──────▶│ hapax-ytube-ducked (sidechain sink)    │──▶ default stereo
└───────────────────────────────┘       │  LADSPA sc4m_1916 (-30 dBFS, 8:1)      │
┌───────────────────────────────┐       │                                        │
│ OBS / browser YouTube bed     │──────▶│                                        │
└───────────────────────────────┘       └────────────────────────────────────────┘
```

## 4. Echo-cancel topology

**Goal:** kill the YouTube-crossfeed → Yeti → Silero VAD → ducking loop.

- `config/pipewire/hapax-echo-cancel.conf` loads `module-echo-cancel` with the
  WebRTC AEC backend.
- `capture.props` exposes the cancelled mono/near end as
  `echo_cancel_capture` (Audio/Source).
- `source.props` re-exposes the same graph as `yeti_cancelled` (alias).
- `sink.props` creates `echo_cancel_sink` — the reference (far-end) bus.
  WirePlumber loopback routes default-sink audio (music, TTS playback,
  browser audio) into it, per spec §7 Q3.
- Downstream consumers (`AudioInputStream`, `vad.py`, `multi_mic.py`) read
  `echo_cancel_capture`. Raw Yeti is only used when AEC is not installed.

**Daimonion toggle:** `HAPAX_AEC_ACTIVE=1` in the daimonion service env
promotes `echo_cancel_capture` as the preferred source. Default off; flip
once the drop-in is installed and verified via
`scripts/audio-topology-check.sh`.

## 5. Ducking rules

### Current (shipped)

| Direction                       | Trigger                            | Target                        | Mechanism                                                         | PR    |
|---------------------------------|------------------------------------|-------------------------------|-------------------------------------------------------------------|-------|
| Hapax TTS → YouTube PiP slots   | `_do_speak_and_advance` invocation | 3 PiP slot volumes            | Python `wpctl` envelope (~30 ms atk / 350 ms rel, ~-8 dB)         | #778  |
| Operator voice VAD → YT PiPs    | VAD speech from `voice-state.json` | 3 PiP slot volumes            | Same `wpctl` envelope                                             | #943  |
| Operator voice → YT bed sink    | Sidechain on `hapax-operator-mic-tap` | `hapax-ytube-ducked` sink   | LADSPA `sc4m_1916` compressor (-30 dBFS, 8:1, 5 ms, 300 ms)       | #1000 |

### Planned (spec #134 §3.2 + CVS #145)

| Direction                            | Trigger                                                | Target                 | Spec reference           | Status      |
|--------------------------------------|--------------------------------------------------------|------------------------|--------------------------|-------------|
| Operator voice → YT (embedding-gated) | `VAD && operator-voice-embedding match > 0.75`         | 3 PiP slots + YT sink  | `2026-04-18` §3.2        | deferred    |
| YouTube → 24c operator mix           | YT sink output keys sidechain on `hapax-24c-ducked`    | 24c hardware mix       | CVS #145 §7              | **shipped** (flag OFF) |
| YT loudness normalization            | `loudnorm` / `ebur128` on `hapax-ytube-ducked`          | YT bed itself          | CVS #145 §7              | spec needed |

### AudioDuckingController state machine (CVS #145, feature-flagged)

`agents/studio_compositor/audio_ducking.py::AudioDuckingController`
couples operator VAD + React/YT audio activity into a 4-state FSM and
drives both `hapax-ytube-ducked` and `hapax-24c-ducked` gains.

| State          | Condition                       | YT bed gain | Backing gain |
|----------------|---------------------------------|-------------|--------------|
| `NORMAL`       | neither VAD nor YT active       | 1.0         | 1.0          |
| `VOICE_ACTIVE` | VAD fires, YT silent (≤debounce)| -12 dB      | 1.0          |
| `YT_ACTIVE`    | YT audible, VAD silent          | 1.0         | -6 dB        |
| `BOTH_ACTIVE`  | VAD + YT both fire              | -18 dB      | 1.0          |

- **Feature flag:** `HAPAX_AUDIO_DUCKING_ACTIVE=1` in the compositor
  unit env. Default OFF — the controller still observes and publishes
  state but dispatches no PipeWire changes.
- **Hysteresis:** `vad_debounce_s=2.0`, `yt_debounce_s=0.5`. Brief VAD
  drops don't flip out of `VOICE_ACTIVE`.
- **Observability:** `hapax_audio_ducking_state{state}` Prometheus
  gauge (one-hot).
- **PipeWire preset:** install
  `config/pipewire/yt-over-24c-duck.conf` to provision the
  `hapax-24c-ducked` sink before flipping the flag on.

### CVS #145 install + verify

```fish
# 1. Install the 24c ducker sink (paired with the existing ytube-ducked).
cp config/pipewire/yt-over-24c-duck.conf ~/.config/pipewire/pipewire.conf.d/
systemctl --user restart pipewire pipewire-pulse wireplumber

# 2. Verify both sinks appear.
pactl list short sinks | grep -E "hapax-ytube-ducked|hapax-24c-ducked"

# 3. Route backing sources (DAW return, synth strip) through hapax-24c-ducked.
#    Per-application audio assignment — no global default change required.

# 4. Flip the flag (compositor systemd user unit env or shell override).
set -Ux HAPAX_AUDIO_DUCKING_ACTIVE 1
systemctl --user restart studio-compositor.service  # or equivalent entry point

# 5. Confirm state machine output.
curl -s http://127.0.0.1:9482/metrics | grep hapax_audio_ducking_state
```

The embedding gate (§3.2) is what transforms "VAD fires → duck" into
"operator speech → duck". Today's path C (#1000 sidechain compressor) is
amplitude-triggered and cannot distinguish operator voice from crossfed
YouTube voice; once `echo_cancel_capture` lands, the crossfeed concern
disappears for paths A/B (both now read AEC'd input), and the embedding
gate covers any residual cases + operator VAD false fires on
non-speech percussive content.

## 6. Diagnostic commands

```fish
# Authoritative: compare live graph to expected topology.
scripts/audio-topology-check.sh

# Raw PipeWire graph inspection.
pw-cli list-objects Node
pw-link -I                 # enumerate links
pw-link -o                 # ports by output
pw-link -i                 # ports by input

# WirePlumber high-level view (default source / sink / routes).
wpctl status

# PulseAudio compatibility surface (easier for grep-based checks).
pactl list short sources
pactl list short sinks
pactl list sources         # full (volumes, mute, active port)

# Verify AEC module actually loaded.
pw-cli list-objects Module | grep echo-cancel

# Tail filter-chain errors (common after preset swaps).
journalctl --user -u pipewire -n 200
journalctl --user -u wireplumber -n 200

# Quick round-trip: record 1 s from echo-cancel source, confirm non-silent.
pw-cat --record --target echo_cancel_capture --format s16 --rate 16000 --channels 1 /tmp/aec-probe.wav && \
    ffprobe -v error -show_format /tmp/aec-probe.wav
```

## 7. Private Monitor Exact-Target Recovery

Private assistant and notification audio must bind only to the exact private
monitor endpoint. They must not fall through to the default sink, L-12,
multimedia, voice-fx, or any public/broadcast route.

Use the recovery command whenever the operator cannot hear private monitor
audio or after PipeWire/private monitor hardware churn:

```fish
scripts/hapax-private-monitor-recover --install
cat /dev/shm/hapax-audio/private-monitor-target.json
scripts/audio-leak-guard.sh
```

In normal operation, the repo-managed user timer keeps this witness fresh:

```fish
systemctl --user status hapax-private-monitor-recover.timer
systemctl --user status hapax-private-monitor-recover.service
```

The timer runs every 60 seconds and writes
`/dev/shm/hapax-audio/private-monitor-target.json`, which is safely inside the
semantic router's 300-second freshness window. `blocked_absent` is a successful
witness publication: it means the exact private monitor path is unavailable and
private voice must remain silent rather than fall back.

Expected healthy state:

- `private_monitor_state=ready`;
- status JSON reports `surface_id: audio.yeti_monitor`;
- status JSON reports `route_id: route:private.yeti_monitor`;
- status JSON reports `fallback_policy: no_default_fallback`;
- `scripts/audio-leak-guard.sh` reports no leak risk.

If the exact target or bridge is missing, the command writes
`state: blocked_absent` with an operator-visible reason. That state is the
correct failure mode. Do not route private comms to a default sink or public
route to "make it audible."

The status JSON is intentionally sanitized. It uses semantic refs such as
`audio.yeti_monitor` and `route:private.yeti_monitor`; do not paste raw
PipeWire hardware identifiers into relay/task notes or chat.

## 8. Install + verify sequence

```fish
# 1. Drop echo-cancel config in place.
cp config/pipewire/hapax-echo-cancel.conf ~/.config/pipewire/pipewire.conf.d/

# 2. Reload PipeWire stack (brief audio interruption).
systemctl --user restart pipewire pipewire-pulse wireplumber

# 3. Verify topology.
scripts/audio-topology-check.sh

# 4. Flip daimonion to the cancelled source.
set -Ux HAPAX_AEC_ACTIVE 1
systemctl --user restart hapax-daimonion.service
```

## 9. Rollback

```fish
rm ~/.config/pipewire/pipewire.conf.d/hapax-echo-cancel.conf
systemctl --user restart pipewire pipewire-pulse wireplumber
set -Ue HAPAX_AEC_ACTIVE
systemctl --user restart hapax-daimonion.service
```

Daimonion falls back to the raw Yeti source (pre-AEC behavior).

## 10. Rode Wireless Pro (task #133)

The Rode Wireless Pro is the operator's on-body lavalier. When present,
it becomes the authoritative voice source; on disappear, daimonion
falls back to the Blue Yeti (AEC'd) automatically. **No daimonion
restart** is ever required — the adapter flips a tag file which the
STT resolver reads live with a 5 s cache.

**Components:**

- `agents/hapax_daimonion/rode_wireless_adapter.py` — polls
  `pw-cli list-objects` every 5 s, writes the current source tag
  (`rode` | `yeti` | `contact-mic`) to
  `/dev/shm/hapax-compositor/voice-source.txt`.
- `agents/hapax_daimonion/cpal/stt_source_resolver.py` — reads the
  tag file (5 s cache), maps to the PipeWire node that
  `pw-cat --record --target` accepts.
- `systemd/units/hapax-rode-wireless-adapter.service` — user unit.
  **Not auto-enabled.** Engage manually.
- Prometheus gauge `hapax_voice_source{source}` (1 = active, 0 = inactive).

**Engage:**

```fish
# 1. Symlink or copy the unit into the user directory.
install -Dm644 systemd/units/hapax-rode-wireless-adapter.service \
  ~/.config/systemd/user/hapax-rode-wireless-adapter.service

# 2. Start + enable (enable only once you've confirmed it does the right thing).
systemctl --user daemon-reload
systemctl --user start hapax-rode-wireless-adapter.service
journalctl --user -u hapax-rode-wireless-adapter -f

# 3. Plug the Rode receiver; within ~5 s the tag file should flip.
cat /dev/shm/hapax-compositor/voice-source.txt          # "rode"
# Unplug — the adapter falls back to Yeti.
cat /dev/shm/hapax-compositor/voice-source.txt          # "yeti"

# 4. Enable for next boot once satisfied.
systemctl --user enable hapax-rode-wireless-adapter.service
```

**Rollback:** `systemctl --user stop hapax-rode-wireless-adapter`
and remove the tag file — the resolver falls back to Yeti on missing
tag, so no daimonion state is affected.

### 9.1 Source priority and the two-layer resolver (audit-pathways T4.3)

Two layers cooperate to pick the live capture source. Documented here
because they look adjacent but are NOT the same priority system —
operator confusion about why a Rode plug-in didn't immediately swap a
running pw-cat is almost always the wrong layer being inspected.

**Layer A — `DEFAULT_SOURCE_PRIORITY` (`agents/hapax_daimonion/audio_input.py`):**

A static, ordered list of pw-cli node names the daimonion's main
capture path tries in order. First match in the live PipeWire graph
wins. Current default:

```python
DEFAULT_SOURCE_PRIORITY = [
    "echo_cancel_capture",                                           # AEC virtual source
    "alsa_input.usb-Blue_Microphones_Yeti_Stereo_Microphone_REV8-00.analog-stereo",  # raw Yeti fallback
]
```

The Rode is NOT in this list because the AEC source is the
authoritative voice path when present (it consumes Yeti underneath +
ducks against the playback monitor). Plan §T4.3 recommended extending
to `["echo_cancel_capture", "Rode_Wireless_Pro", "Yeti"]`; this is a
follow-on if/when the Rode is enrolled into the AEC source's capture
chain (currently, AEC is hard-wired to Yeti via the conf in
`config/pipewire/hapax-echo-cancel.conf`).

**Layer B — `voice-source.txt` tag file (`stt_source_resolver.py`):**

A live tag the rode_wireless_adapter writes (`rode` | `yeti` |
`contact-mic`) every 5 s based on PipeWire enumeration. The STT
resolver reads this file (5 s cache) to override the static priority
when the Rode is physically present. This layer is for
**display + STT routing**, not for the capture pipeline itself.

**Rule of thumb:** if you want the daimonion to use the Rode for STT,
plug it in and verify `voice-source.txt` flips. If you want the AEC
echo-cancel chain to use the Rode as its noisy-mic input, you have to
edit `config/pipewire/hapax-echo-cancel.conf` and restart the
PipeWire user units — the chain does not dynamically swap capture
targets.

### 9.2 Bayesian presence cross-check

The presence engine (`agents/hapax_daimonion/presence_engine.py`)
fuses heterogeneous signals into a single posterior. Rode presence
is currently a **secondary** indicator (the Rode being on-body is
strong evidence of operator presence) but the Rode-RSSI sub-signal
is NOT yet wired into `PresenceEngine`. Open follow-on:

- `Rode_RSSI` from `pw-cli list-objects | grep rode` — likelihood
  ratio TBD (operator empirical)
- Cross-check with `ir_body_heat` (already wired): when both fire,
  bump posterior; when Rode says "present" but IR says "no body
  heat for 30s," log a contradiction (operator may have left the
  Rode at the desk while stepping away).

Wire-up is an open task; T4.3 names it as the audit-pathways follow-on.

## 10. Related

- Spec: `docs/superpowers/specs/2026-04-18-audio-pathways-audit-design.md`
- Research: `/tmp/cvs-research-145.md` (ducking direction audit)
- Voice-FX presets: `config/pipewire/README.md`
- Follow-on CVS #145: symmetric YT→24c ducker + YT loudness normalization.
