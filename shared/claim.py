"""Universal Bayesian Claim-Confidence — Phase 0 FULL.

Phase 0 STUB shipped the frozen signatures (#1341); this lands the
implementation. ``ClaimEngine[bool]`` mirrors PresenceEngine's log-odds
posterior + hysteresis state machine, generalized over an arbitrary
binary perceptual claim. Phase 1 refactors PresenceEngine itself onto
this engine with a bit-identical regression pin.

Research foundation: ``docs/research/2026-04-24-universal-bayesian-claim-confidence.md``.

Kill-switch: ``HAPAX_BAYESIAN_BYPASS=1`` makes ``ClaimEngine.update`` a
no-op and ``posterior`` returns the configured prior. Restores
pre-Phase-0 routing for emergency rollback while the deployment is
inflight.
"""

from __future__ import annotations

import math
import os
from typing import Literal

from pydantic import BaseModel, Field

# Fail-closed env name; "1" enables, anything else disables.
_BYPASS_ENV = "HAPAX_BAYESIAN_BYPASS"


def _bypass_active() -> bool:
    """True if the kill-switch env var is set to a truthy value (case-insensitive)."""
    return os.environ.get(_BYPASS_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


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
    """Per-claim temporal dynamics. Presence: fast-enter/slow-exit. Music: inverted.

    `k_uncertain` is the tick-dwell count for transitions involving the
    intermediate UNCERTAIN state (UNCERTAIN→ASSERTED uses k_enter,
    ASSERTED→{UNCERTAIN,RETRACTED} uses k_exit, but UNCERTAIN→RETRACTED
    and RETRACTED→UNCERTAIN use this third value). Defaults to 4 so
    PresenceEngine's existing behavior carries through bit-identical
    when refactored onto this engine in Phase 1.

    BOCD changepoint detection (research §6) is deferred to Phase 7.
    The previously-declared `bocd_hazard: float | None` field was never
    consumed (AUDIT-09); removed in v4 audit-incorporated cycle. When
    Phase 7 lands, BOCD support enters via a separate optional field
    + an opt-in code path in `_required_ticks_for_transition` that
    reads the live posterior-changepoint probability instead of fixed
    dwell counts.
    """

    enter_threshold: float = Field(ge=0.0, le=1.0)
    exit_threshold: float = Field(ge=0.0, le=1.0)
    k_enter: int = Field(ge=1)
    k_exit: int = Field(ge=1)
    k_uncertain: int = Field(default=4, ge=1)


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


ClaimState = Literal["ASSERTED", "UNCERTAIN", "RETRACTED"]


class ClaimEngine[T]:
    """Generic Bayesian claim posterior + hysteresis state machine.

    Mirrors PresenceEngine's math (log-odds prior + per-signal LR fusion,
    drift-toward-prior decay, sigmoid back to probability) with two
    generalizations:

    1. Per-claim asymmetric ``TemporalProfile`` (presence: fast-enter,
       slow-exit; music: slow-enter, fast-exit — research §6).
    2. ``LRDerivation``-driven likelihood ratios (provenance, not bare
       tuples — research §5).

    Bypass: when ``HAPAX_BAYESIAN_BYPASS=1`` is set, ``update`` is a
    no-op and ``posterior`` returns the configured prior. State stays
    ``UNCERTAIN``. Designed as the single rollback knob for the entire
    Bayesian layer.

    Phase 1 refactors PresenceEngine onto this engine with a bit-identical
    regression pin against shipped output for 100 ticks of replay data.
    """

    def __init__(
        self,
        name: str,
        prior: float,
        temporal_profile: TemporalProfile,
        signal_weights: dict[str, LRDerivation],
        *,
        decay_rate: float = 0.02,
    ) -> None:
        if not 0.0 < prior < 1.0:
            raise ValueError(f"prior must be in (0, 1); got {prior}")
        self._name = name
        self._prior = prior
        self._profile = temporal_profile
        self._signal_weights = dict(signal_weights)
        self._decay_rate = decay_rate

        # Mutable state
        self._posterior: float = prior
        self._observations: dict[str, T | None] = {}
        self._state: ClaimState = "UNCERTAIN"
        self._candidate_state: ClaimState | None = None
        self._ticks_in_candidate_state: int = 0

    # ── Mutation ─────────────────────────────────────────────────────

    def update(self, signal_name: str, value: T) -> None:
        """Record an observation and recompute posterior + state.

        ``value`` is whatever the signal produces for this claim. For
        ``ClaimEngine[bool]`` it's True/False/None (None means "no
        evidence this tick"; the signal is skipped by the log-odds
        update — positive-only signals use this for absence).
        """
        if _bypass_active():
            return
        self._observations[signal_name] = value
        self._posterior = self._compute_posterior()
        self._update_state_machine(self._posterior)

    def tick(self, observations: dict[str, T | None]) -> None:
        """Atomic batch tick: set all observations at once + single state update.

        Mirrors PresenceEngine's per-tick semantics where multiple signals
        are observed together and the state machine ticks once per tick.
        Use this in preference to repeated ``update()`` calls when the
        observations represent a single perceptual moment.
        """
        if _bypass_active():
            return
        self._observations.update(observations)
        self._posterior = self._compute_posterior()
        self._update_state_machine(self._posterior)

    def reset(self) -> None:
        """Discard accumulated observations, return to prior."""
        self._observations.clear()
        self._posterior = self._prior
        self._state = "UNCERTAIN"
        self._candidate_state = None
        self._ticks_in_candidate_state = 0

    # ── Computation ──────────────────────────────────────────────────

    def _compute_posterior(self) -> float:
        """Bayesian log-odds fusion. Mirrors PresenceEngine._compute_posterior."""
        # Drift toward prior so stale evidence decays
        prior = self._posterior + (self._prior - self._posterior) * self._decay_rate
        prior = max(0.001, min(0.999, prior))
        log_odds = math.log(prior / (1.0 - prior))

        for signal_name, lr_record in self._signal_weights.items():
            observed = self._observations.get(signal_name)
            if observed is None:
                continue
            p_present = lr_record.p_true_given_h1
            p_absent = lr_record.p_true_given_h0
            if observed:
                lr = p_present / max(p_absent, 1e-12)
            else:
                if lr_record.positive_only:
                    # Positive-only signals don't contribute on False
                    continue
                lr = (1.0 - p_present) / max(1.0 - p_absent, 1e-12)
            log_odds += math.log(max(lr, 1e-12))

        try:
            posterior = 1.0 / (1.0 + math.exp(-log_odds))
        except OverflowError:
            posterior = 0.0 if log_odds < 0 else 1.0
        return max(0.0, min(1.0, posterior))

    def _update_state_machine(self, posterior: float) -> None:
        """Hysteresis: posterior threshold + sustained-tick dwell."""
        target: ClaimState
        if posterior >= self._profile.enter_threshold:
            target = "ASSERTED"
        elif posterior < self._profile.exit_threshold:
            target = "RETRACTED"
        else:
            target = "UNCERTAIN"

        if target == self._state:
            self._candidate_state = None
            self._ticks_in_candidate_state = 0
            return

        if target == self._candidate_state:
            self._ticks_in_candidate_state += 1
        else:
            self._candidate_state = target
            self._ticks_in_candidate_state = 1

        required = self._required_ticks_for_transition(self._state, target)
        if self._ticks_in_candidate_state >= required:
            self._state = target
            self._candidate_state = None
            self._ticks_in_candidate_state = 0

    def _required_ticks_for_transition(self, frm: ClaimState, to: ClaimState) -> int:
        """Asymmetric per-claim dwell from TemporalProfile.

        Mirrors PresenceEngine._required_ticks_for_transition exactly so
        the Phase 1 PresenceEngine refactor onto this engine is
        bit-identical. UNCERTAIN-state transitions use k_uncertain.
        """
        if to == "ASSERTED":
            return self._profile.k_enter
        if frm == "ASSERTED" and to in ("UNCERTAIN", "RETRACTED"):
            return self._profile.k_exit
        # UNCERTAIN ↔ RETRACTED transitions use the dedicated dwell
        return self._profile.k_uncertain

    # ── Read accessors ───────────────────────────────────────────────

    @property
    def name(self) -> str:
        return self._name

    @property
    def posterior(self) -> float:
        if _bypass_active():
            return self._prior
        return self._posterior

    @property
    def state(self) -> ClaimState:
        if _bypass_active():
            return "UNCERTAIN"
        return self._state

    @property
    def temporal_profile(self) -> TemporalProfile:
        return self._profile


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
    "ClaimState",
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
