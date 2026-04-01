"""Core types for the Conversational Perception-Action Loop."""

from __future__ import annotations

import enum
from dataclasses import dataclass


class ConversationalRegion(enum.Enum):
    """Behavioral regions defined by loop gain thresholds.

    Each region activates different capabilities in the signal repertoire.
    Transitions are continuous drift, not discrete events.
    """

    AMBIENT = "ambient"  # 0.0-0.1
    PERIPHERAL = "peripheral"  # 0.1-0.3
    ATTENTIVE = "attentive"  # 0.3-0.5
    CONVERSATIONAL = "conversational"  # 0.5-0.7
    INTENSIVE = "intensive"  # 0.7-1.0

    @property
    def threshold(self) -> float:
        """Lower bound of this region."""
        return _REGION_THRESHOLDS[self]

    @classmethod
    def from_gain(cls, gain: float) -> ConversationalRegion:
        """Map a gain value to its behavioral region."""
        if gain >= 0.7:
            return cls.INTENSIVE
        if gain >= 0.5:
            return cls.CONVERSATIONAL
        if gain >= 0.3:
            return cls.ATTENTIVE
        if gain >= 0.1:
            return cls.PERIPHERAL
        return cls.AMBIENT


_REGION_THRESHOLDS: dict[ConversationalRegion, float] = {
    ConversationalRegion.AMBIENT: 0.0,
    ConversationalRegion.PERIPHERAL: 0.1,
    ConversationalRegion.ATTENTIVE: 0.3,
    ConversationalRegion.CONVERSATIONAL: 0.5,
    ConversationalRegion.INTENSIVE: 0.7,
}


class CorrectionTier(enum.Enum):
    """Tiered corrective actions, ordered by cost and latency.

    T0: <50ms, zero computation (visual state changes)
    T1: <200ms, presynthesized audio (backchannels, acknowledgments)
    T2: <500ms, lightweight computation (echo/rephrase, discourse markers)
    T3: 3-6s, full LLM formulation (substantive response)
    """

    T0_VISUAL = "t0_visual"
    T1_PRESYNTHESIZED = "t1_presynthesized"
    T2_LIGHTWEIGHT = "t2_lightweight"
    T3_FULL_FORMULATION = "t3_full_formulation"


class ErrorDimension(enum.Enum):
    """Dimensions of conversational error."""

    COMPREHENSION = "comprehension"  # ungrounded DUs, repair frequency
    AFFECTIVE = "affective"  # declining GQI, disengagement cues
    TEMPORAL = "temporal"  # growing gap between expected and actual timing


@dataclass(frozen=True)
class ErrorSignal:
    """Multi-dimensional conversational error.

    Each dimension is 0.0 (no error) to 1.0 (maximum error).
    The control law selects corrective action based on magnitude
    and dominant dimension.
    """

    comprehension: float
    affective: float
    temporal: float

    @property
    def magnitude(self) -> float:
        """Overall error magnitude -- max of all dimensions."""
        return max(self.comprehension, self.affective, self.temporal)

    @property
    def dominant(self) -> ErrorDimension:
        """Which dimension contributes most to error."""
        vals = {
            ErrorDimension.COMPREHENSION: self.comprehension,
            ErrorDimension.AFFECTIVE: self.affective,
            ErrorDimension.TEMPORAL: self.temporal,
        }
        return max(vals, key=vals.get)  # type: ignore[arg-type]

    @property
    def suggested_tier(self) -> CorrectionTier:
        """Map error magnitude to minimum correction tier."""
        mag = self.magnitude
        if mag < 0.1:
            return CorrectionTier.T0_VISUAL
        if mag < 0.3:
            return CorrectionTier.T1_PRESYNTHESIZED
        if mag < 0.45:
            return CorrectionTier.T2_LIGHTWEIGHT
        return CorrectionTier.T3_FULL_FORMULATION


@dataclass(frozen=True)
class GainUpdate:
    """A single adjustment to loop gain with provenance."""

    delta: float  # positive = driver, negative = damper
    source: str  # e.g. "operator_speech", "silence_decay", "grounding_failure"

    @property
    def is_driver(self) -> bool:
        return self.delta > 0

    @property
    def is_damper(self) -> bool:
        return self.delta < 0
