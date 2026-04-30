"""Source-qualified temporal span registry and media sidecar contracts.

This module is a fixture-backed foundation for downstream replay, media, and
perception tasks. It does not mutate live media pipelines; it defines the
span/sidecar contract those pipelines can consume without joining by file mtime.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPORAL_SPAN_REGISTRY_FIXTURES = REPO_ROOT / "config" / "temporal-span-registry-fixtures.json"

REQUIRED_SIDECAR_KINDS = frozenset(
    {
        "camera_jpeg",
        "hls_segment",
        "audio_window",
        "scene_detection",
        "ir_report",
        "vad_transition",
        "reverie_content",
        "replay_span",
        "context_state",
    }
)
REQUIRED_ALIGNMENT_SOURCE_KINDS = frozenset(
    {
        "audio_window",
        "camera_jpeg",
        "scene_detection",
        "ir_report",
        "stimmung_context",
        "director_context",
        "research_condition",
    }
)
FAIL_CLOSED_POLICY = {
    "mtime_is_join_key": False,
    "missing_span_refs_allow_claim_bearing_output": False,
    "diagnostic_records_are_dropped_on_missing_span_refs": False,
    "private_spans_can_ground_public_claims": False,
    "rights_blocked_spans_can_ground_public_claims": False,
}

type TemporalSpanKind = Literal[
    "instant_event",
    "sample_window",
    "frame_exposure",
    "classification_window",
    "trajectory_span",
    "composition_span",
    "archive_segment_span",
    "replay_span",
    "validity_span",
    "future_sensor_span",
]
type TemporalSourceKind = Literal[
    "camera_jpeg",
    "hls_segment",
    "audio_window",
    "scene_detection",
    "ir_report",
    "vad_transition",
    "reverie_content",
    "replay_span",
    "stimmung_context",
    "director_context",
    "research_condition",
]
type ProducerKind = Literal[
    "studio_compositor",
    "hapax_daimonion",
    "environmental_perception",
    "reverie",
    "archive_replay",
    "research_registry",
    "temporal_span_fixture",
]
type ClockDomain = Literal[
    "monotonic_ns",
    "wall_clock_ns",
    "hls_media_time_ns",
    "audio_sample_clock_ns",
    "camera_exposure_clock_ns",
    "derived_span_ns",
]
type PrivacyLabel = Literal["public_safe", "private_only", "dry_run", "blocked", "unknown"]
type RightsClass = Literal[
    "public_clear", "private_only", "blocked", "missing", "not_applicable", "unknown"
]
type SidecarKind = Literal[
    "camera_jpeg",
    "hls_segment",
    "audio_window",
    "scene_detection",
    "ir_report",
    "vad_transition",
    "reverie_content",
    "replay_span",
    "context_state",
]
type MediaOutputKind = Literal[
    "replay_card", "media_sidecar", "public_event_clip", "diagnostic_report"
]
type SpanClaimDecisionStatus = Literal[
    "allowed",
    "blocked_no_span_refs",
    "blocked_public_scope",
    "blocked_missing_span_refs",
    "blocked_private_or_rights",
    "degraded_diagnostic",
]


class TemporalSpanRegistryError(ValueError):
    """Raised when temporal span registry fixtures fail closed."""


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TemporalSpan(FrozenModel):
    """Source-qualified interval or instant that can be joined without mtime."""

    schema_version: Literal[1] = 1
    span_id: str = Field(pattern=r"^span:[a-z0-9_.:-]+$")
    span_kind: TemporalSpanKind
    source_id: str = Field(min_length=1)
    source_kind: TemporalSourceKind
    producer: ProducerKind
    clock_domain: ClockDomain
    observed_start_ns: int = Field(ge=0)
    observed_end_ns: int = Field(ge=0)
    ingested_at_ns: int = Field(ge=0)
    sequence_ids: tuple[str, ...] = Field(min_length=1)
    capture_session_id: str = Field(min_length=1)
    cadence_s: float | None = Field(default=None, ge=0.0)
    validity_start_ns: int = Field(ge=0)
    validity_until_ns: int = Field(ge=0)
    source_span_refs: tuple[str, ...] = Field(default_factory=tuple)
    source_refs: tuple[str, ...] = Field(min_length=1)
    transform: str = Field(min_length=1)
    privacy_label: PrivacyLabel
    rights_class: RightsClass
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    artifact_path: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_temporal_bounds_and_authority(self) -> Self:
        if self.observed_end_ns < self.observed_start_ns:
            raise ValueError("observed_end_ns cannot precede observed_start_ns")
        if self.span_kind != "instant_event" and self.observed_end_ns == self.observed_start_ns:
            raise ValueError("non-instant spans require non-zero duration")
        if self.validity_until_ns < self.validity_start_ns:
            raise ValueError("validity_until_ns cannot precede validity_start_ns")
        if self.validity_start_ns > self.observed_start_ns:
            raise ValueError("validity window must include observed_start_ns")
        if self.validity_until_ns < self.observed_end_ns:
            raise ValueError("validity window must include observed_end_ns")
        if self.ingested_at_ns < self.observed_start_ns:
            raise ValueError("ingested_at_ns cannot precede observed_start_ns")
        if self.span_id in self.source_span_refs:
            raise ValueError("span cannot cite itself as a source span")
        if self.privacy_label == "public_safe" and self.rights_class in {
            "blocked",
            "missing",
            "unknown",
        }:
            raise ValueError("public_safe spans require non-blocked rights")
        _reject_mtime_metadata(self.metadata)
        return self

    def overlaps(self, other: TemporalSpan) -> bool:
        """Return true when two observed intervals intersect."""

        return (
            self.observed_start_ns <= other.observed_end_ns
            and other.observed_start_ns <= self.observed_end_ns
        )


class TemporalMediaSidecar(FrozenModel):
    schema_version: Literal[1] = 1
    sidecar_id: str = Field(pattern=r"^sidecar:[a-z0-9_.:-]+$")
    sidecar_kind: SidecarKind
    span_ref: str = Field(pattern=r"^span:[a-z0-9_.:-]+$")
    artifact_path: str = Field(min_length=1)
    producer: ProducerKind
    source_refs: tuple[str, ...] = Field(min_length=1)
    produced_at_ns: int = Field(ge=0)
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    diagnostic_only: bool = False
    join_policy: Literal["temporal_span_overlap"] = "temporal_span_overlap"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_sidecar_join_policy(self) -> Self:
        _reject_mtime_metadata(self.metadata)
        return self


class TemporalSpanAlignment(FrozenModel):
    anchor_span_ref: str
    required_source_kinds: tuple[TemporalSourceKind, ...]
    aligned_span_refs: tuple[str, ...]
    aligned_by_source_kind: dict[TemporalSourceKind, tuple[str, ...]]
    missing_required_source_kinds: tuple[TemporalSourceKind, ...]
    used_mtime: Literal[False] = False

    @model_validator(mode="after")
    def _validate_alignment_without_mtime(self) -> Self:
        if self.used_mtime is not False:
            raise ValueError("temporal span alignment cannot use mtime")
        if self.missing_required_source_kinds:
            missing = ", ".join(self.missing_required_source_kinds)
            raise ValueError(f"alignment fixture missing required source kinds: {missing}")
        return self


class ClaimBearingMediaOutput(FrozenModel):
    output_id: str = Field(pattern=r"^media_output:[a-z0-9_.:-]+$")
    output_kind: MediaOutputKind
    claim_bearing: bool
    diagnostic_only: bool
    public_scope: Literal["private", "public_safe", "public_forbidden"]
    span_refs: tuple[str, ...] = Field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_output_claim_shape(self) -> Self:
        if self.claim_bearing and self.diagnostic_only:
            raise ValueError("claim-bearing outputs cannot be diagnostic_only")
        if self.claim_bearing and self.public_scope == "public_safe" and not self.evidence_refs:
            raise ValueError("public claim-bearing outputs require evidence_refs")
        return self


class SpanClaimGateDecision(FrozenModel):
    output_id: str
    allowed: bool
    status: SpanClaimDecisionStatus
    missing_span_refs: tuple[str, ...] = Field(default_factory=tuple)
    blocked_span_refs: tuple[str, ...] = Field(default_factory=tuple)
    diagnostic_preserved: bool
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_fail_closed_decision(self) -> Self:
        if self.allowed and self.status != "allowed":
            raise ValueError("allowed decisions must use allowed status")
        if self.allowed and (self.missing_span_refs or self.blocked_span_refs):
            raise ValueError("allowed decisions cannot carry missing or blocked span refs")
        if self.status == "allowed" and not self.allowed:
            raise ValueError("allowed status requires allowed=true")
        if self.status == "blocked_missing_span_refs" and not self.missing_span_refs:
            raise ValueError("blocked_missing_span_refs requires missing_span_refs")
        if self.status == "degraded_diagnostic" and not self.diagnostic_preserved:
            raise ValueError("degraded diagnostic decisions must preserve diagnostics")
        return self


class AlignmentFixture(FrozenModel):
    anchor_span_ref: str
    required_source_kinds: tuple[TemporalSourceKind, ...]
    expected_aligned_span_refs: tuple[str, ...]
    expected_missing_required_source_kinds: tuple[TemporalSourceKind, ...] = Field(
        default_factory=tuple
    )


class ClaimGateFixture(FrozenModel):
    output: ClaimBearingMediaOutput
    expected: SpanClaimGateDecision


class TemporalSpanRegistryFixtureSet(FrozenModel):
    schema_version: Literal[1]
    fixture_set_id: str
    schema_ref: Literal["schemas/temporal-span-registry.schema.json"]
    generated_from: tuple[str, ...] = Field(min_length=1)
    declared_at: str
    producer: str
    required_sidecar_kinds: tuple[SidecarKind, ...]
    fail_closed_policy: dict[str, bool]
    spans: tuple[TemporalSpan, ...] = Field(min_length=1)
    sidecars: tuple[TemporalMediaSidecar, ...] = Field(min_length=1)
    alignment_fixture: AlignmentFixture
    claim_gate_fixtures: tuple[ClaimGateFixture, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_registry_fixture_contract(self) -> Self:
        if self.fail_closed_policy != FAIL_CLOSED_POLICY:
            raise ValueError("fail_closed_policy must pin every no-mtime/no-grant gate")
        declared_sidecars = {kind for kind in self.required_sidecar_kinds}
        if not REQUIRED_SIDECAR_KINDS.issubset(declared_sidecars):
            missing = REQUIRED_SIDECAR_KINDS - declared_sidecars
            raise ValueError("required_sidecar_kinds missing: " + ", ".join(sorted(missing)))
        observed_sidecars = {sidecar.sidecar_kind for sidecar in self.sidecars}
        if not REQUIRED_SIDECAR_KINDS.issubset(observed_sidecars):
            missing = REQUIRED_SIDECAR_KINDS - observed_sidecars
            raise ValueError("sidecar fixtures missing: " + ", ".join(sorted(missing)))
        span_ids = [span.span_id for span in self.spans]
        duplicates = sorted({span_id for span_id in span_ids if span_ids.count(span_id) > 1})
        if duplicates:
            raise ValueError("duplicate temporal span ids: " + ", ".join(duplicates))
        span_map = self.spans_by_id()
        for span in self.spans:
            missing_sources = [ref for ref in span.source_span_refs if ref not in span_map]
            if missing_sources:
                raise ValueError(f"{span.span_id} cites unknown source spans: {missing_sources}")
        for sidecar in self.sidecars:
            span = span_map.get(sidecar.span_ref)
            if span is None:
                raise ValueError(f"{sidecar.sidecar_id} cites unknown span_ref")
            if sidecar.artifact_path != span.artifact_path:
                raise ValueError(f"{sidecar.sidecar_id} artifact_path must mirror span")
            if sidecar.content_hash != span.content_hash:
                raise ValueError(f"{sidecar.sidecar_id} content_hash must mirror span")
        registry = TemporalSpanRegistry(spans=self.spans, sidecars=self.sidecars)
        alignment = registry.resolve_alignment(
            self.alignment_fixture.anchor_span_ref,
            required_source_kinds=self.alignment_fixture.required_source_kinds,
        )
        if alignment.aligned_span_refs != self.alignment_fixture.expected_aligned_span_refs:
            raise ValueError("alignment fixture expected_aligned_span_refs drifted")
        if (
            alignment.missing_required_source_kinds
            != self.alignment_fixture.expected_missing_required_source_kinds
        ):
            raise ValueError("alignment fixture expected missing source kinds drifted")
        for fixture in self.claim_gate_fixtures:
            actual = registry.evaluate_claim_bearing_output(fixture.output)
            if actual != fixture.expected:
                raise ValueError(f"claim gate fixture drifted for {fixture.output.output_id}")
        return self

    def spans_by_id(self) -> dict[str, TemporalSpan]:
        """Return span rows keyed by span id."""

        return {span.span_id: span for span in self.spans}

    def sidecars_by_kind(self) -> dict[SidecarKind, tuple[TemporalMediaSidecar, ...]]:
        """Return media sidecars grouped by sidecar kind."""

        grouped: dict[SidecarKind, list[TemporalMediaSidecar]] = {}
        for sidecar in self.sidecars:
            grouped.setdefault(sidecar.sidecar_kind, []).append(sidecar)
        return {kind: tuple(rows) for kind, rows in grouped.items()}

    def registry(self) -> TemporalSpanRegistry:
        """Return a queryable registry for fixture consumers."""

        return TemporalSpanRegistry(spans=self.spans, sidecars=self.sidecars)


class TemporalSpanRegistry(FrozenModel):
    spans: tuple[TemporalSpan, ...]
    sidecars: tuple[TemporalMediaSidecar, ...] = Field(default_factory=tuple)

    def spans_by_id(self) -> dict[str, TemporalSpan]:
        """Return span rows keyed by span id."""

        return {span.span_id: span for span in self.spans}

    def require_span(self, span_ref: str) -> TemporalSpan:
        """Return one span or raise KeyError."""

        try:
            return self.spans_by_id()[span_ref]
        except KeyError as exc:
            raise KeyError(f"unknown temporal span: {span_ref}") from exc

    def overlapping_spans(
        self,
        anchor_span_ref: str,
        *,
        source_kinds: tuple[TemporalSourceKind, ...] = (),
    ) -> tuple[TemporalSpan, ...]:
        """Return spans whose observed interval overlaps the anchor span."""

        anchor = self.require_span(anchor_span_ref)
        allowed = set(source_kinds)
        return tuple(
            span
            for span in self.spans
            if self._can_align_with_anchor(anchor=anchor, candidate=span, source_kinds=allowed)
        )

    def _can_align_with_anchor(
        self,
        *,
        anchor: TemporalSpan,
        candidate: TemporalSpan,
        source_kinds: set[TemporalSourceKind],
    ) -> bool:
        if candidate.span_id == anchor.span_id:
            return False
        if source_kinds and candidate.source_kind not in source_kinds:
            return False
        if candidate.capture_session_id != anchor.capture_session_id:
            return False
        if not candidate.overlaps(anchor):
            return False
        return _clock_domains_are_compatible(anchor, candidate)

    def resolve_alignment(
        self,
        anchor_span_ref: str,
        *,
        required_source_kinds: tuple[TemporalSourceKind, ...],
    ) -> TemporalSpanAlignment:
        """Resolve aligned spans by interval overlap, never by file mtime."""

        overlapping = self.overlapping_spans(
            anchor_span_ref,
            source_kinds=required_source_kinds,
        )
        by_kind: dict[TemporalSourceKind, list[str]] = {kind: [] for kind in required_source_kinds}
        for span in overlapping:
            by_kind.setdefault(span.source_kind, []).append(span.span_id)
        aligned_by_kind = {
            kind: tuple(refs)
            for kind, refs in by_kind.items()
            if refs or kind in required_source_kinds
        }
        missing = tuple(kind for kind in required_source_kinds if not aligned_by_kind.get(kind))
        aligned_refs = tuple(
            dict.fromkeys(ref for refs in aligned_by_kind.values() for ref in refs)
        )
        return TemporalSpanAlignment(
            anchor_span_ref=anchor_span_ref,
            required_source_kinds=required_source_kinds,
            aligned_span_refs=aligned_refs,
            aligned_by_source_kind=aligned_by_kind,
            missing_required_source_kinds=missing,
        )

    def evaluate_claim_bearing_output(
        self,
        output: ClaimBearingMediaOutput,
    ) -> SpanClaimGateDecision:
        """Fail closed when claim-bearing media/replay output lacks valid span refs."""

        span_map = self.spans_by_id()
        if output.claim_bearing and not output.span_refs:
            return SpanClaimGateDecision(
                output_id=output.output_id,
                allowed=False,
                status="blocked_no_span_refs",
                diagnostic_preserved=False,
                reason_codes=("empty_span_refs",),
            )
        if output.claim_bearing and output.public_scope != "public_safe":
            return SpanClaimGateDecision(
                output_id=output.output_id,
                allowed=False,
                status="blocked_public_scope",
                diagnostic_preserved=False,
                reason_codes=(f"public_scope_{output.public_scope}",),
            )
        missing = tuple(ref for ref in output.span_refs if ref not in span_map)
        if missing:
            if output.claim_bearing:
                return SpanClaimGateDecision(
                    output_id=output.output_id,
                    allowed=False,
                    status="blocked_missing_span_refs",
                    missing_span_refs=missing,
                    diagnostic_preserved=False,
                    reason_codes=("missing_span_refs",),
                )
            return SpanClaimGateDecision(
                output_id=output.output_id,
                allowed=False,
                status="degraded_diagnostic",
                missing_span_refs=missing,
                diagnostic_preserved=True,
                reason_codes=("diagnostic_missing_span_refs",),
            )

        blocked = tuple(
            span.span_id
            for span in (span_map[ref] for ref in output.span_refs)
            if span.privacy_label != "public_safe"
            or span.rights_class not in {"public_clear", "not_applicable"}
        )
        if output.claim_bearing and blocked:
            return SpanClaimGateDecision(
                output_id=output.output_id,
                allowed=False,
                status="blocked_private_or_rights",
                blocked_span_refs=blocked,
                diagnostic_preserved=False,
                reason_codes=("private_or_rights_blocked_span_refs",),
            )
        return SpanClaimGateDecision(
            output_id=output.output_id,
            allowed=output.claim_bearing,
            status="allowed" if output.claim_bearing else "degraded_diagnostic",
            diagnostic_preserved=not output.claim_bearing,
            reason_codes=(),
        )


def _clock_domain_mapping_ref(span: TemporalSpan) -> str | None:
    mapping_ref = span.metadata.get("clock_domain_mapping_ref")
    if isinstance(mapping_ref, str) and mapping_ref:
        return mapping_ref
    return None


def _has_explicit_span_lineage(anchor: TemporalSpan, candidate: TemporalSpan) -> bool:
    if candidate.span_id in anchor.source_span_refs:
        return True
    if anchor.span_id in candidate.source_span_refs:
        return True
    return bool(set(anchor.source_span_refs).intersection(candidate.source_span_refs))


def _clock_domains_are_compatible(anchor: TemporalSpan, candidate: TemporalSpan) -> bool:
    if anchor.clock_domain == candidate.clock_domain:
        return True
    if _has_explicit_span_lineage(anchor, candidate):
        return True
    anchor_mapping_ref = _clock_domain_mapping_ref(anchor)
    candidate_mapping_ref = _clock_domain_mapping_ref(candidate)
    return anchor_mapping_ref is not None and anchor_mapping_ref == candidate_mapping_ref


def _reject_mtime_metadata(metadata: dict[str, Any]) -> None:
    _reject_mtime_value(metadata, path="metadata")


def _reject_mtime_value(value: Any, *, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if "mtime" in str(key).lower():
                raise ValueError("mtime cannot appear in temporal span metadata keys")
            _reject_mtime_value(child, path=f"{path}.{key}")
        return
    if isinstance(value, list | tuple):
        for index, child in enumerate(value):
            _reject_mtime_value(child, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and "mtime" in value.lower():
        raise ValueError("mtime cannot appear in temporal span metadata values")


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TemporalSpanRegistryError(f"{path} did not contain a JSON object")
    return payload


@cache
def load_temporal_span_registry_fixtures(
    path: Path = TEMPORAL_SPAN_REGISTRY_FIXTURES,
) -> TemporalSpanRegistryFixtureSet:
    """Load and validate temporal span registry fixtures."""

    try:
        return TemporalSpanRegistryFixtureSet.model_validate(_load_json_object(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise TemporalSpanRegistryError(
            f"invalid temporal span registry fixtures at {path}: {exc}"
        ) from exc


__all__ = [
    "FAIL_CLOSED_POLICY",
    "REQUIRED_ALIGNMENT_SOURCE_KINDS",
    "REQUIRED_SIDECAR_KINDS",
    "TEMPORAL_SPAN_REGISTRY_FIXTURES",
    "AlignmentFixture",
    "ClaimBearingMediaOutput",
    "ClaimGateFixture",
    "SpanClaimGateDecision",
    "TemporalMediaSidecar",
    "TemporalSpan",
    "TemporalSpanAlignment",
    "TemporalSpanRegistry",
    "TemporalSpanRegistryError",
    "TemporalSpanRegistryFixtureSet",
    "load_temporal_span_registry_fixtures",
]
