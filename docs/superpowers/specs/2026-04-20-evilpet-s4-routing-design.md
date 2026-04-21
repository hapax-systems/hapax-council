---
date: 2026-04-20
author: delta
audience: operator + implementation (alpha)
status: Phase S — formal specification, decision-committed
register: scientific, neutral

parent_research: docs/research/2026-04-20-evilpet-s4-routing-permutations-research.md (775 lines, 7 topologies, 10 use cases, top-3 recommendations)
parent_queue: ~/.cache/hapax/relay/delta-queue-evilpet-s4-routing-research-20260420.md (operator directive)

related_specs:
  - docs/superpowers/specs/2026-03-31-homage-umbrella-stream-architecture.md (livestream envelope)
  - docs/superpowers/specs/2026-03-31-vinyl-broadcast-signal-chain.md (Mode D operator signal path)
  - docs/superpowers/specs/2026-04-20-voice-tier-director-integration.md (voice-tier routing decisions)

references:
  - shared/evil_pet_presets.py (9 CC-burst presets + BASE_SCENE constant)
  - shared/voice_tier.py (7-tier TIER_CATALOG, tier_capability_record, role defaults)
  - agents/hapax_daimonion/vocal_chain.py (9-dimension voice FX vector)
  - agents/hapax_daimonion/vinyl_chain.py (Mode D turntable/granular mutex)
  - ~/.config/pipewire/pipewire.conf.d/hapax-l6-evilpet-capture.conf (v5 filter-chain, per-channel presets)
  - ~/.config/pipewire/pipewire.conf.d/hapax-stream-split.conf (PC audio loopback routing)
  - ~/.config/pipewire/pipewire.conf.d/hapax-livestream-tap.conf (livestream sink consolidation)
  - shared/project_hardm_anti_anthropomorphization.md (HARDM governance on voice processing)
  - shared/project_soundcloud_bed_music_routing.md (SoundCloud bed-music bypass expectations)

---

# Evil Pet + Torso S-4 Routing Specification — Phase S

## §1 — Executive Summary

This specification locks the routing architecture for the Evil Pet (Endorphin.es analog FX processor, MIDI-CC-controlled) and Torso S-4 (USB audio interface + sculpting sampler) in the Hapax studio production chain. The design commits to three core routings shipping in Phase P (implementation), establishes control surface ownership (L6 AUX sends, software PipeWire sinks, MIDI dispatch), and validates governance invariants (anti-recognition, anti-opacity, voice-destruction consent gates).

Core decisions: (1) PC audio (Kokoro TTS) routes permanently to Ryzen line-out → physical cable → Evil Pet IN; (2) Evil Pet return on L6 CH3 feeds the v5 filter-chain AUX2 → livestream-tap at fixed +6 dB gain; (3) S-4 is a USB-direct audio source to livestream, independent of Evil Pet unless explicitly cabled; (4) L6 CH3 fader is the sole operator monitor path; all other channels contribute to livestream only via the filter-chain, not to monitoring.

---

## §2 — Scope and Non-Goals

### In Scope

- Routing topologies for PC-originated audio (Kokoro TTS) through Evil Pet and/or S-4
- Selected L6-originated audio sources (sampler chain via CH6, vinyl turntable via CH4 in Mode D) routed through Evil Pet for texture/content-defeat
- MIDI-CC control flow: Erica Dispatch → Evil Pet, S-4 MIDI 1 → Erica Dispatch → Evil Pet
- Signal quality validation: unity gain, no single-stage boosts >+6 dB unless downstream target <-18 dBFS, OQ-02 anti-opacity preservation
- Preset pack extension: routing-aware Evil Pet presets mapping to the three core routings
- S-4 USB-direct integration: sink routing, MIDI modulation coupling, latency bounds
- Control surface enumeration: which hardware knob, software parameter, or MIDI CC owns each routing decision
- Governance gates: HARDM consent (non-operator voice + Evil Pet granular), CVS #8 (S-4 sequencer exploitability), Ring 2 WARD classification (livestream-tap legibility)
- Test plan and rollout phases per Phase P plan

### Out of Scope (documented separately)

- Hardware acquisition (Evil Pet, S-4, cables already present; L6 already deployed)
- MIDI-CC control of L6 AUX sends (separate follow-up spec: MIDI-assignable L6 faders)
- Reverie visual synthesis coupling to Evil Pet / S-4 audio (visual recruitment pipeline live; audio-visual cross-coupling deferred)
- S-4 sampler playback mode (Material ≠ Bypass) — S-4 documented as audio-effect processor here; sequencer use case documented in separate spec
- Vinyl-specific granular presets beyond Mode D (turntable DMCA defeat scope complete in `shared/vinyl_chain.py`)

---

## §3 — Locked Architectural Invariants

These invariants are non-negotiable and apply to all three core routings and all secondary routings shipped as presets:

1. **PC audio → Evil Pet path is hardwired.** Kokoro TTS output → `hapax-voice-fx-capture` (PipeWire sink) → `hapax-private` loopback (at unity gain, default) → Ryzen analog out → physical RCA cable → Evil Pet 1/4" TS in (mono). This path exists in every routing. No exception: TTS cannot bypass Evil Pet without a separate operator-gated configuration (documented as emergency-fallback, not a shipping routing).

2. **Evil Pet output → L6 CH3 → livestream-tap.** Evil Pet 1/4" TS out → physical RCA cable → L6 CH3 line in (mono-L input). L6 CH3 pre-fader is captured via multitrack USB altset 2 (AUX2 position in the 12-channel multitrack). The v5 filter-chain `hapax-l6-evilpet-capture` pulls AUX2 → `gain_evilpet` mixer (default +6 dB, 2.0 linear gain) → `sum_l` / `sum_r` summing busses → `hapax-livestream-tap` sink (recorded to broadcast buffer). Operator's L6 physical CH3 fader drives monitoring only (via L6 → L12 analog monitor mix); the fader does NOT affect the USB pre-fader capture level.

3. **L6 CH3 fader is the ONLY active monitor path.** The operator hears (via monitors, not headphones — monitoring is line-level analog out from L6) only the Evil Pet return on CH3, with the CH3 fader controlling loudness. All other channels (CH1 Rode, CH2 Contact mic, CH4 Handy vinyl, CH5 PC line-out, CH6 Sampler) can be routed into the livestream-tap via the filter-chain, but their L6 physical faders and the L6 Master fader do NOT contribute to the analog monitor bus. The L6 Main Mix (AUX10+11 in the multitrack) is intentionally discarded (set to `null` in the filter-chain inputs) so that physical-fader moves don't affect broadcast.

4. **S-4 is USB-direct, not in the Evil Pet path.** Torso S-4 USB audio (10-in/10-out stereo pairs) plugs directly into the PC's PipeWire graph via `alsa_input/alsa_output` USB class-compliant driver. S-4 audio does NOT cable into Evil Pet; S-4 is a separate audio-effect processor that receives its own input from PipeWire or hardware line-in and outputs directly to the livestream-tap or to a dedicated monitoring sink. S-4 can modulate Evil Pet via MIDI (S-4 MIDI 1 → Erica Dispatch → Evil Pet MIDI in), but audio paths remain independent unless the operator explicitly cables S-4 OUT to Evil Pet IN (rare/experimental configuration).

5. **No physical-knob dependency beyond one-time AUX SEND configuration.** The L6 has two AUX SEND knobs per channel: AUX SEND 1 (→ Evil Pet IN) and AUX SEND 2 (→ MPC Live 3 IN). Once per session, the operator sets these knobs to route selected channels into Evil Pet (e.g., CH5 AUX SEND 1 up for PC audio feed, CH6 AUX SEND 1 up if sampler wet-path desired). After the one-time setup, AUX SEND knobs are not touched; software controls (filter-chain gains in `hapax-l6-evilpet-capture.conf`, MIDI CC via vocal-chain) manage the signal flow from that point.

6. **OQ-02 three-bound invariants apply to livestream-tap output.** The resulting livestream-tap stereo mix (after filter-chain summing) must satisfy anti-recognition (no face/person data in audio), anti-opacity (scene legibility threshold: signal not collapsed to single-hue abstraction), and anti-visualizer (no automated visual content sourced from audio energy). Evil Pet granular processing at T5/T6 risks spectral flattening (opacity violation); verified via Ring 2 WARD classifier post-render.

7. **L6 CH3 and Evil Pet output are feedback-protected.** Evil Pet output goes to L6 CH3 in, which pre-fader capture feeds livestream. The livestream-tap does NOT loop back into Evil Pet input; no risk of runaway acoustic or electrical feedback. The AUX SEND 1 knob on CH3 is turned off (set to 0) by operator protocol.

---

## §4 — Committed Routing Topologies

The three core routings from research §10 are formalized here with locked WHICH, HOW, SIGNAL PATH, CONTROL SURFACE, LATENCY, and FAILURE MODES.

### R1: Always-on Hapax Voice Character

**Use case:** Operator-oriented narration, podcast delivery, interactive TTS responses. Voice through Evil Pet is the default "Hapax character" — every utterance carries the studio's sonic signature.

**WHICH routing:** Kokoro TTS → Evil Pet (T2 BROADCAST-GHOST default, T0–T6 on demand) → L6 CH3 → livestream-tap.

**HOW:** 
- TTS engine outputs to `hapax-voice-fx-capture` PipeWire sink (Logos affordance pipeline + vocal_chain + tier selection)
- Sink target: `hapax-private` loopback at unity gain (operator tunable in `hapax-stream-split.conf`)
- `hapax-private` playback target: Ryzen analog out
- Physical RCA cable: Ryzen → Evil Pet IN
- Evil Pet receives 16-CC base scene (shared/evil_pet_presets.py::BASE_SCENE) + tier-specific overrides (shared/voice_tier.py::TIER_CATALOG[tier].cc_overrides)
- Evil Pet output: physical RCA cable → L6 CH3
- L6 multitrack USB altset 2, channel AUX2 (CH3 mono-L pre-fader)
- Filter-chain: `gain_evilpet` (+6 dB) → sum_l/sum_r → livestream-tap

**SIGNAL PATH (end-to-end latency):**
- Kokoro TTS: ~40 ms (CPU synthesis)
- Ryzen → Evil Pet analog: <1 ms (direct cable)
- Evil Pet MIDI latency: 1–2 MIDI ticks (~5–10 ms)
- Evil Pet audio latency: ~50–200 μs (analog passthrough + OLED roundtrip, negligible vs round-trip)
- L6 USB capture: ~5 ms (USB roundtrip at quantum 512)
- Filter-chain (realtime): <1 ms
- Total: ~55 ms TTS-to-broadcast. Operator monitoring (L6 CH3 fader → analog monitor out) is direct; no digital latency.

**CONTROL SURFACE:**
- `hapax-voice-fx-capture` sink: routed by Logos affordance pipeline; no manual knob touch required
- Tier selection: impingement-driven via narrative director (docs/superpowers/specs/2026-04-20-voice-tier-director-integration.md), subject to intelligibility budget
- Evil Pet preset recall: automated via `shared/evil_pet_presets.recall_preset()` on tier transition; MIDI emitted synchronously, no UI button required
- `gain_evilpet` filter-chain knob: operator tunes in `hapax-l6-evilpet-capture.conf` + reloads pipewire, or exposes via Logos overlay (deferred to Phase P §8)
- Operator monitoring: L6 CH3 physical fader only

**FAILURE MODES and Recovery:**

| Failure | Signal Path | Recovery |
|---------|-------------|----------|
| Evil Pet offline / no MIDI response | TTS → dead wire (no audio emerges) | L6 CH3 goes silent; operator hears nothing via monitor. Fallback: operator manually sets L6 CH5 AUX SEND 1 up so PC audio feeds Evil Pet-bypass path. (Emergency procedure; not shipped as a routing.)|
| MIDI port closed / MIDI Dispatch down | TTS plays, Evil Pet doesn't respond to CC, holds previous state | Voice still passes analog (Evil Pet is transparent at any granular level); no Content-ID protection if vinyl was Mode D. Retry MIDI dispatch; check dmesg for kernel errors. |
| L6 USB multitrack drops | TTS emitted, Evil Pet processes, L6 doesn't capture AUX2 | CH3 audio appears on operator's L6 monitor mix (analog), but doesn't reach broadcast. Check `pw-link -m` for broken connections; restart pipewire if needed. |
| PipeWire loopback lag / xrun | TTS → Ryzen loopback → underrun | Crackling in Evil Pet input; operator hears glitchy voice. Mitigation: quantum 512 (already deployed). If xruns persist, bump quantum higher or reduce system load. |

---

### R2: Sampler Wet/Dry Parallel

**Use case:** Sampler chain (Reloop 7 deck → MPC Live 3 → SP-404 MKII pair → MPC sampler) sends both dry and wet (Evil-Pet-processed) versions to broadcast simultaneously, permitting rhythmic interplay between unprocessed samples and granular texture.

**WHICH routing:** 
- Sampler dry return on L6 CH6 (mono-L) → filter-chain `gain_samp` → livestream-tap
- Sampler wet path: L6 CH6 → (operator sets AUX SEND 1 knob up) → Evil Pet IN → Evil Pet OUT → L6 CH3 → filter-chain `gain_evilpet` → livestream-tap (same as R1, but source is CH6 not TTS)

**HOW:** 
- Sampler chain outputs line level (stereo pair, operator sums to mono at the mixer or accepts L-only) into L6 CH6 input
- L6 CH6 pre-fader capture: AUX8 in multitrack → filter-chain `gain_samp`
- Operator sets L6 CH6 AUX SEND 1 knob to a desired level (e.g., 75%)
- Sampler signal splits: dry path (AUX8 directly to sum_l/sum_r) + wet path (AUX SEND 1 → physical cable → Evil Pet IN → Evil Pet OUT → L6 CH3 → AUX2 → sum_l/sum_r via `gain_evilpet`)
- Both paths converge in the livestream-tap stereo mix; wet and dry versions appear as separate tracks in the broadcast

**SIGNAL PATH (end-to-end):**
- Sampler → L6 CH6 line-in: <1 ms (analog)
- L6 multitrack capture (AUX8): ~5 ms (USB)
- AUX SEND 1 split: <1 ms (analog)
- Sampler → Evil Pet → L6 CH3: ~100–200 μs (analog passthrough, cable delay)
- L6 CH3 capture: ~5 ms (USB)
- Filter-chain: <1 ms
- Dry-to-wet skew: ~10 ms (L6 multitrack USB roundtrip + Evil Pet analog = negligible for rhythmic material at typical tempos <200 BPM)

**CONTROL SURFACE:**
- AUX SEND 1 knob (CH6): physical hardware, operator sets once per session
- `gain_samp` (dry path): software mixer in `hapax-l6-evilpet-capture.conf`, default 2.0 (tuned for sampler dynamics)
- `gain_evilpet` (wet path): software mixer, default 2.0 (matches Evil Pet return character)
- Evil Pet preset: operator selects via Logos UI or cc_overrides; sampler-optimized presets (proposed: "hapax-sampler-wet") engage granular engine at T5 by default
- Operator monitoring: L6 CH3 fader controls wet mix loudness; L6 CH6 fader controls dry mix loudness (both analog, pre-broadcast)

**FAILURE MODES:**

| Failure | Dry Path | Wet Path | Operator Experience |
|---------|----------|----------|----------------------|
| AUX SEND 1 knob stuck at 0 | Dry audible | No wet path | Sampler plays clean; operator expected to manually raise the knob |
| Evil Pet offline | Dry audible | Wet silent (AUX SEND 1 signal lost, no Evil Pet to resynthesize) | Asymmetric: only dry reaches broadcast; operator hears both monitors as CH6 fader + CH3 mute |
| L6 CH3 capture drops | Dry audible | Wet doesn't reach livestream (CH3 pre-fader not captured) | Dry preserved, wet lost; operator hears both via analog mixing but broadcast lacks texture |

---

### R3: S-4 as USB-Direct Content Source

**Use case:** Torso S-4 (Material=Bypass, Granular=Bypass/None, leaving 3-device linear chain: Filter → Color → Space) acts as an independent parallel audio processor for music content, samples, or additional voice. S-4 USB feeds a separate PipeWire sink routed to livestream-tap without touching Evil Pet.

**WHICH routing:** 
- S-4 input: either PipeWire sink routed from PC apps (live music playback, sampler loopback) or physical 1/4" line-in (from external hardware)
- S-4 processing: Filter → Color → Space (Material/Granular slots in Bypass)
- S-4 USB output: `alsa_output.usb-Torso_Electronics_S-4_...pro-output-0` PipeWire sink (ALSA card 6)
- S-4 output → PipeWire routing: either directed to a dedicated broadcast monitor sink or mixed into the livestream-tap via a secondary filter-chain path

**HOW:**
- S-4 USB audio interface appears to the Linux kernel as a 10-in/10-out class-compliant device (no proprietary drivers)
- PipeWire loopback module (or explicit module/sink in `~/.config/pipewire/pipewire.conf.d/`) creates `hapax-s4-content` sink for application routing (music playback apps route here)
- Physical 1/4" line-in (S-4 IN 1 or IN 2) also available; operator cables external hardware directly
- S-4 internal mixing: Track 1 = primary content track (Filter → Color → Space only); other 3 tracks optional (muted for basic config)
- S-4 USB output: main stereo pair (Track 1) routed to livestream-tap summing via a second filter-chain or direct mapping
- S-4 MIDI input: S-4 MIDI 1 connector (3.5mm TRS DIN jack) → Erica Dispatch → Evil Pet MIDI in; when S-4 is operating, MIDI from S-4 sequencer can modulate Evil Pet CC parameters

**SIGNAL PATH:**
- Music app → PipeWire → S-4 USB input: ~10 ms (USB latency + app buffering)
- S-4 internal processing (Filter, Color, Space): <1 ms per slot (realtime DSP)
- S-4 USB output → PipeWire: ~5 ms (USB roundtrip)
- Filter-chain (second path if separate): <1 ms
- Total: ~15–20 ms app-to-broadcast

**CONTROL SURFACE:**
- S-4 USB sink: created via PipeWire module or exposed as system sink in PipeWire config; applications select it as output device in their settings
- S-4 physical line-in: operator cables hardware and enables corresponding input selector on S-4 (via S-4 hardware buttons)
- S-4 processing parameters: controlled via S-4 hardware encoders (Filter frequency/resonance, Color amount, Space feedback/spread) or via MIDI CC from Erica Dispatch
- S-4 MIDI CC routing: S-4 MIDI 1 port (ALSA `client 40: 'S-4'`) receives sequencer or external controller output; Erica Dispatch routes S-4 MIDI CCs to Evil Pet MIDI channel (selectable CC map per preset or tie-in to R3's Evil Pet preset)
- S-4 ↔ Evil Pet sync (optional): S-4 MIDI clock out → Erica Dispatch (if Dispatch supports clock discipline) → Evil Pet MIDI clock in (if Evil Pet has sync support; verify hardware capability)

**FAILURE MODES:**

| Failure | Cause | Operator Observation | Recovery |
|---------|-------|----------------------|----------|
| S-4 USB drops (kernel driver error) | Kernel `device descriptor read/64, error -71` or similar | S-4 audio silent; other audio (Evil Pet path) unaffected | Unplug S-4, wait 10s, replug; retry PipeWire restart if needed; check dmesg. Device is not critical to broadcast (R1 + R2 still active). |
| S-4 MIDI port not found by Erica Dispatch | `S-4 MIDI 1` not enumerated after S-4 boot | S-4 audio works, but S-4 → Evil Pet CC modulation silent | `aconnect -i` to verify S-4 MIDI port number; if missing, restart Erica Dispatch or troubleshoot MIDI enumeration script |
| S-4 processing parameters saturate (Color/Space feedback runaway) | Operator sets Color and Space resonance high; feedback loop | S-4 output clips/distorts; livestream audio quality drops | Operator reduces Color amount and Space feedback knob; modulation limits are hardware-enforced (no digital runaway). |

---

## §5 — Secondary Routings (Shipped as Config Presets)

These routings are documented as preset configurations in the Evil Pet preset pack and are available on demand but not shipped as core broadcasters. Each is tested for Signal Quality invariants but receives lower operational priority than R1–R3.

### S5a: DMCA Granular Defeat (Mode D)

**Use case:** Operator plays vinyl turntable (Korg Handytraxx) through Evil Pet at T5/T6 granular character to defeat Content-ID recognition while preserving audibility.

**Routing:** L6 CH4 (Handytraxx stereo) → (operator sets AUX SEND 1 knob up) → Evil Pet IN → Evil Pet OUT → L6 CH3 → livestream-tap.

**Governance:** `docs/research/2026-04-20-mode-d-voice-tier-mutex.md` §4 documents the EVL granular engine mutex with voice tiers T5/T6. When Mode D is active, no voice-tier T5+ can route through Evil Pet's granular engine (same CC 11 resource); voice-tier T5/T6 requests fall through to S-4 Mosaic granular instead (alternative engine). Mode D uses `shared/evil_pet_presets.py::_MODE_D_CCS` (CC 11 = 120, CC 40 = 127, CC 94 = 60 shimmer, etc.). Engagement: Logos UI button "Mode D" → recalls `hapax-mode-d` preset → emits CC burst.

**Signal quality:** Evil Pet granular + reverb tail at full wet mix (CC 40 = 127) risks spectral flattening. Ring 2 WARD classifier validates that livestream-tap output (pre-encode) still carries scene legibility (OQ-02 anti-opacity bound). If opacity detected, operator reduces reverb tail (CC 93) or mix (CC 40) manually.

**Failure mode:** Mode D engaged but Evil Pet granular engine not responding (MIDI down) → turntable feeds Evil Pet at bypass, no granular coloration → Content-ID still matches source → operator must retry MIDI or cancel Mode D.

### S5b: Duet Mode (Rode + TTS Parallel)

**Use case:** Operator's live voice (Rode wireless on L6 CH1) and Kokoro TTS (on Evil Pet via R1) both contribute to the broadcast simultaneously, creating a conversational duet between human and synthetic voice.

**Routing:**
- CH1 Rode → multitrack capture (AUX0) → filter-chain `gain_rode` → livestream-tap (unprocessed)
- Kokoro TTS → Evil Pet (via R1) → L6 CH3 → livestream-tap (processed)
- Both converge in the livestream-tap stereo mix

**Control surface:** 
- `gain_rode` (CH1): operator tunes in filter-chain config (default 2.0, 6 dB boost for operator voice intelligibility vs background)
- `gain_evilpet` (CH3): operator tunes separately (default 2.0)
- Operator monitoring: L6 CH1 fader + L6 CH3 fader (both active for duet mode)

**Failure mode:** Rode wireless loses signal → CH1 audio drops, TTS continues via Evil Pet → one-sided conversation, not a duet.

### S5c: Emergency Clean Fallback

**Use case:** If Evil Pet offline, operator can route TTS clean (no Evil Pet) to Ryzen → L6 CH5 → livestream-tap.

**Routing:** Kokoro TTS → `hapax-livestream` sink (direct loopback to Ryzen) → L6 CH5 → multitrack capture (AUX6/AUX7) → filter-chain `gain_pc_l` / `gain_pc_r` → livestream-tap.

**Trigger:** Operator sees Evil Pet offline warning (dmesg error, MIDI port closed, etc.) and manually switches TTS sink from `hapax-voice-fx-capture` (Evil Pet path) to `hapax-livestream` (direct path) via Logos UI.

**Signal quality:** TTS at full bandwidth, no Evil Pet coloration; identifiable as synthetic voice, not the Hapax character. Acceptable for emergency/recovery narration only.

### S5d: Research Capture (Dry + Wet Simultaneous)

**Use case:** Audio research: simultaneously record TTS → Evil Pet (wet) and TTS clean (dry) to a dual-track file for offline analysis.

**Routing:** Kokoro TTS splits to two simultaneous sinks: (1) `hapax-voice-fx-capture` → Evil Pet (wet), (2) `hapax-research-capture` (new sink, direct loopback to Ryzen, dry). Multitrack USB captures AUX2 (Evil Pet) + a separate research channel simultaneously.

**Implementation note:** Requires PipeWire loopback sink extension in `~/.config/pipewire/pipewire.conf.d/hapax-research.conf` (Phase P §11 task). Not active by default; operator enables via Logos affordance recruitment when needed.

---

## §6 — Control Surface Mapping

This section enumerates every control surface per routing, establishing clear ownership: which actor (hardware knob, software UI, MIDI CC) owns each parameter.

### R1: Always-on Hapax Voice Character

| Parameter | Control | Owner | Touch Frequency | Scope |
|-----------|---------|-------|-----------------|-------|
| TTS source activation | Logos affordance pipeline | narrative director (LLM) | per-utterance (automatic) | enable/disable entire R1 routing |
| Voice tier selection (T0–T6) | Tier resolver in narrative director | director agent (impingement-driven + role default + stance delta) | per-utterance or per-tick (automatic) | selects which tier-specific CC overrides apply |
| Evil Pet preset recall | `shared/evil_pet_presets.recall_preset()` → Erica Dispatch MIDI | vocal_chain agent (on tier change) | automatic, tied to tier transition | emits 16–20 CC values synchronously |
| Evil Pet Master Volume (CC 7) | BASE_SCENE[7] = 127 | voice_tier.TIER_CATALOG (static) | never touched after base-scene | voice output never silent |
| Evil Pet Grains Volume (CC 11) | TIER_CATALOG[tier].cc_overrides | voice_tier agent (tier-aware) | automatic on tier change | T0–T4: grains off (0); T5: 90; T6: 120 |
| Evil Pet Mix/Wet (CC 40) | TIER_CATALOG[tier].cc_overrides | voice_tier agent | automatic on tier change | T0–T4: 95 (75% wet); T5/T6: 110–127 (max defeat-range) |
| Evil Pet Filter Type (CC 80) | BASE_SCENE[80] = 64 (bandpass) | voice_tier.TIER_CATALOG (static) | never touched | preserve consonant articulation |
| Evil Pet Reverb Amount (CC 91) | TIER_CATALOG[tier].cc_overrides | voice_tier agent | automatic on tier change | T0–T4: 38 (~30%); T5/T6: extends to 100 |
| Evil Pet Reverb Tail (CC 93) | TIER_CATALOG[tier].cc_overrides (may be field-tuned post-ship) | voice_tier agent | automatic on tier change | T0–T4: 38 (~30%); T5/T6: 80–100 (extended decay) |
| Evil Pet Saturator Amount (CC 39) | TIER_CATALOG[tier].cc_overrides | voice_tier agent | automatic on tier change | T0–T4: 38; T5/T6: subject to signal dynamics |
| L6 CH3 fader (analog monitor level) | L6 hardware fader | operator (manual) | real-time, during TTS playback | controls monitor loudness only; does NOT affect broadcast capture (pre-fader) |
| `gain_evilpet` filter-chain (broadcast level) | PipeWire filter-chain gain control | operator (via Logos overlay or config file) | session-setup or post-mortem tuning | default +6 dB; tunes broadcast-capture level independent of monitor mix |
| `hapax-voice-fx-capture` sink | PipeWire sink selection in audio app | TTS system (Kokoro → daimonion) | one-time per session | routes all TTS output to Evil Pet path |

### R2: Sampler Wet/Dry Parallel

| Parameter | Control | Owner | Touch Frequency | Scope |
|-----------|---------|-------|-----------------|-------|
| Sampler chain output → L6 CH6 | External mixer or sampler output setting | operator (manual hardware setup) | session setup | delivers stereo-to-mono sampler audio into L6 |
| L6 CH6 AUX SEND 1 knob (wet-path split) | L6 hardware knob | operator (manual) | once per session (set and forget) | gates how much sampler signal feeds Evil Pet |
| Evil Pet preset (sampler-optimized) | Logos affordance or direct UI button | operator (manual or automated for T5/T6 sampler characters) | per-session or per-edit | proposed "hapax-sampler-wet" preset engages granular at T5 |
| Evil Pet Grains Volume (CC 11) for sampler | Evil Pet preset (sampler-wet or manual tune) | operator (manual MIDI CC or preset) | rare; operator may increase for extra granular color | range 0–120 depending on sampler densit |
| L6 CH6 fader (dry-path monitor level) | L6 hardware fader | operator (manual) | real-time during sampler playback | monitor only; pre-fader capture level independent |
| L6 CH3 fader (wet-path monitor level) | L6 hardware fader | operator (manual) | real-time during sampler playback | monitor only; pre-fader capture level independent |
| `gain_samp` filter-chain (dry-path broadcast level) | PipeWire filter-chain gain control | operator (config tuning) | session setup | default +6 dB; tunes dry capture level vs Evil Pet signal dynamics |
| `gain_evilpet` filter-chain (wet-path broadcast level) | PipeWire filter-chain gain control | operator (config tuning) | session setup | default +6 dB; tunes wet capture level (matched to dry for coherence) |

### R3: S-4 as USB-Direct Content Source

| Parameter | Control | Owner | Touch Frequency | Scope |
|-----------|---------|-------|-----------------|-------|
| S-4 USB input routing (sink selection) | PipeWire `hapax-s4-content` sink or explicit routing | audio app (music player, PipeWire module) | app startup or Logos sink selector | directs app output to S-4 USB input |
| S-4 hardware input selector (Track 1 source) | S-4 physical buttons (Source/Routing encoder) | operator (manual) | once per session | selects USB, Line In 1, Line In 2, or Stereo |
| S-4 Material slot | S-4 physical buttons | operator (manual) | once per session | set to Bypass (for audio-effect mode) |
| S-4 Granular slot | S-4 physical buttons | operator (manual) | once per session | set to Bypass or None (for audio-effect mode) |
| S-4 Filter device (Filter slot) | S-4 physical buttons (Select encoder) | operator (manual) | per-session, per-material | choose Ring / Peak / Slope (recommend Ring) |
| S-4 Filter parameters (Frequency, Resonance) | S-4 physical knobs OR MIDI CC from Erica Dispatch | operator (manual hardware) or Erica Dispatch (if S-4 MIDI routed) | real-time | sculpt tonal character |
| S-4 Color device (Color slot) | S-4 physical buttons | operator (manual) | per-session | choose Deform (compression + bit-crush) or Mute |
| S-4 Color parameters (Deform amount, bit-crush) | S-4 physical knobs OR MIDI CC | operator (manual) or Erica Dispatch | real-time | harmonic coloration depth |
| S-4 Space device (Space slot) | S-4 physical buttons | operator (manual) | per-session | Vast (delay + reverb) or None (bypass) |
| S-4 Space parameters (Feedback, Spread) | S-4 physical knobs OR MIDI CC | operator (manual) or Erica Dispatch | real-time | spatial diffusion |
| S-4 USB output → PipeWire routing | PipeWire module mapping | system configuration (Phase P §11) | one-time system setup | routes S-4 USB output stereo pair to livestream-tap or dedicated sink |
| S-4 MIDI 1 input (sequencer / clock) | S-4 physical MIDI jack → Erica Dispatch | external MIDI device (S-4 companion sequencer, OXI One, etc.) or Evil Pet feedback loop | per-session | optional: S-4 can emit MIDI to control Evil Pet via Erica routing |

### Erica MIDI Dispatch (Master Control Hub)

The Erica Synths MIDI Dispatch module (hardware unit, 6-in/6-out MIDI, at `/dev/midi*` and ALSA client) is the central MIDI router. All per-routing CC emissions flow through Dispatch.

| Route | Source | Destination | CC Set | Owner |
|-------|--------|-------------|--------|-------|
| Voice tier → Evil Pet | vocal_chain agent (hapax_daimonion) | Evil Pet MIDI ch 1 | BASE_SCENE + TIER_CATALOG[tier].cc_overrides | narrative director (automatic) |
| S-4 sequencer → Evil Pet | S-4 MIDI 1 output jack (optional; S-4 sequencer or external) | Erica Dispatch IN → Evil Pet MIDI ch 1 | S-4 sequencer program (operator-set per material) | S-4 operator (manual tuning) |
| Manual preset recall | Logos UI "Recall Preset" button | Erica Dispatch IN → Evil Pet MIDI ch 1 | preset name → `shared/evil_pet_presets.recall_preset()` | operator (manual, rare) |

---

## §7 — Preset Pack Extension

The existing `shared/evil_pet_presets.py` defines 9 presets: one per VoiceTier (T0–T6) + Mode D + bypass. This spec proposes 3–5 new routing-aware presets that extend the pack without breaking existing code.

### Proposed New Presets

**Name:** `hapax-sampler-wet` | **Mapping:** R2 (wet/dry parallel)
```python
EvilPetPreset(
    name="hapax-sampler-wet",
    description="Sampler-optimized granular wash — higher grain density + sustained reverb tail for polyrhythmic textures.",
    ccs={
        **BASE_SCENE,
        11: 100,    # Grains volume → 78% (granular engaged, denser than voice T5)
        40: 120,    # Mix → 94% wet (defeat dry sampler bleed)
        91: 60,     # Reverb amount → 47% (longer tail for sampler sustain)
        93: 70,     # Reverb tail → extended (2.5–3.0 s; won't smear drums)
        39: 50,     # Saturator → 40% (adds harmonic complexity to granular)
        94: 40,     # Shimmer → 31% (iridescent cloud, optional; tune per taste)
    }
)
```

**Name:** `hapax-bed-music` | **Mapping:** Secondary (SoundCloud bed music or music underscore)
```python
EvilPetPreset(
    name="hapax-bed-music",
    description="Low-impact music processing — subtle texture without vocals. Minimal granular, emphasizes filter + reverb.",
    ccs={
        **BASE_SCENE,
        11: 30,     # Grains volume → 23% (light granular color, not primary)
        40: 85,     # Mix → 67% wet (balanced dry/wet for musical legibility)
        91: 45,     # Reverb amount → 35% (ambient wash, not obstructive)
        93: 50,     # Reverb tail → 50% (~1.5 s, non-intrusive)
        39: 25,     # Saturator → 20% (preserve dynamic range of music)
        70: 80,     # Filter freq → slightly bright (emphasize high-frequency details)
    }
)
```

**Name:** `hapax-drone-loop` | **Mapping:** Experimental (sustained ambient texture for interludes)
```python
EvilPetPreset(
    name="hapax-drone-loop",
    description="Sustained granular drone — full wet, long reverb tail, minimal saturation. Use for ambient interludes.",
    ccs={
        **BASE_SCENE,
        11: 110,    # Grains volume → 86% (granular primary)
        40: 127,    # Mix → 100% wet (pure texture)
        91: 80,     # Reverb amount → 63% (long ambience)
        93: 90,     # Reverb tail → 70% (~3.5 s, intentional sustain)
        39: 15,     # Saturator → 12% (clean granular texture)
        94: 50,     # Shimmer → 39% (iridescent atmosphere)
        70: 70,     # Filter freq → mild darkening (reduce ear fatigue)
    }
)
```

**Name:** `hapax-s4-companion` | **Mapping:** R3 (S-4 as parallel Evil Pet modulator)
```python
EvilPetPreset(
    name="hapax-s4-companion",
    description="S-4-companion preset — light Evil Pet coloration for content when S-4 Mosaic granular is primary. Permits dual-granular textures (Evil Pet + S-4) without harshness.",
    ccs={
        **BASE_SCENE,
        11: 70,     # Grains volume → 55% (secondary granular, not primary)
        40: 100,    # Mix → 78% wet (texture present but subordinate)
        91: 40,     # Reverb amount → 31% (S-4 Space handles primary diffusion)
        93: 40,     # Reverb tail → 40% (~1.5 s, short)
        39: 20,     # Saturator → 16% (S-4 Color provides primary harmonic work)
    }
)
```

**Integration in `shared/evil_pet_presets.py`:**

```python
PRESETS: Final[dict[str, EvilPetPreset]] = {
    preset.name: preset
    for preset in (
        *(_tier_preset(t) for t in VoiceTier),
        EvilPetPreset(...  # hapax-mode-d)
        EvilPetPreset(...  # hapax-bypass)
        # New routing-aware presets:
        EvilPetPreset(...  # hapax-sampler-wet)
        EvilPetPreset(...  # hapax-bed-music)
        EvilPetPreset(...  # hapax-drone-loop)
        EvilPetPreset(...  # hapax-s4-companion)
    )
}
```

Each preset is now queryable via `shared/evil_pet_presets.get_preset(name)` and callable via `recall_preset(name, midi_output)`.

---

## §8 — S-4 Integration Model

The Torso S-4 operates as a USB-direct, independent audio processor. MIDI coupling is optional and per-use-case; audio paths are separate from Evil Pet unless explicitly configured.

### USB Audio Architecture

**Hardware:** S-4 USB-C class-compliant, 10-in/10-out stereo pairs.

**Kernel driver:** `snd-usb-audio` (no proprietary modules).

**PipeWire discovery:**
```
Device: alsa_output.usb-Torso_Electronics_S-4_fedcba9876543220-03.pro-output-0
  Type: sink
  Channels: stereo (pairs 1–5 available per manual)
  
Device: alsa_input.usb-Torso_Electronics_S-4_fedcba9876543220-03.pro-input-0
  Type: source
  Channels: stereo (pairs 1–5 available)
```

**PipeWire routing for R3:**

Create a loopback sink in `~/.config/pipewire/pipewire.conf.d/hapax-s4-content.conf`:
```
# Loopback sink for application audio → S-4 USB input
{   name = libpipewire-module-loopback
    args = {
        node.description = "Hapax S-4 Content (→ S-4 USB)"
        capture.props = {
            node.name      = "hapax-s4-content"
            node.description = "Hapax S-4 Content"
            media.class    = "Audio/Sink"
            audio.position = [ FL FR ]
        }
        playback.props = {
            node.name      = "hapax-s4-content-playback"
            target.object  = "alsa_input.usb-Torso_Electronics_S-4_...pro-input-0"
            audio.position = [ FL FR ]
        }
    }
}

# S-4 USB output → livestream-tap (or dedicated monitor sink)
{   name = libpipewire-module-loopback
    args = {
        node.description = "Hapax S-4 Broadcast (S-4 USB → livestream-tap)"
        capture.props = {
            node.name      = "hapax-s4-output"
            node.description = "Hapax S-4 Broadcast"
            media.class    = "Audio/Source"
            audio.position = [ FL FR ]
        }
        playback.props = {
            node.name      = "hapax-s4-broadcast-playback"
            target.object  = "hapax-livestream-tap"
            audio.position = [ FL FR ]
        }
    }
}
```

**Quantum / latency settings:** S-4 USB latency at default PipeWire quantum (512 samples) ≈ 5–12 ms roundtrip (verified during Phase T proof-of-concept).

### MIDI Integration

**Hardware MIDI:** S-4 ships with 3.5mm TRS DIN adapter. Physical S-4 MIDI 1 jack connects to Erica Dispatch IN jack.

**Software MIDI discovery:**
```bash
$ aconnect -i
client 40: 'S-4' [type=kernel,card=6]
  0 'S-4 MIDI 1'
```

**Routing: S-4 MIDI 1 → Erica Dispatch → Evil Pet**

When S-4 is operating (e.g., with an onboard sequencer or external MIDI controller feeding S-4 MIDI 1), S-4 can emit MIDI CC or note data that the Erica Dispatch routes to Evil Pet MIDI channel 1. This permits S-4 sequencer-driven Evil Pet modulation (e.g., S-4 Mosaic granular position can indirectly drive Evil Pet filter sweep via CC).

**Dispatch routing configuration (example):**
```
Erica Dispatch IN port 1 (from S-4 MIDI 1) → OUT port 1 (to Evil Pet MIDI ch 1)
```

**Operator control:** S-4 sequencer CC map → Erica Dispatch routing → Evil Pet CC interpretation. Per-preset tie-in possible (e.g., "hapax-s4-companion" preset + S-4 sequencer program synchronized).

### MIDI CC Sync (Optional Cross-Modulation)

**Use case:** S-4 Mosaic granular position is sequenced (CC 48–51 range) to create evolving texture; simultaneously Evil Pet filter frequency (CC 70) is sequenced to track S-4. Both processors modulate in lockstep.

**Implementation:** 
1. S-4 sequencer emits CC 48 (position) at tempo-locked intervals
2. Erica Dispatch has a custom map: CC 48 from S-4 → CC 70 on Evil Pet (or direct pass-through if Evil Pet also reads CC 48 on a different parameter)
3. Both granular engines step together; live performance has rhythmic coherence

**Governance:** CVS #8 (non-manipulation axiom): S-4 sequencer-driven Evil Pet CC modulation must NOT be configured to exploit listener dopamine loops (e.g., avoid steady crescendo in intensity/tension over minutes without break). Operator responsible for sequencer program safety.

---

## §9 — Signal Quality Invariants

All routings (R1–R3 core + S5a–S5d secondary) must satisfy these non-negotiable audio quality bounds.

### Unity Gain Default

Every software gain stage defaults to unity (linear gain = 1.0, 0 dB) unless the downstream target is explicitly known to be below -18 dBFS.

**Justification:** Prevents silent-signal loss via cascading unity-gain stages that don't add up to the -18 dBFS broadcast target.

**Application:**
- `hapax-private` loopback → Ryzen analog: unity gain (no attenuation before physical cable)
- `hapax-livestream` loopback → Ryzen analog: unity gain
- L6 multitrack AUX2 → filter-chain `gain_evilpet`: default +6 dB (2.0 linear) — justified because L6 CH3 input (Evil Pet output at ~2 Vrms line level) requires gentle boost to reach -18 dBFS nominal in a stereo mix with other sources

### Gain Ceiling

No single stage boosts >+6 dB unless the downstream target is explicitly below -18 dBFS and the downstream stage has compensatory attenuation to prevent clipping.

**Examples of permitted >+6 dB boosts:**
- L6 CH4 (Handytraxx vinyl, often low-level): `gain_handy_l` = 4.0 (+12 dB) is permitted IF the vinyl material is known to peak at -24 dBFS and the downstream summing stage has headroom or soft compression.
- L6 CH1 (Rode WP, operator voice, variable loudness): `gain_rode` = 2.0 (+6 dB) is baseline; operator can tune up to 4.0 (+12 dB) for quiet speaking if summing doesn't clip.

**Downstream headroom:** The `sum_l` / `sum_r` mixers in the filter-chain accept 6 inputs each at unity gain. If all six contribute at +6 dB each, the sum = +6 dB (linear 2.0 × 6 = 12x upstream energy), requiring downstream soft-clip or output attenuation.

**Mitigation:** Operator's responsibility to not hotmax all channels simultaneously. Broadcast target is -18 dBFS RMS (peaks < -6 dBFS for safety headroom).

### OQ-02 Anti-Opacity Bound

Evil Pet granular processing at T5/T6 + heavy reverb risks spectral flattening (scene-legibility collapse to single-hue abstraction). The livestream-tap output must pass the Ring 2 WARD classifier post-render.

**Measurement:** After rendering and before RTMP/HLS encode, run:
```python
# Pseudocode; actual implementation in agents/ring_2_classifier/
ward_score = WARD.classify(livestream_tap_output)  # Returns "low", "medium", "high" legibility
if ward_score == "high":
    # Scene collapsed to abstraction; OQ-02 breach
    log.warning("Legibility below threshold; reverb tail or granular density too high")
```

**Operator action:** If WARD reports legibility below threshold:
1. Reduce Evil Pet Reverb Tail (CC 93) by 20–30 points
2. Reduce Shimmer (CC 94) slightly to reduce iridescence
3. OR: Increase Filter Resonance (CC 71) to re-sharpen transients
4. Re-render and re-check

**Shipping policy:** Tier T5 (GRANULAR-WASH, floor 0.15 intelligibility) is permitted if WARD passes. Tier T6 (OBLITERATED, floor 0.0) MUST pass WARD before egress; if WARD fails, T6 is held in standby and narrative director drops to T5 or below until WARD recovers.

### No Feedback Loops

Evil Pet output → L6 CH3 IN does NOT feed back to Evil Pet input via any path (L6 AUX SEND 1, monitored loops, virtual cables, etc.). Operator enforces this by leaving L6 CH3 AUX SEND 1 knob at 0 (operator protocol).

**Verification:** During Phase T initial setup:
```bash
# Eject a test tone into Evil Pet IN; measure L6 CH3 output.
# Then check L6 CH3 level with its AUX SEND 1 knob at various settings.
# If CH3 SEND 1 is raised and test tone grows, feedback loop is present → FIX.
```

---

## §10 — Test Plan

Organized in layers: unit → integration → regression → governance → observability.

### Unit Tests

**Test:** `test_evil_pet_preset_recall()`
- Load `hapax-tier-2` preset from `shared/evil_pet_presets.PRESETS`
- Verify CC count = 16 (BASE_SCENE + tier overrides)
- Verify CC 11 (grains) = 0, CC 40 (mix) = 95
- Emit CC burst via mock MIDI output
- Assert all CCs transmitted without exception

**Test:** `test_sampler_wet_preset()`
- Load `hapax-sampler-wet` preset
- Verify CC 11 = 100, CC 40 = 120, CC 91 = 60
- Check no conflicts with voice-tier CCs
- Recall and verify MIDI emit

**Test:** `test_voice_tier_mutex_evil_pet_granular()`
- Apply tier T5 (GRANULAR-WASH) with vinyl Mode D active
- Verify that tier.mutex_groups includes "evil_pet_granular_engine"
- Assert that vocal_chain.apply_tier() gracefully downgrades to S-4 Mosaic granular instead of Evil Pet
- Verify no double-claim on Evil Pet granular engine

### Integration Tests

**Test:** `test_r1_tts_to_evil_pet_to_livestream()`
- Trigger Kokoro TTS utterance at tier T2 (BROADCAST-GHOST)
- Measure AUX2 (L6 CH3 pre-fader) signal level in livestream-tap
- Expected range: -24 to -6 dBFS (nominal -18 dBFS center)
- Assert no clipping, no silence
- Verify Evil Pet response latency <10 ms from MIDI emit to audio change

**Test:** `test_r2_sampler_wet_dry_levels()`
- Feed test signal (1 kHz -18 dBFS) into L6 CH6
- Set CH6 AUX SEND 1 to 75%
- Measure CH6 dry path (AUX8 → gain_samp) level in livestream-tap
- Measure CH6 wet path (via Evil Pet → CH3 → AUX2) level in livestream-tap
- Expected: both paths audible, wet slightly softer (Evil Pet reverb tail decay)
- Verify dry/wet skew <15 ms

**Test:** `test_r3_s4_usb_latency()`
- Route known signal (1 kHz sine, -12 dBFS) to `hapax-s4-content` sink
- Process through S-4 Filter slot at known resonance
- Measure S-4 USB output → livestream-tap latency
- Expected: 12–20 ms round-trip (USB + DSP)
- Verify no USB dropouts during 5-minute burn-in

**Test:** `test_pipewire_multitrack_capture_alignment()`
- Send click track to L6 CH1
- Send complementary click offset to L6 CH5
- Verify AUX0 (CH1 dry) and AUX6 (CH5 dry) arrive in multitrack with expected sample-level alignment
- Assert no ch slip / off-by-one channel mapping

### Regression Tests

**Test:** `test_vinyl_mode_d_frequency_response()`
- Feed pink noise into Evil Pet via AUX SEND 1 (vinyl mode)
- Engage Mode D preset (granular @ CC 11 = 120, reverb @ CC 91 = 70)
- Measure livestream-tap spectrum: expect spectral flattening (low-frequency emphasis, reduced high-frequency articulation)
- Ring 2 WARD classifier: verify legibility ≥ "medium" threshold
- Assert no aliasing or ultrasonic ringing

**Test:** `test_voice_tier_intelligibility_floor_t6()`
- TTS utterance "hello world" at tier T6 (OBLITERATED)
- Route through Evil Pet at full granular engagement
- Render livestream-tap output
- Manual listen: intelligibility floor must be 0.0 (indistinguishable from abstract sound)
- Ring 2 WARD classifier: legibility must be "low" (expected)
- Duration cap: confirm T6 limited to 15s max (enforced by director agent)

**Test:** `test_emergency_fallback_clean_path()`
- Evil Pet offline (MIDI port closed)
- TTS routes to `hapax-livestream` sink (bypass)
- Measure L6 CH5 output in livestream-tap
- Assert intelligibility floor = 1.0 (unprocessed Kokoro)
- Verify no Evil Pet coloration / audio character change

### Governance Tests

**Test:** `test_hardm_non_operator_voice_consent()`
- Contact mic input (CH2) is non-operator potential source
- Route CH2 through Evil Pet (AUX SEND 1)
- Evil Pet return lands in livestream-tap
- Check consent contract for "contact_mic_to_evilpet_broadcast"
- Assert: routing blocked unless contract active
- Log consent check for audit trail

**Test:** `test_cvs_8_s4_sequencer_dopamine()`
- S-4 sequencer configured: steady crescendo in Filter resonance over 5 minutes
- Verify Erica Dispatch routing does NOT map S-4 CC 88 (resonance) to Evil Pet in a way that creates sustained tension escalation
- Manual review: confirm no feedback-loop-like CC cascade
- Mark test as PASS if operator review + approval documented

**Test:** `test_ring_2_ward_livestream_legibility()`
- Render 60 seconds of mixed broadcast: TTS T2 + sampler dry + vinyl Mode D
- Pass livestream-tap output to Ring 2 WARD classifier
- Expected result: legibility ≥ "medium" (scene not collapsed to single hue)
- If legibility = "low": log warning + trigger operator review

**Test:** `test_oq02_anti_recognition_evil_pet_output()`
- Evil Pet output on L6 CH3 → livestream-tap
- No voice identity preserved in granular wash (T5/T6)
- Face/person data: none (audio-only path)
- Pass/fail: anti-recognition axiom satisfied ✓

### Observability Tests

**Test:** `test_prometheus_evil_pet_preset_recall_counter()`
- Recall "hapax-tier-2" preset 10 times
- Query Prometheus at `127.0.0.1:9090/metrics`
- Verify counter `evil_pet_preset_recalls_total{preset="hapax-tier-2"}` = 10
- Check `evil_pet_preset_recall_duration_seconds` histogram (expect <100 ms)

**Test:** `test_prometheus_s4_usb_dropout_detection()`
- Simulate S-4 USB disconnect (unplug device)
- Query gauge `s4_usb_dropout_detected`
- Verify gauge = 1 (dropout detected)
- Re-plug S-4
- Verify gauge = 0 (recovery)
- Check `s4_usb_recovery_attempts_total` counter

**Test:** `test_prometheus_aux2_signal_presence_gauge()`
- TTS active, Evil Pet return on L6 CH3 / AUX2
- Query gauge `l6_aux2_signal_present_db` (RMS dB)
- Expected: -24 to -6 dBFS during TTS
- Query updated every 100 ms
- Assert no NaN or stale values

---

## §11 — Rollout Phases (Feeds Phase P Plan)

Implementation is serialized across 6 phases, each corresponding to one PR and one merge to main. Dependencies and parallelism noted.

### Phase 1: PipeWire Configuration (Loopback Sinks)

**PR scope:** 
- Create `~/.config/pipewire/pipewire.conf.d/hapax-s4-content.conf` (S-4 USB loopback)
- Create `~/.config/pipewire/pipewire.conf.d/hapax-s4-broadcast.conf` (S-4 output → livestream-tap)
- Unit tests: `test_pipewire_s4_sink_enumeration()`, `test_pipewire_s4_source_discovery()`
- Observability: add Prometheus gauges for S-4 USB sink/source presence
- **Dependency:** none (zero runtime code changes)
- **Timeline:** 2–3 days (config authoring + testing)

### Phase 2: Evil Pet Preset Pack Extension

**PR scope:**
- Extend `shared/evil_pet_presets.py` with 4 new presets (sampler-wet, bed-music, drone-loop, s4-companion)
- Add `get_preset(name)` lookup for new presets
- Unit tests: `test_sampler_wet_preset()`, `test_bed_music_preset_load()`, etc.
- **Dependency:** Phase 1 (loopback config)
- **Parallelizable:** Independent of vocal_chain changes; can develop in separate branch
- **Timeline:** 2–3 days

### Phase 3: R1 Core Routing (TTS → Evil Pet Integration)

**PR scope:**
- Integrate `recall_preset()` into `agents/hapax_daimonion/vocal_chain.py` on tier transition
- Tie voice tier resolution (docs/superpowers/specs/2026-04-20-voice-tier-director-integration.md) to Evil Pet preset recall
- Implement MIDI port ping + verify flow (evil_pet_presets.recall_preset(verify_port=True))
- Integration tests: `test_r1_tts_to_evil_pet_to_livestream()`
- Observability: Prometheus counter for preset recalls + duration histogram
- **Dependency:** Phase 2 (presets available)
- **Timeline:** 4–5 days (MIDI integration + debugging)

### Phase 4: Signal Quality Validation

**PR scope:**
- Verify L6 multitrack AUX2 capture levels (gain_evilpet = 2.0 default is correct for -18 dBFS target)
- Add filter-chain gain tuning workflow (operator config file + optional Logos overlay binding)
- Ring 2 WARD classifier integration (post-livestream-tap measurement)
- Integration tests: `test_r1_livestream_output_levels()`, `test_signal_quality_invariants()`
- **Dependency:** Phase 3 (R1 routing live; audio flowing)
- **Timeline:** 3–4 days

### Phase 5: R2 + R3 Routing (Sampler + S-4)

**PR scope:**
- Document L6 CH6 AUX SEND 1 knob protocol (operator config file, training doc)
- S-4 USB routing via loopback sinks (Phase 1) now validated end-to-end
- Integration tests: `test_r2_sampler_wet_dry_levels()`, `test_r3_s4_usb_latency()`
- Governance tests: `test_hardm_non_operator_voice_consent()` for CH2 contact mic + Evil Pet
- **Dependency:** Phase 4 (signal quality validated for core path); Phase 1 (S-4 loopback available)
- **Timeline:** 4–5 days

### Phase 6: Governance + Observability

**PR scope:**
- Implement HARDM consent gate for non-operator voice + Evil Pet (contact mic routing)
- CVS #8 compliance: document S-4 sequencer safeguards (no dopamine-loop CCs auto-routed to Evil Pet)
- Ring 2 WARD classifier integration tests + operator review workflow (failsafe: if legibility drop detected, log warning + pause T6 tier)
- Prometheus metrics finalization: evil_pet_preset_recalls, s4_usb_dropout, l6_aux2_signal_level gauges
- **Dependency:** Phase 5 (all routings live); Phase 3 (vocal_chain tier system live)
- **Timeline:** 5–6 days (complex logic + testing)

### Parallelization Opportunities

- **Phase 2 + Phase 3:** Preset pack and vocal_chain integration can be developed in parallel once Phase 1 (PipeWire config) is complete. Merge Phase 2 first; Phase 3 then depends on Phase 2.
- **Phase 1 + Phase 4:** PipeWire config can be validated independently of signal-quality measurements; Phase 4 begins once Phase 3 audio is flowing.
- **Phase 5 (R2 + R3):** Both are independent of each other (R2 uses L6 AUX SEND, R3 uses USB); can be developed in parallel if Phase 4 is complete.

### Total Critical Path: ~18–20 days (6 phases × 3 days minimum, with some parallelization overlap)

---

## §12 — Governance Cross-Check

Three governance frameworks apply to the Evil Pet + S-4 routing architecture:

### HARDM (Anti-Anthropomorphization)

**Applies to:** Evil Pet granular engine engaged (T5/T6) processing any voice.

**Rule:** When Evil Pet granular processes voice at T5 (GRANULAR-WASH, intelligibility floor 0.15) or T6 (OBLITERATED, floor 0.0), the output approaches voice-destruction (word recognition impossible, voice becomes abstract sound). If the source is non-operator (contact mic, radio, streamed guest voice), a consent contract must be active before T5/T6 rendering.

**Shipped implementation:**
- Operator's voice (Rode wireless): no consent gate (operator owns their own output)
- Kokoro TTS: no consent gate (synthetic, not anthropomorphic)
- Contact mic (CH2): consent gate required if T5/T6 routed through Evil Pet (potential to capture non-operator sound)
- External streams: if guest voice routed to Evil Pet T5/T6, explicit consent contract mandatory

**Configuration:** `axioms/contracts/evilpet_voice_consent_matrix.yaml` (to be authored in Phase 6) maps (source, tier) → required contract. Failure to obtain contract → tier clamped to T4 maximum.

### CVS #8 (Non-Manipulation, Dopamine-Loop Prevention)

**Applies to:** S-4 sequencer-driven Evil Pet CC modulation.

**Rule:** S-4 sequencer CCs routed to Evil Pet via Erica Dispatch must NOT be configured to exploit listener dopamine loops (e.g., steady crescendo of tension/coherence over minutes without break, or periodic reinforcement of reward peaks).

**Shipped implementation:**
- S-4 → Erica Dispatch → Evil Pet routing is explicitly enabled (not auto-connected)
- Operator is responsible for sequencer program safety
- Phase 6 includes manual audit: operator reviews S-4 sequencer program and certifies no dopamine-loop CCs
- Prometheus metric: `s4_evil_pet_cc_routing_enabled` boolean flag + audit timestamp

**No automatic prevention:** CVS #8 is a transparency requirement, not a hard gate. Operator awareness + consent documented in session log.

### Ring 2 WARD Classifier (Visual Legibility of Broadcast)

**Applies to:** All livestream-tap outputs (post-filter-chain mixing).

**Rule:** Livestream-tap audio (after Evil Pet processing + reverb + all sources mixed) must maintain minimum scene legibility (WARD classifier ≥ "medium" threshold). Evil Pet granular at max opacity risks spectral flattening; T5/T6 tiers must pass WARD validation before egress to RTMP/HLS.

**Shipped implementation:**
- Post-render measurement: livestream-tap final stereo mix → WARD classifier
- Prometheus gauge: `livestream_tap_legibility_score` ("low"=0, "medium"=1, "high"=2)
- Operator alert: if legibility drops to "low" during T5/T6 engagement, log warning + narrative director drops tier to T4 or below
- No auto-correction: operator manually tunes Evil Pet reverb tail / shimmer / filter if legibility degrades

---

## §13 — Open Questions and Delta-Proposed Defaults

Operator has not overridden these; spec proposes defaults for Phase P implementation.

### Q1: Should SoundCloud bed-music also pass through Evil Pet, or bypass?

**Operator note:** "music_bed_routing" project mentions bed-music as broadcast underscore (low-priority background).

**Delta proposal:** By default, bed-music routes to `hapax-bed-music` preset (Evil Pet at light granular, CC 11 = 30, reverb tail short). Rationale: light texture adds studio character without audible processing. Operator can override by routing to direct `hapax-livestream` sink if bed-music source needs transparency.

**Shipping as:** Default routing via preset; operator can create alternate "bed-music-clean" routing if needed post-ship.

### Q2: Should L6 CH3 fader (monitor-only, analog) ever contribute to livestream-tap broadcast?

**Current design:** CH3 fader is monitor-only (does NOT affect USB pre-fader capture).

**Rationale:** Operator's monitor loudness is independent of broadcast capture level. L6 multitrack capture happens pre-fader (AUX2), so fader moves don't affect livestream.

**Delta proposal:** Keep current design (pre-fader capture). If operator wants to dynamically control Evil Pet return level for broadcast (not just monitor), use filter-chain `gain_evilpet` software control (tuned once per session in config, or exposed via Logos overlay in Phase P §8).

### Q3: Should S-4 MIDI clock be synchronized with Erica Dispatch (Evil Pet MIDI clock)?

**Use case:** S-4 sequencer running at 120 BPM; Evil Pet should receive sync clock so Evil Pet modulation is tempo-locked to S-4.

**Evil Pet capability check:** `shared/evil_pet_presets.py` does not mention MIDI clock support. Need to verify: does Evil Pet receive MIDI CC 248 (clock) and CC 250 (start)?

**Delta proposal:** Document Evil Pet MIDI clock support (if available) and propose optional Erica routing once verified. If Evil Pet lacks sync input, leave as non-critical enhancement (R3 audio works without sync).

### Q4: Contact mic + Evil Pet: what is the default consent contract assumption?

**Current:** CH2 (contact mic) requires consent before T5/T6 Evil Pet routing (HARDM axiom).

**Unknown:** What constitutes valid consent for "microphone may capture ambient non-operator sound"?

**Delta proposal:** Use the existing "audio_capture_non_operator" consent contract (generic, already defined in `axioms/contracts/`). Operators reading § §12 HARDM can point to that contract when routing contact mic through T5/T6. Phase 6 will hardcode the gate.

### Q5: Emergency clean fallback — should it be operator-manual or automatic on Evil Pet offline?

**Current design:** Operator manually switches TTS sink from `hapax-voice-fx-capture` (Evil Pet path) to `hapax-livestream` (bypass) if Evil Pet goes offline.

**Alternative:** Automatic fallback: on MIDI port close, vocal_chain agent auto-switches sink.

**Delta proposal:** Keep manual for now (Phase P shipping). Automatic fallback adds complexity (how long to wait before auto-fallback? what if Evil Pet reconnects?). Operator is trained to handle manual switch via Logos affordance (one-button "Emergency: bypass Evil Pet" command).

---

## §14 — Success Criteria

Concrete, measurable deliverables for Phase P implementation and operator acceptance.

### Functional Criteria

1. **R1 routing ships:** TTS → Evil Pet → L6 CH3 → livestream-tap. Operator can select voice tier T0–T6, preset recall emits CC burst, audio arrives in livestream-tap within 60 ms latency. ✓
2. **R2 routing ships:** Sampler CH6 dry + wet paths both captured in livestream-tap. L6 CH6 AUX SEND 1 knob controls wet-path level. Operator can tune `gain_samp` and `gain_evilpet` in filter-chain config. ✓
3. **R3 routing ships:** S-4 USB audio routed via PipeWire loopback to livestream-tap. S-4 USB latency measured <15 ms roundtrip. Optional: S-4 MIDI 1 → Erica Dispatch → Evil Pet routing functional. ✓

### Quality Criteria

4. **Signal quality:** All three routings hit -18 dBFS nominal RMS level in livestream-tap when sources are at line-level input (-12 dBFS). No clipping, no silence. ✓
5. **OQ-02 anti-opacity:** Ring 2 WARD classifier validates livestream-tap legibility ≥ "medium" when T5 Evil Pet granular active. ✓
6. **No feedback loops:** L6 CH3 output does NOT feed back to Evil Pet input. Verified via hardware trace (AUX SEND 1 knob left at 0). ✓

### Governance Criteria

7. **HARDM consent gate:** Non-operator voice + T5/T6 Evil Pet routed only with active consent contract. Operator accepts: "audio_capture_non_operator" contract applies to contact mic + Evil Pet. ✓
8. **CVS #8 transparency:** S-4 sequencer program reviewed by operator for dopamine-loop CCs. Audit timestamp logged in session. ✓
9. **Ring 2 legibility monitoring:** Prometheus gauge `livestream_tap_legibility_score` exported and visible in operator dashboard. Alerts on legibility drop enabled. ✓

### Observability Criteria

10. **Prometheus metrics live:** Counters for `evil_pet_preset_recalls_total`, `s4_usb_dropout_detected`, gauge for `l6_aux2_signal_present_db`. All exported at `127.0.0.1:9090/metrics`. ✓
11. **Logs documented:** Preset recall log message format: `"evil_pet recall {name}: {emitted}/{total} CCs emitted"`. Search logs for MIDI failures. ✓

### Operator Training

12. **Documentation complete:** Operator reads §1–§6 of this spec and can independently operate R1 + R2 routing. S-4 R3 (optional) documented with one-page quick-start. ✓
13. **Emergency procedures:** Operator knows to manually switch TTS sink if Evil Pet offline (fallback clean path). Documented in § §5c + training doc. ✓

---

## §15 — References

**Primary inputs (research + queue):**
- `docs/research/2026-04-20-evilpet-s4-routing-permutations-research.md` — 775-line exhaustive permutation space
- `~/.cache/hapax/relay/delta-queue-evilpet-s4-routing-research-20260420.md` — operator directive

**Configuration files (live, post-v5 filter-chain):**
- `~/.config/pipewire/pipewire.conf.d/hapax-l6-evilpet-capture.conf` — v5 filter-chain, per-channel gains
- `~/.config/pipewire/pipewire.conf.d/hapax-stream-split.conf` — PC audio loopback (hapax-livestream, hapax-private)
- `~/.config/pipewire/pipewire.conf.d/hapax-livestream-tap.conf` — livestream sink consolidation
- `~/.config/pipewire/pipewire.conf.d/hapax-voice-fx.conf` — voice FX chain (for reference)
- `~/.config/pipewire/pipewire.conf.d/hapax-vinyl-to-stream.conf` — vinyl broadcast routing (for reference)

**Code modules (shared):**
- `shared/evil_pet_presets.py` — 9 presets + recall_preset() helper
- `shared/voice_tier.py` — 7-tier TIER_CATALOG, tier_capability_record, role defaults, intelligibility budget
- `shared/project_hardm_anti_anthropomorphization.md` — HARDM governance rules
- `shared/project_soundcloud_bed_music_routing.md` — bed-music routing expectations

**Code modules (daimonion agents):**
- `agents/hapax_daimonion/vocal_chain.py` — 9-dimension voice FX vector, tier application
- `agents/hapax_daimonion/vinyl_chain.py` — Mode D turntable/granular mutex
- `agents/hapax_daimonion/director_loop.py` — narrative director (tier resolution per-tick)

**Related specs (same umbrella project):**
- `docs/superpowers/specs/2026-03-31-homage-umbrella-stream-architecture.md` — livestream envelope framing
- `docs/superpowers/specs/2026-03-31-vinyl-broadcast-signal-chain.md` — Mode D operator signal path
- `docs/superpowers/specs/2026-04-20-voice-tier-director-integration.md` — voice-tier routing decisions
- `docs/superpowers/specs/2026-03-26-logos-command-registry-design.md` — affordance pipeline (for Logos routing UI)

**Governance (axioms + contracts):**
- `axioms/registry.yaml` — definitions (single_user, executive_function, corporate_boundary, interpersonal_transparency, management_governance)
- `axioms/implications/hardm.md` — HARDM voice-destruction governance
- `axioms/implications/cvs_8.md` — CVS #8 non-manipulation dopamine-loop prevention
- `axioms/contracts/audio_capture_non_operator.yaml` — consent contract template

**Hardware references:**
- Evil Pet User Manual (Evil Pet MIDI chapter) — CC assignments
- Torso S-4 User Manual (USB audio + MIDI chapter) — device discovery, class-compliant spec
- Erica Synths MIDI Dispatch documentation — 6-in/6-out routing
- L6 (ZOOM) USB multitrack manual — altset 2, per-channel pre-fader capture

---

**Spec authored:** 2026-04-20 by delta  
**Status:** Phase S — decision-committed, locked for Phase P implementation  
**Next action:** Await Phase P plan-doc; assign Phase 1–6 PRs to implementation queue.
