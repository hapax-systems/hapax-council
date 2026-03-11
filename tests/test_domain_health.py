"""Tests for cockpit.data.domain_health — aggregated domain health."""
from __future__ import annotations

import pytest

from cockpit.data.domain_health import (
    DomainStatus,
    DomainHealthSnapshot,
    collect_domain_health,
)


class TestDomainStatus:
    def test_dataclass_fields(self) -> None:
        """DomainStatus has all required fields."""
        s = DomainStatus(
            domain_id="test",
            domain_name="Test",
            status="active",
            sufficiency_score=0.5,
            total_requirements=10,
            satisfied_count=5,
            direction="steady",
            regularity="regular",
            alignment="plateaued",
        )
        assert s.sufficiency_score == 0.5
        assert s.direction == "steady"


class TestDomainHealthSnapshot:
    def test_snapshot_has_domains(self) -> None:
        """collect_domain_health returns a snapshot with domain statuses."""
        snap = collect_domain_health()
        assert isinstance(snap, DomainHealthSnapshot)
        assert isinstance(snap.domains, list)

    def test_snapshot_has_overall_score(self) -> None:
        """Snapshot includes an overall sufficiency score."""
        snap = collect_domain_health()
        assert 0.0 <= snap.overall_score <= 1.0

    def test_snapshot_has_emergence_candidates(self) -> None:
        """Snapshot includes emergence candidate count."""
        snap = collect_domain_health()
        assert snap.emergence_candidate_count >= 0
