---
date: 2026-04-21
author: delta
audience: operator + delta (execution) + alpha (control-law integration)
register: scientific, neutral
status: research — current-configuration routing with maximal + dynamic dual-processor use directive
supersedes_partial:
  - docs/research/2026-04-20-evilpet-s4-routing-permutations-research.md (static-topology prior; §§1-6 primitives preserved, §§7-12 augmented/replaced)
related:
  - docs/research/2026-04-20-evilpet-s4-routing-permutations-research.md (prior 776-line permutation survey)
  - docs/research/2026-04-19-evil-pet-s4-base-config.md (base signal levels, base presets)
  - docs/research/2026-04-20-dual-fx-routing-design.md (Option A rationale — S-4 USB direct)
  - docs/research/2026-04-20-unified-audio-architecture-design.md (topology abstraction)
  - docs/research/2026-04-20-audio-normalization-ducking-strategy.md (source inventory + ducking matrix)
  - docs/research/2026-04-20-voice-transformation-tier-spectrum.md (T0..T6 tier ladder)
  - docs/research/2026-04-20-mode-d-voice-tier-mutex.md (granular-engine mutex)
  - docs/research/2026-04-20-evil-pet-cc-exhaustive-map.md (39-CC footprint)
  - docs/research/2026-04-20-evil-pet-factory-presets-midi.md (factory preset vs CC-burst)
  - docs/superpowers/plans/2026-04-20-evilpet-s4-routing-plan.md (6-phase TDD plan)
  - docs/superpowers/specs/2026-04-20-evilpet-s4-routing-design.md (R1/R2/R3 routing design)
  - shared/evil_pet_presets.py (13 presets live: T0..T6 + mode-d + bypass + sampler-wet + bed-music + drone-loop + s4-companion)
  - agents/hapax_daimonion/vocal_chain.py (9-dim → CC emitter)
  - agents/hapax_daimonion/vinyl_chain.py (Mode D vinyl granular)
directive: maximal + dynamic use of both Evil Pet and Torso S-4
---

# Evil Pet + S-4 Dynamic Dual-Processor Routing — Current-Configuration Research

## §1. TL;DR

### Design directive (from operator, 2026-04-21)

> *"Re-run the entire research investigation, starting with what we have, but for the specific configuration we have at our fingertips right now. Make maximal and dynamic use of both S-4 and Evil Pet."*

Three explicit shifts from the 2026-04-20 research:

1. **Specific current hardware**, not aspirational. The L-6 → L-12 swap is complete; the `hapax-s4-content` PipeWire sink exists but the S-4 is not currently USB-enumerated (§2.2). All permutations must be expressed against the 14-channel L-12 multitrack and the software path currently in place, not the five-channel L-6 path of the prior design.

2. **Maximal dual-engine use**. The prior research defined three *siloed* routings (R1 voice-only Evil Pet, R2 sampler wet/dry, R3 S-4 USB-direct). The new directive treats siloing as a regression. Every broadcast-visible audio source must be usable by *both* processors simultaneously — the question is *how the engine duties divide across sources in the current moment*, not which single engine owns which single source.

3. **Dynamic switching**. The prior research catalogued static topologies and governance gates. It did not specify *what decides the current topology*. This doc adds §7 (control-law layer) and §8 (dynamic switching mechanisms) to fill that gap.

### Current configuration snapshot (verified 2026-04-21 04:25 UTC)

```
Hardware present (USB/ALSA):
  - L-12 (card 12, 14-ch multitrack, class-compliant UAC2)
  - MIDI Dispatch (Erica Synths, card 11) → Evil Pet MIDI ch 1
  - Evil Pet (analog loop: L-12 MONITOR A → IN, OUT → CH1 XLR → CH6 input, AUX5 on capture)
  - Ryzen HDA line-out (alsa_output.pci-0000_73_00.6.analog-stereo) → L-12 CH11/12 (AUX10/11)
  - Cortado MKIII contact mic → L-12 CH2 (AUX1)
  - Blue Yeti (USB, card 10, private by default)

Hardware absent:
  - Torso S-4 (not USB-enumerated; `hapax-s4-content` sink is registered but has no producer)
  - PreSonus Studio 24c (retired)

PipeWire routing (live):
  HAPAX_TTS_TARGET=hapax-voice-fx-capture
  hapax-voice-fx-capture → (HPF 80 / lowmid −2dB / presence +3dB / air +2dB)
    → hapax-voice-fx-playback
    → alsa_output.Ryzen.analog-stereo
    → physical cable → L-12 CH11/12 → MONITOR A bus → Evil Pet → CH1 XLR → CH6
    → L-12 multichannel capture AUX5 (+ AUX10/AUX11 raw PC via same CH11/12)
    → hapax-l12-evilpet-capture filter-chain (sum_l/sum_r)
    → hapax-l12-evilpet-playback → hapax-livestream-tap → OBS → broadcast

Evil Pet preset pack (13, all queryable via shared.evil_pet_presets):
  hapax-unadorned    (T0 bypass)
  hapax-radio        (T1 announcement)
  hapax-broadcast-ghost  (T2 default, always-on)
  hapax-memory       (T3 memory-callback)
  hapax-underwater   (T4 underwater)
  hapax-granular-wash (T5 granular)
  hapax-obliterated  (T6 rare, gated)
  hapax-mode-d       (vinyl DMCA defeat)
  hapax-bypass       (governance fallback)
  hapax-sampler-wet  (music — sampler-optimised granular)
  hapax-bed-music    (music — low-impact background)
  hapax-drone-loop   (music — sustained granular drone)
  hapax-s4-companion (music — S-4-paired subtle Evil Pet coloration)
```

### Drift identified (current-config bypass mechanism, 2026-04-21 03:xx UTC)

`hapax-l12-evilpet-capture.conf` sums **both** `gain_evilpet` (AUX5, Evil Pet hardware return) **and** `gain_pc_l/r` (AUX10/11, raw Ryzen PC line). If the Evil Pet hardware loop (MONITOR A → IN, OUT → CH1) is intact, the broadcast contains dry PC + Evil Pet return — Evil Pet is a colour layer, not a gate. If the loop is silent (broken cable, wrong L-12 SD scene, wrong MONITOR A mix), broadcast is 100% raw PC audio — **full Evil Pet bypass**, signal-invariant. This is out-of-spec relative to UC1 (§5.1 prior research, R1 in the plan): the design never called for raw PC on the broadcast sum. The bypass is the primary concrete motivator for this research.

### Top 3 recommendations under the new directive

**TR1 — Dual-engine voice character (UC1' in §6.1).** TTS splits at `hapax-voice-fx-playback`: one branch to Ryzen → L-12 MONITOR A → Evil Pet (T2 default, MIDI CC recall); second branch to `hapax-s4-content` via a new PipeWire loopback, then through S-4 Track 1 (Bypass-Bypass-Ring-Deform-Vast) → L-12 CH7/8 analog return (or S-4 USB back to `hapax-s4-tap`). Two complementary characters summed at livestream-tap. Operator blends via L-12 per-channel gain in the software filter-chain, not hardware faders. *Fallback:* if S-4 absent, broadcast drops to single-engine Evil Pet only (the R1 path); no other degradation.

**TR2 — Complementary split per source (UC2' in §6.2).** Simultaneously, *by source identity*: voice (TTS / Rode) always through Evil Pet; music (YT/SoundCloud/vinyl-dry) always through S-4; sampler chops through both (Evil Pet dry-path coloration + S-4 time-stretch). No source has both engines processing it *unless* the director recruits a dual-engine programme. Reduces anthropomorphization risk from §5.5 (parallel dual-processor on voice) while keeping both engines maximally utilised on each broadcast tick.

**TR3 — Dynamic arbiter agent (`agents/audio_router/dynamic_router.py`, new).** 5 Hz tick, reads stimmung + programme + impingement + ephemeral state (§7.1), writes: (a) Evil Pet preset recall (MIDI), (b) S-4 scene/track target (MIDI program change + macro), (c) filter-chain gain adjustments via `/dev/shm/hapax-audio/router.json`. Control-law layer (§7.2) arbitrates overlapping requests; operator CLI always wins (§7.8). This is the piece that was missing from the 2026-04-20 research — *what decides the topology at runtime*.

---

## §2. Current configuration at fingertips (2026-04-21)

### §2.1 Hardware present

| # | Device | Connection | ALSA card | Linux driver | Role in path |
|---|--------|-----------|-----------|--------------|--------------|
| H1 | **ZOOM LiveTrak L-12** | USB (bus 003:024, `1686:03d5`) | 12 | snd-usb-audio (UAC2, class-compliant, `QUIRK_FLAG_GENERIC_IMPLICIT_FB` via `quirk_flags=0x40`) | 14-ch multitrack USB capture + analog-surround-40 playback. Source of truth for broadcast sum (sums 10 of 12 pre-fader/post-comp channels). |
| H2 | **Erica Synths MIDI Dispatch** | USB (card 11) | 11 | snd-usb-audio (USB-MIDI) | MIDI patchbay: `hw:11,0,0` → Evil Pet ch 1 (hardwired). No S-4 MIDI port live (would need second patchbay lane when S-4 plugs in). |
| H3 | **Endorphin.es Evil Pet** | Analog (mono 1/4" TS in/out) + MIDI DIN in | — | (no ALSA; controlled via MIDI through H2) | Linear FX processor + granular synthesiser. Parameter space = 39 CCs. Mutex-held granular engine (§9.1 Mode D). |
| H4 | **Ryzen HDA (motherboard)** | PCIe | 4,5 (analog-stereo on `pci-0000_73_00.6`) | snd-hda-intel | TTS fan-out point: Kokoro → voice-fx-chain → Ryzen analog → L-12 CH11/12. Also carries YT/SoundCloud/any non-S-4 PC audio. |
| H5 | **Cortado MKIII contact mic** | Analog (XLR, +48V phantom) | — | (via L-12 CH2 preamp) | Desk-activity signal → AUX1 in capture. **Private by default** (not broadcast). |
| H6 | **Blue Yeti** | USB (card 10) | 10 | snd-usb-audio | Room-ambient USB mic. Private by default. |

### §2.2 Hardware absent (but addressable in software)

| Device | Expected connection | Current state | What's still live |
|--------|--------------------|---------------|--------------------|
| **Torso Elektron S-4** | USB-C (class-compliant, 10-in/10-out) + optional 2× 1/4" TR analog | Not USB-enumerated (no `Elektron_Torso*` entry in lsusb, no `alsa_*_usb-Elektron*` in arecord). | `hapax-s4-content` loopback sink (defined in `config/pipewire/hapax-s4-loopback.conf`); `hapax-s4-tap` playback stream → `hapax-livestream-tap`. Sink is silent because no producer targets it. Plan-complete, hardware-absent. |

**Implication for this research**: §6 use-cases that require S-4 are described as *current-config-compatible when the device is plugged in*. §10 Phase A (the immediate remediation) assumes S-4-absent; §10 Phase B unlocks at S-4 plug-in time. No use-case in §6 is *dependent* on S-4 being present for its minimum viable variant — S-4 is an enhancement axis, not a blocker.

### §2.3 Software routing (live graph, pw-dump verified)

Ten `hapax-*` PipeWire nodes are live:

```
Sinks (Audio/Sink):
  hapax-voice-fx-capture   — TTS input; HPF 80Hz + lowmid −2dB + presence +3dB + air +2dB
  hapax-private            — loopback into Ryzen line-out (currently also the role.notification target)
  hapax-livestream         — OBS content sink (terminal; OBS consumes this)
  hapax-livestream-tap     — pre-OBS tap for broadcast-side FX / metering
  hapax-yt-loudnorm        — YT bed input sink (−16 LUFS / −1.5 dBTP normalized)
  hapax-s4-content         — S-4 USB content sink (producer-less; dormant)

Streams (Stream/*):
  hapax-voice-fx-playback  — voice-fx → Ryzen → L-12 CH11/12 physical path
  hapax-private-playback   — hapax-private → Ryzen line-out
  hapax-yt-loudnorm-playback — yt-loudnorm output; currently routes to output.loopback.sink.role.multimedia → Yeti sink (suspect drift; should route to hapax-livestream or hapax-s4-content instead)
  hapax-l12-evilpet-capture — 14-ch filter-chain (AUX0..AUX13 → sum_l/sum_r)
  hapax-l12-evilpet-playback — filter-chain output → hapax-livestream-tap
  hapax-s4-tap             — S-4 loopback output → hapax-livestream-tap (dormant)
  hapax-vinyl-playback     — vinyl (from prior 24c-era; now dormant)
  hapax-livestream-tap-src / hapax-livestream-tap-dst — tap monitor/playback virtual loopback
  output.loopback.sink.role.assistant — daimonion assistant SFX loopback
```

### §2.4 MIDI topology (live)

```
ALSA seq clients:
  14 Midi Through (kernel)
  16..19 Virtual Raw MIDI 0-0..0-3 (VirMIDI card 0) — not externally connected
  60 MIDI Dispatch MIDI 1 (Erica, card 11) — hardwired patchbay to Evil Pet

amidi:
  hw:0,0..0,3 VirMIDI (ignored for audio FX)
  hw:11,0,0 MIDI Dispatch MIDI 1 — the active Evil Pet channel
```

**Evil Pet MIDI reachable** via `mido.open_output('MIDI Dispatch MIDI 1')` or `amidi -p hw:11,0,0`. Preset recall latency (measured in prior research): ~20 ms per CC, ~15 CCs per preset ≈ 300 ms per preset transition.

**S-4 MIDI not live** — would require either a second MIDI Dispatch output lane (Erica has multiple OUT ports) or a USB-MIDI adapter. Erica Dispatch is documented to have 2+ outputs in the prior research (OUT 2 is reserved for S-4 in `mode-d-voice-tier-mutex.md` §4.3).

### §2.5 State surfaces (live runtime variables)

- **Working mode**: `~/.cache/hapax/working-mode` = `rnd` (research-and-development; fortress mode excluded).
- **Stimmung current state**: `/dev/shm/hapax-stimmung/current.json` — currently empty/missing (stimmung writer may be down). When live, exposes stance, 6-dim vector, exploration_deficit.
- **Voice-tier state**: `/dev/shm/hapax-voice-tier-current.json` — missing. Voice-tier routing layer not currently writing state (either director loop down or writer never attached).
- **Evil Pet state ledger**: `/dev/shm/hapax-compositor/evil-pet-state.json` — authoritative MIDI ownership file (per prior research §6.2); heartbeat refresh every 5s. Staleness > 15s → assume bypass. Not audited in this session.
- **Impingement stream**: `/dev/shm/hapax-dmn/impingements.jsonl` — continuous; two consumers read (CPAL + affordance loop).
- **Ephemeral**: no-vinyl-state JSON, mode_d_active flag, operator VAD from Rode, phone-context from hapax-phone — all addressable via shared.state.

**Observation**: at least three state surfaces that the dynamic router needs are currently not writing. §10 Phase A item A5 is to verify/reinstate those writers before the router can tick.

---

## §3. Source inventory (revised for current configuration)

Seven live PC audio sources; two private, five broadcast-addressable. Each is tagged with current routing (what's live) and target routing (what the design calls for).

| # | Source | Content | Current path (live) | Target path (this design) | Default FX profile |
|---|--------|---------|---------------------|---------------------------|---------------------|
| **S1** | **Hapax TTS (Kokoro)** | Narration, dialogue, system-state annotations | `hapax-voice-fx-capture` → Ryzen → L-12 CH11/12 → (hardware: MONITOR A → Evil Pet → CH6) AND (software: AUX10/11 direct sum — **drift**) | `hapax-voice-fx-capture` → split: (a) Ryzen → L-12 MONITOR A → Evil Pet hardware return (AUX5 only); (b) `hapax-s4-content` → S-4 Track 1 FX → CH7/8 or `hapax-s4-tap` | **T2 BROADCAST-GHOST on Evil Pet (default)**; S-4 Track 1 on `hapax-s4-companion`-equivalent vocal scene |
| **S2** | **Vinyl (Korg Handytrax)** | DJ-mixed records | L-12 CH9/10 stereo direct → AUX8/9 in capture → broadcast dry | Dry path unchanged; optional AUX send to Evil Pet Mode D (T5 granular wash) for DMCA defeat | Dry by default; Mode D when operator opts in (governance-gated) |
| **S3** | **Operator voice (Rode Wireless Pro)** | Live speech | L-12 CH5 → AUX4 | Mostly dry (Rode handles its own compression); optional AUX send to Evil Pet T1 RADIO for announcement moments; S-4 Vast (short reverb) for room coherence with vinyl | Rarely T0..T2 coloration; duet mode with TTS is §6.4 |
| **S4** | **Contact mic (Cortado MKIII)** | Desk-activity DSP signal | L-12 CH2 → AUX1 (pre-fader to capture) | **Private** — governed off broadcast; feeds presence detection only | Never through broadcast FX; `gain_contact` is operator's private-monitor gain only |
| **S5** | **YT/SoundCloud browser audio** | Music beds, stream content | Chromium PulseAudio → default sink (mixer_master, currently) → leaks into mixer_master → capture → broadcast | `hapax-yt-loudnorm` sink (−16 LUFS/−1.5 dBTP) → split: (a) `hapax-s4-content` → S-4 Track 2 music scene; (b) *minor* Evil Pet coloration via S-4-companion → hapax-livestream-tap | S-4 primary (Ring+Deform+Vast clean music FX); Evil Pet secondary only on programme recruitment |
| **S6** | **System notifications** | Chat alerts, app chimes | `output.loopback.sink.role.notification` → `hapax-private` → Ryzen → L-12 CH11/12 (!) | Route notifications to a dedicated `hapax-notification-private` sink that is **never** captured by the L-12 filter-chain | Always bypassed; governance-forbidden on broadcast (per prior research §3 S6) |
| **S7** | **Assistant SFX** | Daimonion chimes, stingers | `output.loopback.sink.role.assistant` → hapax-livestream | Same, but add optional Evil Pet T1 path when stimmung=ENGAGED and SFX is programme-aligned | Typically dry (T0); T1..T2 subtle colour on programme recruitment |
| **S8** | **Blue Yeti room ambient** | Environment, ASMR, room noise | Private (not broadcast) | Same; if programme recruits (rare), route through hapax-yt-loudnorm for level consistency, then S-4 Vast for room reverb | Rare, programme-gated |

**Audit findings on current state**:

1. **S1 drift** — the `hapax-l12-evilpet-capture.conf` sums AUX10/11 (raw PC from S1 path via CH11/12) *and* AUX5 (Evil Pet return via CH6). Target is: AUX5 only. Fix = filter-chain edit (§10 Phase A1).
2. **S5 hapax-yt-loudnorm producer missing from S4 path** — `hapax-yt-loudnorm-playback` currently routes to `output.loopback.sink.role.multimedia` → Yeti sink; it should target `hapax-s4-content` when S-4 plugs in, with a fallback to livestream-tap direct. (§10 Phase B wires this.)
3. **S5 Chromium default sink** — not currently named; audio probably flows via default routing → mixer_master. **Unreliable for broadcast**. Browser audio should be force-targeted to `hapax-yt-loudnorm` via WirePlumber rule.
4. **S6 notification path** — `hapax-private` currently serves both operator-private Ryzen monitoring AND notification loopback, which means chat chimes hit the L-12 CH11/12 physical path alongside TTS. Notifications must split off to a sink that is NOT captured by the L-12 filter-chain. (§10 Phase A4.)
5. **S8 Yeti auto-link bleed** — unrelated to this research but flagged in memory `reference_brio_mic_autolink_bleed.md`; WirePlumber default-source policy historically auto-links unexpected mics into broadcast chains. Pin Yeti with `node.passive=true` if it ever starts appearing in the sum.

---

## §4. Destination inventory (revised)

| Destination | Path | Broadcast-bound? | Monitor? | Role under new directive |
|-------------|------|------------------|----------|--------------------------|
| **L-12 broadcast sum** (via filter-chain) | 14ch capture → `hapax-l12-evilpet-capture` → sum_l/r → `hapax-l12-evilpet-playback` → `hapax-livestream-tap` → OBS | YES | NO | Primary broadcast output. Every capture channel with a non-null stage contributes. |
| **L-12 MASTER OUT (analog)** | L-12 master fader → speakers | NO | YES (operator) | Room monitor. Independent of broadcast content (operator can solo / mute without affecting livestream). |
| **L-12 PHONES** | Phones knob → headphones | NO | YES (operator) | Private operator monitoring. |
| **L-12 MONITOR A (hardware send bus)** | Per-channel MONITOR A knob → analog MON-A out → Evil Pet input | (send, not output) | — | **Hard rule** — exactly one voice-class source at a time (mutex: vinyl-Mode-D and TTS-T5 can't both occupy MON-A simultaneously; see §7.5 arbitration). |
| **Evil Pet → CH1 XLR → CH6 input (AUX5)** | Evil Pet OUT (line) → hardware loop → L-12 CH6 → AUX5 in capture → filter-chain `gain_evilpet` stage | YES (via broadcast sum) | (monitor only via L-12 MASTER) | FX return. Governed by Evil Pet preset + current L-12 CH6 gain + software `gain_evilpet` in the filter-chain. |
| **S-4 USB out → `hapax-s4-content` (sink → `hapax-s4-tap`)** | S-4 USB stereo pair → `alsa_input.usb-Elektron_Torso*` → loopback → `hapax-s4-content` → `hapax-s4-tap` → `hapax-livestream-tap` | YES (when S-4 plugged) | NO direct | **The R3 path**. Parallel to Evil Pet, not serial. Currently dormant (no S-4 hardware). |
| **S-4 analog OUT 1/2 → L-12 CH7/CH8** | S-4 OUT (line) → L-12 CH7 (AUX6) and CH8 (AUX7) | YES (via broadcast sum) | (monitor via MASTER) | Hardware alternative to USB. Lower latency (analog) but consumes L-12 channels currently marked "reserve" in `hapax-l12-evilpet-capture.conf`. |
| **`hapax-livestream-tap-src:input_FL/FR`** | Tap monitor loopback → ?  | (tap) | (metering) | Used by PipeWire-internal monitoring. |
| **Dry fallback (ch 11/12 direct, if AUX10/11 preserved)** | L-12 CH11/12 → AUX10/11 → filter-chain `gain_pc_l/r` → sum | YES (currently; the **drift path**) | YES | Governance-mode: usable as an emergency dry-bypass *only* if explicitly gated by stimmung=FORTRESS or operator override. Not the default. (§10 Phase A1.) |

### §4.1 Destination-by-purpose summary

- **Primary broadcast egress**: `hapax-livestream-tap` (single choke point; all audit / metering happens here).
- **Governance tap**: `hapax-livestream-tap-src` → monitor-only loopback that re-emits the broadcast sum for metering, Ring-2 WARD classifier input, and loudness monitor.
- **Operator monitor**: L-12 MASTER OUT + PHONES (independent, physical).
- **Private (never broadcast)**: contact mic CH2, Blue Yeti, system notifications post-reroute (§10 A4).
- **Processing returns**: Evil Pet → AUX5; S-4 → `hapax-s4-tap` OR AUX6/7.

---

## §5. Routing topology classes (expanded for dual-engine directive)

The prior research enumerated 7 static topology classes (§5.1..§5.7). All seven are retained under this design. In addition, five new **dual-engine** classes (D1..D5) capture the maximal-use directive.

### §5.1..§5.7 — preserved classes (citing prior research)

Prior classes are reused without change:

- **§5.1 Single-Evil-Pet linear** (R1 basic voice path). Fallback for S-4-absent.
- **§5.2 Single-S-4 linear** (music-only, S-4 present).
- **§5.3 Serial Evil Pet → S-4** (deepest texture, rare, gated).
- **§5.4 Parallel dry-wet (L-12 dry ch + Evil Pet ch)** (operator-driven fader blend).
- **§5.5 Parallel Evil Pet + S-4 simultaneous** (two granular characters summed).
- **§5.6 MIDI-coupled S-4 sequencer ↔ Evil Pet** (rhythmic cross-modulation).
- **§5.7 Hybrid L-12-aware (sampler dry + Evil Pet FX return)** (sampler stems + texture).

All failure modes, control surfaces, latency budgets, and governance gates from prior §5 stand. The L-6-specific language maps onto L-12 as: ch5→CH11/12 (PC fan-out), ch4→CH9/10 (vinyl stereo), ch3→CH6 (Evil Pet return / AUX5), ch6→CH7/8 (S-4 analog return / AUX6/7), AUX1→MONITOR A.

### §5.8 D1 — Dual-parallel voice (both engines process the same TTS)

**Pattern.** Kokoro TTS → `hapax-voice-fx-playback` → **fan-out**:
- Branch A: Ryzen → L-12 CH11/12 → MONITOR A → Evil Pet (preset per tier) → CH6 → AUX5 → filter-chain `gain_evilpet` → sum_l/r
- Branch B: PipeWire loopback (new module) → `hapax-s4-content` → S-4 USB in → S-4 Track 1 (vocal scene, e.g. *HAPAX-VOCAL-COMPANION* = Bypass-Bypass-Ring-Deform-Vast) → S-4 USB out → `hapax-s4-tap` → `hapax-livestream-tap`

Both branches converge in the broadcast sum (one via L-12 capture, the other via the tap).

**Control surface.**
- Evil Pet preset recall: `shared.evil_pet_presets.recall_preset('hapax-<tier>')` via MIDI Dispatch OUT 1.
- S-4 scene recall: MIDI program change on S-4 ch 1 (when MIDI Dispatch OUT 2 wired), or macro encoder adjustment.
- Software gains: `gain_evilpet` and a new `gain_s4_vocal` on the filter-chain (or on `hapax-s4-tap`).
- Operator crossfade: realtime adjustment of `gain_evilpet:In 1` vs `gain_s4_vocal:In 1` via pw-cli.

**Failure modes.**
- Evil Pet fails → Branch A silent; Branch B (S-4) continues. Broadcast still has voice character.
- S-4 fails → Branch B silent; Branch A (Evil Pet) continues. Standard single-engine fallback.
- Both fail → no broadcast voice character (intolerable). Governance: operator CLI emergency recovery drops both branches and enables AUX10/11 direct (the drift path) as emergency dry.
- Phase mismatch between branches → inherent, because latencies differ (Evil Pet ~0 ms analog; S-4 ~5–12 ms USB). Solution: intentionally embrace the staggering (spatial depth) or delay-compensate Branch A in software if tight sync needed.

**Use case fit.** §6.1 ("dual voice character"), §6.4 ("operator duet live mix"), §6.6 ("research capture double-take").

**Latency.** Branch A ~0 ms, Branch B ~5–12 ms. Summed; broadcast carries both.

**Feedback risk.** NONE. Both branches terminate at `hapax-livestream-tap`; no path loops back to the shared source.

**Governance fit.** If Evil Pet preset is T4 or lower AND S-4 vocal scene excludes Mosaic granular, then voice intelligibility floor preserved. T5 on both simultaneously = dual-granular = max anthropomorphization risk → requires programme gate + monetization opt-in + explicit operator consent contract.

**Interaction with Mode D mutex (§9.1).** If vinyl Mode D is active, Evil Pet's granular engine is taken. Branch A's voice tier cannot exceed T4 (non-granular tiers only). Branch B's S-4 vocal scene is unaffected (S-4 Mosaic is independent). This is the `voice-tier-mutex` hot-path: when Mode D claims Evil Pet, voice-tier-5/6 recruitments are forwarded to S-4 Track 1 Mosaic instead (§7.5 arbitration rule R3).

### §5.9 D2 — Complementary split per source

**Pattern.** Source identity determines which engine processes:
- Voice class (TTS, Rode) → always Evil Pet (T-tier)
- Music class (YT, SoundCloud, vinyl-wet-via-Mode-D) → always S-4
- Percussive class (sampler, contact-mic-performative) → either, per programme

Both engines active on the same livestream tick, but on *different* content; no cross-engine contention. This is the "maximal" interpretation that preserves clear semantic separation.

**Signal flow (assuming S-4 live):**

```
TTS S1 → hapax-voice-fx → Ryzen → L-12 CH11/12 → MON-A → Evil Pet → CH6 → AUX5 → sum
YT/SC S5 → hapax-yt-loudnorm → hapax-s4-content → S-4 Track 2 (MUSIC scene) → hapax-s4-tap → livestream-tap
Vinyl S2 → L-12 CH9/10 direct → AUX8/9 → sum (dry) AND optional Mode D via MON-A/CH6 → sum
Sampler S* → L-12 CH4 direct → AUX3 → sum (dry) AND optional AUX send to Evil Pet (T5 sampler-wet preset)
```

**Control surface.** Per-source routing is static under this topology; dynamic layer is preset selection (§7.2) and gain staging.

**Failure modes.** Same as prior §5.1 + §5.2 combined. Evil Pet fail → voice silent (governance fallback to dry PC via AUX10/11 gated by FORTRESS mode). S-4 fail → music silent (governance fallback to dry YT via `hapax-yt-loudnorm` direct to livestream-tap).

**Use case fit.** §6.2 ("default livestream"), §6.5 ("live performance stack"), §6.8 ("monitor-only preview").

**Latency.** Sources have independent latencies; no additional stacking.

**Feedback risk.** NONE.

**Governance fit.** Highest-legibility default. No dual-granular on voice; no voice-coloration of music (which would sound intentional or anthropomorphic). Recommended baseline when operator hasn't specified otherwise.

### §5.10 D3 — Cross-character swap (context-driven engine reassignment)

**Pattern.** The default is D2 (complementary split). But on specific state triggers, the engine-to-source assignment swaps:
- **Trigger: stimmung=SEEKING, exploration_deficit>0.6** — voice routes to S-4 Mosaic (exploratory, textural) instead of Evil Pet T-tier. Evil Pet becomes available for music coloration.
- **Trigger: vinyl Mode D active** — voice-tier-5/6 requests route to S-4 Mosaic (Mode D mutex override; prior research §7).
- **Trigger: programme role = 'research_mode'** — both engines go to S-4 only; Evil Pet idle (for recording clean archive stems while S-4 handles all broadcast FX).

**Control surface.** Dynamic router agent (§7.2) selects the swap policy based on state; operator CLI can override.

**Failure modes.** Swap requires both engines alive; if one fails, fall back to single-engine version of the parent topology (D2 → §5.1 or §5.2).

**Use case fit.** §6.3 ("seeking exploration"), §6.9 ("impingement-driven shift"), §6.10 ("programme-gated unlock").

**Latency.** Swap latency = preset recall latency on both engines (Evil Pet ~300 ms + S-4 scene ~50 ms = ~350 ms worst-case total). Within stimmung-transition ramp budgets (§7.3).

**Feedback risk.** NONE.

**Governance fit.** Swaps must be audible-explicable. If the operator hears a character change mid-stream that they didn't ask for, the director event log (§7.7) should let them trace it back to a specific state trigger.

### §5.11 D4 — MIDI-driven dual-engine cross-modulation

**Pattern.** Both engines run simultaneously (as in D1 or D2), AND S-4 sequencer / modulator MIDI CC output modulates Evil Pet parameters via Erica Dispatch OUT 2 → Evil Pet MIDI IN. Prior research §5.6 covered single-direction modulation; this class extends to bidirectional:
- S-4 LFO → CC 40 (Evil Pet Mix) → rhythmic wet/dry sweep on voice
- Evil Pet MIDI transport / clock → S-4 internal clock sync → S-4 sequencer tempo-locks to Hapax-director cadence
- (Optional) Evil Pet user CC mapping → S-4 macro → Evil Pet's knob modulation drives S-4 Track 2 Ring resonance

**Control surface.** S-4 sequencer setup (step entry, swing, modulator routing); Evil Pet CC user mapping (CONFIG menu). Erica Dispatch routing matrix. All static after setup; only tempo / program numbers change dynamically.

**Failure modes.** MIDI Dispatch failure → modulation stops; both engines continue in last-known-good state. S-4 sequencer stop (user error or programmatic) → modulation silent; voice/music continue with static preset. Tempo drift on S-4 clock → audible as FX-period wandering.

**Use case fit.** §6.5 ("live performance stack"), specialised segments with rhythmic-gating aesthetic.

**Latency.** MIDI CC response ~10 ms + Evil Pet envelope ~2 ticks ≈ 20 ms total. Acceptable for rhythmic effects.

**Feedback risk.** NONE (MIDI is unidirectional per edge; bidirectional via separate paths).

**Governance fit.** Rhythmic modulation is signal-honest — depth and rate are explicit setup choices, not hidden algorithmic drift. Low anthropomorphization risk. Monetization: neutral unless combined with vinyl Mode D (then §5.6 / prior research applies).

### §5.12 D5 — Serial-fallback-parallel (operator-gesture-driven escalation)

**Pattern.** Baseline is parallel (D1 or D2). On operator gesture (`hapax-serial-mode on` CLI, or programme recruitment, or stimmung=TRANSCENDENT), the routing transitions to serial Evil Pet → S-4 (prior §5.3): Evil Pet output re-routes from `hapax-livestream-tap` into S-4 IN 1 (analog cable or software re-route via L-12 CH6 → AUX5 → PipeWire graph-mutate → S-4 USB IN). When gesture releases, parallel resumes.

**Control surface.** Single-gesture toggle. Internally: graph-mutation JSON at `/dev/shm/hapax-audio/topology.json`; router reads, dispatches pw-cli `set-param-default` commands or WirePlumber rule reloads.

**Failure modes.** Serial mode has two-device dependency (both alive). If either fails mid-segment, automatic revert to parallel (single engine) with operator notification via ntfy.

**Use case fit.** Specialised aesthetic moments — transitions, ritualistic passages, "drop" moments in a set. §6.7 ("emergency clean fallback") inverse-use: operator can also gesture OUT of all FX to raw bypass.

**Latency.** Topology transition ~1–2 s (PipeWire graph mutation + S-4 input retargeting). Not suitable for per-utterance switching; use D1 or D3 for those.

**Feedback risk.** Elevated during transition window (see prior §5.3 feedback risk); mitigated by `serial-mode-on` gesture requiring software confirmation before mutation (ntfy prompt or CLI double-confirm).

**Governance fit.** Mid-to-high anthropomorphization risk at transition boundary (operator may not anticipate the swap). Requires programme-level consent contract or stimmung=TRANSCENDENT gate. Telemetry-heavy: every gesture logged with timestamp + reason.

---

## §6. Use-case catalog (rewritten for maximal + dynamic dual-processor)

Ten use-cases. Each specifies: recommended topology, default presets, control surface, context triggers for the dynamic router, latency budget, failure recovery, and governance disposition.

### §6.1 UC1 — Dual voice character (operator-blended dual-engine TTS)

**Narrative.** Hapax TTS is processed by Evil Pet (T2 default) AND S-4 Track 1 (vocal-companion scene) simultaneously. Operator crossfades between the two characters in realtime via software gains. Evil Pet provides granular/reverb; S-4 provides ring-resonant spatial wash. Blend = operator aesthetic per-segment.

**Topology.** §5.8 D1 dual-parallel voice.

**Default presets.**
- Evil Pet: `hapax-broadcast-ghost` (T2, BP filter, subtle saturator, 20–30% reverb mix).
- S-4: `VOCAL-COMPANION` scene = Track 1, Material=Bypass, Granular=None, Filter=Ring (freq 2 kHz, Q 0.4, wet 35%), Color=Deform (drive 20, compression 40), Space=Vast (size 30, tone bright, wet 40%).

**Control surface.** Evil Pet preset via MIDI CC burst (`recall_preset`). S-4 scene via MIDI PC (program change 1 → `VOCAL-COMPANION`) or macro. Software gains: `gain_evilpet`, `gain_s4_vocal` (new stage in `hapax-s4-tap` or filter-chain — see §10 Phase B1). Operator can blend: 100% EP / 0% S4, or 50/50, or 0% EP / 100% S4, or anything between.

**Context triggers for dynamic router (§7).** Stance-driven:
- NOMINAL → 60% Evil Pet / 40% S-4
- ENGAGED → 80% Evil Pet / 20% S-4 (voice tightness emphasised)
- SEEKING → 40% Evil Pet / 60% S-4 (textural exploration)
- FORTRESS → 100% Evil Pet (clarity priority, S-4 Track 1 scene → *VOCAL-MUTE*)
- CONSTRAINED → 100% S-4 (voice sounds "far" — less demand on attention)

**Latency.** Evil Pet ~0 ms; S-4 ~5–12 ms USB. Broadcast carries both.

**Failure recovery.** Evil Pet fail → S-4-only (governance-OK); S-4 fail → Evil Pet-only (current default); both fail → dry fallback via FORTRESS mode gate.

**Governance.** Monetization-neutral if both T ≤ 4. T5+ on Evil Pet with S-4 Mosaic simultaneously = max risk (dual-granular) → programme opt-in required.

### §6.2 UC2 — Default livestream (complementary split, no dual-granular)

**Narrative.** Baseline livestream. Voice routes to Evil Pet only; music routes to S-4 only; vinyl dry; sampler dry. Single-engine per-source; both engines live on every broadcast tick.

**Topology.** §5.9 D2 complementary split.

**Default presets.** Evil Pet `hapax-broadcast-ghost` (voice); S-4 *MUSIC-BED* scene on Track 2 for YT, *MUSIC-DRONE* scene on Track 3 for SoundCloud if pinned.

**Control surface.** Static routing; dynamic layer = per-tier preset recalls on Evil Pet and per-track scene recalls on S-4 (via MIDI PC).

**Context triggers.** Programme role determines Evil Pet tier; stimmung 6-dim vector writes per-preset CC modulations.

**Latency.** Source-dependent; no additional.

**Failure recovery.** Standard per-engine fallback (voice-only or music-only until recovery).

**Governance.** Lowest-risk default. Recommended unless operator gestures otherwise.

### §6.3 UC3 — SEEKING-stance exploration (cross-character swap)

**Narrative.** When stimmung is SEEKING (exploration_deficit high, operator experimenting / curious), voice routes to S-4 Mosaic (textural, exploratory) instead of Evil Pet. Evil Pet becomes available for music coloration (overriding UC2's S-4-only music rule).

**Topology.** §5.10 D3 cross-character swap, triggered.

**Default presets.**
- S-4 Track 1: *VOCAL-MOSAIC* scene (Material=Bypass, Granular=Mosaic density 70%, position drift 30%, Filter=Ring q 0.7, Color=Deform drive 15, Space=Vast reverb tail 60%).
- Evil Pet: `hapax-s4-companion` (subtle Evil Pet coloration applied to music instead of voice; grain density 55%, reverb 40%).

**Context triggers.** `stance=SEEKING AND exploration_deficit > 0.6` (hysteresis: 3-tick entry, 5-tick exit). Optional: programme role `research_mode` forces this swap.

**Latency.** Swap latency = both engines' preset recall ~350 ms. Within stimmung-ramp budget (§7.3).

**Failure recovery.** Swap requires both engines alive. Fall back to D2 if one fails.

**Governance.** Voice-on-S-4-Mosaic is novel character — may surprise audiences if not narratively introduced. Director loop should emit a narrative preamble before engaging (§7.7 observability).

### §6.4 UC4 — Operator duet live mix (simultaneous operator + Hapax voice)

**Narrative.** Operator speaks on Rode; Hapax speaks on TTS. Both live on the broadcast. Hapax has dual-engine voice character (UC1); operator voice has subtle Evil Pet T1 RADIO or full-dry (operator's choice per-moment).

**Topology.** §5.8 D1 (for TTS) + §5.1 (for operator voice with optional §5.4 AUX blend).

**Default presets.**
- TTS on Evil Pet: `hapax-broadcast-ghost`.
- TTS on S-4: *VOCAL-COMPANION*.
- Operator voice on Evil Pet (optional): `hapax-radio` (T1). When operator gestures "dry only", that tier routes to T0 bypass.

**Control surface.** TTS path: as UC1. Operator voice path: L-12 CH5 fader + MON-A knob for optional Evil Pet send. If operator gestures to add Evil Pet to voice, router emits CC recall to `hapax-radio` and adjusts MON-A gain via L-12 hardware (operator's choice; software can't control L-12 physical knobs).

**Context triggers.** None automatic — this is an operator-initiated mode via CLI `hapax-duet-mode on`.

**Latency.** TTS as UC1. Operator voice ~0 ms (analog).

**Failure recovery.** Evil Pet fail → operator still audible dry; TTS on S-4 only. S-4 fail → TTS on Evil Pet only; operator dry.

**Governance.** Voice-on-voice (two voices simultaneously) requires consent-style governance: operator's voice always has priority in the mix (operator fader level) + TTS must duck when operator speaks (handled by existing VAD + voice-gate + ducker pipeline — alpha's B1 work).

### §6.5 UC5 — Live performance stack (S-4 sequencer + Evil Pet vinyl + TTS clean)

**Narrative.** S-4 runs a beat sequencer on Track 4 (generating percussive foundation). Vinyl plays on L-12 CH9/10, routed through Evil Pet Mode D for DMCA defeat. TTS narrates events (over-the-beat) cleanly, bypassing both processors. All three paths converge in the broadcast.

**Topology.** §5.11 D4 MIDI-coupled for S-4-sequencer-tempo-locks-vinyl + §5.7 hybrid L-12-aware (Evil Pet on vinyl AUX send) + §5.1 direct voice (Evil Pet T0 bypass).

**Default presets.**
- Evil Pet: `hapax-mode-d` (vinyl granular wash).
- S-4 Track 4: beat sequencer (*BEAT-1* program), Material=Tape (sample-based kick-snare-hi-hat), Granular=None, Filter=Peak (HPF 150 Hz to cut rumble), Color=Deform light drive, Space=None (no reverb on beat — keep it punchy).
- TTS: `hapax-unadorned` (T0, bypass) — voice stays crisp and dry while beat + vinyl occupy the FX space.

**Control surface.** S-4 front panel tempo + step entry (operator). Erica Dispatch OUT 2 → Evil Pet for optional tempo-coupled CC modulation (D4 extension).

**Context triggers.** Programme role = `live_performance` OR operator gesture `hapax-perf-mode on`.

**Latency.** S-4 sequencer tick ~5 ms; Evil Pet Mode D ~0 ms analog; TTS path ~0 ms.

**Failure recovery.** S-4 fail → beat silent; vinyl + TTS continue. Evil Pet fail → vinyl dry (DMCA risk elevated; programme should either pause vinyl or accept risk). TTS fail (Kokoro) → narration silent.

**Governance.** Mode D engaged → monetization flag `mode_d_granular_wash` required. Dual-engine simultaneous use on different sources — **no** dual-granular on any single source.

### §6.6 UC6 — Research capture double-take (S-4 records dry stems; Evil Pet for broadcast)

**Narrative.** During research sessions (working_mode=research), operator wants to capture clean stems for later analysis while the broadcast still has production FX. S-4 Track 1 is configured as a record-only passthrough (Material=Tape record; all other slots Bypass). Evil Pet applies broadcast character as usual. S-4 stems write to `~/hapax-research/stems/{timestamp}/track{N}.wav` (new feature, §10 Phase B).

**Topology.** §5.8 D1 with S-4 branch set to record-dry (Bypass) instead of vocal-FX.

**Default presets.**
- Evil Pet: Whatever tier is live (T2 default).
- S-4 Track 1: *RECORD-DRY* scene (Material=Tape record-enabled, Granular=None, Filter=None, Color=None, Space=None — pure recorder).

**Control surface.** S-4 record toggle via MIDI CC (S-4 CC 73 Track 1 Material Tape Record Gate) or macro; file path auto-incremented.

**Context triggers.** `working_mode=research` activates; recordings persist for 7 days then rotate.

**Latency.** S-4 USB recording ~5–12 ms; Evil Pet ~0 ms. Both carry broadcast-timing independently (record is time-stamped).

**Failure recovery.** S-4 record fail → stems lost (logged); broadcast unaffected. Evil Pet fail → broadcast character lost; record continues. Disk full on stems → record backs off; ntfy operator.

**Governance.** Recordings are governance-critical (audio may contain operator or other voices). Must honor consent contracts per `axioms/contracts/`. Auto-delete after 7 days (rotation). `interpersonal_transparency` axiom applies if any non-operator voice is likely.

### §6.7 UC7 — Emergency clean fallback (bypass all FX)

**Narrative.** Something's wrong — Evil Pet making a bad noise, S-4 in a weird state, or operator wants pristine live-reference. Single gesture → everything bypasses. Broadcast becomes: TTS dry, operator voice dry, vinyl dry, music dry. No FX anywhere.

**Topology.** All D* classes abandoned; each source single-path dry.

**Default presets.** Evil Pet `hapax-bypass` (grains=0, mix=0, saturator=0, reverb=0, filter=0). S-4 `BYPASS` scene (all slots off). AUX sends off. Filter-chain `gain_evilpet`=0 and `gain_s4_vocal`=0 (if added per §10).

**Control surface.** Single CLI: `hapax-audio-reset-dry` (new, §10). Equivalent stream-deck button, also.

**Context triggers.** Stimmung=FORTRESS OR operator emergency CLI OR programme explicit `force_bypass=true`.

**Latency.** Bypass CC burst ~300 ms per engine = ~600 ms total. Within "emergency" tolerance.

**Failure recovery.** If MIDI Dispatch dead, force bypass by killing L-12 MONITOR A (analog — hardware mute). If software routers dead, operator manually pulls L-12 faders to discrete source channels.

**Governance.** Always-allowed, always-available. Governance-critical fallback path. No gates.

### §6.8 UC8 — Monitor-only preview (dry-run before live)

**Narrative.** Operator wants to test a tier change or S-4 scene before committing to broadcast. Preview routes to operator headphones only (or a private sink), broadcast stays on prior preset. Operator listens, decides, then commits or aborts.

**Topology.** New: dual-engine preview via `hapax-voice-fx-monitor` sink (separate from `hapax-voice-fx-capture`). Monitor sink routes to L-12 PHONES via Ryzen (operator-only); not captured by filter-chain.

**Default presets.** Any preset being tested.

**Control surface.** CLI `hapax-voice-preview <preset>` or `hapax-s4-preview <scene>`. 10-second auto-cutoff unless `--commit` specified.

**Context triggers.** Operator only; no automatic.

**Latency.** Preview latency same as live path (~0 ms Evil Pet or ~5–12 ms S-4).

**Failure recovery.** Preview failure → no impact on live broadcast (by design).

**Governance.** Monitor sink must never be captured by livestream-tap filter-chain (guaranteed by design).

### §6.9 UC9 — Impingement-driven tier shift

**Narrative.** An imagination fragment with high salience (>0.7) and specific narrative tone arrives. Director loop recognizes: "this is a memory callback moment" → triggers tier shift from T2 → T3 for the duration of the narrative passage. Dual-engine: S-4 Track 1 scene also shifts to a companion *MEMORY-COMPANION* scene that complements the Evil Pet T3 character.

**Topology.** §5.8 D1 with dynamic preset recalls on both engines triggered by impingement.

**Default presets.**
- Evil Pet: `hapax-memory` (T3) — narrow BP filter around 1–1.5 kHz, slight grit, moderate reverb tail (evoking tape hiss / old-radio).
- S-4 Track 1: *MEMORY-COMPANION* — Material=Bypass, Granular=None, Filter=Peak (1.2 kHz narrow Q 2.0 wet 30%), Color=Deform (vintage tape saturation), Space=Vast (medium-long reverb, dark tone).

**Control surface.** Automatic — director loop emits `VoiceTierShift(target=T3, reason=imagination.memory_callback.salience=0.84)` which the router consumes.

**Context triggers.** `impingement.type=imagination AND impingement.kind=memory_callback AND impingement.salience > 0.7` (configurable threshold).

**Latency.** Impingement arrival → CC emit ~100 ms (router tick at 5 Hz + CC burst). Director narrative commitment "sticks" for duration of passage (§7.4).

**Failure recovery.** CC emit fail → log + revert to prior tier; director continues with prior character.

**Governance.** T3 is standard tier; no special gates. T5+ triggers from impingement require programme opt-in.

### §6.10 UC10 — Programme-gated texture unlock

**Narrative.** A specific programme (e.g., `programme/sonic_ritual`) unlocks T5 (GRANULAR-WASH) and Evil Pet Mode D + S-4 dual-Mosaic for a bounded duration. Outside the programme, T5 is clamped. Operator consents by selecting the programme; engagement is always voluntary + bounded.

**Topology.** §5.8 D1 with T5 on Evil Pet + S-4 Track 1 dual-Mosaic.

**Default presets.**
- Evil Pet: `hapax-granular-wash` (T5) — grains 120, mix 100%, reverb tail extended.
- S-4 Track 1: *SONIC-RITUAL* — Material=Bypass, Granular=Mosaic (density 90%, position drift, sparse grains), Filter=Ring (resonance 60%, wet 70%), Color=Deform (heavy bit-crush, governance-gated), Space=Vast (huge room, 60% reverb tail).

**Control surface.** Programme activation via `hapax-programme select sonic_ritual`. Monetization opt-in required (`monetization_opt_ins: [voice_tier_granular, mode_d_granular_wash]`). Auto-expires at programme-end.

**Context triggers.** Programme active AND opt-in flags present.

**Latency.** Full tier ramp: ~500 ms–2.5 s (see §7.3).

**Failure recovery.** Preset recall fail → log + use prior preset; programme continues.

**Governance.** Maximum governance gating:
- Monetization opt-in: `voice_tier_granular`.
- Mode D mutex: if vinyl is playing, Mode D claim may conflict — resolve per §7.5 arbitration.
- Monotonic intelligibility budget: voice-tier-5/6 totals ≤ 120s per 300s window (clamped by voice-tier governor).
- WARD classifier on broadcast must pass Ring-2 (voice must remain legible per CVS #8 non-manipulation).

---

## §7. Control-law layer (the missing piece)

The prior research specified *what is reachable*. This section specifies *how to navigate the reachable space in real time*.

### §7.1 State variables driving routing decisions

Inputs to the dynamic router (`agents/audio_router/dynamic_router.py`, new agent):

| State variable | Source | Cadence | Role in routing |
|----------------|--------|---------|-----------------|
| **Stimmung stance** | `/dev/shm/hapax-stimmung/current.json` | 1 Hz tick | Primary driver of tier selection per §7.2 lookup. |
| **Stimmung 6-dim vector** (energy, coherence, focus, intention-clarity, presence, exploration-deficit) | same | 1 Hz tick | Per-preset CC modulations (brightness → filter freq, density → grain volume, etc.). |
| **Programme role + opt-ins** | `/dev/shm/hapax-programme/current.json` | On change | Tier ceiling/floor, monetization unlocks, scene selection for S-4. |
| **Impingement stream salience** | `/dev/shm/hapax-dmn/impingements.jsonl` | Continuous tail | Delta modulation of target tier (imagination fragment → +1 tier toward T3..T5 per salience). |
| **Operator voice VAD (Rode)** | `/dev/shm/hapax-audio/rode_vad.json` (alpha's B1 output) | 50 ms | If operator speaking → duck TTS, reduce S-4 Vast reverb to avoid smearing. |
| **Vinyl Mode D active** | `/dev/shm/hapax-audio/mode_d.json` | On change | Triggers Mode D mutex arbitration (§7.5 R3). |
| **Sampler activity** (from capture signal level) | `/dev/shm/hapax-audio/sampler_active.json` (new, optional) | 200 ms | If sampler firing → ensure AUX send to Evil Pet is open for sampler-wet preset recall. |
| **Intelligibility budget** | `/dev/shm/hapax-audio/intelligibility.json` (alpha's B3 output, via ProgrammeManager) | 1 Hz tick | Clamp T5+ if budget exhausted (per prior design §8.2). |
| **Hardware state** (Evil Pet MIDI reachable, S-4 USB enumerated) | `/dev/shm/hapax-audio/hw_state.json` (new, from probe agent) | 10 s heartbeat | Disable topologies that require unavailable hardware; enable fallback topologies. |
| **Ephemeral capability-health** (recent CC emit success rate) | `capability_health.voice_tier_N_eval_success` Prometheus counter | Minute rolling | Bias director away from unreliable tiers. |

**Observation**: per §2.5, at least three of these state surfaces are currently not writing (stimmung, voice-tier, and possibly programme). §10 Phase A item A5 is to verify/reinstate those writers before the router can tick.

### §7.2 Decision rules / policy lookup

The router applies a **three-layer policy** per tick (5 Hz):

**Layer 1: Safety clamps (fail-closed, highest priority).** Any clamp returns immediately without consulting Layer 2 or 3.

- Consent-critical utterance → T0 (prior design §3, retained).
- Monetization opt-in missing for requested tier → clamp to T4 (or T0 if T0 is gatekeeper; see `monetization_risk_gate.py`).
- Intelligibility budget exhausted AND no programme override → clamp to T3 (cap of "intelligible" range).
- Mode D active AND Evil Pet granular requested for voice → reroute to S-4 Mosaic (§7.5 R3).
- Hardware state: MIDI Dispatch unreachable → Evil Pet tier locked to whatever is currently loaded (silent fail OK, fallback to dry if operator requests); S-4 USB unenumerated → fallback D2 → §5.1 single-Evil-Pet linear.

**Layer 2: Context lookup** (stance × programme → target tier + S-4 scene).

Simple table:

| Stance | No programme | `livestream_director` | `memory_narrator` | `research_mode` | `sonic_ritual` | `live_performance` |
|--------|-------------|-----------------------|-------------------|-----------------|----------------|--------------------|
| NOMINAL | T2 / BED | T2 / BED | T3 / MEMORY-COMPANION | T0 / RECORD-DRY | T5 / SONIC-RITUAL (opt-in) | T0 / BEAT-1 |
| ENGAGED | T2 / BED | T2 / BED | T3 / MEMORY-COMPANION | T1 / RECORD-DRY | T5 / SONIC-RITUAL (opt-in) | T1 / BEAT-1 |
| SEEKING | T3 / MOSAIC-EXPLORE (D3 swap) | T3 / MEMORY-COMPANION | T4 / UNDERWATER-COMPANION | T4 / RECORD-DRY | T5 / SONIC-RITUAL (opt-in) | T0 / BEAT-1 |
| ANT | T2 / BED | T2 / BED | T3 / MEMORY-COMPANION | T0 / RECORD-DRY | T4 / MEMORY-COMPANION | T0 / BEAT-1 |
| FORTRESS | T0 / BYPASS | T0 / BYPASS | T0 / BYPASS | T0 / BYPASS | T0 / BYPASS | T0 / BYPASS |
| CONSTRAINED | T2 / BED | T2 / BED | T3 / MEMORY-COMPANION | T0 / RECORD-DRY | T3 / MEMORY-COMPANION | T0 / BEAT-1 |

(Cells: `EvilPet-tier / S4-scene`. "BED" = `MUSIC-BED` on Track 2 for music; vocal Track 1 scene follows tier.)

**Layer 3: Salience modulation.** Impingements add deltas to the target tier:

- `imagination.memory_callback (salience s)` → ΔTier = +round(s) toward T3, duration = passage length.
- `imagination.ritual_fragment (salience s)` → ΔTier = +round(s) toward T5 (governance-gated).
- `perception.anomaly_detected (salience s)` → ΔTier = +round(s) toward T4.
- `operator.voice_characterization_intent (explicit)` → ΔTier = operator-specified; arbitration per §7.5.

Salience modulation is additive but clamp-bounded by Layer 1. Multiple concurrent impingements compose via *max*: Δ_final = max(Δ_1, Δ_2, ..., Δ_n), not sum. Max-composition ensures a single strong impingement dominates; sum would allow trivially-salient events to stack into T6.

### §7.3 Ramp-time responsiveness

Tier transitions are interpolated to avoid audible jumps. The interpolation is CC-level, not signal-level: the router emits a *sequence* of CC values between current and target over the ramp duration, rate-limited to 20 Hz per CC.

**Ramp time = inverse(stimmung_velocity)**, clamped:

- Stimmung_velocity = |d(stance)/dt|; high velocity = ramp_time 0.2 s (snappy).
- Low velocity = ramp_time 2.5 s (smooth).
- Default (stable stimmung) = ramp_time 1.0 s.

Formula: `ramp_s = clamp(0.2, 2.5, 0.8 / max(stimmung_velocity, 0.1))`.

Practical ramp completion: 20 CCs × 50 ms spacing = 1.0 s for a default tier change. A 0.2 s ramp = 4 CCs spacing → lower resolution but same ramp completion. A 2.5 s ramp = 50 CCs spacing → high resolution.

**S-4 scene transitions are step, not ramp.** Scene recall is a single MIDI program change; there's no cleaner way to interpolate. Character transitions during ramp are audible; acceptable for slow ramps (>1 s) but jarring for fast ramps (<0.3 s). Recommendation: for fast ramps, hold S-4 scene and only ramp Evil Pet (user perceives single-engine ramp without scene-transition artifact).

### §7.4 Utterance-boundary semantics

What happens to the active tier when TTS finishes speaking?

**Default policy: stick for 10 s.** After 10 s of silence (no TTS audio energy above −50 dB), the router reverts to `stance-default` tier (whatever Layer 2 would produce without impingement modulation).

**Rationale.** The 10 s window covers most inter-utterance pauses (Hapax narrates in paragraphs with 2–8 s pauses). Snapping to stance-default mid-paragraph would audibly reset the character; the operator listens to a sequence, not isolated bursts.

**Operator override via CLI.** `hapax-voice-tier <n> --sticky` pins the tier indefinitely until released. `--release` restores automatic behaviour.

**Impingement-override.** A new impingement during silence window can re-trigger a tier shift — the "sticky" behaviour is not strong; it's a weak default that yields to explicit state changes.

### §7.5 Arbitration order for overlapping requests

When multiple inputs want conflicting tiers, composition rules determine the winner. Order from highest to lowest priority:

1. **Consent-critical clamp.** If utterance is marked `consent_critical: true`, tier = T0. Absolute priority.
2. **Mode D mutex (R3 rule).** If vinyl Mode D is active and voice request is T5+, route voice to S-4 Mosaic (preserves granular character for voice, keeps Evil Pet granular on vinyl). This is not a "win" but a *re-route*.
3. **Monetization gate.** If requested tier requires opt-in and opt-in is missing, clamp to highest allowed tier per `monetization_opt_ins`.
4. **Intelligibility budget.** If request exceeds budget (T5+ would consume > remaining budget), clamp to T3 regardless of context.
5. **Operator CLI override.** Explicit conscious request. Wins over automatic recruitment.
6. **Programme target.** Per-programme tier floor/ceiling from `programme.voice_tier_target` field.
7. **Director recruitment (impingement-derived).** Salience modulation from §7.2 Layer 3.
8. **Stance default.** Per §7.2 Layer 2 lookup.

**Edge case: two operator CLI overrides within 100 ms.** Last-write-wins (atomic rename of `/dev/shm/hapax-audio/operator-override.json`). Latency spec: operator acknowledged after override takes effect (~50 ms recall completion).

### §7.6 Latency budgets

For each switching mechanism, target budget:

| Switch type | Budget | Current | Notes |
|-------------|--------|---------|-------|
| Evil Pet single CC emit | ≤ 20 ms | ~20 ms (measured) | Near-lock. Any regression is a bug. |
| Evil Pet preset recall (15 CCs) | ≤ 300 ms | ~300 ms | Per CC-burst debounce of 50 ms × sparse parameters. |
| S-4 MIDI PC (program change) | ≤ 50 ms | Untested (S-4 absent) | S-4 manual spec; verify at plug-in. |
| S-4 full scene reload (5 slots × ~4 CCs each) | ≤ 200 ms | Untested | Per-slot debounce suggests 100 ms; spec is 200 ms ceiling. |
| Handoff sequence (Mode D ↔ voice-tier-5/6) | ≤ 300 ms | ~200 ms (measured per prior design) | Ordered CC burst per `mode-d-voice-tier-mutex.md`. |
| Full topology swap (D5 parallel ↔ serial) | ≤ 2000 ms | Untested | PipeWire graph mutation. Not suitable per-utterance. |
| Router tick period | 200 ms (5 Hz) | New (to be built) | Informs minimum latency for context-response (router can't react faster than tick period). |

**Failing-fast path.** If any CC emit fails (MIDI write error), router:
1. Logs to Prometheus counter `hapax_voice_tier_cc_emit_failures_total{cc,preset}`.
2. Does NOT retry (avoids cascading failures).
3. Continues with next CC (graceful degradation; some params may be stale).
4. Router increments `capability_health.voice_tier_{tier}_reliability` downward.

### §7.7 Feedback loop / observability closure

The prior research had no director-feedback mechanism. This design closes the loop:

- **Prometheus** (updated per tick):
    - `hapax_evilpet_preset_active{preset}` (gauge)
    - `hapax_evilpet_preset_recalls_total{preset}` (counter)
    - `hapax_evilpet_cc_emits_total{cc,preset,outcome="success|fail"}` (counter)
    - `hapax_s4_scene_active{track,scene}` (gauge)
    - `hapax_s4_scene_recalls_total{track,scene}` (counter)
    - `hapax_audio_router_tick_seconds` (histogram)
    - `hapax_voice_tier_transitions_total{from,to,reason}` (counter)
    - `hapax_voice_tier_clamp_total{reason}` (counter; reasons: consent_critical, intelligibility_budget, monetization_gate, mode_d_mutex)
    - `capability_health.voice_tier_{0..6}_reliability` (gauge; reliability = rolling mean of success rate over last 5 minutes)

- **Langfuse events** (per tier transition):
    ```json
    {"type": "voice_tier_transition",
     "from": "T2", "to": "T3",
     "reason": "imagination.memory_callback.salience=0.84",
     "ramp_s": 1.0, "success": true,
     "clamp_reason": null,
     "s4_scene_shifted": true}
    ```

- **Structured log** at `~/hapax-state/audio-router/router.jsonl` — per-tick decisions for post-hoc analysis. Rotation: 10 MB / keep 5. 

- **Director feedback**: `capability_health` gauges feed into the unified recruitment pipeline (AffordancePipeline). If `voice_tier_5` reliability < 0.8, director biases away from T5 in its Thompson-sampling prior for future recruitments. This closes the loop: *performed reliability informs future intent*.

### §7.8 Operator escape hatches

Every automatic behavior has a manual override:

- `hapax-voice-tier <0..6>` — set tier immediately.
- `hapax-voice-tier 2 --sticky` — pin tier until released.
- `hapax-voice-tier --release` — resume automatic.
- `hapax-evilpet-recall <preset>` — force specific preset.
- `hapax-s4-scene <track> <scene>` — force S-4 scene.
- `hapax-mode-d on|off` — explicit Mode D claim.
- `hapax-audio-reset-dry` — UC7 emergency clean fallback.
- `hapax-voice-preview <preset>` — UC8 monitor-only preview.
- `hapax-audio-router stop` — pause router ticks; operator manually drives everything.
- `hapax-audio-router start` — resume.

Operator CLI always wins per §7.5 priority 5. Commands emit Langfuse events with `reason: "operator_override"` for audit.

---

## §8. Dynamic switching mechanisms

Four primitive mechanisms available to the router:

### §8.1 MIDI CC burst (Evil Pet)

- **Transport**: ALSA sequencer (`mido.open_output('MIDI Dispatch MIDI 1')`) or direct ALSA (`amidi -p hw:11,0,0`).
- **Debounce**: 50 ms minimum per CC (rate-limit, prevents CC storming).
- **Atomic per CC, non-atomic per preset**: a 15-CC preset recall is 15 independent MIDI messages. If one fails, others still emit (graceful degradation). No rollback.
- **Latency**: ~20 ms per CC + 50 ms debounce = ~70 ms min sequence; 15 CCs ≈ 300 ms total.
- **Used for**: Evil Pet preset recalls, per-tick CC modulations (grain density tracking stimmung energy, etc.).

### §8.2 MIDI program change (S-4)

- **Transport**: same ALSA seq; requires S-4 MIDI lane (Erica Dispatch OUT 2 → S-4 MIDI IN, not yet physically configured).
- **Atomic**: program change is a single MIDI message; S-4 loads the program immediately.
- **Latency**: ≤ 50 ms (S-4 spec).
- **Used for**: S-4 scene transitions (e.g., *MUSIC-BED* → *VOCAL-MOSAIC*).

### §8.3 PipeWire graph mutation

- **Transport**: `pw-cli set-param-default`, WirePlumber rule reloads, or graph-mutation file writes.
- **Scope**: can re-target link endpoints, adjust gain stages, toggle passive mode.
- **Latency**: ~50 ms for gain/param changes; ~1–2 s for topology changes (link create/destroy).
- **Used for**: software gain adjustments (`gain_evilpet`, `gain_s4_vocal` in filter-chain); per-tier output routing.

### §8.4 Filter-chain parameter writes

- **Transport**: `/dev/shm/hapax-audio/filter_chain_params.json` — atomic rename semantics; filter-chain reads via `rules` block.
- **Scope**: per-node gain controls in the L-12 capture chain (sum_l/r input gains).
- **Latency**: ~20 ms (file write + filter-chain read).
- **Used for**: real-time gain ducking (voice-over-music duck when Rode VAD active), per-tier character-blend gains.

---

## §9. Governance constraints (preserved + extended)

### §9.1 Mode D mutex (from prior research, retained)

Evil Pet granular engine is exclusive: either vinyl Mode D OR voice-tier-5/6, never both. Arbitration: vinyl wins if both recruited in same tick (§7.5 R2). Blocked voice-tier-5 request is re-routed to S-4 Mosaic (R3 re-route).

### §9.2 HARDM anti-anthropomorphization (from prior research, retained)

No face-iconography in voice character. Shimmer permanently clamped to 0. Breath/sigh effects disallowed. Pitch-LFO to voice blocked. Envelope→filter mod capped at 60. `shared/governance/vocal_restraints.py` enforces at CC-emit boundary.

### §9.3 Consent contracts (prior research, retained)

`axioms/contracts/` gates dual-granular (voice-tier-5/6 + Mode D simultaneous) and cross-character swaps that may surprise audience (D3). Programme-level opt-in mechanism.

### §9.4 Intelligibility budget (prior research, retained)

Rolling 5-min window. T5–T6 clamped after 120 s / 15 s cap exhausted per window. Programme `intelligibility_gate_override: true` disables.

### §9.5 Monetization gates (prior research, retained)

Opt-ins required on programme: `voice_tier_granular`, `mode_d_granular_wash`, `dual_granular_simultaneous` (new; unlocks T5 on Evil Pet + Mosaic on S-4 at once).

### §9.6 **Dual-engine-anthropomorphization (NEW)**

If both engines run voice-granular simultaneously (Evil Pet T5+ AND S-4 Track 1 Mosaic engaged), governance classifies this as *maximum-texture voice processing* and applies:
- Tier budget consumption charged at 1.5× (reflects higher anthropomorphization risk).
- `monetization_opt_ins.dual_granular_simultaneous` required.
- Stimmung=TRANSCENDENT stance required (not reachable through normal stance transitions; requires programme activation).
- Duration ceiling: 60 s per 300 s window (tighter than T5 alone).

### §9.7 **Pre-render WARD classifier gate (NEW, Ring-2 classifier)**

Before any dual-engine tier transition commits to broadcast, the Ring-2 WARD classifier (alpha's #215/#218 work) evaluates the preview (via UC8 monitor-only path) for legibility and consent safety. If WARD rejects, transition aborts; director logs `ward_rejected` and keeps prior state. Implementation: hook into `dynamic_router.commit()` method; pipe preview through classifier; require PASS before commit.

---

## §10. Implementation recommendation

### Phase A — Immediate (S-4 absent; pure software fix)

**A1: Filter-chain drift fix** (ship in a small PR; ~30 LOC).

Edit `config/pipewire/hapax-l12-evilpet-capture.conf`:

- Remove `gain_pc_l` and `gain_pc_r` from the mixer node list.
- Remove their `sum_l:In 6` and `sum_r:In 6` links.
- Remove their AUX10/11 input bindings (change to `null`).

Result: broadcast sum has `gain_evilpet` (AUX5) + `gain_contact` (AUX1, operator-private; fader determines broadcast contribution) + `gain_rode` (AUX4) + `gain_samp` (AUX3) + `gain_handy_l/r` (AUX8/9). PC audio on CH11/12 is **not** directly summed — it reaches broadcast only via Evil Pet hardware return (AUX5). UC1 compliance restored.

**A2: Hardware loop verification** (operator-dependent; 5 min on L-12).

Verify:
- L-12 MONITOR A bus carries CH11/12 at appropriate level (operator's fader + MON-A knob).
- Evil Pet IN has signal from MONITOR A (ear-check or L-12 built-in probe).
- Evil Pet OUT → CH1 XLR; CH1 fader up.
- CH6 input has signal from CH1 (L-12 built-in signal LED).
- L-12 BROADCAST scene on SD card is loaded and has the MONITOR A + CH1 routing preserved.

If any step fails, Evil Pet hardware chain is broken; no software fix restores it.

**A3: Notification-sink isolation** (new PipeWire conf; ~20 LOC).

Create `config/pipewire/hapax-notification-private.conf` — a new sink that replaces the role.notification → hapax-private → Ryzen → L-12 leak. Notifications route to a dedicated sink that is NOT captured by L-12 filter-chain. WirePlumber rule pins it.

**A4: State surface audit** (verify / reinstate writers).

Check that `/dev/shm/hapax-stimmung/current.json` is being written. If not, investigate why stimmung agent is down. Same for voice-tier, programme, ephemeral surfaces. Router can't tick until state is flowing.

**A5: Static S-4 sink producer** (placeholder, before S-4 plugs in; ~30 LOC).

Add a `hapax-yt-loudnorm → hapax-s4-content` loopback so that when the S-4 *is* plugged in, music sources already target it. Until then, this is a no-op (no S-4 USB = sink is silent consumer).

Phase A is a ~100-LOC PR (6 files). Tests: verify filter-chain load, verify notification isolation, verify hapax-yt-loudnorm routing. **Ships before S-4 hardware decision.**

### Phase B — S-4 online (S-4 physically plugged; ~500 LOC across 15 files)

**B1: S-4 USB enumeration + PipeWire sink producer.**

Plug S-4 USB-C; verify `alsa_input.usb-Elektron_Torso_S-4_*` and `alsa_output.usb-Elektron_Torso_S-4_*` appear. Update `hapax-s4-loopback.conf` to target the specific device name. Verify `hapax-s4-content` has a producer (loopback from `hapax-yt-loudnorm`) and `hapax-s4-tap` has a consumer (`hapax-livestream-tap`).

**B2: S-4 MIDI lane.**

Erica Dispatch OUT 2 → S-4 MIDI IN (physical cable). Verify in `aconnect -l` that S-4 MIDI appears as a separate client. Update `shared/s4_midi.py` (new) with scene recall primitives.

**B3: Dynamic router agent (`agents/audio_router/dynamic_router.py`, new).**

5 Hz tick. Reads state surfaces, applies §7.2 policy, emits preset recalls + scene recalls + gain writes. ~200 LOC core, ~200 LOC tests. Systemd user unit. Per §7.6 graceful-degradation.

**B4: S-4 scene library.**

Define and burn (or document) 10 scenes: `VOCAL-COMPANION`, `VOCAL-MOSAIC`, `MUSIC-BED`, `MUSIC-DRONE`, `MEMORY-COMPANION`, `UNDERWATER-COMPANION`, `SONIC-RITUAL`, `BEAT-1`, `RECORD-DRY`, `BYPASS`. Per-scene CC maps documented at `docs/audio/s4-scene-library.md`.

**B5: Dual-engine preset pack extension.**

Add 4 new Evil Pet companion presets to `shared/evil_pet_presets.py` — vocal-companion-subtle (pairs with `VOCAL-COMPANION`), vocal-companion-memory (pairs with `MEMORY-COMPANION`), etc. Preserves dual-engine character coherence.

**B6: UC1..UC10 integration tests.**

Per use case, integration test that (a) initiates the context trigger, (b) verifies correct preset recall on both engines, (c) verifies topology, (d) verifies governance gates. ~10 tests × ~30 LOC each.

### Phase C — Production dynamism (post-Phase-B; ~200 LOC across 5 files)

**C1: Ramp-time responsiveness.**

Implement §7.3 ramp formula in `dynamic_router.py`. Stimmung_velocity computed from 3-tick window. CC-level interpolation.

**C2: Utterance-boundary sticky behavior.**

§7.4 10 s stick + revert. Operator CLI sticky override.

**C3: Observability closure.**

Prometheus counters / gauges per §7.7. Langfuse events. `router.jsonl` rotation.

**C4: Dry-run preview** (UC8).

New `hapax-voice-fx-monitor` sink. CLI `hapax-voice-preview <preset>`. 10-s auto-cutoff.

**C5: WARD classifier pre-render gate.**

Hook §9.7 into `dynamic_router.commit()`.

Phase C is the "quality" phase — the dynamic router works without it, but feels like a simple lookup table. Phase C turns it into a context-aware controller.

---

## §11. Open questions for operator

Questions that block or re-scope the design:

1. **S-4 physical connection preference.** USB-C (lower latency via direct PipeWire) or analog (CH7/8 on L-12, but consumes reserved channels)? Both are defined in the plan; which is the primary path?

2. **Dual-granular policy.** Should voice-tier-5 + Mode D *ever* coexist (using S-4 Mosaic for voice while Evil Pet granular is on vinyl)? This is technically supported by §7.5 R3 re-route, but asks the voice to wear a different granular character than the vinyl. Aesthetic call.

3. **Ramp-time preference.** Aggressive (snappy 0.2 s tier changes, operator hears crisp transitions) or smooth (2.5 s ramps, character drifts)? Probably programme-dependent; prefer defaulting to smooth for broadcast and aggressive for live-performance programmes.

4. **Pre-cue mechanism.** Should UC8 dry-run use S-4 OUT 2 (dedicated analog monitor output) or a separate PipeWire sink routed to L-12 PHONES? Analog is physically instant; PipeWire has software advantages (metering, visual feedback).

5. **MIDI-coupled cross-modulation depth.** Should S-4 LFO → Evil Pet CC modulation (§5.11 D4) be routine-allowed or gated? Routine allows interesting rhythmic effects; gated limits anthropomorphization drift.

6. **Filter-chain mutation strategy.** Can the dynamic router safely do live topology changes (pw-link add/remove), or is a PipeWire restart required for safety? Current assumption: mutation-safe for gain/param writes, restart-safe for link topology. Verify empirically.

7. **Priority order for Phase A rollout.** Should A1 (drift fix) ship immediately as a tiny PR, or bundle with A3 (notification isolation) + A4 (state surface audit) + A5 (static S-4 placeholder) in one larger PR? Tiny PR = faster ship, smaller review surface. Larger PR = fewer coordination overhead. Recommendation: tiny, because A1 alone restores UC1 compliance (the critical fix).

8. **Programme opt-in for dual-granular (§9.6).** New opt-in flag `dual_granular_simultaneous` is proposed. Should it be binary (allow / deny) or graded (allow-with-monitor, allow-with-budget-halved, allow-full)? Graded gives more control but more surface area to test.

9. **S-4 scene definition custody.** Who writes `docs/audio/s4-scene-library.md` — delta (config / spec), or operator (aesthetic-domain authority)? Suggest: delta proposes structure, operator signs off on specific CC values per scene.

10. **D5 serial-fallback-parallel gesture.** Does `hapax-serial-mode on` require double-confirm (prevents accidental transition with elevated feedback risk), or is single-CLI-invocation enough? Current design: double-confirm via CLI prompt OR ntfy quick-action.

---

## §12. Appendix

### A. Current PipeWire node inventory (2026-04-21 verified)

```
Audio/Sink:
  alsa_output.pci-0000_73_00.6.analog-stereo         Ryzen HD Audio
  alsa_output.usb-ZOOM_Corporation_L-12_*.analog-surround-40    L-12
  hapax-livestream                                    OBS content sink
  hapax-livestream-tap                                pre-OBS broadcast tap
  hapax-private                                       loopback → Ryzen
  hapax-s4-content                                    S-4 USB content (dormant, no producer)
  hapax-voice-fx-capture                              TTS input with HPF/EQ/air
  hapax-yt-loudnorm                                   YT bed input (−16 LUFS)
  input.loopback.sink.role.assistant                  daimonion SFX

Audio/Source:
  alsa_input.usb-ZOOM_Corporation_L-12_*.multichannel-input    L-12 14-ch multitrack

Stream/Output/Audio:
  hapax-l12-evilpet-playback                          filter-chain → livestream-tap
  hapax-livestream-playback                           (loopback → Ryzen for L6 ch 5 hardware)
  hapax-private-playback                              hapax-private → Ryzen
  hapax-s4-tap                                        S-4 → livestream-tap (dormant)
  hapax-vinyl-playback                                vinyl (dormant)
  hapax-voice-fx-playback                             voice-fx output → Ryzen
  hapax-yt-loudnorm-playback                          YT loudnorm output → mixer (drifted)
  output.loopback.sink.role.assistant                 daimonion SFX loopback
```

### B. Evil Pet preset pack (13, via `shared.evil_pet_presets.PRESETS`)

- **Voice tiers (T0..T6)**: `hapax-unadorned`, `hapax-radio`, `hapax-broadcast-ghost`, `hapax-memory`, `hapax-underwater`, `hapax-granular-wash`, `hapax-obliterated`.
- **Modes**: `hapax-mode-d` (vinyl DMCA), `hapax-bypass` (governance fallback).
- **Music scenes**: `hapax-sampler-wet`, `hapax-bed-music`, `hapax-drone-loop`, `hapax-s4-companion`.

### C. L-12 BROADCAST scene channel map (from `hapax-l12-evilpet-capture.conf`)

| CH | L-12 label | Role | AUX in capture | Filter-chain stage | Target state |
|----|-----------|------|----------------|---------------------|-----------------|
| 1  | XLR phantom-1-4 | reserve | AUX0 | null | null |
| 2  | Phantom-1-4 | Cortado contact mic | AUX1 | `gain_contact` (1.5) | `gain_contact` |
| 3  | Phantom-1-4 | reserve | AUX2 | null | null |
| 4  | Phantom-1-4 | Sampler | AUX3 | `gain_samp` (2.0) | `gain_samp` |
| 5  | Phantom-5-8 | Rode Wireless | AUX4 | `gain_rode` (2.0) | `gain_rode` |
| 6  | Phantom-5-8 | **Evil Pet return** | AUX5 | `gain_evilpet` (2.0) | `gain_evilpet` |
| 7  | Phantom-5-8 | reserve (S-4 OUT 1 when plugged) | AUX6 | null → `gain_s4_l` (Phase B) | `gain_s4_l` |
| 8  | Phantom-5-8 | reserve (S-4 OUT 2 when plugged) | AUX7 | null → `gain_s4_r` (Phase B) | `gain_s4_r` |
| 9/10 | Stereo | Handytrax vinyl L/R | AUX8/9 | `gain_handy_l/r` (4.0) | retain |
| 11/12 | Stereo | **PC line L/R** | AUX10/11 | **`gain_pc_l/r` (1.0) — DRIFT** | `null` (remove) |
| 13/14 | Master L/R | (dropped) | AUX12/13 | null | null |

### D. Gap checklist vs prior research (2026-04-20)

| Topic | Prior | This doc | Status |
|-------|-------|----------|--------|
| Hardware affordances | §2 | §2 | Identical |
| Source inventory | §3 (8 sources) | §3 (8 sources, revised for current config) | Updated |
| Destination inventory | §4 | §4 | Updated (L-12-specific) |
| Static topology classes (§§5.1–5.7) | yes | §5 cites | Preserved |
| Dual-engine topology classes (D1..D5) | — | §§5.8–5.12 | **NEW** |
| Use-case catalog | 10 UCs (static) | §6 (10 UCs, dynamic) | **Rewritten** |
| Constraint summary | §7 | §9 | Preserved + extended |
| Control surface taxonomy | §8 | §§7, 8 | **Restructured** |
| Governance | §9 | §9 | Preserved + extended (§9.6, §9.7) |
| Top-3 recommendation | §10 | §1 TR1-3 | **Rewritten** for dual-engine |
| Open questions | §11 | §11 | Updated |
| Control-law layer | — | §7 | **NEW (the core gap filled)** |
| Dynamic switching mechanisms | scattered | §8 | **Consolidated** |

### E. Deltas from 2026-04-20 research

**Structural additions:**
- §5.8–§5.12: five new dual-engine topology classes (D1..D5).
- §7: full control-law specification — state vars, policy layers, arbitration, latency, observability, escape hatches.
- §8: dynamic switching mechanism primitives (consolidated).
- §9.6: dual-engine-anthropomorphization governance extension.
- §9.7: WARD classifier pre-render gate (new).

**Replaced/rewritten:**
- §6 use-case catalog: every UC rewritten to specify context triggers + dual-engine presets, not just topology.
- §1 Top-3 recommendations: D1 dual-parallel voice, D2 complementary split, dynamic router agent.
- §10 implementation plan: 3 phases (A: software-only; B: S-4 online; C: production dynamism).

**Preserved:**
- Source/destination inventories (§§3–4) — structure preserved, content updated for L-12.
- Static topology classes (§§5.1–5.7) — unchanged.
- Mode D mutex and intelligibility budget (§9.1, §9.4) — unchanged.
- HARDM anti-anthropomorphization (§9.2) — unchanged.

---

## Sources

- Operator directive (2026-04-21 session): "Re-run the entire research investigation ... Make maximal and dynamic use of both s-4 and evil pet."
- Evil Pet MIDI spec: midi.guide Evil Pet page.
- Torso S-4 manual + `alsa_output.usb-Elektron_Torso_S-4_*` device naming.
- ZOOM L-12 v5 manual + `alsa_input.usb-ZOOM_Corporation_L-12_*.multichannel-input` 14-channel exposition.
- Prior research: `docs/research/2026-04-20-evilpet-s4-routing-permutations-research.md` and 9 cross-refs enumerated in frontmatter.
- Live audit 2026-04-21 04:15–04:30 UTC: `pw-dump`, `arecord -l`, `lsusb`, `aconnect -l`, `amidi -l`, `pw-link -l`, config files under `~/.config/pipewire/pipewire.conf.d/`.

Permutation space: 12 topology classes (7 prior + 5 new) × 10 use-cases × 4 switching mechanisms × 8 state variables ≈ 3,840 distinct operational configurations, arbitrated by the control-law layer in §7 at runtime.

---

**Next action**: operator review. Open questions in §11 block or re-scope Phase A/B/C. Phase A1 (filter-chain drift fix) is independent of all open questions and can ship immediately as a ~30-line PR.
