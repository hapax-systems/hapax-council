"""Tests for activity-aware briefing delivery gating."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

from agents.hapax_voice.watch_signals import read_watch_signal


class TestActivityGating:
    """Briefing delivery gated on watch activity state."""

    def test_delivers_immediately_when_active(self, tmp_path):
        """Delivers when activity state shows WALKING."""
        from agents.briefing import should_deliver_briefing
        activity = tmp_path / "activity.json"
        activity.write_text(json.dumps({
            "state": "WALKING",
            "updated_at": "2026-03-12T07:05:00-05:00",
        }))
        assert should_deliver_briefing(watch_dir=tmp_path) is True

    def test_waits_when_still(self, tmp_path):
        """Defers when activity state is STILL (asleep)."""
        from agents.briefing import should_deliver_briefing
        activity = tmp_path / "activity.json"
        activity.write_text(json.dumps({
            "state": "STILL",
            "updated_at": "2026-03-12T07:00:00-05:00",
        }))
        assert should_deliver_briefing(watch_dir=tmp_path) is False

    def test_delivers_when_no_watch_data(self, tmp_path):
        """Delivers immediately (graceful degradation) when no watch data."""
        from agents.briefing import should_deliver_briefing
        assert should_deliver_briefing(watch_dir=tmp_path) is True

    def test_delivers_at_hard_deadline(self, tmp_path):
        """Delivers at 09:00 regardless of activity state."""
        from agents.briefing import should_deliver_briefing
        activity = tmp_path / "activity.json"
        activity.write_text(json.dumps({
            "state": "STILL",
            "updated_at": "2026-03-12T09:01:00-05:00",
        }))
        assert should_deliver_briefing(
            watch_dir=tmp_path, current_hour=9, current_minute=1
        ) is True
