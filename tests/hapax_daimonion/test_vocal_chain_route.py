"""Tests for VocalChainCapability dual-FX route switching (Phase 5)."""

from __future__ import annotations

from unittest.mock import MagicMock

from agents.hapax_daimonion.vocal_chain import VocalChainCapability
from shared.voice_tier import VoiceTier


class TestRouteSwitch:
    def test_first_tier_triggers_switch(self) -> None:
        switcher = MagicMock()
        midi = MagicMock()
        chain = VocalChainCapability(midi_output=midi, route_switcher=switcher)
        chain.apply_tier(VoiceTier.BROADCAST_GHOST)
        # BROADCAST_GHOST → EVIL_PET path. Switcher called once with Ryzen sink.
        assert switcher.call_count == 1
        assert "alsa_output.pci" in switcher.call_args.args[0]

    def test_same_path_skips_switch(self) -> None:
        """BROADCAST_GHOST → MEMORY both map to EVIL_PET; no re-switch."""
        switcher = MagicMock()
        midi = MagicMock()
        chain = VocalChainCapability(midi_output=midi, route_switcher=switcher)
        chain.apply_tier(VoiceTier.BROADCAST_GHOST)
        chain.apply_tier(VoiceTier.MEMORY)
        # Both tiers → EVIL_PET; only one switch.
        assert switcher.call_count == 1

    def test_path_transition_triggers_switch(self) -> None:
        """UNADORNED (DRY) → BROADCAST_GHOST (EVIL_PET) fires new switch."""
        switcher = MagicMock()
        midi = MagicMock()
        chain = VocalChainCapability(midi_output=midi, route_switcher=switcher)
        chain.apply_tier(VoiceTier.UNADORNED)
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
        chain = VocalChainCapability(midi_output=midi, route_switcher=switcher)
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
        # UNADORNED normally → DRY path. Override forces EVIL_PET.
        chain.apply_tier(VoiceTier.UNADORNED, path_override=VoicePath.EVIL_PET)
        assert switcher.call_count == 1
        # Sink is the Evil Pet path's sink, not the DRY path's.
        from agents.hapax_daimonion.voice_path import load_paths

        expected_sink = load_paths()[VoicePath.EVIL_PET].sink
        assert switcher.call_args.args[0] == expected_sink
