# Vocal Chain Capability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a capability that indexes MIDI processing parameters as semantic affordances in Qdrant, recruited through the impingement cascade, translating activation levels to MIDI CC messages on the Evil Pet and Torso S-4.

**Architecture:** Nine semantic dimensions (intensity, tension, diffusion, etc.) are indexed as independent `CapabilityRecord`s in Qdrant. A single `VocalChainCapability` class manages hold-and-decay activation state for all dimensions. A thin `MidiOutput` wrapper sends CC messages via mido. Registration follows the fortress/speech capability pattern in the voice daemon.

**Tech Stack:** mido + python-rtmidi (already in deps), Qdrant affordances collection (existing), Capability protocol (existing).

**Spec:** `docs/superpowers/specs/2026-03-27-vocal-chain-capability-design.md`

---

### Task 1: MidiOutput — thin mido wrapper

**Files:**
- Create: `agents/hapax_voice/midi_output.py`
- Test: `tests/test_midi_output.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for MidiOutput — thin mido wrapper for MIDI CC sending."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.hapax_voice.midi_output import MidiOutput


class TestMidiOutputInit:
    def test_lazy_init_no_port_opened(self) -> None:
        out = MidiOutput()
        assert out._port is None

    def test_port_name_stored(self) -> None:
        out = MidiOutput(port_name="Evil Pet")
        assert out._port_name == "Evil Pet"


class TestMidiOutputSendCC:
    def test_send_cc_opens_port_and_sends(self) -> None:
        mock_port = MagicMock()
        with patch("agents.hapax_voice.midi_output.mido") as mock_mido:
            mock_mido.open_output.return_value = mock_port
            mock_msg = MagicMock()
            mock_mido.Message.return_value = mock_msg

            out = MidiOutput(port_name="Evil Pet")
            out.send_cc(channel=0, cc=42, value=64)

            mock_mido.open_output.assert_called_once_with("Evil Pet")
            mock_mido.Message.assert_called_once_with(
                "control_change", channel=0, control=42, value=64
            )
            mock_port.send.assert_called_once_with(mock_msg)

    def test_send_cc_reuses_port(self) -> None:
        mock_port = MagicMock()
        with patch("agents.hapax_voice.midi_output.mido") as mock_mido:
            mock_mido.open_output.return_value = mock_port
            mock_mido.Message.return_value = MagicMock()

            out = MidiOutput(port_name="Test")
            out.send_cc(channel=0, cc=1, value=10)
            out.send_cc(channel=0, cc=2, value=20)

            mock_mido.open_output.assert_called_once()

    def test_send_cc_clamps_value(self) -> None:
        mock_port = MagicMock()
        with patch("agents.hapax_voice.midi_output.mido") as mock_mido:
            mock_mido.open_output.return_value = mock_port
            mock_mido.Message.return_value = MagicMock()

            out = MidiOutput()
            out.send_cc(channel=0, cc=42, value=200)

            mock_mido.Message.assert_called_once_with(
                "control_change", channel=0, control=42, value=127
            )

    def test_send_cc_clamps_negative(self) -> None:
        mock_port = MagicMock()
        with patch("agents.hapax_voice.midi_output.mido") as mock_mido:
            mock_mido.open_output.return_value = mock_port
            mock_mido.Message.return_value = MagicMock()

            out = MidiOutput()
            out.send_cc(channel=0, cc=42, value=-5)

            mock_mido.Message.assert_called_once_with(
                "control_change", channel=0, control=42, value=0
            )


class TestMidiOutputGracefulDegradation:
    def test_port_unavailable_logs_warning(self) -> None:
        with patch("agents.hapax_voice.midi_output.mido") as mock_mido:
            mock_mido.open_output.side_effect = OSError("No MIDI devices")

            out = MidiOutput(port_name="Nonexistent")
            # Should not raise
            out.send_cc(channel=0, cc=42, value=64)
            assert out._port is None

    def test_send_after_failed_init_is_noop(self) -> None:
        with patch("agents.hapax_voice.midi_output.mido") as mock_mido:
            mock_mido.open_output.side_effect = OSError("No MIDI")

            out = MidiOutput()
            out.send_cc(channel=0, cc=1, value=10)  # triggers failed init
            out.send_cc(channel=0, cc=2, value=20)  # should be noop, not retry

            mock_mido.open_output.assert_called_once()


class TestMidiOutputClose:
    def test_close_closes_port(self) -> None:
        mock_port = MagicMock()
        with patch("agents.hapax_voice.midi_output.mido") as mock_mido:
            mock_mido.open_output.return_value = mock_port
            mock_mido.Message.return_value = MagicMock()

            out = MidiOutput()
            out.send_cc(channel=0, cc=1, value=1)  # opens port
            out.close()

            mock_port.close.assert_called_once()
            assert out._port is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/test_midi_output.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.hapax_voice.midi_output'`

- [ ] **Step 3: Write MidiOutput implementation**

```python
"""MidiOutput — thin mido wrapper for sending MIDI CC messages.

Lazy-initializes the MIDI output port on first send. Fails gracefully
if no MIDI hardware is available (logs warning, becomes a no-op).
"""

from __future__ import annotations

import logging

import mido

log = logging.getLogger(__name__)


class MidiOutput:
    """Send MIDI CC messages to external hardware."""

    def __init__(self, port_name: str = "") -> None:
        self._port_name = port_name
        self._port: mido.ports.BaseOutput | None = None
        self._init_failed = False

    def send_cc(self, channel: int, cc: int, value: int) -> None:
        """Send a MIDI Control Change message.

        Args:
            channel: MIDI channel (0-indexed, 0-15).
            cc: CC number (0-127).
            value: CC value (0-127, clamped).
        """
        if self._init_failed:
            return
        if self._port is None:
            self._open_port()
            if self._port is None:
                return

        value = max(0, min(127, value))
        msg = mido.Message("control_change", channel=channel, control=cc, value=value)
        self._port.send(msg)

    def _open_port(self) -> None:
        """Lazy-open the MIDI output port."""
        try:
            name = self._port_name or None  # None = mido picks first available
            self._port = mido.open_output(name)
            log.info("MIDI output opened: %s", self._port.name)
        except (OSError, IOError) as exc:
            log.warning("No MIDI output available (%s) — vocal chain disabled", exc)
            self._init_failed = True

    def close(self) -> None:
        """Close the MIDI output port."""
        if self._port is not None:
            self._port.close()
            self._port = None
```

- [ ] **Step 4: Run tests**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/test_midi_output.py -v`
Expected: All PASS

- [ ] **Step 5: Lint and commit**

```bash
cd /home/hapax/projects/hapax-council
uv run ruff check agents/hapax_voice/midi_output.py tests/test_midi_output.py
uv run ruff format agents/hapax_voice/midi_output.py tests/test_midi_output.py
git add agents/hapax_voice/midi_output.py tests/test_midi_output.py
git commit -m "feat(voice): add MidiOutput — thin mido wrapper for CC sending"
```

---

### Task 2: VocalChainCapability — dimensions, CC mappings, hold-and-decay

**Files:**
- Create: `agents/hapax_voice/vocal_chain.py`
- Test: `tests/test_vocal_chain.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for VocalChainCapability — semantic MIDI affordances for speech modulation."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, call

import pytest

from agents.hapax_voice.vocal_chain import (
    DIMENSIONS,
    VOCAL_CHAIN_RECORDS,
    VocalChainCapability,
    cc_value_from_level,
)
from shared.impingement import Impingement, ImpingementType


def _make_impingement(
    source: str = "stimmung",
    metric: str = "arousal_spike",
    strength: float = 0.7,
) -> Impingement:
    return Impingement(
        timestamp=time.time(),
        source=source,
        type=ImpingementType.STATISTICAL_DEVIATION,
        strength=strength,
        content={"metric": metric},
    )


# ---------------------------------------------------------------------------
# Dimension definitions
# ---------------------------------------------------------------------------


class TestDimensions:
    def test_nine_dimensions_defined(self) -> None:
        assert len(DIMENSIONS) == 9

    def test_each_dimension_has_cc_mappings(self) -> None:
        for dim in DIMENSIONS.values():
            assert len(dim.cc_mappings) >= 2, f"{dim.name} needs at least 2 CC mappings"

    def test_each_dimension_has_description(self) -> None:
        for dim in DIMENSIONS.values():
            assert len(dim.description) > 20, f"{dim.name} needs a meaningful description"

    def test_dimension_names_prefixed(self) -> None:
        for name in DIMENSIONS:
            assert name.startswith("vocal_chain."), f"{name} must be prefixed"


# ---------------------------------------------------------------------------
# CapabilityRecords for Qdrant indexing
# ---------------------------------------------------------------------------


class TestCapabilityRecords:
    def test_nine_records(self) -> None:
        assert len(VOCAL_CHAIN_RECORDS) == 9

    def test_records_match_dimensions(self) -> None:
        record_names = {r.name for r in VOCAL_CHAIN_RECORDS}
        dim_names = set(DIMENSIONS.keys())
        assert record_names == dim_names

    def test_records_have_daemon(self) -> None:
        for r in VOCAL_CHAIN_RECORDS:
            assert r.daemon == "hapax_voice"

    def test_records_not_gpu(self) -> None:
        for r in VOCAL_CHAIN_RECORDS:
            assert not r.operational.requires_gpu


# ---------------------------------------------------------------------------
# CC value mapping
# ---------------------------------------------------------------------------


class TestCCMapping:
    def test_level_zero_returns_transparent(self) -> None:
        # Breakpoints: [(0.0, 0), (0.25, 25), ...] — level 0 = CC 0
        result = cc_value_from_level(0.0, [(0.0, 0), (0.25, 25), (1.0, 127)])
        assert result == 0

    def test_level_one_returns_max(self) -> None:
        result = cc_value_from_level(1.0, [(0.0, 0), (0.5, 64), (1.0, 127)])
        assert result == 127

    def test_interpolation_midpoint(self) -> None:
        result = cc_value_from_level(0.5, [(0.0, 0), (1.0, 100)])
        assert result == 50

    def test_clamps_above_one(self) -> None:
        result = cc_value_from_level(1.5, [(0.0, 0), (1.0, 127)])
        assert result == 127

    def test_clamps_below_zero(self) -> None:
        result = cc_value_from_level(-0.5, [(0.0, 10), (1.0, 127)])
        assert result == 10


# ---------------------------------------------------------------------------
# Capability protocol
# ---------------------------------------------------------------------------


class TestCapabilityProtocol:
    def test_name(self) -> None:
        cap = VocalChainCapability(midi_output=MagicMock())
        assert cap.name == "vocal_chain"

    def test_affordance_signature(self) -> None:
        cap = VocalChainCapability(midi_output=MagicMock())
        sig = cap.affordance_signature
        assert "vocal_modulation" in sig
        assert "stimmung_shift" in sig

    def test_activation_cost_low(self) -> None:
        cap = VocalChainCapability(midi_output=MagicMock())
        assert cap.activation_cost < 0.1  # MIDI is cheap

    def test_consent_not_required(self) -> None:
        cap = VocalChainCapability(midi_output=MagicMock())
        assert not cap.consent_required

    def test_not_priority_floor(self) -> None:
        cap = VocalChainCapability(midi_output=MagicMock())
        assert not cap.priority_floor


# ---------------------------------------------------------------------------
# Activation and MIDI sending
# ---------------------------------------------------------------------------


class TestActivation:
    def test_activate_sets_dimension_level(self) -> None:
        midi = MagicMock()
        cap = VocalChainCapability(midi_output=midi)
        imp = _make_impingement()

        cap.activate_dimension("vocal_chain.intensity", imp, level=0.5)

        assert cap.get_dimension_level("vocal_chain.intensity") == pytest.approx(0.5)

    def test_activate_sends_midi_cc(self) -> None:
        midi = MagicMock()
        cap = VocalChainCapability(midi_output=midi, evil_pet_channel=0, s4_channel=1)
        imp = _make_impingement()

        cap.activate_dimension("vocal_chain.intensity", imp, level=0.5)

        assert midi.send_cc.call_count >= 2  # at least 2 CCs per dimension

    def test_activate_zero_resets_to_transparent(self) -> None:
        midi = MagicMock()
        cap = VocalChainCapability(midi_output=midi)
        imp = _make_impingement()

        cap.activate_dimension("vocal_chain.intensity", imp, level=0.7)
        cap.activate_dimension("vocal_chain.intensity", imp, level=0.0)

        assert cap.get_dimension_level("vocal_chain.intensity") == 0.0

    def test_multiple_dimensions_independent(self) -> None:
        midi = MagicMock()
        cap = VocalChainCapability(midi_output=midi)
        imp = _make_impingement()

        cap.activate_dimension("vocal_chain.intensity", imp, level=0.8)
        cap.activate_dimension("vocal_chain.depth", imp, level=0.3)

        assert cap.get_dimension_level("vocal_chain.intensity") == pytest.approx(0.8)
        assert cap.get_dimension_level("vocal_chain.depth") == pytest.approx(0.3)

    def test_unknown_dimension_ignored(self) -> None:
        midi = MagicMock()
        cap = VocalChainCapability(midi_output=midi)
        imp = _make_impingement()

        cap.activate_dimension("vocal_chain.nonexistent", imp, level=0.5)
        midi.send_cc.assert_not_called()


# ---------------------------------------------------------------------------
# Decay
# ---------------------------------------------------------------------------


class TestDecay:
    def test_decay_reduces_levels(self) -> None:
        midi = MagicMock()
        cap = VocalChainCapability(midi_output=midi, decay_rate=0.1)
        imp = _make_impingement()

        cap.activate_dimension("vocal_chain.intensity", imp, level=1.0)
        cap.decay(elapsed_s=5.0)  # 5s * 0.1/s = 0.5 decay

        assert cap.get_dimension_level("vocal_chain.intensity") == pytest.approx(0.5)

    def test_decay_floors_at_zero(self) -> None:
        midi = MagicMock()
        cap = VocalChainCapability(midi_output=midi, decay_rate=0.1)
        imp = _make_impingement()

        cap.activate_dimension("vocal_chain.intensity", imp, level=0.2)
        cap.decay(elapsed_s=10.0)  # would go to -0.8, clamped to 0

        assert cap.get_dimension_level("vocal_chain.intensity") == 0.0

    def test_decay_sends_updated_cc(self) -> None:
        midi = MagicMock()
        cap = VocalChainCapability(midi_output=midi, decay_rate=0.1)
        imp = _make_impingement()

        cap.activate_dimension("vocal_chain.intensity", imp, level=1.0)
        midi.reset_mock()

        cap.decay(elapsed_s=5.0)

        assert midi.send_cc.call_count >= 2  # sends updated CCs for active dimensions

    def test_decay_skips_already_zero(self) -> None:
        midi = MagicMock()
        cap = VocalChainCapability(midi_output=midi, decay_rate=0.1)

        cap.decay(elapsed_s=5.0)  # nothing active

        midi.send_cc.assert_not_called()


# ---------------------------------------------------------------------------
# Deactivate
# ---------------------------------------------------------------------------


class TestDeactivate:
    def test_deactivate_resets_all(self) -> None:
        midi = MagicMock()
        cap = VocalChainCapability(midi_output=midi)
        imp = _make_impingement()

        cap.activate_dimension("vocal_chain.intensity", imp, level=0.8)
        cap.activate_dimension("vocal_chain.depth", imp, level=0.5)
        cap.deactivate()

        assert cap.get_dimension_level("vocal_chain.intensity") == 0.0
        assert cap.get_dimension_level("vocal_chain.depth") == 0.0
        assert cap.activation_level == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/test_vocal_chain.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write VocalChainCapability implementation**

```python
"""Vocal chain capability — semantic MIDI affordances for speech modulation.

Nine expressive dimensions (intensity, tension, diffusion, etc.) indexed
independently in Qdrant. Each dimension maps to CC parameters on the
Evil Pet and Torso S-4. Activation is hold-and-decay: levels persist
until shifted by another impingement or decayed by a timer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from shared.affordance import CapabilityRecord, OperationalProperties
from shared.impingement import Impingement

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CCMapping:
    """Maps an activation level to a specific MIDI CC on a specific device."""

    device: str  # "evil_pet" or "s4"
    cc: int
    # Piecewise linear breakpoints: (level, cc_value)
    # level 0.0 = transparent, 1.0 = noise
    breakpoints: list[tuple[float, int]]


@dataclass(frozen=True)
class Dimension:
    """A semantic vocal modulation dimension."""

    name: str
    description: str
    cc_mappings: list[CCMapping]


def cc_value_from_level(level: float, breakpoints: list[tuple[float, int]]) -> int:
    """Interpolate CC value from activation level using piecewise linear breakpoints."""
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
            return round(v0 + t * (v1 - v0))
    return breakpoints[-1][1]


# ---------------------------------------------------------------------------
# Dimension definitions with CC mappings
# ---------------------------------------------------------------------------

_STD_CURVE = [(0.0, 0), (0.25, 20), (0.50, 50), (0.75, 85), (1.0, 127)]
_GENTLE_CURVE = [(0.0, 0), (0.25, 15), (0.50, 35), (0.75, 65), (1.0, 100)]
_CENTER_CURVE = [(0.0, 64), (0.25, 72), (0.50, 85), (0.75, 105), (1.0, 127)]

DIMENSIONS: dict[str, Dimension] = {
    "vocal_chain.intensity": Dimension(
        name="vocal_chain.intensity",
        description=(
            "Increases vocal energy and density. Speech becomes louder, more present, "
            "more forceful. Distinct from emotional valence — pure physical energy."
        ),
        cc_mappings=[
            CCMapping("evil_pet", 40, _STD_CURVE),  # Mix
            CCMapping("evil_pet", 46, _GENTLE_CURVE),  # Grains
            CCMapping("s4", 69, _STD_CURVE),  # Mosaic Wet
            CCMapping("s4", 63, _GENTLE_CURVE),  # Rate
        ],
    ),
    "vocal_chain.tension": Dimension(
        name="vocal_chain.tension",
        description=(
            "Constricts vocal timbre. Speech sounds strained, tight, forced through "
            "resistance. Harmonics sharpen, resonance builds. Distinct from volume."
        ),
        cc_mappings=[
            CCMapping("evil_pet", 71, _STD_CURVE),  # Filter Res
            CCMapping("evil_pet", 39, _GENTLE_CURVE),  # Saturator
            CCMapping("s4", 79, _STD_CURVE),  # Ring Res
            CCMapping("s4", 94, _GENTLE_CURVE),  # Deform Drive
        ],
    ),
    "vocal_chain.diffusion": Dimension(
        name="vocal_chain.diffusion",
        description=(
            "Scatters vocal output across spatial field. Speech becomes ambient, "
            "sourceless, environmental. Words dissolve into texture at high levels."
        ),
        cc_mappings=[
            CCMapping("evil_pet", 42, _STD_CURVE),  # Spread
            CCMapping("evil_pet", 43, _GENTLE_CURVE),  # Cloud
            CCMapping("s4", 67, _STD_CURVE),  # Spray
            CCMapping("s4", 66, _GENTLE_CURVE),  # Warp
        ],
    ),
    "vocal_chain.degradation": Dimension(
        name="vocal_chain.degradation",
        description=(
            "Corrupts vocal signal. Speech fractures into digital artifacts, "
            "broken transmission, static. System malfunction expressed through voice."
        ),
        cc_mappings=[
            CCMapping("evil_pet", 39, _STD_CURVE),  # Saturator amount
            CCMapping("evil_pet", 84, [(0.0, 0), (0.5, 80), (1.0, 110)]),  # Sat type → crush
            CCMapping("s4", 96, _STD_CURVE),  # Crush
            CCMapping("s4", 98, _GENTLE_CURVE),  # Noise
        ],
    ),
    "vocal_chain.depth": Dimension(
        name="vocal_chain.depth",
        description=(
            "Places voice in reverberant space. Distant, cathedral-like, submerged. "
            "Speech recedes from foreground without losing content at low levels."
        ),
        cc_mappings=[
            CCMapping("evil_pet", 91, _STD_CURVE),  # Reverb amount
            CCMapping("evil_pet", 93, _GENTLE_CURVE),  # Reverb tail
            CCMapping("s4", 112, _STD_CURVE),  # Vast Reverb
            CCMapping("s4", 113, _GENTLE_CURVE),  # Vast Size
        ],
    ),
    "vocal_chain.pitch_displacement": Dimension(
        name="vocal_chain.pitch_displacement",
        description=(
            "Shifts vocal pitch away from natural register. Higher, lower, or "
            "unstable. Uncanny displacement without volume or timbre change."
        ),
        cc_mappings=[
            CCMapping("evil_pet", 44, _CENTER_CURVE),  # Pitch (center = neutral)
            CCMapping("s4", 62, _CENTER_CURVE),  # Mosaic Pitch
            CCMapping("s4", 68, _GENTLE_CURVE),  # Pattern (melodic scatter)
        ],
    ),
    "vocal_chain.temporal_distortion": Dimension(
        name="vocal_chain.temporal_distortion",
        description=(
            "Stretches, freezes, or stutters speech in time. Words elongate, "
            "fragment, or loop. Temporal continuity breaks down."
        ),
        cc_mappings=[
            CCMapping("evil_pet", 50, [(0.0, 100), (0.5, 60), (1.0, 10)]),  # Size (inverted)
            CCMapping("s4", 63, [(0.0, 64), (0.5, 30), (1.0, 5)]),  # Rate (inverted)
            CCMapping("s4", 65, _STD_CURVE),  # Contour
        ],
    ),
    "vocal_chain.spectral_color": Dimension(
        name="vocal_chain.spectral_color",
        description=(
            "Shifts vocal brightness and metallicity. Dark, bright, hollow, metallic. "
            "Changes tonal character without changing pitch or volume."
        ),
        cc_mappings=[
            CCMapping("evil_pet", 70, _CENTER_CURVE),  # Filter freq
            CCMapping("s4", 83, _CENTER_CURVE),  # Ring Tone
            CCMapping("s4", 88, _CENTER_CURVE),  # Tilt
        ],
    ),
    "vocal_chain.coherence": Dimension(
        name="vocal_chain.coherence",
        description=(
            "Controls intelligibility of speech. Master axis from clear human voice "
            "to pure abstract texture. Affects overall processing depth."
        ),
        cc_mappings=[
            CCMapping("evil_pet", 40, _STD_CURVE),  # Mix (master wet/dry)
            CCMapping("s4", 69, _STD_CURVE),  # Mosaic Wet
            CCMapping("s4", 85, _GENTLE_CURVE),  # Ring Wet
        ],
    ),
}

# CapabilityRecords for Qdrant indexing
VOCAL_CHAIN_RECORDS = [
    CapabilityRecord(
        name=dim.name,
        description=dim.description,
        daemon="hapax_voice",
        operational=OperationalProperties(latency_class="fast"),
    )
    for dim in DIMENSIONS.values()
]

# Affordance keywords for can_resolve matching
VOCAL_CHAIN_AFFORDANCES = {
    "vocal_modulation",
    "stimmung_shift",
    "voice_character",
    "speech_texture",
    "conversational_tone",
}


class VocalChainCapability:
    """Vocal chain as a Capability — recruited for expressive speech modulation."""

    def __init__(
        self,
        midi_output: Any,
        evil_pet_channel: int = 0,
        s4_channel: int = 1,
        decay_rate: float = 0.02,
    ) -> None:
        self._midi = midi_output
        self._evil_pet_ch = evil_pet_channel
        self._s4_ch = s4_channel
        self._decay_rate = decay_rate
        self._levels: dict[str, float] = {name: 0.0 for name in DIMENSIONS}
        self._activation_level = 0.0

    @property
    def name(self) -> str:
        return "vocal_chain"

    @property
    def affordance_signature(self) -> set[str]:
        return VOCAL_CHAIN_AFFORDANCES

    @property
    def activation_cost(self) -> float:
        return 0.05  # MIDI CC is nearly free

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
        """Match impingements that warrant vocal modulation."""
        content = impingement.content
        metric = content.get("metric", "")

        if any(aff in metric for aff in VOCAL_CHAIN_AFFORDANCES):
            return impingement.strength

        # Stimmung shifts should modulate voice character
        if "stimmung" in impingement.source:
            return impingement.strength * 0.4

        # DMN evaluative signals (trajectory changes)
        if "dmn.evaluative" in impingement.source:
            return impingement.strength * 0.3

        return 0.0

    def activate(self, impingement: Impingement, level: float) -> dict[str, Any]:
        """Activate vocal chain — sets activation level for cascade tracking."""
        self._activation_level = level
        log.info(
            "Vocal chain activated: %s (strength=%.2f, level=%.2f)",
            impingement.content.get("metric", impingement.source),
            impingement.strength,
            level,
        )
        return {"vocal_chain_activated": True, "level": level}

    def activate_dimension(
        self, dimension_name: str, impingement: Impingement, level: float
    ) -> None:
        """Activate a specific dimension and send corresponding MIDI CCs."""
        if dimension_name not in DIMENSIONS:
            log.debug("Unknown dimension: %s", dimension_name)
            return

        self._levels[dimension_name] = max(0.0, min(1.0, level))
        self._activation_level = max(self._levels.values())
        self._send_dimension_cc(dimension_name)

    def get_dimension_level(self, dimension_name: str) -> float:
        """Get the current activation level of a dimension."""
        return self._levels.get(dimension_name, 0.0)

    def decay(self, elapsed_s: float) -> None:
        """Decay all active dimensions toward transparent."""
        amount = self._decay_rate * elapsed_s
        any_active = False
        for name in list(self._levels):
            if self._levels[name] > 0.0:
                self._levels[name] = max(0.0, self._levels[name] - amount)
                if self._levels[name] > 0.0:
                    any_active = True
                self._send_dimension_cc(name)

        if not any_active:
            self._activation_level = 0.0
        else:
            self._activation_level = max(self._levels.values())

    def deactivate(self) -> None:
        """Reset all dimensions to transparent."""
        for name in self._levels:
            self._levels[name] = 0.0
        self._activation_level = 0.0

    def _send_dimension_cc(self, dimension_name: str) -> None:
        """Send MIDI CC messages for a dimension at its current level."""
        dim = DIMENSIONS[dimension_name]
        level = self._levels[dimension_name]
        for mapping in dim.cc_mappings:
            value = cc_value_from_level(level, mapping.breakpoints)
            channel = self._evil_pet_ch if mapping.device == "evil_pet" else self._s4_ch
            self._midi.send_cc(channel=channel, cc=mapping.cc, value=value)
```

- [ ] **Step 4: Run tests**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/test_vocal_chain.py -v`
Expected: All PASS

- [ ] **Step 5: Lint and commit**

```bash
cd /home/hapax/projects/hapax-council
uv run ruff check agents/hapax_voice/vocal_chain.py tests/test_vocal_chain.py
uv run ruff format agents/hapax_voice/vocal_chain.py tests/test_vocal_chain.py
git add agents/hapax_voice/vocal_chain.py tests/test_vocal_chain.py
git commit -m "feat(voice): add VocalChainCapability — 9 semantic MIDI dimensions"
```

---

### Task 3: Config fields and voice daemon registration

**Files:**
- Modify: `agents/hapax_voice/config.py:192-194`
- Modify: `agents/hapax_voice/__main__.py:958-983`

- [ ] **Step 1: Add config fields**

In `agents/hapax_voice/config.py`, after line 194 (`midi_beats_per_bar: int = 4`), add:

```python
    # MIDI output (vocal chain)
    midi_output_port: str = ""  # empty = first available, or device name
    midi_evil_pet_channel: int = 0  # 0-indexed MIDI channel
    midi_s4_channel: int = 1  # 0-indexed MIDI channel
```

- [ ] **Step 2: Register vocal chain in voice daemon**

In `agents/hapax_voice/__main__.py`, after line 983 (`log.info("Pipeline dependencies precomputed...")`), add:

```python
        # Vocal chain: MIDI affordances for speech modulation
        from agents.hapax_voice.midi_output import MidiOutput
        from agents.hapax_voice.vocal_chain import VOCAL_CHAIN_RECORDS, VocalChainCapability

        self._midi_output = MidiOutput(port_name=self.cfg.midi_output_port)
        self._vocal_chain = VocalChainCapability(
            midi_output=self._midi_output,
            evil_pet_channel=self.cfg.midi_evil_pet_channel,
            s4_channel=self.cfg.midi_s4_channel,
        )
        for record in VOCAL_CHAIN_RECORDS:
            self._affordance_pipeline.index_capability(record)
        log.info("Vocal chain capability indexed (9 dimensions)")
```

- [ ] **Step 3: Run ruff check**

Run: `cd /home/hapax/projects/hapax-council && uv run ruff check agents/hapax_voice/config.py agents/hapax_voice/__main__.py`
Expected: Clean

- [ ] **Step 4: Commit**

```bash
cd /home/hapax/projects/hapax-council
git add agents/hapax_voice/config.py agents/hapax_voice/__main__.py
git commit -m "feat(voice): register vocal chain capability in daemon startup"
```

---

### Task 4: Run full test suite and verify

- [ ] **Step 1: Run all TTS and vocal chain tests**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/test_midi_output.py tests/test_vocal_chain.py tests/test_hapax_voice_tts.py tests/hapax_voice/test_tts_tier_cleanup.py -v`
Expected: All PASS

- [ ] **Step 2: Run ruff on all changed files**

Run: `cd /home/hapax/projects/hapax-council && uv run ruff check agents/hapax_voice/midi_output.py agents/hapax_voice/vocal_chain.py agents/hapax_voice/config.py && uv run ruff format --check agents/hapax_voice/midi_output.py agents/hapax_voice/vocal_chain.py agents/hapax_voice/config.py`
Expected: Clean

- [ ] **Step 3: Verify no import issues**

Run: `cd /home/hapax/projects/hapax-council && uv run python -c "from agents.hapax_voice.vocal_chain import VocalChainCapability, VOCAL_CHAIN_RECORDS, DIMENSIONS; print(f'{len(DIMENSIONS)} dimensions, {len(VOCAL_CHAIN_RECORDS)} records')"`
Expected: `9 dimensions, 9 records`

- [ ] **Step 4: Verify MidiOutput import**

Run: `cd /home/hapax/projects/hapax-council && uv run python -c "from agents.hapax_voice.midi_output import MidiOutput; print('MidiOutput OK')"`
Expected: `MidiOutput OK`
