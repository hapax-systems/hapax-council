"""Tests for shared.alert_state."""
import json

from shared.alert_state import AlertPhase, AlertStateTracker, CheckAlertState


class TestAlertStateTracker:
    def test_first_failure_notifies(self, tmp_path):
        t = AlertStateTracker(state_path=tmp_path / "state.json")
        should_notify, priority = t.update("docker.qdrant", is_healthy=False)
        assert should_notify is True
        assert priority == "high"
        assert t.get_state("docker.qdrant").phase == AlertPhase.FIRING

    def test_repeated_failure_suppressed(self, tmp_path):
        t = AlertStateTracker(state_path=tmp_path / "state.json")
        t.update("docker.qdrant", is_healthy=False)  # 1st — notifies
        should_notify, _ = t.update("docker.qdrant", is_healthy=False)  # 2nd
        assert should_notify is False

    def test_escalation_at_threshold(self, tmp_path):
        t = AlertStateTracker(state_path=tmp_path / "state.json")
        t.update("docker.qdrant", is_healthy=False)  # count=1, escalation_level=0
        t.update("docker.qdrant", is_healthy=False)  # count=2
        t.update("docker.qdrant", is_healthy=False)  # count=3
        should_notify, _ = t.update("docker.qdrant", is_healthy=False)  # count=4
        assert should_notify is True  # escalation threshold [1, 4, 12]

    def test_recovery_notifies(self, tmp_path):
        t = AlertStateTracker(state_path=tmp_path / "state.json")
        t.update("docker.qdrant", is_healthy=False)
        should_notify, priority = t.update("docker.qdrant", is_healthy=True)
        assert should_notify is True
        assert priority == "low"
        assert t.get_state("docker.qdrant").phase == AlertPhase.OK

    def test_persistence_roundtrip(self, tmp_path):
        path = tmp_path / "state.json"
        t1 = AlertStateTracker(state_path=path)
        t1.update("docker.qdrant", is_healthy=False)
        t1.save()

        t2 = AlertStateTracker(state_path=path)
        assert t2.get_state("docker.qdrant").phase == AlertPhase.FIRING
        assert t2.get_state("docker.qdrant").consecutive_failures == 1

    def test_get_firing(self, tmp_path):
        t = AlertStateTracker(state_path=tmp_path / "state.json")
        t.update("docker.qdrant", is_healthy=False)
        t.update("docker.ollama", is_healthy=True)
        firing = t.get_firing()
        assert "docker.qdrant" in firing
        assert "docker.ollama" not in firing
