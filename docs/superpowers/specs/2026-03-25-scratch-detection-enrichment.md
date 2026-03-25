# Scratch Detection Enrichment

**Date:** 2026-03-25
**Status:** Design approved
**Depends on:** Contact Microphone Integration (PR #332)

## Summary

Add vinyl scratch detection to the ContactMicBackend and wire it through the full perception pipeline so downstream consumers (flow state, camera profiles, OBS governance, audio processor) can react to turntable activity. The contact mic captures the back-and-forth oscillation of vinyl scratching as a continuous amplitude-modulated vibration through the desk — a signature no other sensor in the system can detect.

## The Signal

Vinyl scratching produces a **quasi-periodic oscillation at 2-20 Hz** in the contact mic's amplitude envelope. This is fundamentally different from every other desk activity:

- **Typing:** Discrete impulses, stochastic timing, ~10-30% duty cycle
- **Pad hits (SP-404/MPC):** Discrete impulses, rhythmic, ~5-15% duty cycle
- **Drumming:** Discrete hits with sustained resonance, ~20-40% duty cycle
- **Scratching:** Continuous oscillation, ~100% duty cycle, sinusoidal AM envelope

The **amplitude envelope autocorrelation** is the single strongest discriminator. Scratching shows a strong periodic peak at 50-500ms lag (corresponding to 2-20 Hz gesture rate); nothing else on a producer's desk produces this pattern.

## Component 1: Scratch Detection DSP

**File:** `agents/hapax_voice/backends/contact_mic.py`

### Algorithm

Add a new pure function `_compute_envelope_autocorrelation()` and extend `_classify_activity()` with a `"scratching"` classification.

1. Maintain a ring buffer of recent RMS energy values (~1-2 seconds, ~30-60 frames at 30ms/frame)
2. Every 4th frame (same cadence as spectral centroid), compute normalized autocorrelation of the energy buffer
3. Find the peak autocorrelation value in the 50-500ms lag range (lags 2-16 at 30ms frame rate)
4. If peak autocorrelation > threshold (0.4) AND energy is above idle threshold → `"scratching"`

### New Constants

```python
_SCRATCH_AUTOCORR_THRESHOLD = 0.4  # normalized autocorrelation peak required
_SCRATCH_MIN_ENERGY = 0.02  # minimum energy for scratch detection
_SCRATCH_MIN_LAG = 2  # ~64ms at 32ms frames (corresponds to ~16 Hz)
_SCRATCH_MAX_LAG = 16  # ~512ms at 32ms frames (corresponds to ~2 Hz)
_ENERGY_BUFFER_SIZE = 60  # ~1.9 seconds of energy history at 32ms frames
```

### Updated Classification Logic

```python
def _classify_activity(
    energy: float,
    onset_rate: float,
    centroid: float,
    autocorr_peak: float,
) -> str:
    if energy < _IDLE_THRESHOLD:
        return "idle"
    if autocorr_peak >= _SCRATCH_AUTOCORR_THRESHOLD and energy >= _SCRATCH_MIN_ENERGY:
        return "scratching"
    if energy >= _DRUMMING_MIN_ENERGY and centroid < _DRUMMING_MAX_CENTROID:
        return "drumming"
    if onset_rate >= _TYPING_MIN_ONSET_RATE and energy < _DRUMMING_MIN_ENERGY:
        return "typing"
    if onset_rate >= _TAPPING_MIN_ONSET_RATE:
        return "tapping"
    return "idle"
```

Scratching is checked **before** drumming because both can have high energy, but scratching's autocorrelation signature is unambiguous. Drumming has impulsive onsets that produce weak or no autocorrelation peak in the envelope.

### Capture Loop Changes

Add before the while loop:

```python
energy_buffer: deque[float] = deque(maxlen=_ENERGY_BUFFER_SIZE)
autocorr_peak = 0.0
```

Inside the loop, append to energy buffer every frame:

```python
energy_buffer.append(smoothed_energy)
```

Every 4th frame (alongside centroid), compute autocorrelation:

```python
if frame_count % 4 == 0:
    centroid = _compute_spectral_centroid(data)
    autocorr_peak = _compute_envelope_autocorrelation(energy_buffer)
```

Update the classification call to pass the new argument:

```python
activity = _classify_activity(smoothed_energy, onset_rate, centroid, autocorr_peak)
```

All existing tests must be updated to pass `autocorr_peak=0.0` as a keyword argument. New tests add cases with `autocorr_peak=0.5` for scratch verification.

### CPU Budget

Autocorrelation of a 60-element float array is trivial — ~0.01ms via NumPy `np.correlate()`. Well within the FAST tier <10ms budget, even at the 4-frame cadence.

## Component 2: Perception State Export

**File:** `agents/hapax_voice/_perception_state_writer.py`

The perception state writer does **not** automatically export new behaviors. Each must be explicitly added to the state dict (line ~322). Add four lines:

```python
# Contact mic (desk vibration sensing)
"desk_activity": str(_bval("desk_activity", "")),
"desk_energy": _safe_float(_bval("desk_energy", 0.0)),
"desk_onset_rate": _safe_float(_bval("desk_onset_rate", 0.0)),
"desk_tap_gesture": str(_bval("desk_tap_gesture", "none")),
```

This exports all four contact mic behaviors, not just `desk_activity`. Needed for downstream consumers.

**Note:** This wiring was missing from the original contact mic integration (PR #332). It is a prerequisite — without it, no downstream consumer can see desk activity.

## Component 3: OverlayData Extension

**File:** `agents/studio_compositor.py`

Add `desk_activity` to the `OverlayData` model (line ~303):

```python
class OverlayData(BaseModel):
    production_activity: str = ""
    music_genre: str = ""
    desk_activity: str = ""  # NEW: from ContactMicBackend
    # ... rest unchanged
```

Once in the model, camera profile conditions like `condition="desk_activity=scratching"` work automatically via `_condition_matches()` which uses `getattr()`.

## Component 4: Flow State Integration

**File:** `agents/hapax_voice/_perception_state_writer.py` (lines 248-283)

Flow state is computed **inline in the perception state writer**, NOT via `FlowStateMachine` (which exists in `shared/flow_state.py` but is unused in production). The writer computes `flow_score = base_flow + flow_modifier` where modifiers come from gaze, posture, emotion, gesture, and audio signals.

Add `desk_activity` as a new flow modifier. After the existing modifier block (line ~275) and before the `flow_score = min(1.0, ...)` computation (line 277), add:

```python
    # Desk activity bonus (structure-borne instrument engagement)
    desk_act = str(_bval("desk_activity", ""))
    if desk_act in ("scratching", "drumming"):
        flow_modifier += 0.15  # strong physical engagement with instruments
    elif desk_act == "tapping":
        flow_modifier += 0.05  # moderate engagement (pad playing)
```

Scratching and drumming get a 0.15 boost — these are unambiguously intentional musical activities. Typing gets nothing (it's work, not production). Tapping gets 0.05 (pad playing is production-adjacent).

**No changes to `shared/flow_state.py`.** The `FlowStateMachine` class is not used in production and does not need modification.

## Component 5: Camera Profile for Scratching

**File:** `~/.config/hapax-compositor/profiles.yaml` (or wherever profiles are configured)

Add a new profile entry:

```yaml
- name: scratching-focus
  condition: "desk_activity=scratching"
  priority: 10
  cameras: {}  # Use default camera settings — this profile's value is in triggering, not V4L2
```

This is a config-only change. The compositor evaluates profiles every 10 seconds via `_evaluate_camera_profile()`. When `desk_activity=scratching` appears in `perception-state.json` and `OverlayData`, this profile activates.

Initial implementation: profile triggers but uses default cameras. Future: add turntable camera-specific V4L2 settings once the camera inventory supports it.

## Component 6: Audio Processor Source Tagging

No code change needed. The audio processor already tags contact mic recordings with `source: "contact_mic"`. The CLAP classifier running on those FLAC files will naturally produce different classifications for scratch sessions vs silence. The `desk_activity` behavior (exported to perception-state.json) can be correlated with recording timestamps for richer RAG metadata, but this is a future enhancement — not needed now.

## File Inventory

| Action | Path | Scope |
|--------|------|-------|
| Edit | `agents/hapax_voice/backends/contact_mic.py` | Add autocorrelation, update classify_activity signature, "scratching" class |
| Edit | `tests/hapax_voice/test_contact_mic_backend.py` | Add scratch detection tests, update classify_activity call sites |
| Edit | `agents/hapax_voice/_perception_state_writer.py:322` | Add 4 desk_* behavior exports |
| Edit | `agents/studio_compositor.py:303` | Add desk_activity to OverlayData |
| Edit | `agents/hapax_voice/_perception_state_writer.py:275` | Add desk_activity flow modifier (scratching/drumming/tapping) |
| Config | `~/.config/hapax-compositor/profiles.yaml` | Add scratching-focus profile |

**Not touched:** `perception.py`, `EnvironmentState`, `multi_mic.py`, `__main__.py` backend registration (already done), `audio_processor.py`

## Testing

| Component | Method |
|-----------|--------|
| Autocorrelation function | Unit test with synthetic oscillating envelope vs flat envelope |
| Scratch classification | Unit test: high autocorr + energy → "scratching" |
| Classification priority | Unit test: scratching checked before drumming |
| Perception state export | Unit test: verify desk_* fields appear in state dict |
| OverlayData | Unit test: desk_activity field parsed from JSON |
| Flow state scoring | Unit test: desk_activity="scratching" boosts score by 0.15 |
| End-to-end | Manual: scratch vinyl, check perception-state.json shows desk_activity=scratching |

## Constraints

- Autocorrelation requires ~1.9 seconds of energy history (60 frames × 32ms) before producing meaningful results. First ~2 seconds after mic starts will show `"idle"`.
- The autocorrelation threshold (0.4) may need tuning with real scratch data. Start conservative (higher threshold = fewer false positives) and lower as needed.
- Camera profile switching has 10-second evaluation cadence. Scratch detection is near-instant but profile changes lag.
- Flow state has 5-minute hysteresis. A short scratch session won't trigger flow transitions — sustained scratching will.
