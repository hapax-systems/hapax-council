"""Tests for shared.health_correlator — cross-signal correlation (mocked)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from shared.health_correlator import (
    CorrelatedEvent,
    CorrelationCluster,
    _cluster_events,
    _collect_health_events,
)


def _ts(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


class TestClustering:
    def test_events_within_window_clustered(self):
        events = [
            CorrelatedEvent(timestamp=_ts(10), source="health", event="docker.qdrant failed"),
            CorrelatedEvent(timestamp=_ts(9), source="langfuse", event="Error trace"),
            CorrelatedEvent(timestamp=_ts(1), source="health", event="docker.ollama failed"),
        ]
        clusters = _cluster_events(events, window_minutes=5)
        # First two events within 1 min of each other → clustered
        # Third event 8 min later → separate
        assert len(clusters) == 1
        assert len(clusters[0].events) == 2

    def test_no_clusters_from_single_events(self):
        events = [
            CorrelatedEvent(timestamp=_ts(60), source="health", event="a"),
            CorrelatedEvent(timestamp=_ts(30), source="health", event="b"),
        ]
        clusters = _cluster_events(events, window_minutes=5)
        assert len(clusters) == 0  # both isolated


class TestHealthEventCollection:
    def test_collect_from_history(self, tmp_path, monkeypatch):
        monkeypatch.setattr("shared.health_correlator.PROFILES_DIR", tmp_path)
        path = tmp_path / "health-history.jsonl"
        entry = {
            "timestamp": _ts(30),
            "status": "failed",
            "failed_checks": ["docker.qdrant"],
        }
        path.write_text(json.dumps(entry))
        events = _collect_health_events(hours=4)
        assert len(events) == 1
        assert "docker.qdrant" in events[0].event
