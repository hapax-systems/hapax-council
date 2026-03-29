"""Tests for VocalChainCapability — semantic MIDI affordances for speech modulation."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from agents.hapax_daimonion.vocal_chain import (
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
            assert r.daemon == "hapax_daimonion"

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
