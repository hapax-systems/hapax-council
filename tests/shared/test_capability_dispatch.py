"""Gate-0A tests for capability catalogue and current-evidence resolution."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.capability_dispatch import (
    CAPABILITY_ALIASES,
    DEFAULT_REGISTRY_PATH,
    UNROUTED_POINTERS,
    CapabilityResolution,
    CapabilityState,
    build_dispatch_carrier,
    catalogued_aliases,
    catalogued_route_ids,
    default_dispatch_ledger,
    dispatch_carrier_hash,
    load_capability_registry,
    registry_error,
    resolve_capability,
    resolve_catalogued_capability,
    split_route_id,
    utilization_status,
    verify_dispatch_carrier,
)
from shared.platform_capability_registry import PlatformCapabilityRegistry

FRESH_NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


def _support(carrier: dict, code: str) -> object:
    matches = [item for item in carrier["support"] if item["code"] == code]
    assert len(matches) == 1
    assert matches[0]["claim_ceiling"] == "support_non_authoritative"
    return matches[0]["value"]


def _raw_registry() -> dict:
    return json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))


def _fresh_registry(route_id: str = "codex.headless.full") -> PlatformCapabilityRegistry:
    payload = _raw_registry()
    route = next(item for item in payload["routes"] if item["route_id"] == route_id)
    observed = "2026-07-12T11:59:00Z"
    route["route_state"] = "active"
    route["blocked_reasons"] = []
    for surface in ("capability", "quota", "resource", "provider_docs"):
        route["freshness"][f"{surface}_checked_at"] = observed
        route["freshness"]["evidence"][surface] = {
            "evidence_refs": [f"test:{route_id}:{surface}"],
            "blocked_reasons": [],
        }
    for score in route["capability_scores"].values():
        score["observed_at"] = observed
    for tool in route["tool_state"]:
        tool["observed_at"] = observed
    return PlatformCapabilityRegistry.model_validate(payload)


def _catalogue() -> frozenset[str]:
    return catalogued_route_ids(load_capability_registry(receipt_dir=Path("/nonexistent")))


def test_static_alias_resolution_is_catalogued_not_available() -> None:
    resolution = resolve_catalogued_capability("  CODEX ", route_ids=_catalogue())
    assert resolution.state is CapabilityState.CATALOGUED
    assert resolution.route_id == "codex.headless.full"
    assert resolution.available is False
    assert resolution.catalogued is True
    assert (resolution.platform, resolution.mode, resolution.profile) == (
        "codex",
        "headless",
        "full",
    )


def test_raw_route_catalogue_resolution_does_not_infer_supply() -> None:
    resolution = resolve_catalogued_capability("claude.headless.opus", route_ids=_catalogue())
    assert resolution.state is CapabilityState.CATALOGUED
    assert "availability has not been evaluated" in resolution.reason


def test_known_unrouted_name_is_held_and_unknown_name_is_unknown() -> None:
    held = resolve_catalogued_capability("fugu", route_ids=_catalogue())
    unknown = resolve_catalogued_capability("not-a-capability", route_ids=_catalogue())
    assert held.state is CapabilityState.HELD and held.route_id is None
    assert unknown.state is CapabilityState.UNKNOWN and unknown.route_id is None


def test_alias_catalogue_drift_is_a_hold() -> None:
    resolution = resolve_catalogued_capability(
        "codex-spark", route_ids=_catalogue() - {"codex.headless.spark"}
    )
    assert resolution.state is CapabilityState.HELD
    assert "absent from the typed registry catalogue" in resolution.reason


def test_current_resolution_uses_typed_freshness_and_policy_evidence() -> None:
    available = resolve_capability("codex", registry=_fresh_registry(), now=FRESH_NOW)
    assert available.state is CapabilityState.AVAILABLE
    assert available.checked_at == "2026-07-12T12:00:00Z"
    assert available.evidence_refs
    assert available.blocker_reasons == ()

    seed = load_capability_registry(receipt_dir=Path("/nonexistent"))
    held = resolve_capability("codex", registry=seed, now=FRESH_NOW)
    assert held.state is CapabilityState.HELD
    assert held.route_id == "codex.headless.full"
    assert held.blocker_reasons
    assert "blocked" in held.reason or "stale" in held.reason


def test_catalogued_aliases_include_non_worker_surfaces_without_calling_them_launchable() -> None:
    aliases = catalogued_aliases(_catalogue())
    assert aliases["codex"] == "codex.headless.full"
    assert aliases["agy-review"] == "agy.review.direct"
    assert aliases["api"] == "api.headless.provider_gateway"
    assert aliases["local-worker"] == "local_tool.local.worker"


def test_aliases_are_well_formed_and_unrouted_names_are_disjoint() -> None:
    assert set(UNROUTED_POINTERS).isdisjoint(CAPABILITY_ALIASES)
    assert all(split_route_id(route_id) is not None for route_id in CAPABILITY_ALIASES.values())
    assert split_route_id("two.parts") is None
    assert split_route_id("a..c") is None


def test_typed_registry_error_is_visible(tmp_path: Path) -> None:
    malformed = tmp_path / "registry.json"
    malformed.write_text("{not json", encoding="utf-8")
    detail = registry_error(malformed)
    assert detail is not None
    assert "invalid platform capability registry" in detail


def test_carrier_is_exact_rehashable_and_always_negative_state() -> None:
    resolution = resolve_capability("codex", registry=_fresh_registry(), now=FRESH_NOW)
    first = build_dispatch_carrier(
        resolution=resolution,
        task_id="cc-task-example",
        lane="cx-red",
        requested_operation="validate",
        mq_message_id="message-1",
        idempotency_key="key-1",
    )
    second = build_dispatch_carrier(
        resolution=resolution,
        task_id="cc-task-example",
        lane="cx-red",
        requested_operation="validate",
        mq_message_id="message-1",
        idempotency_key="key-1",
    )
    assert first == second
    assert verify_dispatch_carrier(first)
    assert first["carrier_hash"] == dispatch_carrier_hash(first)
    assert first["carrier_ref"] == (f"methodology-dispatch-carrier@sha256:{first['carrier_hash']}")
    assert first["effect_state"] == "held_not_admitted"
    assert first["materialization_state"] == "not_materialized"
    assert first["correlation"] == {
        "schema": "hapax.dispatch-correlation.v1",
        "mq_message_id": "message-1",
        "idempotency_key": "key-1",
    }
    assert _support(first, "capability.state") == "available"
    assert _support(first, "task.validation_state") == "not_evaluated"


def test_launch_compatibility_request_cannot_change_effect_state() -> None:
    resolution = resolve_capability("codex", registry=_fresh_registry(), now=FRESH_NOW)
    carrier = build_dispatch_carrier(
        resolution=resolution,
        task_id="cc-task-example",
        lane="cx-red",
        requested_operation="launch",
    )
    assert carrier["requested_operation"] == "launch"
    assert carrier["effect_state"] == "held_not_admitted"
    assert carrier["materialization_state"] == "not_materialized"
    assert verify_dispatch_carrier(carrier)


def test_carrier_tamper_requires_a_new_content_address() -> None:
    resolution = resolve_catalogued_capability("codex", route_ids=_catalogue())
    carrier = build_dispatch_carrier(
        resolution=resolution,
        task_id="cc-task-example",
        lane="cx-red",
        requested_operation="validate",
    )
    carrier["task_id"] = "other-task"
    assert not verify_dispatch_carrier(carrier)


def test_carrier_refuses_an_unresolved_capability() -> None:
    unresolved = CapabilityResolution(
        capability="unknown",
        state=CapabilityState.UNKNOWN,
        reason="unknown",
    )
    with pytest.raises(ValueError, match="catalogued route"):
        build_dispatch_carrier(
            resolution=unresolved,
            task_id="cc-task-example",
            lane="cx-red",
            requested_operation="validate",
        )


def test_legacy_utilization_is_support_only_unknown() -> None:
    status = utilization_status()
    assert status.state is CapabilityState.UNKNOWN
    assert status.legacy_source_authority == "support_only_not_consumed"
    assert "cannot prove ACTIVE or LATENT" in status.reason


def test_retired_ledger_symbol_preserves_imports_without_returning_an_evidence_path() -> None:
    assert default_dispatch_ledger() is None


def test_source_has_no_static_launchable_or_legacy_ledger_reader() -> None:
    source = Path(__import__("shared.capability_dispatch", fromlist=["x"]).__file__).read_text(
        encoding="utf-8"
    )
    assert "LAUNCHABLE_PATHS" not in source
    assert "launchable_aliases" not in source
    assert "read_dispatch_ledger" not in source
    assert "ledger_health" not in source
