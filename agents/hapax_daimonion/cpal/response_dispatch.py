"""Response dispatcher — modality classification → parallel verbal+chat emit.

The single load-bearing entry point is :func:`dispatch_response`. It:

1. Classifies the impingement's response modality
   (:func:`classify_response_modality`).
2. For VERBAL or BOTH: resolves the existing audio playback decision
   via ``destination_channel.resolve_playback_decision`` so the Evil
   Pet broadcast TTS path is reused untouched.
3. For TEXT_CHAT or BOTH: posts via
   :class:`YoutubeLiveChatPublisher` using the active reader's
   ``live_chat_id()``. Skips silently when no reader is registered
   (epsilon's lane has not yet shipped or no broadcast is active).
4. Returns a :class:`ResponseDispatch` envelope so callers can
   observe both decisions without re-classifying.

Operator-referent attribution: when ``attribution=True`` (default),
the chat text is signed with one of the four equally-weighted
referents picked stickily per ``impingement_id``. Legal name never
appears — the publisher's legal-name-leak guard would refuse the
publish if it did, so this is belt-and-suspenders.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.hapax_daimonion.cpal.chat_destination import (
    ResponseModality,
    classify_response_modality,
)
from agents.hapax_daimonion.cpal.destination_channel import (
    VoicePlaybackDecision,
    resolve_playback_decision,
)
from agents.publication_bus.publisher_kit.base import (
    PublisherPayload,
    PublisherResult,
)
from agents.publication_bus.youtube_live_chat_publisher import (
    YoutubeLiveChatPublisher,
)
from agents.youtube_chat_reader import get_active_reader
from shared.operator_referent import OperatorReferentPicker

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResponseDispatch:
    """Envelope describing the outcome of dispatching a response.

    ``audio_decision`` is set when the modality includes verbal — even
    if the playback decision is BLOCKED, the caller still gets the
    decision back for telemetry. ``chat_result`` is set when the chat
    POST was attempted; ``skip_reason`` is set when the chat path was
    skipped (no reader / drop modality / etc.) so callers can
    distinguish "tried and failed" from "did not try".
    """

    modality: ResponseModality
    audio_decision: VoicePlaybackDecision | None = None
    chat_result: PublisherResult | None = None
    skip_reason: str | None = None


OPERATOR_PLACEHOLDER: str = "{operator}"
"""Token Hapax's narrative LLM may emit when it wants the moderation
layer to pick the operator referent stickily for the impingement.

Substituted by :func:`moderate_chat_text` with one of the four
ratified non-formal referents (``shared/operator_referent.REFERENTS``)
so the legal name never appears in chat output. Pre-substituted text
is also forwarded to the publisher's legal-name-leak guard, which
refuses any post whose body literally contains the operator's legal
name pattern (``HAPAX_OPERATOR_NAME``).
"""


def moderate_chat_text(text: str, *, impingement_id: str | None) -> str:
    """Apply non-formal operator-referent policy to outgoing chat text.

    Substitutes any occurrence of :data:`OPERATOR_PLACEHOLDER` with a
    sticky operator referent picked via
    :class:`OperatorReferentPicker`. Same ``impingement_id`` always
    picks the same referent so verbal and text channels of a single
    response read consistently and the same impingement quoted twice
    on chat reads identically.

    Returns the moderated text. Never raises; if no placeholder is
    present the text is returned unchanged. The publisher's
    legal-name-leak guard runs separately and refuses any post whose
    body still contains the literal operator legal name after
    moderation — moderation is a substitution layer, not a
    sanitization gate.
    """
    seed = f"impingement-{impingement_id}" if impingement_id else None
    referent = OperatorReferentPicker.pick(seed)
    return text.replace(OPERATOR_PLACEHOLDER, referent)


def _sign_for_chat(text: str, *, impingement_id: str | None) -> str:
    """Append a sticky operator referent to ``text``.

    Sticky-per-impingement: same impingement_id always picks the same
    referent so a multi-modal response (verbal + chat) reads
    consistently. Caller-controlled via ``attribution=True``.

    Composes with :func:`moderate_chat_text` (placeholder substitution
    runs first; signing appends the suffix). Both use the same seed,
    so the suffix referent matches any in-body referent that came from
    the placeholder.
    """
    seed = f"impingement-{impingement_id}" if impingement_id else None
    referent = OperatorReferentPicker.pick(seed)
    return f"{text} — {referent}"


def dispatch_response(
    impingement: Any,
    *,
    publisher: YoutubeLiveChatPublisher | None = None,
    attribution: bool = True,
    private_monitor_status_path: Path | None = None,
    broadcast_audio_health_path: Path | None = None,
) -> ResponseDispatch:
    """Dispatch the response for ``impingement`` per its modality.

    See module docstring for behavior. Always returns; never raises.
    """
    modality = classify_response_modality(impingement)

    audio_decision: VoicePlaybackDecision | None = None
    chat_result: PublisherResult | None = None
    skip_reason: str | None = None

    if modality in {ResponseModality.VERBAL, ResponseModality.BOTH}:
        kwargs: dict[str, Any] = {}
        if private_monitor_status_path is not None:
            kwargs["private_monitor_status_path"] = private_monitor_status_path
        if broadcast_audio_health_path is not None:
            kwargs["broadcast_audio_health_path"] = broadcast_audio_health_path
        audio_decision = resolve_playback_decision(impingement, **kwargs)

    if modality in {ResponseModality.TEXT_CHAT, ResponseModality.BOTH}:
        reader = get_active_reader()
        if reader is None:
            skip_reason = "no_reader_registered"
        else:
            try:
                chat_id = reader.live_chat_id()
            except Exception as exc:  # noqa: BLE001 — reader stub may raise
                log.info("chat post skipped: live_chat_id unavailable (%s)", exc)
                skip_reason = "live_chat_id_unavailable"
            else:
                content = getattr(impingement, "content", {}) or {}
                text = content.get("response_text", "")
                impingement_id = content.get("impingement_id")
                # Moderation pass — substitute {operator} placeholder with the
                # sticky referent. Runs unconditionally (independent of
                # attribution) because the placeholder is a contract between
                # Hapax's narrative LLM and the moderation layer; ignoring it
                # would leak the literal token into chat.
                text = moderate_chat_text(text, impingement_id=impingement_id)
                if attribution:
                    text = _sign_for_chat(text, impingement_id=impingement_id)
                pub = publisher or YoutubeLiveChatPublisher()
                chat_result = pub.publish(PublisherPayload(target=chat_id, text=text))

    return ResponseDispatch(
        modality=modality,
        audio_decision=audio_decision,
        chat_result=chat_result,
        skip_reason=skip_reason,
    )


__all__ = [
    "OPERATOR_PLACEHOLDER",
    "ResponseDispatch",
    "dispatch_response",
    "moderate_chat_text",
]
