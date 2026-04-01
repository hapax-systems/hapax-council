"""Tests for shared.exploration — ExplorationSignal computation."""

from __future__ import annotations

from shared.exploration import (
    CoherenceTracker,
    HabituationTracker,
    InterestTracker,
    LearningProgressTracker,
    compute_boredom_index,
    compute_curiosity_index,
    compute_exploration_signal,
)


class TestHabituationTracker:
    def test_novel_edge_has_full_gain(self) -> None:
        ht = HabituationTracker(edges=["dmn_pulse", "salience_router"])
        assert ht.gain("dmn_pulse") == 1.0

    def test_predictable_input_reduces_gain(self) -> None:
        ht = HabituationTracker(edges=["a"], kappa=1.0, alpha=0.5, beta=0.0)
        for _ in range(10):
            ht.update("a", current=1.0, previous=1.0, std_dev=0.1)
        assert ht.gain("a") < 0.5

    def test_surprising_input_preserves_gain(self) -> None:
        ht = HabituationTracker(edges=["a"], kappa=1.0, alpha=0.5, beta=0.0)
        for i in range(10):
            ht.update("a", current=float(i), previous=float(i - 1), std_dev=0.1)
        assert ht.gain("a") > 0.8

    def test_natural_decay_recovers_sensitivity(self) -> None:
        ht = HabituationTracker(edges=["a"], kappa=1.0, alpha=0.5, beta=0.1)
        for _ in range(20):
            ht.update("a", current=1.0, previous=1.0, std_dev=0.1)
        habituated_gain = ht.gain("a")
        for _ in range(50):
            ht.decay_all()
        assert ht.gain("a") > habituated_gain

    def test_mean_habituation(self) -> None:
        ht = HabituationTracker(edges=["a", "b"], kappa=1.0, alpha=0.5, beta=0.0)
        for _ in range(20):
            ht.update("a", current=1.0, previous=1.0, std_dev=0.1)
        mh = ht.mean_habituation()
        assert 0.0 < mh < 1.0

    def test_max_novelty_edge(self) -> None:
        ht = HabituationTracker(edges=["a", "b"], kappa=1.0, alpha=0.5, beta=0.0)
        for _ in range(20):
            ht.update("a", current=1.0, previous=1.0, std_dev=0.1)
        edge, score = ht.max_novelty()
        assert edge == "b"
        assert score > 0.8


class TestInterestTracker:
    def test_fresh_trace_has_full_interest(self) -> None:
        it = InterestTracker(traces=["a"], rho_base=0.005, rho_adapt=0.020, t_patience=300.0)
        assert it.interest("a") == 1.0

    def test_unchanged_trace_decays(self) -> None:
        it = InterestTracker(traces=["a"], rho_base=0.1, rho_adapt=0.0, t_patience=300.0)
        it.tick("a", current=1.0, std_dev=0.1, elapsed_s=10.0)
        assert it.interest("a") < 1.0

    def test_meaningful_change_resets_interest(self) -> None:
        it = InterestTracker(traces=["a"], rho_base=0.1, rho_adapt=0.0, t_patience=300.0)
        it.tick("a", current=1.0, std_dev=0.1, elapsed_s=10.0)
        decayed = it.interest("a")
        it.tick("a", current=2.0, std_dev=0.1, elapsed_s=1.0)
        assert it.interest("a") > decayed

    def test_adaptive_evaporation_accelerates_after_patience(self) -> None:
        it = InterestTracker(traces=["a"], rho_base=0.005, rho_adapt=0.020, t_patience=10.0)
        it.tick("a", current=1.0, std_dev=0.1, elapsed_s=5.0)
        early = it.interest("a")
        it2 = InterestTracker(traces=["a"], rho_base=0.005, rho_adapt=0.020, t_patience=10.0)
        it2.tick("a", current=1.0, std_dev=0.1, elapsed_s=15.0)
        late = it2.interest("a")
        assert late < early

    def test_mean_trace_interest(self) -> None:
        it = InterestTracker(traces=["a", "b"], rho_base=0.1, rho_adapt=0.0, t_patience=300.0)
        it.tick("a", current=1.0, std_dev=0.1, elapsed_s=10.0)
        mean = it.mean_interest()
        assert 0.0 < mean < 1.0

    def test_stagnation_duration(self) -> None:
        it = InterestTracker(traces=["a", "b"], rho_base=0.005, rho_adapt=0.0, t_patience=300.0)
        it.tick("a", current=1.0, std_dev=0.1, elapsed_s=60.0)
        it.tick("b", current=1.0, std_dev=0.1, elapsed_s=30.0)
        assert it.stagnation_duration() == 30.0


class TestLearningProgressTracker:
    def test_initial_state(self) -> None:
        lp = LearningProgressTracker(alpha_ema=0.05)
        assert lp.chronic_error == 0.0
        assert lp.error_improvement_rate == 0.0

    def test_decreasing_error_shows_learning(self) -> None:
        lp = LearningProgressTracker(alpha_ema=0.5)
        for e in [1.0, 0.8, 0.6, 0.4, 0.2]:
            lp.update(e)
        assert lp.error_improvement_rate > 0.0

    def test_stable_error_shows_stagnation(self) -> None:
        lp = LearningProgressTracker(alpha_ema=0.5)
        for _ in range(20):
            lp.update(0.5)
        assert abs(lp.error_improvement_rate) < 0.01

    def test_increasing_error_shows_degradation(self) -> None:
        lp = LearningProgressTracker(alpha_ema=0.5)
        for e in [0.2, 0.4, 0.6, 0.8, 1.0]:
            lp.update(e)
        assert lp.error_improvement_rate < 0.0


class TestCoherenceTracker:
    def test_synchronized_components_high_coherence(self) -> None:
        ct = CoherenceTracker(neighbors=["a", "b", "c"])
        ct.update_phases({"a": 0.0, "b": 0.0, "c": 0.0})
        assert ct.local_coherence() > 0.9

    def test_desynchronized_components_low_coherence(self) -> None:
        ct = CoherenceTracker(neighbors=["a", "b", "c"])
        ct.update_phases({"a": 0.0, "b": 2.094, "c": 4.189})
        assert ct.local_coherence() < 0.2

    def test_dwell_time_accumulates_during_coherence(self) -> None:
        ct = CoherenceTracker(neighbors=["a", "b"], coherence_threshold=0.8)
        ct.update_phases({"a": 0.0, "b": 0.1})
        ct.tick(elapsed_s=5.0)
        ct.tick(elapsed_s=5.0)
        assert ct.dwell_time_in_coherence() == 10.0

    def test_dwell_time_resets_on_desync(self) -> None:
        ct = CoherenceTracker(neighbors=["a", "b"], coherence_threshold=0.8)
        ct.update_phases({"a": 0.0, "b": 0.1})
        ct.tick(elapsed_s=5.0)
        ct.update_phases({"a": 0.0, "b": 3.14})
        ct.tick(elapsed_s=5.0)
        assert ct.dwell_time_in_coherence() == 0.0


class TestComputeBoredomIndex:
    def test_weights_sum_to_one(self) -> None:
        bi = compute_boredom_index(
            mean_habituation=1.0,
            mean_trace_interest=0.0,
            stagnation_duration=1000.0,
            dwell_time_in_coherence=1000.0,
            t_patience=300.0,
        )
        assert 0.95 < bi <= 1.0

    def test_all_novel_zero_boredom(self) -> None:
        bi = compute_boredom_index(
            mean_habituation=0.0,
            mean_trace_interest=1.0,
            stagnation_duration=0.0,
            dwell_time_in_coherence=0.0,
            t_patience=300.0,
        )
        assert bi == 0.0


class TestComputeCuriosityIndex:
    def test_novel_edge_drives_curiosity(self) -> None:
        ci = compute_curiosity_index(
            chronic_error=0.0,
            error_improvement_rate=0.0,
            max_novelty_score=0.9,
            local_coherence=0.95,
        )
        assert ci >= 0.9

    def test_stalled_reorganization_drives_curiosity(self) -> None:
        ci = compute_curiosity_index(
            chronic_error=0.8,
            error_improvement_rate=-0.01,
            max_novelty_score=0.0,
            local_coherence=0.95,
        )
        assert ci > 0.5

    def test_desynchronization_drives_curiosity(self) -> None:
        ci = compute_curiosity_index(
            chronic_error=0.0,
            error_improvement_rate=0.0,
            max_novelty_score=0.0,
            local_coherence=0.2,
        )
        assert ci >= 0.8


class TestComputeExplorationSignal:
    def test_end_to_end(self) -> None:
        ht = HabituationTracker(edges=["a", "b"])
        it = InterestTracker(traces=["a", "b"])
        lp = LearningProgressTracker()
        ct = CoherenceTracker(neighbors=["a", "b"])

        sig = compute_exploration_signal("test", ht, it, lp, ct)
        assert sig.component == "test"
        assert 0.0 <= sig.boredom_index <= 1.0
        assert 0.0 <= sig.curiosity_index <= 1.0
        assert sig.timestamp > 0

    def test_to_dict_round_trip(self) -> None:
        ht = HabituationTracker(edges=["a"])
        it = InterestTracker(traces=["a"])
        lp = LearningProgressTracker()
        ct = CoherenceTracker(neighbors=["a"])

        sig = compute_exploration_signal("test", ht, it, lp, ct)
        d = sig.to_dict()
        assert isinstance(d, dict)
        assert d["component"] == "test"
        assert isinstance(d["boredom_index"], float)
