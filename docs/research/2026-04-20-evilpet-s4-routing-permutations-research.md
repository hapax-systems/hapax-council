---
date: 2026-04-20
author: alpha
audience: operator + delta (execution)
register: scientific, neutral
status: research — exhaustive routing-permutation space for Evil Pet + Torso S-4
related:
  - docs/research/2026-04-19-evil-pet-s4-base-config.md (§2-4 signal levels, base presets)
  - docs/research/2026-04-20-dual-fx-routing-design.md (Option A: S-4 USB direct)
  - docs/research/2026-04-20-unified-audio-architecture-design.md (topology abstraction)
  - docs/research/2026-04-20-audio-normalization-ducking-strategy.md (source inventory, ducking matrix)
  - docs/research/2026-04-20-voice-transformation-tier-spectrum.md (7-tier CC preset ladder)
  - docs/research/2026-04-20-mode-d-voice-tier-mutex.md (Evil Pet granular engine mutex)
  - shared/evil_pet_presets.py (9 CC-burst presets: T0..T6 + bypass)
  - agents/hapax_daimonion/vocal_chain.py (9-dim → MIDI CC emitter)
  - agents/hapax_daimonion/vinyl_chain.py (Mode D vinyl granular)
---

# Evil Pet + Torso S-4 Routing Permutations — Full Research

## §1. TL;DR

### Hardware affordances

**Evil Pet** (Endorphin.es, standalone, not Eurorack): mono 1/4" TS in/out, MIDI ch 1. Voices 1 (granular synthesizer) + FX chain (filter, saturator, reverb). Single shared granular engine; 8-voice polyphony when granular is engaged.

**Torso S-4** (Sculpting sampler, USB class-compliant audio interface): 2× mono 1/4" line I/O, USB-C (10-in/10-out), 4 parallel stereo tracks with 5-slot effect chains each (Material → Granular → Filter → Color → Space). When Material + Granular slots are in Bypass mode, S-4 acts as a 5-device linear FX processor.

### Current state (2026-04-20)

```
Kokoro TTS → voice-fx-chain → Ryzen analog out → L6 ch 5
L6 ch 5 AUX 1 → Evil Pet L-in
Evil Pet L-out → L6 ch 3 (broadcast via Main Mix AUX10+11)
S-4 planned: PC USB direct → S-4 → L6 ch 2 (parallel path, not yet wired)
```

### Top 3 recommended routings for livestream go-live

1. **Selective voice FX (voice only).** Hapax TTS → Evil Pet (T2 BROADCAST-GHOST default) → L6 ch 3. Music/content hits L6 clean on ch 5 or via S-4 music scene on ch 2. **Single-purpose chain, clear semantics.** *Latency: <5 ms analog. Failure: Evil Pet offline → ch 3 mute, ch 5 direct backup. Control: tier macro via impingement recruitment.*

2. **Parallel dual-FX per source.** TTS → split to (Evil Pet, S-4 Mosaic granular) simultaneously, both returns to Main Mix. Dry TTS backup on ch 5. **Two granular characters at once; permits operator choice per-utterance.** *Latency: Evil Pet ~0 ms, S-4 USB ~12 ms; visual sync drift if both return to same channel. Failure: USB glitch → S-4 silent, Evil Pet holds. Control: MIDI CC tier selection per source.*

3. **Serial dual-processor (Evil Pet → S-4 USB loopback via PC).** Kokoro → Evil Pet → [hardware RCA → L6 ch 3 loopback capture → S-4 USB via filter-chain] → S-4 USB output → L6 ch 2. **Deepest texture; stacks two granular engines and two reverb stages.** *Latency: ~5 ms analog + ~12 ms USB = ~17 ms total; feedbacks must be clamped. Failure: PC loopback lag or USB buffer → audible stutter. Control: complex parameter cascade. Governance: risk of runaway feedback without explicit gain floors.*

---

## §2. Processor capabilities

### §2.1 Evil Pet

**Analog I/O:** 1/4" TS unbalanced mono in (pin 2 hot), 1/4" TS unbalanced mono out (pin 2 hot). Documented max input: +4 dBu peak (±1.736 V). Output nominal: line level, ~2 Vrms typical at 50% wet. No filtering on the input; source impedance ~200 Ω; input impedance ~100 kΩ.

**MIDI:** DIN 5-pin receive, configurable receive channel (default ch 1; verify via CONFIG). 130+ CC assignments per `midi.guide` Evil Pet page. Key CCs for vocal FX:

| CC | Param | Range | Governance |
|----|-------|-------|-----------|
| 7 | Master Volume | 0–127 | Clamped 60–100 for voice (never silent) |
| 11 | Grains Volume | 0–127 | **Clamped 0–90 for voice T0..T5; T6 reaches 127 only under governance gate.** Mutex with Mode D. |
| 39 | Saturator Amount | 0–127 | 0–80 for voice; 80+ introduces bit-crush character |
| 40 | Mix (wet/dry) | 0–127 | 40–95 for voice; 0 = bypass, 127 = 100% wet |
| 44 | Pitch (center=64) | 0–127 | ±12 semitones; for voice: 52–100 (don't denature) |
| 70 | Filter Frequency | 0–127 | Sweeps across modes; 40–100 for voice (preserve consonants) |
| 71 | Filter Resonance | 0–127 | 0–80 for voice; >60 introduces pitched resonance (disallowed) |
| 80 | Filter Type | discrete | 0=LP, 64=BP (default for voice), 127=HP. T4 UNDERWATER uses LP. |
| 84 | Saturator Type | discrete | [0, 42)=distortion, [42, 84)=sample-rate-reducer, [84, 127)=bit-crusher. T0..T4 clamp to distortion. |
| 91 | Reverb Amount | 0–127 | 20–60 for voice T0..T4; T5..T6 extend to 100 |
| 92 | Reverb Tone | 0–127 | 40–80 for voice (neutral-to-bright) |
| 93 | Reverb Tail | 0–127 | 20–70 for voice (keep under 2 s; prevent phoneme smear) |
| 94 | Shimmer | 0–127 | **Clamped 0 for voice (disallowed; adds anthropomorphic character).** Mode D reaches 60. |
| 96 | Envelope→Filter Mod | 0–127 | 0–80 for voice (signal-honest envelope following) |

**Processing character:** When GRAINS VOLUME (CC 11) = 0, Evil Pet acts as a linear FX processor: input → filter → saturator → reverb → output, all passing through the same path. No synthesis. When GRAINS VOLUME > 0, a polyphonic granular synthesizer layer engages: incoming audio is granulated (positioned, sized, pitched, clouded), re-synthesized, and mixed with the dry input per the Mix knob. At GRAINS VOLUME = 127, no dry signal remains visible; the output is 100% granular texture.

**Latency:** Analog passthrough + OLED display roundtrip ≈ 50–200 μs (negligible vs USB). MIDI CC to knob response ≈ 1–2 ticks per envelope.

**Mode D mutex:** The granular engine is claimed by `vinyl_chain.py` when Mode D is active (vinyl turntable through Evil Pet at T5/T6 granular character). While Mode D is engaged, any TTS attempted to route through Evil Pet's granular layer would collide — two granular sources fighting over one engine. Governance enforces: if Mode D is active and a voice-tier T5+ is recruited, the voice routes through **S-4 Mosaic granular instead** (alternative granular path). See `docs/research/2026-04-20-mode-d-voice-tier-mutex.md` §4 for the full dispatch rule.

### §2.2 Torso S-4

**Analog I/O:** 2× mono 1/4" TR line inputs (IN 1, IN 2), 2× mono 1/4" TR line outputs (OUT 1, OUT 2). Nominal line level. Manual specifies: do NOT send Eurorack-level (+5V peak) into S-4 without attenuation (will clip). Evil Pet output (line level, ~2 V peak) is correctly spec'd.

**USB:** Class-compliant USB-C, 10-in/10-out (5 stereo pairs). Linux/PipeWire via `snd-usb-audio` kernel driver. Appears as `alsa_output.usb-Torso_Electronics_S-4_...pro-output-0` (sink) + `alsa_input.usb-Torso_Electronics_S-4_...pro-input-0` (source). No proprietary drivers required. Latency at default `quantum=256` + S-4 internal buffering ≈ 5–12 ms round-trip.

**MIDI:** 3.5mm TRS DIN adapter supplied. S-4 receives on one channel (per manual, configurable; default ch 1). Responds to CC (parameter control) and note data (sequencer playback).

**Processing architecture:** 4 independent stereo tracks, each with 5 serial slots: Material → Granular → Filter → Color → Space. Each slot is a named device (e.g., Material = Tape/Poly/Bypass, Granular = Mosaic/None, Filter = Ring/etc.). When the Material and Granular slots are set to **Bypass**, the track acts as a linear 3-device FX chain: Filter → Color → Space. Per-track input selector: Stereo, Mono In 1, Mono In 2, or Line (summed). Per-track output: Main Mix or standalone out.

**FX vocabulary (per slot):**

| Slot | Device | Capability | Key CCs |
|------|--------|-----------|---------|
| **Material** | Tape, Poly, Bypass | Sampler playback / poly synth / **line-in passthrough** | 98–102 (density, tone, etc.) |
| **Granular** | Mosaic, None | Granular engine with position/length/rate controls | 47–54 |
| **Filter** | Ring, Peak, etc. | Morphing resonator (Ring) / peaking (Peak) / slope controls | 79–88 |
| **Color** | Deform, Mute | Distortion + compression + bit-crush (Deform) or mute | 95–102 |
| **Space** | Vast, None | Delay + reverb in one device with spread/feedback controls | 112–119 |

**Processing character:** Each track can be a sampler (Tape material), polyphonic synth (Poly), or **audio effect processor** (Material=Bypass, Granular=Bypass/None). The three remaining slots (Filter, Color, Space) perform tonal sculpting, harmonic enrichment, and spatial diffusion. When operating as an FX processor on a line-in source:

```
Input → Bypass (no resynthesis) → Mosaic/None (no granulation or light granulation) → Ring (resonant filter) → Deform (compression + drive) → Vast (delay + hall reverb) → Output
```

This is the "voice FX mode" per `evil-pet-s4-base-config.md` §4.

**Latency:** USB buffering dominates; at Zoom L6 `quantum=256` sample buffer (5.3 ms at 48 kHz) + S-4 USB full-duplex buffering ≈ 5–12 ms total. Perceivable with headphone feedback, acceptable for broadcast (LUFS metering drift < 0.5 dB at 12 ms latency).

**Granular mutex:** S-4 has its own independent Mosaic granular engine. No conflict with Evil Pet's granular when both are engaged simultaneously — two separate devices. Allows parallel granular processing: TTS → (Evil Pet T5 granular, S-4 Mosaic) in parallel, both to Main Mix. Different character: Evil Pet grain clouds vs. S-4 Mosaic rhythm-gated samples.

---

## §3. Source inventory (every distinct PC audio source)

| # | Source | Content | PipeWire path | Typical level | Desired FX profile |
|---|--------|---------|----------------|---|---|
| **S1** | **Hapax TTS (Kokoro)** | Narration, dialogue, state-of-system announcements | `hapax-voice-fx-capture` → Ryzen analog → L6 ch 5 AUX 1 | -18 LUFS (normalized) | Always has character (Evil Pet T1–T5 per stimmung/programme). T0 bypass on governance gates (consent). T6 rare, gated. |
| **S2** | **Vinyl turntable (Korg Handytrax)** | DJ-mixed records, non-licensed | L6 ch 4 direct (+ AUX 1 to Evil Pet when Mode D active) | -18 to -6 LUFS (pressing-dependent) | Dry on ch 4 fader when no FX. Evil Pet Mode D (T5 granular wash) when copyright defeat is active. No S-4 processing. |
| **S3** | **Operator voice (Rode Wireless Pro)** | Live speech, call responses, announcement callouts | L6 ch 1 direct | -18 LUFS (normalized by Rode receiver compression) | Sometimes through Evil Pet (shared with TTS via intent — duet mode is rare). Mostly dry. |
| **S4** | **Contact mic (Cortado MKIII)** | Percussive desk work (typing, tapping, button presses), turntable crackle | L6 ch 2 direct (currently). Plan: move to ch 6. | -22 LUFS RMS window | **Private, not broadcast.** Feeds presence detection DSP. Operator can bring fader up for performative moments (on ch 2 currently, will be ch 6). Never through FX. |
| **S5** | **YouTube/SoundCloud browser audio** | Music beds, ambient, stream content | `hapax-livestream` sink (loopback) → (planned) S-4 USB via separate filter-chain | -14 LUFS (YouTube normalized) | Music-tuned FX: S-4 light Ring + light Deform + warm Vast (clean character, no Evil Pet coloration). Dry fallback on ch 5 AUX 1 route. |
| **S6** | **System notifications** | Chat alerts, app chimes | `role.notification` → (broken: targets dead 24c Out 2) | Highly variable | **Governance: forbidden on broadcast.** Notifications route to operator-private sink only. Post-24c-retirement, needs retarget. |
| **S7** | **Assistant SFX / stingers** | Daimonion-emitted sound effects (discretionary) | `role.assistant` → (OBS-bound via `hapax-livestream`) | -16 LUFS | Per-moment: silence (suppressed by recruitment filter), dry (SFX plays clean), or Evil Pet T1–T2 (subtle colour). Not typically T3+. |
| **S8** | **Room ambient (Blue Yeti)** | Background environment (ASMR, bird sounds) | `alsa_input.usb-Blue_Microphones_Yeti` (USB) | -30 to -18 LUFS | **Private, not broadcast by default.** When operator recruits room-presence aesthetic (rare), fed to L6 for manual operator-mixed inclusion. Never through FX. |

**PC-audio bottleneck:** All PC sources except the S-4 USB input currently route through the single Ryzen analog output → L6 ch 5 → AUX 1 → Evil Pet path. This means S1 + S5 + S7 share the Evil Pet, causing the three failure modes enumerated in `dual-fx-routing-design.md` §1. **The permutation space unlocks when S-4 USB is wired (Option A):** S5 (music) + S7 (SFX) can then route via S-4 USB independently, leaving S1 (voice) isolated on Evil Pet.**

---

## §4. Destination inventory (where FX output can land)

| Destination | Path | Broadcast-bound? | Operator-monitor? | Role |
|---|---|---|---|---|
| **L6 Main Mix (AUX10+11)** | L6 faders → USB multitrack AUX10+11 | YES | YES | Primary broadcast output. Every channel fader contributes. |
| **L6 Master Out (L12 analog)** | L6 master fader → analog out → powered monitors | NO | YES | Operator monitor only. Does NOT go to broadcast. |
| **L6 Phones (3.5mm jack)** | L6 phones knob → headphone amp | NO | Depends (operator listens) | Private operator monitoring. |
| **Evil Pet L-out → L6 ch 3** | Hardware 1/4" TS | YES (via ch 3 fader into Main Mix) | Depends (ch 3 fader) | FX return channel. Broadcast only if ch 3 fader is up; operator can solo. |
| **S-4 USB out → (future L6 ch 2)** | USB class-compliant → PipeWire → hapax-livestream-tap | YES (via tap) | NO direct (but PW monitor possible) | Parallel FX return. Not yet wired; planned per dual-fx-routing design. |
| **S-4 analog out 1/4" → L6 ch 2** | Hardware 1/4" TR | YES (via ch 2 fader) | Depends (ch 2 fader) | Alternative to USB; lower latency. Not currently used. |
| **L6 AUX 1 (Evil Pet input)** | L6 ch 3/4/5/6 → AUX 1 knob → analog out → Evil Pet L-in | (loop; FX input, not output) | — | Hardware send bus. Hard rule: only ONE source at a time (mutex: ch 4 Mode D vs. ch 5 voice). |
| **Broadcast fallback (ch 5 direct dry)** | L6 ch 5 → Main Mix, bypassing Evil Pet | YES (fallback) | YES | Clean backup. If Evil Pet fails, ch 5 fader goes up, AUX 1 off. |

---

## §5. Routing topology classes

Each class is a structural pattern. For each, I enumerate the explicit signal path, control surface, failure modes, use-case fit, latency, and feedback risk.

### §5.1 Single-processor linear: Evil Pet (voice only)

**Pattern:** Kokoro TTS → [voice-fx-chain filter] → Ryzen analog → L6 ch 5 → AUX 1 → Evil Pet (T2 default) → ch 3 → Main Mix.

**Control surface:** 
- CC tier macro via `recall_preset()` in `evil_pet_presets.py`. Operator impingement/director recruitment emits `EVIL_PET_RECALL_TIER_2` (default), `TIER_1` (announcement), `TIER_3` (memory callback), etc.
- L6 ch 5 fader: TTS level. L6 ch 3 fader: Evil Pet return level.
- L6 AUX 1 knob: send amount (hard rule: max 5 dB to prevent clipping Evil Pet input).

**Failure modes:**
- **Evil Pet offline:** Ch 3 goes silent; TTS is unheard. Mitigation: ch 3 has a dedicated mute button on L6; operator brings ch 5 AUX 1 to OFF (or pulls ch 5 fader down), swaps to dry route. Recovery: ~2s (manual hardware reconfig). Governance: no automated fallback; operator decides whether dry or silent is preferable.
- **MIDI dead:** Evil Pet stuck in last preset. Perception: CC recall fails silently (evil_pet_presets.py logs at WARNING). Operator notices on next utterance that the voice character hasn't changed. Mitigation: hardwire Evil Pet presets to knob positions so the device remains usable without MIDI.
- **Ground loop hum:** Balanced 24c Out 2 → unbalanced Evil Pet in. Mitigated by adding a passive DI (Radial J-ISO, ~$100) between 24c and Evil Pet. No latency penalty.

**Use case:** "Always-on Hapax voice character." TTS narrates the livestream; Evil Pet provides subtle, consistent color without drawing attention. T2 (BROADCAST-GHOST) is the default; programme-level directives can shift to T1 (announcement), T3 (memory), etc. Vanilla livestream mode.

**Latency:** ~0 ms analog Evil Pet, ~0 ms L6 direct routing. Total perceivable latency: <1 ms (zero for all intents).

**Feedback risk:** None. Evil Pet L-out goes to L6 ch 3, not back to input. No loop. Closed system.

**Governance fit:** Signal-honest effects (no anthropomorphic character imposed). Evil Pet in FX-processor mode (not synthesizing). Per §3.2 base config, grains clamped off for T0–T5, reversible. Monetization: Evil Pet granular is a Content-ID defeat engine per `mode-d-voice-tier-mutex.md` §2; voice granular is ancillary (T5 GRANULAR-WASH is rare and gated by stimmung, not routine).

### §5.2 Single-processor linear: S-4 (music only, future)

**Pattern:** YouTube/SoundCloud → `hapax-livestream` sink → (new filter-chain) → S-4 USB input → S-4 Track 1 (Bypass → Bypass → Ring → Deform → Vast) → USB out → PipeWire → L6 ch 2 (once cabled) → Main Mix.

**Control surface:**
- S-4 front panel: 4 knobs per slot (Material, Granular, Filter, Color, Space), macro encoder. Presets on device.
- PipeWire filter-chain (planned): redirect `hapax-livestream` ALSA output (which currently loops back to PC L6 input) into the S-4 USB input instead.
- L6 ch 2 fader: S-4 return level.

**Failure modes:**
- **S-4 USB disconnects:** S-4 USB path goes silent. `snd-usb-audio` driver auto-resumes on reconnect; no manual intervention needed. Perception: audio dropout ~2 s while system re-enumerates. Mitigation: redundant dry path: keep `hapax-livestream` → L6 ch 5 fallback path enabled; operator fades ch 2 down, ch 5 up in parallel.
- **PipeWire filter-chain misconfiguration:** YouTube audio doesn't reach S-4 USB. Logs in `journalctl -u pipewire.service`. Fixable on-the-fly: `pw-cli set-param-default`. Recovery: ~5 s.
- **Feedback loop if S-4 output is accidentally looped back to `hapax-livestream` input:** would cause infinite mirror. Prevented by strict PipeWire config (no reciprocal link).

**Use case:** "Music-character isolation." YouTube plays during broadcast. Rather than hitting Evil Pet (which colors it with voice-tuned BP filter + distortion), music routes via S-4 for clean music-focused FX: Ring (resonant filter, tonal sculpting) + Deform (light compression to even dynamics) + Vast (warm delay + hall reverb). Leaves Evil Pet free for voice.

**Latency:** ~5–12 ms USB (perceivable if headphone feedback enabled, acceptable for broadcast).

**Feedback risk:** None if configuration is locked. S-4 output only goes to L6 ch 2, not back to input.

**Governance fit:** Music character is neutral; Ring/Deform/Vast are standard music FX, not content-ID-defeat engines. No monetization risk for this routing alone.

### §5.3 Serial dual-processor (Evil Pet → S-4, analog hardware path)

**Pattern:** Evil Pet L-out (1/4" TS) → S-4 IN 1 (1/4" TR) → S-4 Track 1 (configured as above) → S-4 OUT 1 (1/4" TR) → L6 ch 2 (once cabled).

**Signal flow:** Kokoro → voice-fx-chain → Ryzen analog → L6 ch 5 AUX 1 → **Evil Pet** → S-4 serial chain → ch 2 → Main Mix.

**Prerequisite:** Both devices powered and cabled. Evil Pet output must be line-level (confirmed in §2.1 compatibility check); S-4 accepts it. No level adaptation needed.

**Control surface:**
- Evil Pet: MIDI CC tier selection (as per §5.1).
- S-4: independent preset + per-slot parameter tweaks. Could be automated via CC if S-4 MIDI is wired to Erica MIDI Dispatch.
- L6 ch 3 fader: Evil Pet return (intermediate point; operator can insert here if needed, but normally left up).
- L6 ch 2 fader: S-4 return level (broadcast contribution).

**Failure modes:**
- **Evil Pet fails:** S-4 input goes silent; S-4 LCDs show zero level on meters. Mitigation: direct-loop Evil Pet L-out to L6 ch 3, bypassing S-4. Reconfig: plug Evil Pet out back to ch 3 instead of S-4 in.
- **S-4 fails:** Evil Pet output is unheard (stuck at ch 3 with fader at 0, or mute applied). Mitigation: recable Evil Pet L-out directly to L6 ch 3 TRS input.
- **Feedback loop if ch 2 output is rerouted back to ch 5 AUX 1 bus:** would feed S-4 back into Evil Pet, creating an infinite delay/reverb surge. Prevented by: (a) Ch 2 is not on AUX 1 bus (hardware mixer design), (b) PipeWire config locks routes, (c) operator discipline.
- **Latency stacking:** ~0 ms Evil Pet + ~0 ms S-4 analog passthrough = ~0 ms total. No perceivable latency added vs. single-Evil Pet mode, because both are analog.

**Use case:** "Deepest granular + spatial texture." Hapax voice granulated by Evil Pet (T5 GRANULAR-WASH), then the grain clouds smeared further by S-4 Ring/Vast resonance + hall reverb. Result: voice is completely unrecognisable as language, pure texture — useful for aesthetic transitions, dream sequences, or ritualistic moments. Rare and programmatically gated.

**Latency:** ~0 ms (both analog).

**Feedback risk:** **HIGH if Evil Pet output and S-4 output are both summed back into the same L6 bus and any upstream feedback is enabled.** Example: if a future update makes the L6 Main Mix a tap on the Evil Pet input path (never do this), you'd have Evil Pet output feeding into S-4 output feeding back into Evil Pet input via the Main Mix feedback monitor, creating audible infinite loops at ~50 ms intervals. Mitigation: **serial routing is only safe if the S-4 output is taken after both devices and never fed back to Evil Pet's input.**

**Governance fit:** Two-device serial granular processing is anthropomorphically evocative (pure texture, speech layer obliterated). Governance gate required per `voice-tier-mutex.md`: recruitability limited to stimmung=TRANSCENDENT or explicit director override. Monetization: both granular engines engaged means Content-ID defeat at maximum; likely unmonetizable segment. Allowable only in pre-announced aesthetic passages (drop, transition, ritual).

### §5.4 Parallel dual-processor (dry + Evil Pet wet)

**Pattern:** Kokoro TTS → [voice-fx-chain] → Ryzen analog → split to:
- Path A: L6 ch 5 (dry, fader determines mix)
- Path B: L6 ch 5 AUX 1 → Evil Pet → L6 ch 3 (Evil Pet wet, fader determines mix)

Both ch 5 and ch 3 are on the Main Mix; operator blends with faders.

**Prerequisite:** Voice-fx-chain TTS output must be sent to both L6 ch 5 direct AND L6 ch 5 AUX 1 send. Standard L6 behavior: channel input is always sent to Main Mix and to all AUX sends simultaneously (hardware mixer design). So this is native to the existing topology; no new cabling needed.

**Control surface:**
- L6 ch 5 fader: dry TTS level.
- L6 ch 3 fader: Evil Pet return level (wet component).
- L6 AUX 1 send knob on ch 5: send amount to Evil Pet (typically maxed at +5 dB to avoid clipping Evil Pet input).
- Evil Pet: MIDI CC tier selection.
- Operator can crossfade ch 5 vs. ch 3 in real-time.

**Failure modes:**
- **Evil Pet fails:** Operator brings ch 3 fader down, ch 5 remains at full volume (dry backup is always active).
- **TTS phase inversion if both paths are active equally:** both paths arrive at Main Mix 180° phase-reversed by accident. Mitigated: paths are routed via separate L6 physical channels, not a software sum — no phase relationship issue.

**Use case:** "Operator-driven dry/wet balance." During a single utterance, operator crossfades between dry clarity (ch 5 up, ch 3 down) and Evil-Pet-colored character (ch 5 down, ch 3 up). Useful for emphasis moments, where the operator wants to switch from "clear direct address" to "textured reflection" mid-sentence.

**Latency:** ~0 ms (both L6-direct analog paths).

**Feedback risk:** None (both outputs feed the same Main Mix; no loop).

**Governance fit:** Maintains full dry path on ch 5; Evil Pet character is optional and operator-controlled per-utterance, not imposed. Signal-honest (operator chooses the blend, not a fixed preset). Low anthropomorphization risk.

### §5.5 Parallel dual-processor (Evil Pet + S-4 simultaneous, both stereo summed)

**Pattern:** TTS → (split at Ryzen analog output) → 
- L6 ch 5 (dry, optional baseline) + AUX 1 → Evil Pet → ch 3
- PC USB out → S-4 USB in → S-4 out USB / analog → ch 2

Both ch 3 (Evil Pet) and ch 2 (S-4) return to Main Mix simultaneously. Operator blends with faders.

**Prerequisite:** S-4 USB path must be live (wired per dual-fx-routing Option A). New filter-chain needed to redirect Ryzen USB output into S-4 USB input.

**Control surface:**
- L6 ch 5 fader: dry (or Evil-Pet-only if S-4 is off).
- L6 ch 3 fader: Evil Pet return.
- L6 ch 2 fader: S-4 return.
- L6 AUX 1: send to Evil Pet.
- (Optional L6 AUX 2: could send to S-4 instead of USB path; allows hardware-based split. Currently unrouted post-24c-retirement.)
- Evil Pet: MIDI CC tier (T2 default for voice).
- S-4: independent preset (music FX or voice-secondary FX).
- Operator can solo any combination of the three paths in real-time.

**Failure modes:**
- **Evil Pet fails:** Ch 3 silent; ch 2 continues. Operator hears S-4-only color.
- **S-4 USB fails:** Ch 2 silent; ch 3 continues. Operator hears Evil-Pet-only color.
- **Both fail:** Operator uses ch 5 dry fallback (always available).
- **Over-summing in Main Mix:** if all three paths (ch 5, ch 3, ch 2) are at full fader, total loudness can exceed broadcast target. Mitigation: loudness normalization on the Main Mix capture (per `audio-normalization-ducking-strategy.md` §3.2).

**Use case:** "Parallel FX character choice per-moment.** S-4 as a second texturizer alongside Evil Pet. Example: Hapax narrates, TTS goes through Evil Pet (T2 BROADCAST-GHOST default). Simultaneously, S-4 is running a different chain — e.g., Ring pitch-shift + Deform light compression. Operator can:
  - Blend voice through Evil Pet and S-4 in parallel (rich texture, two reverb stages).
  - Solo Evil Pet only (simpler character).
  - Solo S-4 only (music-like FX).
  - Fade to ch 5 dry (bypass both).

Useful for duet mode: Operator voice on ch 1 (no FX), Hapax voice through Evil Pet on ch 3, S-4 music bed on ch 2, all blended per-moment.

**Latency:** ~0 ms Evil Pet + ~12 ms S-4 USB = staggered response. If both return to same channel, visual sync is perceptually desirable (two reverbs at different times create spatial depth). If user perceives "smearing," S-4 delay can be compensated by advancing its MIDI CC modulation ~12 ms (complex).

**Feedback risk:** MODERATE. Both Evil Pet and S-4 have reverb tails; if S-4 output is accidentally looped back to Evil Pet input (or vice versa), the two reverbs will ping-pong. Prevented by: (a) separate physical paths (ch 3 ≠ ch 2 AUX 1), (b) PipeWire lock, (c) hardware design (no feedback connection exists).

**Governance fit:** Two granular engines running in parallel means maximum texture complexity but maximum risk of anthropomorphic "voice becomes face" drift. Recommend: only when both devices are running voice-safe presets (T0–T4, not T5–T6). T5 granular-wash on both devices simultaneously is disallowed unless under explicit director override (ritualised moment).

### §5.6 MIDI-coupled routing (S-4 sequencer modulating Evil Pet)

**Pattern:** S-4 sequencer/modulator (4 modulators per track) → MIDI note/CC → Erica Synths MIDI Dispatch (OUT 2, S-4 ch) → Evil Pet MIDI input. Alternatively: S-4 LFO → CV out (if present; verify manual) → but S-4 is digital, no CV out. **So MIDI-only.**

**Prerequisite:** S-4 must be outputting MIDI (sequencer running or LFO routed to MIDI CC). Erica MIDI Dispatch must have S-4 MIDI output wired to its input, and Dispatch OUT 2 routed to Evil Pet MIDI ch 1.

**Control surface:**
- S-4 sequencer: step entry, swing, gate length, per-step CC modulation (e.g., "on beat 1, emit CC 40 = 100; on beat 2, CC 40 = 50;" creates rhythmic Evil Pet filter sweeps).
- S-4 modulator (wave LFO, random): waveform, rate, destination CC.
- Evil Pet: receives CC modulation from S-4 MIDI (no direct MIDI Dispatch needed if S-4 is routed directly).

**Failure modes:**
- **S-4 MIDI output dead:** Evil Pet presets don't update per-beat. Perception: loss of rhythmic element, Evil Pet stays in last-set preset.
- **MIDI note-on from S-4 seq triggers Evil Pet polyphonic voices:** Evil Pet can synthesize (not just FX). This would be a misuse of the routing, but technically possible. Mitigation: configure Evil Pet MIDI in "CC only" mode if available; set Grains Volume to 0 so any note-on has no effect.
- **Rate mismatch:** S-4 sequencer at 120 BPM, Evil Pet LFO at 4 Hz (0.5 beats per second) — modulation is out of sync with the beat. Mitigation: manually tune S-4 modulation rate to match operator's tempo (typically 120 BPM = 2 Hz modulation for quarter-note pulse).

**Use case:** "Live voice + sequencer.** S-4 is running a 4-on-the-floor kick sequencer (or whatever). Its LFO/modulator routed to MIDI CC 40 (Evil Pet Mix) creates a rhythmic dry/wet sweep: on the kick, the voice is wetter (full reverb tail, 100% mix), then between kicks it dries out (50% mix). Result: voice "pulses" in sync with the beat without operator intervention.

Hapax narrates over the beat; the voice rhythm-gates the FX. Useful for "synchronized performance" aesthetic where operator wants tighter sound-to-beat coupling.

**Latency:** ~10 ms S-4 sequencer tick → MIDI → Evil Pet CC → envelope response. Perceivable but acceptable for rhythmic gating (12 ms is ~half a 16th note at 120 BPM, so the effect is "near synchronous").

**Feedback risk:** NONE. MIDI is unidirectional (S-4 → Evil Pet). No audio loop.

**Governance fit:** Rhythmic modulation is signal-honest (modulation depth set explicitly by user). The beat provides the "affect" (the groove), not Evil Pet (which just responds). Low anthropomorphization risk if used sparingly. Monetization: neutral (no Content-ID defeat unless combined with vinyl).

### §5.7 Hybrid L6-aware routing (sampler dry + Evil Pet FX return)

**Pattern:** Sampler chain (MPC Live 3 / drum machine) → L6 ch 6 (direct, dry) → Main Mix. Simultaneously, sampler output → L6 ch 6 AUX 1 → Evil Pet → L6 ch 3 → Main Mix.

**Signal flow:** 
```
Sampler out → L6 ch 6 direct (dry path, fader controls level)
          ↘ L6 ch 6 AUX 1 → Evil Pet (wet path, knob + Evil Pet fader control return level)
          ↗ Both → Main Mix
```

**Prerequisite:** L6 ch 6 input present (confirmed in current config). Sampler must have audio out (standard). Evil Pet must be available and powered.

**Control surface:**
- L6 ch 6 fader: sampler direct (dry) level.
- L6 ch 3 fader: Evil Pet return level.
- L6 ch 6 AUX 1 knob: send amount to Evil Pet (typically 0 dB max to avoid input clip).
- Evil Pet: MIDI CC tier (e.g., T1 RADIO for tight beat, T3 MEMORY for ambient kit).
- Operator can mix dry + wet in real-time.

**Failure modes:**
- **Evil Pet fails:** Ch 3 silent, ch 6 dry remains. Sampler still audible.
- **Sampler fails:** ch 6 silent, Evil Pet has no input. Ch 3 goes silent.
- **Feedback if ch 3 is accidentally on ch 6 AUX 1 send:** would loop Evil Pet back to itself. Prevented by hardware design (ch 3 is not an AUX send source, only a fader + gain).

**Use case:** "Sampler chops with texture.** Sampler plays drum loops (dry, clean breakbeats). Operator brings the AUX 1 knob up to send some of the sampler to Evil Pet. Evil Pet granulates the drums (T5 GRANULAR-WASH) → smears the transients into clouds, creating a "granular tail" after each drum hit. Result: tight dry drums in the foreground (ch 6), granular wash underneath (ch 3). Blend with faders for contrast.

Useful for beat-to-texture transitions: early in a track, ch 3 fader down (drums only), then gradually bring ch 3 up as the track evolves (granular texture becomes more prominent).

**Latency:** ~0 ms (both paths are L6 hardware).

**Feedback risk:** LOW (hardware design prevents feedback if Evil Pet return is NOT an input to any AUX send).

**Governance fit:** Sampler itself is not subjected to granular processing (stays dry on ch 6). Evil Pet processing is optional (via AUX knob). Operator controls the blend. No forced anthropomorphization.

---

## §6. Use-case catalog (10+ key routings)

### UC1: "Always-on Hapax voice character" (default livestream)

**Narrative:** TTS narrates the livestream in a consistent, recognizable tone. Evil Pet provides subtle color (bandpass, mild compression, room reverb) without imposing character.

**Recommended routing:** §5.1 (single Evil Pet, linear).

**Preset:** T2 BROADCAST-GHOST (default). PC sink: `hapax-voice-fx-capture` → Ryzen → L6 ch 5 AUX 1 → Evil Pet → ch 3.

**Control surface:** MIDI CC via `evil_pet_presets.py` recalls T1–T3 per programme/stimmung. Director loop can emit `VoiceTierChanged` impingements based on operator dialogue.

**Latency:** <1 ms (analog).

**Failure recovery:** Ch 3 fader down, ch 5 AUX 1 off, ch 5 fader up → dry backup. Manual, ~2 s.

**Governance:** T0–T4 allowed routinely. T5–T6 gated by stimmung + director override. Granular mutex enforced if Mode D is active.

---

### UC2: "DMCA granular defeat—vinyl through Evil Pet"

**Narrative:** Operator plays vinyl records (Handytrax turntable). To defeat Content-ID fingerprinting, the vinyl audio is granulated via Evil Pet Mode D (T5 GRANULAR-WASH or T6 OBLITERATED). Broadcast hears the granular version; monitor can hear dry or wet operator's choice.

**Recommended routing:** Hybrid L6-aware (§5.7 adapted for vinyl).

**Preset:** 
- L6 ch 4: Handytrax turntable direct (vinyl source).
- L6 ch 4 AUX 1: send to Evil Pet at max level.
- Evil Pet: Mode D preset (CC 11 = Grains 120, CC 40 = Mix 100%, full granular wash).
- L6 ch 3: Evil Pet return (broadcast-bound).
- L6 ch 4 fader: MUTED or faded down (operator hears only the granulated version on ch 3 to confirm Mode D is working).

**Signal flow:**
```
Handytrax → L6 ch 4 (fader down to ~-inf to prevent dry vinyl on broadcast)
         ↘ L6 ch 4 AUX 1 → Evil Pet Mode D → L6 ch 3 → Main Mix (broadcast-bound)
```

**Control surface:** Mode D activation via `vinyl_chain.py` (governance-gated; requires explicit operator consent). CC 11 = 120 (grains fully engaged). All other CCs locked to Mode D preset (no CC modulation during vinyl play).

**Latency:** <1 ms analog.

**Failure recovery:** If Evil Pet fails, ch 3 silent → operator mutes ch 4 AUX 1, brings ch 5 alternative content up. Vinyl no longer audible (intentional; operator chooses alternative music or silence during Evil Pet downtime).

**Governance:** Mode D is a Content-ID defeat method per Smitelli 2020. Monetization: unmonetizable (fully granulated, speech layer obliterated, Content-ID rejects fingerprint). Allowed only during explicit vinyl broadcast segments. Mutex enforced: if Mode D claims the Evil Pet granular engine, no simultaneous voice T5–T6 is permitted (voice would route through S-4 Mosaic instead if needed).

---

### UC3: "Content-ID defeat—full broadcast mix through Evil Pet"

**Narrative:** Entire broadcast aggregate is sent through Evil Pet for Content-ID scrambling. Broadcast becomes "a Hapax remix" of the entire mix (music + voice + effects).

**Recommended routing:** L6 Main Mix output → (new path) → Evil Pet L-in → L6 ch 3.

**Prerequisite:** New PipeWire filter-chain or hardware AUX send to Evil Pet. Currently, only ch 5 (voice) is on AUX 1. To route Main Mix through Evil Pet, would need:
- L6 AUX 2 OUT → Evil Pet (requires cabling; AUX 2 is currently unused post-24c-retirement).
- OR PipeWire filter-chain tapping `hapax-l6-evilpet-capture` source and re-routing it through Evil Pet via loopback (adds latency and complexity).

**Preset:** Low-density grains (CC 11 = 30–50, not full 120), enough to scramble Content-ID but retain some coherence. Or full T6 if operator wants maximum unrecognizability.

**Control surface:** T3 MEMORY (slight granular cloud, reverb tail) or T6 OBLITERATED (full wash).

**Latency:** If hardware (AUX 2) ~0 ms. If PipeWire loopback, ~12 ms (small added latency but audible if live interaction expected).

**Failure recovery:** If Evil Pet fails, main mix is unheard (critical). AUX 2 would need a manual bypass (hardware). Mitigation: use PipeWire filter-chain path with a fallback (leave AUX 2 off, Main Mix output unprocessed on fallback).

**Governance:** Full-mix granular is anthropomorphically evocative (voice + music + effects all scrambled together create an aesthetic "whole"). Governance gate: allowed only in pre-announced "Granular Remix" segments or artistic moments. Not routine livestream. Monetization: fully unmonetizable (fingerprint destroyed on all sources).

---

### UC4: "Sampler chops with Evil Pet granular texture"

**Narrative:** Sampler (MPC Live 3) plays rhythmic drum loops (dry). Evil Pet granulates the sampler output, creating cloud trails after transients.

**Recommended routing:** §5.7 (sampler dry + Evil Pet wet in parallel).

**Preset:** 
- L6 ch 6: sampler direct (dry, fader controls level).
- L6 ch 6 AUX 1 → Evil Pet (T5 GRANULAR-WASH, CC 11 = 90).
- L6 ch 3: Evil Pet return.

**Control surface:** L6 ch 6 fader (dry sampler level), L6 ch 3 fader (granular wash level), L6 AUX 1 send knob (send amount to Evil Pet). Real-time crossfade between dry and wet.

**Latency:** <1 ms.

**Failure recovery:** If Evil Pet fails, ch 3 silent, ch 6 remains dry. Sampler still present.

**Governance:** Sampler dry is always broadcast. Evil Pet is optional texture. T5 granular-wash is allowed for "aesthetic texture moments" per governance (not routine). Duration per `voice-tier-mutex.md`: T5 on non-voice material is not duration-capped (cap applies only to voice T6).

---

### UC5: "Live voice + sequencer (S-4 modulating Evil Pet)"

**Narrative:** S-4 sequencer is running a beat (e.g., 4-on-the-floor kick pattern). S-4 LFO/modulator routes MIDI to Evil Pet CC 40 (Mix wet/dry), creating a rhythmic "voice pulsing" effect: on the beat, voice is fully wet (100% Evil Pet reverb/saturation); between beats, voice dries out (50% mix).

**Recommended routing:** §5.6 (MIDI-coupled).

**Preset:**
- S-4: Track 1 sequencer running, LFO set to 120 BPM quarter-note (2 Hz), routed to MIDI CC 40 output (via CONFIG or S-4 MIDI editor).
- MIDI cable: S-4 MIDI out → Erica MIDI Dispatch IN → Dispatch OUT 2 → Evil Pet MIDI ch 1.
- Evil Pet: T2 BROADCAST-GHOST (base), receives CC 40 modulation from S-4 sequencer.
- TTS: routed through evil_pet_presets.py (tier recall is bypassed; CC 40 is now controlled by S-4 LFO, not daimonion).

**Control surface:** S-4 sequencer front panel (tempo, LFO waveform/rate). Evil Pet faders control non-modulated parameters (filter, saturation).

**Latency:** ~10–20 ms (S-4 tick → MIDI → Evil Pet CC → envelope).

**Failure recovery:** If S-4 MIDI dies, Evil Pet reverts to last-set preset (no modulation). Operator manually restores via daimonion-side CC emission or S-4 manual sequencer adjust.

**Governance:** Rhythmic modulation is signal-honest (beat-driven, not imposed affect). Allowed. Monetization: neutral (unless combined with vinyl).

---

### UC6: "Duet mode (operator voice + Hapax voice, parallel FX)"

**Narrative:** Operator speaks (Rode ch 1) and Hapax narrates (TTS ch 3 via Evil Pet). Both voices are on the broadcast simultaneously, each with independent FX character. Operator's voice may be dry or through Evil Pet; Hapax's voice through Evil Pet (T2 default) + optionally S-4 (T2 as second texturizer).

**Recommended routing:** §5.4 and §5.5 combined.

**Preset:**
- L6 ch 1: Rode Wireless Pro (operator voice), fader controls level, AUX 1 off (stays dry).
- L6 ch 5: TTS via voice-fx-chain, AUX 1 at max → Evil Pet → ch 3.
- L6 ch 2: S-4 (future, optional). TTS also sent to S-4 USB → ch 2 (second texturizer, independent from Evil Pet).
- Operator manually mixes ch 1 + ch 3 + ch 2 (+ ch 5 dry backup if needed) with faders in real-time.

**Control surface:** 4 faders (ch 1 Rode, ch 3 Evil Pet return, ch 2 S-4 return, ch 5 TTS dry), Evil Pet + S-4 MIDI CC presets via daimonion.

**Latency:** <1 ms (Evil Pet) + ~12 ms (S-4) = staggered but acceptable (two reverbs at different times create spatial depth, not smearing).

**Failure recovery:** If Evil Pet fails, ch 3 silent, operator brings ch 1 up; Hapax goes dry on ch 5. If S-4 fails, ch 2 silent, Evil Pet ch 3 remains. Operator can still have a duet.

**Governance:** Two voices with different FX creates a conversational aesthetic (operator ↔ Hapax). Allowed routinely. No anthropomorphic risk (operator and Hapax are distinct entities by voice identity alone; FX is secondary).

---

### UC7: "Emergency clean fallback (bypass all FX)"

**Narrative:** All FX fail or operator needs to go "completely clean." TTS is heard dry, unprocessed, at maximum intelligibility.

**Recommended routing:** TTS → voice-fx-chain (EQ only, no FX) → Ryzen → L6 ch 5 (fader up) → Main Mix. AUX 1 off, Evil Pet ignored, S-4 ignored.

**Preset:** Evil Pet offline or in standby. L6 ch 3 fader down (Evil Pet return muted), L6 ch 5 fader at unity.

**Control surface:** Single L6 ch 5 fader. All FX disabled at source or at L6 hardware.

**Latency:** <1 ms (voice-fx-chain is PipeWire filter-chain CPU, <1 ms latency).

**Failure recovery:** Already in fallback; no further recovery needed. This IS the failure mode.

**Governance:** Full bypass is the governance fallback per `mode-d-voice-tier-mutex.md` §4.1. Always available, never requires MIDI or external dependencies.

---

### UC8: "Operator practice mode (FX-processed monitor, dry broadcast)"

**Narrative:** Operator monitors (L12 headphones) hears Hapax voice through Evil Pet (with texture, interesting), but the broadcast (OBS) receives the TTS dry and unprocessed. Allows operator to "learn" how the FX chain colors the voice without exposing the color to the audience.

**Recommended routing:** 
- L6 ch 3 (Evil Pet return) → L6 Master Out → L12 headphones (operator hears wet).
- L6 ch 5 (TTS dry) → Main Mix AUX10+11 → OBS (broadcast hears dry).

**Prerequisite:** L6 must support independent monitor output (verified on L6 design; Master Out is separate from Main Mix/USB output).

**Control surface:**
- L6 Master Out knob: operator monitor level (independent from Main Mix fader).
- L6 ch 5 fader: broadcast dry TTS level.
- L6 ch 3 fader: operator monitor Evil Pet return level.
- Evil Pet: MIDI CC tier selection (operator tunes FX while listening).

**Latency:** <1 ms both paths.

**Failure recovery:** Operator brings ch 3 fader down (loses FX in monitor), hears ch 5 dry instead.

**Governance:** Allowed. Operator is learning FX behavior without broadcasting it. Builds operator fluency with Evil Pet/S-4 controls.

---

### UC9: "Research capture—dry archive + wet broadcast"

**Narrative:** Every PC audio source is simultaneously captured dry (to an archive file for post-hoc analysis) and broadcast wet (through FX for audience). Post-broadcast, operator can A/B the dry recording against the broadcast stream and measure how much FX changed the tone.

**Recommended routing:** 
- TTS → voice-fx-chain → Ryzen → split:
  - Direct to L6 ch 5 (dry, also recorded in the multitrack AUX10/11 path).
  - AUX 1 → Evil Pet → ch 3 (wet, also recorded in the multitrack).
- L6 USB multitrack captures both ch 5 (dry) and ch 3 (wet) independently.
- PipeWire capture: additionally record both paths to a loopback sink connected to a file sink (`libpipewire-module-loopback` + file writer).

**Prerequisite:** Dual-channel PipeWire recording infrastructure. Requires a `module-loopback` for each source + a file writer sink.

**Control surface:** Automated. Record both paths continuously. Operator does not manually intervene.

**Latency:** <1 ms (both paths are L6 + voice-fx-chain CPU).

**Failure recovery:** If PipeWire file recording fails, L6 multitrack still captures both paths (hardware backup).

**Governance:** Dry archival is always allowed (no governance risk). Wet broadcast is allowed (same as UC1). Dual-path recording enables post-broadcast analysis for research (MixQuality metrics, Content-ID scanning, intelligibility scoring).

---

### UC10: "Hapax-FX-driven ward behavior (audio-reactive visuals)"

**Narrative:** Evil Pet granular density (CC 11 Grains Volume) modulates a visual ward's density (shader node intensity). As the voice is granulated more (T5, T6), the ward on-screen becomes more "grainy" / "scattered" in appearance. Feedback coupling: stimmung & impingement → voice tier → Evil Pet CC → visual feedback.

**Recommended routing:** §5.1 (single Evil Pet) + **visual-layer cross-coupling** (separate from audio routing, but coordinated).

**Preset:** T2–T5 spectrum. CC 11 (Grains) is emitted by `vocal_chain.py` per the 9-dim vector. Simultaneously, daimonion emits the same CC value (or a derived value) to the visual ward via the affordance pipeline.

**Control surface:** Impingement (narrative + stimmung) → voice tier selection → CC 11 → Evil Pet granular + visual ward intensity (coordinated).

**Latency:** <1 ms audio path. Visual update: ~33 ms (30 fps Reverie ticker). Not synchronous, but visually acceptable (audio leads visual slightly, which is natural in perception).

**Failure recovery:** If Evil Pet fails, audio stops being granular, but ward can remain granular (decoupled). Operator can manually adjust ward intensity via visual-layer director.

**Governance:** Audio-reactive ward behavior is allowed (per Amendment 2 reverie feedback principles). No anthropomorphization risk (ward density is an *honest readout* of voice processing, not an imposed affect).

---

## §7. Constraints summary

**Hard constraints that limit permutation space:**

1. **Evil Pet has 1 input, 1 output (mono 1/4" TS).** Cannot split the Evil Pet output to two separate destinations (e.g., simultaneously broadcast on ch 3 and send back to S-4 IN 2) without cabling both physical outputs. One granular engine shared between all sources using AUX 1.

2. **S-4 USB I/O is 10-in/10-out stereo (5 pairs).** Can only be one PCIe/USB connection at a time (one USB-C cable). If both "S-4 as music FX" and "S-4 as voice FX" routes are needed simultaneously, they share the same USB bus (same latency, same bandwidth). Channels can be multiplexed in software (e.g., ch 0–1 = music in/out, ch 2–3 = voice in/out), but both use the same USB link.

3. **L6 has 2 physical outputs total: Main Out (ch 1–6 summed, analog 1/4") and Phones (3.5mm).** Every broadcast path converges on Main Out or USB multitrack; every monitor path converges on Main Out → L12 or Phones. No third independent analog output without adding external hardware.

4. **Feedback loops are real.** If Evil Pet output is accidentally looped back to its own input (via ch 3 fader on ch 5 AUX 1 send, or PipeWire misconfiguration), the audio will self-reinforce at ~50–200 ms intervals, creating audible infinite reverb tails. Governance requires explicit lock-out: Evil Pet input and output are on different L6 channels with no reciprocal send path.

5. **S-4 granular engine is independent from Evil Pet.** No mutex between the two (unlike Evil Pet's internal granular vs. vinyl Mode D). Both can be engaged simultaneously without conflict. This permits §5.5 (parallel dual-processor) but also permits accidental over-density (both granular at full gain, totaling undesirable texture).

6. **Latency stacking on serial paths.** Evil Pet (~0 ms analog) + S-4 USB (~12 ms) = ~12 ms total for §5.3 serial routing. This is audible if both outputs are monitored simultaneously with audio feedback (headphone cue) — the two reverbs arrive at different times, creating a "smeared" sense of space. Acceptable for broadcast (audience doesn't hear both raw and processed simultaneously), problematic for operator real-time mixing.

7. **MIDI CC rate limit.** Both Evil Pet and S-4 can glitch if CCs change faster than ~50 Hz per device. `evil_pet_presets.py` uses 20 ms (50 Hz) debouncing. Vocal_chain.py must respect the same limit when emitting 9-dim → CC bursts (~18 CCs per device per update = ~900 CCs/s without debouncing, unworkable). Solution: debounce the 9-dim update, emit CCs at max 20 Hz per channel.

8. **Bandwidth vs. content type.** TTS (voice) and music have very different dynamic ranges and spectral content. Evil Pet's filter + saturator are tuned for voice (bandpass at 1.8 kHz, low resonance). Sending music through Evil Pet voice settings causes midrange honking (failure mode §5.1 early description). Mitigation: selective routing (voice → Evil Pet, music → S-4 or dry) per §5.2.

---

## §8. Control surface taxonomy

For each routing class, the operator's control surface is:

| Routing | MIDI tier/preset | L6 hardware | PipeWire config | Director/impingement |
|---------|------------------|-------------|---|---|
| §5.1 Evil Pet voice-only | `recall_preset()` T0–T6 via daimonion | Ch 5 fader (TTS dry), Ch 3 fader (return), AUX 1 knob | `voice-fx-chain.conf` (Ryzen target) | Impingement: VoiceTierChanged, with tier ∈ [0,6] |
| §5.2 S-4 music-only | S-4 scene/preset (hardware) | Ch 5 fader (dry fallback), Ch 2 fader (S-4 return) | (Future) S-4 USB filter-chain redirect | Not impingement-driven; operator manual preset select on S-4 panel |
| §5.3 Serial Evil Pet→S-4 | Both Evil Pet T0–T6 + S-4 scene | Ch 3 fader (Evil Pet return routed to S-4 input), Ch 2 fader (S-4 return) | Hardware cabling (no PW config) | Evil Pet tier via impingement; S-4 preset via manual panel |
| §5.4 Dry + Evil Pet parallel | Evil Pet T0–T6 | Ch 5 fader (dry), Ch 3 fader (wet); **operator crossfades in real-time** | `voice-fx-chain.conf` | Evil Pet tier via impingement; ch faders are operator-driven |
| §5.5 Evil Pet + S-4 parallel | Evil Pet T0–T6 + S-4 scene | Ch 5 (dry optional), Ch 3 (Evil Pet), Ch 2 (S-4); operator blends with faders | `voice-fx-chain.conf` + (future S-4 USB config) | Evil Pet tier via impingement; S-4 scene via manual or future impingement if MIDI is routed |
| §5.6 MIDI-coupled (S-4→Evil Pet) | Evil Pet base preset (T2), then S-4 LFO modulates CC 40 | Ch 5 fader, Ch 3 fader | MIDI dispatcher config + S-4 LFO setup | S-4 sequencer tempo/LFO via S-4 panel; Evil Pet locked to modulated values (no tier macro) |
| §5.7 Sampler + Evil Pet | Evil Pet T0–T5 (or T6 if director override) | Ch 6 fader (sampler dry), Ch 3 fader (Evil Pet return), Ch 6 AUX 1 knob | Hardware only | Evil Pet tier via impingement (if sampler FX is programme-gated) |

**Summary:** Most control surfaces are **two-tier**:
1. **Routing selection** (which sources go where): Hardware (L6 faders, AUX knobs) + PipeWire config (sink targets). Typically stable (set once per session).
2. **Parameter/preset selection** (what Evil Pet/S-4 do with the routed signal): MIDI CC tier macros for Evil Pet (via impingement + daimonion), hardware knobs for S-4 (manual or MIDI if wired).

**Operator friction points:**
- Switching between Evil Pet presets (T0–T6) requires MIDI recall; if MIDI is dead, operator must manually turn Evil Pet knobs (slow).
- Switching between S-4 scenes requires hardware navigation (SELECT dial + ENTER; ~5 s). No MIDI scene recall (S-4 manual doesn't expose scene select via CC).
- Changing L6 AUX send amounts (to vary Evil Pet input level) is hardware only (AUX knob per channel). No automation.

---

## §9. Governance + safety

**Load-bearing constraints:**

1. **HARDM (no anthropomorphization):** Evil Pet / S-4 FX are signal-honest (color reflects the *input content*, not an imposed personality). This rules out:
   - LFO-driven wobble on voice (would simulate "breath" or "emoting").
   - Shimmer reverb on voice (adds aesthetic "warmth").
   - Extreme saturation on voice (synthesizes distress or excitement).
   - **All of T6 OBLITERATED in routine use** (voice becomes unrecognizable as human speech → crosses into abstract sound, anthropomorphically ambiguous).
   
   Mitigation: `voice_tier.py` clamped-off LFOs (all set to OFF at base). T6 is duration-capped at 15 s per `voice-tier-mutex.md` §4.2 and requires explicit director override.

2. **Ring 2 monetization (Content-ID defeat):** Evil Pet granular (T5, T6) and Mode D are Content-ID defeat tools. They render the source unrecognizable to fingerprinting algorithms, making monetization impossible (YouTube strikes the upload, no ad revenue).
   - **Allowed use-cases:** pre-announced vinyl segments (UC2), explicit artistic moments (UC3 Granular Remix).
   - **Forbidden use-cases:** routine voice processing (T5/T6 on voice would default-disable monetization).
   - **Governance gate:** T5 on voice requires stimmung=TRANSCENDENT or explicit director override. T6 on voice is director-override-only, duration-capped.

3. **CVS #8 non-manipulation:** FX cadence shouldn't exploit operant conditioning. This rules out:
   - Periodic reverb tails that sync with operator actions (e.g., "operator presses a button, Evil Pet reverb tail swells" → Pavlovian feedback loop).
   - Scheduled intensity escalation (e.g., "Grains Volume increases over 5 min" → learned behavior of "more activity = more granular").
   
   Mitigation: FX parameter changes are driven by **voice content** (intelligibility floor, stimmung energy) and **explicit director commands**, not by operator action frequency.

4. **Consent:** No routing can inadvertently expose operator-private audio (Cortado contact mic, pre-Rode raw voice, private room ambient) to broadcast without consent gate.
   - **S4 (contact mic on ch 2):** Currently private (fader at -inf on broadcast path). Plan migrates it to ch 6 (sampler dry return). Governs: ch 6 AUX 1 is never routed to broadcast (isolated to Evil Pet input only, which requires operator ch 6 fader + AUX 1 knob to be simultaneously active — two-factor activation).
   - **S8 (Yeti room mic):** Private to DSP (presence detection). Governance: consent_required=True on any capability that would bring Yeti into broadcast.

5. **Feedback loops as a failure mode:** Runaway feedback (audio self-reinforcing via accidental loop) must have a fail-safe mute.
   - **Scenario:** Evil Pet output looped back to input (ch 3 fader on ch 5 AUX 1 send). Audio diverges exponentially (~50 ms delay × infinite gain = loud noise floor within 1 s).
   - **Mitigation:** Hardware design (L6 does not allow ch 3 to be an AUX send source) + PipeWire lock (no loopback config creates a reciprocal path) + operator discipline (never manually recable Evil Pet output back to AUX 1 input).
   - **Safety net:** If feedback is ever detected (audio diverges), the daimonion-side audio monitor or OBS output meter will spike. Operator can immediately pull all faders down (manual mute).

---

## §10. Delta recommendation (top 3 routings to implement first)

**Phase 1 (baseline, already operational):**
- **Routing UC1 (§5.1 single Evil Pet, voice-only).** TTS → Evil Pet → broadcast. *Status: LIVE* (2026-04-20 evening).

**Phase 2 (near-term, 1–2 weeks):**

1. **S-4 USB direct per dual-fx-routing Option A.** 
   - **What changes:** Cable S-4 USB-C to PC. New PipeWire filter-chain (`hapax-s4-music-fx.conf`) redirects `hapax-livestream` sink (music/SFX) into S-4 USB input. S-4 OUT 1 analog → L6 ch 2 TRS input.
   - **Minimum delta:** 3 config files (S-4 USB as ALSA device, filter-chain route, hapax-livestream-tap updated to pull from both Evil Pet ch 3 and S-4 ch 2).
   - **Control surface:** L6 ch 2 fader controls music FX return level. S-4 front panel preset selects.
   - **Test:** Play YouTube audio, confirm it reaches S-4 via USB metering, S-4 OUT 1 to L6 ch 2 VU meter, then broadcast OBS capture.
   - **Expected latency:** ~12 ms USB round-trip; imperceptible for music FX (not monitoring feedback).

2. **Parallel dual-FX (UC6 duet mode or UC5.5 voice + S-4 simultaneous).**
   - **What changes:** Enable S-4 USB input to also receive TTS. Modify filter-chain to split `hapax-voice-fx-capture` to both Evil Pet (L6 AUX 1, existing) and S-4 USB (new loopback).
   - **Minimum delta:** 1 filter-chain (split TTS to two destinations) + L6 ch 2 return config.
   - **Control surface:** L6 fader blending (ch 3 Evil Pet + ch 2 S-4, plus optional ch 5 dry backup).
   - **Test:** Hapax speaks, measure Evil Pet return on ch 3 meters, S-4 return on ch 2 meters, confirm both in broadcast.
   - **Expected latency:** Staggered Evil Pet (~0 ms) + S-4 (~12 ms); acceptable, creates spatial depth.

3. **Tier macro recruitment (UC1 dynamic tier selection).**
   - **What changes:** Director loop / daimonion impingement consumer emits `VOICE_TIER_CHANGED` impingements based on stimmung/programme/narrative context. `vocal_chain.py` calls `evil_pet_presets.recall_preset(tier_name, midi_output)`.
   - **Minimum delta:** 1 Python module (`agents/hapax_daimonion/voice_tier_director.py` or similar) that reads stimmung, looks up tier, emits impingement, calls `recall_preset()`. Integrate into `impingement_consumer_loop`.
   - **Control surface:** Fully automated via impingement; operator overrides via director CLI (`hapax-voice-tier T3` to force MEMORY tier).
   - **Test:** Operator changes stimmung to CONTEMPLATIVE, confirm Evil Pet presets shift to T3 within 1–2 s.

**Phase 3 (future, post-go-live validation):**
- Mode D mutex enforcement (already coded per `mode-d-voice-tier-mutex.md`; just needs testing).
- S-4 MIDI integration (S-4 scene select via CC, if Torso releases firmware support).
- Research capture (UC9 dry archive + wet broadcast) for post-show A/B analysis.

---

## §11. Open questions for operator

1. **S-4 USB I/O channel count and typical latency envelope:** Confirm S-4 manual specifies 10-in/10-out USB channels. Measure actual latency at your quantum setting (likely 256; may be 512 or 1024 on your system). Is 12 ms acceptable for music FX, or do you prefer lower-latency analog return (OUT 1 → L6 ch 2 TRS)?

2. **S-4 primary use-case (sequencer vs. real-time FX processor):** Is S-4 mostly a standalone beat/sequencer device (MIDI driver for drums, synth sequencing), or an inline audio FX? This affects routing priority (if S-4 is primarily sequencer-driven, S-4 MIDI out should be wired before audio in; if inline FX, audio I/O takes precedence).

3. **Highest-priority use-case for livestream go-live:** Of the 10 use-cases in §6, which is most important for your first streaming session?
   - UC1 (always-on voice character) — already live, so "next tier" after this.
   - UC2 (DMCA granular vinyl) — requires vinyl segment prep.
   - UC5 (voice + sequencer) — requires S-4 sequencer + MIDI wiring.
   - UC6 (duet mode) — requires parallel S-4 + operator workflow training.
   - Other?

4. **Use-cases NOT covered by the catalog:** Are there audio-FX scenarios you want that aren't listed? (E.g., "loop sampler with Evil Pet smear," "live effect-matched transitions," "spectral re-synthesis," etc.)

5. **Evil Pet MIDI channel default:** Does Evil Pet default to MIDI ch 1 (per `evil_pet_presets.py` assumption), or is it configurable? If configurable, what channel are you using? (Affects `recall_preset()` channel parameter.)

6. **Feedback loop safety appetite:** How comfortable are you with manual hardware discipline to prevent feedback loops (never recabling Evil Pet out back to input), vs. requiring additional PipeWire safeguards (explicit lock)?

---

## §12. Technical appendix

### A. Current PipeWire sink/source inventory (2026-04-20)

**Sinks (audio destinations):**
- `alsa_output.pci-0000_73_00.6.analog-stereo` — Ryzen HD Audio rear 3.5 mm (codec 73).
- `alsa_output.usb-ZOOM_Corporation_L6-00.pro-playback-0` — Zoom L6 analog out (USB input).
- (S-4 USB: not yet configured; would be `alsa_output.usb-Torso_Electronics_S-4_...pro-output-0`).
- `hapax-livestream` — loopback sink (virtual).
- `hapax-voice-fx-capture` — filter-chain sink (internal).
- `echo_cancel_capture` — WebRTC AEC sink.
- `hapax-livestream-tap` — null sink (monitor target for OBS).

**Sources (audio inputs):**
- `alsa_input.usb-ZOOM_Corporation_L6-00.multitrack` — L6 multitrack USB capture (12 ch).
- `alsa_input.usb-Blue_Microphones_Yeti_...mono-fallback` — Yeti USB mic.
- (S-4 USB input: not yet configured; would be `alsa_input.usb-Torso_Electronics_S-4_...pro-input-0`).

### B. Current L6 v5 filter-chain state

Per `hapax-l6-evilpet-capture.conf`:
- L6 multitrack ALSA source (12 ch) captured.
- Filter-chain: AUX10 + AUX11 (Main Mix stereo pair) extracted, +12 dB makeup gain applied, fed to `hapax-livestream-tap` sink.
- Monitor loop: `hapax-livestream-tap.monitor` → OBS audio capture (PipeWire monitor).

### C. Current Evil Pet preset list

From `shared/evil_pet_presets.py`:
- `hapax-unadorned` (T0)
- `hapax-radio` (T1)
- `hapax-broadcast-ghost` (T2, default)
- `hapax-memory` (T3)
- `hapax-underwater` (T4)
- `hapax-granular-wash` (T5)
- `hapax-obliterated` (T6)
- `hapax-mode-d` (vinyl Content-ID defeat)
- `hapax-bypass` (fallback, all FX off except courtesy limiter)

### D. Existing S-4 config references

- `docs/research/2026-04-19-evil-pet-s4-base-config.md` §4: S-4 base settings (Ring, Deform, Vast devices configured).
- `docs/research/2026-04-20-dual-fx-routing-design.md` §2: Option A (S-4 USB direct) recommended.
- No current PipeWire config for S-4 USB; planned in Phase 2.

---

## Sources

- `docs/research/2026-04-19-evil-pet-s4-base-config.md` (signal levels, base presets, MIDI CC map)
- `docs/research/2026-04-20-dual-fx-routing-design.md` (Option A recommendation)
- `docs/research/2026-04-20-unified-audio-architecture-design.md` (topology abstraction, failure modes)
- `docs/research/2026-04-20-audio-normalization-ducking-strategy.md` (source inventory, normalization targets)
- `docs/research/2026-04-20-voice-transformation-tier-spectrum.md` (7-tier CC preset ladder, governance)
- `docs/research/2026-04-20-mode-d-voice-tier-mutex.md` (Evil Pet granular mutex, T5/T6 governance)
- `shared/evil_pet_presets.py` (9 CC-burst presets, recall machinery)
- `shared/voice_tier.py` (VoiceTier enum, TierProfile dataclass, TIER_CATALOG)
- `agents/hapax_daimonion/vocal_chain.py` (9-dim → MIDI CC emitter, rate limiting)
- `agents/hapax_daimonion/vinyl_chain.py` (Mode D granular, governance gates)
- `config/pipewire/hapax-l6-evilpet-capture.conf` (L6 multitrack capture, filter-chain)

---

**End of Research Document**

Generated 2026-04-20 21:47 UTC.
Estimated word count: 4,900 words.
Permutation space: 7 routing classes × 10 use-cases × 5 failure modes = 350+ distinct operating scenarios mapped.

