"""Chat-destination + response-modality types for CPAL.

Sister module to ``destination_channel.py``. The audio router there
classifies utterances as LIVESTREAM / PRIVATE; this module classifies
*responses* (text+audio together) as VERBAL / TEXT_CHAT / BOTH / DROP.

The two surfaces are intentionally parallel rather than merged so the
existing Evil Pet broadcast TTS path remains untouched (per directive
"no DRY, broadcast TTS via Evil Pet path"). When the modality is
``VERBAL`` or ``BOTH`` callers reuse the existing
``resolve_playback_decision()`` audio path; only the chat post is new.

Classification rules (first match wins):

1. ``content["response_modality_hint"]`` is a valid ResponseModality value → that.
2. Impingement source is not chat AND has non-empty response_text → VERBAL.
3. Source is chat AND response_text empty/missing → DROP.
4. Source is chat AND len(response_text) <= ``SHORT_RESPONSE_CHAR_LIMIT`` → TEXT_CHAT.
5. Source is chat AND len(response_text) > limit → VERBAL.
6. Anything else → DROP.

The threshold ``SHORT_RESPONSE_CHAR_LIMIT`` = 140 matches the
chat-task spec.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

log = logging.getLogger(__name__)

SHORT_RESPONSE_CHAR_LIMIT: int = 140
"""Per cc-task: short reply (<140 chars) → text-back; longer → vocal."""

CHAT_SOURCE_PREFIXES: tuple[str, ...] = ("youtube.live_chat", "chat.")
"""Impingement-source prefixes that mark a chat-origin event."""


class ChatDestination(StrEnum):
    """Where a chat-text response is posted."""

    YOUTUBE_LIVE_CHAT = "youtube_live_chat"


class ResponseModality(StrEnum):
    """How an impingement's response is delivered.

    ``VERBAL`` — TTS only (existing Evil Pet broadcast / private path).
    ``TEXT_CHAT`` — chat post only.
    ``BOTH`` — TTS and chat post in parallel for the same response_text.
    ``DROP`` — no response (default fail-closed).
    """

    VERBAL = "verbal"
    TEXT_CHAT = "text_chat"
    BOTH = "both"
    DROP = "drop"


def _is_chat_source(source: object) -> bool:
    if not isinstance(source, str):
        return False
    return any(source.startswith(p) for p in CHAT_SOURCE_PREFIXES)


def _hinted_modality(content: dict[str, Any]) -> ResponseModality | None:
    hint = content.get("response_modality_hint")
    if not isinstance(hint, str):
        return None
    try:
        return ResponseModality(hint)
    except ValueError:
        return None


def classify_response_modality(impingement: Any) -> ResponseModality:
    """Pick the response delivery modality for ``impingement``.

    Returns ``ResponseModality.DROP`` for malformed inputs so callers
    fail closed (no response is preferable to a misrouted one).
    """
    if impingement is None:
        return ResponseModality.DROP
    content = getattr(impingement, "content", None)
    if not isinstance(content, dict):
        return ResponseModality.DROP

    hinted = _hinted_modality(content)
    if hinted is not None:
        return hinted

    response_text = content.get("response_text")
    has_text = isinstance(response_text, str) and bool(response_text.strip())

    source = getattr(impingement, "source", "") or ""
    chat_origin = _is_chat_source(source)

    if not chat_origin:
        return ResponseModality.VERBAL if has_text else ResponseModality.DROP

    if not has_text:
        return ResponseModality.DROP
    if len(response_text) <= SHORT_RESPONSE_CHAR_LIMIT:
        return ResponseModality.TEXT_CHAT
    return ResponseModality.VERBAL


__all__ = [
    "CHAT_SOURCE_PREFIXES",
    "SHORT_RESPONSE_CHAR_LIMIT",
    "ChatDestination",
    "ResponseModality",
    "classify_response_modality",
]
