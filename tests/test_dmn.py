"""Tests for the DMN (Default Mode Network) module."""

import time

from agents.dmn.buffer import DMNBuffer, Observation


class TestDMNBuffer:
    """Test buffer accumulation and U-curve formatting."""

    def test_add_observation(self):
        buf = DMNBuffer()
        buf.add_observation("Activity: coding. Flow: 0.8.")
        assert len(buf) == 1
        assert buf.tick == 1

    def test_observation_format(self):
        obs = Observation(
            tick=1, timestamp=time.time(), content="test content", deltas=["flow: 0.7 → 0.4"]
        )
        formatted = obs.format()
        assert "test content" in formatted
        assert "DELTA: flow: 0.7" in formatted
        assert "dmn_observation" in formatted

    def test_buffer_max_entries(self):
        buf = DMNBuffer()
        for i in range(25):
            buf.add_observation(f"tick {i}")
        # Should cap at MAX_RAW_ENTRIES (18)
        assert len(buf) == 18

    def test_format_for_tpn_empty(self):
        buf = DMNBuffer()
        result = buf.format_for_tpn()
        assert result == ""

    def test_format_for_tpn_with_summary(self):
        buf = DMNBuffer()
        buf.set_retentional_summary("Last 5 min: stable coding session.")
        buf.add_observation("Activity: coding.")
        result = buf.format_for_tpn()
        assert "retentional_summary" in result
        assert "Last 5 min" in result
        assert "coding" in result

    def test_format_for_tpn_recency_ordering(self):
        buf = DMNBuffer()
        buf.add_observation("old observation")
        for _ in range(7):
            buf.add_observation("middle observation")
        buf.add_observation("recent observation")
        result = buf.format_for_tpn()
        # Recent should be AFTER old
        old_pos = result.find("old observation")
        recent_pos = result.find("recent observation")
        assert recent_pos > old_pos

    def test_needs_consolidation(self):
        buf = DMNBuffer()
        for i in range(11):
            buf.add_observation(f"tick {i}", raw_sensor=f"raw {i}")
        assert not buf.needs_consolidation()
        buf.add_observation("tick 12", raw_sensor="raw 12")
        assert buf.needs_consolidation()

    def test_no_consolidation_when_all_stable(self):
        buf = DMNBuffer()
        for _i in range(15):
            buf.add_observation("stable")
        assert not buf.needs_consolidation()

    def test_consolidation_input_uses_raw_sensor(self):
        buf = DMNBuffer()
        for i in range(12):
            buf.add_observation(f"DMN output {i}", raw_sensor=f"Sensor data {i}")
        input_text = buf.get_consolidation_input()
        assert "Sensor data" in input_text
        assert "DMN output" not in input_text

    def test_prune_consolidated(self):
        buf = DMNBuffer()
        for i in range(12):
            buf.add_observation(f"tick {i}", raw_sensor=f"raw {i}")
        assert len(buf) == 12
        pruned = buf.prune_consolidated()
        assert pruned == 6
        assert len(buf) == 6

    def test_add_evaluation(self):
        buf = DMNBuffer()
        buf.add_evaluation("degrading", ["drink count is zero"])
        result = buf.format_for_tpn()
        assert "degrading" in result
        assert "drink count" in result

    def test_delta_context(self):
        buf = DMNBuffer()
        prior = {
            "perception": {"activity": "coding", "flow_score": 0.8},
            "stimmung": {"stance": "nominal"},
            "fortress": {"population": 5, "drink": 10, "food": 100, "threats": 0},
        }
        current = {
            "perception": {"activity": "browsing", "flow_score": 0.3},
            "stimmung": {"stance": "cautious"},
            "fortress": {"population": 4, "drink": 0, "food": 100, "threats": 0},
        }
        deltas = buf.format_delta_context(prior, current)
        assert any("activity" in d for d in deltas)
        assert any("flow" in d for d in deltas)
        assert any("stimmung" in d for d in deltas)
        assert any("population" in d for d in deltas)
        assert any("drink" in d for d in deltas)

    def test_no_deltas_when_unchanged(self):
        buf = DMNBuffer()
        snapshot = {
            "perception": {"activity": "coding", "flow_score": 0.8},
            "stimmung": {"stance": "nominal"},
        }
        deltas = buf.format_delta_context(snapshot, snapshot)
        assert deltas == []

    def test_format_for_tpn_respects_token_budget(self):
        """Middle-zone observations are trimmed when buffer exceeds token budget."""
        buf = DMNBuffer()
        buf.set_retentional_summary("Summary of prior observations.")
        for i in range(18):
            buf.add_observation(
                f"Observation {i}: " + "detailed sensor reading " * 10,
                raw_sensor=f"raw {i}",
            )
        result = buf.format_for_tpn()
        estimated_tokens = len(result) // 4
        assert estimated_tokens <= 1500, f"Buffer exceeded token budget: {estimated_tokens} tokens"
        assert "Summary of prior observations" in result
        assert "Observation 17" in result


class TestDMNSensor:
    """Test sensor reading functions."""

    def test_read_all_returns_dict(self):
        from agents.dmn.sensor import read_all

        result = read_all()
        assert "timestamp" in result
        assert "perception" in result
        assert "stimmung" in result
        assert "watch" in result

    def test_perception_has_required_fields(self):
        from agents.dmn.sensor import read_perception

        result = read_perception()
        assert "source" in result
        assert "activity" in result
        assert "flow_score" in result
        assert "stale" in result

    def test_stimmung_has_required_fields(self):
        from agents.dmn.sensor import read_stimmung

        result = read_stimmung()
        assert "source" in result
        assert "stance" in result


import json as _json
from unittest.mock import AsyncMock, patch

from agents.dmn.pulse import DMNPulse
from agents.dmn.sensor import SensorConfig, read_all


class TestSensorConfig:
    def test_read_all_with_custom_config(self, tmp_path):
        stimmung_path = tmp_path / "stimmung.json"
        stimmung_path.write_text(_json.dumps({"overall_stance": "nominal"}))
        config = SensorConfig(
            stimmung_state=stimmung_path,
            fortress_state=tmp_path / "nonexistent.json",
            watch_dir=tmp_path / "watch",
            voice_perception=tmp_path / "perception.json",
            visual_frame=tmp_path / "frame.jpg",
            imagination_current=tmp_path / "imagination.json",
        )
        snapshot = read_all(config)
        assert snapshot["stimmung"]["stance"] == "nominal"
        assert snapshot["fortress"] is None


class TestOllamaFailureTracking:
    async def test_degradation_impingement_after_threshold(self):
        buf = DMNBuffer()
        pulse = DMNPulse(buf)
        with patch("agents.dmn.pulse._ollama_generate", new_callable=AsyncMock, return_value=""):
            for _ in range(6):
                snapshot = {
                    "perception": {"activity": "coding", "flow_score": 0.5},
                    "stimmung": {"stance": "nominal", "operator_stress": 0.1},
                    "fortress": None,
                    "watch": {"heart_rate": 0},
                }
                await pulse._sensory_tick(snapshot)
        impingements = pulse.drain_impingements()
        degraded = [i for i in impingements if i.source == "dmn.ollama_degraded"]
        assert len(degraded) >= 1
        assert degraded[0].content["metric"] == "ollama_degraded"


class TestTPNActiveStaleness:
    def test_stale_signal_returns_false(self, tmp_path):
        from agents.dmn.__main__ import _read_tpn_active

        path = tmp_path / "tpn_active"
        path.write_text(f"1:{time.time() - 10:.3f}")
        assert _read_tpn_active(path) is False

    def test_fresh_signal_returns_true(self, tmp_path):
        from agents.dmn.__main__ import _read_tpn_active

        path = tmp_path / "tpn_active"
        path.write_text(f"1:{time.time():.3f}")
        assert _read_tpn_active(path) is True

    def test_legacy_format_still_works(self, tmp_path):
        from agents.dmn.__main__ import _read_tpn_active

        path = tmp_path / "tpn_active"
        path.write_text("1")
        assert _read_tpn_active(path) is True

    def test_missing_file_returns_false(self, tmp_path):
        from agents.dmn.__main__ import _read_tpn_active

        assert _read_tpn_active(tmp_path / "nonexistent") is False


class TestSensorStarvation:
    async def test_starvation_impingement_emitted(self):
        buf = DMNBuffer()
        pulse = DMNPulse(buf)
        snapshot = {
            "perception": {"source": "perception", "age_s": 90.0, "stale": True},
            "stimmung": {"source": "stimmung", "age_s": 5.0, "stance": "nominal"},
            "fortress": None,
            "watch": {"source": "watch", "age_s": 700.0},
        }
        pulse._check_sensor_starvation(snapshot)
        impingements = pulse.drain_impingements()
        starved = [i for i in impingements if i.source == "dmn.sensor_starvation"]
        assert len(starved) >= 1
        sensors_starved = {i.content["sensor"] for i in starved}
        assert "perception" in sensors_starved

    async def test_starvation_deduplicated(self):
        buf = DMNBuffer()
        pulse = DMNPulse(buf)
        snapshot = {
            "perception": {"source": "perception", "age_s": 90.0, "stale": True},
            "stimmung": {"source": "stimmung", "age_s": 5.0, "stance": "nominal"},
            "fortress": None,
            "watch": {"source": "watch", "age_s": 5.0},
        }
        pulse._check_sensor_starvation(snapshot)
        pulse._check_sensor_starvation(snapshot)
        impingements = pulse.drain_impingements()
        perception_starved = [
            i
            for i in impingements
            if i.source == "dmn.sensor_starvation" and i.content["sensor"] == "perception"
        ]
        assert len(perception_starved) == 1
