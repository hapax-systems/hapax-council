"""Temporal band evidence envelope fixtures and claim-support gates.

This module is a contract surface for the temporal-grounding train. It turns
the current `/dev/shm/hapax-temporal/bands.json` prompt-oriented payload into a
fixture-backed evidence envelope vocabulary that downstream WCS, prompt, voice,
director, and public-output gates can consume without treating XML, mtimes, or
posterior scores as grounding authority.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPORAL_BAND_EVIDENCE_FIXTURES = (
    REPO_ROOT / "config" / "temporal-band-evidence-envelope-fixtures.json"
)

TEMPORAL_BANDS_PATH = "/dev/shm/hapax-temporal/bands.json"

REQUIRED_TEMPORAL_BANDS = frozenset({"retention", "impression", "protention", "surprise"})
REQUIRED_SHM_FIXTURE_CASES = frozenset({"fresh", "stale", "missing", "malformed", "empty"})

TEMPORAL_EVIDENCE_ENVELOPE_REQUIRED_FIELDS = (
    "schema_version",
    "envelope_id",
    "source_id",
    "claim_name",
    "observed_at_wall",
    "observed_at_mono",
    "produced_at_wall",
    "valid_from_wall",
    "valid_until_wall",
    "sample_window_s",
    "ttl_s",
    "age_s",
    "temporal_band",
    "evidence_role",
    "authority",
    "authority_ceiling",
    "frame_source",
    "freshness",
    "public_scope",
    "source_payload_state",
    "source_refs",
    "evidence_refs",
    "witness_refs",
    "span_refs",
    "posterior",
    "raw_xml_context_ref",
    "missing_data_reason",
    "language_obligations",
    "expected_in_s",
    "must_verify_by",
)

FAIL_CLOSED_POLICY = {
    "raw_xml_alone_satisfies_public_or_director_claim": False,
    "protention_satisfies_present_current_live_claim": False,
    "stale_retention_satisfies_current_claim": False,
    "stale_retention_without_age_window_language_satisfies_last_observed": False,
    "producer_failure_satisfies_positive_world_state": False,
    "expired_above_floor_posterior_satisfies_claim": False,
    "synthetic_or_llm_inferred_authority_satisfies_factual_ground": False,
}

type IsoTimestamp = str
type TemporalBand = Literal["retention", "impression", "protention", "surprise"]
type EvidenceRole = Literal[
    "supports", "refutes", "context", "prediction", "absence", "producer_failure"
]
type EvidenceAuthority = Literal[
    "raw_sensor",
    "calibrated_claim",
    "derived_claim",
    "broadcast_self_evidence",
    "llm_bound_frame",
    "llm_inferred",
    "synthetic",
]
type AuthorityCeiling = Literal[
    "no_claim",
    "diagnostic_only",
    "last_observed_only",
    "anticipatory_only",
    "fresh_impression_required",
    "public_gate_required",
]
type FrameSource = Literal["raw_sensor", "broadcast_frame", "llm_bound_frame", "none"]
type FreshnessState = Literal["fresh", "aging", "stale", "expired", "missing", "unknown"]
type PublicScope = Literal["private", "public_safe", "public_forbidden"]
type SourcePayloadState = Literal["fresh", "stale", "missing", "malformed", "empty", "unknown"]
type ShmFixtureCase = Literal["fresh", "stale", "missing", "malformed", "empty"]
type ClaimShape = Literal[
    "present_current",
    "public_live",
    "last_observed",
    "anticipatory",
    "surprise_change",
    "diagnostic",
]
type ClaimSupportStatus = Literal[
    "allowed",
    "allowed_last_observed_only",
    "allowed_anticipatory_only",
    "allowed_surprise_only",
    "blocked_raw_xml_only",
    "blocked_public_scope",
    "blocked_missing_span_refs",
    "blocked_missing_witness_refs",
    "blocked_protention_current_claim",
    "blocked_temporal_band_mismatch",
    "blocked_expired_or_stale_current_claim",
    "blocked_stale_retention_requires_age_window",
    "blocked_producer_failure",
    "blocked_synthetic_authority",
    "blocked_evidence_role",
]
type RenderedClaimMode = Literal[
    "present_current",
    "public_live",
    "last_observed_with_age_window",
    "anticipatory",
    "surprise_mismatch",
    "diagnostic_only",
    "none",
]


class TemporalBandEvidenceError(ValueError):
    """Raised when temporal evidence fixtures fail closed."""


class FixtureCase(StrEnum):
    FRESH_IMPRESSION_PUBLIC = "fresh_impression_public"
    STALE_RETENTION = "stale_retention"
    PROTENTION_EXPECTED = "protention_expected"
    SURPRISE_MISMATCH = "surprise_mismatch"
    RAW_XML_ONLY = "raw_xml_only"
    PRODUCER_FAILURE_MISSING = "producer_failure_missing"
    PRODUCER_FAILURE_MALFORMED = "producer_failure_malformed"
    PRODUCER_FAILURE_EMPTY = "producer_failure_empty"
    EXPIRED_HIGH_POSTERIOR = "expired_high_posterior"


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TemporalEvidenceEnvelope(FrozenModel):
    """One temporal-band evidence object consumable by claim gates."""

    schema_version: Literal[1] = 1
    envelope_id: str = Field(pattern=r"^temporal-evidence:[a-z0-9_.:-]+$")
    source_id: str = Field(min_length=1)
    claim_name: str = Field(min_length=1)
    observed_at_wall: IsoTimestamp
    observed_at_mono: float = Field(ge=0.0)
    produced_at_wall: IsoTimestamp
    valid_from_wall: IsoTimestamp
    valid_until_wall: IsoTimestamp
    sample_window_s: float = Field(ge=0.0)
    ttl_s: float = Field(ge=0.0)
    age_s: float = Field(ge=0.0)
    temporal_band: TemporalBand
    evidence_role: EvidenceRole
    authority: EvidenceAuthority
    authority_ceiling: AuthorityCeiling
    frame_source: FrameSource
    freshness: FreshnessState
    public_scope: PublicScope
    source_payload_state: SourcePayloadState
    source_refs: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    witness_refs: tuple[str, ...] = Field(default_factory=tuple)
    span_refs: tuple[str, ...] = Field(default_factory=tuple)
    posterior: float | None = Field(default=None, ge=0.0, le=1.0)
    raw_xml_context_ref: str | None = None
    missing_data_reason: str | None = None
    language_obligations: tuple[str, ...] = Field(default_factory=tuple)
    expected_in_s: float | None = Field(default=None, ge=0.0)
    must_verify_by: IsoTimestamp | None = None
    fixture_case: FixtureCase

    @model_validator(mode="after")
    def _validate_temporal_authority(self) -> Self:
        if _epoch(self.valid_until_wall) < _epoch(self.valid_from_wall):
            raise ValueError("valid_until_wall cannot precede valid_from_wall")
        if _epoch(self.produced_at_wall) < _epoch(self.observed_at_wall):
            raise ValueError("produced_at_wall cannot precede observed_at_wall")
        if self.evidence_role == "producer_failure":
            if self.authority_ceiling != "no_claim":
                raise ValueError("producer_failure evidence must keep authority_ceiling=no_claim")
            if self.missing_data_reason is None:
                raise ValueError("producer_failure evidence requires missing_data_reason")
            if self.source_payload_state not in {"missing", "malformed", "empty"}:
                raise ValueError(
                    "producer_failure evidence must identify missing/malformed/empty data"
                )
            if self.witness_refs or self.span_refs:
                raise ValueError(
                    "producer_failure evidence cannot carry positive witness/span refs"
                )
        if self.temporal_band == "protention":
            if self.evidence_role != "prediction":
                raise ValueError("protention evidence must use evidence_role=prediction")
            if self.authority_ceiling != "anticipatory_only":
                raise ValueError(
                    "protention evidence must keep authority_ceiling=anticipatory_only"
                )
            if self.expected_in_s is None or self.must_verify_by is None:
                raise ValueError("protention evidence requires expected_in_s and must_verify_by")
        if self.temporal_band == "retention" and self.freshness in {"stale", "expired"}:
            if self.authority_ceiling != "last_observed_only":
                raise ValueError(
                    "stale/expired retention must keep authority_ceiling=last_observed_only"
                )
        if (
            self.temporal_band == "impression"
            and self.freshness == "fresh"
            and self.evidence_role == "supports"
            and self.public_scope == "public_safe"
        ):
            if not self.witness_refs or not self.span_refs:
                raise ValueError("fresh public-safe impressions require witness_refs and span_refs")
        if self.authority in {"synthetic", "llm_inferred"} and self.authority_ceiling in {
            "fresh_impression_required",
            "public_gate_required",
        }:
            raise ValueError(
                "synthetic/llm-inferred evidence cannot carry factual authority ceilings"
            )
        return self

    def expired_at(self, now_wall: IsoTimestamp) -> bool:
        """Return true if the envelope is not valid at now_wall."""

        return self.freshness == "expired" or _epoch(now_wall) > _epoch(self.valid_until_wall)


class TemporalShmPayloadFixture(FrozenModel):
    """Fixture row for `/dev/shm/hapax-temporal/bands.json` read states."""

    fixture_case: ShmFixtureCase
    path: Literal["/dev/shm/hapax-temporal/bands.json"]
    source_payload_state: SourcePayloadState
    payload_present: bool
    raw_xml_present: bool
    age_s: float | None = Field(default=None, ge=0.0)
    max_age_s: float = Field(ge=0.0)
    producer_failure: bool
    produces_envelope_refs: tuple[str, ...] = Field(default_factory=tuple)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_fixture_case(self) -> Self:
        if self.fixture_case == "fresh":
            if not self.payload_present or self.producer_failure:
                raise ValueError(
                    "fresh temporal SHM fixture must be present and not producer failure"
                )
            if self.source_payload_state != "fresh":
                raise ValueError("fresh temporal SHM fixture must use source_payload_state=fresh")
        if self.fixture_case in {"missing", "malformed", "empty"}:
            if not self.producer_failure:
                raise ValueError(
                    "missing/malformed/empty temporal SHM fixtures are producer failures"
                )
            if not self.produces_envelope_refs:
                raise ValueError(
                    "producer failure fixtures must produce missing-data evidence refs"
                )
        if self.fixture_case == "stale" and self.source_payload_state != "stale":
            raise ValueError("stale temporal SHM fixture must use source_payload_state=stale")
        return self


class TemporalClaimSupportRequest(FrozenModel):
    claim_id: str = Field(pattern=r"^claim:[a-z0-9_.:-]+$")
    claim_name: str = Field(min_length=1)
    claim_shape: ClaimShape
    public_or_director: bool
    now_wall: IsoTimestamp
    includes_age_window_language: bool = False


class TemporalClaimSupportDecision(FrozenModel):
    claim_id: str
    envelope_id: str
    allowed: bool
    status: ClaimSupportStatus
    rendered_claim_mode: RenderedClaimMode
    authority_ceiling: AuthorityCeiling
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    required_language: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_decision_shape(self) -> Self:
        if self.allowed and self.status.startswith("blocked_"):
            raise ValueError("allowed decisions cannot use blocked status")
        if not self.allowed and self.rendered_claim_mode != "none":
            raise ValueError("blocked decisions must render no claim")
        if self.status == "allowed_last_observed_only":
            required = {"last_observed", "age_s", "sample_window_s"}
            if not required.issubset(set(self.required_language)):
                raise ValueError("last-observed decisions require age/window language")
        return self


class TemporalClaimSupportFixture(FrozenModel):
    fixture_case: str = Field(min_length=1)
    envelope_ref: str = Field(pattern=r"^temporal-evidence:[a-z0-9_.:-]+$")
    request: TemporalClaimSupportRequest
    expected: TemporalClaimSupportDecision


class TemporalBandEvidenceFixtureSet(FrozenModel):
    schema_version: Literal[1]
    fixture_set_id: str
    schema_ref: Literal["schemas/temporal-band-evidence-envelope.schema.json"]
    generated_from: tuple[str, ...] = Field(min_length=1)
    declared_at: IsoTimestamp
    producer: str = Field(min_length=1)
    temporal_bands: tuple[TemporalBand, ...] = Field(min_length=4)
    shm_fixture_cases: tuple[ShmFixtureCase, ...] = Field(min_length=5)
    evidence_envelope_required_fields: tuple[str, ...]
    fail_closed_policy: dict[str, bool]
    shm_payload_fixtures: tuple[TemporalShmPayloadFixture, ...] = Field(min_length=5)
    envelopes: tuple[TemporalEvidenceEnvelope, ...] = Field(min_length=4)
    claim_support_fixtures: tuple[TemporalClaimSupportFixture, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_fixture_set(self) -> Self:
        if set(self.temporal_bands) != REQUIRED_TEMPORAL_BANDS:
            raise ValueError("temporal_bands must cover retention/impression/protention/surprise")
        if set(self.shm_fixture_cases) != REQUIRED_SHM_FIXTURE_CASES:
            raise ValueError("shm_fixture_cases must cover fresh/stale/missing/malformed/empty")
        if set(self.evidence_envelope_required_fields) != set(
            TEMPORAL_EVIDENCE_ENVELOPE_REQUIRED_FIELDS
        ):
            raise ValueError("evidence_envelope_required_fields drifted")
        if self.fail_closed_policy != FAIL_CLOSED_POLICY:
            raise ValueError("fail_closed_policy must pin temporal no-false-grounding gates")
        envelope_map = self.envelopes_by_id()
        if {envelope.temporal_band for envelope in self.envelopes} < REQUIRED_TEMPORAL_BANDS:
            raise ValueError("envelopes must include every required temporal band")
        shm_cases = {fixture.fixture_case for fixture in self.shm_payload_fixtures}
        if shm_cases != REQUIRED_SHM_FIXTURE_CASES:
            raise ValueError("shm_payload_fixtures must cover every required SHM case")
        for fixture in self.shm_payload_fixtures:
            for ref in fixture.produces_envelope_refs:
                envelope = envelope_map.get(ref)
                if envelope is None:
                    raise ValueError(f"SHM fixture cites unknown envelope: {ref}")
                if fixture.producer_failure and envelope.evidence_role != "producer_failure":
                    raise ValueError(
                        f"{fixture.fixture_case} producer failure must cite producer_failure evidence"
                    )
        for fixture in self.claim_support_fixtures:
            envelope = envelope_map.get(fixture.envelope_ref)
            if envelope is None:
                raise ValueError(f"claim fixture cites unknown envelope: {fixture.envelope_ref}")
            actual = evaluate_temporal_claim_support(envelope, fixture.request)
            if actual != fixture.expected:
                raise ValueError(f"claim support fixture drifted: {fixture.fixture_case}")
        return self

    def envelopes_by_id(self) -> dict[str, TemporalEvidenceEnvelope]:
        return {envelope.envelope_id: envelope for envelope in self.envelopes}


def evaluate_temporal_claim_support(
    envelope: TemporalEvidenceEnvelope,
    request: TemporalClaimSupportRequest,
) -> TemporalClaimSupportDecision:
    """Return the fail-closed claim-support decision for one temporal envelope."""

    base = {
        "claim_id": request.claim_id,
        "envelope_id": envelope.envelope_id,
        "authority_ceiling": envelope.authority_ceiling,
    }

    def block(status: ClaimSupportStatus, *reasons: str) -> TemporalClaimSupportDecision:
        return TemporalClaimSupportDecision(
            **base,
            allowed=False,
            status=status,
            rendered_claim_mode="none",
            reason_codes=tuple(reasons),
        )

    if envelope.evidence_role == "producer_failure":
        return block("blocked_producer_failure", "producer_failure_is_missing_data")

    if request.public_or_director:
        if envelope.raw_xml_context_ref and not envelope.witness_refs and not envelope.span_refs:
            return block("blocked_raw_xml_only", "raw_xml_without_witness_or_span_refs")
        if envelope.public_scope != "public_safe":
            return block("blocked_public_scope", f"public_scope_{envelope.public_scope}")
        if not envelope.span_refs:
            return block("blocked_missing_span_refs", "span_refs_required_for_public_or_director")
        if not envelope.witness_refs:
            return block(
                "blocked_missing_witness_refs",
                "witness_refs_required_for_public_or_director",
            )

    if envelope.authority in {"synthetic", "llm_inferred"} and request.claim_shape != "diagnostic":
        return block("blocked_synthetic_authority", f"authority_{envelope.authority}")

    if request.claim_shape in {"present_current", "public_live"}:
        if envelope.temporal_band == "protention":
            return block("blocked_protention_current_claim", "protention_is_anticipatory")
        if envelope.temporal_band != "impression":
            return block(
                "blocked_temporal_band_mismatch",
                f"{envelope.temporal_band}_cannot_ground_current_claim",
            )
        if envelope.expired_at(request.now_wall) or envelope.freshness != "fresh":
            return block(
                "blocked_expired_or_stale_current_claim",
                f"freshness_{envelope.freshness}",
                "validity_window_expired" if envelope.expired_at(request.now_wall) else "not_fresh",
            )
        if envelope.evidence_role != "supports":
            return block("blocked_evidence_role", f"evidence_role_{envelope.evidence_role}")
        return TemporalClaimSupportDecision(
            **base,
            allowed=True,
            status="allowed",
            rendered_claim_mode="public_live"
            if request.claim_shape == "public_live"
            else "present_current",
        )

    if request.claim_shape == "last_observed":
        if envelope.temporal_band != "retention":
            return block(
                "blocked_temporal_band_mismatch",
                f"{envelope.temporal_band}_cannot_ground_last_observed",
            )
        if envelope.freshness == "expired":
            return block("blocked_expired_or_stale_current_claim", "retention_expired")
        if not request.includes_age_window_language:
            return block(
                "blocked_stale_retention_requires_age_window",
                "last_observed_requires_age_s_and_sample_window_s",
            )
        return TemporalClaimSupportDecision(
            **base,
            allowed=True,
            status="allowed_last_observed_only",
            rendered_claim_mode="last_observed_with_age_window",
            required_language=("last_observed", "age_s", "sample_window_s"),
        )

    if request.claim_shape == "anticipatory":
        if envelope.temporal_band != "protention":
            return block(
                "blocked_temporal_band_mismatch",
                f"{envelope.temporal_band}_cannot_ground_anticipatory_claim",
            )
        if envelope.evidence_role != "prediction":
            return block("blocked_evidence_role", f"evidence_role_{envelope.evidence_role}")
        return TemporalClaimSupportDecision(
            **base,
            allowed=True,
            status="allowed_anticipatory_only",
            rendered_claim_mode="anticipatory",
            required_language=("anticipatory", "expected_in_s", "must_verify_by"),
        )

    if request.claim_shape == "surprise_change":
        if envelope.temporal_band != "surprise":
            return block(
                "blocked_temporal_band_mismatch",
                f"{envelope.temporal_band}_cannot_ground_surprise",
            )
        return TemporalClaimSupportDecision(
            **base,
            allowed=True,
            status="allowed_surprise_only",
            rendered_claim_mode="surprise_mismatch",
            required_language=("mismatch_or_change_detected",),
        )

    return TemporalClaimSupportDecision(
        **base,
        allowed=True,
        status="allowed",
        rendered_claim_mode="diagnostic_only",
    )


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TemporalBandEvidenceError(f"{path} did not contain a JSON object")
    return payload


@cache
def load_temporal_band_evidence_fixtures(
    path: Path = TEMPORAL_BAND_EVIDENCE_FIXTURES,
) -> TemporalBandEvidenceFixtureSet:
    """Load and validate temporal band evidence fixtures."""

    try:
        return TemporalBandEvidenceFixtureSet.model_validate(_load_json_object(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise TemporalBandEvidenceError(
            f"invalid temporal band evidence fixtures at {path}: {exc}"
        ) from exc


def _epoch(value: IsoTimestamp) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC).timestamp()


__all__ = [
    "FAIL_CLOSED_POLICY",
    "REQUIRED_SHM_FIXTURE_CASES",
    "REQUIRED_TEMPORAL_BANDS",
    "TEMPORAL_BAND_EVIDENCE_FIXTURES",
    "TEMPORAL_BANDS_PATH",
    "TEMPORAL_EVIDENCE_ENVELOPE_REQUIRED_FIELDS",
    "FixtureCase",
    "TemporalBandEvidenceError",
    "TemporalBandEvidenceFixtureSet",
    "TemporalClaimSupportDecision",
    "TemporalClaimSupportFixture",
    "TemporalClaimSupportRequest",
    "TemporalEvidenceEnvelope",
    "TemporalShmPayloadFixture",
    "evaluate_temporal_claim_support",
    "load_temporal_band_evidence_fixtures",
]
