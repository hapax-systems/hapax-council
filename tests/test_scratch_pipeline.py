"""Tests for scratch detection perception pipeline wiring."""

from __future__ import annotations


class TestPerceptionStateExport:
    """Verify desk_* fields appear in the perception state dict."""

    def test_desk_activity_in_state_dict_keys(self):
        """The perception state writer must include desk_activity."""
        from pathlib import Path

        writer_path = Path("agents/hapax_voice/_perception_state_writer.py")
        source = writer_path.read_text()
        assert '"desk_activity"' in source

    def test_desk_energy_in_state_dict_keys(self):
        from pathlib import Path

        writer_path = Path("agents/hapax_voice/_perception_state_writer.py")
        source = writer_path.read_text()
        assert '"desk_energy"' in source


class TestOverlayDataField:
    def test_desk_activity_field_exists(self):
        from agents.studio_compositor import OverlayData

        data = OverlayData(desk_activity="scratching")
        assert data.desk_activity == "scratching"

    def test_desk_activity_defaults_empty(self):
        from agents.studio_compositor import OverlayData

        data = OverlayData()
        assert data.desk_activity == ""


class TestFlowModifier:
    def test_scratching_boosts_flow(self):
        """Source check: perception state writer adds flow modifier for scratching."""
        from pathlib import Path

        source = Path("agents/hapax_voice/_perception_state_writer.py").read_text()
        assert "scratching" in source
        assert "drumming" in source
        assert "flow_modifier" in source
