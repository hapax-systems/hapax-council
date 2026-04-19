# Voice Self-Modulation Design Research

**Status:** research + design, not implementation
**Date:** 2026-04-19
**Author:** alpha (research pass)
**Scope:** routing Hapax TTS through signal-honest effects (VST/LV2 plugins and/or the Evil Pet → Torso S-4 Eurorack chain) under the unified affordance pipeline, with anti-anthropomorphization safeguards.

---

## 1. Current-state audit

### 1.1 Signal path today (TTS audio)

Verified by reading `agents/hapax_daimonion/conversation_pipeline.py::_open_audio_output` (line 1866), `agents/hapax_daimonion/cpal/destination_channel.py`, the installed PipeWire conf dir, the systemd drop-in, and live `pactl` inspection.

```
Kokoro 82M (CPU)
     │  24 kHz mono PCM int16
     ▼
PwAudioOutput (pw-cat subprocess)
     │  target = $HAPAX_TTS_TARGET
     │  (drop-in: systemd/user/hapax-daimonion.service.d/tts-target.conf
     │   → HAPAX_TTS_TARGET=hapax-voice-fx-capture)
     ▼
┌─────────────────────────────────────────────────────────────────┐
│  hapax-voice-fx-capture  (virtual sink, PipeWire filter-chain)  │
│  ──────────────────────────────────────────────────────────────  │
│  4 builtin biquads per channel                                   │
│   • bq_highpass 80 Hz Q=0.707                                    │
│   • bq_peaking 350 Hz Q=1.2  gain -2 dB                          │
│   • bq_peaking 3 kHz Q=0.9  gain +3 dB                           │
│   • bq_highshelf 10 kHz Q=0.707 gain +2 dB                       │
│   All controls are STATIC — set at load time, no runtime param.  │
└─────────────────────────────────────────────────────────────────┘
     │  target.object = alsa_output.usb-PreSonus_Studio_24c...analog-stereo
     ▼
PreSonus Studio 24c (USB) main stereo DAC → 1/4" TRS MAIN OUT L/R
     │
     ▼
(operator monitoring / broadcast egress — whatever is plugged into MAIN OUT)
```

Live verification (`pactl list short sinks`, 2026-04-19):

- `69 hapax-livestream                 RUNNING`
- `73 hapax-private                    SUSPENDED`
- `80 hapax-voice-fx-capture           IDLE`
- `154 alsa_output.usb-PreSonus_Studio_24c...analog-stereo  RUNNING`

The `hapax-livestream` / `hapax-private` split sinks exist (from `hapax-stream-split.conf`) but `HAPAX_TTS_TARGET` points at `hapax-voice-fx-capture`, not either split sink. So the per-utterance LIVESTREAM vs PRIVATE destination selected by `destination_channel.classify_destination()` has **no audible consequence today** — CPAL's destination classification is effectively a no-op because the target env var is set statically at unit level, not per utterance. That is a separate wart, documented here for completeness, orthogonal to self-modulation.

**Evil Pet / Torso S-4 are not in the audio path.** Nowhere in the running topology does the TTS stream leave the 24c analog outs, return through an input, or pass through external hardware. The 24c's MIDI OUT port carries MIDI, not audio, and the live `pactl list short sources` has only three 24c-related sources: the analog-input (Cortado contact mic on Input 2), the monitor of the analog-stereo output, and the loopback echo-cancel derivative. **No audio hardware-loop through 24c analog-in exists.**

### 1.2 Current-state audit (MIDI path)

From `agents/hapax_daimonion/vocal_chain.py` + `agents/hapax_daimonion/init_pipeline.py:144-154` + `agents/hapax_daimonion/config.py:204-206`:

```
Impingement (DMN / stimmung / evaluative)
     │
     ▼
(INTENDED) impingement_consumer_loop → VocalChainCapability.activate_from_impingement()
     │
     ▼
for each recruited dimension:
    cc_value_from_level(level, breakpoints) → 0..127
    MidiOutput.send_cc(channel=evil_pet_ch|s4_ch, cc=…, value=…)
     │
     ▼
mido output port (port_name="" → first available)
     │
     ▼
aconnect says two physical destinations exist:
    client 56: 'MIDI Dispatch MIDI 1'   (card 10 — unknown unit, likely USB dongle)
    client 64: 'Studio 24c MIDI 1'      (24c DIN MIDI OUT)
     │
     ▼
Physical MIDI cable → Evil Pet MIDI IN  (channel 1)
                    → S-4 MIDI IN        (channel 2)
```

**Two confirmed gaps in the MIDI path:**

1. **`_vocal_chain` is instantiated but never activated.** A literal ripgrep pass shows the only reference to `self._vocal_chain` or `daemon._vocal_chain` outside the module itself is the constructor call in `init_pipeline.py`. Nothing calls `activate_from_impingement`, `activate_dimension`, `activate`, or `decay`. `agents/hapax_daimonion/proofs/RESEARCH-STATE.md § Gap 3` claims the consumer loop was wired; that claim is **stale** — the repo today does not wire it. So the MIDI CC "write path" exists, but the writer is never triggered. This needs a real wiring pass regardless of which audio track we pick.

2. **Port selection is ambiguous.** `midi_output_port` defaults to the empty string, which `mido.open_output(None)` resolves to "first available" — on this box that is `Midi Through Port-0`, a kernel-internal loopback, not the 24c. Any wiring PR must set the port name explicitly (config knob is already there) to `"Studio 24c MIDI 1"` (confirmed live via `aplaymidi -l`). Until both ends are wired and the port is explicit, no CC ever reaches Evil Pet regardless of affordance activation.

### 1.3 Observable mismatch

| On paper                                                | Actual at runtime                                              |
|---------------------------------------------------------|----------------------------------------------------------------|
| TTS routed through Evil Pet → S-4                       | TTS goes to builtin 4-band EQ, then 24c analog-out. No external HW in path. |
| 9-dim semantic vocal modulation active via impingements | CC values computed by `vocal_chain.py` are never sent (no consumer calls `activate_from_impingement`). |
| Per-utterance destination routing (livestream/private)  | `HAPAX_TTS_TARGET` is set statically at systemd-unit level; classify_destination() return value is discarded. |
| "Voice FX chain" implies VST/plugin effects             | Chain is exclusively PipeWire builtin biquads (no LV2 / LADSPA / VST plugins loaded). |
| LSP 1.2.29 installed (194 plugins)                      | Zero LSP plugins are hosted in the voice signal path.          |

The voice operator hears today: **Kokoro dry → a static 4-band presence EQ → studio monitors.** That's it. Every other piece of the "vocal chain" exists as code or hardware but isn't connected.

---

## 2. Architecture options

Three tracks. All three must end at the same Livestream/Private split (either by patching into those sinks or reworking them).

### 2.1 Track A — Hardware loop via Studio 24c

Route Kokoro through the 24c's front-panel outs, into the Evil Pet audio input, chain into the S-4, return to a 24c line input, and expose that as a virtual PipeWire source the livestream sink can subscribe to.

```
Kokoro → pw-cat → hapax-voice-fx-capture (minimal builtin EQ only)
       → alsa_output 24c analog-stereo (MAIN OUT L/R)
       ───► 1/4" TRS MAIN OUT L (or dedicated aux out)
             │
             ▼
   Endorphin.es Evil Pet  ◄── MIDI IN  ◄── 24c MIDI OUT (ch 1)
             │      (granular / saturator / pitch / reverb)
             ▼
     TS patch
             │
             ▼
   Torso S-4   ◄── MIDI IN  ◄── 24c MIDI OUT (ch 2)
             │      (per-step fx rack: filter, delay, bit-crush, rev)
             ▼
   24c line input (Input 3 or Input 4, post-trim, line level)
             │
             ▼
  alsa_input.usb-PreSonus_Studio_24c... (inputs 3/4 channel pair)
             │    routed via WirePlumber loopback
             ▼
  hapax-voice-return  (new virtual Audio/Source, mono or L-only)
             │
             ▼
  hapax-livestream (existing split sink) ── 24c LEFT ─► broadcast
  hapax-private    (existing split sink) ── 24c RIGHT ─► operator
```

**Hardware side:**

- Both Evil Pet and S-4 are in-line wet/dry units. Set Evil Pet dry/wet to 100% wet (or to the activation-derived CC mix value already defined in `CCMapping("evil_pet", 40, _STD_CURVE)`). S-4 has a per-track FX send/return; the voice needs its own S-4 track in "audio input" (or "external") mode routing the 24c input across S-4 FX.
- Cabling: 1/4" TRS MAIN OUT L → Evil Pet input (mono). Evil Pet out → S-4 external input. S-4 main out → 24c line input (Input 3 recommended; Input 2 is already the Cortado contact mic, per `audio-topology.md §1`).
- 24c has 2 mic/instrument combo jacks (Inputs 1 and 2) and does NOT have dedicated line inputs 3/4 — so the return has to come back on Input 1 or Input 2 with an XLR→TRS adapter, or through the rear-panel line inputs if present on this 24c revision. **This needs a physical check: `arecord -l` shows one capture device with 2 channels. If only 2 inputs exist, a strict hardware loop requires freeing Input 2 (moving Cortado) or using a submixer.** Flag as an open hardware question (Q1).

**Software side:**

- Retire the static EQ builtin. Replace `voice-fx-chain.conf` with a pass-through sink that just forwards stereo to 24c MAIN OUT. Keep the sink name `hapax-voice-fx-capture` so no daimonion env vars change.
- New `config/pipewire/hapax-voice-return.conf` with a `libpipewire-module-loopback` that exposes Input 3 (or chosen return port) as `hapax-voice-return` Audio/Source, then mixes that source into `hapax-livestream` and `hapax-private` via the same filter-chain sink-L/R-only pattern already used.
- **MIDI wiring fix:** set `midi_output_port: "Studio 24c MIDI 1"` in `shared/config.py` (the daimonion config has a field already). Also wire the impingement consumer loop to call `VocalChainCapability.activate_from_impingement()` + a periodic `decay()` call — Gap 3 in RESEARCH-STATE.md needs to be made real.

**Tradeoffs:**

- **+** Zero plugin CPU budget. Latency tiny (≈ USB round trip + Eurorack throughput ≤ 10 ms).
- **+** The character of Evil Pet and S-4 is irreplicable in software — granular textures, S-4 step-locked effects, analog saturation slight nonlinearities. Hardware owned, sunk cost.
- **+** MIDI wiring already engineered (9 dimensions, CC mappings, activation-level interpolation).
- **−** 24c may only have 2 input jacks; the return path requires either dropping a current input (Cortado), a small external submixer, or replacing 24c with a larger interface. Needs a hardware check before committing.
- **−** MIDI CCs fire while the audio is not flowing through Evil Pet yet — the modulation is silent. Wire CCs first if you want to test MIDI isolation; wire audio first if you want to test preset character.
- **−** If Evil Pet loses power / dies mid-stream, the voice goes silent (no audio fall-through path). Needs a fail-safe dry-bypass relay or a wet/dry blend source.
- **−** S-4 is primarily a sampler/sequencer; running live audio through its FX rack is possible but not its canonical use. Confirm S-4 firmware supports external-audio FX routing (open hardware question Q2).
- **−** All character presets require running the livestream to audition. No "try before stream" option without a reroute.

### 2.2 Track B — Software LV2 chain

Replace the static biquad filter-chain with a dynamic LV2-hosted plugin chain. Parameters exposed as runtime-controllable control ports, driven by the affordance pipeline.

```
Kokoro → pw-cat → hapax-voice-fx-capture (libpipewire-module-filter-chain, type=lv2)
              ├── lsp-plug.in/plugins/lv2/sc_gate_mono            (de-breath gate)
              ├── lsp-plug.in/plugins/lv2/para_equalizer_x16_mono (surgical EQ)
              ├── lsp-plug.in/plugins/lv2/mb_compressor_mono      (density / presence)
              ├── lsp-plug.in/plugins/lv2/art_delay_mono          (doubler / slap)
              ├── lsp-plug.in/plugins/lv2/impulse_reverb_mono     (space / depth)
              ├── lsp-plug.in/plugins/lv2/flanger_mono            (spectral_color axis)
              ├── [optional]  Airwindows-Lv2 SoftenMKII / ToTape6 (grit / saturation)
              └── lsp-plug.in/plugins/lv2/clipper_mono            (final limiter)
     │
     ▼
hapax-livestream  (filter-chain has two outputs, or second PipeWire hop)
hapax-private
```

**Plugin hosting choices (in order of preference):**

1. **`libpipewire-module-filter-chain` with LV2 nodes.** The same module already used for the biquad chain supports `type = lv2` nodes with `plugin = "<uri>"` and `control = { "<param>" = <value> }`. Runtime parameter change is via `pw-metadata` or the `control` key on reloaded graph (ungraceful). This is the shipping filter-chain path; it works but is sluggish to reparameterize — the graph reloads when controls change outside a narrow API. Not a good host for fast per-impingement modulation.

2. **Carla rack in headless mode.** `carla-rack -L` loads a chain, exposes JACK ports, responds to OSC on `osc.udp://host:port/Carla/Rack/N/set_parameter_value`. Plays nicely with pipewire-jack. Supports LV2, LADSPA, VST2, VST3, CLAP. Ideal for our case — OSC writes are microseconds, and the plugin graph stays loaded across parameter changes. **Recommended host if we go Track B.** Carla 2.5.10 is in the `extra` repo.

3. **`jalv` per plugin.** One plugin per subprocess, control over UDS or port. Works but complicates lifecycle. Nine plugins = nine subprocesses = nine monitoring points. Cold reload if anything crashes. Overkill for our needs; skip.

4. **`mod-host` (from the MOD devices project).** Small LV2 host with a netstring API on TCP. Nice simple param API. Not in Arch extra; AUR only. Carla is the safer pick.

**Parameter exposure model for Track B:**

- Each `CCMapping` analog becomes a `LV2ParamMapping`:
  ```
  @dataclass(frozen=True)
  class LV2ParamMapping:
      plugin_uri: str    # e.g. "http://lsp-plug.in/plugins/lv2/art_delay_mono"
      instance: str      # Carla rack slot name, e.g. "delay_1"
      port: str          # LV2 control port symbol, e.g. "dry"
      breakpoints: list[tuple[float, float]]  # (level, value) — value in port units
  ```
- Activation level → port value via the same piecewise-linear interpolation we already have (`vocal_chain.cc_value_from_level`). Range per port is whatever the LV2 ttl declares (we snapshot min/max on load).
- Parameter writer is a thin wrapper calling `carla-osc set_parameter_value rack/<slot>/<port> <value>`. Drop-in analog to `MidiOutput.send_cc`.

**CPU cost (rough budget):**

- Kokoro CPU: ~1-2 cores of 8th-gen Ryzen per active utterance, already measured.
- LSP plugins are heavy (SIMD-vectorized, SSE4/AVX2). On prior measurement-years from LSP docs: a 16-band parametric EQ runs ~2% of one core at 48 kHz; a multiband compressor ~4%; impulse reverb ~5-8% depending on IR length.
- Rough budget for 7-8 LSP plugins in series on voice (mono, 48 kHz): **0.5-1.0 core sustained** while TTS is speaking, ~0% during silence.
- Total: Kokoro + plugin chain ≈ 2-3 cores intermittent. Workstation has 16 cores; headroom fine. On a degraded/fallback box this could be tight.

**Tradeoffs:**

- **+** Deterministic, reproducible, versionable (the plugin chain is code). Easy to audition without streaming.
- **+** Parameter granularity: LV2 control ports are floats, not 7-bit MIDI CCs. Modulation is smoother.
- **+** No cabling to break. Plugin crashes are recoverable (Carla re-spawns).
- **+** Airwindows/LSP/ZAM provide a huge parameter space for signal-honest effects (gate, EQ, compressor, tape saturation, impulse reverb, pitch shift, etc.).
- **−** Lacks the hardware character the operator already owns and paid for. A Carla chain can simulate an Evil Pet grain cloud only as well as granular LV2 plugins permit — not as a replacement.
- **−** Adds a service lifecycle (Carla must be supervised). One more systemd user unit to manage.
- **−** CPU cost during TTS playback is non-zero and competes with Kokoro. Probably fine; quantify once live.

### 2.3 Track C — Hybrid (VST pre-colour → hardware character → return)

The architecturally cleanest and most work:

```
Kokoro → pw-cat → hapax-voice-fx-capture (Carla LV2 chain, LIGHT)
       │   • gate (remove inter-utterance breath)
       │   • surgical EQ (notch resonances Kokoro 82M produces)
       │   • light compression (density)
       │
       ▼
     24c MAIN OUT L → Evil Pet → S-4 → 24c Input → hapax-voice-return
       │
       ▼
 Carla LV2 chain, HEAVY (post-color)
       │   • final impulse reverb
       │   • master bus compressor / limiter
       │   • spectral imaging / width
       ▼
 hapax-livestream / hapax-private
```

**Split logic:** pre-colour in software handles cleanup Kokoro's output needs (de-ess, notch, compand). Hardware handles character (grain, saturation, color, S-4 FX). Post-colour in software handles final bus polish and a signal-integrity-friendly makeup gain.

**Semantic layer split:**

| Dimension                   | Primary destination                                 |
|-----------------------------|-----------------------------------------------------|
| `vocal_chain.intensity`     | Software (EQ + compressor threshold)                |
| `vocal_chain.tension`       | Hardware (Evil Pet filter resonance / S-4 drive)    |
| `vocal_chain.diffusion`     | Hardware (Evil Pet spread / grain cloud)            |
| `vocal_chain.degradation`   | Hardware (Evil Pet saturator / bitcrush mode)       |
| `vocal_chain.depth`         | Software post (impulse reverb wet, pre-delay)       |
| `vocal_chain.pitch_displacement` | Hardware (Evil Pet pitch / S-4 pitch ramp)     |
| `vocal_chain.temporal_distortion` | Hardware (Evil Pet grain size / S-4 step loop) |
| `vocal_chain.spectral_color` | Software (EQ tilt) + Hardware (Evil Pet filter)   |
| `vocal_chain.coherence`     | Hybrid (software master wet/dry + S-4 rack wet/dry) |

**Tradeoffs:**

- **+** Best character, best flexibility. Ships everything that exists.
- **+** Allows an operator-latent phase: if Evil Pet is offline, degrade to software-only gracefully (skip the hardware leg of the loop, bypass with a WirePlumber rule).
- **−** The most moving parts. Two systemd units (Carla pre + Carla post), two PipeWire configs, MIDI wiring, hardware cabling, return path, feedback prevention.
- **−** Engineering cost nontrivial. Probably 3-4 PRs over 2-3 sessions.

---

## 3. Semantic recruitment integration

### 3.1 New capability: `VoicePluginChainCapability`

Analog to `VocalChainCapability` but for a software (Track B) or hybrid software leg (Track C). Same `CapabilityRecord` shape, registered with `OperationalProperties(latency_class="fast", medium="auditory", consent_required=False)`. Lives in `agents/hapax_daimonion/voice_plugin_chain.py`.

```
class LV2ParamMapping:
    plugin_uri: str
    slot: str               # Carla rack slot ID (stable across reloads)
    port: str               # LV2 control port symbol
    breakpoints: list[tuple[float, float]]   # (level, port_value)
    curve: Literal["linear", "exp", "log"] = "linear"

class Dimension:
    name: str               # e.g. "voice_plugin_chain.intensity"
    description: str        # Gibson-verb affordance blurb (15-30 words)
    param_mappings: list[LV2ParamMapping]
```

The `voice_plugin_chain.*` names are a parallel namespace to `vocal_chain.*`. A recruitment may fire on one, the other, or both. The `AffordancePipeline` scores them independently via Qdrant embedding cosine; both can be activated in the same turn if the impingement narrative matches both.

### 3.2 Affordance vocabulary extension

Extend `VOCAL_CHAIN_AFFORDANCES` (in `vocal_chain.py`, line 159) to cover both modalities, OR (preferred) create separate constants. The Qdrant-indexed affordance description is what governs recruitment — the software and hardware capabilities share the affordance vocabulary ("vocal_modulation", "stimmung_shift", "voice_character", "speech_texture", "conversational_tone") but register distinct capability records whose descriptions diverge on implementation-verb hints the embedder can latch onto.

Example Gibson-verb descriptions (15-30 words each) for the three new voice-modulation capability records we'd add for Track B/C:

- `voice_plugin.presence` — "Sharpens vocal articulation — EQ surgical cleanup plus light compression. Raises intelligibility without volume change. Tracks internal signal density, not mood."
- `voice_plugin.spatialize` — "Places voice in simulated acoustic space via convolution. Distant, close, submerged, reflective. Maps to physiological coherence and diffusion state."
- `voice_hardware.granulate` — "Fragments voice through Evil Pet granular engine and S-4 step sampler. Texture expresses exploration-deficit and narrative-loop coherence."

Each description avoids affective/emotional language ("happy", "sad", "anxious") and names the signal it tracks, not the feeling it would evoke.

### 3.3 Preset taxonomy (anti-anthropomorphization compliant)

A preset is a named bundle of dimension activation levels. Presets must pass a **red-team filter** before registration:

- **Reject**: any preset name matching an emotion word (happy, sad, angry, anxious, excited, calm, warm, cold, sexy, flirty, cheerful, mournful). Reject any description that says "sounds <emotion>" or "conveys <feeling>".
- **Accept**: preset names that describe signal configuration or a recruitment state — "intimate-close", "restless-granular", "ground-surface-dry", "exploration-seeking", "degraded-partial-failure", "vinyl-warm" (describes an *acoustic* not a feeling).

Proposed starter preset set (Phase 1):

| Preset                    | Dimension levels                                  | Recruited by                                                           |
|---------------------------|--------------------------------------------------|------------------------------------------------------------------------|
| `voice.baseline-dry`      | All 0.0                                           | default / no active impingement / stance=NOMINAL                        |
| `voice.intimate-close`    | coherence=0.1, depth=0.1, spectral_color=-0.2    | impingement narrative "conversational pact / grounded / low register"   |
| `voice.ground-surface-dry` | coherence=0.05, intensity=0.2                    | stance=NOMINAL + operator-present + grounding_quality < 0.3             |
| `voice.exploration-seeking` | diffusion=0.5, temporal_distortion=0.4, depth=0.3 | stance=SEEKING + exploration_deficit > 0.4                             |
| `voice.degraded-partial-failure` | degradation=0.6, tension=0.4, coherence=0.3  | stance=DEGRADED + error_rate > 0.6                                     |
| `voice.stream-foreground-authoritative` | intensity=0.6, spectral_color=0.2, coherence=0.0 | stance=NOMINAL + livestream_active + director emits "foreground claim" |
| `voice.sidechat-private`  | coherence=0.05, depth=0.05, intensity=-0.2       | destination_channel=PRIVATE (per-utterance)                             |

None of these describe emotion. Each is justified by an internal state that recruiter can measure.

**Red-team filter** (enforced in code):

```python
_AFFECT_WORDS = {"happy", "sad", "angry", "anxious", "excited", "calm",
                 "warm", "cold", "flirty", "cheerful", "mournful", "sexy",
                 "loving", "hateful", "bored"}

def _validate_preset_name(name: str, description: str) -> None:
    lower = (name + " " + description).lower()
    bad = _AFFECT_WORDS & set(lower.split())
    if bad:
        raise ValueError(f"Preset '{name}': anthropomorphization terms {bad}")
```

Add to the capability-registration path. Raises at startup so a bad preset never ships to recruitment.

### 3.4 Recruitment flow (consistent with spec `2026-04-02-unified-semantic-recruitment-design.md`)

1. Daimonion CPAL forms an utterance, producing a pre-speech impingement with narrative like "register: intimate, context: operator present, grounded".
2. `AffordancePipeline.select()` scores voice-related capabilities. `voice.intimate-close` preset's affordance description (embedded in Qdrant `affordances` collection) scores high cosine.
3. Pipeline returns `voice_plugin_chain.intimate-close` + `vocal_chain.intimate-close` (hardware analog).
4. `VoicePluginChainCapability.activate_from_impingement(impingement)` reads the preset dims, sets Carla plugin params via OSC.
5. `VocalChainCapability.activate_from_impingement(impingement)` sends MIDI CCs to Evil Pet + S-4.
6. On TTS synthesis, the audio flows through the already-parametrized chain.
7. Decay timer ticks (existing `decay()` method) gradually returns levels to 0 over ~50s unless re-impinged.

Key property: **expression-time cost of recruitment is zero** — the plugin/hardware chain is always audio-live; only control values change. No subprocess spawns, no hot-reload, no audio dropouts.

---

## 4. Self-modulation model

### 4.1 Signal inventory (what can drive modulation)

Read from code:

| Source                                                            | Signal                               | Type       | Range     |
|-------------------------------------------------------------------|--------------------------------------|------------|-----------|
| `SystemStimmung.health`                                           | infrastructure health (0 good, 1 bad) | continuous | [0, 1]   |
| `SystemStimmung.error_rate`                                       | LLM / backend error rate             | continuous | [0, 1]    |
| `SystemStimmung.grounding_quality`                                | epistemic grounding                  | continuous | [0, 1]    |
| `SystemStimmung.exploration_deficit`                              | boredom / seeking pressure           | continuous | [0, 1]    |
| `SystemStimmung.audience_engagement`                              | chat liveness                        | continuous | [0, 1]    |
| `SystemStimmung.operator_stress`                                  | biometric stress                     | continuous | [0, 1]    |
| `SystemStimmung.operator_energy`                                  | biometric energy                     | continuous | [0, 1]    |
| `SystemStimmung.physiological_coherence`                          | HRV coherence                        | continuous | [0, 1]    |
| `Stance` (overall)                                                | {NOMINAL, DEGRADED, SEEKING, FORTRESS} | enum      | 4-valued  |
| `Impingement.strength`                                            | salience of current impingement      | continuous | [0, 1]    |
| `Impingement.source`                                              | provenance (stimmung, dmn, operator.sidechat, …) | categorical | ≈20 |
| DMN evaluative tick dimensions (intensity, coherence, tension, …) | 9-dim first-person evaluation        | continuous | [0, 1]    |
| Phase 7 POSTURE                                                   | register {TEXTMODE, ANALYTICAL, INTIMATE, DIRECTORIAL, …} | enum | 8 |
| Director stance (`twitch_director.py`)                            | foreground / backgrounded            | binary     | {0,1}     |
| `destination_channel`                                             | LIVESTREAM / PRIVATE                 | enum       | 2-valued  |

### 4.2 Signal → dimension mapping

Format: `signal` → `dimension` via `function`, with `decay_rate` and `hysteresis` notes.

1. `stimmung.exploration_deficit` → `voice.diffusion`
   - Linear: `level = clamp(0, 1, deficit - 0.3)`. Hysteresis: 3-tick (matches stance SEEKING hysteresis).
   - Decay: 0.02/s (existing default).
   - Rationale: high boredom recruits more granular, ambient voice texture. Signal-honest: boredom literally has no outward effect until it tips the system into SEEKING, and then the voice *sounds* like the system is reaching further. No claim about what Hapax "feels".

2. `stimmung.grounding_quality` → `voice.coherence`
   - Sigmoid: `level = sigmoid(-(gq - 0.5) * 4)`. Inverted: low grounding → high modulation (voice gets less coherent), high grounding → voice close to neutral.
   - Decay: 0.01/s (slow — grounding is slow to shift, voice should track).

3. `stimmung.error_rate` → `voice.degradation`
   - Threshold + ramp: `level = 0 if err<0.3 else (err-0.3)/0.7`.
   - Hysteresis: 2-tick minimum at threshold to avoid one-spike degradation.
   - Rationale: voice actually degrades (bitcrush, saturation) when the system is degrading. Signal-honest.

4. `stimmung.operator_stress` → `voice.depth`, `voice.intensity` (inverted)
   - Depth: `level = max(0, stress - 0.4) * 1.5` — high operator stress → voice recedes into more space, quieter presence. Less in your face.
   - Intensity: multiplicative damper, `intensity *= (1 - stress * 0.5)`.
   - Decay: 0.005/s (biometrics move slowly).

5. `Impingement.strength` on the current utterance → `voice.intensity`
   - Linear direct: `level = strength * utterance_scale`. Per-utterance, no decay — next utterance fully overrides.
   - Rationale: a very salient impingement produces a more present delivery.

6. `Stance` (overall) → preset floor
   - Table lookup:
     - NOMINAL → `voice.baseline-dry` preset as floor.
     - SEEKING → `voice.exploration-seeking`.
     - DEGRADED → `voice.degraded-partial-failure`.
     - FORTRESS → `voice.baseline-dry` with all mod dampers at 0.3× (voice stays simple for broadcast safety).
   - Presets apply as *floors* — impingement-recruited deltas can raise individual dims higher but not below the stance floor. Implementation: `level = max(stance_floor[dim], recruited_level)`.

7. `POSTURE` (register) → preset selection
   - `TEXTMODE` → skip voice plugin entirely (no TTS generally in TEXTMODE).
   - `INTIMATE` → `voice.intimate-close` preset.
   - `ANALYTICAL` → `voice.baseline-dry` preset.
   - `DIRECTORIAL` → `voice.stream-foreground-authoritative`.
   - Register changes are discrete events; on transition, fade from old preset to new over 1.0 s.

8. `destination_channel` → spectral + diffusion deltas
   - PRIVATE → `voice.sidechat-private` additive (lower intensity, tighter diffusion).
   - LIVESTREAM → no delta (baseline).

9. DMN `dimensions.intensity` → `voice.intensity` (additive)
   - `level += dmn_intensity * 0.3`. Capped at 1.0.
   - The DMN already produces a 9-dim evaluation every tick; of those, intensity/coherence/tension/depth map 1:1 to vocal chain dimensions. Give each a 0.3× weight and additive blend into the stimmung-derived floor.

### 4.3 Math conventions (all dimensions)

- All dimension levels in `[0.0, 1.0]`.
- Aggregation: `level(dim) = clamp(0, 1, stance_floor + Σ weight_k * signal_k)` where weights are per-signal constants.
- Hysteresis: if `|level_now - level_prev| < 0.03`, hold `level_prev` (damps jitter from stimmung tick noise).
- Decay: per-dim `decay_rate` applied every `_vocal_chain.decay(elapsed_s)` tick. Already implemented in `vocal_chain.py`; extend to `voice_plugin_chain.py` verbatim.
- Hold: after an impingement-driven activation, hold the activated level for `hold_s = 2 + 3 * impingement.strength` seconds before decay starts. Rationale: a salient event should linger in the voice across at least one full utterance.

### 4.4 Signal honesty audit

For each dimension, verify it is **tracking** an internal signal, not **performing** an affective state. Checklist:

- Can this dimension's level go up while the "equivalent emotion" is absent? (If yes, it's not performing.)
  - Example: `voice.intensity` rises with `impingement.strength` regardless of "mood". A salient question from operator raises intensity — doesn't mean Hapax is "happy" or "energetic".
- Can this dimension go to 0 during a notional positive event?
  - Example: `voice.depth` has no reason to go up on a "cheerful moment" — because depth tracks space/distance/stress, not cheer. Correct.
- Does the preset documentation name feelings?
  - Reject `voice.happy`, accept `voice.intimate-close` (describes physical register, not affect).

Run this audit on any new preset or dimension before merging.

---

## 5. Failure modes + safeguards

### 5.1 Latency budget

- Kokoro CPU synth: measured around 150-250 ms first-sample. This is unchanged.
- Plugin chain (Track B): LSP plugins + Airwindows, 7-8 in series. Each adds ≤ 2 ms. Total plugin chain ≤ 15 ms.
- Hardware loop (Track A): 24c USB round trip is ~5 ms at 128-frame buffer + Eurorack analog is sub-ms. Total ≤ 10 ms.
- Hybrid (Track C): software pre + hardware + software post ≈ 25 ms.

Against the ~300 ms voice response window: even Track C fits. The response window is dominated by STT + LLM, not post-TTS signal processing. No compromise.

### 5.2 Feedback loops (CRITICAL)

**Scenario:** Hapax's modulated voice comes out of the monitor, is heard by the Cortado contact mic (remember Cortado is on Input 2 of the 24c — same interface that outputs the voice). The contact mic drives `stimmung.desk_active` and feeds into the presence engine. In theory, a very loud Hapax could keep `desk_active` pinned and keep modulation level high, which makes the voice louder or more characterful, which…

**Design the damper:**

- The Cortado is bandpass-ish focused on sub-500 Hz (physical mechanical bumps). It does not readily pick up monitor playback — it's a contact transducer on the desk surface. Empirically, operator confirmed contact mic has low crosstalk. Low risk.
- Belt+suspenders: add a gate on `stimmung.exploration_deficit → voice.diffusion` modulation: **do not modulate voice in a way that increases the signal driving the presence engine beyond a cap.** Concretely: subtract the last 30 s of Hapax TTS activity from `stimmung.desk_active` in the presence engine *if* the contact mic energy correlates with TTS waveform.
- Additional: add a hard cap — no single dimension may exceed 0.85 at any time, period. Prevents runaway even if a feedback loop is accidentally created.
- AEC on operator mic already eats the Hapax TTS from Yeti; so the only residual feedback vector is contact mic → stimmung, which the cap above covers.

### 5.3 Plugin crashes

- Carla supervises plugins. On individual plugin crash, Carla bypasses that slot (audio passes through), logs, and continues. This is the default behavior.
- If Carla itself dies: new systemd user unit `hapax-voice-plugin-host.service` with `Restart=always`, `RestartSec=2`. PipeWire's filter-chain-based fallback path auto-reconnects when Carla's JACK ports reappear. During the outage, `hapax-voice-fx-capture` would need an always-on passthrough source as the default — provided by keeping a stripped-down builtin filter-chain always loaded, with Carla as a *secondary* processing stage routed via loopback. Operator hears raw Kokoro through the minimal EQ while Carla restarts.
- Equivalent on Track A: Evil Pet power loss → no audio. Preventer: a WirePlumber rule that monitors Evil Pet presence (via MIDI keepalive — periodically query Evil Pet's firmware version over SysEx, fall to a software-only path if no reply within 2 s). On fallback, audio passes through a minimal Carla chain and skips the hardware loop.

### 5.4 Hardware failure

- Evil Pet power pulled mid-utterance: silence. Operator's first reaction would be panic. Mitigate with a wet/dry mix approach: run a passive splitter or a 24c-internal monitor mix that guarantees a dry voice path is always bussed to the broadcast, and Evil Pet is a parallel "wet" bus that mixes in. On Evil Pet outage the wet send goes to silence but the dry path remains. This is a studio-standard parallel processing topology and is cleaner than the strict serial loop.
- Recommended physical topology update: dry-wet parallel instead of strict serial. Requires a Y-split on 24c MAIN OUT and a summing return strip on 24c. Eurorack-native: use a simple passive mult + a sum mixer module. Adds hardware but survives dropouts.

### 5.5 Safety gate compliance

`shared/speech_safety.py` gates run **pre-TTS** (on the text that will be spoken). Modulation is post-TTS (on waveform). No interaction. Safety gate remains authoritative; modulation cannot make a safety-blocked utterance reach the stream, because the utterance never synthesizes.

Nevertheless, add a regression test: a blocked utterance must produce zero signal at the `hapax-livestream` sink monitor. Can be verified by a PipeWire tap + RMS check in CI (uses the `pw-cat --record @MONITOR@` pattern from the existing audio-topology-check.sh).

### 5.6 Monetization safety

Extreme modulation states (`voice.degraded-partial-failure` with degradation > 0.7) produce intentionally broken audio. Broadcast compliance (YouTube music policies, PeerTube ToS) doesn't distinguish modulated speech from distorted music, so this is fine. But: the spectral-color dimension at extremes could resemble mastered-music patterns a platform fingerprinter might miscategorize. Operator hasn't flagged this; leave for stream ops triage if it becomes a problem.

---

## 6. Implementation plan outline

**Phase 0 — close the obvious gap (no new work, just make existing code real).** MIDI wiring: set `midi_output_port: "Studio 24c MIDI 1"` in config. Wire `VocalChainCapability.activate_from_impingement()` into the impingement consumer loop per the claim in `RESEARCH-STATE.md § Gap 3`. Add a periodic `decay()` call. Tests: assert `mido.open_output` called with explicit 24c name; assert `send_cc` called for DMN impingements carrying dimensions. 1 PR.

**Phase 1 (recommended MVP) — Track A minimal hardware loop without return.** Replace the static builtin EQ in `voice-fx-chain.conf` with a pass-through sink. Cable Kokoro → 24c MAIN OUT L → Evil Pet input. Evil Pet's audio *does not yet return to the stream* — it plays through Evil Pet's own output into the operator's local monitor. This lets MIDI modulation become audible immediately, on an analog monitor, while the livestream egress is unchanged. Minimum PR: reconfigure PipeWire, cable, and flip one env var. **This produces immediate audible improvement the moment it ships.** No software plugin host yet.

**Phase 2 — Track A full: close the return loop.** Add 24c input return path (requires hardware decision: free Input 2 for voice return, or add a small submixer / Eurorack summing module). Add `hapax-voice-return.conf` exposing the return as a PipeWire source. Reroute `hapax-livestream` and `hapax-private` to consume from the return. Remove the direct `hapax-voice-fx-capture → 24c` output. Test: a Hapax utterance with `vocal_chain.intensity=0.8` impingement produces audibly different broadcast output.

**Phase 3 — Software LV2 chain (Track B foundation).** Add `hapax-voice-plugin-host.service` running Carla headless. Register a minimal LV2 chain: gate → 16-band EQ → compressor → limiter. Implement `VoicePluginChainCapability` with three dimensions (`intensity`, `depth`, `degradation`) mapped to 3-4 LV2 ports. Wire into affordance pipeline with three capability records + a preset registry + red-team filter. This phase adds software effects as a parallel recruitment target, not replacing Phase 2. Ships as a standalone improvement.

**Phase 4 — Hybrid (Track C): split pre-colour / post-colour.** Route Kokoro → Carla pre → 24c → hardware → 24c return → Carla post → livestream. Full 9-dim mapping, all seven proposed presets live. Stance-based preset floors. Self-modulation model §4.2 fully active.

**Phase 5 — Feedback damper, fail-safe, dry-wet parallel.** Add the contact-mic correlation subtraction, MIDI-based Evil Pet keepalive, passive dry path, dimension caps. Regression tests for safety-gate compliance. Observability metrics (Prometheus gauges for each active dim level, TTS → modulation latency histogram).

**Phase 6 — Preset library and audition mode.** Let the operator audition any preset without streaming via a CLI (`hapax-voice-audition <preset>`). Export / import preset bundles. Preset naming guardrails enforced in CI.

Each phase ships independently — if we stop after Phase 1, Hapax has audibly modulated voice and MIDI-driven character. Phase 2+ are enhancements.

---

## 7. Recommendation

**Phase 1 = Track A minimal (hardware loop without return, MIDI live).** Justification:

- **Zero net-new software.** Operator owns Evil Pet + S-4 + 24c + cables. Kokoro + pw-cat exist. The only code change is setting `midi_output_port` and wiring `activate_from_impingement` — the latter is already claimed done in RESEARCH-STATE.md, so this PR makes the claim real.
- **The fastest path to an audible win.** On the operator's local monitor, within minutes of the PR merging, Hapax's voice will start reflecting impingement state through hardware character. That's what the operator asked for. No VST install required.
- **No regression risk for livestream.** Phase 1 leaves the livestream path untouched — it still plays dry Kokoro through the 24c main out. The Evil Pet branch is parallel/monitor-only until Phase 2 closes the return.
- **Buys us time to make Track B/C engineering decisions.** Phase 2 requires a hardware decision (free Input 2 vs. submixer), which takes physical inventory. Phase 3 requires a Carla systemd unit. Neither blocks Phase 1.
- **Matches the operator's direct statement:** "We have MIDI capabilities and an Endorphin.es Evil Pet → Torso S-4 that could be utilized as well or instead." Track A says "use what we have, now." Track B/C say "add software for later."

**What to NOT do in Phase 1:** do not add Carla, do not rewrite the PipeWire config beyond removing the static EQ stage, do not touch the affordance pipeline, do not introduce LV2ParamMapping. The 9-dim `vocal_chain` code already exists and is correct — just make it run. Once it runs and the operator hears it, the shape of Phase 2/3/4 will be clearer and driven by lived feedback rather than spec guesses.

**Track C (hybrid) remains the target endstate** — it's the architecturally cleanest and gives the fullest vocabulary for self-modulation. But you don't ship an endstate in one PR. Ship Phase 1 this week, listen, then plan Phase 2.

---

## Open questions (for next research pass)

- Q1. Can 24c provide a line-level return without freeing Input 2 (Cortado)? Needs physical inspection of the 24c rear panel for separate line inputs vs. combo-only.
- Q2. Does Torso S-4 firmware support routing external audio through its FX rack in real time, or is its FX limited to its internal sample engine? Needs S-4 manual / firmware version check.
- Q3. Does the `MIDI Dispatch MIDI 1` port (client 56, card 10) correspond to Evil Pet's USB MIDI or to a separate USB MIDI dongle? `lsusb` inspection needed. Affects whether channel-0 CCs from `vocal_chain` reach Evil Pet via the dongle or must go via 24c DIN MIDI OUT.
- Q4. Does Kokoro's 24 kHz output cause audible artifacts when hardware-processed at 48 kHz? The pw-cat resampler handles it; whether Evil Pet's input ADC notices is an audition question.
- Q5. Is there a working budget for Carla (Phase 3+) given the CPU is already running Kokoro + daimonion + imagination + compositor? `cpu-audit` pre-merge will answer this.
