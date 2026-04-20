# Evil Pet + S-4 Base Configuration for Hapax Vocal Chain

**Date:** 2026-04-19
**Register:** Scientific, operator-facing
**Scope:** Concrete base settings for the Hapax-TTS → Evil Pet → S-4 → Zoom L6 chain. Phase 1 = signal-level compatibility + base knob positions. Phase 2 = MIDI CC mapping to the 9-dim vocal_chain.py.

---

## §1. Confirmed device identities + high-level capabilities

### Endorphin.es Evil Pet
- **Form factor:** Desktop / "pedal-style" processor, glossy pink enclosure. **Not a Eurorack module** — this is a standalone DC-powered box with its own audio I/O on 1/4" TS jacks. (Earlier chain notes assumed Eurorack; they are wrong.)
- **Role:** 8-voice polyphonic granular synthesizer, multi-FX processor, FM radio receiver, sample player, loop/reel recorder. Single device, selectable source (line-in jacks / built-in mic / FM / microSD samples).
- **Key engine capabilities:**
  - 8-voice granular engine with position, size, pitch, grains, spread, cloud, detune, shape
  - Digital oscillator layer (sine, triangle, saw, square) — can be muted
  - Multimode resonant filter (dual LP/HP, LP, HP, BP, comb)
  - ADSR + three multi-wave LFOs + envelope follower
  - Saturator modes: distortion, sample-rate reducer, bit-crusher, flanger, chorus, feedback
  - Reverb modes: plate, reverse, room with shimmer
  - **No built-in delay** — this is a documented gap
  - MIDI + MPE, expression pedal input, 512 MB sample RAM, 2.42" OLED
- **Firmware at time of writing:** v1.42 (2026-03-27, from endorphin.es product page)
- **Official product page:** https://www.endorphin.es/modules/p/evil-pet

### Torso Electronics S-4
- **Form factor:** Desktop device, 242 × 156 × 39 mm, 820 g aluminum.
- **Role:** "Sculpting sampler" — 4 parallel stereo tracks, each a 5-slot audio device chain (Material → Granular → Filter → Color → Space). Operates as sampler, synth, **or live effects processor** via per-slot Bypass mode routing line inputs straight into the chain.
- **Default device chain (per track):**
  - **Material:** `Tape` (sampler) or `Poly` (poly synth) — or **Bypass** (line-in passthrough)
  - **Granular:** `Mosaic`
  - **Filter:** `Ring` (morphing resonator + 48-band tuned filter bank)
  - **Color:** `Deform` (dual-band distortion, compression, bit-crush, noise)
  - **Space:** `Vast` (delay + reverb in one device, stereo spread macros, hall-style reverb)
- **Modulation:** 4 modulators per track (Wave LFO, Random, ADSR, envelope follower), can modulate any parameter.
- **I/O:** 2× 1/4" TR mono line inputs, 2× 1/4" TR mono line outputs, 3.5mm TRS/TRRS headphone, USB-C class-compliant 10-in/10-out audio interface, 3.5mm MIDI in/out (DIN adapter supplied), 3.5mm sync in/out.
- **Firmware referenced in manual:** OS 1.0.4 (manual `The S-4 Manual 1v0v4a.pdf`)
- **Official product page:** https://torsoelectronics.com/products/s-4
- **Official manual (PDF):** https://downloads.torsoelectronics.com/s-4/manual/The%20S-4%20Manual%201v0v4a.pdf

---

## §2. Signal-level compatibility check

### 2.1 Stage 1 — MOTU 24c Output 2 → Evil Pet LEFT IN
| | Source (MOTU 24c Out 2) | Destination (Evil Pet LEFT IN) |
|---|---|---|
| Connector | 1/4" TRS balanced | **1/4" TS unbalanced mono** |
| Nominal level | +4 dBu (line, pro) ≈ 1.228 Vrms ≈ 3.47 Vpp | Accepts up to +4 dBu / ±1.736 V per manufacturer |
| Impedance | Balanced line-out, typical Zout ~75 Ω | Hi-Z instrument-compatible, line-level-tolerant |

**Verdict: compatible, but with a balanced-to-unbalanced caveat.** Evil Pet inputs are **unbalanced TS** jacks. A TRS-to-TS cable dropped directly from the 24c into the Evil Pet will short the cold leg (ring) to sleeve at the Evil Pet end. This is the normal, correct way to terminate a balanced pro output into an unbalanced line input — the signal is preserved on tip, the cold leg is simply grounded at the destination. The 6 dB of common-mode-rejection benefit is lost, but the absolute level is correct.

- **If you hear hum or ground-loop buzz:** insert a **passive DI / isolation transformer** between 24c Out 2 and Evil Pet LEFT IN. Recommended: Radial ProDI, Radial J-Iso, Jensen ISO-MAX, or Palmer PLI-01.
- **If the signal is too hot:** Evil Pet's documented LEFT IN ceiling is +4 dBu (±1.736 V). The 24c at full-scale digital output slams into exactly that ceiling. Use the Evil Pet's `SHIFT + ENCODER` input-gain trim (§3) to attenuate, or reduce the TTS playback level in software by ≈ 6 dB. No external pad needed.

### 2.2 Stage 2 — Evil Pet LEFT OUT → S-4 IN 1
| | Source (Evil Pet LEFT OUT) | Destination (S-4 IN 1) |
|---|---|---|
| Connector | 1/4" TS unbalanced mono | 1/4" TR mono line input |
| Nominal level | Line level (consumer-to-pro range) | Line level |
| Impedance | Low-Z line-out | Line-in, line-level expected |

**Verdict: compatible.** Both are line level, 1/4" unbalanced mono. Direct TS-to-TS cable. The S-4 manual explicitly calls out that **Eurorack signal levels are too hot** and may need attenuation — this is not that case. Evil Pet is a line-level box, not a Eurorack module, so this warning does not apply.

### 2.3 Stage 3 — S-4 OUT 1 → Zoom L6 Channel 1
| | Source (S-4 OUT 1) | Destination (L6 INPUT 1) |
|---|---|---|
| Connector | 1/4" TR mono line-out | **XLR/TRS combo** |
| Nominal level | Line level (2 Vrms typical for 24-bit DAC hardware) | TRS = +4 dBu line, XLR = mic level |

**Verdict: compatible, but use the correct plug.** The L6 manual is explicit: *"use line level devices when connecting with TRS plugs, and use mic level devices when connecting with XLR plugs."* Combo jacks switch sensitivity based on plug type.

- **Required cable:** 1/4" TS → 1/4" TRS (or TS → TS, the combo jack accepts both). Driving the XLR side will overload the mic pre.
- **L6 channel 1 gain:** start at **9 o'clock** (well below unity) with PAD off. S-4 is a 24-bit DAC; its line output runs clean and hot. Confirm headroom on the L6 VU before engaging phantom, etc.

### 2.4 Summary of level-shifting needs
No Eurorack ↔ line crossings exist in this chain. **The whole path is line-level, end-to-end.** Operator does not need an Intellijel Line In 1U, Expert Sleepers ES-9 level-shifter, or any equivalent attenuator. The one real hazard is stage 1: a balanced pro output feeding an unbalanced input — this is normal practice but is the most likely place to hear ground-loop noise. Mitigate with a passive DI only if empirically necessary.

---

## §3. Evil Pet base configuration

Design goals:
1. Evil Pet is an **effects processor** for a mono speech signal, not a granular synth generating new sound.
2. The processed signal must remain **intelligible** — words stay words.
3. Processing must be **signal-honest** — tracks the input, no fake emotion, no humanizing coloration, no anthropomorphic cadence. Consistent with HARDM governance: the texture is a readout of signal density, not a performed affect.
4. The output must be **clearly different from dry** — Evil Pet has to be doing work, or it's wasting a patch slot.

### 3.1 Input routing
- **Source select:** `LINE` (not MIC, not FM, not SD) — use the front-panel source button to select the 1/4" jacks.
- **Input gain:** `SHIFT + ENCODER` — start at **11 o'clock** (~45%, ~-3 dB trim). Confirm peaks on the OLED level meter sit at ~-6 dBFS during loudest TTS phrases. If clipping, step to 10 o'clock.
- **Built-in microphone:** disabled (automatic when LINE is selected).

### 3.2 Engine mode: use it as an FX processor, not a granular synth
The Evil Pet can run a granular engine *on top of* incoming audio, or process the raw incoming audio through its filter + saturator + reverb chain. For Hapax voice, the goal is the latter. Bypass the granular re-synthesis where possible and lean on the FX blocks.

- **GRAINS VOLUME (CC 11):** `7 o'clock` (0%, fully off). This kills granular re-synthesis of the audio — we are not reshaping Hapax's voice into a cloud of grains.
- **OVERTONE VOLUME (CC 85):** `7 o'clock` (0%, fully off). Digital oscillator layer disabled.
- **MIX (CC 40):** `12 o'clock` (~50% wet / 50% dry). This is the master wet/dry between the incoming signal and the processed output. Adjust up or down based on intelligibility test.
- **VOLUME (CC 7):** `1 o'clock` (~60%). Output level to stage 2.

### 3.3 Filter section
- **FILTER TYPE (CC 80):** `bandpass`. Gives the voice a narrow "radio / telephone" midband character without wrecking consonants. (HP would thin it; LP would smother it; comb would resonate on steady vowels — disallowed as it synthesizes character.)
- **FILTER FREQUENCY (CC 70):** `1 o'clock` (~60%, ≈ 1.8 kHz center with the BP). Keeps consonants.
- **FILTER RESONANCE (CC 71):** `9 o'clock` (~20%). Low — resonance adds synthetic character.
- **ENVELOPE FILTER MODULATION (CC 96):** `11 o'clock` (~35%). Opens the filter on louder phonemes. This is signal-honest envelope-following, not imposed cadence.

### 3.4 Saturator
- **SATURATOR TYPE (CC 84):** `distortion` (the mildest of the six modes — not flanger, not chorus, not bit-crusher at base). Honest harmonic enrichment.
- **SATURATOR (CC 39):** `10 o'clock` (~30%). Audible harmonics on plosives and sibilants, no wrecking of intelligibility.

### 3.5 Reverb (no delay is available on Evil Pet — we put delay on the S-4)
- **REVERB TYPE (CC 95):** `room`. Plate sounds like a studio effect; reverse is disorienting for speech; room is spatially honest.
- **REVERB AMOUNT (CC 91):** `10 o'clock` (~30%). Present but not drowning.
- **REVERB TONE (CC 92):** `12 o'clock` (neutral — do not darken; Hapax needs consonant clarity).
- **REVERB TAIL (CC 93):** `10 o'clock` (short tail, ~1–1.5 s). Long tails smear subsequent phonemes.
- **REVERB SHIMMER (CC 94):** `7 o'clock` (0%). Shimmer is an aesthetic coloration inappropriate for voice.

### 3.6 LFOs
All three LFOs disabled at base (speed knobs at `7 o'clock`, types set to `OFF` where selectable). LFOs applied to filter or pitch would impose humanizing wobble — exactly the kind of added-affect the governance forbids. In Phase 2, MIDI CC can re-engage LFO 1 speed (CC 76) under tight limits if we want the filter to breathe with Hapax's stimmung energy.

### 3.7 What NOT to touch at base
- **Position, Size, Pitch, Grains, Spread, Cloud, Detune, Shape** — all granular-engine parameters. Irrelevant while GRAINS VOLUME = 0.
- **RECORD ENABLE (CC 69):** leave OFF. We are not capturing to internal buffer.
- **Sustain, Attack, Decay, Release:** envelopes for the synth voice, not the FX path.

### 3.8 Configuration summary table
| Control | Position | Clock | CC# |
|---|---|---|---|
| Source select | LINE | — | — |
| Input gain (SHIFT+ENC) | ~45% | 11 o'clock | — |
| Grains volume | 0% | 7 o'clock | 11 |
| Overtone volume | 0% | 7 o'clock | 85 |
| Mix | ~50% | 12 o'clock | 40 |
| Volume | ~60% | 1 o'clock | 7 |
| Filter type | Bandpass | — | 80 |
| Filter freq | ~60% | 1 o'clock | 70 |
| Filter resonance | ~20% | 9 o'clock | 71 |
| Env→filter mod | ~35% | 11 o'clock | 96 |
| Saturator type | Distortion | — | 84 |
| Saturator amount | ~30% | 10 o'clock | 39 |
| Reverb type | Room | — | 95 |
| Reverb amount | ~30% | 10 o'clock | 91 |
| Reverb tone | neutral | 12 o'clock | 92 |
| Reverb tail | ~30% | 10 o'clock | 93 |
| Reverb shimmer | 0% | 7 o'clock | 94 |

---

## §4. S-4 base configuration

Design goal: route the Evil-Pet-processed speech through exactly the S-4 slots that are useful for speech — **Filter (tonal sculpting), Color (mild drive), Space (delay + reverb)** — and put every other slot in Bypass. Hapax's TTS drives the chain; S-4 itself generates nothing.

### 4.1 Top-level routing: Bypass the sampler, monitor line-in live
Per S-4 manual §3.7 ("Bypass Application: S-4 As an Effects Processor") and §6.3:

- Use **Track 1 only** (other 3 tracks silent).
- `Config → Audio → Input Mode = LINE` (routes IN 1 / IN 2 into the track).
- Track 1 Input: **Stereo mono-summed** — or actually, use **Mono IN 1** since our signal is mono on LEFT. Set `Track 1 LINE IN = Mono In 1` in track config.
- `Material` slot → **Bypass device.** Press `[CTRL] + [MATERIAL]`, select Bypass. This routes line-in straight through without engaging the Tape sampler or Poly synth.
- `Granular` slot → **Bypass device.** Mosaic granular is off.
- `Filter` slot → **Ring active** (configured below).
- `Color` slot → **Deform active** (configured below).
- `Space` slot → **Vast active** (configured below).

Result: line-in → Bypass → Bypass → Ring filter → Deform color → Vast space → Track 1 output → mixed to main out.

### 4.2 Filter slot — Ring device
Ring is a morphing resonator with a 48-band tuned filter bank. For voice, we stay tonal/subtle — Ring at extreme settings becomes a pitched resonator and produces the uncanny "frozen formant" sound, which is anthropomorphically evocative and disallowed.

- **Cutoff (CC 79):** `12 o'clock` (50%, mid sweep). Keeps all formants present.
- **Resonance (CC 80):** `9 o'clock` (~20%). Light.
- **Decay (CC 81):** `9 o'clock` (~20%). Keep the resonator short — long decay becomes a drone.
- **Pitch (CC 82):** `12 o'clock` (0, centered). No pitch tracking of the filter.
- **Slope (CC 83):** `10 o'clock` (~30%). Gentle.
- **Tone (CC 84):** `12 o'clock` (neutral).
- **Scale (CC 85):** Chromatic. Voice has no scale.
- **Wet (CC 86):** `10 o'clock` (~30%). Ring is flavor, not dominant.
- **Waves (CC 87):** `8 o'clock` (~10%). Minimal oscillator injection.
- **Noise (CC 88):** `7 o'clock` (0%). No noise injection.

### 4.3 Color slot — Deform device
Deform = dual-band distortion + compression + bit-crusher + noise. For voice we want **compression to even out dynamics** and **drive for warmth**, nothing destructive.

- **Drive (CC 95):** `10 o'clock` (~30%). Mild tube-style warmth.
- **Compress (CC 96):** `1 o'clock` (~60%). Noticeable leveling — evens TTS dynamics for livestream consistency.
- **Crush (CC 98):** `7 o'clock` (0%). No bit reduction. Bit-crush on voice is a stylization that adds fake character.
- **Tilt (CC 99):** `12 o'clock` (neutral EQ).
- **Noise (CC 100):** `7 o'clock` (0%). No added noise.
- **Noise Decay (CC 101):** n/a (noise off).
- **Noise Color (CC 102):** n/a (noise off).
- **Wet (CC 103):** `1 o'clock` (~60%). Deform is doing real work.

### 4.4 Space slot — Vast device
Vast is a combined delay + reverb. Evil Pet has no delay, so all echo work happens here.

- **Delay Amount (CC 112):** `11 o'clock` (~40%). Audible tempo-sync echo.
- **Delay Time (CC 113):** `1/8D` (dotted eighth). Sets up a rhythmic bed without conflicting with speech cadence. If no global tempo context, use `~350 ms` freely set.
- **Reverb Amount (CC 114):** `10 o'clock` (~30%). On top of Evil Pet's room reverb, this adds a larger hall wash.
- **Reverb Size (CC 115):** `1 o'clock` (~60%). Medium-large. Vast is hall-based per manual §3.6.
- **Delay Feedback (CC 116):** `10 o'clock` (~30%). 2–3 repeats, no runaway.
- **Delay Spread (CC 117):** `12 o'clock` (50%). Center — no ping-pong at base (stereo ping-pong on mono speech is a stylization). Phase 2 can push this under stimmung-driven state.
- **Reverb Damp (CC 118):** `1 o'clock` (~60%). Darken the tail — keep consonants out of the wash.
- **Reverb Decay (CC 119):** `11 o'clock` (~40%, ~2 s). Short enough to not collide with the next utterance.

### 4.5 Master Mix
- **Track 1 Level (CC 47, Ch 16):** `12 o'clock` (unity, ~0 dB).
- **Master Output Level:** `12 o'clock` (unity).
- **Master Compression:** ON, light. Prevents any cascade overshoot from hitting the L6.
- **DJ-style filters:** bypassed.

### 4.6 Preset name
Save as **project:** `HAPAX-VOX-BASE`. **Scene 1** of 128 captures this state.

---

## §5. MIDI CC map for Phase 2 — 9-dim vocal_chain.py → hardware

`vocal_chain.py` 9 dimensions (from project memory `project_vocal_chain.md`): **intensity, tension, diffusion, brightness, density, grit, space, motion, presence**. These are signal-derived, grounded impingement/stimmung values — all scaled 0.0–1.0.

### 5.1 Evil Pet — channel 1 (recommended)
| Hapax dim | CC# | Param | Range | Curve | Breakpoints |
|---|---|---|---|---|---|
| intensity | 39 | Saturator amount | 0–80 | linear | 0.0→0 / 0.5→40 / 1.0→80 |
| tension | 70 | Filter frequency | 40–100 | linear | 0.0→40 / 1.0→100 (opens up under tension) |
| tension | 71 | Filter resonance | 20–60 | linear | 0.0→20 / 1.0→60 |
| diffusion | 91 | Reverb amount | 20–60 | log | 0.0→20 / 0.7→45 / 1.0→60 |
| brightness | 92 | Reverb tone | 40–80 | linear | mid-anchored at 60 ± 20 |
| grit | 84 | Saturator type | discrete | N/A | [0,0.5)=distortion / [0.5,1.0]=bit-crush (stepped) |
| space | 93 | Reverb tail | 20–70 | linear | 0.0→20 / 1.0→70 |
| motion | 96 | Env→filter mod | 20–80 | linear | signal-honest; scales directly |
| presence | 40 | Wet/dry mix | 40–70 | linear | (ensures base dryness floor so words stay clear) |
| density | 11 | Grains volume | 0–0 | **clamped OFF** | governance: never engage granular on voice |

*Curve notes:* `log` curve on reverb amount gives smooth perceptual expansion without a sudden "wet" jump. `linear` elsewhere for legibility. All scaled to 0–127 at send time.

### 5.2 S-4 — channel 1 (Track 1)
| Hapax dim | CC# | Param | Range | Curve | Breakpoints |
|---|---|---|---|---|---|
| tension | 79 | Ring cutoff | 40–80 | linear | mid-anchored |
| tension | 80 | Ring resonance | 15–35 | linear | conservative ceiling |
| intensity | 95 | Deform drive | 20–60 | linear | |
| presence | 96 | Deform compress | 50–80 | log | compression rises with presence to hold level |
| space | 112 | Delay amount | 25–65 | linear | |
| space | 114 | Reverb amount | 20–55 | linear | |
| motion | 116 | Delay feedback | 20–45 | **clamped ceiling** | 45 max — prevents runaway |
| diffusion | 115 | Reverb size | 40–90 | linear | |
| brightness | 118 | Reverb damp | 40–80 | linear (inverted) | brighter = less damp; 0.0→80 / 1.0→40 |
| density | 86 | Ring wet | 15–45 | linear | |

### 5.3 Rate limiting
Both devices can glitch if CCs change faster than ~50 Hz. Debounce the CC emitter to max **20 Hz per CC** (50 ms min interval). 9 dims × 20 Hz × 2 devices = 360 msg/s — well within DIN MIDI's 31.25 kbaud limit (~1000 msg/s ceiling).

### 5.4 Implementation hook
`agents/hapax_daimonion/vocal_chain.py` already maps 9 dims to MIDI CCs for the Evil Pet + S-4. This table should replace or validate the existing map. Phase 2 of the wiring project (project memory `project_vocal_chain.md`) is the execution ticket.

---

## §6. Operator setup procedure

1. **Cable the chain.** TRS-TS from MOTU 24c Out 2 → Evil Pet LEFT IN. TS-TS from Evil Pet LEFT OUT → S-4 IN 1. TS-TRS from S-4 OUT 1 → L6 INPUT 1 (use the TRS side of the combo, **not** XLR).
2. **Power on** Evil Pet (9–18 V DC) and S-4 (12 V 2 A centre positive). Verify OLED on both comes up.
3. **Zoom L6 ch1:** gain at 9 o'clock, phantom power OFF, PAD off.
4. **Evil Pet source select:** press source-select until `LINE` is shown on OLED.
5. **Evil Pet input-gain trim:** hold SHIFT, turn the main encoder to ~11 o'clock.
6. **Evil Pet engine:** dial in §3.8 table values. Granular/overtone volume = 0 is the most important — do this first so the device isn't generating anything on its own.
7. **S-4 project:** load or create `HAPAX-VOX-BASE`. On Track 1, set Material + Granular to Bypass (`[CTRL] + [MATERIAL]`, `[CTRL] + [GRANULAR]`). Confirm Filter/Color/Space are loaded with Ring/Deform/Vast.
8. **S-4 input mode:** `[CONFIG] → AUDIO → INPUT MODE = LINE`. Set Track 1 LINE IN to Mono In 1.
9. **S-4 parameters:** dial in §4 values per slot. Save as Scene 1.
10. **Signal test — silence check:** TTS playing nothing. L6 channel 1 VU must be at noise floor (below -60 dBFS). If hum present, insert passive DI between MOTU and Evil Pet.
11. **Signal test — speech check:** play Hapax TTS line "systems nominal, signal present." Expected result:
    - Evil Pet OLED input meter peaks at ~-6 dBFS
    - S-4 Track 1 meter peaks at ~-6 to -3 dBFS
    - L6 channel 1 meter peaks at -12 to -6 dBFS
    - The words are clearly intelligible
    - There is a noticeable bandpass-colored, gently saturated, spatially wet quality — not a dry passthrough
    - No anthropomorphic quality — no "breath," no "warmth in the wrong way," no affective color that wasn't in the TTS source
12. **If signal is too hot on L6:** reduce S-4 Master Output or Track 1 Level by 3 dB increments until L6 meter sits in -12 to -6 zone.
13. **If signal is thin / far away:** raise Evil Pet `Mix` (CC 40) toward 14 o'clock, or S-4 `Vast Wet` / `Deform Wet` slightly. Do not raise gain alone — that just pushes the chain hotter.
14. **Verify in OBS:** confirm the `hapax-livestream-tap` source carries this chain to OBS with meters behaving the same as L6 channel 1.

---

## §7. Open questions for operator

Fill in from physical manuals or a live device walk:

1. **Evil Pet reverb type — is "room" really tighter than "plate"?** Manufacturer copy is ambiguous on which of the three (plate / reverse / room) has the shortest, driest character. Confirm on device; may prefer plate if the on-board room emulation is too chamber-like.
2. **Evil Pet MIDI channel default.** The MIDI Guide chart does not specify receive channel — is it default ch1, or user-configurable? Verify in `Config` menu.
3. **Evil Pet OLED input meter scaling.** Is the meter dBFS, dBu, or percent? Impacts the "peak at ~-6 dBFS" target in §6 step 11.
4. **S-4 "Mono In 1" vs "Stereo."** The manual §6.3 shows per-track LINE IN mode options (Stereo / Mono / etc.) but truncates the list. Confirm on device that a Mono-In-1 option exists. If only Stereo is offered, set it to Stereo and let IN 2 run empty — internal summing should still work.
5. **S-4 Vast delay time — "1/8D"** exists as a step option? The manual enumerates timing rate options in §9.3 which weren't captured here. Confirm that dotted eighth exists; if not, use straight 1/8 or free-time ~350 ms.
6. **S-4 Ring Scale parameter.** Docs show "Scale" on CC 85 — does "Chromatic" or "Off" disable pitch-tracking? If every Ring scale option imposes a note grid, drop Ring Wet further (or put Filter slot in Bypass and lean only on Color + Space).
7. **Global tempo source.** If the L6 / council livestream has no master clock, S-4 runs on its internal clock at 120 BPM. Verify this is acceptable for the delay rhythm, or sync S-4 to a host clock via `sync in`.
8. **Ground-loop behavior.** Only discoverable empirically. If audible hum appears, a Radial J-Iso between 24c and Evil Pet resolves it — budget for one in advance.

---

## Sources

- [ENDORPHIN.ES Evil Pet product page](https://www.endorphin.es/modules/p/evil-pet)
- [Endorphin.es Evil Pet MIDI CCs and NRPNs — midi.guide](https://midi.guide/d/endorphines/evil-pet/)
- [Endorphines Evil Pet Granular Processor User Manual (manuals.plus)](https://manuals.plus/m/068472d380f335f9e901241a8c81ed421e1fc3973820446abe12e8e5eaeb4335)
- [Endorphin.es Evil Pet - SYNTH ANATOMY coverage](https://synthanatomy.com/2025/10/endorphin-es-evil-pet-an-mpe-polyphonic-granular-synthesizer.html)
- [Torso Electronics S-4 product page](https://torsoelectronics.com/products/s-4)
- [Torso Electronics S-4 Manual, OS 1.0.4](https://downloads.torsoelectronics.com/s-4/manual/The%20S-4%20Manual%201v0v4a.pdf)
- [Sound on Sound — Torso Electronics S-4 review](https://www.soundonsound.com/reviews/torso-electronics-s-4)
- [Zoom LiveTrak L6 product page](https://zoomcorp.com/en/us/digital-mixer-multi-track-recorders/digital-mixer-recorder/livetrak-l6-final/)
- [Zoom L6 Operation Manual](https://zoomcorp.com/manuals/l6-en/)
