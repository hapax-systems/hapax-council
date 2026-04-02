"""Tests for exploration pilot component wiring."""

from __future__ import annotations

from pathlib import Path

from shared.exploration_tracker import ExplorationTrackerBundle


class TestExplorationTrackerBundle:
    def test_compute_and_publish(self, tmp_path: Path) -> None:
        bundle = ExplorationTrackerBundle(
            component="test",
            edges=["a", "b"],
            traces=["x", "y"],
            neighbors=["p", "q"],
        )
        # Feed some data
        bundle.feed_habituation("a", 1.0, 1.0, 0.1)
        bundle.feed_interest("x", 1.0, 0.1)
        bundle.feed_error(0.5)
        bundle.feed_phases({"p": 0.0, "q": 0.1})

        # Compute (publish will fail silently in test env without /dev/shm)
        sig = bundle.compute_and_publish()
        assert sig.component == "test"
        assert 0.0 <= sig.boredom_index <= 1.0
        assert 0.0 <= sig.curiosity_index <= 1.0

    def test_multiple_ticks(self) -> None:
        bundle = ExplorationTrackerBundle(
            component="multi",
            edges=["a"],
            traces=["x"],
            neighbors=["p"],
        )
        # Tick several times with same data → habituation increases
        for _ in range(20):
            bundle.feed_habituation("a", 1.0, 1.0, 0.1)
            bundle.feed_interest("x", 1.0, 0.1)
            bundle.feed_error(0.1)
        sig = bundle.compute_and_publish()
        assert sig.mean_habituation > 0.0  # should have habituated

    def test_novel_input_resets_habituation(self) -> None:
        bundle = ExplorationTrackerBundle(
            component="novel",
            edges=["a"],
            traces=["x"],
            neighbors=["p"],
        )
        # Habituate
        for _ in range(20):
            bundle.feed_habituation("a", 1.0, 1.0, 0.1)
        habituated = bundle.habituation.mean_habituation()
        # Novel input
        bundle.feed_habituation("a", 5.0, 1.0, 0.1)
        # Habituation shouldn't increase further (novel input doesn't add weight)
        assert bundle.habituation.mean_habituation() <= habituated


class TestExplorationGuard:
    def test_stimmung_collector_default_has_exploration(self) -> None:
        from shared.stimmung import StimmungCollector

        sc = StimmungCollector()
        assert sc._exploration is not None

    def test_stimmung_collector_disabled_exploration(self) -> None:
        from shared.stimmung import StimmungCollector

        sc = StimmungCollector(enable_exploration=False)
        assert sc._exploration is None

    def test_temporal_formatter_default_has_exploration(self) -> None:
        from agents.temporal_bands import TemporalBandFormatter

        tf = TemporalBandFormatter()
        assert tf._exploration is not None

    def test_temporal_formatter_disabled_exploration(self) -> None:
        from agents.temporal_bands import TemporalBandFormatter

        tf = TemporalBandFormatter(enable_exploration=False)
        assert tf._exploration is None


class TestSalienceRouterExploration:
    def test_salience_router_has_exploration_tracker(self) -> None:
        from unittest.mock import MagicMock

        from agents.hapax_daimonion.salience_router import SalienceRouter

        embedder = MagicMock()
        concern_graph = MagicMock()
        concern_graph.anchor_count = 0

        router = SalienceRouter(embedder, concern_graph)
        assert router._exploration is not None
        assert router._exploration.component == "salience_router"


class TestIrPresenceExplorationInit:
    def test_ir_backend_has_exploration_tracker(self) -> None:
        from agents.hapax_daimonion.backends.ir_presence import IrPresenceBackend

        backend = IrPresenceBackend()
        assert hasattr(backend, "_exploration")
        assert backend._exploration.component == "ir_presence"


class TestImaginationDaemonExplorationInit:
    def test_imagination_daemon_has_exploration_tracker(self) -> None:
        from agents.imagination_daemon.__main__ import ImaginationDaemon

        daemon = ImaginationDaemon()
        assert hasattr(daemon, "_exploration")
        assert daemon._exploration.component == "dmn_imagination"
