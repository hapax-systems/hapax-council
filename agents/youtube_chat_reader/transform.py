"""Pure transforms: ``liveChatMessages.list`` item → bus + state records.

Kept pure so the reader loop can unit-test the entire transform without
touching the YouTube API or the filesystem. The reader hands an item
dict (the YouTube response shape) plus an :class:`AuthorAnonymizer`
and gets back the two records that ship to disk.

Both records share the same canonical fields (``message_id``,
``author_token``, ``text``, structural signals) so a downstream
consumer reading either surface can correlate without round-tripping
through both files.
"""

from __future__ import annotations

import time
from typing import Any

from agents.youtube_chat_reader.anonymize import AuthorAnonymizer
from agents.youtube_chat_reader.sanitize import extract_signals, sanitize_message

__all__ = [
    "BASE_STRENGTH",
    "MENTION_STRENGTH_BONUS",
    "QUESTION_STRENGTH_BONUS",
    "build_bus_record",
    "build_state_record",
    "extract_published_at_ts",
    "interrupt_token_for",
]

BASE_STRENGTH = 0.45
QUESTION_STRENGTH_BONUS = 0.10
MENTION_STRENGTH_BONUS = 0.15
SOURCE_TAG = "youtube_chat"


def interrupt_token_for(signals: dict[str, Any]) -> str:
    """Pick the most informative interrupt token for the affordance pipeline.

    Mention takes precedence over question because it is rarer and
    higher-priority for response (operator/channel was directly
    addressed). Commands ride on top because they encode an explicit
    intent. Falls back to plain ``chat_message`` so the family-prefix
    routing still narrows the candidate set.
    """
    if signals.get("is_command"):
        return "chat_command"
    if signals.get("has_mention"):
        return "chat_mention"
    if signals.get("has_question"):
        return "chat_question"
    return "chat_message"


def _strength_for(signals: dict[str, Any]) -> float:
    """Compose the impingement strength from signal flags.

    Capped at 1.0 to satisfy the :class:`Impingement` field validator.
    """
    strength = BASE_STRENGTH
    if signals.get("has_mention"):
        strength += MENTION_STRENGTH_BONUS
    if signals.get("has_question"):
        strength += QUESTION_STRENGTH_BONUS
    return min(1.0, strength)


def extract_published_at_ts(item: dict[str, Any], *, fallback: float | None = None) -> float:
    """Return the message's publishedAt as a unix timestamp.

    YouTube returns RFC3339 strings (``2026-05-04T02:31:14.123456Z``).
    Failure to parse falls back to ``fallback`` (defaults to wall-clock
    now) so a malformed item never blocks the pipeline.
    """
    snippet = item.get("snippet") or {}
    raw = snippet.get("publishedAt")
    if not raw:
        return fallback if fallback is not None else time.time()
    try:
        from datetime import datetime

        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return fallback if fallback is not None else time.time()


def _author_id(item: dict[str, Any]) -> str | None:
    """Pull the YouTube channelId from a chat item, or None."""
    author_details = item.get("authorDetails") or {}
    return author_details.get("channelId")


def _message_text(item: dict[str, Any]) -> str:
    """Pull the displayed message text from a chat item."""
    snippet = item.get("snippet") or {}
    return snippet.get("displayMessage") or ""


def build_bus_record(
    item: dict[str, Any],
    *,
    anonymizer: AuthorAnonymizer,
    broadcast_id: str | None = None,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Compose the impingement-bus record for one chat item.

    Schema follows the existing producers (``inflection_to_impingement``,
    ``youtube_telemetry.emitter``): a flat dict carrying canonical
    impingement fields plus typed content. Returns ``None`` when the
    sanitized text is empty (drop-on-empty so the bus only sees
    actionable messages).
    """
    raw_text = _message_text(item)
    clean_text = sanitize_message(raw_text)
    if not clean_text:
        return None

    signals = extract_signals(clean_text)
    author_token = anonymizer.token(_author_id(item))
    ts = extract_published_at_ts(item, fallback=now)
    message_id = item.get("id") or f"chat-{author_token}-{int(ts * 1000)}"

    narrative = (
        f"chat message arrived: {clean_text}; livestream-audience signal — author={author_token}"
    )

    return {
        "id": message_id,
        "timestamp": ts,
        "source": SOURCE_TAG,
        "type": "pattern_match",
        "strength": _strength_for(signals),
        "interrupt_token": interrupt_token_for(signals),
        "intent_family": None,
        "content": {
            "narrative": narrative,
            "metric": "chat.message",
            "author_token": author_token,
            "text": clean_text,
            "length": signals["length"],
            "has_question": signals["has_question"],
            "has_mention": signals["has_mention"],
            "is_command": signals["is_command"],
            "broadcast_id": broadcast_id,
        },
    }


def build_state_record(
    item: dict[str, Any],
    *,
    anonymizer: AuthorAnonymizer,
    broadcast_id: str | None = None,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Compose the chat-state-surface record for one chat item.

    Subset of the bus record sized for the 50-message ring buffer the
    compositor's chat ward consumes. Returns ``None`` on empty
    sanitization for parity with :func:`build_bus_record`.
    """
    raw_text = _message_text(item)
    clean_text = sanitize_message(raw_text)
    if not clean_text:
        return None

    signals = extract_signals(clean_text)
    author_token = anonymizer.token(_author_id(item))
    ts = extract_published_at_ts(item, fallback=now)
    message_id = item.get("id") or f"chat-{author_token}-{int(ts * 1000)}"

    return {
        "id": message_id,
        "ts": ts,
        "author_token": author_token,
        "text": clean_text,
        "length": signals["length"],
        "has_question": signals["has_question"],
        "has_mention": signals["has_mention"],
        "is_command": signals["is_command"],
        "broadcast_id": broadcast_id,
    }
