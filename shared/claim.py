"""Universal Bayesian Claim-Confidence — API surface stub (Phase 0 STUB).

Ships the frozen signatures so peer Phase 1 drafts (alpha prompt-envelope wrap,
delta vinyl/music cluster, epsilon refusal gate) can import against a stable
contract while the implementation lands in Phase 0 FULL.

Research foundation: ``docs/research/2026-04-24-universal-bayesian-claim-confidence.md``.
Every field docstring here is operative; no ad-hoc priors, no ungrounded claims.

Phase 0 FULL will implement the bodies + ship the CI rules HPX003 (Claim needs
LRDerivation) + HPX004 (Claim needs reconstructible prior_provenance). Both
are gate-listed in workstream-realignment-v3 §7 (Phase-gated, not in-force).

Kill-switch for rollback: ``HAPAX_BAYESIAN_BYPASS=1`` — restores pre-Phase-0
routing. Implementation lands alongside CI rules in Phase 0 FULL.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Domain = Literal["audio", "visual", "activity", "identity", "mood", "environment", "meta"]

PriorSource = Literal[
    "maximum_entropy", "jeffreys", "reference", "constraint_narrowed", "empirical"
]

LRSourceCategory = Literal[
    "calibration_study",
    "calibrated_classifier",
    "physical_model",
    "expert_elicitation_shelf",
    "online_recalibration",
]

FrameSource = Literal["raw_sensor", "broadcast_frame", "llm_bound_frame"]

CompositionOp = Literal["noisy_or", "noisy_and", "cpt"]


class EvidenceRef(BaseModel):
    signal_name: str
    value: bool | float | str
    timestamp: float
    frame_source: FrameSource


class TemporalProfile(BaseModel):
    """Per-claim temporal dynamics. Presence: fast-enter/slow-exit. Music: inverted."""

    enter_threshold: float = Field(ge=0.0, le=1.0)
    exit_threshold: float = Field(ge=0.0, le=1.0)
    k_enter: int = Field(ge=1)
    k_exit: int = Field(ge=1)
    bocd_hazard: float | None = None


class LRDerivation(BaseModel):
    """Per-signal likelihood-ratio provenance. HPX003 CI rule requires this record
    for every signal any ClaimEngine consumes."""

    signal_name: str
    claim_name: str
    source_category: LRSourceCategory
    p_true_given_h1: float = Field(ge=0.0, le=1.0)
    p_true_given_h0: float = Field(ge=0.0, le=1.0)
    positive_only: bool
    estimation_reference: str
    calibration_window_s: float | None = None


class PriorProvenance(BaseModel):
    """Derivation-trail for a claim's prior. HPX004 CI rule requires this record
    and validates reconstructibility. Operator directive 2026-04-24: priors are
    derivations of invariants, not ad-hoc."""

    claim_name: str
    structural_commitments: list[str]
    reference_prior: str
    constraint_narrowing: str
    symmetry: str | None = None
    derivation_document_ref: str


class ClaimComposition(BaseModel):
    operator: CompositionOp
    parent_claim_names: list[str]


class Claim(BaseModel):
    """One perceptual or world-state assertion with calibrated posterior."""

    name: str
    domain: Domain
    proposition: str
    posterior: float = Field(ge=0.0, le=1.0)
    prior_source: PriorSource
    prior_provenance_ref: str  # YAML key into prior_provenance.yaml registry
    evidence_sources: list[EvidenceRef]
    last_update_t: float
    temporal_profile: TemporalProfile
    composition: ClaimComposition | None = None
    narration_floor: float = Field(ge=0.0, le=1.0)
    staleness_cutoff_s: float = Field(gt=0.0)


class Signal[T](BaseModel):
    """Raw sensor → Claim contribution adapter. YAMNet, SigLIP2, PaddleOCR subclass.

    Decoration-strip duality: the same classifier run on broadcast_frame vs
    llm_bound_frame produces distinct Signal instances with distinct
    LRDerivation records (gate 22 enforces per-signal frame-source
    declaration).
    """

    name: str
    claim_name: str
    frame_source: FrameSource
    value: T
    timestamp: float


class ClaimEngine[T]:
    """PresenceEngine generalized. STUB — Phase 0 FULL implements bodies."""

    def __init__(
        self,
        name: str,
        prior: float,
        temporal_profile: TemporalProfile,
        signal_weights: dict[str, LRDerivation],
    ) -> None:
        raise NotImplementedError("Phase 0 FULL")

    def update(self, signal_name: str, value: T) -> None:
        raise NotImplementedError("Phase 0 FULL")

    @property
    def posterior(self) -> float:
        raise NotImplementedError("Phase 0 FULL")

    @property
    def state(self) -> Literal["ASSERTED", "UNCERTAIN", "RETRACTED"]:
        raise NotImplementedError("Phase 0 FULL")


class InferenceBroker:
    """5060 Ti co-residency broker for PaddleOCR + SigLIP2 (Phase 2b).

    STUB — Phase 2b implementation. Queues classifier requests, enforces
    VRAM budget, and serializes access to shared models.
    """

    def __init__(self, vram_budget_gb: float = 12.0) -> None:
        raise NotImplementedError("Phase 2b")


__all__ = [
    "Claim",
    "ClaimComposition",
    "ClaimEngine",
    "CompositionOp",
    "Domain",
    "EvidenceRef",
    "FrameSource",
    "InferenceBroker",
    "LRDerivation",
    "LRSourceCategory",
    "PriorProvenance",
    "PriorSource",
    "Signal",
    "TemporalProfile",
]
