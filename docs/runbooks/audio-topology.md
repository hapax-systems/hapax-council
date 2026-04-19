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
| `hapax-voice-fx-capture` *(virtual, optional)*           | TTS FX chain (`voice-fx-chain.conf` / `voice-fx-radio.conf`)   | Installed only if operator opts in. See `config/pipewire/README.md`. |
| `hapax-ytube-ducked` *(virtual)*                         | OBS / browser YouTube bed                                      | LADSPA sidechain; operator voice ducks the bed.                    |
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
| YouTube → 24c operator mix           | YT sink output keys sidechain on `hapax-24c-ducked`    | 24c hardware mix       | CVS #145 §7 (new spec)   | spec needed |
| YT loudness normalization            | `loudnorm` / `ebur128` on `hapax-ytube-ducked`          | YT bed itself          | CVS #145 §7              | spec needed |

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

## 7. Install + verify sequence

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

## 8. Rollback

```fish
rm ~/.config/pipewire/pipewire.conf.d/hapax-echo-cancel.conf
systemctl --user restart pipewire pipewire-pulse wireplumber
set -Ue HAPAX_AEC_ACTIVE
systemctl --user restart hapax-daimonion.service
```

Daimonion falls back to the raw Yeti source (pre-AEC behavior).

## 9. Related

- Spec: `docs/superpowers/specs/2026-04-18-audio-pathways-audit-design.md`
- Research: `/tmp/cvs-research-145.md` (ducking direction audit)
- Voice-FX presets: `config/pipewire/README.md`
- Follow-on #133 (Rode Wireless Pro): extends source priority list.
- Follow-on CVS #145: symmetric YT→24c ducker + YT loudness normalization.
