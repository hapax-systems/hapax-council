"""Test that activation summaries are written to Qdrant point payloads."""

from shared.affordance import ActivationState


def test_activation_state_to_summary():
    state = ActivationState()
    state.record_success()
    state.record_success()
    state.record_failure()
    summary = state.to_summary()
    assert summary["use_count"] == 3
    assert summary["ts_alpha"] > 2.0  # optimistic prior + 2 successes - decay
    assert summary["success_rate"] > 0.5
    assert "last_use_ts" in summary
