"""Tests for the World Capability Surface seed registry loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.world_capability_surface import (
    REQUIRED_EVIDENCE_FIELDS,
    REQUIRED_SURFACE_DOMAINS,
    AvailabilityState,
    EvidenceClass,
    GroundingStatus,
    WCSRegistryError,
    WorldCapabilityRegistry,
    load_world_capability_registry,
    world_capabilities_by_id,
)


def test_seed_registry_loads_required_surface_domains() -> None:
    registry = load_world_capability_registry()

    assert {record.domain for record in registry.records} >= REQUIRED_SURFACE_DOMAINS
    assert set(world_capabilities_by_id()) == {
        "audio.broadcast_voice",
        "camera.studio_compositor_frame",
        "archive.replay_sidecar",
        "public.research_vehicle_apertures",
        "file.obsidian_vault",
        "browser.mcp_tool_read",
        "music.midi_control_surface",
        "mobile.watch_biometrics",
    }


def test_seed_registry_fails_closed_by_default() -> None:
    registry = load_world_capability_registry()

    for record in registry.records:
        assert record.availability_state is not AvailabilityState.PUBLIC_LIVE
        assert record.blocked_reasons
        assert record.public_claim_policy.claim_public_live is False
        assert record.public_claim_policy.claim_monetizable is False
        assert registry.public_claim_allowed(record.capability_id, readiness={}) is False
        assert registry.public_claim_allowed("missing.capability", readiness={}) is False


def test_public_claim_bearing_records_require_non_inferred_witnesses() -> None:
    registry = load_world_capability_registry()

    claim_bearing = [
        record
        for record in registry.records
        if record.grounding_status is GroundingStatus.PUBLIC_CLAIM_BEARING
    ]
    assert claim_bearing

    for record in claim_bearing:
        assert record.witness_requirements
        assert record.public_claim_policy.requires_grounding_gate is True
        for witness in record.witness_requirements:
            assert EvidenceClass.INFERRED_CONTEXT not in witness.evidence_classes


def test_every_record_carries_required_evidence_envelope_fields() -> None:
    registry = load_world_capability_registry()

    for record in registry.records:
        fields = set(record.evidence_envelope_requirements.required_fields)
        assert fields >= REQUIRED_EVIDENCE_FIELDS
        assert record.evidence_envelope_requirements.inferred_context_satisfies_witness is False


def test_read_access_supports_downstream_queries() -> None:
    registry = load_world_capability_registry()

    audio = registry.require("audio.broadcast_voice")
    assert audio.domain == "audio"
    assert audio.fallback.reason_code == "broadcast_witness_missing"

    assert registry.records_for_domain("browser_mcp")[0].capability_id == "browser.mcp_tool_read"
    assert {
        record.capability_id
        for record in registry.records_for_surface_ref("public:youtube_metadata")
    } == {"public.research_vehicle_apertures"}
    assert "seed_record_no_live_witness" in registry.blocked_reason_codes()

    with pytest.raises(KeyError):
        registry.require("unknown.surface")


def test_malformed_registry_rows_fail_closed(tmp_path: Path) -> None:
    registry = load_world_capability_registry()
    payload = registry.model_dump(mode="json", by_alias=True)
    payload["records"][0]["public_claim_policy"]["claim_public_live"] = True

    path = tmp_path / "unsafe-wcs-registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(WCSRegistryError, match="public-live readiness"):
        load_world_capability_registry(path)


def test_duplicate_or_missing_required_domain_rejected() -> None:
    registry = load_world_capability_registry()
    payload = registry.model_dump(mode="json", by_alias=True)
    payload["records"] = [
        record for record in payload["records"] if record["domain"] != "mobile_watch"
    ]

    with pytest.raises(ValueError, match="mobile_watch"):
        WorldCapabilityRegistry.model_validate(payload)

    duplicate_payload = registry.model_dump(mode="json", by_alias=True)
    duplicate_payload["records"].append(duplicate_payload["records"][0])
    with pytest.raises(ValueError, match="duplicate WCS capability ids"):
        WorldCapabilityRegistry.model_validate(duplicate_payload)
