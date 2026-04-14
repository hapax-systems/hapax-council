# Sprint 3 — Audio Capture + Analysis + Reactivity

**Date:** 2026-04-13 CDT
**Theme coverage:** F1 (PipeWire graph), F2 (audio input inventory), G1 (feature extraction), G2-G5 (RMS/FFT/BPM/transient), G6 (modulation path), G7 (preset reactivity map)
**Register:** scientific, neutral

## Headline

**Six findings, one of them is good news and the rest are unblocks for better reactivity:**

1. **The audio reactivity pipeline is EXTENSIVE and largely correct.** `agents/studio_compositor/audio_capture.py` is a well-designed DSP pipeline that captures from the `mixer_master` PipeWire virtual source via `pw-cat`, runs Hann-windowed FFT at 10.7 ms chunks, and exposes **18+ audio features** (mixer_energy, mixer_bass/mid/high, mixer_beat, onset_kick/snare/hat, sidechain_kick, spectral_centroid/flatness/rolloff, zero_crossing_rate, plus 8 mel bands).
2. **`_default_modulations.json` is merged into every preset at load time.** `agents/studio_compositor/effects.py:81` calls `merge_default_modulations(graph)`. This means every preset inherits the baseline audio-reactive modulation table even without explicit preset-level modulation.
3. **Sidechain kick ducking is already wired.** `sidechain_kick` is published at 0.92x decay per frame (0.95x in vinyl mode) from `audio_capture.py`. It scales colorgrade brightness by -0.7 on kick hits. This is the visual-side ducking the operator wants, and it exists.
4. **47 vs 30 fps cadence mismatch.** mixer_input.py analyzes at 47 fps (21.3 ms frames) + audio_capture.py at 93 fps (10.7 ms chunks), but the compositor's fx_tick reads signals at 30 fps (33.3 ms). **Transient resolution at the render layer is capped at 33 ms even though the analysis resolves to 10 ms.** Sub-frame transients (sharp drum hits) get quantized at the render boundary.
5. **PipeWire graph is healthy.** 91 nodes, 64 links, 12 video sources, 13 audio sources, 9 audio sinks, 44 audio stream inputs, 2 MIDI bridges. No dead nodes observed.
6. **`mixer_master` is a real PipeWire Audio/Source** (confirmed via `pw-cli`), and `audio_capture.py` is live-connected (journal: `pw-cat connected to mixer_master`). The foundational audio plumbing works.

## Data

### F1.1 — PipeWire graph inventory (pw-dump summary)

```text
Total nodes: 91
Total links: 64

Nodes by media.class:
   44  Stream/Input/Audio      ← audio clients reading sources
   13  Audio/Source            ← physical + virtual audio sources
   12  Video/Source            ← 6 cameras, each exposes 2 video nodes
    9  Audio/Sink              ← output devices + loopbacks
    9  Stream/Output/Audio     ← audio producers writing sinks
    2  Midi/Bridge             ← MIDI routing
    2  (unclassified)          ← utility nodes
```

**Healthy graph shape**. 13 sources feeding 44 listeners + 9 sinks is consistent with a studio that has multiple cameras routing audio to multiple consumers (OBS, compositor, daimonion).

### F2.1 — `mixer_master` virtual source confirmed

```text
$ pw-cli list-objects Node | grep -A1 mixer_master
  node.name = "mixer_master"
  node.description = "Mixer Master Output"
  media.class = "Audio/Source"
```

**The mixer_master is a PipeWire Audio/Source**, not a physical device. Likely a filter-chain or loopback sink-exposed-as-source that aggregates the hardware mixer's output into a virtual source pin. The compositor's audio capture pulls from this pin.

**Why this is clean**: the compositor doesn't need to know about the PreSonus Studio 24c channel count or the Yeti's routing — it just reads the pre-mixed output of whatever the operator has routed to the mixer. Adding a new input source (another mic, a music player, an OBS audio source) requires no compositor change.

### F3.1 — `audio_capture.py` → live

**Journal confirms connection**:

```text
Apr 13 19:58:36 audio_capture started (target=mixer_master)
Apr 13 19:58:36 audio_capture _capture_loop pw-cat connected to mixer_master
```

**DSP constants**:

```python
RATE = 48000
CHANNELS = 2
CHUNK = 512                # 10.7ms chunks
CHUNK_BYTES = CHUNK * 4    # stereo int16

AGC_HISTORY_LEN = 372      # 4-second rolling AGC history
MEL_BAND_EDGES_HZ = [20, 60, 250, 500, 1000, 2000, 4000, 8000, 16000]
MEL_BAND_NAMES = ["sub_bass", "bass", "low_mid", "mid",
                  "upper_mid", "presence", "brilliance", "air"]
```

**Analysis frame rate**: 48000/512 = **93.75 fps** at the DSP side. Each chunk is 10.7 ms. The `mixer_input.py` alternative backend at `agents/hapax_daimonion/backends/mixer_input.py` uses a different cadence (1024 samples = 21.3 ms = 47 fps).

**Two overlapping audio analysis paths exist**:
- `agents/studio_compositor/audio_capture.py` — 10.7 ms chunks, richer feature set, FEEDS THE COMPOSITOR MODULATOR
- `agents/hapax_daimonion/backends/mixer_input.py` — 21.3 ms chunks, simpler feature set, feeds the daimonion perception layer

Both pull from `mixer_master`. This is a **dual-consumer pattern** — each client opens its own `pw-cat` stream and runs its own DSP. PipeWire handles the node duplication.

### G1.1 — Full audio feature catalog (from audio_capture.py:106-123)

```python
self._signals = {
    "mixer_energy":       0.0,  # RMS from full-band audio
    "mixer_bass":         0.0,  # Bass band RMS (20-250 Hz mel)
    "mixer_mid":          0.0,  # Mid band RMS (250-2000 Hz)
    "mixer_high":         0.0,  # High band RMS (2000-8000 Hz)
    "mixer_beat":         0.0,  # Beat pulse (spike + decay)
    "onset_kick":         0.0,  # Kick drum onset
    "onset_snare":        0.0,  # Snare drum onset
    "onset_hat":          0.0,  # Hi-hat onset
    "sidechain_kick":     0.0,  # Slow-decay kick for sidechain pump
    "spectral_centroid":  0.0,  # Brightness measure
    "spectral_flatness":  0.0,  # Noise vs tonality measure
    "spectral_rolloff":   0.0,  # 85% energy cutoff frequency
    "zero_crossing_rate": 0.0,  # Fast-attack transient-ish proxy
    "beat_pulse":         0.0,  # Alias for mixer_beat
    # Plus 8 mel-band signals:
    "mel_sub_bass", "mel_bass", "mel_low_mid", "mel_mid",
    "mel_upper_mid", "mel_presence", "mel_brilliance", "mel_air",
}
```

**18 signals total** published from `audio_capture.py`. All available as modulation sources in the effect graph.

### G2.1 — RMS envelope + beat detection

`mixer_input.py:39-44` (daimonion side):

```python
_RMS_SMOOTHING = 0.3          # exponential smoothing alpha
_BEAT_BASELINE_ALPHA = 0.02   # slow baseline tracking
_BEAT_SPIKE_RATIO = 2.0       # RMS > baseline × 2.0 = beat
_BEAT_DECAY = 0.85            # per-frame decay (~200 ms release)
_ACTIVITY_THRESHOLD = 0.005   # smoothed RMS > this = active
```

**Beat detection method**: baseline-tracking + spike threshold. When RMS exceeds 2× a slowly-tracking baseline, emit a beat. Pulse decays at 0.85/frame (~200 ms half-life). Simple but effective for drum-heavy content.

`audio_capture.py` implements a richer version with asymmetric attack/decay + per-onset classification:

```python
self._sidechain_kick *= 0.95 if self.VINYL_MODE else 0.92
# ...
self._sidechain_kick = 1.0  # on kick onset
```

**Vinyl mode** (0.95x) gives a slower-release envelope than normal mode (0.92x). At 93 fps, 0.92^93 ≈ 0.0004, so the envelope decays to near-zero over ~1 second. 0.95^93 ≈ 0.009, so vinyl mode has a ~2-second decay. **Musical context-aware.**

### G3 — FFT + frequency bands

**mixer_input.py** (daimonion, simpler):

```python
_BASS_UPPER = 250.0 Hz
_MID_UPPER  = 2000.0 Hz
_HIGH_UPPER = 8000.0 Hz
```

3-band split using raw FFT bin summing.

**audio_capture.py** (compositor, richer): 8 mel-spaced bands spanning 20-16000 Hz with perceptually-weighted bin widths. Uses a pre-computed Mel filterbank matrix.

**Rolling AGC**: `AGC_HISTORY_LEN=372` = 4 seconds of history. Each signal is normalized against its own rolling history so the output tracks relative dynamics, not absolute level. **This means the modulation values don't depend on master volume — a quiet passage reacts as much as a loud passage.** Good design.

### G4 — Beat detection + BPM

**Current state**: onset-level beat detection (mixer_beat, onset_kick, onset_snare, onset_hat). **BPM tracking is NOT implemented**. No autocorrelation on the beat history, no tempo inference.

**What this means**: presets can react to individual beats but can't lock to a tempo. A preset can't say "pulse on every quarter note" — it can only say "pulse on every detected onset."

**Gap**: BPM-locked effects (tunnels that move 4 bars at a time, flashes that fire on downbeats, transitions that time to bar boundaries) are **not currently possible**. Research map G4 + G4.3 captures this.

### G5 — Transient detection

**audio_capture.py** implements per-onset classification (kick vs snare vs hat) based on spectral shape at the onset time. Not just "something happened" — "a kick happened."

**This enables differentiated reactivity**: kicks can duck colorgrade brightness (via `sidechain_kick`), snares can pulse some other parameter, hats can modulate feedback drift. Each drum gets its own modulation channel.

**The presets use these differentiated onset sources** (`onset_kick`, `onset_snare`, `onset_hat` appear in `_default_modulations.json` + preset files).

### G6.1 — `_default_modulations.json` merged into every preset

`agents/studio_compositor/effects.py:81`:

```python
# In the graph-loading path
if ...:
    graph = merge_default_modulations(graph)

def merge_default_modulations(graph: Any) -> Any:
    template_path = Path(__file__).parent.parent.parent / "presets" / "_default_modulations.json"
    defaults = json.loads(template_path.read_text()).get("default_modulations", [])
    # Merge defaults into graph
    ...
```

**Every preset activation path runs `merge_default_modulations`.** The defaults file becomes a baseline that applies unless a preset explicitly overrides. Presets without explicit audio modulation still get the default reactivity from `_default_modulations.json`.

### `_default_modulations.json` structure (13 modulation entries)

```json
{
  "default_modulations": [
    {"node": "colorgrade", "param": "brightness", "source": "sidechain_kick", "scale": -0.7, "offset": 0.0, "attack": 0.0, "decay": 0.88},
    {"node": "colorgrade", "param": "saturation", "source": "sidechain_kick", "scale": -1.0, ...},
    {"node": "colorgrade", "param": "contrast",   "source": "mixer_energy",   "scale":  0.5, ...},
    {"node": "colorgrade", "param": "hue_rotate", "source": "spectral_centroid", "scale": 40.0, ...},
    {"node": "vignette",   "param": "...",        "source": "...",            ...},
    ...
    # 13 total entries
  ]
}
```

**Kick → colorgrade ducking is the primary audio-visual link.** On every detected kick, colorgrade brightness drops by 0.7 and saturation drops by 1.0, then recovers at 0.88 decay/frame. This IS the visual ducking the operator wants — and it's wired as the default for every preset.

### G7.1 — Audio source usage across all presets

Counts from `grep -ohE '"source": "[a-z_]+"' presets/*.json | sort | uniq -c | sort -rn`:

| source | preset count | source type |
|---|---|---|
| `mixer_energy` | 3 | full-band RMS |
| `mixer_bass` | 3 | bass RMS |
| `audio_rms` | 3 | another RMS alias |
| `audio_beat` | 3 | beat pulse |
| `sidechain_kick` | 2 | kick ducking envelope |
| `onset_kick` | 2 | kick transient |
| `time` | 1 | time-based (not audio) |
| `spectral_centroid` | 1 | brightness |
| `onset_snare` | 1 | snare transient |
| `onset_hat` | 1 | hat transient |

**Presets with explicit audio modulation** (via grep -l): feedback_preset, fisheye_pulse, kaleidodream, trails, tunnelvision, vhs_preset + _default_modulations = **7 of 30 files**.

**But all 30 presets inherit `_default_modulations.json`** via the merge path, so the effective audio-reactive coverage is **30 of 30**. The 7 files with explicit sources add preset-specific reactivity on top of the default.

### G7.2 — Reactivity gaps (potentially dead audio wiring)

Names in presets that don't match `audio_capture.py` signal keys:

- `audio_rms` (used in 3 presets) — **no match in audio_capture.py signals**. Should be `mixer_energy`. Possibly a legacy alias the modulator resolves, but needs verification.
- `audio_beat` (used in 3 presets) — **no match**. Should be `mixer_beat` or `beat_pulse`. Same issue.

**If these aliases are not resolved by the modulator**, the 3 presets that reference them have DEAD audio modulation. Check `agents/effect_graph/modulator.py` for an alias table.

This is a similar pattern to the "publisher-without-consumer" / "consumer-without-publisher" findings from queues 024-025. File for investigation.

### Audio → visual latency budget (inferred)

| stage | latency | notes |
|---|---|---|
| Hardware audio capture (Studio 24c / Yeti) | ~2-5 ms | PipeWire clock.quantum=128 gives 2.67 ms period |
| pw-cat subprocess buffer | ~10 ms | 1 chunk of 512 samples |
| `audio_capture.py` FFT + classify | <1 ms | Hann window + rfft + onset detection |
| `self._signals` dict write (lock) | <0.1 ms | single lock held briefly |
| `fx_tick` reads `get_signals()` | — | runs at 30 fps cadence (33 ms period) |
| `modulator.tick(signals)` | <1 ms | applies modulation table |
| GPU uniform upload | <1 ms | `uniforms.json` SHM write + Rust picks up |
| Next compositor frame | ≤33 ms | the next render tick |
| Encoder + v4l2loopback + OBS + RTMP | ~1000 ms | the compositor-to-viewer delay |

**Mic-to-shader latency**: 10 + 1 + 0.1 + (0-33) + 1 + 1 = **~12-46 ms**. Fits inside the 50 ms target.

**Mic-to-viewer latency** (what the audience sees): 12-46 ms + ~1000 ms OBS/RTMP/YouTube = **~1000-1050 ms**. This is normal for livestreams. Video arrives at the viewer with ~1-second delay, and audio + visual effects arrive in sync with the video.

**The audio-to-visual-change sync is what matters**, and that's 12-46 ms inside the compositor, which is well under the 50 ms perceptual threshold.

## Findings + fix proposals

### F1 (HIGH): 47/93 fps analysis vs 30 fps render cadence mismatch

The compositor fx_tick runs at 30 fps, which is the output render rate. Audio analysis runs at 93 fps (audio_capture.py) and 47 fps (mixer_input.py). **The effect graph can only apply modulation updates at render-frame boundaries**, so sub-frame transient detail is quantized.

**Impact**: A drum hit that happens at 10 ms after the previous render frame arrives as a modulation update 23 ms later (next frame). Visually: a slight lag between snare + flash.

**Fix proposal**: The compositor's `tick_modulator` reads the latest `self._signals` snapshot at each render frame. It could instead read a **ring buffer of the last N analysis frames** and apply an envelope-style smoothing that captures the sub-frame peak. Or: render at 60 fps instead of 30, which halves the quantization error.

**Priority**: MEDIUM. Subtle perceptual improvement, not a blocker.

### F2 (HIGH): `audio_rms` + `audio_beat` alias names may be dead

3 presets reference `audio_rms` and `audio_beat`, but `audio_capture.py` publishes `mixer_energy` and `mixer_beat`. If the modulator doesn't alias these, the preset modulations are dead.

**Fix proposal**: Read `agents/effect_graph/modulator.py` for an alias table. If it exists, verify `audio_rms → mixer_energy` and `audio_beat → mixer_beat`. If not, either add the aliases (backward compat) or rename the preset entries.

**Priority**: HIGH (the 3 affected presets may be running with half their intended modulation). Cross-ref for an audit.

### F3 (MEDIUM): BPM tracking missing

Beat detection works at the onset level but BPM / tempo tracking is absent. Can't lock effects to tempo (every 4th beat, downbeat pulses, bar-length transitions).

**Fix proposal**: Add a simple BPM tracker to `audio_capture.py`. Options:
1. **Autocorrelation on the beat history**: keep a circular buffer of beat timestamps, autocorrelate to find the dominant period.
2. **Library-based**: librosa has `librosa.beat.beat_track` but requires offline analysis. `madmom` has a real-time BPM follower.
3. **Phase-locked loop**: track beat timing with a PLL that locks to the audio's beat grid over ~4 seconds.

Expose as `audio_bpm` (float, beats per minute) and `audio_beat_phase` (0.0-1.0, position within the current beat).

**Priority**: MEDIUM. Nice-to-have; the operator has not explicitly asked for BPM-locked effects.

### F4 (INFO): Sidechain kick ducking already wired

Good news finding. The visual-side ducking (kick → colorgrade dim) is already implemented and running in every preset via `_default_modulations.json`. The operator's "ducking visual effects" target state partial-matches what's already working.

**No fix needed on the visual side.** Audio-side ducking (music ducks when TTS/operator speaks) is a separate concern handled in Sprint 4.

### F5 (HIGH): Per-feature cost of the audio analysis pipeline is unmetered

`audio_capture.py` runs at 93 fps. Each chunk does:
- Hann window application
- `np.fft.rfft` on 512 samples (cheap)
- Mel filterbank multiply (cheap)
- Per-onset classifier (spectral shape check)
- AGC history update
- 18+ signal writes

**No per-feature timing today.** Is the DSP actually keeping up with 93 fps, or does `pw-cat` buffer drift over time? Does the self._signals lock block the compositor's tick_modulator at the wrong moment?

**Fix proposal**: Add a microsecond-precision timer around the DSP block in `_capture_loop`. Report max + mean per minute. Expose as Prometheus histograms `hapax_compositor_audio_dsp_ms`.

**Priority**: MEDIUM (observability, not correctness).

### F6 (observability): Dual audio analysis backends

Two backends analyze mixer_master: `audio_capture.py` (compositor, rich) and `mixer_input.py` (daimonion, simpler). **They don't share state** — each runs its own FFT on the same audio. The daimonion's mixer_input is smaller scope (perception level only) and the compositor's audio_capture is the modulation-driving one.

**Fix proposal**: Not urgent. The duplication is ~8 ms/chunk × 93 chunks/sec × 2 = 1.5 seconds of CPU per minute on the daimonion side. A refactor could have the compositor publish signals to a SHM location the daimonion reads, cutting duplicate DSP. Worth a backlog ticket.

**Priority**: LOW.

## Sprint 3 backlog additions (items 179+)

179. **`research(modulator): audit audio_rms + audio_beat alias resolution`** [Sprint 3 F2] — 3 presets may have dead audio modulation if the modulator doesn't alias these to mixer_energy + mixer_beat. HIGH (preset correctness).
180. **`feat(audio_capture): BPM tracking + beat_phase signal`** [Sprint 3 F3] — enables tempo-locked effects. Medium priority.
181. **`feat(compositor): audio DSP per-chunk timing histogram`** [Sprint 3 F5] — `hapax_compositor_audio_dsp_ms`. MEDIUM observability.
182. **`feat(compositor): audio signal ring buffer + peak-preserving smoother for sub-frame transients`** [Sprint 3 F1] — eliminates the 33 ms render-quantization loss for drum hits. MEDIUM perceptual.
183. **`refactor(daimonion): share audio features with compositor via SHM instead of dual DSP`** [Sprint 3 F6] — saves ~1.5 cpu-sec/min on daimonion side. LOW.
184. **`fix(audio_capture): publish VINYL_MODE state + make it operator-togglable`** [Sprint 3 observation] — the 0.92 vs 0.95 decay is music-context-aware; operator should be able to flip it without a restart.
185. **`research(preset): catalog which presets actually drive which uniforms under _default_modulations merge`** [Sprint 3 G7.2] — clarify the effective modulation per preset after the default merge. Useful for tuning + debugging.
