"""Tests for OBS instrument_focus candidate driven by desk_activity.

Validates that the instrument_focus candidate in build_obs_fallback_chain
fires GEAR_CLOSEUP for scratching/drumming/tapping, passes through for idle,
and degrades gracefully when desk_activity is missing from samples.

Self-contained, unittest.mock only, asyncio_mode="auto".
"""

from __future__ import annotations

import unittest

from agents.hapax_daimonion.governance import FusedContext
from agents.hapax_daimonion.obs_governance import OBSScene, build_obs_fallback_chain
from agents.hapax_daimonion.primitives import Stamped


def _make_ctx(desk_activity: str | None = None) -> FusedContext:
    """Build a minimal FusedContext with low energy so only instrument_focus fires."""
    samples: dict[str, Stamped] = {
        "audio_energy_rms": Stamped(0.05, 1.0),
        "emotion_arousal": Stamped(0.1, 1.0),
    }
    if desk_activity is not None:
        samples["desk_activity"] = Stamped(desk_activity, 1.0)
    return FusedContext(
        trigger_time=1.0,
        trigger_value=None,
        samples=samples,
        min_watermark=1.0,
    )


class TestInstrumentFocusCandidate(unittest.TestCase):
    """instrument_focus candidate predicate tests."""

    def setUp(self) -> None:
        self.chain = build_obs_fallback_chain()
        # Extract the instrument_focus candidate by name
        self.candidate = next(c for c in self.chain._candidates if c.name == "instrument_focus")

    def test_scratching_triggers(self) -> None:
        ctx = _make_ctx("scratching")
        self.assertTrue(self.candidate.predicate(ctx))

    def test_drumming_triggers(self) -> None:
        ctx = _make_ctx("drumming")
        self.assertTrue(self.candidate.predicate(ctx))

    def test_tapping_triggers(self) -> None:
        ctx = _make_ctx("tapping")
        self.assertTrue(self.candidate.predicate(ctx))

    def test_idle_does_not_trigger(self) -> None:
        ctx = _make_ctx("idle")
        self.assertFalse(self.candidate.predicate(ctx))

    def test_missing_desk_activity_does_not_trigger(self) -> None:
        ctx = _make_ctx()  # no desk_activity in samples
        self.assertFalse(self.candidate.predicate(ctx))

    def test_chain_selects_gear_closeup_for_scratching(self) -> None:
        """Full chain: scratching at low energy → instrument_focus → GEAR_CLOSEUP."""
        ctx = _make_ctx("scratching")
        result = self.chain.select(ctx)
        self.assertEqual(result.action, OBSScene.GEAR_CLOSEUP)
        self.assertEqual(result.selected_by, "instrument_focus")


if __name__ == "__main__":
    unittest.main()
