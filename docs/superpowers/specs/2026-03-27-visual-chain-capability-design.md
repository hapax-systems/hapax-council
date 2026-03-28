# Visual Chain Capability — Semantic Visual Expression via Impingement Activation

## Summary

Map the 6 wgpu visual techniques, compositor, and postprocess parameters to the same 9 semantic dimensions used by the vocal chain. Register as `CapabilityRecord` entries in Qdrant so the affordance pipeline can recruit visual expression alongside vocal expression from a single impingement.

## Motivation

The vocal chain maps 9 semantic dimensions (intensity, tension, diffusion, degradation, depth, pitch_displacement, temporal_distortion, spectral_color, coherence) to MIDI CC parameters on hardware effects processors. The visual surface has equivalent expressive range through its 6 wgpu techniques but lacks semantic addressing — parameters are only driven by stimmung ambient state, not by impingement activation.

By defining the same 9 dimensions with visual parameter targets, a single DMN escalation simultaneously recruits both vocal and visual expression through the existing affordance pipeline.

## Architecture

### Approach: Parallel Capability Class

A new `VisualChainCapability` alongside `VocalChainCapability`. Same 9 dimension names, same `Impingement` activation interface. `ParameterMapping` objects (analogous to `CCMapping`) target wgpu shader uniforms instead of MIDI CC numbers.

The affordance pipeline naturally recruits both `vocal_chain.*` and `visual_chain.*` capabilities when an impingement matches a dimension — cross-modal expression with no coupling between the two capability classes.

## Data Structures

```python
@dataclass(frozen=True)
class ParameterMapping:
    technique: str                          # "gradient", "rd", "physarum", "compositor", "postprocess"
    param: str                              # "brightness", "reaction_rate", "decay_rate", etc.
    breakpoints: list[tuple[float, float]]  # (activation_level [0.0-1.0], param_value)

@dataclass(frozen=True)
class VisualDimension:
    name: str                               # "visual_chain.intensity"
    description: str                        # same semantic text as vocal_chain equivalent
    parameter_mappings: list[ParameterMapping]
```

Breakpoint interpolation uses the same `piecewise_linear(level, breakpoints)` function as the vocal chain's `cc_value_from_level`.

## The 9 Dimensions and Their Visual Mappings

### 1. visual_chain.intensity
Physical energy expressed as visual brightness and saturation.

| Technique | Param | Breakpoints | Effect |
|-----------|-------|-------------|--------|
| gradient | brightness | (0.0, 0.0), (0.5, 0.15), (1.0, 0.40) | Additive brightness boost |
| compositor | opacity_rd | (0.0, 0.0), (0.5, 0.2), (1.0, 0.5) | RD pattern prominence |
| postprocess | vignette_strength | (0.0, 0.0), (1.0, -0.2) | Vignette reduction (opens up frame) |

### 2. visual_chain.tension
Timbral constriction expressed as pattern tightness and angular sharpness.

| Technique | Param | Breakpoints | Effect |
|-----------|-------|-------------|--------|
| rd | reaction_rate | (0.0, 0.0), (0.5, 0.02), (1.0, 0.06) | Tighter Turing patterns |
| wave | frequency | (0.0, 0.0), (0.5, 2.0), (1.0, 8.0) | Higher-frequency wave modulation |
| compositor | opacity_wave | (0.0, 0.0), (0.5, 0.15), (1.0, 0.4) | Wave layer prominence |

### 3. visual_chain.diffusion
Spatial scatter expressed as blur, trail spread, and softness.

| Technique | Param | Breakpoints | Effect |
|-----------|-------|-------------|--------|
| physarum | sensor_dist | (0.0, 0.0), (0.5, 5.0), (1.0, 20.0) | Wider agent sensing (dispersed trails) |
| rd | diffusion_a | (0.0, 0.0), (0.5, 0.1), (1.0, 0.4) | Higher diffusion spreads pattern |
| feedback | decay | (0.0, 0.0), (1.0, -0.02) | Slower feedback decay (more persistent blur) |

### 4. visual_chain.degradation
Signal corruption expressed as noise and pattern disruption.

| Technique | Param | Breakpoints | Effect |
|-----------|-------|-------------|--------|
| physarum | deposit_amount | (0.0, 0.0), (0.5, 3.0), (1.0, 10.0) | Heavier trail deposits (visual noise) |
| compositor | opacity_physarum | (0.0, 0.0), (0.5, 0.1), (1.0, 0.3) | Physarum layer prominence |
| postprocess | sediment_height | (0.0, 0.0), (0.5, 0.03), (1.0, 0.1) | Sediment strip grows |

### 5. visual_chain.depth
Reverberant space expressed as darkness and spatial recession.

| Technique | Param | Breakpoints | Effect |
|-----------|-------|-------------|--------|
| gradient | brightness | (0.0, 0.0), (1.0, -0.15) | Darkening (subtractive) |
| postprocess | vignette_strength | (0.0, 0.0), (0.5, 0.15), (1.0, 0.4) | Heavier vignette |
| compositor | opacity_feedback | (0.0, 0.0), (0.5, 0.15), (1.0, 0.35) | More feedback (spatial echo) |

### 6. visual_chain.pitch_displacement
Pitch shift expressed as hue rotation and color displacement.

| Technique | Param | Breakpoints | Effect |
|-----------|-------|-------------|--------|
| gradient | hue_offset | (0.0, 0.0), (0.5, 30.0), (1.0, 90.0) | Oklch hue rotation |
| feedback | hue_shift | (0.0, 0.0), (0.5, 2.0), (1.0, 8.0) | Feedback hue drift per frame |
| gradient | chroma_boost | (0.0, 0.0), (1.0, 0.06) | Additive chroma (more vivid shift) |

### 7. visual_chain.temporal_distortion
Time manipulation expressed as animation speed changes.

| Technique | Param | Breakpoints | Effect |
|-----------|-------|-------------|--------|
| gradient | speed | (0.0, 0.0), (0.5, -0.04), (1.0, 0.2) | Speed change (slow then fast) |
| rd | steps_per_frame | (0.0, 0.0), (0.5, -4), (1.0, 8) | Fewer/more RD iterations |
| physarum | move_speed | (0.0, 0.0), (0.5, -0.5), (1.0, 2.0) | Agent speed modulation |

### 8. visual_chain.spectral_color
Timbral brightness expressed as warmth and chroma.

| Technique | Param | Breakpoints | Effect |
|-----------|-------|-------------|--------|
| gradient | color_warmth | (0.0, 0.0), (0.5, 0.3), (1.0, 0.8) | Additive warmth shift |
| gradient | chroma_boost | (0.0, 0.0), (0.5, 0.03), (1.0, 0.08) | Saturation increase |
| postprocess | env_chroma_scale | (0.0, 0.0), (1.0, 0.5) | Environmental chroma boost |

### 9. visual_chain.coherence
Intelligibility axis expressed as pattern regularity (inverted = dissolution).

| Technique | Param | Breakpoints | Effect |
|-----------|-------|-------------|--------|
| gradient | turbulence | (0.0, 0.0), (0.5, 0.15), (1.0, 0.5) | Additive turbulence (less coherent) |
| rd | feed_rate | (0.0, 0.0), (0.5, 0.005), (1.0, 0.02) | Pattern destabilization |
| physarum | turn_speed | (0.0, 0.0), (0.5, 0.2), (1.0, 0.8) | Agents turn more (chaotic trails) |

## Activation Semantics

All breakpoint values are **additive deltas** applied on top of the stimmung-driven ambient baseline. At level 0.0, every mapping contributes 0.0 — no change from ambient state. This ensures the visual surface looks identical when no impingements are active.

Activation level [0.0–1.0] comes from `Impingement.strength` via the affordance pipeline, same as vocal chain.

## Hold and Decay

Same model as vocal chain:
- Activation persists at the set level until shifted by another impingement
- When no impingement sustains a dimension, level decays at `decay_rate` (default 0.02/s)
- Full decay from 1.0 to 0.0 takes ~50 seconds (gradual visual recovery)

## Integration

### Upstream: Qdrant Registration

9 `CapabilityRecord` entries registered at startup:
```python
VISUAL_CHAIN_RECORDS = [
    CapabilityRecord(
        name=dim.name,
        description=dim.description,
        daemon="visual_layer_aggregator",
        operational=OperationalProperties(latency_class="realtime"),
    )
    for dim in VISUAL_DIMENSIONS.values()
]
```

### Downstream: Parameter Delivery

`VisualChainCapability` writes activated state to `/dev/shm/hapax-visual/visual-chain-state.json`:
```json
{
  "levels": {
    "visual_chain.intensity": 0.6,
    "visual_chain.tension": 0.3
  },
  "params": {
    "gradient.brightness": 0.09,
    "gradient.speed": -0.016,
    "rd.reaction_rate": 0.012,
    "compositor.opacity_rd": 0.12,
    "postprocess.vignette_strength": -0.06
  },
  "timestamp": 1711583400.0
}
```

The `params` dict contains pre-computed additive deltas (breakpoint interpolation already applied). The wgpu `StateReader` reads this file, adds deltas to the stimmung-driven baselines, and passes combined values to `SmoothedParams.lerp_toward()`.

### Rust Side: StateReader Extension

`StateReader` gains one new shm file to poll:
```rust
const VISUAL_CHAIN_PATH: &str = "/dev/shm/hapax-visual/visual-chain-state.json";
```

`SmoothedParams` adds a `chain_deltas: HashMap<String, f32>` field. During `lerp_toward`, each technique's uniform is computed as `baseline + chain_delta` before smoothing.

## File Layout

| File | Purpose |
|------|---------|
| `agents/visual_chain.py` | `VisualDimension`, `ParameterMapping`, `VISUAL_DIMENSIONS` dict, `VISUAL_CHAIN_RECORDS` |
| `agents/visual_chain_capability.py` | `VisualChainCapability` class (activate, decay, write shm) |
| `src-tauri/src/visual/state.rs` | Extended `StateReader` + `SmoothedParams` for chain deltas |
| `tests/test_visual_chain.py` | Unit tests for breakpoint interpolation, dimension mapping, activation/decay |

## Testing

- Breakpoint interpolation: verify piecewise linear matches expected values at key points
- Dimension mapping: each of the 9 dimensions produces non-zero deltas at activation > 0
- Activation/decay: level rises on activate, decays at correct rate, reaches 0.0
- Shm output: JSON written to correct path with correct schema
- Integration: impingement with strength=0.5 on "intensity" produces expected parameter deltas
- No-activation baseline: all levels at 0.0 produces zero deltas (visual unchanged)
