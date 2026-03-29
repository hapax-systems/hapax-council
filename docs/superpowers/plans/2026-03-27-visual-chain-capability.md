# Visual Chain Capability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a `VisualChainCapability` that maps the same 9 semantic dimensions as the vocal chain to wgpu shader uniforms, enabling cross-modal impingement activation of both voice and visual expression.

**Architecture:** Parallel capability class (`visual_chain.py`) with `ParameterMapping` objects targeting wgpu technique uniforms via `/dev/shm`. The Rust `StateReader` reads chain state and applies additive deltas to smoothed ambient params. Qdrant `CapabilityRecord` entries enable affordance-pipeline recruitment alongside `vocal_chain.*`.

**Tech Stack:** Python 3.12, Pydantic, Qdrant, Rust/wgpu (state.rs only), serde_json, pytest

---

## File Structure

| File | Responsibility |
|------|---------------|
| `agents/visual_chain.py` | `ParameterMapping`, `VisualDimension`, 9 dimension definitions, `VISUAL_CHAIN_RECORDS`, `VisualChainCapability` class |
| `tests/test_visual_chain.py` | Unit tests for interpolation, dimensions, activation, decay, shm output |
| `hapax-logos/src-tauri/src/visual/state.rs` | Read `/dev/shm/hapax-visual/visual-chain-state.json`, apply additive deltas to `SmoothedParams` |

---

### Task 1: ParameterMapping and Interpolation

**Files:**
- Create: `agents/visual_chain.py`
- Create: `tests/test_visual_chain.py`

- [ ] **Step 1: Write the failing test for piecewise linear interpolation**

```python
# tests/test_visual_chain.py
"""Tests for the visual chain capability — semantic visual expression."""

from agents.visual_chain import ParameterMapping, param_value_from_level


def test_param_value_at_zero():
    mapping = ParameterMapping(
        technique="gradient",
        param="brightness",
        breakpoints=[(0.0, 0.0), (0.5, 0.15), (1.0, 0.40)],
    )
    assert param_value_from_level(0.0, mapping.breakpoints) == 0.0


def test_param_value_at_midpoint():
    mapping = ParameterMapping(
        technique="gradient",
        param="brightness",
        breakpoints=[(0.0, 0.0), (0.5, 0.15), (1.0, 0.40)],
    )
    result = param_value_from_level(0.5, mapping.breakpoints)
    assert abs(result - 0.15) < 0.001


def test_param_value_interpolates():
    mapping = ParameterMapping(
        technique="gradient",
        param="brightness",
        breakpoints=[(0.0, 0.0), (1.0, 1.0)],
    )
    result = param_value_from_level(0.25, mapping.breakpoints)
    assert abs(result - 0.25) < 0.001


def test_param_value_clamps_below():
    mapping = ParameterMapping(
        technique="gradient",
        param="brightness",
        breakpoints=[(0.0, 0.0), (1.0, 1.0)],
    )
    assert param_value_from_level(-0.5, mapping.breakpoints) == 0.0


def test_param_value_clamps_above():
    mapping = ParameterMapping(
        technique="gradient",
        param="brightness",
        breakpoints=[(0.0, 0.0), (1.0, 1.0)],
    )
    assert param_value_from_level(1.5, mapping.breakpoints) == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_visual_chain.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.visual_chain'`

- [ ] **Step 3: Write ParameterMapping and interpolation**

```python
# agents/visual_chain.py
"""Visual chain capability — semantic visual affordances for wgpu shader modulation.

Nine expressive dimensions (same as vocal chain) mapped to wgpu technique
uniforms instead of MIDI CCs. Registered in Qdrant for cross-modal
impingement activation alongside vocal_chain.*.
"""

from __future__ import annotations

import json
import logging
import time as time_mod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shared.affordance import CapabilityRecord, OperationalProperties
from shared.impingement import Impingement

log = logging.getLogger(__name__)

SHM_PATH = Path("/dev/shm/hapax-visual/visual-chain-state.json")
SHM_TMP_PATH = Path("/dev/shm/hapax-visual/visual-chain-state.json.tmp")


@dataclass(frozen=True)
class ParameterMapping:
    """Maps an activation level to a specific wgpu technique uniform."""

    technique: str  # "gradient", "rd", "physarum", "compositor", "postprocess"
    param: str  # uniform name
    breakpoints: list[tuple[float, float]]  # (level, param_value)


@dataclass(frozen=True)
class VisualDimension:
    """A semantic visual modulation dimension."""

    name: str
    description: str
    parameter_mappings: list[ParameterMapping]


def param_value_from_level(level: float, breakpoints: list[tuple[float, float]]) -> float:
    """Interpolate parameter value from activation level using piecewise linear breakpoints."""
    level = max(0.0, min(1.0, level))
    if level <= breakpoints[0][0]:
        return breakpoints[0][1]
    if level >= breakpoints[-1][0]:
        return breakpoints[-1][1]
    for i in range(len(breakpoints) - 1):
        l0, v0 = breakpoints[i]
        l1, v1 = breakpoints[i + 1]
        if l0 <= level <= l1:
            t = (level - l0) / (l1 - l0) if l1 != l0 else 0.0
            return v0 + t * (v1 - v0)
    return breakpoints[-1][1]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_visual_chain.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add agents/visual_chain.py tests/test_visual_chain.py
git commit -m "feat(visual-chain): ParameterMapping and piecewise linear interpolation"
```

---

### Task 2: Define the 9 Visual Dimensions

**Files:**
- Modify: `agents/visual_chain.py`
- Modify: `tests/test_visual_chain.py`

- [ ] **Step 1: Write the failing test for dimension definitions**

Add to `tests/test_visual_chain.py`:

```python
from agents.visual_chain import VISUAL_DIMENSIONS


def test_nine_dimensions_defined():
    assert len(VISUAL_DIMENSIONS) == 9


def test_all_dimensions_have_visual_chain_prefix():
    for name in VISUAL_DIMENSIONS:
        assert name.startswith("visual_chain."), f"{name} missing prefix"


def test_all_dimensions_have_mappings():
    for name, dim in VISUAL_DIMENSIONS.items():
        assert len(dim.parameter_mappings) > 0, f"{name} has no mappings"


def test_all_breakpoints_start_at_zero_delta():
    """At level 0.0, every mapping must produce 0.0 (no change from baseline)."""
    for name, dim in VISUAL_DIMENSIONS.items():
        for m in dim.parameter_mappings:
            val = param_value_from_level(0.0, m.breakpoints)
            assert val == 0.0, (
                f"{name}/{m.technique}.{m.param}: level=0.0 should produce 0.0, got {val}"
            )


def test_dimension_names_match_vocal_chain():
    expected_suffixes = {
        "intensity", "tension", "diffusion", "degradation", "depth",
        "pitch_displacement", "temporal_distortion", "spectral_color", "coherence",
    }
    actual_suffixes = {name.split(".", 1)[1] for name in VISUAL_DIMENSIONS}
    assert actual_suffixes == expected_suffixes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_visual_chain.py -v`
Expected: FAIL with `ImportError` for `VISUAL_DIMENSIONS`

- [ ] **Step 3: Add the 9 dimension definitions**

Add to `agents/visual_chain.py` after the `param_value_from_level` function:

```python
# ---------------------------------------------------------------------------
# Reusable breakpoint curves (all produce 0.0 at level=0.0)
# ---------------------------------------------------------------------------

_GENTLE = [(0.0, 0.0), (0.25, 0.05), (0.50, 0.15), (0.75, 0.30), (1.0, 0.50)]
_STANDARD = [(0.0, 0.0), (0.25, 0.10), (0.50, 0.25), (0.75, 0.50), (1.0, 1.0)]
_AGGRESSIVE = [(0.0, 0.0), (0.25, 0.15), (0.50, 0.40), (0.75, 0.70), (1.0, 1.0)]
_INVERTED = [(0.0, 0.0), (0.50, -0.10), (1.0, -0.30)]

# ---------------------------------------------------------------------------
# The 9 visual dimensions — same semantics as vocal_chain.*
# All breakpoint values are ADDITIVE DELTAS on top of ambient baseline.
# ---------------------------------------------------------------------------

VISUAL_DIMENSIONS: dict[str, VisualDimension] = {
    "visual_chain.intensity": VisualDimension(
        name="visual_chain.intensity",
        description=(
            "Increases visual energy and density. Display becomes brighter, more "
            "saturated, more present. Distinct from emotional valence — pure energy."
        ),
        parameter_mappings=[
            ParameterMapping("gradient", "brightness", _STANDARD),
            ParameterMapping("compositor", "opacity_rd",
                             [(0.0, 0.0), (0.5, 0.1), (1.0, 0.3)]),
            ParameterMapping("postprocess", "vignette_strength", _INVERTED),
        ],
    ),
    "visual_chain.tension": VisualDimension(
        name="visual_chain.tension",
        description=(
            "Constricts visual patterns. Display tightens, sharpens, builds angular "
            "energy. Turing patterns become finer, waves increase frequency."
        ),
        parameter_mappings=[
            ParameterMapping("rd", "f_delta",
                             [(0.0, 0.0), (0.5, 0.005), (1.0, 0.015)]),
            ParameterMapping("compositor", "opacity_wave",
                             [(0.0, 0.0), (0.5, 0.1), (1.0, 0.3)]),
            ParameterMapping("gradient", "turbulence",
                             [(0.0, 0.0), (0.5, -0.03), (1.0, -0.06)]),
        ],
    ),
    "visual_chain.diffusion": VisualDimension(
        name="visual_chain.diffusion",
        description=(
            "Scatters visual output across spatial field. Patterns become ambient, "
            "sourceless, environmental. Structure dissolves into texture at high levels."
        ),
        parameter_mappings=[
            ParameterMapping("physarum", "sensor_dist",
                             [(0.0, 0.0), (0.5, 4.0), (1.0, 12.0)]),
            ParameterMapping("rd", "da_delta",
                             [(0.0, 0.0), (0.5, 0.05), (1.0, 0.2)]),
            ParameterMapping("compositor", "opacity_feedback",
                             [(0.0, 0.0), (0.5, 0.08), (1.0, 0.2)]),
        ],
    ),
    "visual_chain.degradation": VisualDimension(
        name="visual_chain.degradation",
        description=(
            "Corrupts visual signal. Display fractures into noise, disruption, "
            "broken pattern. System malfunction expressed through visual artifacts."
        ),
        parameter_mappings=[
            ParameterMapping("physarum", "deposit_amount",
                             [(0.0, 0.0), (0.5, 2.0), (1.0, 6.0)]),
            ParameterMapping("compositor", "opacity_physarum",
                             [(0.0, 0.0), (0.5, 0.05), (1.0, 0.15)]),
            ParameterMapping("postprocess", "sediment_height",
                             [(0.0, 0.0), (0.5, 0.02), (1.0, 0.08)]),
        ],
    ),
    "visual_chain.depth": VisualDimension(
        name="visual_chain.depth",
        description=(
            "Places visual in recessive space. Display darkens, recedes, "
            "becomes distant and cave-like. Vignette intensifies."
        ),
        parameter_mappings=[
            ParameterMapping("gradient", "brightness", _INVERTED),
            ParameterMapping("postprocess", "vignette_strength", _STANDARD),
            ParameterMapping("compositor", "opacity_feedback",
                             [(0.0, 0.0), (0.5, 0.08), (1.0, 0.2)]),
        ],
    ),
    "visual_chain.pitch_displacement": VisualDimension(
        name="visual_chain.pitch_displacement",
        description=(
            "Shifts visual color away from natural register. Hue rotates, "
            "colors become displaced and uncanny without changing brightness."
        ),
        parameter_mappings=[
            ParameterMapping("gradient", "hue_offset",
                             [(0.0, 0.0), (0.5, 25.0), (1.0, 70.0)]),
            ParameterMapping("feedback", "hue_shift",
                             [(0.0, 0.0), (0.5, 1.5), (1.0, 5.0)]),
            ParameterMapping("gradient", "chroma_boost",
                             [(0.0, 0.0), (0.5, 0.02), (1.0, 0.05)]),
        ],
    ),
    "visual_chain.temporal_distortion": VisualDimension(
        name="visual_chain.temporal_distortion",
        description=(
            "Stretches or accelerates visual animation in time. Patterns elongate, "
            "slow, or rush. Temporal continuity shifts."
        ),
        parameter_mappings=[
            ParameterMapping("gradient", "speed",
                             [(0.0, 0.0), (0.3, -0.03), (0.7, 0.0), (1.0, 0.15)]),
            ParameterMapping("physarum", "move_speed",
                             [(0.0, 0.0), (0.3, -0.3), (0.7, 0.0), (1.0, 1.5)]),
        ],
    ),
    "visual_chain.spectral_color": VisualDimension(
        name="visual_chain.spectral_color",
        description=(
            "Shifts visual warmth and saturation. Display becomes cooler or warmer, "
            "more or less chromatic. Tonal character changes."
        ),
        parameter_mappings=[
            ParameterMapping("gradient", "color_warmth",
                             [(0.0, 0.0), (0.5, 0.25), (1.0, 0.6)]),
            ParameterMapping("gradient", "chroma_boost",
                             [(0.0, 0.0), (0.5, 0.02), (1.0, 0.06)]),
        ],
    ),
    "visual_chain.coherence": VisualDimension(
        name="visual_chain.coherence",
        description=(
            "Controls pattern regularity. Master axis from structured to dissolved. "
            "Affects overall visual turbulence and pattern stability."
        ),
        parameter_mappings=[
            ParameterMapping("gradient", "turbulence", _STANDARD),
            ParameterMapping("rd", "f_delta",
                             [(0.0, 0.0), (0.5, -0.005), (1.0, -0.015)]),
            ParameterMapping("physarum", "turn_speed",
                             [(0.0, 0.0), (0.5, 0.15), (1.0, 0.5)]),
        ],
    ),
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_visual_chain.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add agents/visual_chain.py tests/test_visual_chain.py
git commit -m "feat(visual-chain): define 9 visual dimensions with parameter mappings"
```

---

### Task 3: CapabilityRecord Registration

**Files:**
- Modify: `agents/visual_chain.py`
- Modify: `tests/test_visual_chain.py`

- [ ] **Step 1: Write the failing test for capability records**

Add to `tests/test_visual_chain.py`:

```python
from agents.visual_chain import VISUAL_CHAIN_RECORDS


def test_nine_capability_records():
    assert len(VISUAL_CHAIN_RECORDS) == 9


def test_records_use_visual_layer_aggregator_daemon():
    for rec in VISUAL_CHAIN_RECORDS:
        assert rec.daemon == "visual_layer_aggregator"


def test_records_are_realtime_latency():
    for rec in VISUAL_CHAIN_RECORDS:
        assert rec.operational.latency_class == "realtime"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_visual_chain.py::test_nine_capability_records -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Add capability records**

Add to `agents/visual_chain.py` after `VISUAL_DIMENSIONS`:

```python
# CapabilityRecords for Qdrant indexing
VISUAL_CHAIN_RECORDS = [
    CapabilityRecord(
        name=dim.name,
        description=dim.description,
        daemon="visual_layer_aggregator",
        operational=OperationalProperties(latency_class="realtime"),
    )
    for dim in VISUAL_DIMENSIONS.values()
]

# Affordance keywords for can_resolve matching
VISUAL_CHAIN_AFFORDANCES = {
    "visual_modulation",
    "stimmung_shift",
    "visual_character",
    "display_texture",
    "ambient_expression",
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_visual_chain.py -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add agents/visual_chain.py tests/test_visual_chain.py
git commit -m "feat(visual-chain): Qdrant capability records for 9 visual dimensions"
```

---

### Task 4: VisualChainCapability Class

**Files:**
- Modify: `agents/visual_chain.py`
- Modify: `tests/test_visual_chain.py`

- [ ] **Step 1: Write the failing tests for capability activation and decay**

Add to `tests/test_visual_chain.py`:

```python
from unittest.mock import MagicMock

from agents.visual_chain import VisualChainCapability, VISUAL_DIMENSIONS
from shared.impingement import Impingement, ImpingementType


def _make_impingement(strength: float = 0.6, source: str = "dmn.evaluative") -> Impingement:
    return Impingement(
        id="test-001",
        timestamp=0.0,
        source=source,
        type=ImpingementType.SALIENCE_INTEGRATION,
        strength=strength,
        content={"metric": "stimmung_shift", "trajectory": "degrading"},
        context={},
        interrupt_token=None,
        embedding=None,
    )


def test_capability_initial_levels_are_zero():
    cap = VisualChainCapability()
    for name in VISUAL_DIMENSIONS:
        assert cap.get_dimension_level(name) == 0.0


def test_activate_dimension_sets_level():
    cap = VisualChainCapability()
    imp = _make_impingement(strength=0.6)
    cap.activate_dimension("visual_chain.intensity", imp, 0.6)
    assert cap.get_dimension_level("visual_chain.intensity") == 0.6


def test_activate_dimension_clamps_to_unit():
    cap = VisualChainCapability()
    imp = _make_impingement(strength=1.5)
    cap.activate_dimension("visual_chain.intensity", imp, 1.5)
    assert cap.get_dimension_level("visual_chain.intensity") == 1.0


def test_decay_reduces_levels():
    cap = VisualChainCapability(decay_rate=0.1)
    imp = _make_impingement()
    cap.activate_dimension("visual_chain.intensity", imp, 0.5)
    cap.decay(1.0)  # 1 second at 0.1/s = 0.1 reduction
    assert abs(cap.get_dimension_level("visual_chain.intensity") - 0.4) < 0.001


def test_decay_does_not_go_below_zero():
    cap = VisualChainCapability(decay_rate=1.0)
    imp = _make_impingement()
    cap.activate_dimension("visual_chain.intensity", imp, 0.1)
    cap.decay(10.0)
    assert cap.get_dimension_level("visual_chain.intensity") == 0.0


def test_deactivate_resets_all():
    cap = VisualChainCapability()
    imp = _make_impingement()
    cap.activate_dimension("visual_chain.intensity", imp, 0.8)
    cap.activate_dimension("visual_chain.tension", imp, 0.5)
    cap.deactivate()
    for name in VISUAL_DIMENSIONS:
        assert cap.get_dimension_level(name) == 0.0


def test_compute_deltas_at_zero_is_empty():
    cap = VisualChainCapability()
    deltas = cap.compute_param_deltas()
    assert all(v == 0.0 for v in deltas.values())


def test_compute_deltas_at_nonzero():
    cap = VisualChainCapability()
    imp = _make_impingement()
    cap.activate_dimension("visual_chain.intensity", imp, 1.0)
    deltas = cap.compute_param_deltas()
    # gradient.brightness should have a positive delta at level=1.0
    assert deltas.get("gradient.brightness", 0.0) > 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_visual_chain.py::test_capability_initial_levels_are_zero -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement VisualChainCapability**

Add to `agents/visual_chain.py`:

```python
class VisualChainCapability:
    """Visual chain as a Capability — recruited for expressive visual modulation."""

    def __init__(self, decay_rate: float = 0.02) -> None:
        self._decay_rate = decay_rate
        self._levels: dict[str, float] = {name: 0.0 for name in VISUAL_DIMENSIONS}
        self._activation_level = 0.0

    @property
    def name(self) -> str:
        return "visual_chain"

    @property
    def affordance_signature(self) -> set[str]:
        return VISUAL_CHAIN_AFFORDANCES

    @property
    def activation_cost(self) -> float:
        return 0.01  # shm write is nearly free

    @property
    def activation_level(self) -> float:
        return self._activation_level

    @property
    def consent_required(self) -> bool:
        return False

    @property
    def priority_floor(self) -> bool:
        return False

    def can_resolve(self, impingement: Impingement) -> float:
        """Match impingements that warrant visual modulation."""
        content = impingement.content
        metric = content.get("metric", "")

        if any(aff in metric for aff in VISUAL_CHAIN_AFFORDANCES):
            return impingement.strength

        if "stimmung" in impingement.source:
            return impingement.strength * 0.4

        if "dmn.evaluative" in impingement.source:
            return impingement.strength * 0.3

        return 0.0

    def activate(self, impingement: Impingement, level: float) -> dict[str, Any]:
        """Activate visual chain — sets activation level for cascade tracking."""
        self._activation_level = level
        log.info(
            "Visual chain activated: %s (strength=%.2f, level=%.2f)",
            impingement.content.get("metric", impingement.source),
            impingement.strength,
            level,
        )
        return {"visual_chain_activated": True, "level": level}

    def activate_dimension(
        self, dimension_name: str, impingement: Impingement, level: float
    ) -> None:
        """Activate a specific dimension and recompute parameter deltas."""
        if dimension_name not in VISUAL_DIMENSIONS:
            log.debug("Unknown visual dimension: %s", dimension_name)
            return

        self._levels[dimension_name] = max(0.0, min(1.0, level))
        self._activation_level = max(self._levels.values())

    def get_dimension_level(self, dimension_name: str) -> float:
        """Get the current activation level of a dimension."""
        return self._levels.get(dimension_name, 0.0)

    def compute_param_deltas(self) -> dict[str, float]:
        """Compute additive parameter deltas from all active dimensions.

        Returns a dict of "technique.param" → delta_value. Multiple dimensions
        contributing to the same param are summed.
        """
        deltas: dict[str, float] = {}
        for dim_name, dim in VISUAL_DIMENSIONS.items():
            level = self._levels.get(dim_name, 0.0)
            if level == 0.0:
                continue
            for mapping in dim.parameter_mappings:
                key = f"{mapping.technique}.{mapping.param}"
                delta = param_value_from_level(level, mapping.breakpoints)
                deltas[key] = deltas.get(key, 0.0) + delta
        return deltas

    def decay(self, elapsed_s: float) -> None:
        """Decay all active dimensions toward zero."""
        amount = self._decay_rate * elapsed_s
        any_active = False
        for name in self._levels:
            if self._levels[name] > 0.0:
                self._levels[name] = max(0.0, self._levels[name] - amount)
                if self._levels[name] > 0.0:
                    any_active = True

        self._activation_level = max(self._levels.values()) if any_active else 0.0

    def deactivate(self) -> None:
        """Reset all dimensions to zero."""
        for name in self._levels:
            self._levels[name] = 0.0
        self._activation_level = 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_visual_chain.py -v`
Expected: 22 passed

- [ ] **Step 5: Commit**

```bash
git add agents/visual_chain.py tests/test_visual_chain.py
git commit -m "feat(visual-chain): VisualChainCapability with activation, decay, param deltas"
```

---

### Task 5: SHM Output

**Files:**
- Modify: `agents/visual_chain.py`
- Modify: `tests/test_visual_chain.py`

- [ ] **Step 1: Write the failing test for shm output**

Add to `tests/test_visual_chain.py`:

```python
import json
from pathlib import Path


def test_write_state_creates_json(tmp_path: Path):
    cap = VisualChainCapability()
    imp = _make_impingement()
    cap.activate_dimension("visual_chain.intensity", imp, 0.7)

    out_path = tmp_path / "visual-chain-state.json"
    cap.write_state(out_path)

    assert out_path.exists()
    data = json.loads(out_path.read_text())
    assert "levels" in data
    assert "params" in data
    assert "timestamp" in data
    assert data["levels"]["visual_chain.intensity"] == 0.7
    assert data["params"]["gradient.brightness"] > 0.0


def test_write_state_atomic(tmp_path: Path):
    """Write uses tmp+rename for atomic update."""
    cap = VisualChainCapability()
    out_path = tmp_path / "visual-chain-state.json"
    cap.write_state(out_path)
    # File should exist and be valid JSON even if read mid-write
    assert json.loads(out_path.read_text())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_visual_chain.py::test_write_state_creates_json -v`
Expected: FAIL with `AttributeError: 'VisualChainCapability' object has no attribute 'write_state'`

- [ ] **Step 3: Implement write_state**

Add to `VisualChainCapability` class in `agents/visual_chain.py`:

```python
    def write_state(self, path: Path | None = None) -> None:
        """Write current state to shm as JSON (atomic tmp+rename)."""
        path = path or SHM_PATH
        tmp_path = path.with_suffix(".json.tmp")

        state = {
            "levels": {k: round(v, 4) for k, v in self._levels.items() if v > 0.0},
            "params": {k: round(v, 6) for k, v in self.compute_param_deltas().items()},
            "timestamp": time_mod.time(),
        }

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(json.dumps(state))
        tmp_path.rename(path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_visual_chain.py -v`
Expected: 24 passed

- [ ] **Step 5: Commit**

```bash
git add agents/visual_chain.py tests/test_visual_chain.py
git commit -m "feat(visual-chain): atomic shm JSON output for wgpu state reader"
```

---

### Task 6: Rust StateReader Extension

**Files:**
- Modify: `hapax-logos/src-tauri/src/visual/state.rs`

- [ ] **Step 1: Add the visual chain state struct and shm path**

Add to `state.rs` after the `CONTROL_PATH` constant:

```rust
const VISUAL_CHAIN_PATH: &str = "/dev/shm/hapax-visual/visual-chain-state.json";

#[derive(Debug, Clone, Default, Deserialize)]
struct VisualChainState {
    #[serde(default)]
    params: HashMap<String, f64>,
    #[serde(default)]
    timestamp: f64,
}
```

- [ ] **Step 2: Add chain_deltas to SmoothedParams**

Add a new field to `SmoothedParams`:

```rust
    // Visual chain additive deltas (from impingement activation)
    pub chain_deltas: HashMap<String, f32>,
```

And in `Default for SmoothedParams`:

```rust
            chain_deltas: HashMap::new(),
```

- [ ] **Step 3: Read visual chain state in poll_now**

Add to `StateReader::poll_now()` after the control.json read:

```rust
        // Read visual chain state for impingement-driven deltas
        if let Some(chain) = Self::read_json::<VisualChainState>(VISUAL_CHAIN_PATH) {
            self.smoothed.chain_deltas = chain
                .params
                .into_iter()
                .map(|(k, v)| (k, v as f32))
                .collect();
        }
```

- [ ] **Step 4: Apply chain deltas in lerp_toward**

Modify `SmoothedParams::lerp_toward` to apply chain deltas after baseline lerp. Add at the end of the method, before the transition progress block:

```rust
        // Apply visual chain additive deltas (impingement-driven expression)
        if let Some(&d) = self.chain_deltas.get("gradient.brightness") {
            self.brightness += d;
        }
        if let Some(&d) = self.chain_deltas.get("gradient.speed") {
            self.speed += d;
        }
        if let Some(&d) = self.chain_deltas.get("gradient.turbulence") {
            self.turbulence += d;
        }
        if let Some(&d) = self.chain_deltas.get("gradient.color_warmth") {
            self.color_warmth = (self.color_warmth + d).clamp(0.0, 1.0);
        }
        if let Some(&d) = self.chain_deltas.get("gradient.hue_offset") {
            self.env_hue_shift += d;
        }
        if let Some(&d) = self.chain_deltas.get("gradient.chroma_boost") {
            self.env_chroma_scale += d;
        }
        if let Some(&d) = self.chain_deltas.get("postprocess.vignette_strength") {
            // Will be read by postprocess update_uniforms once wired
        }
```

- [ ] **Step 5: Verify compilation**

Run: `cd ~/projects/hapax-council--beta/hapax-logos && cargo clean -p hapax-logos --manifest-path src-tauri/Cargo.toml && cargo check --manifest-path src-tauri/Cargo.toml`
Expected: compiles with warnings only

- [ ] **Step 6: Commit**

```bash
git add hapax-logos/src-tauri/src/visual/state.rs
git commit -m "feat(visual-chain): Rust StateReader reads visual-chain-state.json, applies additive deltas"
```

---

### Task 7: Integration Test

**Files:**
- Modify: `tests/test_visual_chain.py`

- [ ] **Step 1: Write end-to-end integration test**

Add to `tests/test_visual_chain.py`:

```python
def test_full_activation_cycle(tmp_path: Path):
    """Full cycle: activate → compute deltas → write shm → decay → write again."""
    cap = VisualChainCapability(decay_rate=0.5)
    imp = _make_impingement(strength=0.8)
    out_path = tmp_path / "visual-chain-state.json"

    # Activate intensity and tension
    cap.activate_dimension("visual_chain.intensity", imp, 0.8)
    cap.activate_dimension("visual_chain.tension", imp, 0.4)

    # Write state
    cap.write_state(out_path)
    data = json.loads(out_path.read_text())
    assert data["levels"]["visual_chain.intensity"] == 0.8
    assert data["levels"]["visual_chain.tension"] == 0.4
    assert len(data["params"]) > 0

    # Decay 1 second
    cap.decay(1.0)
    assert cap.get_dimension_level("visual_chain.intensity") == 0.3
    assert cap.activation_level > 0.0

    # Write updated state
    cap.write_state(out_path)
    data2 = json.loads(out_path.read_text())
    assert data2["levels"]["visual_chain.intensity"] == 0.3

    # Decay to zero
    cap.decay(10.0)
    assert cap.activation_level == 0.0

    # Write zero state — params should all be zero
    cap.write_state(out_path)
    data3 = json.loads(out_path.read_text())
    assert len(data3["levels"]) == 0
    assert all(v == 0.0 for v in data3["params"].values()) or len(data3["params"]) == 0
```

- [ ] **Step 2: Run all tests**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_visual_chain.py -v`
Expected: 25 passed

- [ ] **Step 3: Commit**

```bash
git add tests/test_visual_chain.py
git commit -m "test(visual-chain): end-to-end activation cycle integration test"
```
