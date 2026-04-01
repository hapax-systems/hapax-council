"""Integration tests for DMN daemon lifecycle."""

from unittest.mock import AsyncMock, patch

from agents.dmn.buffer import DMNBuffer
from agents.dmn.pulse import DMNPulse


class TestDMNPulseIntegration:
    async def test_sensory_tick_with_ollama(self):
        buf = DMNBuffer()
        pulse = DMNPulse(buf)
        snapshot = {
            "perception": {"activity": "coding", "flow_score": 0.7, "age_s": 1.0},
            "stimmung": {"stance": "nominal", "operator_stress": 0.1, "age_s": 1.0},
            "fortress": None,
            "watch": {"heart_rate": 72, "age_s": 1.0},
        }
        with patch("agents.dmn.pulse._ollama_generate", new_callable=AsyncMock) as mock_ollama:
            mock_ollama.return_value = "Operator coding with moderate flow."
            await pulse._sensory_tick(snapshot)
        assert len(buf) == 1
        obs = list(buf._observations)[0]
        assert "coding" in obs.content

    async def test_evaluative_tick_degrading_emits_impingement(self):
        buf = DMNBuffer()
        pulse = DMNPulse(buf)
        pulse._prior_snapshot = {
            "perception": {"activity": "coding", "flow_score": 0.8},
            "stimmung": {"stance": "nominal"},
        }
        snapshot = {
            "perception": {"activity": "idle", "flow_score": 0.2, "age_s": 1.0},
            "stimmung": {"stance": "degraded", "operator_stress": 0.6, "age_s": 1.0},
            "fortress": None,
            "watch": {"heart_rate": 0, "age_s": 1.0},
        }
        with patch("agents.dmn.pulse._ollama_generate", new_callable=AsyncMock) as mock:
            mock.return_value = "Trajectory: degrading. Concern: flow dropped significantly."
            await pulse._evaluative_tick(snapshot)
        impingements = pulse.drain_impingements()
        evaluative = [i for i in impingements if i.source == "dmn.evaluative"]
        assert len(evaluative) == 1
        assert evaluative[0].content["trajectory"] == "degrading"


# TestTPNActiveIntegration removed — TPN active flag no longer in DMN.
# The voice daemon writes tpn_active; perception signals replace it for DMN.
# See: docs/research/stigmergic-cognitive-mesh.md §3.3 P1
