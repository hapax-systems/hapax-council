"""System-wide aperture registry for Hapax Unified.

This module provides a fixture-backed registry of all concrete apertures in the
system. Every claim, answer, action, render, and public event knows which
aperture it belongs to and what that aperture can witness or expose.

Build-through-contract rule: unregistered apertures default to
private/dry-run/blocked until classified.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from shared.self_presence import (
    ApertureKind,
    AuthorityCeiling,
    ExposureMode,
    PublicPrivateMode,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
APERTURE_REGISTRY_FIXTURES = REPO_ROOT / "config" / "aperture-registry-fixtures.json"

REQUIRED_APERTURE_IDS = frozenset(
    {
        "aperture:private-assistant",
        "aperture:public-broadcast-voice",
        "aperture:private-sidechat",
        "aperture:composed-livestream-frame",
        "aperture:raw-studio-camera",
        "aperture:archive-window",
        "aperture:caption-surface",
        "aperture:public-event",
        "aperture:wcs-surface",
        "aperture:private-notification",
    }
)

REQUIRED_DESTINATION_MAPPINGS = frozenset(
    {
        "livestream",
        "private",
    }
)

# These aperture kinds must always be present in any valid registry.
REQUIRED_APERTURE_KINDS = frozenset(
    {
        ApertureKind.PRIVATE_ASSISTANT,
        ApertureKind.PUBLIC_BROADCAST_VOICE,
        ApertureKind.COMPOSED_LIVESTREAM_FRAME,
        ApertureKind.RAW_STUDIO_CAMERA,
        ApertureKind.ARCHIVE_WINDOW,
        ApertureKind.SIDECHAT,
        ApertureKind.CAPTION_SURFACE,
        ApertureKind.PUBLIC_EVENT,
        ApertureKind.WCS_ROW,
    }
)


class ApertureRegistryError(ValueError):
    """Raised when aperture registry fixtures fail validation."""


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TemporalSpanPolicy(FrozenModel):
    """Temporal span policy for an aperture."""

    default_ttl_s: int = Field(ge=0)
    max_ttl_s: int = Field(ge=0)
    freshness_required: bool

    @model_validator(mode="after")
    def _max_gte_default(self) -> Self:
        if self.max_ttl_s < self.default_ttl_s:
            raise ValueError("max_ttl_s must be >= default_ttl_s")
        return self


class EgressPolicy(FrozenModel):
    """Egress policy for an aperture."""

    requires_programme_authorization: bool
    requires_audio_safety: bool
    requires_egress_witness: bool
    requires_public_event_ref: bool


class DestinationMapping(FrozenModel):
    """Maps an aperture to the existing DestinationChannel enum."""

    destination_channel: str = Field(pattern=r"^(livestream|private)$")
    voice_output_destination: str | None = None


class ApertureRegistryRecord(FrozenModel):
    """One concrete aperture registration in the system-wide registry.

    This extends the ontology Aperture type with operational policies:
    temporal span, egress, and destination mapping.
    """

    schema_version: Literal[1] = 1
    aperture_id: str = Field(pattern=r"^aperture:[a-z0-9_.:-]+$")
    kind: ApertureKind
    family: str = Field(min_length=1)
    perspective: str = Field(min_length=1)
    exposure_mode: ExposureMode
    public_private_mode: PublicPrivateMode
    privacy_ceiling: AuthorityCeiling
    rights_ceiling: AuthorityCeiling
    public_claim_ceiling: AuthorityCeiling
    witness_kinds: tuple[str, ...] = Field(default_factory=tuple)
    temporal_span_policy: TemporalSpanPolicy
    egress_policy: EgressPolicy
    destination_mapping: DestinationMapping
    surface_refs: tuple[str, ...] = Field(default_factory=tuple)
    evidence_classes: tuple[str, ...] = Field(default_factory=tuple)
    notes: str = ""

    @model_validator(mode="after")
    def _fail_closed_public(self) -> Self:
        if self.exposure_mode in {ExposureMode.PUBLIC_LIVE, ExposureMode.PUBLIC_CANDIDATE}:
            if self.public_claim_ceiling not in {
                AuthorityCeiling.PUBLIC_GATE_REQUIRED,
                AuthorityCeiling.EVIDENCE_BOUND,
            }:
                raise ValueError(
                    f"{self.aperture_id}: public apertures require public_gate_required "
                    f"or evidence_bound claim ceiling"
                )
            if not self.egress_policy.requires_egress_witness:
                raise ValueError(f"{self.aperture_id}: public apertures require egress witness")
        if self.exposure_mode is ExposureMode.PRIVATE:
            if self.destination_mapping.destination_channel != "private":
                raise ValueError(
                    f"{self.aperture_id}: private apertures must map to private destination"
                )
        return self


class ApertureRegistryFixtureSet(FrozenModel):
    """System-wide aperture registry fixture set."""

    schema_version: Literal[1] = 1
    fixture_set_id: str = Field(min_length=1)
    generated_from: tuple[str, ...] = Field(min_length=1)
    declared_at: str = Field(min_length=1)
    fail_closed_policy: dict[str, bool]
    records: tuple[ApertureRegistryRecord, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_registry_contract(self) -> Self:
        ids = {record.aperture_id for record in self.records}
        missing = REQUIRED_APERTURE_IDS - ids
        if missing:
            raise ValueError(f"missing required aperture IDs: {sorted(missing)}")

        duplicate_ids = sorted(
            aid for aid in ids if sum(1 for r in self.records if r.aperture_id == aid) > 1
        )
        if duplicate_ids:
            raise ValueError(f"duplicate aperture IDs: {duplicate_ids}")

        kinds = {record.kind for record in self.records}
        missing_kinds = REQUIRED_APERTURE_KINDS - kinds
        if missing_kinds:
            raise ValueError(f"missing required aperture kinds: {sorted(missing_kinds)}")

        dest_channels = {record.destination_mapping.destination_channel for record in self.records}
        missing_dests = REQUIRED_DESTINATION_MAPPINGS - dest_channels
        if missing_dests:
            raise ValueError(f"missing destination mappings: {sorted(missing_dests)}")

        required_policy = {
            "unregistered_aperture_is_private": True,
            "unregistered_aperture_blocks_public": True,
            "missing_aperture_allows_broadcast": False,
        }
        if self.fail_closed_policy != required_policy:
            raise ValueError("fail_closed_policy must enforce private-default for unregistered")

        return self

    def by_id(self) -> dict[str, ApertureRegistryRecord]:
        """Return a dict of aperture_id → record."""

        return {record.aperture_id: record for record in self.records}

    def require(self, aperture_id: str) -> ApertureRegistryRecord:
        """Return the record for aperture_id, or raise KeyError."""

        record = self.by_id().get(aperture_id)
        if record is None:
            raise KeyError(f"unregistered aperture: {aperture_id}")
        return record

    def records_for_kind(self, kind: ApertureKind) -> list[ApertureRegistryRecord]:
        """Return all records matching a given aperture kind."""

        return [record for record in self.records if record.kind is kind]

    def records_for_exposure(self, exposure: ExposureMode) -> list[ApertureRegistryRecord]:
        """Return all records matching a given exposure mode."""

        return [record for record in self.records if record.exposure_mode is exposure]

    def public_apertures(self) -> list[ApertureRegistryRecord]:
        """Return all apertures with public exposure."""

        return [
            record
            for record in self.records
            if record.exposure_mode in {ExposureMode.PUBLIC_LIVE, ExposureMode.PUBLIC_CANDIDATE}
        ]

    def private_apertures(self) -> list[ApertureRegistryRecord]:
        """Return all apertures with private exposure."""

        return [record for record in self.records if record.exposure_mode is ExposureMode.PRIVATE]

    def aperture_for_destination(self, destination_channel: str) -> list[ApertureRegistryRecord]:
        """Return apertures mapped to a given DestinationChannel value."""

        return [
            record
            for record in self.records
            if record.destination_mapping.destination_channel == destination_channel
        ]


def load_aperture_registry(
    path: Path = APERTURE_REGISTRY_FIXTURES,
) -> ApertureRegistryFixtureSet:
    """Load and validate the system-wide aperture registry."""

    try:
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return ApertureRegistryFixtureSet.model_validate(payload)
    except (OSError, ValidationError, json.JSONDecodeError) as exc:
        raise ApertureRegistryError(f"invalid aperture registry at {path}: {exc}") from exc


@cache
def aperture_registry() -> ApertureRegistryFixtureSet:
    """Cached aperture registry for tests and runtime consumers."""

    return load_aperture_registry()


__all__ = [
    "APERTURE_REGISTRY_FIXTURES",
    "REQUIRED_APERTURE_IDS",
    "REQUIRED_APERTURE_KINDS",
    "REQUIRED_DESTINATION_MAPPINGS",
    "ApertureRegistryError",
    "ApertureRegistryFixtureSet",
    "ApertureRegistryRecord",
    "DestinationMapping",
    "EgressPolicy",
    "TemporalSpanPolicy",
    "aperture_registry",
    "load_aperture_registry",
]
