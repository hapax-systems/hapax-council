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
            buf.add_observation(f"tick {i}")
        assert not buf.needs_consolidation()
        buf.add_observation("tick 12")
        assert buf.needs_consolidation()

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
