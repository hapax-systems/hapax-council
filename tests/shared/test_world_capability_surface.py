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
    assert set(world_capabilities_by_id()) >= {
        "audio.broadcast_voice",
        "camera.studio_compositor_frame",
        "camera.studio_rgb_fleet",
        "camera.studio_compositor_public_output",
        "archive.replay_sidecar",
        "archive.hls_sidecar",
        "archive.vod_replay_public_url",
        "public.research_vehicle_apertures",
        "public.youtube_live_aperture",
        "public.archive_replay_aperture",
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
    } >= {"public.research_vehicle_apertures", "public.youtube_live_aperture"}
    assert "seed_record_no_live_witness" in registry.blocked_reason_codes()

    with pytest.raises(KeyError):
        registry.require("unknown.surface")


def test_media_public_aperture_seed_records_keep_public_claims_gated() -> None:
    registry = load_world_capability_registry()

    camera = registry.require("camera.studio_rgb_fleet")
    compositor = registry.require("camera.studio_compositor_public_output")
    hls = registry.require("archive.hls_sidecar")
    replay = registry.require("archive.vod_replay_public_url")
    youtube = registry.require("public.youtube_live_aperture")
    public_replay = registry.require("public.archive_replay_aperture")

    assert camera.authority_ceiling.value == "internal_only"
    assert camera.public_claim_policy.claim_public_live is False
    assert "public:*" in camera.public_claim_policy.denied_surface_refs

    for record in (compositor, replay, youtube, public_replay):
        assert record.authority_ceiling.value == "public_gate_required"
        assert record.public_claim_policy.requires_egress_public_claim is True
        assert record.public_claim_policy.requires_privacy_public_safe is True
        assert record.public_claim_policy.requires_provenance is True
        assert record.public_claim_policy.claim_public_live is False
        assert record.public_claim_policy.claim_monetizable is False
        assert "seed_record_no_live_witness" in record.blocked_reasons

    assert hls.availability_state is AvailabilityState.ARCHIVE_ONLY
    assert hls.public_claim_policy.claim_archive is False
    assert "archive_hash_mtime_not_supplied" in hls.blocked_reasons


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


# ── audio.broadcast_health acceptance criteria ───────────────────────


def test_audio_broadcast_health_surface_registered() -> None:
    """Acceptance: public audio WCS row for broadcast health exists in
    the registry. Director / programme / public-event consumers can
    address it by surface_id."""
    registry = load_world_capability_registry()
    record = next(
        (r for r in registry.records if r.capability_id == "audio.broadcast_health"),
        None,
    )
    assert record is not None, (
        "audio.broadcast_health must be in WCS registry per "
        "broadcast-audio-health-world-surface acceptance criteria"
    )
    assert record.domain == "audio"
    assert record.realm == "world_state"
    assert record.direction == "observe"
    assert record.grounding_status == "public_claim_bearing"
    # Producer is the broadcast health daemon, not director or programme
    assert record.producer == "hapax-broadcast-audio-health"


def test_audio_broadcast_health_consumers_include_director_programme_public_event() -> None:
    """Acceptance: director, programme, public-event consumers can read
    the same surface id."""
    registry = load_world_capability_registry()
    record = next(r for r in registry.records if r.capability_id == "audio.broadcast_health")
    consumer_set = set(record.consumer_refs)
    assert "studio-compositor-director" in consumer_set, (
        "director must be a registered consumer of audio.broadcast_health"
    )
    assert "programme-scheduler" in consumer_set, (
        "programme scheduler must be a registered consumer of audio.broadcast_health"
    )
    assert "research-vehicle-public-event" in consumer_set, (
        "public-event adapter must be a registered consumer of audio.broadcast_health"
    )


def test_audio_broadcast_health_fails_closed_without_witness() -> None:
    """Acceptance: surface starts blocked; only fresh evidence + marker
    + no-leak witness should let it claim public audio safety."""
    registry = load_world_capability_registry()
    record = next(r for r in registry.records if r.capability_id == "audio.broadcast_health")
    assert record.availability_state == "blocked"
    assert record.public_claim_policy.claim_public_live is False
    assert record.public_claim_policy.requires_egress_public_claim is True
    assert record.public_claim_policy.requires_audio_safe is True
    # 5 distinct blocker categories preserved per acceptance criteria;
    # implementation lives in shared.audio_world_surface_health._aggregate_health_projection
    # and is exercised in tests/shared/test_audio_world_surface_health.py
    # (HEALTHY / STALE / UNSAFE / UNKNOWN). The notes field documents
    # the 5-category invariant for downstream maintainers.
    assert "unsafe" in record.notes.lower()
    assert "stale" in record.notes.lower()
    assert "unknown" in record.notes.lower()


def test_audio_broadcast_health_witness_requirements_cover_marker_and_safety() -> None:
    """Acceptance: commanded TTS without egress witness is not public
    audio success — witness requirements must include the marker."""
    registry = load_world_capability_registry()
    record = next(r for r in registry.records if r.capability_id == "audio.broadcast_health")
    witness_ids = {w.witness_id for w in record.witness_requirements}
    assert "broadcast_audio_safety_witness" in witness_ids
    assert "broadcast_egress_marker_witness" in witness_ids, (
        "egress marker witness is the single load-bearing fact that "
        "distinguishes 'commanded' from 'audible' — it must be required"
    )
    # The marker witness gates the no-quiet-off-air invariant
    marker = next(
        w for w in record.witness_requirements if w.witness_id == "broadcast_egress_marker_witness"
    )
    assert "no_quiet_off_air" in marker.required_for


# ── visual.surface_health acceptance criteria ────────────────────────


def test_visual_surface_health_registered() -> None:
    """Acceptance: public visual WCS row exists for camera/lane/frame
    health. Director / programme / public-event consumers can address
    it by surface_id."""
    registry = load_world_capability_registry()
    record = next(
        (r for r in registry.records if r.capability_id == "visual.surface_health"),
        None,
    )
    assert record is not None, (
        "visual.surface_health must be in WCS registry per "
        "world-surface-health-visual-adapter acceptance"
    )
    assert record.realm == "world_state"
    assert record.direction == "observe"
    assert record.grounding_status == "public_claim_bearing"
    assert record.producer == "studio-compositor"


def test_visual_surface_health_consumers_include_director_programme_public_event() -> None:
    """Acceptance: director, programme, public-event consumers can read
    the same surface id."""
    registry = load_world_capability_registry()
    record = next(r for r in registry.records if r.capability_id == "visual.surface_health")
    consumer_set = set(record.consumer_refs)
    assert "studio-compositor-director" in consumer_set
    assert "programme-scheduler" in consumer_set
    assert "research-vehicle-public-event" in consumer_set


def test_visual_surface_health_fails_closed_without_witness() -> None:
    """Acceptance: surface starts blocked; only fresh frame + non-blank
    + public aperture witnesses let it claim public visual safety."""
    registry = load_world_capability_registry()
    record = next(r for r in registry.records if r.capability_id == "visual.surface_health")
    assert record.availability_state == "blocked"
    assert record.public_claim_policy.claim_public_live is False
    assert record.public_claim_policy.requires_egress_public_claim is True
    # Notes documents the 4-category blocker invariant
    notes_lower = record.notes.lower()
    assert "rendered" in notes_lower
    assert "observed" in notes_lower
    assert "archived" in notes_lower


def test_visual_surface_health_witness_requirements_separate_render_from_egress() -> None:
    """Acceptance: rendered, observed, archived, public-live are
    SEPARATE evidence classes — commanded render without egress witness
    is NOT public-visual success."""
    registry = load_world_capability_registry()
    record = next(r for r in registry.records if r.capability_id == "visual.surface_health")
    witness_ids = {w.witness_id for w in record.witness_requirements}
    assert "frame_freshness_witness" in witness_ids, (
        "per-lane frame freshness must be a distinct witness"
    )
    assert "compositor_renderability_witness" in witness_ids, (
        "non-blank compositor output must be a distinct witness (separate from per-lane freshness)"
    )
    assert "public_aperture_witness" in witness_ids, (
        "public aperture / egress must be a distinct witness (separate from local renderability)"
    )
    # The aperture witness gates the public-visual claim specifically
    aperture = next(
        w for w in record.witness_requirements if w.witness_id == "public_aperture_witness"
    )
    assert "public_visual_safe" in aperture.required_for
