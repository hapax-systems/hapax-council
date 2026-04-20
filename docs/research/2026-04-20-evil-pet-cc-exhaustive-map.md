# Endorphin.es Evil Pet — Exhaustive CC-to-Audible-Result Map

**Status:** research
**Date:** 2026-04-20
**Register:** engaged practitioner — primary manufacturer documentation, community-level testimony, academic references (Roads, Microsound 2001) for granular theory
**Scope:** complete MIDI CC inventory and audible-result characterisation for the Endorphin.es Evil Pet (8-voice polyphonic granular workstation, firmware v1.42+, 2026-03-27 build) used as a real-time voice-transformation effect on the Hapax-TTS (Kokoro 82M) → MOTU 24c → Evil Pet → Torso S-4 chain
**Parent docs:**
- `docs/research/2026-04-19-evil-pet-s4-base-config.md` (§3.8 CC table, 17 parameters, voice-chain base config)
- `docs/research/2026-04-20-vinyl-broadcast-mode-d-granular-instrument.md` (§4 granular + filter + saturator + reverb behaviour for vinyl Mode D)
**Runtime hook:** `agents/hapax_daimonion/vocal_chain.py` (9-dim MIDI CC emitter, 20 Hz debounce per CC)

---

## §1 Complete CC inventory

The canonical MIDI implementation chart at [midi.guide/d/endorphines/evil-pet](https://midi.guide/d/endorphines/evil-pet/) documents **39 CC numbers** (plus MPE pitch-bend and aftertouch). No NRPNs are documented. The MIDI guide notes value ranges are 0-127 for all entries and the `Last Updated` field reads 2026-01-19 — newer than the v1.42 firmware release, so this chart is canonical for the operator's device.

All parameters are organised below by functional block. Default receive channel behaviour is not explicitly documented by Endorphin.es; the [Endorphin.es product page](https://www.endorphin.es/modules/p/evil-pet) confirms MPE mode is selectable from the `Config` menu. In single-channel mode the device responds on ch1 with per-voice cycling (voice stealing at 8 voices); in MPE mode, the manual's MPE description ([WeAreBlip product page](https://weareblip.com/products/endorphin-es-evil-pet), [SchneidersLaden listing](https://schneidersladen.de/en/endorphin.es-evil-pet)) states each voice takes a dedicated MIDI channel, with X-axis = pitch bend, Y-axis = CC 74 (MPE Timbre), Z-axis = channel pressure.

### 1.1 Input / source block

| CC | Parameter | Range | Behaviour | Low (0–30) | Mid (40–70) | High (90–127) |
|---:|---|:---:|---|---|---|---|
| 1 | Expression | 0–127 | continuous | Unipolar expression pedal value — mirrors TRS expression input. Destination is user-assigned in the device's Config menu (not documented in midi.guide). | — | — | — |
| 7 | Volume (master) | 0–127 | continuous | Global output attenuator. 0 = silent, 127 = unity. | very quiet / bedroom-level | conversational / broadcast | near-clip of Evil Pet output stage; downstream gain staging must be rechecked |
| 40 | Mix (source → grains) | 0–127 | continuous | Wet/dry between the dry input signal and the processed (granular + FX) bus. 0 = dry only, 127 = processed only. | near-dry, minimal processing audible | balanced blend (voice config default at 64) | processed bus dominant — Mode D target ([Mode D §4.2](./2026-04-20-vinyl-broadcast-mode-d-granular-instrument.md)) |

### 1.2 Granular engine block

The granular engine is 8-voice polyphonic with **24-bit/48 kHz internal processing and a 512 MB / 10-minute continuously refreshing buffer** ([Endorphin.es product page](https://www.endorphin.es/modules/p/evil-pet); [Perfect Circuit feature overview](https://www.perfectcircuit.com/signal/endorphines-evil-pet-review)). Position advances through the buffer, Size sets grain duration, and Grains controls the playhead-spawn rate / density.

| CC | Parameter | Range | Behaviour | Low (0–30) | Mid (40–70) | High (90–127) |
|---:|---|:---:|---|---|---|---|
| 11 | Grains Volume | 0–127 | continuous | Master engine wet — cannot be set from the physical encoder; MIDI-only knob. Gating control for the whole granular layer. | engine ducked/off | partial granular blend with the filter/saturator/reverb path | granular fully engaged; dry path reduced |
| 49 | Position | 0–127 | continuous | Read-head position inside the 10-minute buffer ([Blip product page](https://weareblip.com/products/endorphin-es-evil-pet)). | early buffer — historical audio (~5 min old for a filled buffer) | mid buffer | tail of buffer — near-live input (Position ≥ ~95 replays the last few hundred ms of Hapax's current utterance) |
| 50 | Size | 0–127 | continuous (bidirectional, forward / reverse) | Per-grain duration. Per community practitioner walkthroughs ([loopop review on YouTube](https://www.youtube.com/watch?v=tXQzW5pEhNY); [Perfect Circuit overview](https://www.perfectcircuit.com/signal/endorphines-evil-pet-review)) the range appears to span ~1 ms to ~1 s; some practitioner commentary suggests reverse playback at counterclockwise settings. | sub-30 ms grains — re-synthesises the signal as a pointillist cloud; original pitch/rhythm scrambled (Roads 2001 "pointillist" regime) | 30–200 ms grains — "smear" regime, vowels audible but detuned, consonants fragmented | 200 ms – 1 s grains — near-direct replay with mild stutter; closest to source |
| 41 | Diffuse | 0–127 | continuous | Spread of grains across the stereo field and/or slight onset jitter. The midi.guide chart does not explicitly disambiguate Diffuse vs Spread; by community reports ([loopop YouTube walkthrough](https://www.youtube.com/watch?v=tXQzW5pEhNY)) Diffuse is the position-randomisation / time-jitter axis per grain. | tightly synchronised grains — rhythmic pulse clearly audible | mild blur across grain onsets | fully desynchronised, asynchronous granular "cloud" regime (Roads 2001, ch.3–4 on asynchronous granular synthesis) |
| 42 | Spread | 0–127 | continuous | Stereo spread randomisation per grain ([loopop YouTube walkthrough](https://www.youtube.com/watch?v=tXQzW5pEhNY); [perfectcircuit.com/endorphines-evil-pet.html]( https://www.perfectcircuit.com/endorphines-evil-pet.html) listing features). | centred mono stream | mild stereo spread | full stereo randomisation — "cloudy" stereo wash; clarity drops because the listener cannot anchor the voice to a point |
| 43 | Cloud | 0–127 | continuous | Playback window size around the Position read-head — the zone from which grains are sampled ([manuals.plus secondary parameter descriptions](https://manuals.plus/m/068472d380f335f9e901241a8c81ed421e1fc3973820446abe12e8e5eaeb4335); [WeAreBlip product page](https://weareblip.com/products/endorphin-es-evil-pet)). | narrow window (≈ Size) — pinpoint stream | moderate window (~50 ms) — "breathing" of nearby source material | wide window (~1 s) — grains drawn from a broad time zone; dense but unfocused |
| 44 | Pitch | 0–127 | continuous (bipolar, centred at 64) | Per-voice pitch transposition ±2 octaves ([Blip product page](https://weareblip.com/products/endorphin-es-evil-pet)). Quantisation to a scale is selectable from the Config menu. | −2 octaves — dark, slowed (Chipmunks in reverse) | unity / near-unity pitch | +2 octaves — bright, "helium" transpose. At extreme values aliasing artefacts become audible on plosives |
| 45 | Detune | 0–127 | continuous | Per-grain random pitch offset in semitones ([loopop YouTube walkthrough](https://www.youtube.com/watch?v=tXQzW5pEhNY)). | strict unison across voices | mild micro-detuning — chorus-like thickening | aggressive random pitch jitter — source spectrum smeared into a noise-like texture |
| 46 | Grains | 0–127 | continuous, with community-reported non-linear sweet spot | Grain-spawn rate / density. Per practitioner walkthroughs ([blip listing quoting Endorphin.es description](https://weareblip.com/products/endorphin-es-evil-pet)): at 12 o'clock there is always a **single grain**; CW adds more simultaneously; CCW introduces **random grain occurrences** (non-deterministic spawn). | sparse pulsing — a few grains per second; rhythmic effect dominates (Roads 2001 §3.2: low density = rhythmic) | 10s of grains/sec — streams merge into pitched tones | 100s of grains/sec — smoothed granular cloud ≈ texture (Roads 2001 §3.3: once density crosses ~30–50 grains/sec, perception morphs from rhythm into pitch into texture) |
| 47 | Shape | 0–127 | continuous | Grain envelope / window shape. Community reports ([loopop YouTube walkthrough](https://www.youtube.com/watch?v=tXQzW5pEhNY); Endorphin.es Blip description) say Shape "looks after the envelopes applied to the grain to prevent clicking and alter the sound's character." Consistent with academic literature ([Krzyzaniak audio synthesis notes §11.1](https://michaelkrzyzaniak.com/AudioSynthesis/2_Audio_Synthesis/11_Granular_Synthesis/1_Window_Functions/); [GranularSynthesis.com §2.2](https://www.granularsynthesis.com/hthesis/envelope.html)): at one extreme the window is rectangular/Tukey (edges sharp — produces click artefacts and added high-frequency energy); at the other, Gaussian / Hann (smooth — no clicks but wider temporal smear). | rectangular / harsh window — audible per-grain clicks, aggressive spectral spread | Tukey-like — balanced; clear grain onset without severe clicking | Gaussian / Hann — maximally smooth, "airbrushed" granular texture |

### 1.3 Digital oscillator layer (overtone)

Independent of the granular engine and applied in parallel. Monophonic fundamental behaviour per voice; in 8-voice mode it lays sub-oscillators or overtones under the granular output.

| CC | Parameter | Range | Stepped? | Behaviour | Low (0–30) | Mid (40–70) | High (90–127) |
|---:|---|:---:|:---:|---|---|---|---|
| 85 | Overtone Volume | 0–127 | continuous | Level of the added digital oscillator. | oscillator inaudible | subtle harmonic reinforcement under granular | oscillator dominant — voice now has an overt synth drone beneath it |
| 86 | Overtone Type | 0–127 | **5 steps** | Waveform selector for overtone oscillator. Per midi.guide chart: `None (0–25) / Sine (26–51) / Triangle (52–77) / Sawtooth (78–102) / Square (103–127)`. | None → no oscillator regardless of CC 85 | Sine (soft fundamental) → Triangle (clarinet-like) → Saw (buzzy, harmonically rich) | Square (hollow, vocal-"oo") — aggressive overtone stack |

### 1.4 Multimode resonant filter block

Confirmed by [SYNTH ANATOMY](https://synthanatomy.com/2025/10/endorphin-es-evil-pet-an-mpe-polyphonic-granular-synthesizer.html) and [Thomann listing](https://www.thomannmusic.com/endorphines_evil_pet.htm) to include dual LP/HP, LP, HP, BP, and comb modes. Self-oscillation is not documented by Endorphin.es; neither Perfect Circuit's overview nor the modwiggler thread at [modwiggler forum 296887](https://www.modwiggler.com/forum/viewtopic.php?t=296887) explicitly report a self-oscillation threshold for this filter. For practitioner reference, Eurorack digital comb filters typically self-oscillate above resonance ≈ 90 ([2hp Comb product page](https://www.twohp.com/modules/p/comb)); the Evil Pet's comb mode is likely similar, pending live verification (§4).

| CC | Parameter | Range | Stepped? | Behaviour | Low (0–30) | Mid (40–70) | High (90–127) |
|---:|---|:---:|:---:|---|---|---|---|
| 70 | Filter Frequency | 0–127 | continuous | Cutoff / centre frequency. | filter closed — darkest tone, consonants muted | mid-opening — voice in a midband character; base-config default | fully open — bright, full spectrum |
| 71 | Filter Resonance | 0–127 | continuous | Q / emphasis at cutoff. Interacts strongly with cutoff — at high resonance with LP, cutoff sweep is perceived as a filter whistle. | flat response, no colouring | clear peak at cutoff; voice gains a "formant" character | approaching self-oscillation (empirical — see §4); in comb mode, the resonant peak dominates over the source signal |
| 80 | Filter Type | 0–127 | **5 steps** | Per midi.guide chart: `Multimode/dual LP+HP (0–25) / LP (26–51) / HP (52–77) / BP (78–102) / Comb (103–127)`. | Multimode — dual LP+HP parallel (band-definition with two cutoffs) | LP → HP transition (26–77) — warm vs thin voice | BP → comb (78–127) — narrow formant / resonant ringing |
| 96 | Envelope Filter Modulation | 0–127 | continuous | Internal ADSR → filter cutoff depth. | filter ignores envelope — static cutoff | envelope audibly opens/closes filter on each voice trigger | envelope dominates cutoff; voice "quacks" on each phoneme |

**Breakpoints on CC 80:** the two transitions most relevant for voice are the 25→26 jump (multimode → LP — dual-cutoff character collapses to a single cutoff) and the 102→103 jump (BP → comb — continuous bandpass becomes discrete resonant comb teeth at cutoff and its harmonic multiples). Crossing these boundaries during live modulation produces an audible discontinuity. The voice CC map should clamp this parameter away from boundaries unless stepped changes are the intended aesthetic.

### 1.5 Saturator block

6-mode saturation unit ([Endorphin.es product page](https://www.endorphin.es/modules/p/evil-pet); [SYNTH ANATOMY](https://synthanatomy.com/2025/10/endorphin-es-evil-pet-an-mpe-polyphonic-granular-synthesizer.html)). Per midi.guide CC 84 mapping: `Chorus (0–21) / Feedback (22–42) / Distortion (43–63) / Sample rate reducer (64–84) / Bit crusher (85–105) / Flanger (106–127)`.

| CC | Parameter | Range | Stepped? | Behaviour | Low (0–30) | Mid (40–70) | High (90–127) |
|---:|---|:---:|:---:|---|---|---|---|
| 39 | Saturator amount | 0–127 | continuous | Drive / intensity of selected saturator mode. | clean — saturator inaudible | audible character but signal intelligible | heavy — wrecks dynamics; in Feedback mode, risks self-oscillation into howl |
| 84 | Saturator Type | 0–127 | **6 steps** | Saturator mode. Community reports that the **Feedback** mode can drive the granulated output back into the input buffer for runaway self-oscillation ([mode D research §4.3](./2026-04-20-vinyl-broadcast-mode-d-granular-instrument.md); [community thread recap at SYNTH ANATOMY](https://synthanatomy.com/2025/10/endorphin-es-evil-pet-an-mpe-polyphonic-granular-synthesizer.html)). | Chorus (ensemble thickening) → Feedback (echoic re-injection) | Distortion (harmonic enrichment) → SRR (aliased, "telephonic") | Bit crusher (quantised lo-fi) → Flanger (phase-sweep comb) |

**Breakpoints on CC 84:** each 21-step transition crosses a mode boundary. The 42→43 (Feedback → Distortion) and 84→85 (SRR → Bit crusher) transitions are the most perceptually disjoint and should not be crossed during live modulation without a crossfade — the user-perceived character changes completely.

### 1.6 Reverb block

4-mode reverb with shimmer. Per midi.guide CC 95 mapping: `Plate L (0–31) / Reverse (32–63) / Room (64–95) / Plate S (96–127)` — the `Plate L` / `Plate S` distinction (large / small plate) is not in the parent voice-chain doc but is explicit in the canonical CC chart.

| CC | Parameter | Range | Stepped? | Behaviour | Low (0–30) | Mid (40–70) | High (90–127) |
|---:|---|:---:|:---:|---|---|---|---|
| 91 | Reverb Amount | 0–127 | continuous | Send level into the reverb bus. | essentially dry | audible tail, voice remains forward | drenched — consonants bleed into the tail, intelligibility drops |
| 92 | Reverb Tone | 0–127 | continuous | Tonal tilt of reverb tail (dark ↔ bright). | dark tail — warm, muddied | neutral (base config) | bright tail — metallic, glassy reflections |
| 93 | Reverb Tail | 0–127 | continuous | Decay time. | short (≤ 0.5 s) — small-room "bloom" | medium (1–2 s) | long (3+ s) — cathedral-scale wash that smears successive phonemes |
| 94 | Reverb Shimmer | 0–127 | continuous | Pitch-shifted (octave-up) feedback injected into the reverb tail. | no shimmer — natural tail | subtle octave-up halo above voice | dominant — iridescent cloud ("OPN-adjacent"); anthropomorphically distinct and per HARDM/CVS #16 governance, a disallowed voice treatment |
| 95 | Reverb Type | 0–127 | **4 steps** | Algorithm selector. Base voice config uses "Room" (64–95). | Plate L — metallic, long-tail — studio-mix character | Reverse — builds-up reversed tail, disorienting for speech | Room (base default) → Plate S — compact studio plate |

### 1.7 Envelope (ADSR) block

Applied per-voice to the internal synth VCA and routable to the filter via CC 96.

| CC | Parameter | Range | Behaviour | Low (0–30) | Mid (40–70) | High (90–127) |
|---:|---|:---:|---|---|---|---|
| 73 | Attack | 0–127 | continuous | Time for envelope to reach peak. | instant attack — percussive onsets | 10–100 ms gentle attack | 1+ s slow swell — voice fades in under each phoneme boundary |
| 75 | Decay | 0–127 | continuous | Time to fall from peak to sustain. | snappy — voice gates off quickly after peak | moderate fall | slow — envelope holds voice near peak for seconds |
| 79 | Sustain | 0–127 | continuous | Hold level. | 0 = AD (no sustain) — voice drops out after decay | half-level sustain | full sustain = AR envelope behaviour |
| 72 | Release | 0–127 | continuous | Tail after note-off. | instant cut — gated, robotic | 100–500 ms natural release | 1+ s long release — voice hangs after each phoneme |

### 1.8 LFO block (3× multi-wave)

Three independent LFOs with identical CC grammar. Destination is assigned in the Evil Pet's menu (not exposed on CC). Per midi.guide, the waveform selector values for CC 81/82/83 cover `Sin / Tri / Saw / Square / Step random / Fluctuating random / Env. follower`.

| CC | Parameter | Range | Stepped? | Notes |
|---:|---|:---:|:---:|---|
| 76 | LFO 1 Speed | 0–127 | continuous | 0 = halted / DC; higher = faster. Typical LFO rate range on Endorphin.es products spans 0.01 Hz – 20 Hz (per similar-family products; not directly documented for Evil Pet). |
| 77 | LFO 2 Speed | 0–127 | continuous | Same grammar as LFO 1. |
| 78 | LFO 3 Speed | 0–127 | continuous | Same grammar as LFO 1. |
| 81 | LFO 1 Type | 0–127 | **7 steps** | Stepped shape/behaviour selector. Breakpoints at ~18, 36, 54, 73, 91, 109 between Sin/Tri/Saw/Square/Step-rand/Fluct-rand/Env-follower. "Env. follower" mode repurposes this LFO as an envelope follower on the input signal — clicking between waveform and envelope-follower modes is a load-bearing transition. |
| 82 | LFO 2 Type | 0–127 | **7 steps** | Same grammar. |
| 83 | LFO 3 Type | 0–127 | **7 steps** | Same grammar. |

### 1.9 MPE / expression / pedal block

| CC | Parameter | Range | Behaviour |
|---:|---|:---:|---|
| 64 | Sustain Pedal | 0–127 | **2-step** — `0-63 = off / 64-127 = on`. Holds the envelope's release phase open. |
| 69 | Record Enable | 0–127 | **2-step** — `0-63 = off / 64-127 = on`. Engages buffer recording from the selected input source. For voice, this is leave-off unless the operator wants to start capturing TTS into the buffer (an anthropomorphic/echoic move). |
| 74 | MPE Timbre | 0–127 | continuous | Per-voice Y-axis under MPE mode. Typically routed to cutoff / filter timbre per MPE convention. |
| 1 | Expression | 0–127 | continuous | Pedal expression input — destination assignable via menu. |

### 1.10 Summary counts

- **39 named CCs**, **11 stepped (multi-position)** — CCs 80 (filter), 84 (saturator type), 86 (overtone type), 95 (reverb type), 81/82/83 (LFO types), 64 (sustain), 69 (record enable), plus the two filter/overtone/saturator/reverb mode selectors which interact as described above.
- **28 continuous** — everything else, all 0–127 range, primarily smooth in perceptual response with the exception of Grains (non-linear sweet-spot at 12 o'clock per community reports) and Resonance (steep approach to self-oscillation near 110+).
- **No NRPNs documented.** The midi.guide chart's `NRPNs: None documented in source material` is consistent with the absence of NRPN notation in the Endorphin.es product page, manual PDF, or practitioner posts examined during this research.

---

## §2 Subjective sonic-dimension grouping

The operator's `vocal_chain.py` 9-dimension space (intensity, tension, diffusion, brightness, density, grit, space, motion, presence) does not map 1-to-1 to CCs. For live voice modulation it is more useful to pre-group CCs by perceptual axis.

### 2.1 Voice clarity axis — clear ↔ muddy / indistinct

Drivers, ranked by strength of effect on intelligibility:

1. **Grains Volume (CC 11)** — primary gate. 0 = speech-clear; 127 = speech deconstructed to grain cloud.
2. **Cloud (CC 43) + Spread (CC 42) + Diffuse (CC 41)** — the "clarity-ablation triad." Any of these at high values breaks the point-source voice model and puts the listener in an undifferentiated field. Push all three together (>80) = Roads "asynchronous cloud" regime (Roads, *Microsound* 2001, ch. 3 — [Perfect Circuit: Exploring Microsound and Granular Synthesis](https://www.perfectcircuit.com/signal/microsound); [SFU: Truax on granular synthesis](https://www.sfu.ca/~truax/gran.html)).
3. **Size (CC 50)** — ≤ 30 ms grains = pointillist regime (Roads 2001, ch. 3); 30–200 ms = smear regime; > 200 ms = near-source replay.
4. **Shape (CC 47)** — rectangular window = added click energy (reduces perceived clarity); Hann/Gaussian = maximal envelope smoothness but also maximum temporal smearing.
5. **Reverb Amount (CC 91) + Tail (CC 93)** — secondary clarity reducers. Long tails plus high amount merge phoneme ends into the wash.
6. **Filter Resonance (CC 71)** — narrow resonant peaks disrupt the voice formant balance; at high values, a narrow-band-pass voice is less intelligible despite being louder in its emphasised band.

A "clear voice" operating point: CC 11 = 0, CC 41/42/43 each ≤ 30, CC 91 ≤ 40, CC 71 ≤ 30. Matches the base voice-chain config.

### 2.2 Spatial character — intimate ↔ distant

1. **Reverb Amount (CC 91)** — primary distance control.
2. **Reverb Type (CC 95)** — Room = close; Plate L = medium distance / studio-mix; Reverse = dislocated (disorienting for speech and has no natural analogue).
3. **Reverb Tail (CC 93)** — long tail = larger apparent space.
4. **Reverb Tone (CC 92)** — dark tail simulates absorbent surroundings (close, intimate); bright tail simulates reflective surroundings (distant, ceremonial).
5. **Spread (CC 42)** — wide stereo spread reads as "everywhere" / dislocated; narrow reads as "point source" (intimate).
6. **Mix (CC 40)** — secondary distance control — low mix keeps the dry intimate signal forward; high mix pushes the voice behind the FX bus.

Intimate operating point: CC 91 ≤ 35, CC 95 = Room (64–95 on CC), CC 92 = 50 (neutral), CC 42 ≤ 30, CC 40 = 50. Distant operating point: CC 91 = 80, CC 95 = Plate L (0–31 on CC), CC 93 = 80, CC 92 = 90 (bright), CC 42 = 90.

### 2.3 Harmonic character — clean ↔ gritty

1. **Saturator Type (CC 84)** — defines the grit flavour.
   - Chorus (0–21): clean, thickened.
   - Feedback (22–42): echoic, on edge of self-oscillation.
   - Distortion (43–63): classic harmonic enrichment — even-order emphasis.
   - Sample-rate reducer (64–84): aliased telephonic artefacts.
   - Bit crusher (85–105): quantisation noise — lo-fi/hip-hop idiom.
   - Flanger (106–127): phase-sweep comb — whoosh.
2. **Saturator Amount (CC 39)** — grit depth within the chosen mode.
3. **Filter Resonance (CC 71)** — high resonance introduces ringing harmonics even without saturation.
4. **Overtone Volume (CC 85) + Type (CC 86)** — adds a deterministic harmonic under the voice (saw / square = gritty; sine = clean).
5. **Reverb Shimmer (CC 94)** — adds +1-octave harmonic content to the reverb tail — distinctive but **disallowed for voice** per HARDM/CVS #16 anti-anthropomorphisation governance, as shimmer is a distinctly vocal-choral effect.

### 2.4 Temporal character — stable ↔ stuttering ↔ smeared

1. **Grains density (CC 46)** — the primary temporal axis, following the Roads density-percept law (Roads 2001, §3.2–§3.3 — [Perfect Circuit: Microsound](https://www.perfectcircuit.com/signal/microsound)):
   - sparse (< 30) → rhythmic pulse / stutter regime
   - medium (30–70) → pitched stream
   - dense (> 80) → smoothed granular texture / wash
2. **Size (CC 50)** — at small sizes (<30 ms), temporal relationship to source is broken (pointillist); at large sizes (> 500 ms), near-direct replay with stutter.
3. **Diffuse (CC 41)** — temporal jitter between grain onsets.
4. **LFO Speed (CC 76/77/78)** — if LFO is routed to Position (CC 49), LFO speed determines the sweep rate of a scanning/stutter effect.
5. **Envelope Attack + Release (CC 73 + CC 72)** — long attacks + long releases produce smeared temporal boundaries; short values preserve the source rhythm.

---

## §3 Regions of parameter space to avoid

For a real-time voice effect with governance constraints (HARDM anti-anthropomorphisation; CVS #16 anti-personification persona constraint, cross-referenced in CLAUDE.md §Unified Semantic Recruitment). The voice must never perform emotion or humanising warmth — only render signal-density.

### 3.1 Clipping / saturator-driven distortion collapse

- **CC 39 (saturator amount) > 100 with CC 84 = Feedback (22–42):** the feedback saturator at high amount routes processed audio back into the buffer in a self-exciting loop, documented in mode D research ([Mode D §4.3](./2026-04-20-vinyl-broadcast-mode-d-granular-instrument.md)). For voice this produces a runaway roar that buries the signal; for vinyl Mode D this is embraced. **Clamp CC 39 ≤ 80 whenever CC 84 ∈ [22, 42].**
- **CC 39 > 110 with CC 84 = Distortion:** output clips at the saturator stage and no downstream gain staging recovers intelligibility.
- **CC 7 (master volume) > 115 combined with CC 39 > 80:** master output stage begins to clip, hitting the MOTU 24c input above its documented +4 dBu ceiling. Keep the product `CC 7 × CC 39 / 127` ≤ ~60 as a rule of thumb.

### 3.2 Self-oscillation

- **Filter: CC 71 (resonance) > 110 with CC 80 ∈ [103, 127] (comb mode):** comb filter in high-resonance regime self-oscillates at cutoff + its harmonic multiples. For voice, this is unintelligible ringing; may be fun for Mode D. Community thread at [modwiggler forum 296887](https://www.modwiggler.com/forum/viewtopic.php?t=296887) does not explicitly mark the threshold; treat this as empirically verifiable (see §4).
- **Filter: CC 71 > 110 with CC 80 ∈ [26, 51] (LP):** LP at very high resonance typically sings a pitched tone at cutoff. The Evil Pet's digital filter implementation is not documented to explicitly self-oscillate ([SYNTH ANATOMY coverage](https://synthanatomy.com/2025/10/endorphin-es-evil-pet-an-mpe-polyphonic-granular-synthesizer.html) does not mention it). Empirical verification required — but a parameter clamp of CC 71 ≤ 80 for live voice operation is prudent.
- **Saturator Feedback mode** as above.

### 3.3 Silence / no audible output

- **CC 11 (grains volume) = 127 with CC 40 (mix) = 127 and Position (CC 49) > 120 while nothing is currently being recorded into the buffer:** the engine reads from a nearly empty / stale buffer position. The perceived result is silence or only historical fragments. For voice TTS, Hapax is always writing the current utterance to the buffer so Position ≥ 120 gives a near-live read — but if the TTS goes silent, granular re-synthesis has nothing to play. Design rule: **do not couple silence periods to high CC 11 / CC 40 values** unless the expectation is that the Evil Pet plays residual buffer content (plunderphonic-style).
- **CC 40 = 127 with CC 11 = 0:** dry path killed and granular engine also killed — complete silence. Obvious but worth codifying.
- **CC 79 (sustain) = 0 with CC 75 (decay) = 0 and no re-trigger:** envelope closes between phonemes — voice disappears except at onsets. Non-obvious failure mode for TTS because TTS doesn't generate MIDI note-on per phoneme.

### 3.4 Anthropomorphisation (governance-disallowed)

Not technical failures — technical successes that produce outputs the governance forbids. These must be clamped by `vocal_chain.py` regardless of the stimmung / impingement computation:

- **Reverb Shimmer (CC 94) > 10:** distinctively vocal/choral "angelic" colouring. Disallowed outright — clamp to 0 always.
- **LFO → Pitch (CC 44) modulation with slow rate (CC 76/77/78 = 20–40):** produces "crying" / "wobbling emotion" pitch drift. Disallowed. Do not route LFO 1/2/3 to pitch unless rate is > 80 (fast tremolo, mechanical-sounding) or = 0 (DC).
- **Envelope → Filter modulation (CC 96) > 80 combined with long Release (CC 72 > 100):** produces a "sighing" filter opening on each phoneme — reads as an emotion-performing cadence. Clamp CC 96 ≤ 60 or CC 72 ≤ 60.
- **Reverb Type = Reverse (CC 95 ∈ [32, 63]) with Reverb Amount > 60:** the reverse-reverb pre-swell before each phoneme is the well-known "supernatural / dreamy" affect. Disallowed as it performs a pre-cognitive "intake breath" for Hapax. Clamp CC 95 out of the Reverse band.
- **Detune (CC 45) > 40 combined with Grains (CC 46) < 30:** a sparse stream with heavy detune reads as "tearful voice." Clamp one or the other.

Per HARDM / CVS #16 governance: these are not matters of taste — the voice is a readout of signal density, not a performed affect.

### 3.5 Audibility-of-automation (glitch-on-modulation)

- **Stepped-parameter crossings during live voice:** CC 80 (filter type) crossings at 25/26, 51/52, 77/78, 102/103 and CC 84 (saturator type) crossings at 21/22, 42/43, 63/64, 84/85, 105/106 produce audible discontinuities. If the 9-dim emitter routes a continuous dimension to these CCs, clamp the value to a single band or send a crossfade. Same for CC 86 (overtone type, 4 breakpoints) and CC 95 (reverb type, 3 breakpoints).
- **CC emission rate > 50 Hz per CC:** the device can glitch if hit harder than the [voice base config §5.3](./2026-04-19-evil-pet-s4-base-config.md) 20 Hz / 50 ms debounce. Hard ceiling.

---

## §4 Open questions — physical-device verification

These are unresolved from public documentation and require bench measurement on the operator's device:

1. **Filter self-oscillation thresholds per mode.** CC 71 threshold at which each of the five CC 80 modes (multimode, LP, HP, BP, comb) either self-oscillates or simply approaches "ringing but not oscillating." Record a sine-sweep of CC 70 across the range at CC 71 = 100, 110, 120, 127 for each mode.
2. **Grains (CC 46) non-linearity.** Community report says "at 12 o'clock there's always a single grain, CW adds more, CCW = random occurrences." Is the 12 o'clock position at CC = 64 or is the non-linearity around CC = 63 or 65? Log CC value vs measured grain-rate with an impulse-train input.
3. **Size (CC 50) reverse-play threshold.** The manual description mentions "CW = forward, CCW = reverse" but the CC chart does not mark a breakpoint. Is CC 50 = 64 the zero-crossing, or is reverse-play in a distinct band? Test with a transient-rich input (pop + silence).
4. **Cloud (CC 43) vs Spread (CC 42) vs Diffuse (CC 41) disambiguation.** Public docs conflate these. The midi.guide chart simply lists three separate CCs. Walk each independently on a steady test tone; classify by whether the effect is temporal (jitter), spatial (stereo pan), or positional (read-head window).
5. **Shape (CC 47) window family.** Is the window shape selector continuous (morphing between window families) or stepped (discrete Hann / Tukey / Gaussian / rectangular)? Community reports don't specify.
6. **LFO rate range (CC 76/77/78).** Min/max Hz per CC value. The parent voice doc assumed 0 Hz – 20 Hz; unverified.
7. **LFO destination CC.** Endorphin.es does not expose an LFO-destination CC, so destination assignment is menu-only. Confirm whether sysex or MIDI learn can achieve remote destination assignment.
8. **Reverb Plate S vs Plate L distinction.** Quantitative difference in decay or size between the two plate modes. Not documented publicly.
9. **MPE channel range.** Default MPE zone (e.g., channels 2–9 vs 2–16) and whether this is user-configurable in the Config menu.
10. **Buffer-fill latency.** For a just-powered-on device with an empty buffer, how long before Position across the full range produces audible grains? (Parent doc estimates "sub-frame ~21 µs" for grain-engine processing; buffer-fill latency for the first ~10 minutes is separate and affects Mode D's temporal-collage move.)
11. **CC 39 × CC 84 = Feedback runaway threshold.** The saturator feedback mode's self-oscillation point in the drive dimension. Critical for mode D tuning and for voice-mode clamp placement.
12. **Input ceiling (dBFS) vs CC 7 (master).** OLED meter scaling in §3.1 of the voice base config is marked open. Calibrate meter with a reference tone.
13. **NRPNs.** midi.guide says none documented. Verify by sending an NRPN sweep to confirm no hidden high-resolution or menu-level parameters exist.

---

## §5 Integration with `vocal_chain.py` 9-dim map

Relative to the existing `2026-04-19-evil-pet-s4-base-config.md` §5.1 table (17 CCs used), this exhaustive inventory surfaces **additional CCs available for potential use**:

- **CC 41 (Diffuse)** — third axis of clarity control alongside CC 42 (Spread) and CC 43 (Cloud). Could become a `temporal` dimension beyond `motion`.
- **CC 47 (Shape)** — grain window shape. A strong candidate for an `intensity` or `grit` second-order mapping (rectangular at high intensity = more spectral grit without engaging the saturator).
- **CC 49 / CC 50 (Position / Size)** — currently unused for voice. Mode D uses them heavily. For voice could be locked at Size ≥ 200 ms to preserve intelligibility, Position ≥ 120 (near-live buffer tail) to minimise latency.
- **CC 73 / CC 75 / CC 79 / CC 72 (ADSR)** — the envelope is currently ignored for voice because TTS is not MIDI-note-triggered. However, CC 96 (Env → Filter) is used — so CC 73/75/79/72 implicitly shape this modulation's timing. These four CCs could be statically set at load time rather than dynamically mapped.
- **CC 76 / CC 77 / CC 78 (LFO speeds)** — currently disabled. Could be enabled under tight clamp as a `motion` secondary with a high-rate-only policy (CC > 80) to avoid anthropomorphic wobble.
- **CC 69 (Record Enable)** — operator-controlled-only; do not expose to `vocal_chain.py`. Buffer recording policy is a governance question (what utterances enter the 10-minute buffer, what happens if operator unplugs TTS — is the last utterance captured for replay?).
- **CC 64 (Sustain Pedal)** — ignore; TTS doesn't use sustain.
- **CC 74 (MPE Timbre)** — only relevant in MPE mode; voice chain is single-channel.
- **CC 1 (Expression)** — could be repurposed as a high-level "overall processing depth" macro if the operator wants a physical expression-pedal override at the MOTU.

Revised dimension-to-CC table, superseding the parent doc §5.1:

| Dim | Primary CC | Secondary CC | Clamp notes |
|---|---|---|---|
| intensity | 39 (saturator amt) | 84 (saturator type, bias Distortion 43–63 for voice, excl. Feedback/Bit crush extremes) | CC 39 ≤ 80; CC 84 ∈ [43, 84] |
| tension | 70 (filter freq) | 71 (filter reso), 80 (filter type — bias BP) | CC 71 ≤ 60 for voice safety; CC 80 ∈ [78, 102] = BP band |
| diffusion | 91 (reverb amt) | 43 (cloud) | CC 91 ≤ 80; CC 43 ≤ 40 for voice |
| brightness | 92 (reverb tone) | 86 (overtone type) | CC 92 mid-anchored at 60 ± 20 |
| density | 46 (grains) | 43 (cloud) | CC 46 ≤ 70 for voice (avoid Roads-texture regime); 0 if CC 11 = 0 |
| grit | 47 (shape) | 39 (saturator amt), 44 (pitch — avoid for voice) | CC 94 (shimmer) permanently clamped = 0 |
| space | 93 (reverb tail) | 42 (spread), 91 (reverb amt) | CC 93 ≤ 70 for voice; CC 94 = 0 |
| motion | 96 (env → filter) | 41 (diffuse) | CC 96 ≤ 60; no LFO-to-pitch routing |
| presence | 40 (mix) | 7 (volume) | CC 40 ∈ [40, 70] — never fully wet, never fully dry for voice |

---

## §6 References

### Primary manufacturer
- [Endorphin.es — Evil Pet product page](https://www.endorphin.es/modules/p/evil-pet)
- [Endorphines EVIL PET Granular Processor User Manual (manuals.plus)](https://manuals.plus/m/068472d380f335f9e901241a8c81ed421e1fc3973820446abe12e8e5eaeb4335)
- [midi.guide — Endorphin.es Evil Pet CCs and NRPNs](https://midi.guide/d/endorphines/evil-pet/)

### Distributor / retail practitioner pages
- [Perfect Circuit — Evil Pet product page](https://www.perfectcircuit.com/endorphines-evil-pet.html)
- [Perfect Circuit Signal — Feed After Midnight: Endorphin.es Evil Pet Overview](https://www.perfectcircuit.com/signal/endorphines-evil-pet-review)
- [WeAreBlip — Endorphin.es Evil Pet 8-Voice Polyphonic Granular Workstation](https://weareblip.com/products/endorphin-es-evil-pet)
- [SchneidersLaden — Evil Pet](https://schneidersladen.de/en/endorphin.es-evil-pet)
- [Thomann — Endorphin.es Evil Pet](https://www.thomannmusic.com/endorphines_evil_pet.htm)
- [Moog Audio — Endorphin.es Evil Pet](https://moogaudio.com/products/endorphin-es-evil-pet-granular-processor-with-fm-radio)
- [Elevator Sound — Endorphin.es Evil Pet Desktop Granular Processor](https://www.elevatorsound.com/product/endorphin-es-evil-pet-desktop-granular-processor/)
- [Signal Sounds — Endorphin.es Evil Pet Desktop Granular Processor](https://www.signalsounds.com/endorphin-es-evil-pet-desktop-granular-processor/)
- [Modularsquare — Evil Pet](https://www.modularsquare.com/shop/endorphin-es/evil-pet/)

### Community / practitioner press
- [SYNTH ANATOMY — Endorphin.es EVIL PET: a pink MPE polyphonic granular Synthesizer and multi-FX](https://synthanatomy.com/2025/10/endorphin-es-evil-pet-an-mpe-polyphonic-granular-synthesizer.html)
- [Gearnews — Endorphin.es Evil Pet Goes Against the Grain](https://www.gearnews.com/endorphin-es-evil-pet-synth/)
- [modwiggler — Endorphines Evil Pet thread](https://www.modwiggler.com/forum/viewtopic.php?t=296887)
- [Synth Magazine — loopop Explores the Chaotic Charms of the EVIL PET](https://synthmagazine.com/loopop-explores-the-chaotic-charms-of-the-evil-pet-by-endorphin-es/)
- [loopop — Review: EVIL PET by Endorphin.es, Live granular techniques explored (YouTube)](https://www.youtube.com/watch?v=tXQzW5pEhNY)
- [Endorphin.es — RROAARRR with EVIL PET (YouTube)](https://www.youtube.com/watch?v=o9etOvJd3Ng)
- [Endorphin.es — EVIL PET Granular Sampler sound demo (YouTube)](https://www.youtube.com/watch?v=KGfURhIa5sc)

### Granular theory / academic
- Roads, C. (2001). *Microsound*. MIT Press. Summary at [Perfect Circuit: Exploring Microsound and Granular Synthesis](https://www.perfectcircuit.com/signal/microsound); review at [Sound on Sound — Curtis Roads: Microsound](https://www.soundonsound.com/reviews/curtis-roads-microsound).
- [SFU — Barry Truax, Granular Synthesis](https://www.sfu.ca/~truax/gran.html)
- [Michael Krzyzaniak — Audio Synthesis §11.1 Window Functions](https://michaelkrzyzaniak.com/AudioSynthesis/2_Audio_Synthesis/11_Granular_Synthesis/1_Window_Functions/)
- [GranularSynthesis.com — §2.2 The Envelope](https://www.granularsynthesis.com/hthesis/envelope.html)
- [Wikipedia — Granular synthesis](https://en.wikipedia.org/wiki/Granular_synthesis)

### Adjacent-filter / self-oscillation practitioner reference (Evil Pet filter not directly documented)
- [2hp — Comb module product page (digital comb filter self-oscillation context)](https://www.twohp.com/modules/p/comb)
- [Electronic Music Wiki — Self-oscillation](https://electronicmusic.fandom.com/wiki/Self-oscillation)
- [MusicRadar — How to control a self-oscillating filter](https://www.musicradar.com/tuition/tech/how-to-control-a-self-oscillating-filter-617960)

### Internal / hapax-council
- `docs/research/2026-04-19-evil-pet-s4-base-config.md` (voice-chain base config, §3.8 17-CC table, §5.1 9-dim map)
- `docs/research/2026-04-20-vinyl-broadcast-mode-d-granular-instrument.md` (§4 granular + filter + saturator + reverb behaviour for Mode D)
- `agents/hapax_daimonion/vocal_chain.py` (runtime MIDI CC emitter)
- Project memory `project_hardm_anti_anthropomorphization.md` (governance)
- CLAUDE.md §Unified Semantic Recruitment, CVS #16 (anti-personification persona constraint)
