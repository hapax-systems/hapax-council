"""Tests for Phase R2 — affordance learning associations from outcomes."""

import json
from pathlib import Path
from unittest.mock import patch

from shared.affordance_pipeline import AffordancePipeline


def test_record_outcome_success_strengthens_associations():
    """record_outcome(success=True) strengthens context associations."""
    pipe = AffordancePipeline()
    ctx = {"mode": "rnd", "source": "voice"}
    pipe.record_outcome("speak", success=True, context=ctx)

    assert pipe._context_associations[("rnd", "speak")] > 0
    assert pipe._context_associations[("voice", "speak")] > 0


def test_record_outcome_failure_weakens_associations():
    """record_outcome(success=False) weakens context associations."""
    pipe = AffordancePipeline()
    # Prime with a positive association
    pipe.update_context_association("rnd", "speak", delta=0.5)
    pipe.record_outcome("speak", success=False, context={"mode": "rnd"})

    assert pipe._context_associations[("rnd", "speak")] < 0.5


def test_multiple_successes_then_failures_thompson_shift():
    """Multiple successes then failures show Thompson distribution shift."""
    pipe = AffordancePipeline()
    for _ in range(10):
        pipe.record_outcome("cap_a", success=True)
    state_after_success = pipe.get_activation_state("cap_a")
    alpha_high = state_after_success.ts_alpha

    for _ in range(10):
        pipe.record_outcome("cap_a", success=False)
    state_after_failure = pipe.get_activation_state("cap_a")

    # After failures, beta should have grown relative to alpha
    assert state_after_failure.ts_beta > state_after_failure.ts_alpha
    assert state_after_failure.ts_alpha < alpha_high


def test_decay_associations_reduces_strength():
    """decay_associations reduces strengths toward zero."""
    pipe = AffordancePipeline()
    pipe.update_context_association("rnd", "speak", delta=1.0)
    original = pipe._context_associations[("rnd", "speak")]

    for _ in range(100):
        pipe.decay_associations(factor=0.95)

    decayed = pipe._context_associations.get(("rnd", "speak"), 0.0)
    assert decayed < original * 0.01  # Should be very small after 100 rounds of 0.95


def test_decay_associations_removes_near_zero():
    """decay_associations removes entries near zero."""
    pipe = AffordancePipeline()
    pipe.update_context_association("tiny", "cap", delta=0.002)

    pipe.decay_associations(factor=0.1)  # 0.002 * 0.1 = 0.0002 < 0.001

    assert ("tiny", "cap") not in pipe._context_associations


def test_record_dismissal_logs_and_feeds_failure():
    """record_dismissal logs and feeds failure signal."""
    pipe = AffordancePipeline()
    pipe.record_outcome("cap_a", success=True)  # Prime with success
    pipe.record_dismissal("cap_a", impingement_id="imp-123", context={"mode": "rnd"})

    assert len(pipe._dismissal_log) == 1
    assert pipe._dismissal_log[0]["capability"] == "cap_a"
    assert pipe._dismissal_log[0]["impingement_id"] == "imp-123"
    # Failure signal should have increased beta
    state = pipe.get_activation_state("cap_a")
    assert state.ts_beta > 1.0


def test_dismissal_log_trimming():
    """Dismissal log trims when exceeding 100 entries."""
    pipe = AffordancePipeline()
    for i in range(105):
        pipe.record_dismissal("cap", impingement_id=f"imp-{i}")

    # After 101 entries, trims to 50, then 4 more added = 54
    assert len(pipe._dismissal_log) <= 100
    assert len(pipe._dismissal_log) < 105


def test_save_load_activation_state_roundtrip(tmp_path: Path):
    """save_activation_state + load_activation_state roundtrip."""
    state_file = tmp_path / "affordance-activation-state.json"

    pipe = AffordancePipeline()
    pipe.record_outcome("speak", success=True, context={"mode": "rnd"})
    pipe.record_outcome("listen", success=True, context={"source": "voice"})
    pipe.record_outcome("speak", success=True)

    with patch.object(
        type(pipe),
        "save_activation_state",
        lambda self: _save_to(self, state_file),
    ):
        _save_to(pipe, state_file)

    # Load into fresh pipeline
    pipe2 = AffordancePipeline()
    with patch(
        "shared.affordance_pipeline.ACTIVATION_STATE_PATH",
        state_file,
    ):
        pipe2.load_activation_state()

    assert pipe2._activation["speak"].use_count == pipe._activation["speak"].use_count
    assert pipe2._activation["listen"].use_count == pipe._activation["listen"].use_count
    assert ("rnd", "speak") in pipe2._context_associations
    assert ("voice", "listen") in pipe2._context_associations


def _save_to(pipe: AffordancePipeline, path: Path) -> None:
    """Helper to save to a custom path."""
    data = {
        "activations": {name: state.model_dump() for name, state in pipe._activation.items()},
        "associations": {f"{k[0]}|{k[1]}": v for k, v in pipe._context_associations.items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.rename(path)


def test_get_audit_snapshot_structure():
    """get_audit_snapshot returns expected structure."""
    pipe = AffordancePipeline()
    pipe.record_outcome("speak", success=True, context={"mode": "rnd"})
    pipe.record_dismissal("speak", impingement_id="imp-1")

    snapshot = pipe.get_audit_snapshot()

    assert snapshot["capabilities_tracked"] == 1
    assert snapshot["associations_learned"] >= 1
    assert snapshot["recent_cascades"] == 0
    assert "inhibitions_active" in snapshot
    assert snapshot["dismissals_total"] == 1
    assert "speak" in snapshot["activation_states"]
    assert isinstance(snapshot["top_associations"], list)
    assert snapshot["activation_states"]["speak"]["use_count"] >= 1


def test_hebbian_convergence_over_iterations():
    """Hebbian learning over 10 iterations converges (association grows)."""
    pipe = AffordancePipeline()
    for _ in range(10):
        pipe.record_outcome("cap_a", success=True, context={"cue": "signal_x"})

    strength = pipe._context_associations[("signal_x", "cap_a")]
    assert strength >= 0.9  # 10 * 0.1 = 1.0 (capped at 4.0)


def test_associations_can_go_negative():
    """Associations can go negative after repeated failures."""
    pipe = AffordancePipeline()
    for _ in range(25):
        pipe.record_outcome("bad_cap", success=False, context={"cue": "signal_y"})

    strength = pipe._context_associations[("signal_y", "bad_cap")]
    assert strength < 0  # 25 * -0.05 = -1.25, clamped to -1.0


def test_context_boost_reflects_learned_associations():
    """Context boost reflects learned associations correctly."""
    pipe = AffordancePipeline()
    # Train positive association
    for _ in range(5):
        pipe.record_outcome("good_cap", success=True, context={"env": "studio"})

    boost = pipe._compute_context_boost("good_cap", {"env": "studio"})
    assert boost > 0.0

    # Train negative association on different capability
    for _ in range(25):
        pipe.record_outcome("bad_cap", success=False, context={"env": "studio"})

    boost_bad = pipe._compute_context_boost("bad_cap", {"env": "studio"})
    # Negative associations get clamped to 0 by _compute_context_boost
    assert boost_bad == 0.0
