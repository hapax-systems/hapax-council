"""Tests for vocal chain impingement wiring."""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock

from agents._impingement import Impingement, ImpingementType


class TestVocalChainWiring(unittest.TestCase):
    def _imp(self, **kwargs) -> Impingement:
        """Build an Impingement with required defaults filled in."""
        defaults = {
            "timestamp": time.time(),
            "type": ImpingementType.SALIENCE_INTEGRATION,
        }
        defaults.update(kwargs)
        return Impingement(**defaults)

    def test_vocal_affordance_activates_chain(self):
        from agents.hapax_daimonion.vocal_chain import VocalChainCapability

        midi_out = MagicMock()
        chain = VocalChainCapability(midi_output=midi_out, evil_pet_channel=0, s4_channel=1)
        imp = self._imp(
            source="dmn.evaluative",
            strength=0.7,
            content={"metric": "vocal.intensity", "narrative": "test"},
            context={"dimensions": {"intensity": 0.8}},
        )
        score = chain.can_resolve(imp)
        assert score > 0.0
        result = chain.activate_from_impingement(imp)
        assert result["activated"] is True
        assert chain.get_dimension_level("intensity") > 0.0

    def test_non_vocal_impingement_ignored(self):
        from agents.hapax_daimonion.vocal_chain import VocalChainCapability

        midi_out = MagicMock()
        chain = VocalChainCapability(midi_output=midi_out, evil_pet_channel=0, s4_channel=1)
        imp = self._imp(
            source="dmn.sensory",
            strength=0.5,
            content={"metric": "visual.brightness", "narrative": "bright"},
            context={},
        )
        score = chain.can_resolve(imp)
        assert score == 0.0

    def test_stimmung_impingement_reduced_strength(self):
        from agents.hapax_daimonion.vocal_chain import VocalChainCapability

        midi_out = MagicMock()
        chain = VocalChainCapability(midi_output=midi_out, evil_pet_channel=0, s4_channel=1)
        imp = self._imp(
            source="stimmung.shift",
            strength=0.8,
            content={"metric": "stance_change", "narrative": "degraded"},
            context={"dimensions": {"tension": 0.6}},
        )
        score = chain.can_resolve(imp)
        assert 0.3 <= score <= 0.35  # 0.8 * 0.4 = 0.32


if __name__ == "__main__":
    unittest.main()
