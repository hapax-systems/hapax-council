"""Tests for shared/alert_state.py — alert state machine."""

from __future__ import annotations

import json
import time
from pathlib import Path

from agents.health_monitor.models import (
    CheckResult,
    HealthReport,
    Status,
    build_group_result,
    worst_status,
)
from shared.alert_state import (
    DEDUP_WINDOW_S,
    DEGRADED_ESCALATION_CYCLES,
    T0_URGENT_CYCLES,
    process_report,
)


def _make_report(checks: list[dict]) -> dict:
    """Build a health report in the producer's own shape (``HealthReport`` JSON).

    Built from ``build_group_result`` so the fixture cannot drift from what the health monitor
    emits: its groups carry ``group``, not ``name``.

    Args:
        checks: List of dicts with keys: name, status, message, group.
    """
    by_group: dict[str, list[CheckResult]] = {}
    for c in checks:
        g = c.get("group", "misc")
        by_group.setdefault(g, []).append(
            CheckResult(
                name=c["name"],
                group=g,
                status=Status(c["status"]),
                message=c.get("message", ""),
            )
        )
    groups = [build_group_result(g, cs) for g, cs in by_group.items()]
    return HealthReport(
        timestamp="2026-10-10T00:00:00+00:00",
        hostname="test-host",
        overall_status=worst_status(*(g.status for g in groups)) if groups else Status.HEALTHY,
        groups=groups,
    ).model_dump(mode="json")


class TestFirstFailure:
    def test_first_failure_alerts(self, tmp_path: Path):
        """A check going from unknown -> failed should produce an alert."""
        state_file = tmp_path / "state.json"
        report = _make_report(
            [
                {
                    "name": "docker-running",
                    "status": "failed",
                    "message": "docker is down",
                    "group": "docker",
                },
            ]
        )
        actions = process_report(report, state_path=state_file)
        assert len(actions) == 1
        assert actions[0]["title"] == "Health: docker"
        assert "docker-running" in actions[0]["message"]

    def test_first_degraded_alerts(self, tmp_path: Path):
        state_file = tmp_path / "state.json"
        report = _make_report(
            [
                {
                    "name": "disk-space",
                    "status": "degraded",
                    "message": "85% full",
                    "group": "system",
                },
            ]
        )
        actions = process_report(report, state_path=state_file)
        assert len(actions) == 1
        assert actions[0]["priority"] == "default"


class TestDedup:
    def test_dedup_within_window(self, tmp_path: Path):
        """Same check+status within 30min should not re-alert."""
        state_file = tmp_path / "state.json"
        report = _make_report(
            [
                {"name": "gpu-temp", "status": "degraded", "message": "hot", "group": "gpu"},
            ]
        )

        actions1 = process_report(report, state_path=state_file)
        assert len(actions1) == 1

        # Second call immediately -- should be deduped
        actions2 = process_report(report, state_path=state_file)
        assert len(actions2) == 0

    def test_alert_after_dedup_window(self, tmp_path: Path):
        """After 30min, same failure should re-alert."""
        state_file = tmp_path / "state.json"
        report = _make_report(
            [
                {"name": "gpu-temp", "status": "degraded", "message": "hot", "group": "gpu"},
            ]
        )

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
        report = _make_report(
            [
                {
                    "name": "disk-space",
                    "status": "degraded",
                    "message": "85% full",
                    "group": "system",
                },
            ]
        )

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
        report = _make_report(
            [
                {
                    "name": "litellm-health",
                    "status": "failed",
                    "message": "timeout",
                    "group": "litellm",
                },
            ]
        )

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
        report = _make_report(
            [
                {
                    "name": "docker-running",
                    "status": "failed",
                    "message": "down",
                    "group": "docker",
                },
                {
                    "name": "docker-healthy",
                    "status": "failed",
                    "message": "unhealthy",
                    "group": "docker",
                },
            ]
        )
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
        fail_report = _make_report(
            [
                {
                    "name": "langfuse-api",
                    "status": "failed",
                    "message": "timeout",
                    "group": "langfuse",
                },
            ]
        )
        process_report(fail_report, state_path=state_file)

        # Now: recovery
        ok_report = {
            "overall_status": "healthy",
            "groups": [
                {
                    "name": "langfuse",
                    "checks": [
                        {"name": "langfuse-api", "status": "healthy", "message": "ok"},
                    ],
                },
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

        report = _make_report(
            [
                {"name": "check-a", "status": "failed", "message": "bad", "group": "misc"},
            ]
        )
        actions = process_report(report, state_path=state_file)
        assert len(actions) >= 1

    def test_missing_state_file_ok(self, tmp_path: Path):
        """Missing state file should work (first run)."""
        state_file = tmp_path / "nonexistent" / "state.json"
        report = _make_report(
            [
                {"name": "check-b", "status": "degraded", "message": "slow", "group": "misc"},
            ]
        )
        actions = process_report(report, state_path=state_file)
        assert len(actions) >= 1
        assert state_file.exists()


class TestProducerShape:
    def test_group_name_comes_from_the_producer_group_key(self, tmp_path: Path):
        """The producer's groups carry ``group``; reading ``name`` made every group "unknown"."""
        report = _make_report(
            [{"name": "flow.merge_plane", "status": "failed", "message": "red", "group": "flow"}]
        )
        assert "name" not in report["groups"][0]

        actions = process_report(report, state_path=tmp_path / "state.json")

        assert [a["title"] for a in actions] == ["Health: flow"]

    def test_t0_escalation_fires_on_producer_shaped_reports(self, tmp_path: Path, monkeypatch):
        clock = [1_000_000.0]
        monkeypatch.setattr("shared.alert_state.time.time", lambda: clock[0])
        report = _make_report(
            [{"name": "docker-up", "status": "failed", "message": "down", "group": "docker"}]
        )
        state_file = tmp_path / "state.json"
        process_report(report, state_path=state_file)
        clock[0] += DEDUP_WINDOW_S + 1

        actions = process_report(report, state_path=state_file)

        assert actions and actions[0]["priority"] == "urgent"

    def test_the_legacy_name_key_still_reads(self, tmp_path: Path):
        report = {
            "overall_status": "failed",
            "groups": [{"name": "docker", "checks": [{"name": "c", "status": "failed"}]}],
        }

        actions = process_report(report, state_path=tmp_path / "state.json")

        assert [a["title"] for a in actions] == ["Health: docker"]


class TestPolicyParameters:
    """The flow reader's policy: DEGRADED only after 2 h; de-dup until the status or cause
    changes. The defaults stay as they were for every other caller."""

    def _run(self, checks, state_file, **kwargs):
        return process_report(_make_report(checks), state_path=state_file, **kwargs)

    def test_degraded_is_suppressed_until_it_has_lasted_the_minimum(
        self, tmp_path: Path, monkeypatch
    ):
        clock = [1_000_000.0]
        monkeypatch.setattr("shared.alert_state.time.time", lambda: clock[0])
        state_file = tmp_path / "state.json"
        checks = [{"name": "f", "status": "degraded", "message": "slow", "group": "flow"}]
        policy = {"min_duration_s_by_status": {"degraded": 7200}}

        assert self._run(checks, state_file, **policy) == []
        clock[0] += 7199
        assert self._run(checks, state_file, **policy) == []
        clock[0] += 1
        assert len(self._run(checks, state_file, **policy)) == 1

    def test_an_unchanged_failure_is_never_redelivered_without_a_window(
        self, tmp_path: Path, monkeypatch
    ):
        clock = [1_000_000.0]
        monkeypatch.setattr("shared.alert_state.time.time", lambda: clock[0])
        state_file = tmp_path / "state.json"
        checks = [{"name": "f", "status": "failed", "message": "red: test_x", "group": "flow"}]

        assert len(self._run(checks, state_file, dedup_window_s=None)) == 1
        clock[0] += 10 * DEDUP_WINDOW_S
        assert self._run(checks, state_file, dedup_window_s=None) == []

    def test_a_changed_cause_is_delivered_again(self, tmp_path: Path):
        state_file = tmp_path / "state.json"
        policy = {"dedup_window_s": None, "dedup_on_message": True}
        first = [{"name": "f", "status": "failed", "message": "red: test_x", "group": "flow"}]
        second = [{"name": "f", "status": "failed", "message": "red: test_y", "group": "flow"}]

        assert len(self._run(first, state_file, **policy)) == 1
        assert self._run(first, state_file, **policy) == []
        assert len(self._run(second, state_file, **policy)) == 1

    def test_without_a_window_an_escalation_alone_does_not_realert(self, tmp_path: Path):
        state_file = tmp_path / "state.json"
        checks = [{"name": "f", "status": "degraded", "message": "slow", "group": "flow"}]

        sent = [self._run(checks, state_file, dedup_window_s=None) for _ in range(6)]

        assert [len(s) for s in sent] == [1, 0, 0, 0, 0, 0]

    def test_defaults_still_dedup_on_status_only(self, tmp_path: Path):
        state_file = tmp_path / "state.json"
        first = [{"name": "f", "status": "failed", "message": "a", "group": "misc"}]
        second = [{"name": "f", "status": "failed", "message": "b", "group": "misc"}]

        assert len(self._run(first, state_file)) == 1
        assert self._run(second, state_file) == []
