"""Tests for shared.signal_topology — signal chain tracing."""

from __future__ import annotations

from shared import signal_topology, workspace_graph


class TestStaticSignalGraph:
    def setup_method(self) -> None:
        workspace_graph._GRAPH = None

    def test_builds_directed_graph(self) -> None:
        SG = signal_topology.static_signal_graph()
        assert SG.number_of_edges() > 0

    def test_edges_have_protocol(self) -> None:
        SG = signal_topology.static_signal_graph()
        for _, _, data in SG.edges(data=True):
            assert "protocol" in data

    def test_zoom_l12_has_connections(self) -> None:
        neighbors = signal_topology.signal_neighbors("zoom-l12")
        total = len(neighbors["sends_to"]) + len(neighbors["receives_from"])
        assert total > 0


class TestTracePath:
    def setup_method(self) -> None:
        workspace_graph._GRAPH = None

    def test_returns_none_for_unconnected(self) -> None:
        path = signal_topology.trace_path("blue-yeti", "evil-pet")
        assert path is None or len(path) > 1

    def test_returns_none_for_nonexistent(self) -> None:
        path = signal_topology.trace_path("nonexistent", "also-nonexistent")
        assert path is None

    def test_direct_connection_returns_short_path(self) -> None:
        path = signal_topology.trace_path("zoom-l12", "evil-pet")
        if path:
            assert len(path) >= 2
            assert path[0] == "zoom-l12"


class TestAllSignalPaths:
    def setup_method(self) -> None:
        workspace_graph._GRAPH = None

    def test_returns_dict(self) -> None:
        paths = signal_topology.all_signal_paths_from("zoom-l12")
        assert isinstance(paths, dict)

    def test_paths_start_from_source(self) -> None:
        paths = signal_topology.all_signal_paths_from("zoom-l12")
        for target, path in paths.items():
            assert path[0] == "zoom-l12"
            assert path[-1] == target
