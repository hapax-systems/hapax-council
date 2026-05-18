from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CouncilMode(StrEnum):
    LABELING = "labeling"
    SCORING = "scoring"
    DISCONFIRMATION = "disconfirmation"
    AUDIT = "audit"
    NARRATIVE = "narrative"


class ConvergenceStatus(StrEnum):
    CONVERGED = "converged"
    CONTESTED = "contested"
    HUNG = "hung"


class CouncilInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CouncilConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    phases: tuple[int, ...] = (1, 2, 3, 4, 5)
    model_aliases: tuple[str, ...] = (
        "opus",
        "balanced",
        "gemini-3-pro",
        "local-fast",
        "web-research",
        "mistral-large",
    )
    shortcircuit_iqr_threshold: float = 1.0
    contested_iqr_threshold: float = 2.0
    family_correlation_penalty_threshold: float = 0.90


class PhaseOneResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_alias: str
    scores: dict[str, int]
    rationale: dict[str, str]
    research_findings: list[str] = Field(default_factory=list)
    tool_calls_log: list[str] = Field(default_factory=list)


class EvidenceClassification(BaseModel):
    model_config = ConfigDict(frozen=True)

    finding: str
    classification: str
    score_level: int


class EvidenceMatrixAxis(BaseModel):
    model_config = ConfigDict(frozen=True)

    axis: str
    classifications: tuple[EvidenceClassification, ...] = ()
    least_inconsistent_score: int | None = None


class EvidenceMatrix(BaseModel):
    model_config = ConfigDict(frozen=True)

    axes: dict[str, EvidenceMatrixAxis] = Field(default_factory=dict)
    built_by: str = ""


class AdversarialExchange(BaseModel):
    model_config = ConfigDict(frozen=True)

    axis: str
    high_scorer: str
    high_score: int
    low_scorer: str
    low_score: int
    challenge_text: str
    response_text: str


class PhaseFourResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_alias: str
    revised_scores: dict[str, int]
    revision_rationale: dict[str, str]
    changed_axes: list[str] = Field(default_factory=list)


class CouncilVerdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    scores: dict[str, int | None]
    confidence_bands: dict[str, tuple[int, int]]
    convergence_status: ConvergenceStatus
    disagreement_log: list[str]
    research_findings: list[str]
    evidence_matrix: EvidenceMatrix | None
    adversarial_exchanges: tuple[AdversarialExchange, ...] = ()
    receipt: dict[str, Any] = Field(default_factory=dict)


class NarrativeVerdictStatus(StrEnum):
    BROADCAST_READY = "broadcast_ready"
    REVISE_AND_RESUBMIT = "revise_and_resubmit"
    STRUCTURAL_REWORK = "structural_rework"
    GENERIC_DETECTED = "generic_detected"


class NarrativeVerdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    scores: dict[str, int | None]
    confidence_bands: dict[str, tuple[int, int]]
    convergence_status: ConvergenceStatus
    verdict_status: NarrativeVerdictStatus
    alternative_framings: list[str] = Field(default_factory=list)
    audience_breaks: list[str] = Field(default_factory=list)
    disagreement_log: list[str] = Field(default_factory=list)
    revision_directives: list[str] = Field(default_factory=list)
    receipt: dict[str, Any] = Field(default_factory=dict)
