"""Aperture registry unit and contract tests.

Validates:
1. Registry loads and covers all 10 required aperture IDs
2. Required aperture kinds are all present
3. Private/public/archive/composed-frame separation
4. Unregistered aperture fail-closed behaviour
5. Destination channel mapping consistency
6. Public apertures enforce egress and authority gates
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from shared.aperture_registry import (
    APERTURE_REGISTRY_FIXTURES,
    REQUIRED_APERTURE_IDS,
    REQUIRED_APERTURE_KINDS,
    ApertureRegistryFixtureSet,
    load_aperture_registry,
)
from shared.self_presence import ExposureMode


@pytest.fixture(scope="module")
def registry() -> ApertureRegistryFixtureSet:
    return load_aperture_registry()


@pytest.fixture(scope="module")
def raw_payload() -> dict[str, Any]:
    return json.loads(APERTURE_REGISTRY_FIXTURES.read_text(encoding="utf-8"))


def test_registry_loads_and_covers_required_ids(registry: ApertureRegistryFixtureSet) -> None:
    """Every required aperture_id is present in the registry."""

    ids = {record.aperture_id for record in registry.records}
    missing = REQUIRED_APERTURE_IDS - ids
    assert not missing, f"Missing required aperture IDs: {sorted(missing)}"


def test_registry_covers_required_kinds(registry: ApertureRegistryFixtureSet) -> None:
    """Every required aperture kind is represented by at least one record."""

    kinds = {record.kind for record in registry.records}
    missing = REQUIRED_APERTURE_KINDS - kinds
    assert not missing, f"Missing required aperture kinds: {sorted(missing)}"


def test_no_duplicate_ids(registry: ApertureRegistryFixtureSet) -> None:
    """Each aperture_id appears exactly once."""

    ids = [record.aperture_id for record in registry.records]
    assert len(ids) == len(set(ids)), "Duplicate aperture IDs found"


def test_private_apertures_are_non_public(registry: ApertureRegistryFixtureSet) -> None:
    """Private apertures cannot allow public claims or broadcast."""

    private = registry.private_apertures()
    assert len(private) >= 4, "Expected at least 4 private apertures"
    for record in private:
        assert record.public_claim_ceiling.value in {
            "no_claim",
            "private_only",
            "diagnostic_only",
        }, (
            f"{record.aperture_id} private but has public claim ceiling {record.public_claim_ceiling}"
        )
        assert record.destination_mapping.destination_channel == "private", (
            f"{record.aperture_id} private but maps to non-private destination"
        )


def test_public_apertures_require_gates(registry: ApertureRegistryFixtureSet) -> None:
    """Public apertures enforce programme authorization, egress witness, and authority ceiling."""

    public = registry.public_apertures()
    assert len(public) >= 4, "Expected at least 4 public apertures"
    for record in public:
        assert record.egress_policy.requires_egress_witness, (
            f"{record.aperture_id}: public aperture must require egress witness"
        )
        assert record.public_claim_ceiling.value in {
            "public_gate_required",
            "evidence_bound",
        }, f"{record.aperture_id} public but claim ceiling is {record.public_claim_ceiling}"


def test_composed_frame_distinct_from_raw_camera(registry: ApertureRegistryFixtureSet) -> None:
    """Composed livestream frame is a separate registration from raw studio camera."""

    composed = registry.require("aperture:composed-livestream-frame")
    raw = registry.require("aperture:raw-studio-camera")

    assert composed.kind != raw.kind
    assert composed.family != raw.family
    assert composed.exposure_mode != raw.exposure_mode
    assert composed.exposure_mode in {ExposureMode.PUBLIC_CANDIDATE, ExposureMode.PUBLIC_LIVE}
    assert raw.exposure_mode == ExposureMode.PRIVATE


def test_archive_window_is_archive_only(registry: ApertureRegistryFixtureSet) -> None:
    """Archive window has archive_only exposure mode."""

    archive = registry.require("aperture:archive-window")
    assert archive.exposure_mode == ExposureMode.ARCHIVE_ONLY


def test_wcs_surface_is_synthetic_only(registry: ApertureRegistryFixtureSet) -> None:
    """WCS health rows are synthetic_only — not factual public claims."""

    wcs = registry.require("aperture:wcs-surface")
    assert wcs.exposure_mode == ExposureMode.SYNTHETIC_ONLY
    assert wcs.public_claim_ceiling.value == "no_claim"


def test_destination_channel_mapping(registry: ApertureRegistryFixtureSet) -> None:
    """DestinationChannel mappings are complete: private and livestream."""

    livestream = registry.aperture_for_destination("livestream")
    private = registry.aperture_for_destination("private")
    assert len(livestream) >= 1, "No apertures map to livestream"
    assert len(private) >= 1, "No apertures map to private"

    # Broadcast voice maps to livestream
    broadcast = registry.require("aperture:public-broadcast-voice")
    assert broadcast.destination_mapping.destination_channel == "livestream"

    # Private assistant maps to private
    assistant = registry.require("aperture:private-assistant")
    assert assistant.destination_mapping.destination_channel == "private"


def test_unregistered_aperture_fail_closed(registry: ApertureRegistryFixtureSet) -> None:
    """Looking up an unregistered aperture raises KeyError."""

    with pytest.raises(KeyError, match="unregistered aperture"):
        registry.require("aperture:does-not-exist")


def test_fail_closed_policy_enforced(registry: ApertureRegistryFixtureSet) -> None:
    """The fail_closed_policy correctly pins the expected defaults."""

    assert registry.fail_closed_policy["unregistered_aperture_is_private"] is True
    assert registry.fail_closed_policy["unregistered_aperture_blocks_public"] is True
    assert registry.fail_closed_policy["missing_aperture_allows_broadcast"] is False


def test_private_sidechat_and_assistant_are_separate(
    registry: ApertureRegistryFixtureSet,
) -> None:
    """Sidechat and private assistant are distinct apertures."""

    sidechat = registry.require("aperture:private-sidechat")
    assistant = registry.require("aperture:private-assistant")

    assert sidechat.aperture_id != assistant.aperture_id
    assert sidechat.kind != assistant.kind
    assert sidechat.exposure_mode == ExposureMode.PRIVATE
    assert assistant.exposure_mode == ExposureMode.PRIVATE


def test_caption_and_public_event_are_public(registry: ApertureRegistryFixtureSet) -> None:
    """Caption surface and public event are public apertures with egress requirements."""

    caption = registry.require("aperture:caption-surface")
    public_event = registry.require("aperture:public-event")

    for record in [caption, public_event]:
        assert record.exposure_mode in {
            ExposureMode.PUBLIC_CANDIDATE,
            ExposureMode.PUBLIC_LIVE,
        }, f"{record.aperture_id} should be public"
        assert record.egress_policy.requires_programme_authorization
        assert record.egress_policy.requires_egress_witness


def test_broadcast_voice_requires_full_gates(registry: ApertureRegistryFixtureSet) -> None:
    """Public broadcast voice requires programme auth + audio safety + egress witness."""

    broadcast = registry.require("aperture:public-broadcast-voice")
    assert broadcast.egress_policy.requires_programme_authorization
    assert broadcast.egress_policy.requires_audio_safety
    assert broadcast.egress_policy.requires_egress_witness


def test_fixture_rejects_missing_required_id(raw_payload: dict[str, Any]) -> None:
    """Removing a required aperture_id causes validation failure."""

    mutated = copy.deepcopy(raw_payload)
    mutated["records"] = [
        r for r in mutated["records"] if r["aperture_id"] != "aperture:public-broadcast-voice"
    ]

    with pytest.raises(Exception, match="missing required aperture IDs"):
        ApertureRegistryFixtureSet.model_validate(mutated)


def test_fixture_rejects_duplicate_id(raw_payload: dict[str, Any]) -> None:
    """Duplicate aperture_id causes validation failure."""

    mutated = copy.deepcopy(raw_payload)
    mutated["records"].append(copy.deepcopy(mutated["records"][0]))

    with pytest.raises(Exception, match="duplicate aperture IDs"):
        ApertureRegistryFixtureSet.model_validate(mutated)


def test_fixture_sources_avoid_local_absolute_paths(raw_payload: dict[str, Any]) -> None:
    """Fixture sources should not contain absolute paths from local filesystem."""

    for source in raw_payload["generated_from"]:
        assert not source.startswith("/home/"), f"Source contains absolute path: {source}"
