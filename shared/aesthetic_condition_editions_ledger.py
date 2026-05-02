"""Aesthetic condition editions ledger.

Typed ledger for condition-bound stills, loops, visual packs, zines /
logbooks, GEM murals, CBIP signal editions, and installation /
screening packages — Hapax's aesthetic weirdness rendered as
rights-safe, monetizable artifacts.

The ledger is fail-closed: editions cannot be created without
provenance and privacy evidence, and uncleared rights / unanonymized
private / third-party rights-risky / album-cover merch are rejected
at construction.

cc-task: ``aesthetic-condition-editions-ledger``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EditionKind(StrEnum):
    """Distinct edition forms per acceptance §2."""

    STILL = "still"
    LOOP = "loop"
    VISUAL_PACK = "visual_pack"
    ZINE_LOGBOOK = "zine_logbook"
    INSTALLATION_SCREENING_PACKAGE = "installation_screening_package"
    GEM_MURAL = "gem_mural"
    CBIP_SIGNAL_EDITION = "cbip_signal_edition"


class RightsClass(StrEnum):
    OPERATOR_OWNED = "operator_owned"
    PUBLIC_DOMAIN = "public_domain"
    LICENSED = "licensed"
    THIRD_PARTY_RIGHTS_RISKY = "third_party_rights_risky"
    ALBUM_COVER_NO_EXPLICIT_RIGHTS = "album_cover_no_explicit_rights"
    UNCLEARED = "uncleared"


class PrivacyClass(StrEnum):
    FULLY_PUBLIC = "fully_public"
    OPERATOR_ONLY = "operator_only"
    ANONYMIZED = "anonymized"
    UNANONYMIZED_PRIVATE = "unanonymized_private"
    RAW_PRIVATE_FRAME = "raw_private_frame"


class SourceSubstrate(StrEnum):
    """Where the visual material came from."""

    LIVESTREAM_ARCHIVE = "livestream_archive"
    SPECTACLE_LANE = "spectacle_lane"
    HAPAX_IMAGINATION = "hapax_imagination"
    DMN_SEEKSPACE = "dmn_seekspace"
    SHADER_GRAPH = "shader_graph"


class SurfaceLane(StrEnum):
    """Surface / lane the edition was captured from."""

    DESK = "desk"
    OVERHEAD = "overhead"
    ROOM = "room"
    REVERIE = "reverie"
    DIRECTOR_VOCAB = "director_vocab"
    SPECTACLE = "spectacle"


class EditionBlocker(StrEnum):
    """Reasons an edition is rejected at construction (fail-closed)."""

    UNCLEARED_RIGHTS = "uncleared_rights"
    THIRD_PARTY_RIGHTS_RISKY = "third_party_rights_risky"
    ALBUM_COVER_NO_EXPLICIT_RIGHTS = "album_cover_no_explicit_rights"
    RAW_PRIVATE_FRAME = "raw_private_frame"
    UNANONYMIZED_PRIVATE = "unanonymized_private"
    MISSING_PROVENANCE_TOKEN = "missing_provenance_token"
    MISSING_PUBLIC_EVENT_LINK = "missing_public_event_link"
    MISSING_FRAME_REF = "missing_frame_ref"
    MISSING_SOURCE_SUBSTRATES = "missing_source_substrates"


class EditionCannotBeCreatedError(ValueError):
    """Raised when an edition violates a provenance / privacy / rights gate."""


class _LedgerModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EditionMetadata(_LedgerModel):
    """One edition row in the ledger.

    All fields named in acceptance §1 are required: condition id,
    timestamp, broadcast id, programme id, surface/lane, frame ref,
    rights class, privacy class, provenance token, source substrates,
    public-event link.
    """

    edition_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    kind: EditionKind
    condition_id: str = Field(min_length=1)
    timestamp: datetime
    broadcast_id: str = Field(min_length=1)
    programme_id: str = Field(min_length=1)
    surface_lane: SurfaceLane
    frame_ref: str = Field(min_length=1)
    rights_class: RightsClass
    privacy_class: PrivacyClass
    provenance_token: str = Field(pattern=r"^[a-f0-9]{32,}$")
    source_substrates: tuple[SourceSubstrate, ...] = Field(min_length=1)
    public_event_link: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_creation_gate(self) -> Self:
        blockers = _evaluate_creation_blockers(self)
        if blockers:
            raise EditionCannotBeCreatedError(
                f"edition {self.edition_id!r} blocked: {', '.join(b.value for b in blockers)}"
            )
        return self


def _evaluate_creation_blockers(metadata: EditionMetadata) -> tuple[EditionBlocker, ...]:
    """Compute creation blockers — pure, no I/O, used inside the validator."""
    blockers: list[EditionBlocker] = []
    if metadata.rights_class is RightsClass.UNCLEARED:
        blockers.append(EditionBlocker.UNCLEARED_RIGHTS)
    if metadata.rights_class is RightsClass.THIRD_PARTY_RIGHTS_RISKY:
        blockers.append(EditionBlocker.THIRD_PARTY_RIGHTS_RISKY)
    if metadata.rights_class is RightsClass.ALBUM_COVER_NO_EXPLICIT_RIGHTS:
        blockers.append(EditionBlocker.ALBUM_COVER_NO_EXPLICIT_RIGHTS)
    if metadata.privacy_class is PrivacyClass.RAW_PRIVATE_FRAME:
        blockers.append(EditionBlocker.RAW_PRIVATE_FRAME)
    if metadata.privacy_class is PrivacyClass.UNANONYMIZED_PRIVATE:
        blockers.append(EditionBlocker.UNANONYMIZED_PRIVATE)
    if not metadata.provenance_token:
        blockers.append(EditionBlocker.MISSING_PROVENANCE_TOKEN)
    if not metadata.public_event_link:
        blockers.append(EditionBlocker.MISSING_PUBLIC_EVENT_LINK)
    if not metadata.frame_ref:
        blockers.append(EditionBlocker.MISSING_FRAME_REF)
    if not metadata.source_substrates:
        blockers.append(EditionBlocker.MISSING_SOURCE_SUBSTRATES)
    return tuple(blockers)


class EditionEligibilityVerdict(_LedgerModel):
    """Result of dry-run eligibility evaluation (without raising)."""

    edition_id: str
    allowed: bool
    blockers: tuple[EditionBlocker, ...] = Field(default_factory=tuple)


class AestheticConditionEditionsLedger(_LedgerModel):
    """The ledger of all edition metadata."""

    schema_version: Literal[1] = 1
    generated_at: datetime
    editions: tuple[EditionMetadata, ...]

    def by_kind(self, kind: EditionKind) -> tuple[EditionMetadata, ...]:
        return tuple(e for e in self.editions if e.kind is kind)

    def by_rights(self, rights: RightsClass) -> tuple[EditionMetadata, ...]:
        return tuple(e for e in self.editions if e.rights_class is rights)

    def by_condition(self, condition_id: str) -> tuple[EditionMetadata, ...]:
        return tuple(e for e in self.editions if e.condition_id == condition_id)


class CapturePublicEventInput(_LedgerModel):
    """Pre-edition input from the public-event / spectacle-lane source.

    The auto-capture path consumes records of this shape and decides
    whether to mint an edition. Source surfaces hand these in; the
    ledger does not infer rights or privacy from raw archive frames.
    """

    public_event_id: str = Field(min_length=1)
    public_event_link: str = Field(min_length=1)
    broadcast_id: str = Field(min_length=1)
    programme_id: str = Field(min_length=1)
    condition_id: str = Field(min_length=1)
    surface_lane: SurfaceLane
    frame_ref: str = Field(min_length=1)
    rights_class: RightsClass
    privacy_class: PrivacyClass
    provenance_token: str | None = None
    source_substrates: tuple[SourceSubstrate, ...] = Field(default_factory=tuple)
    captured_at: datetime
    suggested_kind: EditionKind = EditionKind.STILL


def evaluate_edition_eligibility_from_input(
    candidate: CapturePublicEventInput,
) -> EditionEligibilityVerdict:
    """Dry-run gate: produce a verdict without raising.

    The actual edition construction is the source of truth — this is
    a pre-flight that helps callers avoid raising on every blocked
    candidate. Any new blocker added to ``EditionMetadata`` must show
    up here too.
    """
    edition_id = f"edition:{candidate.condition_id}:{candidate.public_event_id}"
    blockers: list[EditionBlocker] = []
    if candidate.rights_class is RightsClass.UNCLEARED:
        blockers.append(EditionBlocker.UNCLEARED_RIGHTS)
    if candidate.rights_class is RightsClass.THIRD_PARTY_RIGHTS_RISKY:
        blockers.append(EditionBlocker.THIRD_PARTY_RIGHTS_RISKY)
    if candidate.rights_class is RightsClass.ALBUM_COVER_NO_EXPLICIT_RIGHTS:
        blockers.append(EditionBlocker.ALBUM_COVER_NO_EXPLICIT_RIGHTS)
    if candidate.privacy_class is PrivacyClass.RAW_PRIVATE_FRAME:
        blockers.append(EditionBlocker.RAW_PRIVATE_FRAME)
    if candidate.privacy_class is PrivacyClass.UNANONYMIZED_PRIVATE:
        blockers.append(EditionBlocker.UNANONYMIZED_PRIVATE)
    if not candidate.provenance_token:
        blockers.append(EditionBlocker.MISSING_PROVENANCE_TOKEN)
    if not candidate.source_substrates:
        blockers.append(EditionBlocker.MISSING_SOURCE_SUBSTRATES)
    return EditionEligibilityVerdict(
        edition_id=edition_id,
        allowed=not blockers,
        blockers=tuple(blockers),
    )


def auto_capture_edition_from_input(
    candidate: CapturePublicEventInput,
) -> EditionMetadata:
    """Mint an edition from a public-event capture input.

    Raises ``EditionCannotBeCreatedError`` (via the model validator) if
    rights, privacy, provenance, or substrate evidence is missing.
    """
    if candidate.provenance_token is None:
        raise EditionCannotBeCreatedError("auto_capture: candidate is missing provenance_token")
    edition_id = f"edition-{candidate.condition_id}-{candidate.public_event_id}".lower()
    edition_id = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in edition_id)
    return EditionMetadata(
        edition_id=edition_id,
        kind=candidate.suggested_kind,
        condition_id=candidate.condition_id,
        timestamp=candidate.captured_at,
        broadcast_id=candidate.broadcast_id,
        programme_id=candidate.programme_id,
        surface_lane=candidate.surface_lane,
        frame_ref=candidate.frame_ref,
        rights_class=candidate.rights_class,
        privacy_class=candidate.privacy_class,
        provenance_token=candidate.provenance_token,
        source_substrates=candidate.source_substrates,
        public_event_link=candidate.public_event_link,
    )


__all__ = [
    "AestheticConditionEditionsLedger",
    "CapturePublicEventInput",
    "EditionBlocker",
    "EditionCannotBeCreatedError",
    "EditionEligibilityVerdict",
    "EditionKind",
    "EditionMetadata",
    "PrivacyClass",
    "RightsClass",
    "SourceSubstrate",
    "SurfaceLane",
    "auto_capture_edition_from_input",
    "evaluate_edition_eligibility_from_input",
]
