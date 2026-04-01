"""Tests for the 15th control law — boredom-driven exploration responses."""

from __future__ import annotations

from shared.exploration import (
    ExplorationAction,
    ExplorationMode,
    ExplorationSignal,
    evaluate_control_law,
)


def _make_signal(boredom: float = 0.0, curiosity: float = 0.0, **kwargs) -> ExplorationSignal:
    defaults = {
        "component": "test",
        "timestamp": 0.0,
        "mean_habituation": boredom,
        "max_novelty_edge": "novel_edge" if curiosity > 0 else None,
        "max_novelty_score": curiosity,
        "error_improvement_rate": 0.0,
        "chronic_error": 0.0,
        "mean_trace_interest": 1.0 - boredom,
        "stagnation_duration": 0.0,
        "local_coherence": 0.5,
        "dwell_time_in_coherence": 0.0,
        "boredom_index": boredom,
        "curiosity_index": curiosity,
    }
    defaults.update(kwargs)
    return ExplorationSignal(**defaults)


class TestDirectedExploration:
    """Bored + curious → focus on novel edge."""

    def test_triggers_when_bored_and_curious(self) -> None:
        sig = _make_signal(boredom=0.8, curiosity=0.6)
        action = evaluate_control_law(sig)
        assert action.mode == ExplorationMode.DIRECTED

    def test_boosts_novel_edge_gain(self) -> None:
        sig = _make_signal(boredom=0.8, curiosity=0.6)
        action = evaluate_control_law(sig)
        assert action.gain_boost_edge == "novel_edge"
        assert action.gain_boost_factor == 1.5

    def test_suppresses_habituated_edges(self) -> None:
        sig = _make_signal(boredom=0.8, curiosity=0.6)
        action = evaluate_control_law(sig)
        assert action.gain_suppress_factor == 0.5

    def test_accelerates_tick_rate(self) -> None:
        sig = _make_signal(boredom=0.8, curiosity=0.6)
        action = evaluate_control_law(sig)
        assert action.tick_rate_factor < 1.0  # faster


class TestUndirectedExploration:
    """Bored + not curious → random perturbation."""

    def test_triggers_when_bored_without_curiosity(self) -> None:
        sig = _make_signal(boredom=0.8, curiosity=0.2)
        action = evaluate_control_law(sig)
        assert action.mode == ExplorationMode.UNDIRECTED

    def test_applies_perturbation(self) -> None:
        sig = _make_signal(boredom=0.8, curiosity=0.2)
        action = evaluate_control_law(sig, sigma_explore=0.15)
        assert action.perturb_sigma == 0.15

    def test_may_explore_new_trace(self) -> None:
        sig = _make_signal(boredom=0.9, curiosity=0.1)
        action = evaluate_control_law(sig)
        assert action.explore is True

    def test_no_gain_boost(self) -> None:
        sig = _make_signal(boredom=0.8, curiosity=0.2)
        action = evaluate_control_law(sig)
        assert action.gain_boost_edge is None


class TestFocusedEngagement:
    """Not bored + curious → amplify novel edge."""

    def test_triggers_when_curious_not_bored(self) -> None:
        sig = _make_signal(boredom=0.3, curiosity=0.8)
        action = evaluate_control_law(sig)
        assert action.mode == ExplorationMode.FOCUSED

    def test_strong_gain_boost(self) -> None:
        sig = _make_signal(boredom=0.3, curiosity=0.8)
        action = evaluate_control_law(sig)
        assert action.gain_boost_factor == 2.0

    def test_no_suppression(self) -> None:
        sig = _make_signal(boredom=0.3, curiosity=0.8)
        action = evaluate_control_law(sig)
        assert action.gain_suppress_factor == 1.0


class TestNoAction:
    """Neither bored nor curious → do nothing."""

    def test_nominal_state(self) -> None:
        sig = _make_signal(boredom=0.3, curiosity=0.3)
        action = evaluate_control_law(sig)
        assert action.mode == ExplorationMode.NONE
        assert action.gain_boost_factor == 1.0
        assert action.gain_suppress_factor == 1.0
        assert action.tick_rate_factor == 1.0
        assert action.explore is False
        assert action.perturb_sigma == 0.0

    def test_no_action_static_constructor(self) -> None:
        action = ExplorationAction.no_action()
        assert action.mode == ExplorationMode.NONE


class TestTrackerBundleEvaluateAction:
    def test_evaluate_action_returns_action(self) -> None:
        from shared.exploration_tracker import ExplorationTrackerBundle

        bundle = ExplorationTrackerBundle(
            component="test",
            edges=["a"],
            traces=["x"],
            neighbors=["p"],
        )
        sig = bundle.compute_and_publish()
        action = bundle.evaluate_action(sig)
        assert isinstance(action, ExplorationAction)
