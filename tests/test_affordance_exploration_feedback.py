"""Tests for exploration feedback into affordance scoring.

The 15th control law specifies that boredom should increase gain on novelty
edges. The affordance pipeline's sigma_explore parameter should inject
scoring noise proportional to boredom_index, disrupting monotonic winners.
"""

import random
import time

from shared.affordance import SelectionCandidate
from shared.exploration import ExplorationSignal


def _make_signal(boredom: float, curiosity: float = 0.0) -> ExplorationSignal:
    return ExplorationSignal(
        component="affordance_pipeline",
        timestamp=time.time(),
        mean_habituation=boredom,
        max_novelty_edge=None,
        max_novelty_score=0.0,
        error_improvement_rate=0.0,
        chronic_error=0.0,
        mean_trace_interest=1.0 - boredom,
        stagnation_duration=0.0,
        local_coherence=0.5,
        dwell_time_in_coherence=0.0,
        boredom_index=boredom,
        curiosity_index=curiosity,
    )


class TestExplorationNoise:
    def test_no_noise_when_not_bored(self):
        """With low boredom, scoring should be deterministic (no noise)."""
        from shared.affordance_pipeline import _apply_exploration_noise

        candidates = [
            _make_candidate("cap-a", 0.65),
            _make_candidate("cap-b", 0.60),
        ]
        sig = _make_signal(boredom=0.1)
        random.seed(42)
        _apply_exploration_noise(candidates, sig, sigma_explore=0.10)
        # No noise applied — scores unchanged
        assert candidates[0].combined == 0.65
        assert candidates[1].combined == 0.60

    def test_noise_applied_when_bored(self):
        """High boredom should perturb candidate scores."""
        from shared.affordance_pipeline import _apply_exploration_noise

        candidates = [
            _make_candidate("cap-a", 0.65),
            _make_candidate("cap-b", 0.60),
        ]
        sig = _make_signal(boredom=0.8)
        _apply_exploration_noise(candidates, sig, sigma_explore=0.10)
        # At least one score should have changed
        changed = candidates[0].combined != 0.65 or candidates[1].combined != 0.60
        assert changed

    def test_noise_can_reorder_candidates(self):
        """With enough boredom, noise should occasionally swap rankings."""
        from shared.affordance_pipeline import _apply_exploration_noise

        reordered = False
        for seed in range(100):
            candidates = [
                _make_candidate("cap-a", 0.65),
                _make_candidate("cap-b", 0.63),  # close gap — noise can flip
            ]
            sig = _make_signal(boredom=0.9)
            random.seed(seed)
            _apply_exploration_noise(candidates, sig, sigma_explore=0.10)
            if candidates[1].combined > candidates[0].combined:
                reordered = True
                break
        assert reordered, "100 trials with high boredom should reorder at least once"

    def test_noise_magnitude_proportional_to_boredom(self):
        """Higher boredom should produce larger perturbations."""
        from shared.affordance_pipeline import _apply_exploration_noise

        low_deltas = []
        high_deltas = []
        for seed in range(50):
            c_low = [_make_candidate("a", 0.65)]
            c_high = [_make_candidate("a", 0.65)]
            random.seed(seed)
            _apply_exploration_noise(c_low, _make_signal(boredom=0.75), sigma_explore=0.10)
            random.seed(seed)
            _apply_exploration_noise(c_high, _make_signal(boredom=0.95), sigma_explore=0.10)
            low_deltas.append(abs(c_low[0].combined - 0.65))
            high_deltas.append(abs(c_high[0].combined - 0.65))

        avg_low = sum(low_deltas) / len(low_deltas)
        avg_high = sum(high_deltas) / len(high_deltas)
        assert avg_high > avg_low


def _make_candidate(name: str, combined: float) -> SelectionCandidate:
    return SelectionCandidate(
        capability_name=name,
        similarity=combined,
        combined=combined,
        payload={},
    )
