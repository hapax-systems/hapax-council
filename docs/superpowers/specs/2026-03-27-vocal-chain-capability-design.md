# Vocal Chain Capability — Semantic MIDI Affordances for Speech Modulation

## Goal

Index MIDI processing parameters on the Evil Pet and Torso S-4 as semantic affordances in Qdrant so the impingement cascade can recruit expressive vocal modulation the same way it recruits speech production or fortress governance — through semantic similarity, not explicit mapping.

## Architecture

### Signal Flow

```
Impingement (stimmung shift, conversational state, DMN evaluation)
  ↓
AffordancePipeline.select(impingement)
  ↓
Qdrant "affordances" collection returns matching dimension(s)
  e.g., vocal_chain.tension (similarity 0.74), vocal_chain.intensity (0.68)
  ↓
VocalChainCapability.activate(impingement, level)
  ↓
Dimension activation levels updated (hold with decay)
  ↓
MidiOutput translates levels → CC values via mapping curves
  ↓
MIDI CC messages → Evil Pet (ch1) + S-4 (ch2)
```

### Components

**1. Nine `CapabilityRecord`s in Qdrant** — one per semantic dimension. Each has a function-free description (McCaffrey 2012) that captures the expressive/speech-act character, not the technical MIDI implementation. Retrieval sorts them independently: an arousal spike recruits `intensity` and `tension` but not `degradation`.

**2. `VocalChainCapability`** — single class implementing the `Capability` protocol. Manages the activation state of all 9 dimensions. Unlike one-shot capabilities (speech, fortress), this holds state continuously — activation sets dimension levels that persist until shifted by another impingement or decayed by a timer.

**3. `MidiOutput`** — thin MIDI sender using `mido.open_output()`. Translates dimension activation levels (0.0–1.0) to CC values on configured channels. Stateless — receives (channel, cc, value) tuples and sends them.

**4. Dimension-to-CC mapping** — each dimension maps to 2–6 CC parameters across both devices. The mapping curves follow the transparent→noise classification: level 0.0 = transparent (parameter at safe center), level 1.0 = noise (parameter at extreme). Curves are piecewise linear defined by the classification breakpoints.

### Semantic Dimensions

Each dimension is an independent affordance with its own Qdrant record. Descriptions are written for embedding similarity, not human documentation.

| Dimension | Description (indexed in Qdrant) | Evil Pet CCs | S-4 CCs |
|---|---|---|---|
| `vocal_chain.intensity` | "Increases vocal energy and density. Speech becomes louder, more present, more forceful. Distinct from emotional valence — pure physical energy." | Mix(40), Grains(46) | Mosaic Wet(69), Rate(63) |
| `vocal_chain.tension` | "Constricts vocal timbre. Speech sounds strained, tight, forced through resistance. Harmonics sharpen, resonance builds. Distinct from volume." | Filter Res(71), Saturator(39) | Ring Res(79), Deform Drive(94) |
| `vocal_chain.diffusion` | "Scatters vocal output across spatial field. Speech becomes ambient, sourceless, environmental. Words dissolve into texture at high levels." | Spread(42), Cloud(43) | Spray(67), Warp(66) |
| `vocal_chain.degradation` | "Corrupts vocal signal. Speech fractures into digital artifacts, broken transmission, static. System malfunction expressed through voice." | Sat Type→Crush(84), Sat Amt(39) | Crush(96), Noise(98) |
| `vocal_chain.depth` | "Places voice in reverberant space. Distant, cathedral-like, submerged. Speech recedes from foreground without losing content at low levels." | Reverb(91), Tail(93) | Vast Reverb(112), Size(113) |
| `vocal_chain.pitch_displacement` | "Shifts vocal pitch away from natural register. Higher, lower, or unstable. Uncanny displacement without volume or timbre change." | Pitch(44) | Mosaic Pitch(62), Pattern(68) |
| `vocal_chain.temporal_distortion` | "Stretches, freezes, or stutters speech in time. Words elongate, fragment, or loop. Temporal continuity breaks down." | Size(50) | Rate(63), Contour(65) |
| `vocal_chain.spectral_color` | "Shifts vocal brightness and metallicity. Dark, bright, hollow, metallic. Changes tonal character without changing pitch or volume." | Filter Freq(70), Filter Type(80) | Ring Tone(83), Tilt(88), Scale(84) |
| `vocal_chain.coherence` | "Controls intelligibility of speech. Master axis from clear human voice to pure abstract texture. Affects overall processing depth." | Mix(40) | Mosaic Wet(69), Ring Wet(85) |

### Activation Model

**Hold-and-decay**, not one-shot:

- `activate(impingement, level)` sets the target level for matched dimension(s).
- Dimensions interpolate toward target over 500ms (avoid sudden CC jumps that cause audio clicks).
- Without new impingements, dimensions decay toward 0.0 (transparent) at a configurable rate (default: 0.02/s, reaching transparent in ~50s from full activation).
- Inhibition-of-return is **disabled** for vocal chain affordances — stimmung should continuously modulate voice, not get blocked after one activation.
- Multiple dimensions can be active simultaneously at different levels.

**Level → CC mapping:**

Each CC parameter has a mapping curve defined by 5 breakpoints from the classification tables:

```
level 0.00 → transparent  (CC at safe center)
level 0.25 → coloring     (subtle change)
level 0.50 → expressive   (obviously processed, still intelligible)
level 0.75 → transformative (partially intelligible)
level 1.00 → noise        (sound design territory)
```

Mapping is piecewise linear interpolation between breakpoints. Each CC has its own curve (some parameters have asymmetric or non-linear safe zones). Breakpoints derived from the MIDI classification tables produced during research.

### MIDI Output

**New module: `agents/hapax_voice/midi_output.py`**

- Wraps `mido.open_output()` with lazy initialization.
- Configured via `VoiceConfig`: `midi_output_port` (default: empty string = first available), `midi_evil_pet_channel` (default: 0, 0-indexed), `midi_s4_channel` (default: 1).
- Thread-safe: called from capability activation which may run in the impingement consumer coroutine.
- Sends CC messages immediately (no beat alignment — these are slow parameter sweeps at sentence/clause granularity, not note events).
- Graceful degradation: if no MIDI output available, log warning and skip. Vocal chain is enhancement, not critical path.

### Registration Pattern

Follows fortress daemon pattern exactly:

```python
# In voice daemon startup:
from agents.hapax_voice.vocal_chain import VocalChainCapability, VOCAL_CHAIN_RECORDS

self._vocal_chain = VocalChainCapability(midi_output=self._midi_output)

for record in VOCAL_CHAIN_RECORDS:
    self._affordance_pipeline.index_capability(record)
```

No interrupt tokens registered — vocal chain is never safety-critical. Pure semantic retrieval.

### File Structure

| File | Responsibility |
|---|---|
| `agents/hapax_voice/vocal_chain.py` | `VocalChainCapability` class, 9 dimension definitions with CC mappings, `VOCAL_CHAIN_RECORDS` list of `CapabilityRecord`s, hold-and-decay state management |
| `agents/hapax_voice/midi_output.py` | `MidiOutput` class — thin mido wrapper, lazy port init, graceful degradation |
| `agents/hapax_voice/config.py` | New fields: `midi_output_port`, `midi_evil_pet_channel`, `midi_s4_channel` |
| `tests/test_vocal_chain.py` | Capability tests: dimension activation, decay over time, CC mapping curves, dimension independence, multi-dimension interaction |
| `tests/test_midi_output.py` | MIDI output tests: CC sending, channel routing, port unavailable graceful skip |

### Scope Boundary

This spec covers the vocal chain capability and MIDI output infrastructure. It does NOT cover:

- **Impingement consumer loop** — the background coroutine that polls `/dev/shm/hapax-dmn/impingements.jsonl` and broadcasts to capabilities. That's cascade integration (separate spec, `2026-03-25-cascade-integration-specs.md`). The vocal chain registers itself and waits for broadcast like any other capability.
- **New impingement types** — rides existing stimmung, DMN, and sensor impingements.
- **Beat-aligned MIDI** — not needed for slow parameter sweeps. The existing MIDI clock infrastructure (OXI One input) is unrelated.
- **TTS pipeline changes** — the vocal chain processes audio downstream of PyAudio output, external to the software.

### Dependencies

- `mido>=1.3.0` and `python-rtmidi>=1.5.0` — already in pyproject.toml.
- Qdrant `affordances` collection — already exists (768-dim, Cosine).
- `AffordancePipeline.index_capability()` — already works (used by speech + fortress).
- `Capability` protocol — already defined in `shared/capability_registry.py`.
- `CapabilityRecord` / `OperationalProperties` — already defined in `shared/affordance.py`.
