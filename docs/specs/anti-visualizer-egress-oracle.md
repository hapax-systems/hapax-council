---
title: "Anti-visualizer egress oracle interface and contract"
date: 2026-05-21
author: epsilon
status: draft
cc_task: 202605181733-anti-audio-visual-p2-egress-oracle-design
authority_case: CASE-202605181733-ANTI-AU
parent_metric: docs/research/2026-04-20-oq02-anti-visualizer-metric.md
implementation: shared/governance/scrim_invariants/anti_visualizer.py
---

# Anti-Visualizer Egress Oracle Interface and Contract

## 1. Oracle interface

**Module**: `shared/governance/scrim_invariants/anti_visualizer.py`

### Input contract

```python
class AntiVisualizerOracle:
    def push(self, ts: float, observables: ScrimObservables, audio: AudioSignals) -> None: ...
    def evaluate(self) -> VisualizerScore: ...
    def should_dampen(self) -> bool: ...
    @property
    def coupling_gain(self) -> float: ...
```

| Method | Input | Frequency | Side effects |
|--------|-------|-----------|-------------|
| `push()` | Timestamp + frame observables + audio signals | ~30 Hz (per egress frame) | Appends to rolling deque (fixed capacity) |
| `evaluate()` | None (reads internal state) | On demand | None (pure read) |
| `should_dampen()` | None | Per-window (~every 5s) | Updates `_consec_failing`, `_dampen_active`, `_coupling_gain` |

### Output contract

```python
@dataclass(frozen=True)
class VisualizerScore:
    score: float           # S in [0, 1] — composite visualizer-register metric
    period_agreement: float  # 1 - |P_geom - P_audio| / P_audio
    phase_lock: float      # Kuramoto R in [0, 1]
    radial_on_beat: float  # mean radial symmetry at onset times
    spectral_ratio: float  # cosine similarity of geometry/audio spectra
    silence_guard: bool    # True when audio below MIN_AUDIO_RMS
```

`should_dampen() -> bool`: True when `score > S_THRESHOLD` for `HYSTERESIS_WINDOWS`
consecutive windows. Recovery when `score < S_THRESHOLD - RECOVERY_DELTA`.

`coupling_gain -> float`: Current gain in `[0.30, 1.00]`. Decays by 0.85× per
failing window, recovers by 1.05× per passing window. Never reaches zero.

### Exception contract

The oracle never raises exceptions to callers:
- Empty sample buffer → `VisualizerScore(score=0.0, silence_guard=True)`
- Audio below `MIN_AUDIO_RMS` → silence guard (score=0.0)
- Autocorrelation fails to find period → `period_agreement=0.0`
- Empty onset/peak arrays → `phase_lock=0.0`, `radial_on_beat=0.0`

All numpy operations are bounded by the fixed deque capacity (~150 samples at
30 fps × 5s window). No unbounded allocations.

## 2. Failure modes

### FM-1: False positive — legitimate reactive chain flagged

**Trigger**: A compositor preset with aggressive `mixer_energy → glow_strength`
binding produces transient radial symmetry correlated with audio onsets.

**Oracle behavior**: `score` rises above threshold transiently but the
hysteresis gate (`K=3` consecutive windows = 15s sustained) prevents damping
on transient spikes. If sustained, `coupling_gain` decays asymmetrically
(0.85× down, 1.05× up) so recovery is gradual — the chain adapts rather
than snapping between states.

**Mitigation**: Hysteresis window + asymmetric decay. Preset authors can
validate against the oracle's `evaluate()` output during authoring.

### FM-2: False negative — actual visualizer passes undetected

**Trigger**: A visualizer surface that modulates without phase-locking to
audio onsets (e.g., slow sine-wave brightness tied to audio RMS rather than
onset detection).

**Oracle behavior**: `period_agreement` may be high but `phase_lock` stays
low (Kuramoto R → 0), so the `α · agree · φ_lock` term contributes nothing.
Detection depends entirely on the `β · radial_on_beat` and `γ · spectral_ratio`
terms.

**Mitigation**: The β=0.30 weight on radial-on-beat catches MilkDrop-style
radial blooms even without phase lock. Truly non-periodic visualizers (no
onset correlation, no radial symmetry) are architecturally unlikely given
the audio reactivity bus design.

## 3. Integration points

### Upstream: metric computation → oracle

```
egress frame → _DefaultFrameProjector.project() → ScrimObservables
audio reactivity bus → AudioSignals (shared/audio_reactivity.py)
  ↓
AntiVisualizerOracle.push(ts, observables, audio)
  ↓
AntiVisualizerOracle.should_dampen()
  ↓
coupling_gain → agents/effect_graph/modulator.py (audio→geometry gain)
```

The oracle sits between the compositor's egress probe and the modulator's
gain control. It reads from two sources (frame projector + audio bus) and
writes to one output (coupling gain).

### Downstream: oracle → enforcement

The `coupling_gain` property is the enforcement output. The downstream
consumer (`agents/effect_graph/modulator.py`) multiplies all audio→geometry
bindings by this gain. At floor (0.30), audio still modulates the surface
but cannot drive frame-spatial structure that phase-locks to onsets.

**No circular dependency**: The oracle reads egress frames and audio signals
(both read-only). It writes only `coupling_gain`, which the modulator reads.
The modulator's gain change affects future frames, which the oracle will
evaluate — but this is a stable feedback loop (gain floor prevents
oscillation to zero).

### Calibration integration

```python
def calibrate(
    *,
    negative_fixtures: list[VisualizerScore],
    positive_fixtures: list[VisualizerScore],
    out_path: Path | None = None,
) -> float
```

Produces `S_THRESHOLD` per the metric spec §3. Writes calibration trace to
`presets/scrim_invariants/calibration.json` for audit. Re-calibrate on every
new shipped preset family or shader node.

## 4. Current implementation status

| Component | Status | Tests |
|-----------|--------|-------|
| `AntiVisualizerOracle` class | Implemented (577 lines) | 35 tests, 95% coverage |
| `_DefaultFrameProjector` | Implemented | Covered by oracle tests |
| `calibrate()` | Implemented | Covered |
| Modulator integration | Not wired | Downstream task |
| Egress probe wiring | Not wired | Downstream task |
