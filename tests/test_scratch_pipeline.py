"""Tests for scratch detection perception pipeline wiring."""

from __future__ import annotations

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestPerceptionStateExport:
    """Verify desk_* fields appear in the perception state dict."""

    def test_desk_activity_in_state_dict_keys(self):
        """The perception state writer must include desk_activity."""
        writer_path = _PROJECT_ROOT / "agents/hapax_voice/_perception_state_writer.py"
        source = writer_path.read_text()
        assert '"desk_activity"' in source

    def test_desk_energy_in_state_dict_keys(self):
        writer_path = _PROJECT_ROOT / "agents/hapax_voice/_perception_state_writer.py"
        source = writer_path.read_text()
        assert '"desk_energy"' in source


class TestMidiExport:
    def test_beat_position_in_state_dict(self):
        source = (_PROJECT_ROOT / "agents/hapax_voice/_perception_state_writer.py").read_text()
        assert '"beat_position"' in source

    def test_bar_position_in_state_dict(self):
        source = (_PROJECT_ROOT / "agents/hapax_voice/_perception_state_writer.py").read_text()
        assert '"bar_position"' in source


class TestOverlayDataField:
    def test_desk_activity_field_exists(self):
        from agents.studio_compositor import OverlayData

        data = OverlayData(desk_activity="scratching")
        assert data.desk_activity == "scratching"

    def test_beat_position_field_exists(self):
        from agents.studio_compositor import OverlayData

        data = OverlayData(beat_position=2.5)
        assert data.beat_position == 2.5

    def test_bar_position_field_exists(self):
        from agents.studio_compositor import OverlayData

        data = OverlayData(bar_position=1.0)
        assert data.bar_position == 1.0

    def test_desk_activity_defaults_empty(self):
        from agents.studio_compositor import OverlayData

        data = OverlayData()
        assert data.desk_activity == ""


class TestFlowModifier:
    def test_scratching_boosts_flow(self):
        """Source check: perception state writer adds flow modifier for scratching."""
        source = (_PROJECT_ROOT / "agents/hapax_voice/_perception_state_writer.py").read_text()
        assert "scratching" in source
        assert "drumming" in source
        assert "flow_modifier" in source
