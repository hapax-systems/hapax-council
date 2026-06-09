"""Egress gate for recruited segment media (image / YouTube on OARB).

This module is the FIRST real consumer of agentgov ``Labeled[A]`` in the
media dispatch path. A recruited media ref is wrapped in a ``Labeled`` that
carries its consent label and provenance; the gate only unwraps it for
broadcast when:

1. the consent label can flow to the public broadcast sink
   (``Labeled.can_flow_to(bottom)``) — protected/PRIVATE media is refused;
2. the live stream mode is public; and
3. the working mode is fortress (broadcast media is subordinate to fortress
   gating, matching ``livestream_egress_state``).

The gate is fail-closed: any error refuses. Wiring ``Labeled`` here — with a
real consumer that checks the label before egress — is what turns the
agentgov stack from a dormant formalism into a live consent thread.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from agentgov.consent_label import ConsentLabel

from shared.governance.labeled import Labeled
from shared.stream_mode import StreamMode, get_stream_mode
from shared.working_mode import is_fortress

log = logging.getLogger(__name__)

# Broadcast is the most-public sink: only a value whose label can flow to the
# empty (public) label may be unwrapped for egress.
BROADCAST_LABEL = ConsentLabel.bottom()
_PUBLIC_STREAM_MODES = frozenset({StreamMode.PUBLIC, StreamMode.PUBLIC_RESEARCH})


class MediaEgressOutcome(StrEnum):
    ALLOWED = "allowed"
    REFUSED_CONSENT = "refused_consent"
    REFUSED_STREAM_OFF = "refused_stream_off"
    REFUSED_NOT_FORTRESS = "refused_not_fortress"
    REFUSED_ERROR = "refused_error"


@dataclass(frozen=True)
class MediaEgressDecision:
    """Outcome of gating one recruited media ref for broadcast."""

    outcome: MediaEgressOutcome
    reason: str
    media_ref: str | None = None
    media_kind: str = "unknown"

    @property
    def allowed(self) -> bool:
        return self.outcome is MediaEgressOutcome.ALLOWED


def gate_media_egress(
    media_ref: str,
    *,
    media_kind: str = "unknown",
    label: ConsentLabel | None = None,
    provenance: frozenset[str] = frozenset(),
    is_fortress_fn: Callable[[], bool] = is_fortress,
    stream_mode_fn: Callable[[], StreamMode] = get_stream_mode,
) -> MediaEgressDecision:
    """Gate a recruited media ref for broadcast egress (fail-closed)."""

    try:
        labeled: Labeled[str] = Labeled(
            value=media_ref,
            label=label if label is not None else ConsentLabel.bottom(),
            provenance=provenance,
        )
        if not labeled.can_flow_to(BROADCAST_LABEL):
            return _refused(
                MediaEgressOutcome.REFUSED_CONSENT,
                "consent label cannot flow to the public broadcast sink",
                media_kind,
            )
        stream_mode = stream_mode_fn()
        if stream_mode not in _PUBLIC_STREAM_MODES:
            return _refused(
                MediaEgressOutcome.REFUSED_STREAM_OFF,
                f"stream mode {stream_mode} is not a public broadcast mode",
                media_kind,
            )
        if not is_fortress_fn():
            return _refused(
                MediaEgressOutcome.REFUSED_NOT_FORTRESS,
                "working mode is not fortress; media egress is gated",
                media_kind,
            )
        ref = labeled.unlabel()
        _count(MediaEgressOutcome.ALLOWED, media_kind)
        return MediaEgressDecision(
            outcome=MediaEgressOutcome.ALLOWED,
            reason="consent + stream + fortress satisfied",
            media_ref=ref,
            media_kind=media_kind,
        )
    except Exception:
        log.warning("media egress gate failed closed", exc_info=True)
        return _refused(MediaEgressOutcome.REFUSED_ERROR, "gate error", media_kind)


def _refused(outcome: MediaEgressOutcome, reason: str, media_kind: str) -> MediaEgressDecision:
    _count(outcome, media_kind)
    return MediaEgressDecision(
        outcome=outcome, reason=reason, media_ref=None, media_kind=media_kind
    )


def _count(outcome: MediaEgressOutcome, media_kind: str) -> None:
    """Best-effort Prometheus counter for the egress outcome."""

    try:
        from agents.studio_compositor import metrics

        metrics.record_media_egress(outcome.value, media_kind)
    except Exception:
        log.debug("media egress counter unavailable", exc_info=True)


__all__ = [
    "BROADCAST_LABEL",
    "MediaEgressDecision",
    "MediaEgressOutcome",
    "gate_media_egress",
]
