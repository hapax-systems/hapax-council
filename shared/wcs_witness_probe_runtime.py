"""Runtime witness probe models for World Capability Surface outcomes.

These probes certify declared evidence obligations. They do not infer live truth
from selection, command dispatch, route names, or model confidence.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
WCS_WITNESS_PROBE_FIXTURES = REPO_ROOT / "config" / "wcs-witness-probe-fixtures.json"

REQUIRED_WITNESS_CLASSES = frozenset(
    {
        "read_only",
        "command_result",
        "public_egress",
        "archive_ref",
        "audio_video_state",
    }
)

REQUIRED_PROBE_STATES = frozenset(
    {
        "selected",
        "commanded",
        "observed",
        "witnessed",
        "blocked",
        "stale",
        "failed",
    }
)


class WCSWitnessProbeRuntimeError(ValueError):
    """Raised when witness probe fixtures cannot be loaded safely."""


class WitnessClass(StrEnum):
    READ_ONLY = "read_only"
    COMMAND_RESULT = "command_result"
    PUBLIC_EGRESS = "public_egress"
    ARCHIVE_REF = "archive_ref"
    AUDIO_VIDEO_STATE = "audio_video_state"


class ProbeState(StrEnum):
    SELECTED = "selected"
    COMMANDED = "commanded"
    OBSERVED = "observed"
    WITNESSED = "witnessed"
    BLOCKED = "blocked"
    STALE = "stale"
    FAILED = "failed"


class LearningUpdatePolicy(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    NEUTRAL = "neutral"
    DEFER = "defer"


class WitnessClassInterface(BaseModel):
    model_config = ConfigDict(extra="forbid")

    witness_class: WitnessClass
    certifies: str
    required_evidence_fields: list[str] = Field(min_length=1)
    source_ref_required: Literal[True] = True
    is_truth_oracle: Literal[False] = False


class WitnessProbeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    probe_id: str
    surface_id: str
    capability_id: str
    witness_class: WitnessClass
    state: ProbeState
    checked_at: str
    selected_ref: str | None = None
    command_ref: str | None = None
    witness_ref: str | None = None
    source_refs: list[str] = Field(min_length=1)
    freshness_window_s: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)
    failure_reason: str | None = None
    blocked_reasons: list[str] = Field(default_factory=list)
    required_for_public_claim: bool = False
    required_witness_classes: list[WitnessClass] = Field(default_factory=list)
    command_result_success: bool = False
    selected_at: str | None = None
    commanded_at: str | None = None
    observed_at: str | None = None
    witnessed_at: str | None = None
    certifies_declared_obligation_only: Literal[True] = True

    @model_validator(mode="after")
    def _validate_state_evidence(self) -> Self:
        if self.state is ProbeState.WITNESSED:
            if self.witnessed_at is None:
                raise ValueError("witnessed probes require witnessed_at")
            if self.witness_ref is None:
                raise ValueError("witnessed probes require witness_ref")
            if self.failure_reason is not None:
                raise ValueError("witnessed probes cannot carry failure_reason")

        if self.state in {ProbeState.BLOCKED, ProbeState.STALE, ProbeState.FAILED}:
            if not self.failure_reason:
                raise ValueError(f"{self.state.value} probes require failure_reason")
            if not self.blocked_reasons:
                raise ValueError(f"{self.state.value} probes require blocked_reasons")

        if self.state is ProbeState.COMMANDED and self.command_result_success:
            if self.command_ref is None:
                raise ValueError("successful command probes require command_ref")
            if self.commanded_at is None:
                raise ValueError("successful command probes require commanded_at")

        if self.state is ProbeState.SELECTED and self.selected_ref is None:
            raise ValueError("selected probes require selected_ref")
        return self

    def evidence_timestamp(self) -> str:
        """Return the freshest timestamp this probe can use for freshness checks."""

        return (
            self.witnessed_at
            or self.observed_at
            or self.commanded_at
            or self.selected_at
            or self.checked_at
        )

    def is_fresh(self, *, now: datetime, max_age_s: int | None = None) -> bool:
        """True when the probe's evidence timestamp is inside its freshness window."""

        window_s = self.freshness_window_s if max_age_s is None else max_age_s
        if window_s <= 0:
            return False
        age_s = (now - _parse_timestamp(self.evidence_timestamp())).total_seconds()
        return 0 <= age_s <= window_s


class WitnessProbeEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    probe_id: str
    surface_id: str
    witness_class: WitnessClass
    state: ProbeState
    public_claim_allowed: bool
    learning_update_policy: LearningUpdatePolicy
    blocked_reasons: list[str]
    failure_reason: str | None = None
    confidence: float
    source_refs: list[str]
    certifies_declared_obligation_only: Literal[True] = True


class WCSWitnessProbeFixtureSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    fixture_set_id: str
    schema_ref: str
    generated_from: list[str] = Field(min_length=1)
    declared_at: str
    witness_class_interfaces: list[WitnessClassInterface] = Field(min_length=1)
    states: list[ProbeState] = Field(min_length=1)
    probes: list[WitnessProbeRecord] = Field(min_length=1)
    fail_closed_policy: dict[str, bool]

    @model_validator(mode="after")
    def _validate_contract_coverage(self) -> Self:
        classes = {interface.witness_class.value for interface in self.witness_class_interfaces}
        missing_classes = REQUIRED_WITNESS_CLASSES - classes
        if missing_classes:
            raise ValueError("missing witness probe classes: " + ", ".join(sorted(missing_classes)))

        states = {state.value for state in self.states}
        missing_states = REQUIRED_PROBE_STATES - states
        if missing_states:
            raise ValueError("missing witness probe states: " + ", ".join(sorted(missing_states)))

        fixture_states = {probe.state.value for probe in self.probes}
        missing_fixture_states = REQUIRED_PROBE_STATES - fixture_states
        if missing_fixture_states:
            raise ValueError(
                "missing fixture probe states: " + ", ".join(sorted(missing_fixture_states))
            )

        if self.fail_closed_policy != {
            "selected_or_commanded_is_public_truth": False,
            "missing_witness_allows_public_claim": False,
            "stale_witness_allows_public_claim": False,
            "probes_are_expert_truth_oracle": False,
        }:
            raise ValueError("fail_closed_policy must pin selected/commanded/stale to blocked")

        ids = [probe.probe_id for probe in self.probes]
        duplicate_ids = sorted({probe_id for probe_id in ids if ids.count(probe_id) > 1})
        if duplicate_ids:
            raise ValueError("duplicate witness probe ids: " + ", ".join(duplicate_ids))
        return self

    def probes_by_id(self) -> dict[str, WitnessProbeRecord]:
        return {probe.probe_id: probe for probe in self.probes}

    def require_probe(self, probe_id: str) -> WitnessProbeRecord:
        probe = self.probes_by_id().get(probe_id)
        if probe is None:
            raise KeyError(f"unknown WCS witness probe: {probe_id}")
        return probe

    def probes_for_surface(self, surface_id: str) -> list[WitnessProbeRecord]:
        return [probe for probe in self.probes if probe.surface_id == surface_id]


def evaluate_probe(
    probe: WitnessProbeRecord,
    *,
    now: datetime | None = None,
    min_confidence: float = 0.5,
) -> WitnessProbeEvaluation:
    """Evaluate one probe without inventing evidence beyond its declared record."""

    checked_now = now or datetime.now(tz=UTC)
    blocked_reasons = list(probe.blocked_reasons)
    failure_reason = probe.failure_reason
    state = probe.state
    learning_policy = LearningUpdatePolicy.NEUTRAL
    public_claim_allowed = False

    if probe.state is ProbeState.WITNESSED:
        if probe.confidence < min_confidence:
            state = ProbeState.FAILED
            failure_reason = "witness_confidence_below_threshold"
            blocked_reasons.append("witness_confidence_below_threshold")
            learning_policy = LearningUpdatePolicy.FAILURE
        elif not probe.is_fresh(now=checked_now):
            state = ProbeState.STALE
            failure_reason = "witness_stale"
            blocked_reasons.append("stale_witness_blocks_public_claim")
            learning_policy = LearningUpdatePolicy.FAILURE
        else:
            public_claim_allowed = probe.required_for_public_claim
            learning_policy = LearningUpdatePolicy.SUCCESS
    elif probe.state is ProbeState.COMMANDED:
        learning_policy = LearningUpdatePolicy.DEFER
        blocked_reasons.append("commanded_without_required_witness")
        for witness_class in probe.required_witness_classes:
            blocked_reasons.append(f"missing_witness:{witness_class.value}")
    elif probe.state is ProbeState.SELECTED:
        learning_policy = LearningUpdatePolicy.DEFER
        blocked_reasons.append("selected_without_command_or_witness")
    elif probe.state is ProbeState.OBSERVED:
        learning_policy = LearningUpdatePolicy.DEFER
        blocked_reasons.append("observed_without_required_witness")
    elif probe.state in {ProbeState.BLOCKED, ProbeState.STALE, ProbeState.FAILED}:
        learning_policy = LearningUpdatePolicy.FAILURE

    return WitnessProbeEvaluation(
        probe_id=probe.probe_id,
        surface_id=probe.surface_id,
        witness_class=probe.witness_class,
        state=state,
        public_claim_allowed=public_claim_allowed,
        learning_update_policy=learning_policy,
        blocked_reasons=_dedupe(blocked_reasons),
        failure_reason=failure_reason,
        confidence=probe.confidence,
        source_refs=probe.source_refs,
    )


def load_wcs_witness_probe_fixtures(
    path: Path = WCS_WITNESS_PROBE_FIXTURES,
) -> WCSWitnessProbeFixtureSet:
    """Load the fixture-backed WCS witness probe runtime packet."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return WCSWitnessProbeFixtureSet.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise WCSWitnessProbeRuntimeError(f"failed to load WCS witness probes: {exc}") from exc


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


__all__ = [
    "REQUIRED_PROBE_STATES",
    "REQUIRED_WITNESS_CLASSES",
    "WCSWitnessProbeFixtureSet",
    "WCSWitnessProbeRuntimeError",
    "WCS_WITNESS_PROBE_FIXTURES",
    "LearningUpdatePolicy",
    "ProbeState",
    "WitnessClass",
    "WitnessClassInterface",
    "WitnessProbeEvaluation",
    "WitnessProbeRecord",
    "evaluate_probe",
    "load_wcs_witness_probe_fixtures",
]
