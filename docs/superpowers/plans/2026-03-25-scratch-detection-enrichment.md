# Scratch Detection Enrichment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add vinyl scratch detection to the ContactMicBackend and wire `desk_activity` through the full perception pipeline so downstream consumers (flow state, camera profiles, OBS) react to turntable activity.

**Architecture:** Amplitude envelope autocorrelation distinguishes scratching's continuous oscillation from discrete-impulse activities. Four wiring edits propagate `desk_activity` from the behaviors dict through perception-state.json to OverlayData, flow modifier, and camera profiles.

**Tech Stack:** NumPy (autocorrelation), Python 3.12+, no new dependencies

**Spec:** `docs/superpowers/specs/2026-03-25-scratch-detection-enrichment.md`

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Edit | `agents/hapax_voice/backends/contact_mic.py` | Add autocorrelation, energy buffer, "scratching" classification |
| Edit | `tests/hapax_voice/test_contact_mic_backend.py` | Update existing tests + add scratch detection tests |
| Edit | `agents/hapax_voice/_perception_state_writer.py` | Export desk_* behaviors + add desk_activity flow modifier |
| Edit | `agents/studio_compositor.py` | Add desk_activity to OverlayData model |
| Create | `tests/test_scratch_pipeline.py` | Tests for perception export, OverlayData, flow modifier |
| Config | `~/.config/hapax-compositor/profiles.yaml` | Add scratching-focus camera profile |

---

## Task 1: Scratch Detection DSP

**Files:**
- Modify: `agents/hapax_voice/backends/contact_mic.py`
- Modify: `tests/hapax_voice/test_contact_mic_backend.py`

- [ ] **Step 1: Write failing tests for autocorrelation + scratch classification**

Append to `tests/hapax_voice/test_contact_mic_backend.py`:

```python
class TestEnvelopeAutocorrelation:
    def test_oscillating_envelope_high_peak(self):
        from agents.hapax_voice.backends.contact_mic import _compute_envelope_autocorrelation
        from collections import deque
        import math

        # Simulate scratching: sinusoidal energy at 5 Hz (200ms period, lag ~6 at 32ms)
        buf = deque(maxlen=60)
        for i in range(60):
            buf.append(0.3 + 0.2 * math.sin(2 * math.pi * 5.0 * i * 0.032))
        peak = _compute_envelope_autocorrelation(buf)
        assert peak > 0.4  # strong periodic signal

    def test_flat_envelope_low_peak(self):
        from agents.hapax_voice.backends.contact_mic import _compute_envelope_autocorrelation
        from collections import deque

        buf = deque(maxlen=60)
        for _ in range(60):
            buf.append(0.3)  # constant energy, no oscillation
        peak = _compute_envelope_autocorrelation(buf)
        assert peak < 0.2

    def test_impulsive_envelope_low_peak(self):
        from agents.hapax_voice.backends.contact_mic import _compute_envelope_autocorrelation
        from collections import deque

        # Simulate typing: sparse impulses
        buf = deque(maxlen=60)
        for i in range(60):
            buf.append(0.5 if i % 10 == 0 else 0.01)
        peak = _compute_envelope_autocorrelation(buf)
        # Sparse impulses have weak autocorrelation in the scratch range
        assert peak < 0.4

    def test_short_buffer_returns_zero(self):
        from agents.hapax_voice.backends.contact_mic import _compute_envelope_autocorrelation
        from collections import deque

        buf = deque(maxlen=60)
        buf.append(0.5)
        assert _compute_envelope_autocorrelation(buf) == 0.0


class TestScratchClassification:
    def test_scratching_high_autocorr(self):
        from agents.hapax_voice.backends.contact_mic import _classify_activity
        assert _classify_activity(
            energy=0.1, onset_rate=0.0, centroid=200.0, autocorr_peak=0.5
        ) == "scratching"

    def test_no_scratch_low_autocorr(self):
        from agents.hapax_voice.backends.contact_mic import _classify_activity
        # Same energy but no autocorrelation → falls through to other categories
        assert _classify_activity(
            energy=0.1, onset_rate=2.0, centroid=200.0, autocorr_peak=0.1
        ) == "tapping"

    def test_scratch_before_drumming(self):
        from agents.hapax_voice.backends.contact_mic import _classify_activity
        # High energy + low centroid would be drumming, but autocorr makes it scratching
        assert _classify_activity(
            energy=0.5, onset_rate=0.0, centroid=500.0, autocorr_peak=0.5
        ) == "scratching"

    def test_idle_not_affected(self):
        from agents.hapax_voice.backends.contact_mic import _classify_activity
        # Below idle threshold, autocorr doesn't matter
        assert _classify_activity(
            energy=0.001, onset_rate=0.0, centroid=0.0, autocorr_peak=0.6
        ) == "idle"
```

Also update the 4 existing `TestClassifyActivity` tests to pass `autocorr_peak=0.0`:

```python
class TestClassifyActivity:
    def test_idle_when_silent(self):
        assert _classify_activity(energy=0.0, onset_rate=0.0, centroid=0.0, autocorr_peak=0.0) == "idle"

    def test_typing_high_onset_low_energy(self):
        assert _classify_activity(energy=0.05, onset_rate=5.0, centroid=3000.0, autocorr_peak=0.0) == "typing"

    def test_tapping_moderate_onset_higher_energy(self):
        assert _classify_activity(energy=0.15, onset_rate=2.0, centroid=2000.0, autocorr_peak=0.0) == "tapping"

    def test_drumming_high_energy_low_centroid(self):
        assert _classify_activity(energy=0.6, onset_rate=4.0, centroid=500.0, autocorr_peak=0.0) == "drumming"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapax/projects/hapax-council--beta && uv run pytest tests/hapax_voice/test_contact_mic_backend.py -v 2>&1 | tail -10`
Expected: ImportError for `_compute_envelope_autocorrelation`, TypeError for extra `autocorr_peak` param

- [ ] **Step 3: Add constants and autocorrelation function**

In `agents/hapax_voice/backends/contact_mic.py`, after the existing DSP constants, add:

```python
_SCRATCH_AUTOCORR_THRESHOLD = 0.4
_SCRATCH_MIN_ENERGY = 0.02
_SCRATCH_MIN_LAG = 2   # ~64ms at 32ms frames (~16 Hz)
_SCRATCH_MAX_LAG = 16  # ~512ms at 32ms frames (~2 Hz)
_ENERGY_BUFFER_SIZE = 60  # ~1.9s of history at 32ms frames
```

After the existing DSP functions, add:

```python
def _compute_envelope_autocorrelation(energy_buffer: deque[float]) -> float:
    """Compute peak normalized autocorrelation of energy envelope in scratch lag range.

    Returns the maximum normalized autocorrelation value for lags corresponding
    to 2-16 Hz oscillation (the vinyl scratch gesture rate range).
    """
    if len(energy_buffer) < _SCRATCH_MAX_LAG + 1:
        return 0.0

    arr = np.array(energy_buffer, dtype=np.float32)
    arr = arr - arr.mean()
    norm = np.dot(arr, arr)
    if norm < 1e-10:
        return 0.0

    peak = 0.0
    for lag in range(_SCRATCH_MIN_LAG, _SCRATCH_MAX_LAG + 1):
        corr = np.dot(arr[:-lag], arr[lag:]) / norm
        if corr > peak:
            peak = corr
    return float(peak)
```

- [ ] **Step 4: Update `_classify_activity` signature**

Change `_classify_activity` to accept `autocorr_peak`:

```python
def _classify_activity(
    energy: float, onset_rate: float, centroid: float, autocorr_peak: float = 0.0
) -> str:
    """Classify desk activity from DSP metrics."""
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

Note: `autocorr_peak` has a default of `0.0` making the signature backward-compatible with any call sites that don't pass it.

- [ ] **Step 5: Update capture loop**

In `_capture_loop`, add before the while loop:

```python
            energy_buffer: deque[float] = deque(maxlen=_ENERGY_BUFFER_SIZE)
            autocorr_peak = 0.0
```

After the `smoothed_energy` computation, add:

```python
                    energy_buffer.append(smoothed_energy)
```

In the `frame_count % 4 == 0` block, after centroid, add:

```python
                        autocorr_peak = _compute_envelope_autocorrelation(energy_buffer)
```

Update the `_classify_activity` call to pass `autocorr_peak`:

```python
                    activity = _classify_activity(smoothed_energy, onset_rate, centroid, autocorr_peak)
```

- [ ] **Step 6: Run tests**

Run: `cd /home/hapax/projects/hapax-council--beta && uv run pytest tests/hapax_voice/test_contact_mic_backend.py -v`
Expected: All pass (existing + new)

- [ ] **Step 7: Lint**

Run: `cd /home/hapax/projects/hapax-council--beta && uv run ruff check agents/hapax_voice/backends/contact_mic.py tests/hapax_voice/test_contact_mic_backend.py && uv run ruff format --check agents/hapax_voice/backends/contact_mic.py tests/hapax_voice/test_contact_mic_backend.py`

- [ ] **Step 8: Commit**

```bash
git add agents/hapax_voice/backends/contact_mic.py tests/hapax_voice/test_contact_mic_backend.py
git commit -m "feat(voice): vinyl scratch detection via envelope autocorrelation

Adds _compute_envelope_autocorrelation() and 'scratching' classification
to ContactMicBackend. Scratching detected by quasi-periodic 2-16 Hz
oscillation in amplitude envelope — unique to turntable back-and-forth."
```

---

## Task 2: Perception Pipeline Wiring

**Files:**
- Modify: `agents/hapax_voice/_perception_state_writer.py`
- Modify: `agents/studio_compositor.py`
- Create: `tests/test_scratch_pipeline.py`

- [ ] **Step 1: Write failing tests**

File: `tests/test_scratch_pipeline.py`

```python
"""Tests for scratch detection perception pipeline wiring."""

from __future__ import annotations


class TestPerceptionStateExport:
    """Verify desk_* fields appear in the perception state dict."""

    def test_desk_activity_in_state_dict_keys(self):
        """The perception state writer must include desk_activity."""
        import ast
        from pathlib import Path

        writer_path = Path("agents/hapax_voice/_perception_state_writer.py")
        source = writer_path.read_text()
        assert '"desk_activity"' in source

    def test_desk_energy_in_state_dict_keys(self):
        import ast
        from pathlib import Path

        writer_path = Path("agents/hapax_voice/_perception_state_writer.py")
        source = writer_path.read_text()
        assert '"desk_energy"' in source


class TestOverlayDataField:
    def test_desk_activity_field_exists(self):
        from agents.studio_compositor import OverlayData

        data = OverlayData(desk_activity="scratching")
        assert data.desk_activity == "scratching"

    def test_desk_activity_defaults_empty(self):
        from agents.studio_compositor import OverlayData

        data = OverlayData()
        assert data.desk_activity == ""


class TestFlowModifier:
    def test_scratching_boosts_flow(self):
        """Source check: perception state writer adds flow modifier for scratching."""
        from pathlib import Path

        source = Path("agents/hapax_voice/_perception_state_writer.py").read_text()
        assert "scratching" in source
        assert "drumming" in source
        assert "flow_modifier" in source
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapax/projects/hapax-council--beta && uv run pytest tests/test_scratch_pipeline.py -v 2>&1 | tail -10`
Expected: Failures — desk_activity not in writer source, not in OverlayData

- [ ] **Step 3: Add desk_* exports to perception state writer**

In `agents/hapax_voice/_perception_state_writer.py`, in the state dict (after line ~395, before `"voice_session"`), add:

```python
            # Contact mic (desk vibration sensing)
            "desk_activity": str(_bval("desk_activity", "")),
            "desk_energy": _safe_float(_bval("desk_energy", 0.0)),
            "desk_onset_rate": _safe_float(_bval("desk_onset_rate", 0.0)),
            "desk_tap_gesture": str(_bval("desk_tap_gesture", "none")),
```

- [ ] **Step 4: Add desk_activity flow modifier**

In the same file, after line ~275 (after `flow_modifier += 0.1` for audio silence) and before line 277 (`flow_score = min(...)`), add:

```python
        # Desk activity bonus (structure-borne instrument engagement)
        desk_act = str(_bval("desk_activity", ""))
        if desk_act in ("scratching", "drumming"):
            flow_modifier += 0.15
        elif desk_act == "tapping":
            flow_modifier += 0.05
```

- [ ] **Step 5: Add desk_activity to OverlayData**

In `agents/studio_compositor.py`, in the `OverlayData` class (line ~303), after `production_activity`, add:

```python
    desk_activity: str = ""
```

- [ ] **Step 6: Run tests**

Run: `cd /home/hapax/projects/hapax-council--beta && uv run pytest tests/test_scratch_pipeline.py -v`
Expected: All pass

- [ ] **Step 7: Lint**

Run: `cd /home/hapax/projects/hapax-council--beta && uv run ruff check agents/hapax_voice/_perception_state_writer.py agents/studio_compositor.py tests/test_scratch_pipeline.py && uv run ruff format --check agents/hapax_voice/_perception_state_writer.py agents/studio_compositor.py tests/test_scratch_pipeline.py`

- [ ] **Step 8: Commit**

```bash
git add agents/hapax_voice/_perception_state_writer.py agents/studio_compositor.py tests/test_scratch_pipeline.py
git commit -m "feat(voice): wire desk_activity through perception pipeline

Exports desk_* behaviors to perception-state.json, adds desk_activity
flow modifier (scratching/drumming +0.15, tapping +0.05), extends
OverlayData for camera profile conditions."
```

---

## Task 3: Camera Profile + Full Test + PR

- [ ] **Step 1: Add camera profile**

Check if `~/.config/hapax-compositor/profiles.yaml` exists and add the scratching profile. If the file doesn't exist or profiles are configured differently, add the profile in whatever format the compositor expects.

```yaml
- name: scratching-focus
  condition: "desk_activity=scratching"
  priority: 10
  cameras: {}
```

- [ ] **Step 2: Run all tests**

Run: `cd /home/hapax/projects/hapax-council--beta && uv run pytest tests/hapax_voice/test_contact_mic_backend.py tests/test_scratch_pipeline.py -v`
Expected: All pass

- [ ] **Step 3: Lint all changed files**

Run: `cd /home/hapax/projects/hapax-council--beta && uv run ruff check agents/hapax_voice/backends/contact_mic.py agents/hapax_voice/_perception_state_writer.py agents/studio_compositor.py && uv run ruff format --check agents/hapax_voice/backends/contact_mic.py agents/hapax_voice/_perception_state_writer.py agents/studio_compositor.py`

- [ ] **Step 4: Push and update PR**

Push to the existing `feat/contact-mic-integration` branch and update PR #332 description to include scratch detection.
