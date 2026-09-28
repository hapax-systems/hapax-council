"""E1 quantities reach A1's existing quota ledger reader without inventing zero usage."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from shared.entitlement_census import EXTRACTORS
from shared.platform_capability_registry import (
    PLATFORM_CAPABILITY_REGISTRY,
    PlatformCapabilityRegistry,
)
from shared.quota_headroom import collect_measurements, enrich_ledger, read_census_measurements
from shared.quota_spend_ledger import QuotaMeasurement, load_quota_spend_ledger

NOW = datetime(2026, 9, 28, 20, tzinfo=UTC)


def _file(home: Path, *, at=NOW, rows=None) -> Path:
    path = home / ".cache/hapax/entitlement-census/measurements.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "producer": "scripts/hapax-entitlement-census",
                "generated_at": at.isoformat(),
                "measurements": rows if rows is not None else [],
            }
        )
    )
    return path


def test_census_quantity_validates_as_a1_measurement_and_reaches_collector(tmp_path: Path):
    reading = EXTRACTORS["kimi_usages"](
        {
            "usage": {"limit": "100", "used": "5", "resetTime": "2026-10-01T00:00:00Z"},
        },
        NOW,
        "entitlement-census:test",
    ).measurements[0]
    assert QuotaMeasurement.model_validate(reading).quantity == 5.0
    _file(tmp_path, rows=[reading])
    grouped = read_census_measurements(tmp_path, now=NOW)
    assert grouped["kimi"][0].capacity_id == "kimi.subscription.weekly"
    collected = collect_measurements(tmp_path, tmp_path / "receipts", now=NOW)
    assert any(
        row.capacity_id == "kimi.subscription.weekly" and row.source == "entitlement-census:test"
        for row in collected["kimi"]
    )
    registry = PlatformCapabilityRegistry.model_validate(
        json.loads(PLATFORM_CAPABILITY_REGISTRY.read_text())
    )
    ledger = enrich_ledger(load_quota_spend_ledger(), collected, registry=registry, now=NOW)
    kimi = [row for row in ledger.quota_snapshots if row.family == "kimi"]
    assert kimi
    assert any(
        item.capacity_id == "kimi.subscription.weekly" and item.source == "entitlement-census:test"
        for snapshot in kimi
        for item in (snapshot, *snapshot.measurements)
    )


def test_missing_stale_and_unreadable_census_are_unobserved(tmp_path: Path):
    absent = read_census_measurements(tmp_path, now=NOW)
    assert absent["census"][0].reason_code == "census_measurements_absent"
    path = _file(tmp_path, at=NOW - timedelta(hours=2))
    stale = read_census_measurements(tmp_path, now=NOW)
    assert stale["census"][0].reason_code == "census_measurements_stale"
    path.write_text("{broken")
    broken = read_census_measurements(tmp_path, now=NOW)
    assert broken["census"][0].reason_code == "census_measurements_unreadable"
    assert broken["census"][0].quantity is None


def test_one_invalid_measurement_invalidates_the_batch(tmp_path: Path):
    _file(tmp_path, rows=[{"capacity_id": "kimi.weekly", "quantity": 0, "label": "unobserved"}])
    grouped = read_census_measurements(tmp_path, now=NOW)
    assert set(grouped) == {"census"}
    assert grouped["census"][0].reason_code == "census_measurements_unreadable"
