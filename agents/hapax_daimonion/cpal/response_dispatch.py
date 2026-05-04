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
import time
from collections.abc import Callable
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
from shared.segment_observability import (
    QualityRating,
    SegmentRecorder,
)

log = logging.getLogger(__name__)


CHAT_RESPONSE_SEGMENT_ROLE: str = "chat_response"
"""``programme_role`` label used for chat-response segment events.

Segment-observability ``programme_role`` is documented as a
``ProgrammeRole`` value, but its docstring example uses a free-form
label (``"vocal_only"``). Chat-response is impingement-driven and
spans whatever programme is active at dispatch time, so it gets its
own sentinel rather than the active programme role — the chat-
response outcome rubric is what matters for telemetry, not which
programme happened to be running.
"""

TIMELY_CHAT_LATENCY_S: float = 3.0
"""Per cc-task ``chat-response-verbal-and-text`` acceptance: Hapax
posts text reply within 3s of impingement-driven decision. Above this
threshold a successful post is graded ``ACCEPTABLE`` rather than
``GOOD`` to surface conversational pacing degradation in operator
telemetry."""


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


def _grade_chat_response(
    *,
    modality: ResponseModality,
    audio_decision: VoicePlaybackDecision | None,
    chat_result: PublisherResult | None,
    elapsed_s: float,
    placeholder_substituted: bool,
    timely_latency_s: float = TIMELY_CHAT_LATENCY_S,
) -> tuple[QualityRating, str]:
    """Score a chat-response dispatch on the four-bucket smoke rubric.

    * ``UNMEASURED`` — chat path was not exercised (DROP modality, or
      reader unavailable / no broadcast active). Verbal-only dispatches
      land here for the chat-response dimension; their voice quality is
      the vocal outcome's responsibility, not this rubric.
    * ``POOR`` — chat post attempted and refused or errored (rate-limit
      drop, allowlist deny, legal-name leak guard, or transport error).
      The post never landed.
    * ``ACCEPTABLE`` — chat post landed but elapsed end-to-end latency
      exceeded ``timely_latency_s``. Reaches viewers but with degraded
      conversational pacing.
    * ``GOOD`` — chat post landed within the timely-latency target.
      Either text-only or paired-TTS.
    * ``EXCELLENT`` — chat post landed within target AND the
      ``{operator}`` placeholder was successfully moderated AND the
      paired TTS modality fired alongside (BOTH-modality success).
      Full dual-modality response inside the target window.
    """
    notes_parts: list[str] = [
        f"modality={modality.value}",
        f"latency={elapsed_s:.3f}s",
    ]

    if chat_result is None:
        notes_parts.append("chat path not exercised")
        return QualityRating.UNMEASURED, "; ".join(notes_parts)

    if not chat_result.ok:
        outcome = "refused" if chat_result.refused else "error"
        notes_parts.append(f"chat {outcome}: {chat_result.detail}")
        return QualityRating.POOR, "; ".join(notes_parts)

    if elapsed_s > timely_latency_s:
        notes_parts.append(f"latency exceeded {timely_latency_s}s timely target")
        return QualityRating.ACCEPTABLE, "; ".join(notes_parts)

    audio_ok = audio_decision is not None and audio_decision.allowed
    if modality == ResponseModality.BOTH and placeholder_substituted and audio_ok:
        notes_parts.append("dual-modality + moderation in window")
        return QualityRating.EXCELLENT, "; ".join(notes_parts)

    notes_parts.append("timely chat post")
    return QualityRating.GOOD, "; ".join(notes_parts)


def _record_chat_response_segment(
    *,
    impingement_id: str | None,
    quality: QualityRating,
    notes: str,
    log_path: Path | None,
) -> None:
    """Best-effort segment record for a chat-response dispatch.

    Swallows file-I/O errors so dispatch never raises due to telemetry
    infrastructure. Per cc-task ``chat-response-segment-smoke``: smoke
    recording is non-load-bearing observability — losing a record is
    preferable to losing the chat response itself.
    """
    try:
        with SegmentRecorder(
            CHAT_RESPONSE_SEGMENT_ROLE,
            topic_seed=impingement_id,
            log_path=log_path,
        ) as event:
            event.quality.chat_response = quality
            event.quality.notes = notes
    except OSError as exc:
        log.warning("segment_recorder I/O failed: %s", exc)
    except Exception:  # noqa: BLE001 — best-effort, never propagate
        log.debug("segment_recorder unexpected error", exc_info=True)


def dispatch_response(
    impingement: Any,
    *,
    publisher: YoutubeLiveChatPublisher | None = None,
    attribution: bool = True,
    private_monitor_status_path: Path | None = None,
    broadcast_audio_health_path: Path | None = None,
    segment_log_path: Path | None = None,
    now_clock: Callable[[], float] | None = None,
    timely_latency_s: float = TIMELY_CHAT_LATENCY_S,
) -> ResponseDispatch:
    """Dispatch the response for ``impingement`` per its modality.

    See module docstring for behavior. Always returns; never raises.

    Each dispatch records exactly one segment via
    :class:`shared.segment_observability.SegmentRecorder`; the segment's
    ``quality.chat_response`` carries the verdict from
    :func:`_grade_chat_response`. Segment recording is best-effort —
    a logging-or-file-I/O failure does not break the dispatch path.

    ``now_clock`` is a test-injection seam for latency assertions;
    defaults to :func:`time.monotonic`. Two reads bracket the work and
    the elapsed delta drives the timely / acceptable threshold.
    """
    clock = now_clock or time.monotonic
    started = clock()

    modality = classify_response_modality(impingement)

    audio_decision: VoicePlaybackDecision | None = None
    chat_result: PublisherResult | None = None
    skip_reason: str | None = None
    placeholder_substituted = False

    if modality in {ResponseModality.VERBAL, ResponseModality.BOTH}:
        kwargs: dict[str, Any] = {}
        if private_monitor_status_path is not None:
            kwargs["private_monitor_status_path"] = private_monitor_status_path
        if broadcast_audio_health_path is not None:
            kwargs["broadcast_audio_health_path"] = broadcast_audio_health_path
        audio_decision = resolve_playback_decision(impingement, **kwargs)

    impingement_id: str | None = None

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
                raw_text = content.get("response_text", "")
                impingement_id = content.get("impingement_id")
                placeholder_substituted = (
                    isinstance(raw_text, str) and OPERATOR_PLACEHOLDER in raw_text
                )
                # Moderation pass — substitute {operator} placeholder with the
                # sticky referent. Runs unconditionally (independent of
                # attribution) because the placeholder is a contract between
                # Hapax's narrative LLM and the moderation layer; ignoring it
                # would leak the literal token into chat.
                text = moderate_chat_text(raw_text, impingement_id=impingement_id)
                if attribution:
                    text = _sign_for_chat(text, impingement_id=impingement_id)
                pub = publisher or YoutubeLiveChatPublisher()
                chat_result = pub.publish(PublisherPayload(target=chat_id, text=text))

    if impingement_id is None:
        content = getattr(impingement, "content", {}) or {}
        impingement_id = content.get("impingement_id") if isinstance(content, dict) else None

    elapsed_s = clock() - started
    quality, notes = _grade_chat_response(
        modality=modality,
        audio_decision=audio_decision,
        chat_result=chat_result,
        elapsed_s=elapsed_s,
        placeholder_substituted=placeholder_substituted,
        timely_latency_s=timely_latency_s,
    )
    _record_chat_response_segment(
        impingement_id=impingement_id,
        quality=quality,
        notes=notes,
        log_path=segment_log_path,
    )

    return ResponseDispatch(
        modality=modality,
        audio_decision=audio_decision,
        chat_result=chat_result,
        skip_reason=skip_reason,
    )


__all__ = [
    "CHAT_RESPONSE_SEGMENT_ROLE",
    "OPERATOR_PLACEHOLDER",
    "ResponseDispatch",
    "TIMELY_CHAT_LATENCY_S",
    "dispatch_response",
    "moderate_chat_text",
]
