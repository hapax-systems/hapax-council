"""Tests for activity-aware briefing delivery gating."""

from __future__ import annotations

import json


class TestActivityGating:
    """Briefing delivery gated on watch activity state."""

    def test_delivers_immediately_when_active(self, tmp_path):
        """Delivers when activity state shows WALKING."""
        from agents.briefing import should_deliver_briefing

        activity = tmp_path / "activity.json"
        activity.write_text(
            json.dumps(
                {
                    "state": "WALKING",
                    "updated_at": "2026-03-12T07:05:00-05:00",
                }
            )
        )
        assert should_deliver_briefing(watch_dir=tmp_path) is True

    def test_waits_when_still(self, tmp_path):
        """Defers when activity state is STILL (asleep)."""
        from agents.briefing import should_deliver_briefing

        activity = tmp_path / "activity.json"
        activity.write_text(
            json.dumps(
                {
                    "state": "STILL",
                    "updated_at": "2026-03-12T07:00:00-05:00",
                }
            )
        )
        assert should_deliver_briefing(watch_dir=tmp_path, current_hour=7) is False

    def test_delivers_when_no_watch_data(self, tmp_path):
        """Delivers immediately (graceful degradation) when no watch data."""
        from agents.briefing import should_deliver_briefing

        assert should_deliver_briefing(watch_dir=tmp_path) is True

    def test_delivers_at_hard_deadline(self, tmp_path):
        """Delivers at 09:00 regardless of activity state."""
        from agents.briefing import should_deliver_briefing

        activity = tmp_path / "activity.json"
        activity.write_text(
            json.dumps(
                {
                    "state": "STILL",
                    "updated_at": "2026-03-12T09:01:00-05:00",
                }
            )
        )
        assert should_deliver_briefing(watch_dir=tmp_path, current_hour=9, current_minute=1) is True


import pytest


@pytest.mark.parametrize(
    "payload,kind",
    [("null", "null"), ('"a"', "string"), ("[1,2]", "list"), ("42", "int")],
)
def test_should_deliver_briefing_non_dict_activity_returns_true(tmp_path, payload, kind):
    """Pin should_deliver_briefing against non-dict activity.json. The
    data.get('state', ...) call inside (json.JSONDecodeError, OSError)
    catch let AttributeError escape on non-dict roots — gracefully
    degrade to True (deliver briefing) instead of crashing."""
    from agents.briefing import should_deliver_briefing

    activity = tmp_path / "activity.json"
    activity.write_text(payload)
    # Must not crash; graceful degradation returns True.
    result = should_deliver_briefing(watch_dir=tmp_path, current_hour=9, current_minute=1)
    assert result is True, f"non-dict root={kind} must yield True (degraded)"
