"""Operator-VAD gate (cc-task audio-audit-D-private-monitor-operator-vad-duck).

The broadcast ducker today fires on any VAD event from the room mic — including
non-operator voices (visitors, TV, podcast on background phone). Auditor D wants
the duck to fire only when the speaker is the operator, per a voice fingerprint
match.

Phase 0 (this module): a pure-Python decision gate that wraps an
operator-fingerprint match callable + threshold + Prometheus counter. The
fingerprint model itself (ResemBlyzer or equivalent) is *not* loaded here —
the gate accepts any callable returning a cosine similarity in [0.0, 1.0]
or None (no fingerprint loaded yet). Phase 1 wires this gate into the ducker
trigger and supplies a real ResemBlyzer-backed match function.

Why factor it this way:
- The decision logic (threshold + reason classification) is small and worth
  pinning with deterministic tests *before* introducing model-load complexity.
- The Prometheus counter labels (`is_operator="true"|"false"|"unknown"`) are a
  contract the rest of the stack will subscribe to; pinning them now means
  Phase 1 doesn't quietly break dashboards.
- The match callable signature lets a fixture-only test exercise the gate
  without any audio dependency.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from prometheus_client import Counter

OperatorVADReason = Literal[
    "match",
    "below-threshold",
    "unknown-no-fingerprint",
]
"""The three classification outcomes of the gate.

- ``match``: similarity >= match_threshold; ducker should trigger.
- ``below-threshold``: a similarity was computed but it's under the threshold;
  speech is non-operator (visitor / TV / podcast). Ducker must NOT trigger.
- ``unknown-no-fingerprint``: no operator fingerprint is loaded (cold boot,
  model swap in progress, or operator hasn't recorded a sample yet). Phase 0
  default policy is fail-OPEN (treat as operator → duck) so we never miss
  the operator's actual speech; Phase 1 may revisit if visitor false-ducks
  remain a problem during the warm-up window.
"""

# Threshold tuning notes (for Phase 1 calibration):
# - ResemBlyzer typical thresholds: 0.65 (loose) to 0.85 (strict).
# - 0.75 is the operator-recommended starting point per audit narrative.
# - Re-calibrate after collecting a fixture set of (operator, visitor) samples.
DEFAULT_MATCH_THRESHOLD: float = 0.75


@dataclass(frozen=True)
class OperatorVADDecision:
    """Outcome of a single VAD event against the operator fingerprint."""

    is_operator: bool
    confidence: float | None
    reason: OperatorVADReason

    @property
    def should_duck(self) -> bool:
        """Phase 0 policy: duck on match OR on unknown (fail-open).

        Phase 1 may flip the unknown policy to fail-closed once warm-up
        latency is measured; this property is the single read-site for the
        ducker.
        """
        return self.is_operator


# Module-level counter so multiple gate instances share a single time series.
# Labels are pinned: any future label addition is a breaking dashboard change.
hapax_vad_event_total: Counter = Counter(
    "hapax_vad_event_total",
    "VAD events seen by the operator-VAD gate, labelled by operator-match outcome",
    labelnames=("is_operator",),
)


class OperatorVADGate:
    """Decides whether a VAD event corresponds to operator speech.

    Phase 0 wraps a match callable + threshold; Phase 1 supplies a
    ResemBlyzer-backed match function and threads decisions into the
    audio-ducker trigger.
    """

    def __init__(
        self,
        match_callable: Callable[[bytes], float | None],
        *,
        match_threshold: float = DEFAULT_MATCH_THRESHOLD,
    ) -> None:
        if not 0.0 <= match_threshold <= 1.0:
            raise ValueError(
                f"match_threshold {match_threshold} outside [0.0, 1.0]; cosine similarity range"
            )
        self._match = match_callable
        self._threshold = match_threshold

    @property
    def match_threshold(self) -> float:
        """Read-only accessor; threshold is set at construction."""
        return self._threshold

    def decide(self, audio_window: bytes) -> OperatorVADDecision:
        """Classify a VAD-active audio window against the operator fingerprint.

        Returns an OperatorVADDecision and increments the matching Prometheus
        counter label. The caller (ducker) reads ``decision.should_duck``.
        """
        similarity = self._match(audio_window)

        if similarity is None:
            decision = OperatorVADDecision(
                is_operator=True,
                confidence=None,
                reason="unknown-no-fingerprint",
            )
            hapax_vad_event_total.labels(is_operator="unknown").inc()
            return decision

        if not 0.0 <= similarity <= 1.0:
            raise ValueError(
                f"match_callable returned {similarity}; cosine similarity must be in [0.0, 1.0]"
            )

        if similarity >= self._threshold:
            decision = OperatorVADDecision(
                is_operator=True,
                confidence=similarity,
                reason="match",
            )
            hapax_vad_event_total.labels(is_operator="true").inc()
            return decision

        decision = OperatorVADDecision(
            is_operator=False,
            confidence=similarity,
            reason="below-threshold",
        )
        hapax_vad_event_total.labels(is_operator="false").inc()
        return decision
