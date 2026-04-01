"""Tests for stimmung exploration_deficit + SEEKING stance."""

from __future__ import annotations

from shared.stimmung import Stance, StimmungCollector


def _make_healthy_collector() -> StimmungCollector:
    """Create a collector with all infrastructure dimensions nominal."""
    sc = StimmungCollector()
    sc.update_health(99, 99, [])
    sc.update_gpu(7000, 24000)
    sc.update_engine(100, 50, 0, 3600.0)
    sc.update_perception(1.0, 0.9)
    sc.update_langfuse(0.0)
    return sc


class TestSeekingStance:
    def test_seeking_exists(self) -> None:
        assert Stance.SEEKING == "seeking"

    def test_stance_ordering(self) -> None:
        ordered = [
            Stance.NOMINAL,
            Stance.SEEKING,
            Stance.CAUTIOUS,
            Stance.DEGRADED,
            Stance.CRITICAL,
        ]
        assert len(ordered) == 5


class TestExplorationDeficit:
    def test_update_exploration_sets_dimension(self) -> None:
        sc = StimmungCollector()
        sc.update_exploration(0.5)
        snap = sc.snapshot()
        assert hasattr(snap, "exploration_deficit")
        assert snap.exploration_deficit.value == 0.5

    def test_high_exploration_deficit_enters_seeking(self) -> None:
        sc = _make_healthy_collector()
        # Need 3+ ticks for hysteresis
        for _ in range(5):
            sc.update_exploration(0.5)
            snap = sc.snapshot()
        assert snap.overall_stance == Stance.SEEKING

    def test_seeking_suppressed_when_infrastructure_degraded(self) -> None:
        sc = StimmungCollector()
        sc.update_health(50, 99, [])  # bad health → not NOMINAL
        sc.update_exploration(0.5)
        snap = sc.snapshot()
        assert snap.overall_stance != Stance.SEEKING

    def test_low_deficit_stays_nominal(self) -> None:
        sc = _make_healthy_collector()
        sc.update_exploration(0.1)
        snap = sc.snapshot()
        assert snap.overall_stance == Stance.NOMINAL

    def test_seeking_exit_hysteresis(self) -> None:
        sc = _make_healthy_collector()
        # Enter SEEKING
        for _ in range(5):
            sc.update_exploration(0.5)
            sc.snapshot()
        assert sc.snapshot().overall_stance == Stance.SEEKING
        # Drop deficit — need 5 consecutive non-SEEKING for exit
        for i in range(4):
            sc.update_exploration(0.1)
            snap = sc.snapshot()
            assert snap.overall_stance == Stance.SEEKING, f"Should still be SEEKING at tick {i + 1}"
        sc.update_exploration(0.1)
        snap = sc.snapshot()
        assert snap.overall_stance == Stance.NOMINAL
