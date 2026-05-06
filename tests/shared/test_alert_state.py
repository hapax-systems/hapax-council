"""Tests for shared.alert_state.process_report.

174-LOC alert state machine for health-watchdog. Provides
deduplication, escalation, grouping, recovery notifications.
Untested before this commit.

Tests use a tmp state path so the operator's real
profiles/alert-state.json is never read or mutated.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from shared.alert_state import process_report


def _report(checks: list[tuple[str, str, str]], group: str = "general") -> dict:
    """Build a minimal health report.

    ``checks`` is a list of (name, status, message) triples.
    """
    return {
        "groups": [
            {
                "name": group,
                "checks": [{"name": n, "status": s, "message": m} for n, s, m in checks],
            }
        ]
    }


# ── Healthy paths ──────────────────────────────────────────────────


class TestHealthyPath:
    def test_first_seen_healthy_no_action(self, tmp_path: Path) -> None:
        actions = process_report(
            _report([("check-a", "healthy", "ok")]), state_path=tmp_path / "s.json"
        )
        assert actions == []

    def test_recovery_emits_notification(self, tmp_path: Path) -> None:
        """A check that was previously alerted and is now healthy emits
        a 'Recovered' notification."""
        state_path = tmp_path / "s.json"
        # Seed prior failed-and-alerted state.
        state_path.write_text(
            json.dumps(
                {
                    "check-a": {
                        "status": "failed",
                        "alerted": True,
                        "since": 100.0,
                        "cycles": 1,
                    }
                }
            )
        )
        actions = process_report(_report([("check-a", "healthy", "ok")]), state_path=state_path)
        assert len(actions) == 1
        assert actions[0]["title"] == "Recovered"
        assert "check-a" in actions[0]["message"]
        assert actions[0]["priority"] == "default"

    def test_recovery_skipped_if_never_alerted(self, tmp_path: Path) -> None:
        state_path = tmp_path / "s.json"
        state_path.write_text(
            json.dumps({"check-a": {"status": "failed", "alerted": False, "cycles": 1}})
        )
        actions = process_report(_report([("check-a", "healthy", "ok")]), state_path=state_path)
        assert actions == []


# ── Failure + escalation ───────────────────────────────────────────


class TestFailureEscalation:
    def test_first_failure_emits_high_priority(self, tmp_path: Path) -> None:
        """A 'failed' status (any group) gets >=high priority on first cycle."""
        actions = process_report(
            _report([("c1", "failed", "down")], group="general"),
            state_path=tmp_path / "s.json",
        )
        assert len(actions) == 1
        assert actions[0]["priority"] == "high"

    def test_t0_failed_two_cycles_escalates_to_urgent(self, tmp_path: Path) -> None:
        """T0 group + failed status + cycles >= 2 → urgent."""
        state_path = tmp_path / "s.json"
        # First cycle: failed → high
        process_report(
            _report([("docker-up", "failed", "down")], group="docker"),
            state_path=state_path,
        )
        # Move clock past dedup window so the second alert fires.
        with patch("shared.alert_state.time") as mock_time:
            mock_time.time.return_value = time.time() + 60 * 60 + 1
            actions = process_report(
                _report([("docker-up", "failed", "down")], group="docker"),
                state_path=state_path,
            )
        # Second cycle: T0 + failed + 2 cycles → urgent
        assert any(a["priority"] == "urgent" for a in actions)

    def test_degraded_below_threshold_default(self, tmp_path: Path) -> None:
        """Non-T0 degraded on first cycle → default priority."""
        actions = process_report(
            _report([("c1", "degraded", "slow")], group="general"),
            state_path=tmp_path / "s.json",
        )
        assert len(actions) == 1
        assert actions[0]["priority"] == "default"


# ── Dedup window ───────────────────────────────────────────────────


class TestDedup:
    def test_same_failure_within_window_skipped(self, tmp_path: Path) -> None:
        """Identical status + priority within 30min dedup window → no
        re-alert."""
        state_path = tmp_path / "s.json"
        first = process_report(
            _report([("c1", "failed", "down")], group="general"),
            state_path=state_path,
        )
        assert len(first) == 1
        # Same failure 1min later — within dedup window.
        with patch("shared.alert_state.time") as mock_time:
            mock_time.time.return_value = time.time() + 60
            second = process_report(
                _report([("c1", "failed", "down")], group="general"),
                state_path=state_path,
            )
        assert second == []

    def test_dedup_broken_after_window(self, tmp_path: Path) -> None:
        """Past 30min, the same failure re-alerts."""
        state_path = tmp_path / "s.json"
        process_report(
            _report([("c1", "failed", "down")], group="general"),
            state_path=state_path,
        )
        with patch("shared.alert_state.time") as mock_time:
            mock_time.time.return_value = time.time() + 60 * 60  # 1 hour later
            second = process_report(
                _report([("c1", "failed", "down")], group="general"),
                state_path=state_path,
            )
        assert len(second) == 1


# ── Group aggregation ─────────────────────────────────────────────


class TestGroupAggregation:
    def test_multiple_failures_one_per_group(self, tmp_path: Path) -> None:
        """Multiple failed checks in same group aggregate into one
        notification."""
        actions = process_report(
            _report(
                [
                    ("c1", "failed", "down"),
                    ("c2", "failed", "timeout"),
                ],
                group="general",
            ),
            state_path=tmp_path / "s.json",
        )
        assert len(actions) == 1
        msg = actions[0]["message"]
        assert "c1" in msg
        assert "c2" in msg

    def test_group_priority_uses_highest(self, tmp_path: Path) -> None:
        """Group priority reflects the highest individual check priority."""
        state_path = tmp_path / "s.json"
        # Seed t0 docker check with prev failed (cycles will be 2)
        state_path.write_text(
            json.dumps(
                {
                    "docker-up": {
                        "status": "failed",
                        "cycles": 1,
                        "alerted": True,
                        "alert_status": "failed",
                        "alert_priority": "high",
                        "last_alert_time": time.time() - 7200,  # 2hr ago
                    }
                }
            )
        )
        actions = process_report(
            _report(
                [("docker-up", "failed", "down")],
                group="docker",
            ),
            state_path=state_path,
        )
        # T0 + 2 cycles → urgent priority on the group notification
        assert actions
        assert actions[0]["priority"] == "urgent"


# ── State persistence ─────────────────────────────────────────────


class TestStatePersistence:
    def test_state_file_written_atomically(self, tmp_path: Path) -> None:
        state_path = tmp_path / "subdir" / "s.json"
        process_report(_report([("c1", "healthy", "ok")]), state_path=state_path)
        assert state_path.exists()
        # No leftover .tmp.
        assert not state_path.with_suffix(".tmp").exists()
        # File is well-formed JSON.
        json.loads(state_path.read_text())

    def test_corrupt_state_file_treated_as_empty(self, tmp_path: Path) -> None:
        state_path = tmp_path / "s.json"
        state_path.write_text("{ corrupt")
        # Should not crash; should treat as empty + emit alert.
        actions = process_report(
            _report([("c1", "failed", "down")], group="general"),
            state_path=state_path,
        )
        assert len(actions) == 1


# ── Recovery + tags ───────────────────────────────────────────────


class TestRecoveryTags:
    def test_recovery_uses_check_mark_tag(self, tmp_path: Path) -> None:
        state_path = tmp_path / "s.json"
        state_path.write_text(
            json.dumps(
                {
                    "c1": {
                        "status": "failed",
                        "alerted": True,
                        "cycles": 1,
                    }
                }
            )
        )
        actions = process_report(_report([("c1", "healthy", "ok")]), state_path=state_path)
        assert "white_check_mark" in actions[0]["tags"]


import pytest


@pytest.mark.parametrize(
    "payload,kind",
    [("null", "null"), ('"a"', "string"), ("[1,2]", "list"), ("42", "int")],
)
def test_process_report_non_dict_state_does_not_crash(tmp_path, payload, kind):
    """Pin process_report against non-dict alert-state JSON. Callers
    use state.get(check_name, {}) and state[check_name] = ... — non-
    dict roots crashed those operations."""
    state_path = tmp_path / "s.json"
    state_path.write_text(payload)
    # Must not raise — corrupt state resets to empty.
    actions = process_report(_report([("check-a", "healthy", "ok")]), state_path=state_path)
    assert isinstance(actions, list), f"non-dict root={kind} must not crash"
