"""Voice-embedding ducking gate — audio-pathways Phase 3 (#134).

Pure-decision helper for the phantom-VAD remediation. The VAD frame
processor calls ``should_duck(vad_active, embedding_match)`` to decide
whether a VAD-fired event represents the operator (duck) or YouTube
crossfeed / other non-operator voice (no duck).

Spec docs/superpowers/specs/2026-04-18-audio-pathways-audit-design.md
§3.2 + plan §lines 140-152. Thresholds:

  embedding_match >= 0.75 → duck (high confidence operator speech)
  0.4 <= embedding_match < 0.75 → duck with caveat (low confidence)
  embedding_match < 0.4 → no duck, phantom VAD

The thresholds live as module-level constants so ablation studies can
flip them via env override; the spec values are the validated defaults.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

log = logging.getLogger(__name__)


# Spec §6 line 124: 0.75 = high-confidence operator speech.
HIGH_CONFIDENCE_THRESHOLD = float(os.environ.get("HAPAX_VOICE_GATE_HIGH_THRESHOLD", "0.75"))
# Below this, the gate refuses to duck — the audio almost certainly
# isn't the operator. Phantom-VAD detection lives below this line.
PHANTOM_THRESHOLD = float(os.environ.get("HAPAX_VOICE_GATE_PHANTOM_THRESHOLD", "0.4"))


DuckReason = Literal[
    "vad_and_embedding",  # high-confidence: VAD + embedding >= 0.75
    "vad_only_fallback",  # low-confidence: VAD + 0.4 <= embedding < 0.75
    "no_duck_phantom",  # phantom: VAD + embedding < 0.4
    "no_duck_silent",  # VAD did not fire
]


@dataclass(frozen=True)
class DuckDecision:
    """Result of a single ducking-trigger evaluation."""

    duck: bool
    reason: DuckReason
    embedding_match: float


def should_duck(
    vad_active: bool,
    embedding_match: float,
    *,
    high_threshold: float = HIGH_CONFIDENCE_THRESHOLD,
    phantom_threshold: float = PHANTOM_THRESHOLD,
) -> DuckDecision:
    """Compose the ducking decision from VAD + embedding match.

    The ``embedding_match`` is the cosine similarity (in ``[-1, 1]``,
    typically ``[0, 1]`` for voice embeddings) between the audio
    window's voice embedding and the enrolled operator embedding.
    Caller computes via ``SpeakerIdentifier.identify``.
    """
    if not vad_active:
        return DuckDecision(duck=False, reason="no_duck_silent", embedding_match=embedding_match)
    if embedding_match >= high_threshold:
        return DuckDecision(duck=True, reason="vad_and_embedding", embedding_match=embedding_match)
    if embedding_match >= phantom_threshold:
        return DuckDecision(duck=True, reason="vad_only_fallback", embedding_match=embedding_match)
    return DuckDecision(duck=False, reason="no_duck_phantom", embedding_match=embedding_match)


# Optional emit-on-decision hook — caller injects the real
# observability emit so this module stays prometheus-free.
EmitFn = Callable[[str], None]


def evaluate_and_emit(
    vad_active: bool,
    embedding_match: float,
    *,
    emit: EmitFn | None = None,
    high_threshold: float = HIGH_CONFIDENCE_THRESHOLD,
    phantom_threshold: float = PHANTOM_THRESHOLD,
) -> DuckDecision:
    """``should_duck`` + observability emit. Convenience wrapper for
    callers that wire the gate into the VAD pipeline."""
    decision = should_duck(
        vad_active,
        embedding_match,
        high_threshold=high_threshold,
        phantom_threshold=phantom_threshold,
    )
    if emit is not None and decision.reason != "no_duck_silent":
        try:
            emit(decision.reason)
        except Exception:
            log.debug("voice gate emit failed", exc_info=True)
    return decision


__all__ = [
    "HIGH_CONFIDENCE_THRESHOLD",
    "PHANTOM_THRESHOLD",
    "DuckDecision",
    "DuckReason",
    "EmitFn",
    "evaluate_and_emit",
    "should_duck",
]
