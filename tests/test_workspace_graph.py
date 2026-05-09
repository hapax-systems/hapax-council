"""Tests for shared.workspace_graph — equipment registry graph parser."""

from __future__ import annotations

from shared import workspace_graph


class TestWorkspaceGraph:
    def setup_method(self) -> None:
        workspace_graph._GRAPH = None

    def test_load_graph_from_config(self) -> None:
        G = workspace_graph.load_graph(force_reload=True)
        assert G.number_of_nodes() > 0

    def test_all_devices_returns_seed_devices(self) -> None:
        devices = workspace_graph.all_devices()
        device_ids = [d["device_id"] for d in devices]
        assert "zoom-l12" in device_ids
        assert "torso-s4" in device_ids
        assert "evil-pet" in device_ids

    def test_by_id_returns_device(self) -> None:
        result = workspace_graph.by_id("zoom-l12")
        assert result is not None
        assert result.get("identity", {}).get("model") == "LiveTrak L-12"

    def test_by_id_returns_none_for_unknown(self) -> None:
        result = workspace_graph.by_id("nonexistent-device")
        assert result is None

    def test_by_capability_mixing(self) -> None:
        mixers = workspace_graph.by_capability("mixing")
        assert "zoom-l12" in mixers

    def test_by_capability_sample_playback(self) -> None:
        samplers = workspace_graph.by_capability("sample_playback")
        assert "mpc-live-iii" in samplers
        assert "torso-s4" in samplers
        assert "m8-tracker" in samplers

    def test_by_category(self) -> None:
        synths = workspace_graph.by_category("synthesizer")
        assert "torso-s4" in synths
        assert "digitone-ii" in synths

    def test_by_zone(self) -> None:
        desk_devices = workspace_graph.by_zone("main-desk")
        assert "zoom-l12" in desk_devices
        assert "torso-s4" in desk_devices

    def test_by_status(self) -> None:
        owned = workspace_graph.by_status("owned")
        assert len(owned) >= 10

    def test_connected_to(self) -> None:
        connections = workspace_graph.connected_to("zoom-l12")
        targets = [c.get("target") for c in connections if "target" in c]
        sources = [c.get("source") for c in connections if "source" in c]
        all_connected = targets + sources
        assert len(all_connected) > 0

    def test_summary(self) -> None:
        s = workspace_graph.summary()
        assert s["devices"] >= 10
        assert "mixer" in s["categories"]
        assert s["total_nodes"] > 0

    def test_graph_has_edges(self) -> None:
        G = workspace_graph.load_graph(force_reload=True)
        assert G.number_of_edges() > 0

    def test_midi_clock_source_query(self) -> None:
        clock_sources = workspace_graph.by_capability("midi_clock_source")
        assert "torso-s4" in clock_sources
        assert "mpc-live-iii" in clock_sources
        assert "digitakt-ii" in clock_sources
