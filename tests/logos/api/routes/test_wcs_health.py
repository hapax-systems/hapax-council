"""Tests for the WCS health dashboard API."""

from __future__ import annotations

from logos.api.routes.wcs_health import (
    DashboardResponse,
    HealthRowSummary,
    _envelope_to_dashboard,
    _record_to_row,
)
from shared.world_surface_health import (
    HealthStatus,
    load_world_surface_health_fixtures,
)


def _fixtures():
    return load_world_surface_health_fixtures()


def test_dashboard_response_has_all_records() -> None:
    fixtures = _fixtures()
    dashboard = _envelope_to_dashboard(fixtures.envelopes[0])
    assert isinstance(dashboard, DashboardResponse)
    assert dashboard.total_surfaces == len(fixtures.envelopes[0].records)
    assert len(dashboard.rows) == dashboard.total_surfaces


def test_dashboard_response_reflects_envelope_counts() -> None:
    fixtures = _fixtures()
    dashboard = _envelope_to_dashboard(fixtures.envelopes[0])
    assert dashboard.blocked_count == fixtures.envelopes[0].blocked_surface_count
    assert dashboard.stale_count == fixtures.envelopes[0].stale_surface_count
    assert dashboard.unsafe_count == fixtures.envelopes[0].unsafe_surface_count
    assert dashboard.unknown_count == fixtures.envelopes[0].unknown_surface_count


def test_health_row_summary_has_required_fields() -> None:
    fixtures = _fixtures()
    record = fixtures.envelopes[0].records[0]
    row = _record_to_row(record)
    assert isinstance(row, HealthRowSummary)
    assert row.surface_id == record.surface_id
    assert row.status == record.status.value
    assert row.public_claim_allowed == record.public_claim_allowed
    assert row.monetization_allowed == record.monetization_allowed
    assert row.claimable_health == record.claimable_health
    assert isinstance(row.blocking_reasons, list)


def test_dashboard_statuses_are_machine_readable() -> None:
    fixtures = _fixtures()
    dashboard = _envelope_to_dashboard(fixtures.envelopes[0])
    valid_statuses = {s.value for s in HealthStatus}
    for row in dashboard.rows:
        assert row.status in valid_statuses, f"{row.surface_id} has invalid status: {row.status}"


def test_no_row_implies_public_without_evidence() -> None:
    fixtures = _fixtures()
    dashboard = _envelope_to_dashboard(fixtures.envelopes[0])
    for row in dashboard.rows:
        if not row.claimable_health:
            assert not row.public_claim_allowed, (
                f"{row.surface_id}: public_claim_allowed but not claimable_health"
            )
        if not row.public_claim_allowed:
            assert not row.monetization_allowed, (
                f"{row.surface_id}: monetization_allowed but not public_claim_allowed"
            )


def test_blocked_surfaces_filter() -> None:
    fixtures = _fixtures()
    envelope = fixtures.envelopes[0]
    non_healthy = {
        HealthStatus.BLOCKED,
        HealthStatus.DEGRADED,
        HealthStatus.STALE,
        HealthStatus.UNSAFE,
        HealthStatus.MISSING,
        HealthStatus.UNKNOWN,
    }
    expected_blocked = [r for r in envelope.records if r.status in non_healthy]
    dashboard = _envelope_to_dashboard(envelope)
    blocked_rows = [r for r in dashboard.rows if r.status in {s.value for s in non_healthy}]
    assert len(blocked_rows) == len(expected_blocked)


def test_claimable_surfaces_filter() -> None:
    fixtures = _fixtures()
    envelope = fixtures.envelopes[0]
    expected_claimable = [r for r in envelope.records if r.claimable_health]
    dashboard = _envelope_to_dashboard(envelope)
    claimable_rows = [r for r in dashboard.rows if r.claimable_health]
    assert len(claimable_rows) == len(expected_claimable)
