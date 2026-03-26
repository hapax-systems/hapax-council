"""Tests for Phase R5 — affordance pipeline validation metrics."""

from shared.affordance_metrics import AffordanceMetrics


def test_metrics_empty_summary():
    m = AffordanceMetrics()
    summary = m.compute_summary()
    assert summary["status"] == "no_data"


def test_metrics_record_selection():
    m = AffordanceMetrics()
    m.record_selection(
        impingement_source="dmn.sensory",
        impingement_metric="flow_drop",
        candidates_count=3,
        winner="speech_production",
        winner_similarity=0.85,
        winner_combined=0.72,
    )
    assert len(m._selections) == 1
    assert m._selections[0].winner == "speech_production"


def test_metrics_record_outcome():
    m = AffordanceMetrics()
    m.record_outcome("speech_production", success=True)
    assert len(m._outcomes) == 1
    assert m._outcomes[0].success is True


def test_metrics_summary_with_data():
    m = AffordanceMetrics()
    for i in range(10):
        m.record_selection(
            impingement_source="dmn",
            impingement_metric=f"metric_{i}",
            candidates_count=3,
            winner="speech_production",
            winner_similarity=0.8,
            winner_combined=0.7,
        )
    for _i in range(8):
        m.record_outcome("speech_production", success=True)
    for _i in range(2):
        m.record_outcome("speech_production", success=False)

    summary = m.compute_summary()
    assert summary["status"] == "active"
    assert summary["selections"]["total"] == 10
    assert summary["selections"]["match_rate"] == 1.0
    assert summary["outcomes"]["total"] == 10
    assert summary["outcomes"]["success_rate"] == 0.8


def test_metrics_per_capability_breakdown():
    m = AffordanceMetrics()
    m.record_outcome("speech", success=True)
    m.record_outcome("speech", success=True)
    m.record_outcome("fortress", success=False)

    # Need at least one selection for summary to be "active"
    m.record_selection("dmn", "x", 1, "speech", 0.8, 0.7)

    summary = m.compute_summary()
    assert summary["per_capability"]["speech"]["success"] == 2
    assert summary["per_capability"]["fortress"]["failure"] == 1


def test_metrics_convergence_insufficient():
    m = AffordanceMetrics()
    for _i in range(5):
        m.record_selection("dmn", "x", 1, "speech", 0.8, 0.7)
    summary = m.compute_summary()
    assert summary["convergence"]["converged"] is False
    assert summary["convergence"]["reason"] == "insufficient_data"


def test_metrics_convergence_detected():
    m = AffordanceMetrics()
    # 50 selections with stable combined scores
    for i in range(50):
        m.record_selection("dmn", "x", 1, "speech", 0.8, 0.70 + (i % 2) * 0.01)
    summary = m.compute_summary()
    assert summary["convergence"]["converged"] is True


def test_metrics_save_load_roundtrip(tmp_path, monkeypatch):
    import shared.affordance_metrics as mod

    monkeypatch.setattr(mod, "METRICS_DIR", tmp_path)

    m = AffordanceMetrics()
    m.record_selection("dmn", "flow", 3, "speech", 0.85, 0.72)
    m.record_outcome("speech", success=True)
    m.save()

    m2 = AffordanceMetrics()
    m2.load()
    assert len(m2._selections) == 1
    assert m2._selections[0].winner == "speech"
    assert len(m2._outcomes) == 1
    assert m2._outcomes[0].success is True


def test_metrics_fallback_tracking():
    m = AffordanceMetrics()
    m.record_selection("sensor", "update", 0, None, was_fallback=True)
    summary = m.compute_summary()
    assert summary["selections"]["fallbacks"] == 1


def test_metrics_interrupt_tracking():
    m = AffordanceMetrics()
    m.record_selection("dmn", "critical", 1, "fortress", 1.0, 1.0, was_interrupt=True)
    summary = m.compute_summary()
    assert summary["selections"]["interrupts"] == 1
