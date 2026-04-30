"""Tests for VocalChainCapability dual-FX route switching (Phase 5)."""

from __future__ import annotations

from unittest.mock import MagicMock

from agents.hapax_daimonion.vocal_chain import VocalChainCapability
from shared.audio_expression_surface import FxDeviceWitness
from shared.voice_tier import VoiceTier


def _ready_witness(**overrides: object) -> FxDeviceWitness:
    data: dict[str, object] = {
        "evil_pet_midi": True,
        "evil_pet_sd_pack": True,
        "evil_pet_firmware_verified": True,
        "s4_midi": True,
        "s4_audio": True,
        "l12_route": True,
        "evidence_refs": ("fx-device-witness:test",),
    }
    data.update(overrides)
    return FxDeviceWitness.model_validate(data)


class TestRouteSwitch:
    def test_missing_fx_witness_holds_without_route_switch_or_midi(self) -> None:
        switcher = MagicMock()
        midi = MagicMock()
        chain = VocalChainCapability(midi_output=midi, route_switcher=switcher)
        chain.apply_tier(VoiceTier.BROADCAST_GHOST)
        switcher.assert_not_called()
        midi.send_cc.assert_not_called()

    def test_first_tier_triggers_switch_when_fx_witness_passes(self) -> None:
        switcher = MagicMock()
        midi = MagicMock()
        chain = VocalChainCapability(
            midi_output=midi,
            route_switcher=switcher,
            fx_device_witness_provider=_ready_witness,
        )
        chain.apply_tier(VoiceTier.BROADCAST_GHOST)
        # Passing Evil Pet + S-4 witness resolves public voice to the dual-FX path.
        assert switcher.call_count == 1
        assert "alsa_output.pci" in switcher.call_args.args[0]

    def test_same_path_skips_switch(self) -> None:
        """BROADCAST_GHOST → MEMORY both map to witnessed dual FX; no re-switch."""
        switcher = MagicMock()
        midi = MagicMock()
        chain = VocalChainCapability(
            midi_output=midi,
            route_switcher=switcher,
            fx_device_witness_provider=_ready_witness,
        )
        chain.apply_tier(VoiceTier.BROADCAST_GHOST)
        chain.apply_tier(VoiceTier.MEMORY)
        # Both tiers → BOTH; only one switch.
        assert switcher.call_count == 1

    def test_path_transition_triggers_switch(self) -> None:
        """S-4-only witness → Evil-Pet-only witness fires a new switch."""
        witnesses = iter(
            (
                _ready_witness(
                    evil_pet_midi=False, evil_pet_sd_pack=False, evil_pet_firmware_verified=False
                ),
                _ready_witness(s4_midi=False, s4_audio=False, l12_route=False),
            )
        )
        switcher = MagicMock()
        midi = MagicMock()
        chain = VocalChainCapability(
            midi_output=midi,
            route_switcher=switcher,
            fx_device_witness_provider=lambda: next(witnesses),
        )
        chain.apply_tier(VoiceTier.RADIO)
        chain.apply_tier(VoiceTier.BROADCAST_GHOST)
        assert switcher.call_count == 2

    def test_route_audio_false_skips_switch(self) -> None:
        """route_audio=False emits MIDI without calling pactl."""
        switcher = MagicMock()
        midi = MagicMock()
        chain = VocalChainCapability(midi_output=midi, route_switcher=switcher)
        chain.apply_tier(VoiceTier.MEMORY, route_audio=False)
        switcher.assert_not_called()
        # MIDI still emitted.
        assert midi.send_cc.call_count > 0

    def test_switcher_failure_tolerated(self) -> None:
        """Pactl failure logs + continues — doesn't block MIDI."""
        switcher = MagicMock(side_effect=RuntimeError("pactl missing"))
        midi = MagicMock()
        chain = VocalChainCapability(
            midi_output=midi,
            route_switcher=switcher,
            fx_device_witness_provider=_ready_witness,
        )
        # Must not raise.
        chain.apply_tier(VoiceTier.BROADCAST_GHOST)
        # Current path stays None so next tier re-attempts.
        assert chain._current_path is None
        # MIDI still emitted despite route failure.
        assert midi.send_cc.call_count > 0

    def test_path_override_bypasses_selector(self) -> None:
        """Explicit path_override wins over select_voice_path."""
        from agents.hapax_daimonion.voice_path import VoicePath

        switcher = MagicMock()
        midi = MagicMock()
        chain = VocalChainCapability(midi_output=midi, route_switcher=switcher)
        # UNADORNED normally → safe wet baseline. Override still wins.
        chain.apply_tier(VoiceTier.UNADORNED, path_override=VoicePath.EVIL_PET)
        assert switcher.call_count == 1
        # Sink is the Evil Pet path's sink, not the DRY path's.
        from agents.hapax_daimonion.voice_path import load_paths

        expected_sink = load_paths()[VoicePath.EVIL_PET].sink
        assert switcher.call_args.args[0] == expected_sink
