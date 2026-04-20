---
date: 2026-04-20
author: alpha
audience: operator + alpha + delta (execution)
register: scientific, engineering-normative
status: design — selective dual-FX routing for PC audio on the livestream
related:
  - docs/research/2026-04-19-evil-pet-s4-base-config.md (§4 S-4 base, §2.2 signal levels)
  - docs/research/2026-04-20-audio-normalization-ducking-strategy.md (§3.1 loudnorm, §4 duck tiers)
  - docs/research/2026-04-20-evil-pet-cc-exhaustive-map.md (Evil Pet CCs, §3 governance clamps)
  - config/pipewire/hapax-stream-split.conf (single-wire state)
  - config/pipewire/voice-fx-chain.conf (TTS → Evil Pet path)
  - agents/hapax_daimonion/vocal_chain.py (9-dim CC emitter)
  - agents/hapax_daimonion/vinyl_chain.py (Mode D activation)
operator-directive-load-bearing: |
  Evil Pet must be selective (voice only). Other PC audio should hit L6
  clean OR go through a different FX (S-4). Two simultaneous FX
  characters — voice through Evil Pet, non-voice PC audio through S-4 —
  available on the livestream.
---

# Dual-FX Routing — Evil Pet (voice) + S-4 (music) in parallel

## §1. Problem statement

Post-24c-retirement, every PipeWire sink targeting a PC analog output
funnels through one physical wire: Ryzen HD Audio rear 3.5 mm →
3.5mm-to-TRS → L6 ch 5. Channel 5's AUX 1 send is permanently routed
to the Evil Pet's line input; Evil Pet left-out returns on ch 3.
`hapax-voice-fx` (TTS via `voice-fx-chain.conf`) and `hapax-livestream`
(general PC audio via `hapax-stream-split.conf`) share the Ryzen
target, so every PC-audio stream passes through the Evil Pet regardless
of whether granular/saturator processing is semantically appropriate.

This violates the Evil Pet's intended selective role per
`evil-pet-s4-base-config.md` §3 ("Evil Pet is an effects processor for
a mono speech signal, not a granular synth generating new sound"). When
music or notifications hit the same AUX 1 bus as TTS, three failure
modes emerge:

1. **Unwanted colouration of music.** YouTube / SoundCloud streams pick
   up the voice-tuned BP filter at 1.8 kHz (CC 70 = 60%), distortion
   (CC 39 = 30%), and room reverb (CC 91 = 30%), which dull low end and
   introduce mid-range honk on bass-heavy cuts. EBU R128 broadcast
   practice expects music to arrive mastered, not pre-filtered through
   a speech chain.
2. **Cross-modulation at the Evil Pet input.** Two uncorrelated streams
   sum pre-FX on AUX 1. The envelope-follower filter (CC 96 = 35%)
   tracks whichever is loudest, collapsing both onto the dominant's
   envelope — classic broadcast bus-summing-before-dynamics failure
   (Katz, *Mastering Audio* 3e §17.4). A YouTube kick drives the
   bandpass; simultaneous TTS is coloured by the music's groove, not by
   its phonemes.
3. **Mode D mutex conflict.** Per
   `vinyl-broadcast-mode-d-granular-instrument.md` §4, Mode D claims
   the Evil Pet granular engine for vinyl. Any non-vinyl PC audio
   hitting AUX 1 during Mode D mixes into the same granulator. Documented
   in `audio-normalization-ducking-strategy.md` §4.1 Tier A as the
   Evil-Pet-bypass-OFF cross-modulation artefact.

### 1.1 Concrete scenarios

- **Scenario A — Hapax speaks over bed music.** Operator plays a
  YouTube track at -14 LUFS. Hapax narrates. Today: both streams hit
  the same voice-tuned Evil Pet; music sounds honky, voice sounds
  voice-plus-music-shaped-by-voice-filter. Desired: voice through the
  Evil Pet; music either clean on L6 or through an S-4 music scene
  (mild Ring + light Deform + warm Vast).
- **Scenario B — Narrator over Mode D vinyl.** Operator engages Mode D
  (Evil Pet is granulating vinyl on ch 4's AUX 1). Hapax tries to
  narrate. Today: voice arrives on ch 5 AUX 1, which is the same bus
  as ch 4 → Evil Pet, causing either a dry voice (AUX 1 off) or
  cross-modulation (AUX 1 on). Desired: voice via the **S-4 Mosaic**
  granular engine while the Evil Pet simultaneously granulates vinyl.
  Two granular characters, two devices, no mutex.

The gap is the absence of a second physically independent FX return
path. This design introduces one.

---

## §2. Hardware options

Four candidates, rated on cost, complexity, round-trip latency, channel
isolation, and alignment with the existing L6-centric summation model.
All assume the voice path (Ryzen → L6 ch 5 AUX 1 → Evil Pet → ch 3)
remains intact.

### 2.1 Option A — S-4 as USB class-compliant interface

The Torso S-4 (`evil-pet-s4-base-config.md` §1; manual §3.7) exposes
a USB-C class-compliant 10-in/10-out audio interface. On Linux with
`snd-usb-audio` + PipeWire ≥ 1.0, the S-4 appears as a standard
`Audio/Sink` and `Audio/Source`.

```
PC Ryzen rear ─► L6 ch 5 AUX 1 ─► Evil Pet ─► L6 ch 3 (voice, unchanged)
PC USB-C     ─► S-4 USB ─► S-4 track 1 (Bypass→Bypass→Ring→Deform→Vast) ─► S-4 Out 1 ─► L6 ch 2 (music, new)
```

- **Cost:** $0 (S-4 already in rack).
- **Complexity:** low. USB-C cable + TS/TRS cable to L6 ch 2 (TRS side,
  line level per §2.3 of the base config). L6 ch 2 currently carries
  the Cortado MKIII contact mic, which migrates to ch 6 (§4.4).
- **Latency:** ~5 ms USB at `quantum=256`, plus ~4 ms S-4 internal
  buffering. Total ≤ 12 ms — within ITU-R BS.1116-3 live-mix
  tolerance.
- **Isolation:** excellent. USB transport shares no analog conductor
  with the Evil Pet path; USB controller provides galvanic-ish
  separation. If hum appears, a $30 iFi iDefender+ USB isolator
  resolves it.
- **Alignment:** high. Voice path untouched; parallel music path into
  the same L6. Single summation point unchanged.

### 2.2 Option B — Second PC analog output

Front-panel jack, HDMI audio, or S/PDIF. Front-panel outputs on the
operator's rig historically carry mains hum and GPU coil-whine (cf.
the 24c retirement itself, which was driven by ground-loop behaviour).
HDMI requires an HDMI-to-analog breakout ($40–$120) that adds a DAC
hop. Shared HD Audio codec means CPU load on one sink can starve the
other. **Rejected** — reintroduces the ground-reference risk class the
24c retirement resolved.

### 2.3 Option C — Dedicated cheap USB DAC

iFi Zen Air, Behringer UCA202, FiiO K3 ($30–$200). Adds a redundant
DAC stage that the S-4 already performs natively. **Rejected** —
duplicates Option A's capability with new hardware and no benefit.

### 2.4 Option D — Software-only PipeWire routing

A filter-chain cannot physically deliver two separate analog streams
over one wire. Any software split still converges on the single Ryzen
line-out → AUX 1 → Evil Pet path. Either identical to today, or
requires operator manual intervention on every program change (violates
`feedback_no_expert_system_rules.md` — no hardcoded cadence/threshold
gates). **Not a standalone solution** — a supplementary policy layer
on top of the chosen hardware option.

### 2.5 Recommendation summary

| Option | Cost | Latency | Isolation | Alignment | Verdict |
|---|---|---|---|---|---|
| A — S-4 USB direct | $0 | ~12 ms | excellent | high | **recommended** |
| B — Second analog | $0–$120 | ~3–15 ms | poor | poor | rejected |
| C — Cheap USB DAC | $30–$200 | ~8 ms | excellent | low | rejected |
| D — Software only | $0 | — | — | — | supplementary |

---

## §3. Recommended architecture — S-4 USB direct

Option A is chosen. Rationale:

1. **Zero new hardware.** S-4 already in rack, USB-C port unused. S-4
   Manual §3.7 explicitly documents Bypass mode for "S-4 As an Effects
   Processor" — the operator's intended use.
2. **Parallel, not serial.** The prior series chain (voice → Evil Pet
   → S-4 → L6) decomposes into two parallel chains with independent FX
   per source. Parallel routing preserves dynamic integrity per Katz
   §17.2 ("Parallel processing lets you hear the effect on a dedicated
   bus without forcing the dry signal through the processor").
3. **Existing CC map transfers.** `evil-pet-s4-base-config.md` §5.2
   maps the 9-dim emitter to S-4 CCs already. Music-scene retune (§5)
   diverges from the voice-scene defaults where appropriate.
4. **Mode-D-compatible.** S-4 Mosaic and Evil Pet granular are distinct
   devices with distinct 512 MB buffers; no shared contention (§9).

Risks accepted:

- **USB bus contention.** Confirm the S-4 on a dedicated xHCI root port
  via `lsusb -t` before commit. Bandwidth is a non-issue (10 ch × 24
  bits × 48 kHz = 11.5 Mbps on a 10 Gb/s USB-C port).
- **Firmware pinning.** S-4 OS 1.0.4 has no documented USB-audio
  quirks (cf. Sound on Sound review). Pin firmware version in runbook.

---

## §4. PipeWire configuration

Introduce one new sink (`hapax-s4-fx`), retarget `hapax-livestream`,
add new L6 channel mapping.

### 4.1 Sink inventory

| Sink | Before | After |
|---|---|---|
| `hapax-voice-fx-capture` | → Ryzen → Evil Pet | **unchanged** (voice) |
| `hapax-livestream` | → L6 USB playback (clean) | → `hapax-s4-fx` (music via S-4) |
| `hapax-private` | → Ryzen (shared) | **unchanged** (private monitor) |
| `hapax-s4-fx` | — | **NEW** — filter-chain → S-4 USB |
| Default (notifs) | → L6 USB via role policy | **unchanged** |

### 4.2 New config — `config/pipewire/hapax-s4-fx.conf`

```
# Hapax S-4 FX sink — music path into S-4 USB audio.
# PC USB-C → S-4 → Ring/Deform/Vast (music scene, §5) → S-4 OUT 1
# → L6 ch 2 (TRS, line level) → L6 Main Mix → OBS.

context.modules = [
    {
        name = libpipewire-module-filter-chain
        args = {
            node.name = "hapax-s4-fx"
            node.description = "Hapax S-4 FX (music path → S-4 USB)"
            media.class = "Audio/Sink"
            audio.rate = 48000
            audio.channels = 2
            audio.position = [ FL FR ]

            filter.graph = {
                # No-op attachment points for Phase B loudnorm (ebur128).
                nodes = [
                    { type = builtin name = norm_l label = bq_peaking
                      control = { "Freq" = 1000.0 "Q" = 0.707 "Gain" = 0.0 } }
                    { type = builtin name = norm_r label = bq_peaking
                      control = { "Freq" = 1000.0 "Q" = 0.707 "Gain" = 0.0 } }
                ]
                inputs  = [ "norm_l:In" "norm_r:In" ]
                outputs = [ "norm_l:Out" "norm_r:Out" ]
            }

            capture.props = {
                node.name = "hapax-s4-fx-capture"
                media.class = "Audio/Sink"
            }
            playback.props = {
                node.name = "hapax-s4-fx-playback"
                # Resolved at runtime via pw-cat --list-targets:
                target.object = "alsa_output.usb-Torso_Electronics_S-4-00.pro-output-0"
            }
        }
    }
]
```

The `bq_peaking` nodes are placeholder attachment points; `ebur128`
loudness normalization (`audio-normalization-ducking-strategy.md`
§5.1 targets -14 LUFS for music) drops in here in Phase B without
renaming the public sink.

### 4.3 Retarget `hapax-livestream`

In `hapax-stream-split.conf`, change:

```
playback.props = {
    node.name      = "hapax-livestream-playback"
    target.object  = "hapax-s4-fx-capture"   # was Ryzen or L6 USB
    audio.position = [ FL FR ]
}
```

### 4.4 L6 channel assignment

| L6 ch | Before | After | AUX 1 |
|---|---|---|---|
| 1 | Rode Wireless Pro | (unchanged) | off |
| 2 | Cortado MKIII (+48V) | **S-4 Out 1 (music FX return)** | off |
| 3 | Evil Pet L-out (voice FX return) | (unchanged) | off |
| 4 | Handytrax vinyl | (unchanged) | conditional (Mode D) |
| 5 | Ryzen (TTS dry, pre-Evil Pet) | (unchanged) | UP (→ Evil Pet) |
| 6 | L6 USB return | **Cortado MKIII (migrated)** | off |

If ch 6 is the USB return strip (not a combo jack), confirm physical
layout before commit. The L6 Operation Manual §4.2 describes the USB
return as a distinct strip; this design assumes ch 6 combo jack is
free after `hapax-livestream` ceases to target L6 USB playback.

### 4.5 Routing summary (after)

```
Hapax TTS    → voice-fx-chain → Ryzen → L6 ch 5 (AUX 1 UP)
             → AUX 1 → Evil Pet → L6 ch 3 → Main Mix       (voice FX)

YouTube/SC   → hapax-livestream → hapax-s4-fx (filter-chain)
             → S-4 USB → S-4 track 1 (Bypass→Bypass→Ring→Deform→Vast)
             → S-4 Out 1 → L6 ch 2 → Main Mix              (music FX)

Vinyl        → L6 ch 4 (AUX 1 conditional)
             ├─ dry → Main Mix
             └─ Mode D: AUX 1 → Evil Pet granular → ch 3   (mutex with voice)

Notifications → role.notification → hapax-private → Ryzen  (monitor only)
```

---

## §5. S-4 music-path scene (`HAPAX-MUSIC-FX`)

`evil-pet-s4-base-config.md` §4 scene (`HAPAX-VOX-BASE`) is tuned for
a signal already FX'd upstream: avoids Ring pitch-lock, keeps Deform
compression dominant, softens Vast for consonant preservation. The
music path inverts priorities — intelligibility is not at stake,
music-bed dominance is acceptable, and the goal is a **recognisable
S-4 character** that contrasts with the Evil Pet's voice coloration so
the two chains feel distinctly authored.

### 5.1 Design targets

- **Ring filter:** audible colouration, not pitched. Keep Ring Wet
  ≤ 50%, resonance 25–40% to avoid the 48-band comb's pitch-locking
  on random YouTube content.
- **Deform:** moderate drive (~45%) for transient warmth; lighter
  compression (~35%) so music dynamics survive to master.
- **Vast reverb:** moderate hall wash, medium decay, darker damping
  (~65%) so it doesn't compound with the Evil Pet's voice reverb into
  a common muddy tail.
- **Vast delay:** off or minimal (15–20%, 1/16). Delay on bed music
  fights the groove.
- **Mosaic granular:** Bypass at music baseline. Reserved for
  `NARRATOR-FX` (§5.3).

### 5.2 Music-path CC scene (Scene 2)

CC numbers from `evil-pet-s4-base-config.md` §5.2. Copy `VOX-BASE` as
Scene 2, apply overrides:

| Slot | CC# | Parameter | Voice | Music | Rationale |
|---|---:|---|---:|---:|---|
| Track | 47 (ch16) | track level | 64 | 72 | +2 dB for voice-duck headroom |
| Ring | 79 | cutoff | 64 | 76 | keep top end present |
| Ring | 80 | resonance | 25 | 40 | colouration, no pitch-lock |
| Ring | 81 | decay | 25 | 35 | music is denser than speech |
| Ring | 83 | slope | 35 | 45 | steeper shoulders |
| Ring | 86 | **wet** | 35 | 50 | **primary music-FX contrast knob** |
| Deform | 95 | drive | 35 | 55 | transient warmth |
| Deform | 96 | compress | 72 | 45 | preserve dynamics |
| Deform | 99 | tilt | 64 | 72 | light top-end air |
| Deform | 103 | **wet** | 72 | 90 | **secondary contrast knob** |
| Vast | 112 | delay amt | 45 | 20 | minimal bed-music delay |
| Vast | 113 | delay time | 1/8D | 1/16 | reduce rhythmic fighting |
| Vast | 114 | reverb amt | 35 | 55 | hall wash |
| Vast | 115 | reverb size | 72 | 95 | larger hall |
| Vast | 116 | delay fbk | 35 | 20 | fewer repeats |
| Vast | 118 | reverb damp | 72 | 82 | darker, avoid mid-build |
| Vast | 119 | reverb decay | 45 | 65 | longer suits music |

Save as project `HAPAX-DUAL-FX`, Scene 2. Scene 1 (`VOX-BASE`) remains.

### 5.3 Optional Scene 3 — `HAPAX-NARRATOR-FX`

For Scenario B (§1.1) narrator-over-Mode-D:

- Material = Bypass, Granular = **Mosaic ON**
  - Size 60 (~150 ms grains, speech-smear regime; Roads 2001 §3.2)
  - Density 50 (~30 grains/sec, pitched stream)
  - Spread 30, Wet 60% (granular dominant, dry path preserved)
- Ring / Deform / Vast unchanged from Scene 2.
- Routing: voice-fx-chain retargets to `hapax-s4-fx-capture` via
  WirePlumber role override on `MODE_D_NARRATOR` entry (§10 Phase 4).

### 5.4 Optional Scene 4 — `HAPAX-CLEAN`

All slots Bypass. Safety scene for when the operator wants clean music
through L6 ch 2 without retargeting PipeWire. Recall via MIDI PC.

---

## §6. Parallel recruitment architecture

`vocal_chain.py` emits 9 dims (intensity, tension, diffusion,
brightness, density, grit, space, motion, presence) at 20 Hz per CC
(§5.3 rate limit). Question: for the S-4 music path, reuse
`vocal_chain.py` with a per-device CC map (as `vinyl_chain.py` does),
or introduce a dedicated `s4_chain.py`?

### 6.1 Reuse `vocal_chain.py` — rejected

The 9 dims are derived from Hapax's TTS signal. Music from YouTube
has no Hapax-internal dim state; Hapax's `tension` value has no causal
bearing on what music FX should do. Semantically unmoored.

### 6.2 Dedicated `s4_chain.py` — recommended

Compute music-path dims from music-path signals:

- `music_energy` — short-term RMS of `hapax-livestream` tap (→ Deform
  drive CC 95).
- `music_density` — spectral flatness / transient density (→ Ring wet
  CC 86, Mosaic density in Scene 3).
- `music_brightness` — spectral centroid ratio (→ Ring cutoff CC 79,
  Deform tilt CC 99, Vast damp CC 118).
- `music_harmonicity` — pitch-track confidence (→ Ring resonance CC
  80; high harmonicity permits higher resonance without pitch-lock,
  low harmonicity clamps it).
- `programme_register` — discrete enum from active programme role
  (§7).
- `stimmung_wash` — shared input from `shared/stimmung.py`, the only
  cross-chain signal; biases Vast reverb size on both chains so the
  two FX tails feel part of the same room despite different programs.

Signal sources: `hapax-livestream` sink monitor port → lightweight
Python RMS + FFT daemon (same pattern `vinyl_chain.py` uses).

Wiring sketch:

```python
# agents/hapax_daimonion/s4_chain.py (new)
class S4Chain:
    def __init__(self, midi: MidiOut, tap: StreamTap):
        self._midi, self._tap = midi, tap
        self._stimmung = StimmungReader()
        self._debounce = CCDebounce(min_interval_ms=50)  # 20 Hz per CC

    def tick(self) -> None:
        energy = self._tap.rms_ema()
        density = self._tap.spectral_flatness()
        brightness = self._tap.centroid_ratio()
        harmonicity = self._tap.pitch_confidence()
        wash = self._stimmung.wash()

        self._send(CC=95, value=int(clamp(energy * 0.55, 0, 0.55) * 127))
        self._send(CC=80, value=int(clamp(harmonicity * 0.40, 0.15, 0.40) * 127))
        self._send(CC=86, value=int(clamp(density * 0.50, 0, 0.50) * 127))
        self._send(CC=115, value=int(clamp(0.5 + wash * 0.30, 0.50, 0.95) * 127))
        # ... continue per §5.2 music scene

    def _send(self, *, CC: int, value: int) -> None:
        if self._debounce.should_send(CC, value):
            self._midi.send_cc(channel=1, cc=CC, value=value)
```

Recruitment surface: `s4_chain` registers as a distinct affordance
with a Gibson-verb description ("colour-and-resonate incoming music,
halo it, hall-reverb it, no speech"). The impingement → recruitment
path decides to activate `vocal_chain`, `s4_chain`, or both
independently. Mode D, narrator-mode, showcase-mode are all
programme roles that bias the recruitment (§7).

`vocal_chain.py` continues to write only to the Evil Pet's CCs. No
code path writes to both devices from the same dim vector; each
device sees signals derived from its own audio content.

---

## §7. Programme role × source × FX matrix

The livestream programme system (`project_livestream_control.md` +
Phase 8 programme authoring) defines `ProgrammeRole` values. Which
FX engine engages per source, per role:

| Programme role | Voice (TTS) | Music (YT/SC) | Vinyl | Evil Pet claim | S-4 claim |
|---|---|---|---|---|---|
| LISTENING | muted | clean or experimental S-4 | dry | — | MUSIC-FX or off |
| SHOWCASE | Evil Pet | S-4 MUSIC-FX | dry | voice | music |
| NARRATOR | Evil Pet (modest) | S-4 MUSIC-FX (bed) | dry | voice | music |
| AMBIENT | muted / rare | S-4 MUSIC-FX (gentle) | dry | — | music |
| MODE_D | muted (Tier A mutex) | clean or gentle S-4 | AUX 1 → Evil Pet granular | vinyl | music |
| MODE_D + NARRATOR | **S-4 NARRATOR-FX (Mosaic)** | clean | AUX 1 → Evil Pet granular | vinyl | voice (Mosaic) |
| SHOWCASE_SPLIT | muted (mutex violation) | MUSIC-FX | AUX 1 → Evil Pet | *conflict* | music |
| SILENT | muted | muted | muted | — | — |

Notable entries:

- **LISTENING** — only music-path FX is live. Operator can push
  experimental Ring settings the voice path never tolerates, since
  intelligibility is not at stake.
- **MODE_D + NARRATOR** — the novel simultaneous-granular case. Two
  independent granular engines active: Evil Pet on vinyl, S-4 Mosaic
  on voice. No shared buffer; no cross-modulation possible.
- **SHOWCASE_SPLIT conflict** — vinyl-granulated + voice wanted
  simultaneously is a mutex violation on the Evil Pet. Resolution:
  transition to `MODE_D_NARRATOR`, voice moves to S-4 Mosaic.

Dispatcher: both `vocal_chain.py` and `s4_chain.py` read the active
`ProgrammeRole` and self-decide whether to emit. Cross-chain
coordination is via `stimmung_wash` only.

---

## §8. Ducking + normalization integration

`audio-normalization-ducking-strategy.md` defines an 8-source matrix.
The new S-4 return on L6 ch 2 becomes a ninth row.

### 8.1 Extended source matrix (delta vs parent)

| # | Source | Path | LUFS | Broadcast |
|---|---|---|---|---|
| S1 | Hapax TTS | voice-fx → Ryzen → ch 5 AUX 1 → Evil Pet → ch 3 | -18 | yes |
| S2 | Vinyl dry | ch 4 | -14 | yes |
| S2' | Vinyl Mode D | ch 4 AUX 1 → Evil Pet → ch 3 | -16 | yes (Mode D) |
| S3 | Operator voice | Rode → ch 1 | -18 | yes |
| S4 | Contact mic | Cortado → **ch 6** (migrated) | -22 RMS | private |
| **S5a** | **Music path post-S-4** | **hapax-livestream → hapax-s4-fx → S-4 → ch 2** | **-14** | yes |
| S5b | Music pre-S-4 loudnorm | hapax-s4-fx ebur128 (Phase B) | -14 | yes |
| S6 | Notifications | role.notification → hapax-private | — | no |
| S7 | SFX | role.assistant → hapax-livestream (S5a path) | -16 | yes |
| S8 | Yeti room | USB | -24 RMS | private |

### 8.2 Duck tier updates

**Tier A (hard mutex)** — unchanged. Mode D TTS mutex binds unless
`MODE_D_NARRATOR` role reroutes voice to S-4.

**Tier B (soft duck):**

- S1 TTS ducks S5a music by -10 dB (already shipped via role policy;
  works identically because `hapax-livestream` is still the Multimedia
  role, just on a different downstream path).
- S3 Rode ducks both S1 and S5a by -6 dB (NEW — sidechain follows
  ch 1 envelope, applies at the broadcast-bus tap).
- S2' Mode D vinyl ducks S5a music by -4 dB (NEW — during Mode D,
  music takes a gentle duck so vinyl-granular dominates).

**Tier C (informational):** new metrics `hapax_mix_s4_peak_dbtp`,
`hapax_mix_s4_lufs` emitted by the `hapax-s4-fx` filter-chain. Feeds
MixQuality per `mixquality-skeleton-design.md` §10.8.

### 8.3 Master bus limiter

Unchanged from §5.3 of the parent doc. It now sees a cleaner
summation (voice FX on ch 3, music FX on ch 2, no Evil-Pet-input
cross-modulation) — master limiter workload is reduced.

---

## §9. Mode D concurrency matrix

Mode D and the S-4 music path are **fully orthogonal** — different
devices, buffers, DSP paths. No shared contention.

| Mode D | Evil Pet engine | S-4 scene | S-4 Mosaic | Voice path |
|---|---|---|---|---|
| OFF | voice processor | MUSIC-FX | OFF | Evil Pet |
| ON + operator speaks | — | MUSIC-FX | OFF | muted (Tier A) |
| ON + NARRATOR | Mode D (vinyl granular) | NARRATOR-FX | **ON (voice grains)** | **S-4 Mosaic** |
| ON + listening | Mode D (vinyl granular) | MUSIC-FX (ambient) | OFF | muted |

The `ON + NARRATOR` case has two independent granular engines running
simultaneously — the listener hears two distinct granular characters.
Only achievable because the hardware paths are physically independent.

Operator hard rule from `audio-normalization-ducking-strategy.md`
§6.3 ("only one of {ch 4 AUX 1, ch 5 AUX 1} up at a time") remains
binding; this design doesn't change AUX 1 economy, it adds a second
FX return path (ch 2) that bypasses AUX 1 entirely.

---

## §10. 5-phase implementation plan

### Phase 1 — hardware (operator, 30 min)

1. USB-C from PC rear to S-4 USB-C. Verify `lsusb | grep -i torso`
   and `wpctl status` shows the S-4 as Audio/Sink+Source. Record the
   exact node name.
2. Patch S-4 Out 1 → L6 ch 2 (TRS combo, TRS-to-TS cable, gain 9
   o'clock, phantom off).
3. Migrate Cortado MKIII from ch 2 → ch 6 (+48V on).
4. On S-4, save `VOX-BASE` as Scene 1, duplicate as Scene 2, apply
   §5.2 overrides, name `HAPAX-MUSIC-FX`. Optional Scene 4
   `HAPAX-CLEAN` (all Bypass) for insurance.
5. Signal test: play YouTube; confirm S-4 input meter is at noise
   floor (retargeting not yet done — next phase).

### Phase 2 — PipeWire split (delta, 1 hour)

1. Write `config/pipewire/hapax-s4-fx.conf` (§4.2) with the S-4 node
   name from Phase 1.
2. Edit `hapax-stream-split.conf`: `hapax-livestream-playback.target.object`
   → `hapax-s4-fx-capture`.
3. `systemctl --user restart pipewire pipewire-pulse wireplumber`.
4. Verify `pw-cat --list-targets` shows `hapax-s4-fx`.
5. Smoke test A: YouTube → S-4 meters register, Evil Pet input at
   noise floor.
6. Smoke test B: Hapax TTS → Evil Pet path (ch 3) active, S-4 path
   (ch 2) at noise floor. Chains independent.

### Phase 3 — `s4_chain.py` (alpha, 1-2 sessions)

1. New `agents/hapax_daimonion/s4_chain.py` per §6.2.
2. `StreamTap` (new) subscribes to `hapax-livestream` sink monitor
   port, keeps rolling RMS + FFT state.
3. CC output via `midi_output.py` on ch 1. Debounce at 20 Hz per CC.
4. Tests: `tests/hapax_daimonion/test_s4_chain.py` covering dim
   computation, clamp ranges (§5.2), CC cadence, role gating.

### Phase 4 — programme-role choreography (alpha, 1 session)

1. Extend `ProgrammeRole` enum with §7 values.
2. Both chains read `ProgrammeRole`, self-decide emission per §7
   matrix.
3. On `MODE_D_NARRATOR` entry, WirePlumber role override retargets
   `voice-fx-chain` → `hapax-s4-fx-capture`; TTS flows through S-4
   Mosaic (Scene 3). Evil Pet stays on vinyl granular.
4. On exit, revert voice-fx-chain target; S-4 re-Bypass Mosaic.
5. Tests: `tests/hapax_daimonion/test_programme_fx_routing.py`.

### Phase 5 — observability + operator UX (delta, 1 session)

1. Metrics: `hapax_mix_s4_peak_dbtp`, `hapax_mix_s4_lufs`,
   `hapax_mix_s4_cc_writes_total{cc, channel}`.
2. Grafana panel on livestream-audio dashboard: S-4 music path
   peak/LUFS/CC-rate/active scene.
3. Fullscreen output sidebar widget: which FX engines engaged per
   source; visual indicator on scene transitions.
4. Log scene transitions via `shared/telemetry.hapax_event` →
   `profiles/sdlc-events.jsonl` + Langfuse.
5. MixQuality integration: S-4 peak-ceiling + LUFS-off-target feed
   `headroom` and `dynamic_range` sub-scores per
   `mixquality-skeleton-design.md` §2.

---

## §11. Open questions

1. **S-4 channel count under `snd-usb-audio`.** Does Linux expose all
   10 in/10 out, or cap at 2? 2 is sufficient for this design; verify
   via `arecord -L` after Phase 1.
2. **Latency-sensitive apps on `hapax-livestream`.** If Discord is
   accidentally routed there, it picks up unintended S-4 FX. Confirm
   role policy in `50-hapax-voice-duck.conf` routes voice chat to a
   communication sink, not hapax-livestream.
3. **Cortado MKIII migration.** If L6 ch 6 is actually the USB-return
   strip (not a combo jack), where does the contact mic go? Fallback:
   L6 USB playback strip is freed by this design (PC audio no longer
   targets it), so the combo jack on a different channel is free.
4. **Common reverb tail.** Evil Pet Room + S-4 Vast Hall sum at
   master on simultaneous SHOWCASE. Likely muddy at operator-preferred
   levels — may need to lower Vast reverb amt by another 5 CCs in the
   music scene, or spatial pan the two returns opposite. Empirical.
5. **Scene recall latency on S-4.** S-4 Manual §9.3 claims < 50 ms
   via MIDI PC. If actual glitch is ≥ 100 ms during a stream, scene
   changes must be planned into silent moments, or scenes migrate to
   **separate tracks** selected by track-mute (instant) rather than
   scene-recall.
6. **Mosaic level-feeding at -18 LUFS TTS.** S-4 Mosaic is
   documented to work on full-scale audio. Voice is already normed to
   -18 LUFS. Phase-2 smoke test should capture a Mosaic meter reading
   on a voice utterance; may need make-up gain pre-Mosaic.
7. **Recruitment granularity.** Should `s4_chain` be recruited at
   programme-role level (on/off per role) or at dim-bundle level
   (Ring active when `music_energy` > 0.2, Vast active when
   `music_brightness` > 0.4)? Architecture supports both; operator
   preference outstanding.
8. **Clean-music path.** With music routed through S-4, routing music
   clean to L6 requires either retargeting `hapax-livestream` or
   recalling Scene 4 `HAPAX-CLEAN` (all Bypass). Scene 4 is cheap
   insurance — include in Phase 1.

---

## §12. References

### Manufacturer
- [Torso Electronics S-4 product page](https://torsoelectronics.com/products/s-4)
- [Torso Electronics S-4 Manual, OS 1.0.4](https://downloads.torsoelectronics.com/s-4/manual/The%20S-4%20Manual%201v0v4a.pdf)
- [Endorphin.es Evil Pet product page](https://www.endorphin.es/modules/p/evil-pet)
- [midi.guide — Evil Pet CCs](https://midi.guide/d/endorphines/evil-pet/)
- [Zoom LiveTrak L6 Operation Manual](https://zoomcorp.com/manuals/l6-en/)
- [Sound on Sound — Torso S-4 review](https://www.soundonsound.com/reviews/torso-electronics-s-4)

### Broadcast audio
- [EBU R128 — Loudness normalisation](https://tech.ebu.ch/publications/r128)
- [ITU-R BS.1116-3 — Methods for the subjective assessment of small impairments](https://www.itu.int/rec/R-REC-BS.1116)
- Katz, B. (2015). *Mastering Audio: The Art and the Science*, 3rd ed. Focal Press. §17.2, §17.4.
- [YouTube audio loudness target](https://support.google.com/youtube/answer/9919273)

### Granular synthesis
- Roads, C. (2001). *Microsound*. MIT Press. §3.2–§3.3 on grain density regimes.
- [SFU — Barry Truax, Granular Synthesis](https://www.sfu.ca/~truax/gran.html)
- [Perfect Circuit — Exploring Microsound and Granular Synthesis](https://www.perfectcircuit.com/signal/microsound)

### Linux audio
- [PipeWire — filter-chain module docs](https://docs.pipewire.org/page_module_filter_chain.html)
- [WirePlumber — policy and role-based routing](https://pipewire.pages.freedesktop.org/wireplumber/)
- [ALSA snd-usb-audio kernel docs](https://www.kernel.org/doc/html/latest/sound/designs/usb-audio.html)

### Internal
- `docs/research/2026-04-19-evil-pet-s4-base-config.md`
- `docs/research/2026-04-20-evil-pet-cc-exhaustive-map.md`
- `docs/research/2026-04-20-audio-normalization-ducking-strategy.md`
- `docs/research/2026-04-20-vinyl-broadcast-mode-d-granular-instrument.md`
- `docs/research/2026-04-20-mixquality-skeleton-design.md`
- `config/pipewire/hapax-stream-split.conf`, `voice-fx-chain.conf`
- `agents/hapax_daimonion/vocal_chain.py`, `vinyl_chain.py`
- Project memory: `project_vocal_chain.md`, `project_hardm_anti_anthropomorphization.md`
