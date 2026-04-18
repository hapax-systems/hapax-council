# 24c Global Reactivity Source Contract — Design Spec

**Date:** 2026-04-18
**Task:** CVS #149
**Status:** Stub (design)
**Register:** scientific, neutral
**Related:** #134 (audio pathways audit), #148 (reactivity sync/granularity), #145 (24c ducking), MEMORY `project_contact_mic_wired`

---

## 1. Goal

Generalize audio reactivity so that **any** signal patched into the PreSonus Studio 24c can drive shader modulation without bespoke per-source wiring.

> Operator, 2026-04-04T23:25Z: *"not sure where to shove it in the project sequence, but we need to enable effect reactivity to anything being pumped into the 24c."*

The 24c is an 8-in interface (2 combo + 6 line). Today, only one channel reaches the shader uniform bridge; seven do not.

---

## 2. Current state asymmetry

Two consumers run DSP against 24c virtual sources, and they are not symmetric:

| Source (PipeWire virtual) | 24c channel | DSP consumer | Reaches shader? |
|---|---|---|---|
| `mixer_master` | **FR / Input 2** | `agents/studio_compositor/audio_capture.py::CompositorAudioCapture` — 93 fps FFT, 8 mel bands, spectral flux onset, kick/snare/hat, **18+ signals** | **Yes** — 13 bindings in `presets/_default_modulations.json` (mixer_energy, mixer_bass/mid/high, mixer_beat, sidechain_kick, onset_kick/snare/hat, spectral_centroid/flatness/rolloff, zero_crossing_rate, 8 mel bands) |
| `contact_mic` (Cortado) | **FL / Input 1** | `agents/hapax_daimonion/backends/contact_mic.py` — 16 kHz RMS, centroid, onset rate, autocorrelation, gesture classify | **No** — signals go to `twitch_director` (preset bias) + Bayesian presence engine only |
| Inputs 3–8 (rear line) | — | **none** (no PipeWire loopback defined) | **No** |

Inference for Input 2 content (no explicit route spec found): the operator's external mixer bus (Evil Pet / S-4 / turntable / MPC pads) summed into 24c Input 2. See MEMORY `project_vocal_chain` + `project_contact_mic_wired`.

---

## 3. Documentation correction (fold into #134)

The live PipeWire config at `~/.config/pipewire/pipewire.conf.d/10-contact-mic.conf` splits the 24c stereo capture into:
- **FL / Input 1 → `contact_mic`** (Cortado MKIII)
- **FR / Input 2 → `mixer_master`** (external mixer bus)

This **contradicts** two stale documents, both of which must be corrected as part of #134:

- `docs/superpowers/specs/2026-03-25-contact-mic-integration.md` §"Hardware Setup" — says Cortado → Input 2 / FR (wrong).
- `docs/hardware/cable-inventory.md` — says Yeti → Input 1, Cortado → Input 2 (wrong).

The live PipeWire config is authoritative. #134's topology diagram and channel inventory must be updated to match; this spec (#149) depends on that correction landing first.

---

## 4. Contract shape

### 4.1 Protocol

```python
# shared/audio_reactivity.py (new)
from typing import Protocol, Literal

class AudioReactivitySource(Protocol):
    name: str                              # "mixer", "desk", "input3", "guitar", ...
    pw_target: str                         # PipeWire node name (virtual source)
    channel_role: Literal["FL", "FR", "mono"]
    rate: int                              # sample rate (Hz)
    chunk: int                             # buffer size (samples)

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def get_signals(self) -> dict[str, float]: ...   # keys pre-namespaced
```

### 4.2 Signal namespace

All features carry a source prefix. No more unprefixed globals.

```
mixer.energy, mixer.bass, mixer.beat, mixer.onset_kick, mixer.mel_sub_bass, ...
desk.energy,  desk.onset_rate, desk.tap_gesture, ...
input3.energy, input3.onset_rate, ...
```

Legacy unprefixed names (`audio_rms`, `audio_beat`, `mixer_energy`, `onset_kick`, …) become **aliases** that resolve to `mixer.*` via the registry. Kills the dead-alias debt from Sprint 3 F2 in the same move.

### 4.3 Registry

```python
# agents/studio_compositor/audio_registry.py (new)
class AudioReactivityRegistry:
    def register(self, source: AudioReactivitySource) -> None: ...
    def unregister(self, name: str) -> None: ...
    def snapshot(self) -> dict[str, float]: ...    # merged namespaced dict
    def sources(self) -> list[AudioReactivitySource]: ...
```

`fx_tick` reads `registry.snapshot()` each frame instead of calling one capture directly. The modulator resolves `"source": "desk.onset_rate"` or `"source": "mixer.onset_kick"` uniformly; preset bindings are the only place a channel is named.

---

## 5. Implementation phasing

### Phase A — refactor only (no behavior change)
Extract the mel-FFT DSP from `agents/studio_compositor/audio_capture.py` into a shared `MelFFTReactivitySource` implementing the Protocol. Introduce the registry. Migrate `mixer_master` onto the registry path. Namespace its features as `mixer.*` with legacy aliases. **Preset bindings and shader output are byte-identical.**

### Phase B — Cortado to the shader bridge
Wrap `agents/hapax_daimonion/backends/contact_mic.py` DSP as a second `AudioReactivitySource` named `desk`. Expose `desk.energy`, `desk.onset_rate`, `desk.tap_gesture` as preset-bindable. Add 2–3 default `desk.*` bindings to `presets/_default_modulations.json`. This is the first moment Cortado drives visuals.

### Phase C — auto-discover 24c channels 3–8
Enumerate the 24c via `pw-dump`. For each unmapped channel, generate a mono loopback (same pattern as `10-contact-mic.conf`) and register a `MelFFTReactivitySource`. Operator patches a guitar into Input 3 → `input3.*` is live in presets within one `pipewire --reload`.

### Phase D — dedupe daimonion's duplicate DSP
Retire `agents/hapax_daimonion/backends/mixer_input.py`'s independent FFT pipeline; consume registry snapshot instead (closes Sprint 3 F6 dual-DSP duplication). CPAL gain reader reads from registry.

---

## 6. Dependencies

### 6.1 #148 (reactivity sync/granularity) — **must ship first**

#148 fixes the 33 ms render-quantization loss (2 hr wall-clock peak-hold on the `mixer_master` path: ring buffer + peak-preserving smoother, or 60 fps render). That fix applies to **one** `MelFFTReactivitySource`. Under #149 Phase A it applies to **every** registered source for free. Sequencing #148 before #149 means we validate the granularity fix against a known-good preset once, then multiply it across N sources with no extra validation cost.

### 6.2 #134 (audio pathways audit) — channel ground-truth correction

#134 owns 24c topology. The §3 correction (Cortado on FL, not FR) must land in #134's inventory + topology diagram before #149 Phase A, so the first-principles "which channel is which source" question has a single authoritative answer. #149 references #134 for topology; #134 references #149 for reactivity. Clean split, no overlap.

Recommended order: **#134 correction → #148 granularity fix → #149 Phase A → B → C → D**.

---

## 7. File-level plan

### Phase A
| File | Action |
|---|---|
| `shared/audio_reactivity.py` | Create — Protocol + `ReactivitySourceSpec` dataclass |
| `agents/studio_compositor/audio_registry.py` | Create — registry + legacy alias table |
| `agents/studio_compositor/audio_capture.py` | Extract `MelFFTReactivitySource`; keep thin `CompositorAudioCapture` shim that registers one instance |
| `agents/studio_compositor/fx_tick.py` | Read `registry.snapshot()`; no preset changes |
| `agents/effect_graph/modulator.py` | Accept namespaced keys; resolve legacy aliases via registry |
| `tests/studio_compositor/test_audio_registry.py` | New — register / unregister / snapshot / alias / namespace collision |

### Phase B
| File | Action |
|---|---|
| `agents/hapax_daimonion/backends/contact_mic.py` | Implement `AudioReactivitySource` (or wrap existing class) |
| `agents/studio_compositor/main.py` (or composition root) | Register `desk` source alongside `mixer` |
| `presets/_default_modulations.json` | Add 2–3 `desk.*` bindings |
| `tests/daimonion/test_contact_mic_as_source.py` | New |

### Phase C
| File | Action |
|---|---|
| `shared/pipewire_discovery.py` | New — enumerate 24c channels via `pw-dump` |
| `config/pipewire/10-24c-loopbacks.conf` (generated) | New — per-channel mono loopbacks |
| `agents/studio_compositor/audio_registry.py` | Auto-register on discovery |

### Phase D
| File | Action |
|---|---|
| `agents/hapax_daimonion/backends/mixer_input.py` | Delete; replace with registry read |
| `agents/hapax_daimonion/cpal_gain.py` (or equivalent) | Read registry snapshot |

---

## 8. Test strategy

- **Phase A (refactor):** golden-output test — record one minute of mel-FFT signals from `mixer_master` before refactor, replay same audio post-refactor, assert byte-identical signal dict (within float tolerance).
- **Phase A (registry):** unit tests for register / unregister / snapshot merge / alias resolution / namespace collision (two sources both claiming `mixer.*` → error).
- **Phase B:** integration test that patches a known waveform into `contact_mic`, asserts `desk.onset_rate` appears in registry snapshot and drives a preset-bound uniform.
- **Phase C:** mock `pw-dump` output, assert expected sources materialize with correct `pw_target` and `channel_role`.
- **Phase D:** assert daimonion gain reader produces identical values pre/post dedup against a recorded fixture.

---

## 9. Rollback plan

- **Phase A:** revert the four-file PR. Registry disappears, `CompositorAudioCapture` returns to direct-read. Zero state-on-disk.
- **Phase B:** remove the `desk.*` bindings from `presets/_default_modulations.json`; Cortado goes back to perception-only. Contract remains; operator can re-bind any time.
- **Phase C:** delete generated `10-24c-loopbacks.conf`, `pipewire --reload`. Discovery module idle; inputs 3–8 revert to no-op.
- **Phase D:** restore `mixer_input.py` from git; daimonion returns to dual-DSP. (Cost: CPU, not correctness.)

All phases are independently revertable; none mutate persisted state outside generated config.

---

## 10. Open questions

- **Q1.** What is actually on 24c Input 2 (the FR / `mixer_master` source)? No explicit route spec in-repo. Inferred from MEMORY `project_vocal_chain` + `project_contact_mic_wired`: the operator's external mixer bus carrying Evil Pet + S-4 + turntable + MPC. Confirmation needed for #134's inventory.
- **Q2.** Registry home: `shared/audio_reactivity.py` (contract) + per-service registry instance (no IPC), or compositor-owned with daimonion as a consumer? Default: shared contract, per-process registry.
- **Q3.** Per-input loopbacks vs per-consumer channel selection on the stereo node? Per-input loopback matches the existing `contact_mic` / `mixer_master` pattern and keeps DSP cost one-pass-per-channel; default to that.
- **Q4.** MIDI-reactive sources (OXI One clock, CC impingements from `project_vocal_chain`) — same contract? Out of scope for #149; flag follow-on `GlobalReactivitySource` covering audio + MIDI.
- **Q5.** Blue Yeti (non-24c) as a reactivity source? Operator directive is "into the 24c". Default: no — Yeti stays on the VAD/perception path.

---

## 11. References

- `~/.config/pipewire/pipewire.conf.d/10-contact-mic.conf` — **authoritative channel assignment**
- `agents/studio_compositor/audio_capture.py` — reference DSP to extract
- `agents/hapax_daimonion/backends/contact_mic.py` — Phase B source
- `agents/hapax_daimonion/backends/mixer_input.py` — Phase D dedup target
- `presets/_default_modulations.json` — 13 default bindings
- `docs/superpowers/specs/2026-04-18-audio-pathways-audit-design.md` — #134 spec
- `docs/research/2026-04-13/livestream-performance-map/sprint-3/sprint-3-audio-reactivity.md` — F1/F2/F6 findings
- `docs/research/2026-04-14-audio-path-baseline.md` — DSP histograms, PipeWire clock
- `/tmp/cvs-research-149.md` — source research for this spec
