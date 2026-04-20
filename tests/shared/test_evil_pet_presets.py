"""Tests for shared.evil_pet_presets — CC-burst preset pack (#194)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from shared.evil_pet_presets import (
    PRESETS,
    EvilPetPreset,
    get_preset,
    list_presets,
    recall_preset,
)
from shared.voice_tier import VoiceTier


class TestPresetCoverage:
    def test_has_preset_per_tier(self) -> None:
        names = list_presets()
        for tier in VoiceTier:
            expected = f"hapax-{tier.name.lower().replace('_', '-')}"
            assert expected in names, f"missing preset: {expected}"

    def test_has_mode_d(self) -> None:
        assert "hapax-mode-d" in list_presets()

    def test_has_bypass(self) -> None:
        assert "hapax-bypass" in list_presets()

    def test_nine_presets_total(self) -> None:
        # 7 tiers + Mode D + bypass = 9.
        assert len(PRESETS) == 9


class TestPresetShape:
    def test_each_has_name_and_description(self) -> None:
        for preset in PRESETS.values():
            assert preset.name
            assert preset.description

    def test_each_has_nonempty_ccs(self) -> None:
        for preset in PRESETS.values():
            assert preset.ccs, f"preset {preset.name!r} has empty ccs"

    def test_cc_values_in_midi_range(self) -> None:
        for preset in PRESETS.values():
            for cc, value in preset.ccs.items():
                assert 0 <= cc <= 127, f"{preset.name}: CC {cc} out of range"
                assert 0 <= value <= 127, f"{preset.name}: value {value} out of range"

    def test_bypass_grains_off(self) -> None:
        """Bypass preset must set CC 11 (grains volume) to 0."""
        bypass = get_preset("hapax-bypass")
        assert bypass.ccs[11] == 0

    def test_mode_d_grains_on(self) -> None:
        """Mode D preset must engage grains (CC 11 high)."""
        mode_d = get_preset("hapax-mode-d")
        assert mode_d.ccs[11] >= 100  # 94%+ per Smitelli 2020 floor

    def test_mode_d_shimmer_on(self) -> None:
        mode_d = get_preset("hapax-mode-d")
        assert mode_d.ccs[94] > 0

    def test_mode_d_full_wet_mix(self) -> None:
        mode_d = get_preset("hapax-mode-d")
        assert mode_d.ccs[40] == 127


class TestTierPresets:
    def test_t0_inherits_base_scene(self) -> None:
        """UNADORNED overrides nothing — pure base scene."""
        preset = get_preset("hapax-unadorned")
        assert preset.ccs[11] == 0  # grains off (base scene default)
        assert preset.ccs[7] == 127  # volume max

    def test_t5_engages_granular_engine(self) -> None:
        preset = get_preset("hapax-granular-wash")
        # T5 cc_override sets CC 11 = 90 + CC 40 = 110.
        assert preset.ccs[11] == 90
        assert preset.ccs[40] == 110

    def test_t6_full_granular(self) -> None:
        preset = get_preset("hapax-obliterated")
        assert preset.ccs[11] == 120
        assert preset.ccs[40] == 127
        assert preset.ccs[94] == 60  # shimmer on


class TestGetPreset:
    def test_returns_named(self) -> None:
        preset = get_preset("hapax-bypass")
        assert preset.name == "hapax-bypass"

    def test_raises_on_unknown(self) -> None:
        with pytest.raises(KeyError):
            get_preset("hapax-nonexistent")


class TestRecallPreset:
    def test_emits_all_ccs(self) -> None:
        midi = MagicMock()
        n = recall_preset("hapax-bypass", midi, delay_s=0.0)
        preset = get_preset("hapax-bypass")
        assert n == len(preset.ccs)
        assert midi.send_cc.call_count == len(preset.ccs)

    def test_emits_on_default_channel(self) -> None:
        midi = MagicMock()
        recall_preset("hapax-bypass", midi, delay_s=0.0)
        for call in midi.send_cc.call_args_list:
            assert call.kwargs["channel"] == 0  # EVIL_PET_MIDI_CHANNEL

    def test_custom_channel(self) -> None:
        midi = MagicMock()
        recall_preset("hapax-bypass", midi, channel=3, delay_s=0.0)
        for call in midi.send_cc.call_args_list:
            assert call.kwargs["channel"] == 3

    def test_tolerates_send_cc_failure(self) -> None:
        """A single bad send_cc doesn't abort the whole recall."""
        midi = MagicMock()
        midi.send_cc.side_effect = [RuntimeError("boom")] + [None] * 20
        # Use a small preset so MagicMock side_effect list covers it.
        preset = get_preset("hapax-bypass")
        # Shrink the preset's ccs list for this test by wrapping.
        n = recall_preset("hapax-bypass", midi, delay_s=0.0)
        # One failed, rest succeeded.
        assert n == len(preset.ccs) - 1

    def test_raises_on_unknown_preset(self) -> None:
        with pytest.raises(KeyError):
            recall_preset("hapax-nonexistent", MagicMock(), delay_s=0.0)


class TestPresetObjectShape:
    def test_dataclass_frozen(self) -> None:
        """EvilPetPreset is immutable so shared-dict mutations are safe."""
        preset = EvilPetPreset(name="test", description="t", ccs={11: 0})
        with pytest.raises(Exception):
            preset.name = "other"  # type: ignore[misc]
