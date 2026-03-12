"""Tests for shared/alert_state.py — alert state machine."""

from __future__ import annotations

import json
import time
from pathlib import Path

from shared.alert_state import (
    DEDUP_WINDOW_S,
    DEGRADED_ESCALATION_CYCLES,
    T0_URGENT_CYCLES,
    process_report,
)


def _make_report(checks: list[dict]) -> dict:
    """Build a minimal health report dict.

    Args:
        checks: List of dicts with keys: name, status, message, group.
    """
    by_group: dict[str, list[dict]] = {}
    for c in checks:
        g = c.get("group", "misc")
        by_group.setdefault(g, []).append({
            "name": c["name"],
            "status": c["status"],
            "message": c.get("message", ""),
        })

    return {
        "overall_status": "failed" if any(c["status"] == "failed" for c in checks) else "degraded",
        "groups": [
            {"name": g, "checks": cs}
            for g, cs in by_group.items()
        ],
    }


class TestFirstFailure:
    def test_first_failure_alerts(self, tmp_path: Path):
        """A check going from unknown -> failed should produce an alert."""
        state_file = tmp_path / "state.json"
        report = _make_report([
            {"name": "docker-running", "status": "failed", "message": "docker is down", "group": "docker"},
        ])
        actions = process_report(report, state_path=state_file)
        assert len(actions) == 1
        assert actions[0]["title"] == "Health: docker"
        assert "docker-running" in actions[0]["message"]

    def test_first_degraded_alerts(self, tmp_path: Path):
        state_file = tmp_path / "state.json"
        report = _make_report([
            {"name": "disk-space", "status": "degraded", "message": "85% full", "group": "system"},
        ])
        actions = process_report(report, state_path=state_file)
        assert len(actions) == 1
        assert actions[0]["priority"] == "default"


class TestDedup:
    def test_dedup_within_window(self, tmp_path: Path):
        """Same check+status within 30min should not re-alert."""
        state_file = tmp_path / "state.json"
        report = _make_report([
            {"name": "gpu-temp", "status": "degraded", "message": "hot", "group": "gpu"},
        ])

        actions1 = process_report(report, state_path=state_file)
        assert len(actions1) == 1

        # Second call immediately -- should be deduped
        actions2 = process_report(report, state_path=state_file)
        assert len(actions2) == 0

    def test_alert_after_dedup_window(self, tmp_path: Path):
        """After 30min, same failure should re-alert."""
        state_file = tmp_path / "state.json"
        report = _make_report([
            {"name": "gpu-temp", "status": "degraded", "message": "hot", "group": "gpu"},
        ])

        actions1 = process_report(report, state_path=state_file)
        assert len(actions1) == 1

        # Manipulate state to simulate time passing
        state = json.loads(state_file.read_text())
        state["gpu-temp"]["last_alert_time"] = time.time() - DEDUP_WINDOW_S - 1
        state_file.write_text(json.dumps(state))

        actions2 = process_report(report, state_path=state_file)
        assert len(actions2) == 1


class TestEscalation:
    def test_degraded_escalates_after_4_cycles(self, tmp_path: Path):
        """Degraded check should escalate to high after 4 consecutive cycles."""
        state_file = tmp_path / "state.json"
        report = _make_report([
            {"name": "disk-space", "status": "degraded", "message": "85% full", "group": "system"},
        ])

        for _i in range(DEGRADED_ESCALATION_CYCLES):
            if state_file.exists():
                state = json.loads(state_file.read_text())
                for k in state:
                    state[k]["last_alert_time"] = 0
                state_file.write_text(json.dumps(state))
            actions = process_report(report, state_path=state_file)

        # After 4 cycles, should be high priority
        assert any(a["priority"] == "high" for a in actions)

    def test_t0_failed_urgent_after_2_cycles(self, tmp_path: Path):
        """T0 group failed check should escalate to urgent after 2 cycles."""
        state_file = tmp_path / "state.json"
        report = _make_report([
            {"name": "litellm-health", "status": "failed", "message": "timeout", "group": "litellm"},
        ])

        for _i in range(T0_URGENT_CYCLES):
            if state_file.exists():
                state = json.loads(state_file.read_text())
                for k in state:
                    state[k]["last_alert_time"] = 0
                state_file.write_text(json.dumps(state))
            actions = process_report(report, state_path=state_file)

        assert any(a["priority"] == "urgent" for a in actions)


class TestGrouping:
    def test_multiple_checks_same_group_grouped(self, tmp_path: Path):
        """Multiple failures in the same group should produce one notification."""
        state_file = tmp_path / "state.json"
        report = _make_report([
            {"name": "docker-running", "status": "failed", "message": "down", "group": "docker"},
            {"name": "docker-healthy", "status": "failed", "message": "unhealthy", "group": "docker"},
        ])
        actions = process_report(report, state_path=state_file)
        docker_actions = [a for a in actions if "docker" in a["title"].lower()]
        assert len(docker_actions) == 1
        assert "docker-running" in docker_actions[0]["message"]
        assert "docker-healthy" in docker_actions[0]["message"]


class TestRecovery:
    def test_recovery_notification(self, tmp_path: Path):
        """When a check transitions from alerted failure -> healthy, send recovery."""
        state_file = tmp_path / "state.json"

        # First: failure
        fail_report = _make_report([
            {"name": "langfuse-api", "status": "failed", "message": "timeout", "group": "langfuse"},
        ])
        process_report(fail_report, state_path=state_file)

        # Now: recovery
        ok_report = {
            "overall_status": "healthy",
            "groups": [
                {"name": "langfuse", "checks": [
                    {"name": "langfuse-api", "status": "healthy", "message": "ok"},
                ]},
            ],
        }
        actions = process_report(ok_report, state_path=state_file)
        recovery = [a for a in actions if a["title"] == "Recovered"]
        assert len(recovery) == 1
        assert "langfuse-api" in recovery[0]["message"]


class TestCorruptState:
    def test_corrupt_state_file_handled(self, tmp_path: Path):
        """A corrupt state file should be handled gracefully (reset to empty)."""
        state_file = tmp_path / "state.json"
        state_file.write_text("not valid json {{{")

        report = _make_report([
            {"name": "check-a", "status": "failed", "message": "bad", "group": "misc"},
        ])
        actions = process_report(report, state_path=state_file)
        assert len(actions) >= 1

    def test_missing_state_file_ok(self, tmp_path: Path):
        """Missing state file should work (first run)."""
        state_file = tmp_path / "nonexistent" / "state.json"
        report = _make_report([
            {"name": "check-b", "status": "degraded", "message": "slow", "group": "misc"},
        ])
        actions = process_report(report, state_path=state_file)
        assert len(actions) >= 1
        assert state_file.exists()
