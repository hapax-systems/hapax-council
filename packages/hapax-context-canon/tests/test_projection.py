from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from hapax.context_canon import (
    CanonError,
    ContextBundleCompatibilityProjection,
    ContextFrame,
    ProjectionEnvelope,
    canonical_json_bytes,
    project_context_bundle_v1,
    project_context_frame,
    verify_context_bundle_v1,
    verify_projection,
)
from hapax.context_canon.contract import _domain_hash

FIXTURES = Path(__file__).parent / "fixtures"


def _frame_payload() -> dict[str, object]:
    return json.loads((FIXTURES / "gate0-frame.json").read_text())


def _operator_projection() -> ProjectionEnvelope:
    payload = json.loads((FIXTURES / "gate0-projections.json").read_text())["operator"]
    return ProjectionEnvelope.model_validate(payload)


def _rehash_frame(payload: dict[str, object]) -> None:
    body = {key: value for key, value in payload.items() if key not in {"frame_ref", "frame_hash"}}
    frame_hash = _domain_hash("hapax.context-frame.v1", body)
    payload["frame_hash"] = frame_hash
    payload["frame_ref"] = f"context-frame@sha256:{frame_hash}"


def _rehash_projection(payload: dict[str, object]) -> None:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"projection_ref", "projection_hash"}
    }
    projection_hash = _domain_hash("hapax.projection-envelope.v1", body)
    payload["projection_hash"] = projection_hash
    payload["projection_ref"] = f"projection-envelope@sha256:{projection_hash}"


def _private_canary(payload: dict[str, object]) -> dict[str, object]:
    facts = payload["facts"]
    assert isinstance(facts, list)
    return next(item for item in facts if item["fact_id"] == "fact:private-canary")


def _frame_with_canary_horizon(stale_after: str) -> ContextFrame:
    payload = _frame_payload()
    provenance = _private_canary(payload)["provenance"]
    assert isinstance(provenance, dict)
    provenance["stale_after"] = stale_after
    _rehash_frame(payload)
    return ContextFrame.model_validate(payload)


def _project_operator(
    frame: ContextFrame, *, generated_at: str | None = None
) -> ProjectionEnvelope:
    template = _operator_projection()
    assert template.orientation is not None
    return project_context_frame(
        frame,
        audience=template.audience,
        purpose=template.purpose,
        depth=template.depth,
        device_class=template.device_class,
        register=template.register_mode,
        decoder_ref=template.decoder_ref,
        focus_ref=template.focus_ref,
        producer_ref=template.producer_ref,
        generated_at=generated_at or template.generated_at,
        orientation_ref=template.orientation.facet_ref,
    )


def _frame_with_past_retention_canary() -> ContextFrame:
    payload = _frame_payload()
    temporal_coordinates = payload["temporal_coordinates"]
    resolution_coordinates = payload["resolution_coordinates"]
    air_bindings = payload["air_bindings"]
    assert isinstance(temporal_coordinates, list)
    assert isinstance(resolution_coordinates, list)
    assert isinstance(air_bindings, list)

    source_temporal = temporal_coordinates[0]
    temporal_body = {
        key: value
        for key, value in source_temporal.items()
        if key not in {"temporal_ref", "temporal_hash"}
    }
    temporal_body.update(
        event_time_start="2026-07-09T10:00:00Z",
        event_time_end="2026-07-09T11:00:00Z",
        processing_time="2026-07-10T16:00:00Z",
        valid_from="2026-07-09T10:00:00Z",
        valid_until="2026-07-09T11:00:00Z",
        window_ref="window:retained-fact",
        scale_ref="scale:retained-fact",
        tense="retention",
        watermark="2026-07-09T11:00:00Z",
        parent_span_refs=[],
        correction_refs=[],
        forecast_horizon_ref=None,
    )
    temporal_hash = _domain_hash("hapax.temporal-coordinate.v1", temporal_body)
    retained_temporal = {
        **temporal_body,
        "temporal_ref": f"temporal-coordinate@sha256:{temporal_hash}",
        "temporal_hash": temporal_hash,
    }
    temporal_coordinates.append(retained_temporal)
    temporal_coordinates.sort(key=lambda item: item["temporal_ref"])

    source_resolution = resolution_coordinates[0]
    resolution_body = {
        key: value
        for key, value in source_resolution.items()
        if key not in {"resolution_ref", "resolution_hash"}
    }
    resolution_body.update(
        temporal_ref=retained_temporal["temporal_ref"],
        semantic_resolution_ref="semantic-resolution:retained-fact",
    )
    resolution_hash = _domain_hash("hapax.resolution-coordinate.v1", resolution_body)
    retained_resolution = {
        **resolution_body,
        "resolution_ref": f"resolution-coordinate@sha256:{resolution_hash}",
        "resolution_hash": resolution_hash,
    }
    resolution_coordinates.append(retained_resolution)
    resolution_coordinates.sort(key=lambda item: item["resolution_ref"])

    canary = _private_canary(payload)
    canary["temporal_ref"] = retained_temporal["temporal_ref"]
    canary["resolution_ref"] = retained_resolution["resolution_ref"]
    for object_kind, source_ref, retained_ref in (
        ("temporal", source_temporal["temporal_ref"], retained_temporal["temporal_ref"]),
        ("resolution", source_resolution["resolution_ref"], retained_resolution["resolution_ref"]),
    ):
        source_binding = next(
            item
            for item in air_bindings
            if item["object_kind"] == object_kind and item["object_ref"] == source_ref
        )
        air_bindings.append({**source_binding, "object_ref": retained_ref})
    air_bindings.sort(key=lambda item: (item["object_kind"], item["object_ref"]))
    _rehash_frame(payload)
    return ContextFrame.model_validate(payload)


def test_frozen_projections_and_compatibility_rebuild_exactly() -> None:
    frame = ContextFrame.model_validate_json((FIXTURES / "gate0-frame.json").read_bytes())
    raw_projections = json.loads((FIXTURES / "gate0-projections.json").read_text())
    projections = {
        name: ProjectionEnvelope.model_validate(value) for name, value in raw_projections.items()
    }
    for projection in projections.values():
        assert verify_projection(frame, projection) == projection
    compatibility = ContextBundleCompatibilityProjection.model_validate_json(
        (FIXTURES / "gate0-compatibility.json").read_bytes()
    )
    assert (
        verify_context_bundle_v1(
            frame,
            compatibility,
            operator_private=projections["operator"],
            yard_context=projections["yard"],
            hapax_substrate=projections["hapax"],
        )
        == compatibility
    )
    rebuilt = project_context_bundle_v1(
        frame,
        operator_private=projections["operator"],
        yard_context=projections["yard"],
        hapax_substrate=projections["hapax"],
    )
    assert (
        canonical_json_bytes(rebuilt.model_dump(mode="json", by_alias=True)) + b"\n"
        == (FIXTURES / "gate0-compatibility.json").read_bytes()
    )


def test_current_purpose_projections_cover_operation_and_lifecycle_possibility() -> None:
    frame = ContextFrame.model_validate_json((FIXTURES / "gate0-frame.json").read_bytes())
    raw = json.loads((FIXTURES / "gate0-purpose-projections.json").read_text())
    assert set(raw) == {"lifecycle_possibility", "operation"}
    projections = {
        name: ProjectionEnvelope.model_validate(payload) for name, payload in raw.items()
    }
    operation = projections["operation"]
    possibility = projections["lifecycle_possibility"]
    assert operation.purpose == "operation"
    assert operation.orientation is None
    assert operation.lifecycle_possibility is None
    assert possibility.purpose == "lifecycle_possibility"
    assert possibility.device_class == "accessible_linear"
    assert possibility.orientation is None
    assert possibility.lifecycle_possibility is not None
    assert set(possibility.lifecycle_possibility.lawful_next) <= set(possibility.legal_next)
    assert (
        tuple(event.event_ref for event in possibility.events)
        == possibility.lineage_refs[len(possibility.position.receipt_lineage) :]
    )
    for projection in projections.values():
        assert verify_projection(frame, projection) == projection


@pytest.mark.parametrize(
    ("value_state", "freshness_state"),
    (("partial", "fresh"), ("uncertain", "aging")),
)
def test_usable_nonpresent_facts_require_unexpired_provenance(
    value_state: str, freshness_state: str
) -> None:
    payload = _frame_payload()
    canary = _private_canary(payload)
    canary["state"] = {
        "value_state": value_state,
        "reason_codes": [f"fixture_{value_state}"],
    }
    canary["freshness_state"] = freshness_state
    provenance = canary["provenance"]
    assert isinstance(provenance, dict)
    provenance["stale_after"] = payload["checked_at"]
    _rehash_frame(payload)

    with pytest.raises(ValidationError, match="fresh and aging facts require unexpired provenance"):
        ContextFrame.model_validate(payload)


@pytest.mark.parametrize(
    ("value_state", "freshness_state"),
    (("partial", "fresh"), ("uncertain", "aging")),
)
def test_projected_usable_nonpresent_facts_require_unexpired_provenance(
    value_state: str, freshness_state: str
) -> None:
    payload = _operator_projection().model_dump(mode="json", by_alias=True)
    canary = _private_canary(payload)
    canary["state"] = {
        "value_state": value_state,
        "reason_codes": [f"fixture_{value_state}"],
    }
    canary["freshness_state"] = freshness_state
    provenance = canary["provenance"]
    assert isinstance(provenance, dict)
    provenance["stale_after"] = payload["generated_at"]
    _rehash_projection(payload)

    with pytest.raises(
        ValidationError, match="projected fresh and aging facts require unexpired provenance"
    ):
        ProjectionEnvelope.model_validate(payload)


def test_projection_emits_and_validates_weakest_visible_usable_fact_horizon() -> None:
    frame = _frame_with_canary_horizon("2026-07-10T17:00:00Z")
    projection = _project_operator(frame)

    assert projection.stale_after == "2026-07-10T17:00:00Z"

    forged = projection.model_dump(mode="json", by_alias=True)
    forged["stale_after"] = frame.stale_after
    _rehash_projection(forged)
    with pytest.raises(
        ValidationError, match="projection expiry exceeds visible usable fact provenance"
    ):
        ProjectionEnvelope.model_validate(forged)


def test_projection_generation_at_usable_fact_horizon_refuses() -> None:
    horizon = "2026-07-10T17:00:00Z"
    frame = _frame_with_canary_horizon(horizon)

    with pytest.raises(CanonError) as exc_info:
        _project_operator(frame, generated_at=horizon)

    assert exc_info.value.reason_code == "projection_usable_fact_horizon_expired"


def test_retention_valid_time_does_not_shorten_epistemic_freshness() -> None:
    frame = _frame_with_past_retention_canary()
    projection = _project_operator(frame)
    canary = next(item for item in projection.facts if item.fact_id == "fact:private-canary")
    temporal = next(
        item for item in projection.temporal_coordinates if item.temporal_ref == canary.temporal_ref
    )

    assert temporal.tense == "retention"
    assert temporal.valid_until < frame.checked_at
    assert frame.checked_at < canary.provenance.stale_after
    assert projection.stale_after == canary.provenance.stale_after == frame.stale_after
