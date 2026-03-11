"""Tests for cockpit.data.emergence — undomained activity detection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from cockpit.data.emergence import (
    CANDIDATE_MIN_EVENTS,
    EmergenceSnapshot,
    UndomainedEvent,
    cluster_events,
    collect_undomained_events,
)


class TestUndomainedEvents:
    def test_event_dataclass(self) -> None:
        """UndomainedEvent has required fields."""
        e = UndomainedEvent(
            timestamp="2026-03-04T12:00:00Z",
            source="vault",
            description="Created note in 20-personal/woodworking/project.md",
            keywords=["woodworking", "project"],
            people=[],
        )
        assert e.source == "vault"
        assert len(e.keywords) == 2

    def test_collect_empty_vault(self, tmp_path: Path) -> None:
        """Empty vault produces no undomained events."""
        events = collect_undomained_events(
            vault_path=tmp_path,
            domain_paths={"management": ["10-work"]},
        )
        assert events == []


class TestClustering:
    def test_empty_events(self) -> None:
        """No events => no candidates."""
        assert cluster_events([]) == []

    def test_insufficient_events(self) -> None:
        """Fewer than CANDIDATE_MIN_EVENTS events => no candidate."""
        events = [
            UndomainedEvent(
                timestamp="2026-03-01T12:00:00Z",
                source="vault",
                description="single event",
                keywords=["test"],
                people=[],
            )
        ]
        assert cluster_events(events) == []

    def test_sufficient_cluster(self) -> None:
        """Events meeting threshold produce a candidate."""
        base = datetime(2026, 3, 1, tzinfo=UTC)
        events = []
        for i in range(CANDIDATE_MIN_EVENTS + 1):
            day_offset = (i % 3) * 7  # spread across 3 weeks
            events.append(
                UndomainedEvent(
                    timestamp=(base + timedelta(days=day_offset, hours=i)).isoformat(),
                    source="vault",
                    description=f"woodworking project {i}",
                    keywords=["woodworking", "project", "tools"],
                    people=[],
                )
            )
        candidates = cluster_events(events)
        assert len(candidates) >= 1
        assert candidates[0].event_count >= CANDIDATE_MIN_EVENTS


class TestEmergenceSnapshot:
    def test_snapshot_fields(self) -> None:
        """EmergenceSnapshot has expected fields."""
        s = EmergenceSnapshot(
            candidates=[],
            undomained_event_count=0,
            computed_at="2026-03-04T00:00:00Z",
        )
        assert s.undomained_event_count == 0
