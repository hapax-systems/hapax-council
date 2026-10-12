"""Tests for the coordinator's capability-evidence producer (NO-STALL U3a)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agents.coordinator.capability_evidence import (
    FAMILY_WALL_RESET_UNKNOWN,
    OUTAGE_STORE_UNREADABLE,
    produce_capability_evidence,
)
from shared.dispatcher_policy import (
    DispatchPolicySources,
    RouteAuthorityReceipt,
    build_route_authority_receipt,
    route_authority_receipt_reference,
)
from shared.platform_capability_registry import (
    PlatformCapabilityRegistry,
    load_platform_capability_registry,
)

NOW = datetime(2026, 5, 9, 22, 30, tzinfo=UTC)
FUTURE_RESET = "2026-05-10T04:49:05+00:00"
FUTURE_RESET_Z = "2026-05-10T04:49:05Z"
PAST_RESET = "2026-05-09T21:00:00+00:00"


def _registry_with_routes(
    states: dict[str, tuple[str, tuple[str, ...]]],
) -> PlatformCapabilityRegistry:
    payload = load_platform_capability_registry().model_dump(mode="json")
    by_id = {route["route_id"]: route for route in payload["routes"]}
    for route_id, (state, blocked) in states.items():
        route = by_id[route_id]
        route["route_state"] = state
        route["blocked_reasons"] = list(blocked)
        if state == "active":
            for block in route["freshness"]["evidence"].values():
                block["blocked_reasons"] = []
    return PlatformCapabilityRegistry.model_validate(payload)


def _sources(
    registry: PlatformCapabilityRegistry | None, receipts: tuple[RouteAuthorityReceipt, ...] = ()
) -> DispatchPolicySources:
    return DispatchPolicySources(
        registry=registry,
        route_authority_receipts=receipts,
    )


def _write_outage(path: Path, entries: dict[str, object]) -> Path:
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def _outage_entry(resets_at: str | None = FUTURE_RESET) -> dict[str, object]:
    entry: dict[str, object] = {
        "observed_at": "2026-05-09T22:00:00+00:00",
        "outage_started_at": "2026-05-09T20:00:00+00:00",
    }
    if resets_at is not None:
        entry["wall_evidence"] = {"resets_at": resets_at}
    return entry


def test_walled_family_blocks_otherwise_available_route(tmp_path: Path) -> None:
    registry = _registry_with_routes({"vibe.headless.full": ("active", ())})
    outage = _write_outage(tmp_path / "family-outage.json", {"vibe": _outage_entry()})

    report = produce_capability_evidence(_sources(registry), outage, now=NOW)

    record = report.route("vibe.headless.full")
    assert record is not None
    assert record.available is False
    assert record.family_wall is True
    assert f"family-wall:vibe:resets-at:{FUTURE_RESET_Z}" in record.blocked_reasons
    assert "vibe.headless.full" not in report.usable_routes


def test_expired_family_wall_does_not_block(tmp_path: Path) -> None:
    registry = _registry_with_routes({"vibe.headless.full": ("active", ())})
    outage = _write_outage(
        tmp_path / "family-outage.json", {"vibe": _outage_entry(resets_at=PAST_RESET)}
    )

    report = produce_capability_evidence(_sources(registry), outage, now=NOW)

    record = report.route("vibe.headless.full")
    assert record is not None
    assert record.available is True
    assert record.family_wall is False
    assert record.blocked_reasons == ()
    assert "vibe.headless.full" in report.usable_routes


def test_family_wall_without_reset_time_blocks(tmp_path: Path) -> None:
    registry = _registry_with_routes({"vibe.headless.full": ("active", ())})
    outage = _write_outage(tmp_path / "family-outage.json", {"vibe": _outage_entry(resets_at=None)})

    report = produce_capability_evidence(_sources(registry), outage, now=NOW)

    record = report.route("vibe.headless.full")
    assert record is not None
    assert record.available is False
    assert record.family_wall is True
    assert FAMILY_WALL_RESET_UNKNOWN in record.blocked_reasons


def test_unparseable_family_wall_reset_blocks(tmp_path: Path) -> None:
    registry = _registry_with_routes({"codex.headless.full": ("active", ())})
    outage = _write_outage(
        tmp_path / "family-outage.json",
        {"codex": _outage_entry(resets_at="not-a-timestamp")},
    )

    report = produce_capability_evidence(_sources(registry), outage, now=NOW)

    record = report.route("codex.headless.full")
    assert record is not None
    assert record.available is False
    assert record.family_wall is True
    assert FAMILY_WALL_RESET_UNKNOWN in record.blocked_reasons


def test_absent_outage_store_means_no_walls(tmp_path: Path) -> None:
    registry = _registry_with_routes({"vibe.headless.full": ("active", ())})

    report = produce_capability_evidence(_sources(registry), tmp_path / "absent.json", now=NOW)

    assert report.outage_read_error is None
    assert report.registry_error is None
    assert report.generated_at == NOW
    record = report.route("vibe.headless.full")
    assert record is not None
    assert record.available is True
    assert "vibe.headless.full" in report.usable_routes


def test_unreadable_outage_store_fails_closed(tmp_path: Path) -> None:
    registry = _registry_with_routes({"vibe.headless.full": ("active", ())})
    outage = tmp_path / "family-outage.json"
    outage.write_text("{not json", encoding="utf-8")

    report = produce_capability_evidence(_sources(registry), outage, now=NOW)

    assert report.outage_read_error is not None
    assert report.usable_routes == ()
    assert report.route_evidence
    assert all(not record.available for record in report.route_evidence)
    assert all(
        OUTAGE_STORE_UNREADABLE in record.blocked_reasons for record in report.route_evidence
    )


def test_registry_error_fails_closed(tmp_path: Path) -> None:
    sources = DispatchPolicySources(registry=None, registry_error="registry unreadable")

    report = produce_capability_evidence(sources, tmp_path / "absent.json", now=NOW)

    assert report.registry_error == "registry unreadable"
    assert report.route_evidence == ()
    assert report.usable_routes == ()


def test_registry_blocked_route_stays_blocked(tmp_path: Path) -> None:
    registry = _registry_with_routes(
        {
            "codex.headless.full": ("blocked", ("account_live_quota_receipt_absent",)),
            "vibe.headless.full": ("active", ()),
        }
    )

    report = produce_capability_evidence(_sources(registry), tmp_path / "absent.json", now=NOW)

    blocked = report.route("codex.headless.full")
    assert blocked is not None
    assert blocked.available is False
    assert "account_live_quota_receipt_absent" in blocked.blocked_reasons
    available = report.route("vibe.headless.full")
    assert available is not None
    assert available.available is True
    assert "vibe.headless.full" in report.usable_routes
    assert "codex.headless.full" not in report.usable_routes


def test_receipt_validity_bounds_valid_until(tmp_path: Path) -> None:
    registry = _registry_with_routes({"codex.headless.full": ("active", ())})
    hour = build_route_authority_receipt(
        receipt_type="runtime_actuation",
        route_id="codex.headless.full",
        evidence_refs=("tb-u3a:hour-receipt",),
        task_ids=("policy-test",),
        mutation_surfaces=("source",),
        stale_after="1h",
        issued_at=NOW - timedelta(minutes=10),
    )
    day = build_route_authority_receipt(
        receipt_type="runtime_actuation",
        route_id="codex.headless.full",
        evidence_refs=("tb-u3a:day-receipt",),
        task_ids=("policy-test",),
        mutation_surfaces=("source",),
        stale_after="24h",
        issued_at=NOW,
    )

    report = produce_capability_evidence(
        _sources(registry, receipts=(day, hour)), tmp_path / "absent.json", now=NOW
    )

    record = report.route("codex.headless.full")
    assert record is not None
    assert record.available is True
    assert record.valid_until == NOW + timedelta(minutes=50)
    assert route_authority_receipt_reference(hour) in record.evidence_refs
    assert route_authority_receipt_reference(day) in record.evidence_refs


def test_route_without_receipts_is_valid_one_observer_interval(tmp_path: Path) -> None:
    registry = _registry_with_routes({"vibe.headless.full": ("active", ())})

    short = produce_capability_evidence(
        _sources(registry), tmp_path / "absent.json", now=NOW, observer_interval_s=300
    )
    long = produce_capability_evidence(
        _sources(registry), tmp_path / "absent.json", now=NOW, observer_interval_s=600
    )

    short_record = short.route("vibe.headless.full")
    long_record = long.route("vibe.headless.full")
    assert short_record is not None
    assert long_record is not None
    assert short_record.valid_until == NOW + timedelta(seconds=300)
    assert long_record.valid_until == NOW + timedelta(seconds=600)


def test_family_aliases_are_never_invented(tmp_path: Path) -> None:
    registry = _registry_with_routes({"glmcp.review.direct": ("active", ())})
    outage = _write_outage(tmp_path / "family-outage.json", {"muse": _outage_entry()})

    exact = produce_capability_evidence(_sources(registry), outage, now=NOW)
    aliased = produce_capability_evidence(
        _sources(registry),
        outage,
        now=NOW,
        platform_family_map={"muse": ("glmcp",)},
    )

    exact_record = exact.route("glmcp.review.direct")
    assert exact_record is not None
    assert exact_record.available is True
    assert exact_record.family_wall is False
    aliased_record = aliased.route("glmcp.review.direct")
    assert aliased_record is not None
    assert aliased_record.available is False
    assert aliased_record.family_wall is True
    assert f"family-wall:muse:resets-at:{FUTURE_RESET_Z}" in aliased_record.blocked_reasons


def test_negative_observer_interval_is_rejected(tmp_path: Path) -> None:
    registry = _registry_with_routes({"vibe.headless.full": ("active", ())})

    with pytest.raises(ValueError):
        produce_capability_evidence(
            _sources(registry), tmp_path / "absent.json", now=NOW, observer_interval_s=0
        )
