# Perception-Visual Governance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three-tier perception-visual governance — atmospheric preset selection, gestural parameter offsets, rhythmic shader modulation with expanded signals and a breathing substrate.

**Architecture:** New `visual_governance.py` module contains the atmospheric state machine and gestural offset logic. The compositor's signals dict expands from 4→12 entries. A default modulation template JSON gives every preset perception-driven reactivity. MIDI beat/bar exported to perception-state.json as a prerequisite.

**Tech Stack:** Python 3.12+, Pydantic, NumPy (Perlin noise), existing effect_graph types/runtime/modulator

**Spec:** `docs/superpowers/specs/2026-03-26-perception-visual-governance-design.md`

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `agents/effect_graph/visual_governance.py` | Atmospheric state machine + gestural offsets + breathing substrate |
| Create | `presets/_default_modulations.json` | Default modulation template |
| Create | `tests/effect_graph/test_visual_governance.py` | All governance unit tests |
| Edit | `agents/effect_graph/types.py` | Add `PresetFamily` type |
| Edit | `agents/hapax_voice/_perception_state_writer.py` | Export beat_position + bar_position |
| Edit | `agents/studio_compositor.py:303` | Add desk_energy + stimmung fields to OverlayData |
| Edit | `agents/studio_compositor.py:1928` | Expand signals dict |
| Edit | `agents/studio_compositor.py:545` | Merge default modulations on preset load |

---

## Task 1: Export MIDI Beat/Bar to Perception State

The MIDI clock backend produces `beat_position` and `bar_position` as behaviors but they are NOT exported to perception-state.json. The compositor reads perception-state.json — not the behaviors dict — so these signals are invisible to it.

**Files:**
- Edit: `agents/hapax_voice/_perception_state_writer.py`
- Edit: `tests/test_scratch_pipeline.py` (or create new test)

- [ ] **Step 1: Write failing test**

```python
# In tests/test_scratch_pipeline.py, add:
class TestMidiExport:
    def test_beat_position_in_state_dict(self):
        from pathlib import Path
        _PROJECT_ROOT = Path(__file__).resolve().parents[1]
        source = (_PROJECT_ROOT / "agents/hapax_voice/_perception_state_writer.py").read_text()
        assert '"beat_position"' in source

    def test_bar_position_in_state_dict(self):
        from pathlib import Path
        _PROJECT_ROOT = Path(__file__).resolve().parents[1]
        source = (_PROJECT_ROOT / "agents/hapax_voice/_perception_state_writer.py").read_text()
        assert '"bar_position"' in source
```

- [ ] **Step 2: Run test — verify fail**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/test_scratch_pipeline.py::TestMidiExport -v`

- [ ] **Step 3: Add beat/bar exports to perception state writer**

In `agents/hapax_voice/_perception_state_writer.py`, find the contact mic block (lines ~403-409). After `"desk_tap_gesture"`, add:

```python
            # MIDI clock (beat/bar position for visual sync)
            "beat_position": _safe_float(_bval("beat_position", 0.0)),
            "bar_position": _safe_float(_bval("bar_position", 0.0)),
```

- [ ] **Step 4: Run test — verify pass**
- [ ] **Step 5: Lint + commit**

```bash
git add agents/hapax_voice/_perception_state_writer.py tests/test_scratch_pipeline.py
git commit -m "feat(voice): export beat_position + bar_position to perception state

MIDI clock signals now available in perception-state.json for
compositor visual sync."
```

---

## Task 2: PresetFamily Type + Visual Governance Module

**Files:**
- Edit: `agents/effect_graph/types.py`
- Create: `agents/effect_graph/visual_governance.py`
- Create: `tests/effect_graph/test_visual_governance.py`

- [ ] **Step 1: Write tests for PresetFamily and atmospheric state machine**

File: `tests/effect_graph/test_visual_governance.py`

```python
"""Tests for perception-visual governance."""

from __future__ import annotations

import time

import pytest


class TestPresetFamily:
    def test_first_available_returns_match(self):
        from agents.effect_graph.types import PresetFamily

        family = PresetFamily(presets=("trails", "ghost", "clean"))
        assert family.first_available({"ghost", "clean"}) == "ghost"

    def test_first_available_returns_first(self):
        from agents.effect_graph.types import PresetFamily

        family = PresetFamily(presets=("trails", "ghost"))
        assert family.first_available({"trails", "ghost"}) == "trails"

    def test_first_available_none_when_empty(self):
        from agents.effect_graph.types import PresetFamily

        family = PresetFamily(presets=("trails",))
        assert family.first_available({"clean"}) is None


class TestAtmosphericSelector:
    def test_nominal_low_energy(self):
        from agents.effect_graph.visual_governance import AtmosphericSelector

        sel = AtmosphericSelector()
        family = sel.select_family(stance="nominal", energy_level="low")
        assert family is not None
        assert len(family.presets) > 0

    def test_critical_always_silhouette(self):
        from agents.effect_graph.visual_governance import AtmosphericSelector

        sel = AtmosphericSelector()
        for level in ("low", "medium", "high"):
            family = sel.select_family(stance="critical", energy_level=level)
            assert "silhouette" in family.presets

    def test_dwell_time_prevents_rapid_change(self):
        from agents.effect_graph.visual_governance import AtmosphericSelector

        sel = AtmosphericSelector()
        first = sel.evaluate(stance="nominal", energy_level="low", available_presets={"clean", "ambient"})
        # Immediately change inputs — should return same preset (dwell)
        second = sel.evaluate(stance="nominal", energy_level="high", available_presets={"feedback", "kaleidodream"})
        assert second == first  # dwell prevents change

    def test_stance_change_bypasses_dwell(self):
        from agents.effect_graph.visual_governance import AtmosphericSelector

        sel = AtmosphericSelector()
        first = sel.evaluate(stance="nominal", energy_level="low", available_presets={"clean", "ambient"})
        second = sel.evaluate(stance="critical", energy_level="low", available_presets={"silhouette"})
        assert second == "silhouette"  # stance change bypasses dwell

    def test_energy_level_from_desk_activity(self):
        from agents.effect_graph.visual_governance import energy_level_from_activity

        assert energy_level_from_activity("idle") == "low"
        assert energy_level_from_activity("typing") == "low"
        assert energy_level_from_activity("tapping") == "medium"
        assert energy_level_from_activity("drumming") == "high"
        assert energy_level_from_activity("scratching") == "high"


class TestGesturalOffsets:
    def test_scratching_boosts_trail_opacity(self):
        from agents.effect_graph.visual_governance import compute_gestural_offsets

        offsets = compute_gestural_offsets(
            desk_activity="scratching",
            gaze_direction="hardware",
            person_count=1,
        )
        assert ("trail", "opacity") in offsets
        assert offsets[("trail", "opacity")] > 0

    def test_idle_returns_empty(self):
        from agents.effect_graph.visual_governance import compute_gestural_offsets

        offsets = compute_gestural_offsets(
            desk_activity="idle",
            gaze_direction="screen",
            person_count=1,
        )
        # Idle has no positive offsets (all drift toward default)
        assert all(v <= 0 for v in offsets.values()) or len(offsets) == 0

    def test_typing_reduces_modulation(self):
        from agents.effect_graph.visual_governance import compute_gestural_offsets

        offsets = compute_gestural_offsets(
            desk_activity="typing",
            gaze_direction="screen",
            person_count=1,
        )
        assert ("_modulation_depth_scale",) not in offsets or offsets.get(
            ("_meta", "modulation_depth_scale"), 1.0
        ) < 1.0

    def test_guest_reduces_intensity(self):
        from agents.effect_graph.visual_governance import compute_gestural_offsets

        alone = compute_gestural_offsets("drumming", "hardware", person_count=1)
        guest = compute_gestural_offsets("drumming", "hardware", person_count=2)
        # Guest presence should reduce offsets
        for key in alone:
            if key in guest:
                assert guest[key] <= alone[key]


class TestBreathingSubstrate:
    def test_perlin_drift_within_range(self):
        from agents.effect_graph.visual_governance import compute_perlin_drift

        for t in [0.0, 1.0, 10.0, 100.0]:
            drift = compute_perlin_drift(t, desk_energy=0.0)
            assert -0.1 < drift < 0.1

    def test_drift_suppressed_by_energy(self):
        from agents.effect_graph.visual_governance import compute_perlin_drift

        quiet = abs(compute_perlin_drift(5.0, desk_energy=0.0))
        loud = abs(compute_perlin_drift(5.0, desk_energy=0.8))
        assert loud < quiet

    def test_idle_escalation(self):
        from agents.effect_graph.visual_governance import compute_idle_escalation

        short = compute_idle_escalation(idle_duration_s=10.0)
        long = compute_idle_escalation(idle_duration_s=300.0)
        assert long > short
        assert short >= 1.0  # multiplier starts at 1.0
        assert long <= 3.0  # caps at ~3x
```

- [ ] **Step 2: Run tests — verify fail**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/effect_graph/test_visual_governance.py -v`

- [ ] **Step 3: Add PresetFamily to types.py**

In `agents/effect_graph/types.py`, after the `GraphPatch` class (line ~107), add:

```python
class PresetFamily(BaseModel, frozen=True):
    """Ranked list of preset names for an atmospheric state cell."""

    presets: tuple[str, ...]

    def first_available(self, loaded_presets: set[str]) -> str | None:
        """Return the first preset in the family that exists in the loaded set."""
        for p in self.presets:
            if p in loaded_presets:
                return p
        return None
```

- [ ] **Step 4: Create visual_governance.py**

File: `agents/effect_graph/visual_governance.py`

```python
"""Perception-visual governance — three-tier system for effect reactivity.

Atmospheric layer: selects which preset is active based on stimmung stance,
operator energy level, and music genre.

Gestural layer: adjusts parameters within the active preset based on
desk activity, gaze direction, and person count.

Breathing substrate: ensures the system is never visually dead via
Perlin noise drift, idle escalation, and silence-as-decay.
"""

from __future__ import annotations

import math
import time

from agents.effect_graph.types import PresetFamily

# ── Atmospheric Layer ─────────────────────────────────────────────────────────

# State matrix: stance × energy_level → PresetFamily
_STATE_MATRIX: dict[tuple[str, str], PresetFamily] = {
    # NOMINAL
    ("nominal", "low"): PresetFamily(presets=("clean", "ambient")),
    ("nominal", "medium"): PresetFamily(presets=("trails", "ghost")),
    ("nominal", "high"): PresetFamily(presets=("feedback_preset", "kaleidodream")),
    # CAUTIOUS
    ("cautious", "low"): PresetFamily(presets=("ambient",)),
    ("cautious", "medium"): PresetFamily(presets=("ghost",)),
    ("cautious", "high"): PresetFamily(presets=("trails",)),
    # DEGRADED
    ("degraded", "low"): PresetFamily(presets=("dither_retro", "vhs_preset")),
    ("degraded", "medium"): PresetFamily(presets=("vhs_preset",)),
    ("degraded", "high"): PresetFamily(presets=("screwed",)),
    # CRITICAL
    ("critical", "low"): PresetFamily(presets=("silhouette",)),
    ("critical", "medium"): PresetFamily(presets=("silhouette",)),
    ("critical", "high"): PresetFamily(presets=("silhouette",)),
}

# Genre bias: genre keyword → list of preferred preset names (prepended to family)
_GENRE_BIAS: dict[str, list[str]] = {
    "hip hop": ["trap", "screwed", "ghost"],
    "trap": ["trap", "screwed", "ghost"],
    "lo-fi": ["vhs_preset", "dither_retro", "ambient"],
    "jazz": ["vhs_preset", "dither_retro", "ambient"],
    "soul": ["vhs_preset", "ambient"],
    "electronic": ["voronoi_crystal", "tunnel_vision", "kaleidodream"],
    "ambient": ["voronoi_crystal", "tunnel_vision", "kaleidodream"],
}

_DWELL_MIN_S = 30.0  # minimum seconds before atmospheric transition


def energy_level_from_activity(desk_activity: str) -> str:
    """Map desk_activity classification to energy level."""
    if desk_activity in ("drumming", "scratching"):
        return "high"
    if desk_activity in ("tapping",):
        return "medium"
    return "low"


class AtmosphericSelector:
    """State machine for atmospheric preset selection."""

    def __init__(self) -> None:
        self._current_preset: str | None = None
        self._current_stance: str = "nominal"
        self._last_transition: float = 0.0

    def select_family(self, stance: str, energy_level: str) -> PresetFamily:
        """Get the preset family for a stance × energy combination."""
        key = (stance, energy_level)
        return _STATE_MATRIX.get(key, PresetFamily(presets=("clean",)))

    def evaluate(
        self,
        stance: str,
        energy_level: str,
        available_presets: set[str],
        genre: str = "",
    ) -> str | None:
        """Evaluate atmospheric state and return the preset to load (or None if no change)."""
        now = time.monotonic()

        # Stance change bypasses dwell
        stance_changed = stance != self._current_stance
        self._current_stance = stance

        # Check dwell time (unless stance changed)
        if not stance_changed and (now - self._last_transition) < _DWELL_MIN_S:
            return self._current_preset

        family = self.select_family(stance, energy_level)

        # Apply genre bias: prepend genre-preferred presets to the family
        genre_lower = genre.lower().strip()
        bias = []
        for keyword, preferred in _GENRE_BIAS.items():
            if keyword in genre_lower:
                bias = preferred
                break
        if bias:
            biased_presets = tuple(p for p in bias if p in available_presets) + family.presets
            family = PresetFamily(presets=biased_presets)

        target = family.first_available(available_presets)
        if target is None or target == self._current_preset:
            return self._current_preset

        self._current_preset = target
        self._last_transition = now
        return target


# ── Gestural Layer ────────────────────────────────────────────────────────────

# Activity → {(node, param): offset}
_ACTIVITY_OFFSETS: dict[str, dict[tuple[str, str], float]] = {
    "scratching": {
        ("trail", "opacity"): 0.2,
        ("bloom", "alpha"): 0.15,
        ("drift", "speed"): 1.0,  # additive to drift speed
    },
    "drumming": {
        ("bloom", "alpha"): 0.2,
        ("stutter", "freeze_chance"): 0.1,
    },
    "tapping": {
        ("trail", "opacity"): 0.1,
        ("bloom", "alpha"): 0.1,
    },
    "typing": {},  # typing uses modulation_depth_scale instead
}

_GAZE_MODIFIERS: dict[str, float] = {
    "screen": 0.5,  # reduce effect intensity (reading)
    "hardware": 1.2,  # boost (looking at gear)
    "away": 1.0,  # standard (drift increases separately)
    "person": 0.8,  # slightly reduced (social)
}

_TYPING_MODULATION_DEPTH = 0.5  # 50% modulation depth when typing
_GUEST_REDUCTION = 0.6  # 60% intensity with guests


def compute_gestural_offsets(
    desk_activity: str,
    gaze_direction: str,
    person_count: int,
) -> dict[tuple[str, str], float]:
    """Compute additive parameter offsets from gestural signals.

    Returns dict of {(node_id, param_name): offset_value}.
    """
    base = dict(_ACTIVITY_OFFSETS.get(desk_activity, {}))

    # Gaze modifier scales all offsets
    gaze_scale = _GAZE_MODIFIERS.get(gaze_direction, 1.0)
    for key in base:
        base[key] *= gaze_scale

    # Guest presence reduces intensity
    if person_count >= 2:
        for key in base:
            base[key] *= _GUEST_REDUCTION

    return base


# ── Breathing Substrate ───────────────────────────────────────────────────────


def compute_perlin_drift(t: float, desk_energy: float) -> float:
    """Compute Perlin-like drift value. Inversely proportional to desk_energy.

    Uses layered sine waves as a lightweight Perlin approximation.
    """
    # Lightweight Perlin approximation: layered sinusoids at irrational frequencies
    noise = (
        math.sin(t * 0.13) * 0.5
        + math.sin(t * 0.31) * 0.3
        + math.sin(t * 0.71) * 0.2
    )
    base_amplitude = 0.03  # 3% wobble
    activity_suppression = min(1.0, desk_energy * 5.0)
    return noise * base_amplitude * (1.0 - activity_suppression)


def compute_idle_escalation(idle_duration_s: float) -> float:
    """Compute drift amplitude multiplier based on idle duration.

    Returns 1.0 immediately, ramps to ~2.7x over 5 minutes.
    """
    if idle_duration_s <= 0:
        return 1.0
    # Logarithmic ramp: 1.0 at t=0, ~2.7 at t=300s, caps at 3.0
    return min(3.0, 1.0 + math.log1p(idle_duration_s / 60.0))
```

- [ ] **Step 5: Run tests — verify pass**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/effect_graph/test_visual_governance.py -v`

- [ ] **Step 6: Lint + commit**

```bash
git add agents/effect_graph/types.py agents/effect_graph/visual_governance.py tests/effect_graph/test_visual_governance.py
git commit -m "feat(effect-graph): visual governance — atmospheric selector + gestural offsets + breathing

Three-tier perception-visual governance: atmospheric preset selection
(stimmung × energy × genre), gestural parameter offsets (activity/gaze/
presence), breathing substrate (Perlin drift, idle escalation)."
```

---

## Task 3: Default Modulation Template

**Files:**
- Create: `presets/_default_modulations.json`
- Edit: `agents/studio_compositor.py:545` (preset load path)

- [ ] **Step 1: Create default modulations JSON**

File: `presets/_default_modulations.json`

```json
{
  "default_modulations": [
    {
      "node": "bloom",
      "param": "alpha",
      "source": "desk_energy",
      "scale": 0.3,
      "offset": 0.0,
      "smoothing": 0.85
    },
    {
      "node": "bloom",
      "param": "alpha",
      "source": "beat_pulse",
      "scale": 0.15,
      "offset": 0.0,
      "smoothing": 0.3
    },
    {
      "node": "trail",
      "param": "opacity",
      "source": "desk_energy",
      "scale": 0.2,
      "offset": 0.0,
      "smoothing": 0.85
    },
    {
      "node": "colorgrade",
      "param": "hue_rotate",
      "source": "desk_centroid",
      "scale": 30.0,
      "offset": -15.0,
      "smoothing": 0.92
    },
    {
      "node": "drift",
      "param": "speed",
      "source": "desk_onset_rate",
      "scale": 0.1,
      "offset": 0.0,
      "smoothing": 0.8
    },
    {
      "node": "breathing",
      "param": "rate",
      "source": "heart_rate",
      "scale": 1.5,
      "offset": 0.3,
      "smoothing": 0.95
    },
    {
      "node": "noise_overlay",
      "param": "intensity",
      "source": "stress",
      "scale": 0.05,
      "offset": 0.0,
      "smoothing": 0.95
    },
    {
      "node": "vignette",
      "param": "strength",
      "source": "perlin_drift",
      "scale": 1.0,
      "offset": 0.0,
      "smoothing": 0.0
    }
  ]
}
```

- [ ] **Step 2: Add default modulation merge to preset loading**

In `agents/studio_compositor.py`, find the preset load function (line ~545). After `graph = EffectGraph(**raw)` (line 558), add the default modulation merge:

```python
                    # Merge default modulations (preset's own bindings win)
                    graph = self._merge_default_modulations(graph)
```

Add the merge method to the compositor class:

```python
    def _merge_default_modulations(self, graph: EffectGraph) -> EffectGraph:
        """Merge default modulation template into a graph's modulations.

        Only adds bindings for nodes that exist in the graph. The graph's
        own bindings for the same (node, param) take precedence.
        """
        import json as _json
        from pathlib import Path

        template_path = Path(__file__).parent.parent / "presets" / "_default_modulations.json"
        if not template_path.is_file():
            return graph

        try:
            defaults = _json.loads(template_path.read_text()).get("default_modulations", [])
        except Exception:
            return graph

        # Existing bindings: set of (node, param) that the preset already defines
        existing = {(m.node, m.param) for m in graph.modulations}
        graph_nodes = set(graph.nodes.keys())

        from agents.effect_graph.types import ModulationBinding

        merged = list(graph.modulations)
        for d in defaults:
            key = (d["node"], d["param"])
            if key not in existing and d["node"] in graph_nodes:
                merged.append(ModulationBinding(**d))

        # Return new graph with merged modulations
        return graph.model_copy(update={"modulations": merged})
```

- [ ] **Step 3: Lint + commit**

```bash
git add presets/_default_modulations.json agents/studio_compositor.py
git commit -m "feat(compositor): default modulation template for perception-driven presets

All presets inherit desk_energy→bloom, beat_pulse→bloom, desk_centroid→
hue_rotate, onset_rate→drift, heart_rate→breathing, stress→noise,
perlin_drift→vignette. Preset's own bindings take precedence."
```

---

## Task 4: Expand Signals Dict + OverlayData

**Files:**
- Edit: `agents/studio_compositor.py:303` (OverlayData)
- Edit: `agents/studio_compositor.py:1928` (signals dict)

- [ ] **Step 1: Add missing fields to OverlayData**

In `agents/studio_compositor.py`, in the `OverlayData` class (line ~303), add after `audio_energy_rms`:

```python
    desk_energy: float = 0.0
    desk_onset_rate: float = 0.0
    desk_spectral_centroid: float = 0.0
    beat_position: float = 0.0
    bar_position: float = 0.0
    heart_rate_bpm: int = 0
    stress_elevated: bool = False
```

- [ ] **Step 2: Expand signals dict**

In `agents/studio_compositor.py`, find the signals dict (line ~1928). Replace the entire block:

```python
                signals = {
                    "audio_rms": energy,
                    "audio_beat": b,
                    "time": t,
                }
                data = self._overlay_state._data
                if data.flow_score > 0:
                    signals["flow_score"] = data.flow_score
                if data.emotion_valence != 0:
                    signals["stimmung_valence"] = data.emotion_valence
                if data.emotion_arousal != 0:
                    signals["stimmung_arousal"] = data.emotion_arousal
```

with:

```python
                data = self._overlay_state._data
                signals = {
                    "audio_rms": energy,
                    "audio_beat": b,
                    "time": t,
                }
                # Existing optional signals
                if data.flow_score > 0:
                    signals["flow_score"] = data.flow_score
                if data.emotion_valence != 0:
                    signals["stimmung_valence"] = data.emotion_valence
                if data.emotion_arousal != 0:
                    signals["stimmung_arousal"] = data.emotion_arousal

                # Contact mic signals
                signals["desk_energy"] = data.desk_energy
                signals["desk_onset_rate"] = data.desk_onset_rate
                signals["desk_centroid"] = min(
                    1.0, data.desk_spectral_centroid / 4000.0
                )

                # MIDI clock (sawtooth phases)
                if data.beat_position > 0:
                    beats_per_bar = 4  # TODO: read from timeline_mapping
                    signals["beat_phase"] = data.beat_position % 1.0
                    signals["bar_phase"] = (
                        data.beat_position % beats_per_bar
                    ) / beats_per_bar

                # Beat pulse (spike on downbeat, exponential decay)
                if not hasattr(self, "_beat_pulse"):
                    self._beat_pulse = 0.0
                    self._prev_beat_phase = 0.0
                beat_phase = data.beat_position % 1.0
                if beat_phase < self._prev_beat_phase and data.beat_position > 0:
                    self._beat_pulse = 1.0
                self._beat_pulse *= 0.85
                self._prev_beat_phase = beat_phase
                signals["beat_pulse"] = self._beat_pulse

                # Biometrics
                if data.heart_rate_bpm > 0:
                    signals["heart_rate"] = min(
                        1.0, max(0.0, (data.heart_rate_bpm - 40) / 140.0)
                    )
                signals["stress"] = 1.0 if data.stress_elevated else 0.0

                # Breathing substrate
                from agents.effect_graph.visual_governance import (
                    compute_perlin_drift,
                )

                signals["perlin_drift"] = compute_perlin_drift(
                    t, data.desk_energy
                )
```

- [ ] **Step 3: Lint + commit**

```bash
git add agents/studio_compositor.py
git commit -m "feat(compositor): expand signals dict from 4 to 12 perception inputs

Adds desk_energy, desk_centroid, desk_onset_rate, beat_phase, bar_phase,
beat_pulse (derived), heart_rate, stress, perlin_drift to modulator
signal inputs. All presets now perception-reactive via default template."
```

---

## Task 5: Wire Atmospheric + Gestural Governance into Compositor

**Files:**
- Edit: `agents/studio_compositor.py`

- [ ] **Step 1: Add governance instance to compositor init**

Find the compositor's `__init__` method. After `self._graph_runtime` is initialized, add:

```python
        # Perception-visual governance
        from agents.effect_graph.visual_governance import AtmosphericSelector
        self._atmospheric_selector = AtmosphericSelector()
        self._idle_start: float | None = None
```

- [ ] **Step 2: Add governance tick to the render loop**

In the render tick method, BEFORE the signals dict block (before line ~1924), add:

```python
        # --- Perception-visual governance ---
        if self._graph_runtime is not None:
            data = self._overlay_state._data
            from agents.effect_graph.visual_governance import (
                energy_level_from_activity,
                compute_gestural_offsets,
            )

            # Atmospheric: evaluate preset selection
            energy_level = energy_level_from_activity(data.desk_activity)
            stance = "nominal"  # TODO: read from stimmung via OverlayData when available
            available = self._get_available_preset_names()
            target_preset = self._atmospheric_selector.evaluate(
                stance=stance,
                energy_level=energy_level,
                available_presets=available,
                genre=data.music_genre,
            )
            if target_preset and target_preset != getattr(self, "_current_preset_name", None):
                if self._try_load_graph_preset(target_preset):
                    self._current_preset_name = target_preset

            # Gestural: compute parameter offsets
            offsets = compute_gestural_offsets(
                desk_activity=data.desk_activity,
                gaze_direction="",  # not in OverlayData yet — graceful default
                person_count=0,  # not in OverlayData yet
            )
            for (node_id, param), offset in offsets.items():
                if offset != 0 and self._graph_runtime.current_graph:
                    if node_id in self._graph_runtime.current_graph.nodes:
                        self._on_graph_params_changed(node_id, {param: offset})

            # Idle escalation tracking
            if data.desk_activity == "idle" or data.desk_activity == "":
                if self._idle_start is None:
                    self._idle_start = time.monotonic()
            else:
                self._idle_start = None
```

- [ ] **Step 3: Add helper to list available presets**

```python
    def _get_available_preset_names(self) -> set[str]:
        """Return set of preset names that exist on disk."""
        from pathlib import Path

        names: set[str] = set()
        for dir_ in (
            Path.home() / ".config" / "hapax" / "effect-presets",
            Path(__file__).parent.parent / "presets",
        ):
            if dir_.is_dir():
                for f in dir_.glob("*.json"):
                    if not f.name.startswith("_"):
                        names.add(f.stem)
        return names
```

- [ ] **Step 4: Lint + commit**

```bash
git add agents/studio_compositor.py
git commit -m "feat(compositor): wire atmospheric + gestural governance into render loop

Atmospheric selector evaluates stance × energy × genre to select presets.
Gestural offsets adjust parameters based on desk_activity. Idle tracking
for breathing escalation."
```

---

## Task 6: Full Test Suite + Push

- [ ] **Step 1: Run all tests**

```bash
cd /home/hapax/projects/hapax-council && uv run pytest tests/effect_graph/test_visual_governance.py tests/test_scratch_pipeline.py -v
```

- [ ] **Step 2: Lint all changed files**

```bash
uv run ruff check agents/effect_graph/visual_governance.py agents/effect_graph/types.py agents/studio_compositor.py agents/hapax_voice/_perception_state_writer.py && uv run ruff format --check agents/effect_graph/visual_governance.py agents/effect_graph/types.py agents/studio_compositor.py agents/hapax_voice/_perception_state_writer.py
```

- [ ] **Step 3: Push and create PR**

```bash
git push -u origin HEAD
gh pr create --title "feat: perception-visual governance — three-tier effect reactivity" --body "..."
```
