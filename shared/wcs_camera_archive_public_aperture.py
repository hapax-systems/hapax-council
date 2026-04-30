"""Camera, archive, and public-aperture WCS fixture adapter.

This slice keeps camera/archive existence separate from public claimability.
Records can say that a camera is visible or an archive sidecar exists, but
public-safe, public-live, public-archive, and monetization claims require their
own egress, privacy, rights, audio, archive, and public-event evidence.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
WCS_CAMERA_ARCHIVE_PUBLIC_APERTURE_FIXTURES = (
    REPO_ROOT / "config" / "wcs-camera-archive-public-aperture-fixtures.json"
)

REQUIRED_VISIBILITY_STATES = frozenset(
    {
        "live_visible",
        "internal_visible",
        "archived",
        "public",
        "private",
        "missing",
        "stale",
        "blocked",
    }
)

REQUIRED_FAIL_CLOSED_POLICY = {
    "camera_existence_implies_public_safe": False,
    "archive_existence_implies_public_safe": False,
    "public_url_without_public_event_allows_claim": False,
    "stale_public_surface_allows_claim": False,
    "egress_unknown_allows_public_claim": False,
    "privacy_rights_hold_allows_public_claim": False,
    "monetization_without_explicit_readiness": False,
}


class WCSMediaApertureError(ValueError):
    """Raised when media/public-aperture WCS fixtures fail closed."""


class SurfaceKind(StrEnum):
    CAMERA = "camera"
    COMPOSITOR_PUBLIC_OUTPUT = "compositor_public_output"
    ARCHIVE_REF = "archive_ref"
    VOD_HLS_SIDECAR = "vod_hls_sidecar"
    PUBLIC_APERTURE_URL = "public_aperture_url"


class VisibilityState(StrEnum):
    LIVE_VISIBLE = "live_visible"
    INTERNAL_VISIBLE = "internal_visible"
    ARCHIVED = "archived"
    PUBLIC = "public"
    PRIVATE = "private"
    MISSING = "missing"
    STALE = "stale"
    BLOCKED = "blocked"


class EvidenceState(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    MISSING = "missing"
    STALE = "stale"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class EvidenceRefs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    face_privacy_refs: tuple[str, ...] = Field(default_factory=tuple)
    consent_refs: tuple[str, ...] = Field(default_factory=tuple)
    audio_refs: tuple[str, ...] = Field(default_factory=tuple)
    egress_refs: tuple[str, ...] = Field(default_factory=tuple)
    archive_refs: tuple[str, ...] = Field(default_factory=tuple)
    public_event_refs: tuple[str, ...] = Field(default_factory=tuple)
    rights_refs: tuple[str, ...] = Field(default_factory=tuple)
    privacy_refs: tuple[str, ...] = Field(default_factory=tuple)


class ClaimPosture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    live_visible: bool
    internally_visible: bool
    archived: bool
    public: bool
    private: bool
    public_safe: bool
    public_live_claim_allowed: bool
    public_archive_claim_allowed: bool
    monetization_allowed: Literal[False] = False


class MediaApertureRecord(BaseModel):
    """One witnessed media/public-aperture row for programme WCS consumers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    record_id: str
    capability_id: str
    surface_id: str
    surface_kind: SurfaceKind
    visibility_state: VisibilityState
    observed_at: str
    freshness_ttl_s: int | None = Field(default=None, ge=0)
    observed_age_s: int | None = Field(default=None, ge=0)
    camera_refs: tuple[str, ...] = Field(default_factory=tuple)
    archive_refs: tuple[str, ...] = Field(default_factory=tuple)
    public_urls: tuple[str, ...] = Field(default_factory=tuple)
    witness_probe_refs: tuple[str, ...] = Field(default_factory=tuple)
    temporal_span_refs: tuple[str, ...] = Field(default_factory=tuple)
    archive_replay_decision_refs: tuple[str, ...] = Field(default_factory=tuple)
    research_vehicle_public_event_refs: tuple[str, ...] = Field(default_factory=tuple)
    evidence: EvidenceRefs
    face_privacy_state: EvidenceState
    consent_state: EvidenceState
    audio_state: EvidenceState
    egress_state: EvidenceState
    archive_state: EvidenceState
    public_event_state: EvidenceState
    rights_state: EvidenceState
    privacy_state: EvidenceState
    claim_posture: ClaimPosture
    blocking_reasons: tuple[str, ...] = Field(default_factory=tuple)
    notes: str = ""

    @model_validator(mode="after")
    def _validate_media_aperture_contract(self) -> Self:
        expected_flags = {
            VisibilityState.LIVE_VISIBLE: ("live_visible",),
            VisibilityState.INTERNAL_VISIBLE: ("internally_visible", "private"),
            VisibilityState.ARCHIVED: ("archived",),
            VisibilityState.PUBLIC: ("public",),
            VisibilityState.PRIVATE: ("private",),
            VisibilityState.MISSING: (),
            VisibilityState.STALE: (),
            VisibilityState.BLOCKED: (),
        }[self.visibility_state]
        for flag in (
            "live_visible",
            "internally_visible",
            "archived",
            "public",
            "private",
        ):
            if getattr(self.claim_posture, flag) != (flag in expected_flags):
                raise ValueError(f"{self.record_id} claim_posture.{flag} mismatches state")

        if (
            self.visibility_state
            in {
                VisibilityState.MISSING,
                VisibilityState.STALE,
                VisibilityState.BLOCKED,
            }
            and not self.blocking_reasons
        ):
            raise ValueError(f"{self.record_id} terminal/non-fresh states require blockers")

        if self.visibility_state is VisibilityState.MISSING:
            self._require_missing_reason()
        if self.visibility_state is VisibilityState.STALE and "public_surface_stale" not in (
            self.blocking_reasons
        ):
            raise ValueError(f"{self.record_id} stale public surfaces require public_surface_stale")
        if self.egress_state is EvidenceState.UNKNOWN and "egress_unknown" not in (
            self.blocking_reasons
        ):
            raise ValueError(f"{self.record_id} unknown egress must be an explicit blocker")
        if (
            self.rights_state is EvidenceState.FAIL or self.privacy_state is EvidenceState.FAIL
        ) and "privacy_rights_hold" not in self.blocking_reasons:
            raise ValueError(f"{self.record_id} privacy/rights failure needs hold blocker")

        self._validate_public_safe_claim()
        self._validate_public_live_claim()
        self._validate_public_archive_claim()
        return self

    def public_claim_blockers(self) -> tuple[str, ...]:
        """Return fail-closed reasons a public claim cannot be made."""

        blockers = list(self.blocking_reasons)
        if self.egress_state is not EvidenceState.PASS:
            blockers.append(_state_blocker("egress", self.egress_state))
        if self.public_event_state is not EvidenceState.PASS:
            blockers.append(_state_blocker("public_event", self.public_event_state))
        if self.rights_state is not EvidenceState.PASS:
            blockers.append(_state_blocker("rights", self.rights_state))
        if self.privacy_state is not EvidenceState.PASS:
            blockers.append(_state_blocker("privacy", self.privacy_state))
        if self.face_privacy_state is not EvidenceState.PASS:
            blockers.append(_state_blocker("face_privacy", self.face_privacy_state))
        if self.consent_state is not EvidenceState.PASS:
            blockers.append(_state_blocker("consent", self.consent_state))
        if self.audio_state not in {EvidenceState.PASS, EvidenceState.NOT_APPLICABLE}:
            blockers.append(_state_blocker("audio", self.audio_state))
        if not self.evidence.egress_refs:
            blockers.append("egress_evidence_missing")
        if not self.evidence.public_event_refs:
            blockers.append("public_event_evidence_missing")
        if not self.evidence.rights_refs:
            blockers.append("rights_evidence_missing")
        if not self.evidence.privacy_refs:
            blockers.append("privacy_evidence_missing")
        return _dedupe(blockers)

    def _require_missing_reason(self) -> None:
        if self.surface_kind in {SurfaceKind.CAMERA, SurfaceKind.COMPOSITOR_PUBLIC_OUTPUT}:
            required = "camera_missing"
        elif self.surface_kind in {SurfaceKind.ARCHIVE_REF, SurfaceKind.VOD_HLS_SIDECAR}:
            required = "archive_missing"
        else:
            required = "public_surface_missing"
        if required not in self.blocking_reasons:
            raise ValueError(f"{self.record_id} missing state requires {required}")

    def _validate_public_safe_claim(self) -> None:
        if not self.claim_posture.public_safe:
            return
        blockers = self.public_claim_blockers()
        if blockers:
            raise ValueError(
                f"{self.record_id} public_safe cannot pass with blockers: " + ", ".join(blockers)
            )

    def _validate_public_live_claim(self) -> None:
        if not self.claim_posture.public_live_claim_allowed:
            return
        if not self.claim_posture.public_safe:
            raise ValueError(f"{self.record_id} public-live requires public_safe")
        if self.visibility_state not in {VisibilityState.LIVE_VISIBLE, VisibilityState.PUBLIC}:
            raise ValueError(f"{self.record_id} public-live requires live/public visibility")
        if not self.public_urls and self.surface_kind is SurfaceKind.PUBLIC_APERTURE_URL:
            raise ValueError(f"{self.record_id} public aperture live claim requires URL evidence")

    def _validate_public_archive_claim(self) -> None:
        if not self.claim_posture.public_archive_claim_allowed:
            return
        if not self.claim_posture.public_safe:
            raise ValueError(f"{self.record_id} public archive requires public_safe")
        if self.visibility_state is not VisibilityState.PUBLIC:
            raise ValueError(f"{self.record_id} public archive requires public visibility")
        if self.archive_state is not EvidenceState.PASS:
            raise ValueError(f"{self.record_id} public archive requires archive pass")
        if not self.evidence.archive_refs or not self.archive_refs:
            raise ValueError(f"{self.record_id} public archive requires archive refs")
        if not self.public_urls:
            raise ValueError(f"{self.record_id} public archive requires public URL refs")
        if not self.archive_replay_decision_refs:
            raise ValueError(f"{self.record_id} public archive requires replay decision refs")
        if not self.temporal_span_refs:
            raise ValueError(f"{self.record_id} public archive requires temporal span refs")


class MediaApertureFixtureSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    fixture_set_id: str
    generated_from: tuple[str, ...] = Field(min_length=1)
    declared_at: str
    visibility_states: tuple[VisibilityState, ...] = Field(min_length=1)
    records: tuple[MediaApertureRecord, ...] = Field(min_length=1)
    fail_closed_policy: dict[str, bool]

    @model_validator(mode="after")
    def _validate_fixture_coverage(self) -> Self:
        states = {state.value for state in self.visibility_states}
        missing_states = REQUIRED_VISIBILITY_STATES - states
        if missing_states:
            raise ValueError(
                "missing media aperture visibility states: " + ", ".join(sorted(missing_states))
            )
        record_states = {record.visibility_state.value for record in self.records}
        missing_record_states = REQUIRED_VISIBILITY_STATES - record_states
        if missing_record_states:
            raise ValueError(
                "media aperture records do not cover states: "
                + ", ".join(sorted(missing_record_states))
            )
        if self.fail_closed_policy != REQUIRED_FAIL_CLOSED_POLICY:
            raise ValueError("fail_closed_policy must pin media/public inference gates false")
        ids = [record.record_id for record in self.records]
        duplicates = sorted({record_id for record_id in ids if ids.count(record_id) > 1})
        if duplicates:
            raise ValueError("duplicate media aperture record ids: " + ", ".join(duplicates))
        return self

    def by_id(self) -> dict[str, MediaApertureRecord]:
        return {record.record_id: record for record in self.records}

    def require_record(self, record_id: str) -> MediaApertureRecord:
        record = self.by_id().get(record_id)
        if record is None:
            raise KeyError(f"unknown WCS media aperture record: {record_id}")
        return record

    def records_for_state(self, state: VisibilityState) -> list[MediaApertureRecord]:
        return [record for record in self.records if record.visibility_state is state]


def _state_blocker(prefix: str, state: EvidenceState) -> str:
    if state is EvidenceState.UNKNOWN:
        return f"{prefix}_unknown"
    return f"{prefix}_{state.value}"


def _dedupe(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise WCSMediaApertureError(f"{path} did not contain a JSON object")
    return payload


def load_media_aperture_fixtures(
    path: Path = WCS_CAMERA_ARCHIVE_PUBLIC_APERTURE_FIXTURES,
) -> MediaApertureFixtureSet:
    """Load media/public-aperture WCS fixtures, failing closed on drift."""

    try:
        return MediaApertureFixtureSet.model_validate(_load_json_object(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise WCSMediaApertureError(
            f"invalid WCS media aperture fixtures at {path}: {exc}"
        ) from exc


__all__ = [
    "REQUIRED_FAIL_CLOSED_POLICY",
    "REQUIRED_VISIBILITY_STATES",
    "WCS_CAMERA_ARCHIVE_PUBLIC_APERTURE_FIXTURES",
    "ClaimPosture",
    "EvidenceRefs",
    "EvidenceState",
    "MediaApertureFixtureSet",
    "MediaApertureRecord",
    "SurfaceKind",
    "VisibilityState",
    "WCSMediaApertureError",
    "load_media_aperture_fixtures",
]
