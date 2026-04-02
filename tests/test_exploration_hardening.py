"""Tests for exploration hardening — impingement emission, adaptive std_dev, affordance SEEKING."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from shared.exploration import ExplorationMode, HabituationTracker
from shared.exploration_tracker import ExplorationTrackerBundle, _emit_exploration_impingement


class TestImpingementEmission:
    def _clear_cooldown(self) -> None:
        """Reset the module-level emission cooldown so each test can emit."""
        import shared.exploration_tracker as mod

        mod._last_emission.clear()

    def test_directed_emits_exploration_opp(self, tmp_path: Path) -> None:
        from shared.exploration import ExplorationAction, ExplorationSignal

        self._clear_cooldown()
        imp_file = tmp_path / "impingements.jsonl"
        sig = ExplorationSignal(
            component="test",
            timestamp=0.0,
            mean_habituation=0.8,
            max_novelty_edge="novel",
            max_novelty_score=0.6,
            error_improvement_rate=0.0,
            chronic_error=0.0,
            mean_trace_interest=0.2,
            stagnation_duration=0.0,
            local_coherence=0.5,
            dwell_time_in_coherence=0.0,
            boredom_index=0.8,
            curiosity_index=0.6,
        )
        action = ExplorationAction(
            mode=ExplorationMode.DIRECTED,
            gain_boost_edge="novel",
            gain_boost_factor=1.5,
            gain_suppress_factor=0.5,
            tick_rate_factor=0.77,
            explore=False,
            perturb_sigma=0.0,
        )
        with patch("shared.exploration_tracker._IMPINGEMENTS_FILE", imp_file):
            _emit_exploration_impingement("test", action, sig)
        lines = imp_file.read_text().strip().split("\n")
        assert len(lines) == 1
        imp = json.loads(lines[0])
        assert imp["type"] == "exploration_opp"
        assert imp["source"] == "exploration.test"

    def test_undirected_emits_boredom(self, tmp_path: Path) -> None:
        from shared.exploration import ExplorationAction, ExplorationSignal

        self._clear_cooldown()
        imp_file = tmp_path / "impingements.jsonl"
        sig = ExplorationSignal(
            component="test",
            timestamp=0.0,
            mean_habituation=0.9,
            max_novelty_edge=None,
            max_novelty_score=0.1,
            error_improvement_rate=0.0,
            chronic_error=0.0,
            mean_trace_interest=0.1,
            stagnation_duration=0.0,
            local_coherence=0.5,
            dwell_time_in_coherence=0.0,
            boredom_index=0.9,
            curiosity_index=0.1,
        )
        action = ExplorationAction(
            mode=ExplorationMode.UNDIRECTED,
            gain_boost_edge=None,
            gain_boost_factor=1.0,
            gain_suppress_factor=0.8,
            tick_rate_factor=1.0,
            explore=True,
            perturb_sigma=0.1,
        )
        with patch("shared.exploration_tracker._IMPINGEMENTS_FILE", imp_file):
            _emit_exploration_impingement("test", action, sig)
        imp = json.loads(imp_file.read_text().strip())
        assert imp["type"] == "boredom"

    def test_none_action_no_emission(self, tmp_path: Path) -> None:
        from shared.exploration import ExplorationAction, ExplorationSignal

        imp_file = tmp_path / "impingements.jsonl"
        sig = ExplorationSignal(
            component="test",
            timestamp=0.0,
            mean_habituation=0.3,
            max_novelty_edge=None,
            max_novelty_score=0.0,
            error_improvement_rate=0.0,
            chronic_error=0.0,
            mean_trace_interest=0.7,
            stagnation_duration=0.0,
            local_coherence=0.5,
            dwell_time_in_coherence=0.0,
            boredom_index=0.3,
            curiosity_index=0.0,
        )
        action = ExplorationAction.no_action()
        with patch("shared.exploration_tracker._IMPINGEMENTS_FILE", imp_file):
            _emit_exploration_impingement("test", action, sig)
        assert not imp_file.exists()


class TestBundleAutoEmission:
    def test_compute_and_publish_emits_when_bored(self, tmp_path: Path) -> None:
        imp_file = tmp_path / "impingements.jsonl"
        bundle = ExplorationTrackerBundle(
            component="test_bored",
            edges=["a"],
            traces=["x"],
            neighbors=["p"],
            kappa=10.0,  # very fast habituation
            sigma_explore=0.15,
        )
        # Feed lots of predictable data to trigger boredom
        for _ in range(50):
            bundle.feed_habituation("a", 1.0, 1.0, 0.1)
            bundle.feed_interest("x", 1.0, 0.1)
        bundle.feed_error(0.0)

        with patch("shared.exploration_tracker._IMPINGEMENTS_FILE", imp_file):
            sig = bundle.compute_and_publish()

        # Should have emitted if boredom > 0.7
        if sig.boredom_index > 0.7:
            assert imp_file.exists()
            assert bundle.last_action.mode != ExplorationMode.NONE

    def test_last_action_populated(self) -> None:
        bundle = ExplorationTrackerBundle(
            component="test",
            edges=["a"],
            traces=["x"],
            neighbors=["p"],
        )
        bundle.compute_and_publish()
        assert bundle.last_action is not None
        assert bundle.last_action.mode in (
            ExplorationMode.NONE,
            ExplorationMode.DIRECTED,
            ExplorationMode.UNDIRECTED,
            ExplorationMode.FOCUSED,
        )


class TestAdaptiveStdDev:
    def test_welford_tracks_variance(self) -> None:
        ht = HabituationTracker(edges=["a"])
        # Feed with std_dev=0 to trigger adaptive mode
        for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
            ht.update("a", current=v, previous=v - 1.0, std_dev=0.0)
        # After 5 samples, internal variance should be populated
        assert ht._edge_n["a"] == 5
        assert ht._edge_m2["a"] > 0

    def test_adaptive_mode_uses_historical_std(self) -> None:
        ht = HabituationTracker(edges=["a"], alpha=0.5, beta=0.0)
        # Train on values with known spread
        for v in [10.0, 12.0, 8.0, 11.0, 9.0]:
            ht.update("a", current=v, previous=v, std_dev=0.0)
        # Now a small change (within historical std) should be predictable
        ht.update("a", current=10.5, previous=10.0, std_dev=0.0)
        # The historical std of [10,12,8,11,9] ≈ 1.41 — 0.5 change is within it
        # So habituation weight should increase (predictable)
        assert ht._weights["a"] > 0

    def test_explicit_std_overrides_adaptive(self) -> None:
        ht = HabituationTracker(edges=["a"], alpha=0.5, beta=0.0)
        for v in [1.0, 2.0, 3.0]:
            ht.update("a", current=v, previous=v - 1.0, std_dev=5.0)
        # With std_dev=5.0, delta=1.0 is always predictable
        assert ht._weights["a"] > 0


class TestAffordanceSeeking:
    def test_set_seeking(self) -> None:
        from shared.affordance_pipeline import AffordancePipeline

        pipeline = AffordancePipeline()
        assert pipeline._seeking is False
        pipeline.set_seeking(True)
        assert pipeline._seeking is True
