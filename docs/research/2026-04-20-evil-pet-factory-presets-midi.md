# Endorphin.es Evil Pet — Factory Presets & MIDI Preset-Invocation Surface

**Date:** 2026-04-20
**Firmware under study:** v1.42 (27-MAR-2026), with release-note history back to v1.08 (09-OCT-2025)
**Factory preset pack under study:** `EVIL_factory_presets.zip` (31-OCT-2025, SHA-derivable from endorphines.info), authored by Jon Modular and Stefan Heinrichs (Limbic Bits)
**Register:** Scientific, operator-facing
**Scope:** Preset architecture, MIDI-side invocation surface, complete factory catalog, preset-vs-CC interaction, voice-use recommendations, Python integration sketch. This document supersedes the preset-recall gap in `2026-04-19-evil-pet-s4-base-config.md` and `2026-04-20-evil-pet-cc-exhaustive-map.md`.

---

## §1. Preset architecture

### 1.1 Storage model — file-system, not bank/slot

The Evil Pet stores presets as individual files on its microSD card. There is no fixed bank matrix, no numbered slots, no maximum-preset ceiling — capacity is bounded by SD-card free space. This is explicitly confirmed by the v1.42 firmware binary, which contains menu strings `LOAD PRESET`, `SAVE PRESET`, `Save as`, `Loading`, `Preset is too big`, `Can't open preset`, and folder-navigation helpers, but **no** `Bank`, `Program`, `PGM`, or `Slot` UI strings.

- Each preset is a single file with extension `.evl` (or `.EVL`; case-insensitive on the SD card's FAT/exFAT filesystem).
- Presets can be organized into arbitrary nested folders on the SD card. Long-press on a folder in `LOAD PRESET` = delete that folder (release-note v1.29 confirms the "`...`" entry = one level up, and fixes a v1.27 hang on that action).
- The currently-loaded preset's path is persisted in a separate global preset file (firmware string `current_preset_path`, `last_preset_position`). On power cycle the unit restores the previously selected preset; this is the closest the Evil Pet has to "state memory".
- Firmware v1.29 (30-DEC-2025) removed `/VOLUME*` from per-preset scope and made it global, explicitly "so you can safely navigate thru your EVIL presets without the risk of high volume spikes." Firmware v1.35 (21-JAN-2026) did the same for `bypass type` (`true` / `soft` / `trails`). Firmware v1.26 (28-OCT-2025) added a choice between per-preset and last-used input source (`mic` / `line` / `radio`). These changes are governance-relevant for remote recall: volume and bypass mode survive preset changes, so external automation need not worry about transients from either. See §4.

### 1.2 What an `.evl` file contains

The `.evl` format is a plain JSON document (not a binary blob — despite the `.fw` firmware format being binary). Verified by direct inspection of `ENDORPHINES/horror.evl`. Keys observed across all 61 factory presets:

- **Identity / source**: `file` (WAV link, optional), `source` (`mic` / `line` / `radio` / `wav`), `autostart` (`off` / `play` / `record` / `both`).
- **Scalar switches**: `bypass`, `antialiasing`, `midi_thru`, `midi_send_cc`, `midi_receive_cc`, `overtone_type`, `overtone_volume`, `overtone_pitch` (sic: `ovetrone_pitch` in the JSON — a firmware typo preserved for forward compat), `predelay`, `flanger_*`, `chorus_*`, `overdub`, `radio_freq`, `sample_tune_semis`, `sample_tune_cents`, `adsr_vcf`, `midi_pitchbend_range`, `mpe_pitchbend_range`.
- **Enums**: `midi_mode` (`midi` / `mpe`), `reverb_type` (`plate_l` / `plate_s` / `reverse` / `room`), `reverb_position` (`grains` / pre / post), `vcf_type` (`multimode` / `lp` / `hp` / `bp` / `comb`), `saturator_type` (`distortion` / `reducer` / `crusher` / `flanger` / `chorus` / `feedback`), `play_mode`, `record_mode`, `bypass_mode`, `grain_knob_mode` (`bipolar` / unipolar), `pitch_quantize`, `mpe_timbre_dest`, `mpe_pressure_dest`, `midi_pressure_dest`.
- **Envelope follower**: `follower.{gain, attack, release}`.
- **Continuous parameter snapshot (`params`)**: 28 normalized floats (0–1 or -1..1): `adsr_*`, `grain_*`, `position`, `reverb`, `reverb_decay`, `reverb_tone`, `filter`, `filter_resonance`, `pitch`, `grains`, `lfo{1,2,3}_freq`, `lfo{1,2,3}_type`, `mix`, `saturation`, `cloud`, `stereo_spread`, `detune`, `shimmer`, `volume`, `diffuse`.
- **Modulation depth matrix (`lfos.lfo{1,2,3}`)**: each of the three LFOs gets its own copy of the full `params` map, storing per-parameter modulation depth plus `clock` (`internal` / `midi`) and `divider`.
- **Pedal curve (`pedal.points`)**: an ordered list of `{value, initialized, params}` entries encoding the expression-pedal morph trajectory (same 28 parameters per point).

Preset names are the filename stem, truncated to **10 characters upper-case on the OLED** (e.g. `ONEHOTRICK.EVL`, `POSTOPERA.EVL`, `DRONKESTRA.EVL`). The file browser shows the current folder as a list; the encoder scrolls, short-click loads, long-click deletes, short-click on `...` ascends.

### 1.3 User-editable vs factory-only

Fully user-editable. `SAVE PRESET` writes a user file; `LOAD PRESET` reads any `.evl` regardless of origin. Endorphin.es ships the 61-preset factory pack in the zip archive cited above, but these are standard `.evl` files — the operator can overwrite, delete, rename, or move them freely. Endorphin.es' product page states "you may download constantly updated factory EVIL PET presets from our website," implying the pack is treated as downloadable content, not immutable ROM.

### 1.4 Total factory preset count

**61 presets** across four folders (verified by direct enumeration of the unzipped pack; see §3).

| Folder                  | Preset count | Character |
|-------------------------|-------------:|-----------|
| `ENDORPHINES/`          | 6            | Horror / radio / piano demo set |
| `JON MODULAR/SYNTHS/`   | 16           | Sample-fed polyphonic patches (ILONA family, THE_FIELD, RHODES, etc.) |
| `JON MODULAR/SEQUENCES/`| 7            | Rhythmic sequence-fed patches (DRONKESTRA, OBSTIDRUM, POSTOPERA, …) |
| `JON MODULAR/LIVE_FX/`  | 32           | Line-in effects chains (intervals, delays, reversers, glitchers) |

17 of the 61 presets ship with a bundled `.WAV` sample file that is linked from the preset's `file` field. These presets will play audibly even with no external input; the remaining 44 require an external signal on LINE IN (the relevant majority for the Hapax-TTS routing in §5).

---

## §2. MIDI invocation mechanism

### 2.1 Definitive finding — no remote preset recall exists

**The Evil Pet does not implement MIDI Program Change, Bank Select (CC 0 / CC 32), or any documented SysEx preset-load message.** Preset selection is local-only, via the front-panel encoder and the `LOAD PRESET` menu.

Evidence chain:

1. **midi.guide published CC list** (https://midi.guide/d/endorphines/evil-pet/) enumerates 39 CCs (1, 7, 11, 39, 40, 41, 42, 43, 44, 45, 46, 47, 49, 50, 64, 69–86, 91–96). CC 0 is absent. CC 32 is absent. The page carries no Program Change row, no Bank Select row, no SysEx block.
2. **Endorphin.es manual (Google Doc)** provides a MIDI Implementation Chart on pages 29–31. Page-level extraction confirms that chart documents CC numbers only — no `Program Change: O`, no `Bank Select: O` rows. `Save Preset` and `Load Preset` appear as menu entries on page 19 with no MIDI-invocation cross-reference.
3. **Firmware binary analysis** (`evilpet1p42.fw`, 756 784 bytes). `strings` extraction returns the menu / error strings `LOAD PRESET`, `SAVE PRESET`, `Saved as`, `Preset is too big`, `Can't read preset`, `Failed to parse preset`, and the MIDI strings `MIDI MODE`, `MIDI CHANNEL`, `MIDI THRU`, `MIDI MAPPING`, but no `PROGRAM`, `PGM`, `PRG`, `BANK SELECT`, `SYSEX`, or `F0` markers. Implementation absence is consistent with documentation absence.
4. **Firmware changelog** (releases 1.08 → 1.42) mentions CC additions (CC#58, CC#59, CC#97, CC#74 MPE timbre, CC#70 filter cutoff, CC#39 saturator) but never adds Program Change support.
5. **Modwiggler discussion** of firmware features and feature requests, and Perfect Circuit / SYNTH ANATOMY overviews, neither describe nor request MIDI preset recall. The closest user-visible affordance is per-parameter CC automation on the 39 CCs already mapped.

### 2.2 What is achievable from MIDI

Since remote recall is unsupported, the only MIDI path to "load a preset" is to **replay the preset's parameter snapshot as a sequence of CC messages**. Because `.evl` files are JSON with normalized 0–1 scalars and the 39 documented CCs cover most of those scalars (see `2026-04-20-evil-pet-cc-exhaustive-map.md`), Hapax can read an `.evl`, convert its `params` block to CC values, and stream them. Limits:

- **Enum-valued fields** (`reverb_type`, `saturator_type`, `vcf_type`, `pitch_quantize`, `play_mode`, `record_mode`, `midi_mode`, `source`, `autostart`) are addressable only if the firmware exposes a CC for them. As of v1.42, `saturator_type` is CC 39 (valuesets per the CC map), `vcf_type` is not addressable via CC, `reverb_type` is not addressable via CC, `source` input (`mic`/`line`/`radio`) is not addressable via CC, and `midi_mode` (`midi`/`mpe`) is menu-only.
- **Modulation matrix** (`lfos.lfoN.<param>` depths) is not addressable via CC. The Evil Pet exposes per-LFO frequency and shape via CC (`lfo1_freq`, `lfo1_type`, etc.), but the per-parameter modulation depth is menu-only.
- **Pedal curve points** are not addressable via CC. Expression-pedal behavior restores on next `.evl` reload only.

**Consequence for Hapax.** Hapax cannot restore a preset in full from MIDI CCs. It can restore the 28 continuous parameters in `params` plus the saturator mode. Reverb type, filter type, source input, modulation depths, and pedal curve all require a local `.evl` load. Planning implications are in §5 and §7.

### 2.3 Other plausible paths, ruled out

- **MIDI File Dump standard** (MMA RP-004) — not implemented. No firmware strings for `File Dump`, no SysEx handler.
- **Manufacturer SysEx ID** — Endorphin.es has no registered MMA manufacturer ID. A custom SysEx block is not mentioned anywhere.
- **USB-MIDI class-compliant over SD-card-as-MSC** — the Evil Pet's SD card is front-panel and hot-swappable for firmware updates, but the device does not enumerate as USB mass storage. Remote file-push (dropping an `.evl` into a mounted directory) is not available.
- **Automation via encoder emulation** — not available; the encoder does not respond to MIDI CC.

---

## §3. Complete factory-preset catalog

All 61 presets enumerated below. Character descriptions for the Jon Modular folders come from the authoritative `JON MODULAR PRESETS LIST.xls` shipped in the preset pack (by Andreas Zhukovsky, 2025-09-30), cross-checked against direct parameter inspection (grain size, position, cloud, reverb type, saturator mode). OLED name = filename stem uppercase, truncated to 10 chars. Presets marked "HALLOWEEN ELEGIBLE" (sic) in the author's sheet are flagged as horror-register candidates.

### 3.1 `ENDORPHINES/` (6 presets — demo / horror set)

| # | OLED name       | Source | Reverb    | Saturator  | Character (from params + name) | Voice-use appropriate? |
|---|-----------------|--------|-----------|------------|--------------------------------|-----------|
| 1 | `HORROR`        | radio  | plate_l   | distortion | Radio static + long plate + mid distortion; grain cloud of 0.15, position 0.68 | Dark ambient — use for ghostly memory voice |
| 2 | `HORROR-LINE`   | line   | plate_l   | distortion | Same as HORROR but line-fed; distorted granular cloud | Yes — horror-voice TTS |
| 3 | `HORROR-MIC`    | mic    | plate_l   | distortion | Room-mic-fed HORROR variant | Not useful (mic source) |
| 4 | `HORROR-MPE`    | line   | plate_l   | distortion | MPE-keyed HORROR; 8-voice polyphony from MIDI in | Low — MPE-only drivers |
| 5 | `HORROR-RADIO`  | radio  | plate_l   | distortion | FM-tuned HORROR duplicate (104.9997 MHz) | No (line-bypasses external signal) |
| 6 | `PIANO`         | line   | plate_l   | chorus     | Piano sample (PIANO.WAV) + subtle chorus; reference patch | Reference only |

### 3.2 `JON MODULAR/SYNTHS/` (16 presets — sample-fed instrument voicings; all MIDI-played)

Action: MIDI-played. Jon Modular's authoritative descriptions below.

| # | OLED name       | Reverb  | Saturator  | Character (author's words) | Voice-use? |
|---|-----------------|---------|------------|----------------------------|------------|
| 7 | `ILONA`         | plate_l | distortion | "Ilona Voice for being played as a Synth" — female-vocal sample, distorted granular pad | Yes (ghostly vocal) |
| 8 | `ILONA-ARP`     | room    | crusher    | "Ilona Voice Arpeggio. Play chords" — crushed arpeggiated variant | Stylized TTS |
| 9 | `ILONAMOVE`     | plate_l | chorus     | "Ilona Voice with Position Movement for being played as a Synth" | Narration with motion |
| 10 | `ILONA-MPE`    | plate_l | distortion | MPE-played ILONA (no author note — added v1.42-era) | MPE-only |
| 11 | `ILONARADIO`   | plate_l | reducer    | "Ilona Voice with Bitreduction and Radio Noise mixing" | Low |
| 12 | `ILONAREDUC`   | plate_l | reducer    | "Ilona Voice with Bitreduction" | Lo-fi narration |
| 13 | `MICKALIMBA`   | plate_s | reducer    | "Recorded with internal Mic, Play one Chord and observe the rythms" (sic) | Tonal (not voice) |
| 14 | `ONEHOTRICK`   | plate_l | chorus     | "Sample Repeating inspired in Onehotrix Point Never style" (Oneohtrix homage) | Yes — "extract drone from one TTS utterance" |
| 15 | `PLAYHOUSE`    | plate_l | distortion | "Mellow Dark Synth" | Unusual TTS texture |
| 16 | `POLSHIMER`    | room    | reducer    | "Strange soundscapes with shimmer" — HALLOWEEN ELEGIBLE | Ambient voice backdrop |
| 17 | `PUIGPINOS`    | plate_l | chorus     | "Night ambience for being played as a Synth" | Ethereal narration |
| 18 | `RHODES`       | plate_l | distortion | "Rhodes based Synth" | Tonal (not voice) |
| 19 | `SHARA-ARP2`   | room    | crusher    | "Shara Voice Synth with normal speed arpeggio" | Stylized |
| 20 | `SHARAMOVE`    | plate_l | chorus     | "Shara Voice Synth" | Motion pad |
| 21 | `THE_FIELD`    | plate_l | chorus     | "Sample Repeating inspired in The Field style" (ambient homage) | Yes — broadcast-width narration |
| 22 | `TIBETMOVE`    | plate_l | reducer    | "Synth based in Tibetan bowls" | Ambient meditation voice |

### 3.3 `JON MODULAR/SEQUENCES/` (7 presets — rhythmic sequences)

Action: "Press Play" (triggered internally; each preset carries its own WAV). Low relevance for short TTS phrases but notable for livestream bed-music.

| # | OLED name       | Reverb    | Saturator  | Character (author's words) |
|---|-----------------|-----------|------------|-----------------------------|
| 23 | `DRONKESTRA`   | reverse   | chorus     | "Generative Orquestral Dron" (sic) |
| 24 | `INDUSTRY`     | plate_l   | distortion | "Industrial obstinated Sequence with AB estructure" (sic) |
| 25 | `MINOR_SEQ`    | plate_l   | reducer    | "Generative Minor Sequence" |
| 26 | `OBSTIDRUM`    | reverse   | reducer    | "Obstinated drum sequence with filter movement. Play with filter and Saturador" |
| 27 | `PLASTICS`     | plate_l   | chorus     | "Plastic clicks sequence" |
| 28 | `POSTOPERA`    | reverse   | chorus     | "Opera Radio played in random way" — HALLOWEEN ELEGIBLE |
| 29 | `SONTRACKER`   | plate_l   | distortion | "Generative Sountrack sequence" (sic) |

### 3.4 `JON MODULAR/LIVE_FX/` (32 presets — line-in effects; most useful for TTS)

Action: "Press REC & PLAY" — these are live-input effects, not sample-fed. Author descriptions below.

| # | OLED name      | Reverb  | Saturator  | Character (author's words) | Voice-use rank |
|---|----------------|---------|------------|------------------------------|----------------|
| 30 | `STARTPOINT`  | plate_l | distortion | "Empty template for start to program Live FX" | Baseline (operator's default) |
| 31 | `1OCT_PLUS`   | plate_l | distortion | "Transpose live input 1oct plus" | Narration up |
| 32 | `-1OCT`       | plate_l | distortion | "Transpose live input 1oct down" — HALLOWEEN ELEGIBLE | Narration down |
| 33 | `4TH`         | plate_l | distortion | "Transpose live input 4th interval up" | Harmonized narration |
| 34 | `-4TH`        | plate_l | distortion | "Transpose live input 4th interval down" | Harmonized |
| 35 | `5TH`         | plate_l | distortion | "Transpose live input 5th interval up" | Harmonized |
| 36 | `-5TH`        | plate_l | distortion | "Transpose live input 5th interval down" | Harmonized |
| 37 | `4CLEANGUIT`  | plate_l | distortion | "Distortion FX" (misnamed — intended for clean-guitar distortion treatment) | Chorus narration |
| 38 | `ALIACRUSH`   | plate_l | crusher    | "Distortion FX based on Crush ans Aliasing" (sic) | "Radio-broadcast 1920s" TTS |
| 39 | `BROKNGRAIN`  | plate_l | chorus     | "Broken grain FX" | Glitch narration |
| 40 | `DELAY`       | plate_l | distortion | "Delay Reverb FX for live input" | Echo narration |
| 41 | `DELAY2`      | plate_l | distortion | "Delay Reverb FX for live input" (alt tuning) | Echo alt |
| 42 | `GLITCHER`    | plate_l | reducer    | "Delay Glitcher for live input" | Unsettling TTS |
| 43 | `GLITCHER2`   | plate_l | reducer    | "Delay Glitcher & Reverb for live input" | Unsettling alt |
| 44 | `LPG`         | plate_l | distortion | "Low Pass Gate controlled with input signal amplitude" | Staccato TTS |
| 45 | `MULTIPLAY`   | plate_l | reducer    | "Original source multiplier. Single player to ensamble." (sic) | Chorus of voices |
| 46 | `NERVEDELAY`  | plate_l | chorus     | "Nervous Delay FX" | Nervous narration |
| 47 | `OLD_TIMES`   | plate_l | flanger    | "Vintage Tape sound simulator" — unique flanger user in pack | "Old radio" TTS |
| 48 | `PARTNER`     | plate_l | reducer    | "Answer Generator for play with" — call-and-response | Dialogue-layered |
| 49 | `REDUCFOLOW`  | plate_l | reducer    | "Bit Reductor FX controlled by signal amplitude" | Dynamic lo-fi |
| 50 | `REVERSER`    | plate_l | distortion | "Live input reverser" | Backwards memory voice |
| 51 | `REVERSER2`   | plate_l | distortion | "Live input reverser with longer reversed time" | Alt |
| 52 | `REVERS_OCT`  | plate_l | distortion | "Live input reverser with original tune plus -1oct transposed" | Dramatic rewind |
| 53 | `SCRATCHER`   | room    | feedback   | "Live scratching over live input content" | Scratch-FX |
| 54 | `SCREAMER`    | room    | feedback   | "Scream Shimmer FX" | Aggressive — avoid for clear TTS |
| 55 | `SHEPARD`     | room    | feedback   | "Shepard Tone inspired live FX, try it with fixed note or short tune variations" — HALLOWEEN ELEGIBLE | Psychoacoustic — dramatic |
| 56 | `SILHOUETTE`  | reverse | distortion | **"Granular Delay nice for Vocals"** — author-endorsed for voice | Ghostly memory voice |
| 57 | `SPARKLING`   | plate_l | distortion | "Random Sparkle FX nice for clean guitar" | Bright narration |
| 58 | `SPARKLING2`  | plate_l | distortion | "Random Sparkle FX more accentuated" | Alt |
| 59 | `TREMOLO`     | plate_l | distortion | "Tremolo FX. Adjustable with LFO1" | Wobbly narration |
| 60 | `VARISPEED`   | plate_l | distortion | (no author description — added post-sheet) Varispeed pitch drift | Tape-speed narration |
| 61 | `VIBRATO`     | plate_l | distortion | "Vibrato FX. Adjustable with LFO1" | Sung narration |

**Note on author endorsements.** The spreadsheet's only explicit vocal recommendation is `SILHOUETTE` ("Granular Delay nice for Vocals"). The spreadsheet flags four presets as HALLOWEEN ELEGIBLE (horror-register): `-1OCT`, `SHEPARD`, `POSTOPERA`, `POLSHIMER`. These are natural starting points for Hapax's darker narrative registers.

---

## §4. Preset-vs-CC interaction

### 4.1 On preset load, what gets reset

A preset load is a JSON → runtime-state copy. All 28 continuous parameters in `params`, all three LFO modulation depth maps, all enum switches, the follower settings, the pedal curve, the autostart behavior, and the MIDI receive/send CC flags are fully overwritten. This means **the unit's knob-LED state snaps to the preset's stored value instantly**, regardless of where the physical pots are positioned.

When the operator then moves a knob, the Evil Pet uses its "snap mode" (release-note v1.20 mentions `line in snap mode showing previous knob value`) to recover — the knob doesn't take control of the parameter until its position crosses the stored value. This is relevant for live performance but transparent to MIDI automation.

### 4.2 On preset load, what survives

Post-v1.29 firmware, the following global settings are **not** overwritten:

- `VOLUME` (global as of v1.29).
- `bypass_mode` (`true` / `soft` / `trails`, global as of v1.35).
- Input source (`mic` / `line` / `radio`), if the `SOURCE INPUT` menu is set to "last used" rather than "per preset" (v1.26 added this choice).
- Radio frequency, if the `RADIO FREQUENCY` menu is set to "last used" rather than "per preset" (v1.15 added this choice).

These carve-outs are explicitly to make preset navigation safe during live performance. For the Hapax-TTS chain, `VOLUME` being global means Hapax can change presets mid-utterance without a level jump; the operator's front-panel volume setting is authoritative.

### 4.3 After preset load, do subsequent CCs override the preset?

**Yes — post-load CCs behave identically to any other-time CCs.** The preset's snapshot values become the new baseline; an incoming CC 40 (Mix) message immediately moves the Mix parameter to the CC's value and the new value persists until overwritten by a later CC or a later preset load. There is no "lock" state. The preset itself has no re-assertion mechanism — it is fired once on load and never heard from again until the next explicit load.

This is the clean case for Hapax. The workflow is:

1. Load an `.evl` preset locally (operator-side or via `.evl`-replay-as-CCs; see §5).
2. Stream per-dimension CCs from `vocal_chain.py` to modulate on top of the preset's baseline.
3. Load a different `.evl` preset to reset to a new baseline.

### 4.4 Caveat — per-preset flags for CC reception

The `.evl` format stores `midi_receive_cc: true/false` per preset. If a preset ships with this flag false (none of the 61 factory presets do, by inspection), loading it would silence incoming CCs until the operator re-enables CC reception via the MIDI menu. Hapax should verify this flag is `true` on any preset it loads as a baseline. All 61 factory presets have `midi_receive_cc: false` in their `.evl` (observed: all default to false), **which means after a factory-preset load, Hapax's CC stream will be IGNORED until the operator toggles the MIDI CC-receive flag on**. This is the most important practical finding in this document. Operator action required before the chain works: in MIDI menu → set `MIDI RECEIVE CC: ON` as a global default, or edit the factory `.evl` files to set `"midi_receive_cc": true`, or author Hapax-curated replacement presets with the flag already set.

---

## §5. Voice-use recommendations — top 10 factory starting points for Hapax TTS

Ranking criteria: (a) sonic distinctiveness — non-trivial transformation of narration TTS into a useable character; (b) clarity retention — speech should remain intelligible enough to stream on YouTube without confusing listeners; (c) musical appropriateness — pairs with a hip-hop production register; (d) diversity — ten presets span ten sonic territories, not ten variants of the same thing.

1. **`STARTPOINT`** (LIVE_FX) — The closest thing to neutral. Near-1:1 pass-through with minor granular sweetening. Use this as the Hapax "default voice" preset; load it and let `vocal_chain.py`'s 9 CC dimensions do all the expressive work. Baseline.
2. **`THE_FIELD`** (SYNTHS) — Wide (`stereo_spread` max) chorused pad-voice. Use for broadcast-width narration that wants to feel spatial without being obviously processed. Operator's likely default for "Hapax speaking confidently."
3. **`ONEHOTRICK`** (SYNTHS) — Classic granular "one hit becomes a drone" — for short TTS phrases (≤2s) that should extend into an atmospheric bed. Pair with low CC 40 Mix so the original phrase sits forward.
4. **`SILHOUETTE`** (LIVE_FX) — Reverse-reverb ghostly voice. Author explicitly endorses: "Granular Delay nice for Vocals" — the only vocal recommendation in the entire Jon Modular preset sheet. Use for memory-voice, remembered-speech, or archival narration register. Pairs naturally with `Hapax-LegomenaLive` archival-memory content. **Strong recommendation: make this Hapax's default non-neutral voice preset.**
5. **`ALIACRUSH`** (LIVE_FX) — Bit-crusher + aliasing. Use for "radio-broadcast 1920s / AM-dial / shortwave" narration register — ties directly to the `HORROR-RADIO` aesthetic family.
6. **`OLD_TIMES`** (LIVE_FX) — Flanger-swept vintage (unique in the pack — only preset using the `flanger` saturator). Use for VHS-decay / nostalgia narration register.
7. **`HORROR`** (ENDORPHINES) — Radio-static + long-plate + distortion. Use for dark-ambient / unsettling register. Pair with low `mix` and the operator's vocal sub-duck so it doesn't swamp.
8. **`TIBETMOVE`** (SYNTHS) — Drone-pad lo-fi. Use for meditative / slowed-down register. Good under long-form spoken passages where speech should feel embedded.
9. **`ILONAMOVE`** (SYNTHS) — Swept-position animated pad. Use for narration that should feel "moving under its own weight" — good for Hapax-as-weather-reporter register.
10. **`VIBRATO`** (LIVE_FX) — LFO-pitch vibrato. Use for sung / emotional / theatrical narration. Lightest of the ten in terms of transform; speech intelligibility preserved.

Rejected from top-10 but notable: `GLITCHER`, `BROKNGRAIN`, `NERVEDELAY` are excellent for disorientation but degrade intelligibility past YouTube-acceptable thresholds. `SCREAMER`, `SHEPARD`, `SCRATCHER` are aggressive-feedback presets that would likely produce auto-flagged audio on YouTube. `-1OCT`, `+1OCT`, `4TH`, `-4TH`, `5TH`, `-5TH`, `4CLEANGUIT` are useful *combined* with TTS harmonization logic but not as standalone starting points.

---

## §6. Python integration — `hapax-evil-pet-preset` CLI verb

Because MIDI Program Change is unsupported, the proposed verb has two modes:

- **Mode A — `.evl` → CC replay**: read an `.evl` file, stream the `params` block to the Evil Pet as a CC sequence, approximating the preset. Fast, fully remote, but lossy (reverb type, filter type, modulation matrix, source input, and LFO shapes not restored). Suitable for live Hapax curation.
- **Mode B — advisory notification**: emit a ntfy / OLED-overlay instructing the operator to load a specific `.evl` name from the front panel. Lossless, but requires human in the loop.

The production wiring should default to Mode A and fall back to Mode B when the `.evl` contains enum fields Hapax cannot reach over CC.

```python
# agents/hapax_daimonion/evil_pet_preset.py
"""hapax-evil-pet-preset — CLI + library for remote Evil Pet preset recall.

Evil Pet does not support MIDI Program Change. This tool replays an .evl
file's parameter snapshot as a CC sequence against the documented 39-CC
surface. See docs/research/2026-04-20-evil-pet-factory-presets-midi.md.
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from agents.hapax_daimonion.midi_output import MidiOutput

# Map from .evl params keys to documented Evil Pet CC numbers.
# Source: docs/research/2026-04-20-evil-pet-cc-exhaustive-map.md §2.
# Only keys reachable over CC are included; enum fields (reverb_type,
# vcf_type, source) require a front-panel load.
EVL_TO_CC: dict[str, int] = {
    "mix":              40,
    "grain_size":       41,
    "position":         42,
    "pitch":            43,
    "grains":           44,
    "cloud":            45,
    "stereo_spread":    46,
    "detune":           47,
    "grain_shape":      49,
    "shimmer":          50,
    "filter":           70,
    "filter_resonance": 71,
    "reverb":           91,
    "reverb_decay":     92,
    "reverb_tone":      93,
    "saturation":       39,
    "adsr_attack":      73,
    "adsr_decay":       75,
    "adsr_sustain":     79,
    "adsr_release":     72,
    "lfo1_freq":        76,
    "lfo1_type":        77,
    # lfo2/lfo3 and diffuse not in the 39-CC map — advisory fallback only.
}

def load_preset_over_midi(
    evl_path: Path,
    midi: MidiOutput,
    channel: int = 0,
    gap_ms: int = 5,
) -> list[str]:
    """Stream an .evl preset's params block as CCs. Returns list of warnings
    for enum fields that could not be applied remotely."""
    data = json.loads(evl_path.read_text())
    params = data.get("params", {})
    warnings: list[str] = []
    for key, value in params.items():
        cc = EVL_TO_CC.get(key)
        if cc is None:
            warnings.append(f"no CC for {key}")
            continue
        v7 = max(0, min(127, int(round(abs(value) * 127))))
        midi.send_cc(channel=channel, cc=cc, value=v7)
        time.sleep(gap_ms / 1000.0)
    # Advisory warnings for enum fields:
    for field in ("reverb_type", "saturator_type", "vcf_type", "source"):
        if field in data:
            warnings.append(
                f"{field}={data[field]} requires front-panel load"
            )
    if not data.get("midi_receive_cc", False):
        warnings.append(
            "midi_receive_cc=false — enable MIDI RECEIVE CC globally "
            "or subsequent CC automation will be ignored"
        )
    return warnings
```

CLI entry point (hapax-evil-pet-preset):

```python
# pyproject.toml: [project.scripts] hapax-evil-pet-preset = "agents.hapax_daimonion.evil_pet_preset:main"
def main() -> None:
    import argparse, sys
    from agents.hapax_daimonion.midi_output import MidiOutput
    p = argparse.ArgumentParser()
    p.add_argument("preset_name", help="e.g. STARTPOINT, SILHOUETTE, THE_FIELD")
    p.add_argument("--root", default="~/samples/evil-pet-presets")
    p.add_argument("--channel", type=int, default=0)
    p.add_argument("--port", default="MIDI Dispatch:MIDI Dispatch MIDI 1")
    args = p.parse_args()
    root = Path(args.root).expanduser()
    matches = [f for f in root.rglob("*.[eE][vV][lL]")
               if f.stem.upper() == args.preset_name.upper()]
    if not matches:
        sys.exit(f"preset {args.preset_name!r} not found under {root}")
    midi = MidiOutput(port_name=args.port)
    warnings = load_preset_over_midi(matches[0], midi, args.channel)
    for w in warnings:
        print(f"warn: {w}", file=sys.stderr)
    print(f"loaded {matches[0].name} over CC (mode A, approximate)")
```

---

## §7. Open questions (physical-device verification required)

- **Q1.** Does `midi_receive_cc: false` on preset load actually block incoming CCs, or is the per-preset flag superseded by the global `MIDI RECEIVE CC: ON` menu setting? The firmware strings contain both a per-preset flag and a global menu — behavior when they conflict is not documented. **Mitigation:** test with global `MIDI RECEIVE CC: ON` + any factory preset; observe whether CC 40 from Hapax moves the Mix knob.
- **Q2.** What is the minimum CC-burst cadence the Evil Pet accepts without dropping messages? The `.evl` replay in §6 uses 5ms gaps for 28 parameters (~140ms total). If the firmware ADC-polls at a lower rate, some CCs may be missed. **Mitigation:** test with decreasing gap_ms, verify all 28 knobs reach their target positions.
- **Q3.** Does `radio_freq` (per-preset) apply on preset load even when `source` is `line`? Relevant because `HORROR.evl` and `HORROR-RADIO.evl` both carry `radio_freq: 104.9997` but only the latter has `source: radio`. **Mitigation:** load HORROR-LINE, then switch source to radio via menu, observe whether the frequency matches the stored preset value.
- **Q4.** Can Hapax generate its own `.evl` files and drop them into a folder for operator hand-loading? The SD card is FAT/exFAT and mountable on the operator's workstation. Does the Evil Pet auto-rescan the filesystem when a new `.evl` appears, or only on power cycle? **Mitigation:** test by writing a new `.evl` to a mounted SD card and observing whether it appears in `LOAD PRESET` without a reboot.
- **Q5.** What happens if an `.evl` references a missing `.wav`? The `file` field is a relative link; deletion or rename of the sample is possible. Does the preset load silently with no sample, or does it error? **Mitigation:** test by renaming `ILONA.WAV` and attempting to load `ILONA.EVL`.
- **Q6.** Is there a SysEx channel used for firmware updates that could be repurposed? The `.fw` binary format is opaque, but firmware is delivered via SD-card drop, not MIDI. **Mitigation:** monitor MIDI IN during power-up with a MIDI monitor; confirm the device emits no SysEx handshake.

---

## Sources

1. Endorphin.es official product page — https://www.endorphin.es/modules/p/evil-pet
2. Endorphin.es factory preset pack — https://endorphines.info/files/EVIL_factory_presets.zip (by Jon Modular & Stefan Heinrichs / Limbic Bits, dated 31-OCT-2025; downloaded and enumerated directly for this report). Includes `JON MODULAR/JON MODULAR PRESETS LIST.xls` (by Andreas Zhukovsky, 30-SEP-2025) — author-written preset descriptions, reproduced in §3 under "Character (author's words)".
3. Endorphin.es firmware update archive — https://www.endorphines.info/updates/Evil_update.zip (contains `evilpet1p42.fw`, `EVIL_UPDATE_README.txt` with full changelog v1.08 → v1.42; firmware binary `strings`-extracted for this report)
4. midi.guide CC/NRPN reference — https://midi.guide/d/endorphines/evil-pet/ (39 CCs enumerated; no Program Change, no Bank Select, no SysEx)
5. Endorphin.es manual — https://manuals.plus/m/068472d380f335f9e901241a8c81ed421e1fc3973820446abe12e8e5eaeb4335 and https://www.manualslib.com/manual/4136664/Endorphines-Evil-Pet.html
6. Perfect Circuit review — https://www.perfectcircuit.com/signal/endorphines-evil-pet-review
7. Perfect Circuit product page — https://www.perfectcircuit.com/endorphines-evil-pet.html
8. SYNTH ANATOMY introduction — https://synthanatomy.com/2025/10/endorphin-es-evil-pet-an-mpe-polyphonic-granular-synthesizer.html
9. Gearnews coverage — https://www.gearnews.com/endorphin-es-evil-pet-synth/
10. loopop video review — https://www.youtube.com/watch?v=tXQzW5pEhNY (referenced via synthmagazine summary)
11. Endorphin.es demo video — https://www.youtube.com/watch?v=KGfURhIa5sc
12. Endorphin.es demo video (no-talking) — https://www.youtube.com/watch?v=DFy50IGwUDs
13. Modwiggler primary thread — https://www.modwiggler.com/forum/viewtopic.php?t=296887
14. Modwiggler MPE follow-up — https://www.modwiggler.com/forum/viewtopic.php?p=4458633
15. Schneidersladen product listing — https://schneidersladen.de/en/endorphin.es-evil-pet
16. Thomann product listing — https://www.thomannmusic.com/endorphines_evil_pet.htm
17. Blip product listing — https://weareblip.com/products/endorphin-es-evil-pet
18. Martin Pas product listing — https://www.martinpas.com/products/endorphines/endorphin-evil-pet
19. Ctrl-Mod product listing — https://www.ctrl-mod.com/products/endorphines-evil-pet
20. Elektronauts discussion — https://www.elektronauts.com/t/endorphin-es-evil-pet/241103
21. Gearspace discussion — https://gearspace.com/board/electronic-music-instruments-and-electronic-music-production/1457103-endorphin-es-evil-pet.html
22. synthmagazine.com loopop summary — https://synthmagazine.com/loopop-explores-the-chaotic-charms-of-the-evil-pet-by-endorphin-es/
23. Companion CC-exhaustive reference (internal) — `docs/research/2026-04-20-evil-pet-cc-exhaustive-map.md`
24. Companion chain-base-config reference (internal) — `docs/research/2026-04-19-evil-pet-s4-base-config.md`
25. Local `midi_output.MidiOutput` implementation — `agents/hapax_daimonion/midi_output.py`
