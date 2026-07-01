from __future__ import annotations

from datetime import UTC, datetime

import pytest

from shared.capability_surface_delta import (
    AuthorityCeiling,
    CapabilitySurfaceDelta,
    CapabilitySurfaceDeltaError,
    CapabilitySurfaceDescriptor,
    DeltaKind,
    FreshnessState,
    RequiredIntakeAction,
    SurfaceKind,
    build_surface_delta,
    detect_surface_deltas,
    load_capability_surface_delta_file,
    load_capability_surface_delta_fixtures,
    render_capability_surface_delta_task,
    task_filename_for_delta,
    task_id_for_delta,
    write_capability_surface_delta_tasks,
)

NOW = datetime(2026, 7, 1, 4, 30, tzinfo=UTC)


def _descriptor(**overrides: object) -> CapabilitySurfaceDescriptor:
    payload = {
        "surface_id": "route.glmcp.review.direct",
        "descriptor_ref": "platform-capability-registry:glmcp.review.direct",
        "surface_kind": SurfaceKind.REVIEW_SEAT,
        "authority_ceiling": AuthorityCeiling.READ_ONLY,
        "observed_at": datetime(2026, 7, 1, 4, 0, tzinfo=UTC),
        "stale_after": "1h",
        "evidence_refs": ["platform-capability-receipt:glmcp:fixture"],
        "route_id": "glmcp.review.direct",
        "supply_leaf_id": "z_ai-glm-5.review.direct",
        "carrier_platform": "glmcp",
        "model_id": "z_ai-glm-5",
        "provider_id": "z_ai",
        "effort": "xhigh",
        "context_window": "large",
        "resource_pools": ["subscription_quota"],
        "tool_refs": ["hapax-glmcp-reviewer"],
        "harness_refs": ["review-seat-adapter"],
        "privacy_sensitive": True,
    }
    payload.update(overrides)
    return CapabilitySurfaceDescriptor.model_validate(payload)


def test_fixture_loader_covers_new_stale_and_authority_delta_cases() -> None:
    fixtures = load_capability_surface_delta_fixtures()

    assert {delta.delta_kind for delta in fixtures.deltas} >= {
        DeltaKind.NEW_CAPABILITY,
        DeltaKind.STALE_DETERMINATION,
        DeltaKind.AUTHORITY_CHANGED,
    }
    for delta in fixtures.deltas:
        assert delta.allows_demand_fulfillment() is False


def test_new_capability_delta_mints_intake_and_is_delta_pending() -> None:
    observed = _descriptor(
        surface_id="route.openrouter.qwen3-coder.high",
        descriptor_ref="provider-catalog:openrouter:qwen3-coder:high",
        surface_kind=SurfaceKind.MODEL_ROUTE,
        authority_ceiling=AuthorityCeiling.FRONTIER_REVIEW_REQUIRED,
        route_id="openrouter.headless.qwen3_coder_high",
        carrier_platform="openrouter",
        model_id="qwen3-coder",
        provider_id="openrouter",
        resource_pools=["api_paid_spend"],
        money_rail=True,
    )

    delta = build_surface_delta(
        prior=None,
        observed=observed,
        source="unit-test",
        detected_by="test",
        remediation_ref="cc-task-capability-freshness-remediation-and-discovery-automation-20260630",
        now=NOW,
    )

    assert delta is not None
    assert delta.delta_kind is DeltaKind.NEW_CAPABILITY
    assert delta.freshness_state is FreshnessState.DELTA_PENDING
    assert delta.required_intake_action is RequiredIntakeAction.MINT_INTAKE_ITEM
    assert delta.money_rail is True
    assert delta.allows_demand_fulfillment() is False


def test_stale_observation_requires_refresh_receipt_and_blocks_demand_fulfillment() -> None:
    prior = _descriptor()
    observed = _descriptor(
        descriptor_ref="platform-capability-receipt:glmcp:expired",
        observed_at=datetime(2026, 7, 1, 3, 0, tzinfo=UTC),
        stale_after="30m",
    )

    delta = build_surface_delta(
        prior=prior,
        observed=observed,
        source="unit-test",
        detected_by="test",
        remediation_ref="cc-task-capability-freshness-remediation-and-discovery-automation-20260630",
        now=NOW,
    )

    assert delta is not None
    assert delta.delta_kind is DeltaKind.STALE_DETERMINATION
    assert delta.freshness_state is FreshnessState.STALE
    assert delta.required_intake_action is RequiredIntakeAction.REFRESH_RECEIPT
    assert delta.allows_demand_fulfillment() is False


def test_authority_change_is_descriptor_update_not_availability() -> None:
    observed = _descriptor(
        descriptor_ref="publication-bus:weblog:publish-capable",
        surface_id="surface.publication_bus.weblog",
        surface_kind=SurfaceKind.PUBLICATION_BUS,
        authority_ceiling=AuthorityCeiling.FRONTIER_REVIEW_REQUIRED,
        public_egress=True,
        resource_pools=["public_egress"],
    )
    prior = _descriptor(
        descriptor_ref="publication-bus:weblog:read-only",
        surface_id="surface.publication_bus.weblog",
        surface_kind=SurfaceKind.PUBLICATION_BUS,
        authority_ceiling=AuthorityCeiling.READ_ONLY,
        public_egress=False,
        resource_pools=["public_egress"],
    )

    delta = build_surface_delta(
        prior=prior,
        observed=observed,
        source="unit-test",
        detected_by="test",
        remediation_ref="cc-task-capability-freshness-remediation-and-discovery-automation-20260630",
        now=NOW,
    )

    assert delta is not None
    assert delta.delta_kind is DeltaKind.AUTHORITY_CHANGED
    assert delta.required_intake_action is RequiredIntakeAction.UPDATE_DESCRIPTOR
    assert delta.public_egress is True
    assert delta.allows_demand_fulfillment() is False


def test_unchanged_fresh_descriptor_produces_no_delta() -> None:
    prior = _descriptor()
    observed = _descriptor(descriptor_ref="platform-capability-receipt:glmcp:fresh")

    assert (
        build_surface_delta(
            prior=prior,
            observed=observed,
            source="unit-test",
            detected_by="test",
            remediation_ref="cc-task-capability-freshness-remediation-and-discovery-automation-20260630",
            now=NOW,
        )
        is None
    )


def test_detect_surface_deltas_includes_absent_registered_surface() -> None:
    prior = _descriptor()

    deltas = detect_surface_deltas(
        registered=[prior],
        observed=[],
        source="unit-test",
        detected_by="test",
        remediation_ref="cc-task-capability-freshness-remediation-and-discovery-automation-20260630",
        now=NOW,
    )

    assert len(deltas) == 1
    assert deltas[0].delta_kind is DeltaKind.ABSENT_DETERMINATION
    assert deltas[0].freshness_state is FreshnessState.ABSENT
    assert deltas[0].required_intake_action is RequiredIntakeAction.QUARANTINE_SURFACE


def test_actionable_delta_requires_remediation_ref() -> None:
    payload = {
        "delta_id": "bad",
        "source": "unit-test",
        "observed_at": NOW,
        "detected_by": "test",
        "surface_id": "route.new",
        "delta_kind": "new_capability",
        "prior_descriptor_ref": None,
        "observed_descriptor_ref": "catalog:new",
        "evidence_refs": ["catalog:new"],
        "authority_ceiling": "frontier_review_required",
        "affected_resource_pools": [],
        "privacy_sensitive": True,
        "public_egress": False,
        "money_rail": False,
        "freshness_state": "delta_pending",
        "required_intake_action": "mint_intake_item",
        "summary": "missing remediation",
    }

    with pytest.raises(ValueError, match="actionable deltas require remediation_ref"):
        CapabilitySurfaceDelta.model_validate(payload)


def test_delta_requires_explicit_governance_flags() -> None:
    payload = {
        "delta_id": "bad",
        "source": "unit-test",
        "observed_at": NOW,
        "detected_by": "test",
        "surface_id": "route.new",
        "delta_kind": "new_capability",
        "prior_descriptor_ref": None,
        "observed_descriptor_ref": "catalog:new",
        "evidence_refs": ["catalog:new"],
        "authority_ceiling": "frontier_review_required",
        "freshness_state": "delta_pending",
        "required_intake_action": "mint_intake_item",
        "remediation_ref": "cc-task-capability-freshness-remediation-and-discovery-automation-20260630",
        "summary": "missing governance flags",
    }

    with pytest.raises(ValueError, match="affected_resource_pools"):
        CapabilitySurfaceDelta.model_validate(payload)


def test_bad_fixture_file_raises_typed_error(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(CapabilitySurfaceDeltaError):
        load_capability_surface_delta_fixtures(path)


def test_live_producer_file_does_not_require_fixture_coverage_trio(tmp_path) -> None:
    path = tmp_path / "producer.json"
    path.write_text(
        """
{
  "schema_version": 1,
  "schema_ref": "schemas/capability-surface-delta.schema.json",
  "generated_from": ["unit-test"],
  "declared_at": "2026-07-01T04:30:00Z",
  "descriptors": [
    {
      "descriptor_schema": 1,
      "surface_id": "route.codex.headless.full",
      "descriptor_ref": "platform-capability-registry:codex.headless.full",
      "surface_kind": "model_route",
      "authority_ceiling": "authoritative",
      "observed_at": "2026-07-01T04:00:00Z",
      "stale_after": "1h",
      "evidence_refs": ["test:descriptor"],
      "route_id": "codex.headless.full",
      "resource_pools": ["subscription_quota"]
    }
  ],
  "deltas": [
    {
      "delta_schema": 1,
      "delta_id": "test:single-stale-codex",
      "source": "unit-test",
      "observed_at": "2026-07-01T04:30:00Z",
      "detected_by": "unit-test",
      "surface_id": "route.codex.headless.full",
      "delta_kind": "stale_determination",
      "prior_descriptor_ref": "platform-capability-registry:codex.headless.full",
      "observed_descriptor_ref": "platform-capability-receipt:codex:expired",
      "evidence_refs": ["test:expired"],
      "authority_ceiling": "authoritative",
      "affected_resource_pools": ["subscription_quota"],
      "privacy_sensitive": true,
      "public_egress": false,
      "money_rail": false,
      "freshness_state": "stale",
      "required_intake_action": "refresh_receipt",
      "remediation_ref": "cc-task-capability-freshness-remediation-and-discovery-automation-20260630",
      "summary": "single live producer row"
    }
  ]
}
""",
        encoding="utf-8",
    )

    producer_file = load_capability_surface_delta_file(path)

    assert producer_file.fixture_set_id is None
    assert [delta.delta_id for delta in producer_file.deltas] == ["test:single-stale-codex"]


def test_delta_task_render_preserves_governance_metadata() -> None:
    delta = load_capability_surface_delta_fixtures().deltas[0]
    rendered = render_capability_surface_delta_task(delta, generated_at=NOW)

    assert f'task_id: "{task_id_for_delta(delta)}"' in rendered
    assert 'type: "cc-task"' in rendered
    assert 'authority_case: "CASE-CAPACITY-ROUTING-001"' in rendered
    assert f'capability_surface_delta_id: "{delta.delta_id}"' in rendered
    assert f"- `{delta.evidence_refs[0]}`" in rendered
    assert "auto-minted from `capability_surface_delta`" in rendered


def test_delta_task_writer_dry_run_and_apply_are_idempotent(tmp_path) -> None:
    delta = load_capability_surface_delta_fixtures().deltas[0]

    dry = write_capability_surface_delta_tasks(
        [delta],
        task_root=tmp_path,
        generated_at=NOW,
        apply=False,
    )
    assert dry["ok"] is True
    assert len(dry["would_write"]) == 1
    assert not (tmp_path / "active").exists()

    applied = write_capability_surface_delta_tasks(
        [delta],
        task_root=tmp_path,
        generated_at=NOW,
        apply=True,
    )
    assert applied["ok"] is True
    assert len(applied["written"]) == 1
    written = tmp_path / "active" / f"{task_id_for_delta(delta)}.md"
    assert written.exists()

    again = write_capability_surface_delta_tasks(
        [delta],
        task_root=tmp_path,
        generated_at=NOW,
        apply=True,
    )
    assert again["ok"] is True
    assert again["written"] == []
    assert again["skipped_existing"] == [str(written)]


def test_delta_task_writer_does_not_remint_closed_or_refused_tasks(tmp_path) -> None:
    deltas = load_capability_surface_delta_fixtures().deltas[:2]
    closed = tmp_path / "closed" / task_filename_for_delta(deltas[0])
    refused = tmp_path / "refused" / task_filename_for_delta(deltas[1])
    closed.parent.mkdir(parents=True)
    refused.parent.mkdir(parents=True)
    closed.write_text("closed task\n", encoding="utf-8")
    refused.write_text("refused task\n", encoding="utf-8")

    result = write_capability_surface_delta_tasks(
        deltas,
        task_root=tmp_path,
        generated_at=NOW,
        apply=True,
    )

    assert result["ok"] is True
    assert result["written"] == []
    assert result["skipped_existing"] == [str(closed), str(refused)]
    assert not (tmp_path / "active").exists()
