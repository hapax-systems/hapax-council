"""Dual-channel chat response dispatch — verbal (TTS) + text-back (YouTube).

When the daimonion generates a response to a chat message, this module
dispatches it through both channels:
1. TTS synthesis for verbal broadcast
2. YouTube Live Chat API for text-back in the chat

Either channel can be independently disabled or fail without blocking
the other. The verbal channel is primary; text-back is secondary.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

_log = logging.getLogger(__name__)


class ResponseChannel(StrEnum):
    VERBAL = "verbal"
    TEXT_BACK = "text_back"
    BOTH = "both"


@dataclass(frozen=True)
class DispatchResult:
    verbal_sent: bool = False
    text_back_sent: bool = False
    verbal_error: str | None = None
    text_back_error: str | None = None

    @property
    def any_sent(self) -> bool:
        return self.verbal_sent or self.text_back_sent


async def dispatch_chat_response(
    text: str,
    *,
    channel: ResponseChannel = ResponseChannel.BOTH,
    live_chat_id: str | None = None,
) -> DispatchResult:
    """Dispatch a chat response through verbal and/or text-back channels.

    Fail-independent: each channel can fail without blocking the other.
    """
    verbal_sent = False
    verbal_error = None
    text_back_sent = False
    text_back_error = None

    if channel in (ResponseChannel.VERBAL, ResponseChannel.BOTH):
        try:
            from agents.hapax_daimonion.conversation_pipeline import synthesize_and_play

            await synthesize_and_play(text)
            verbal_sent = True
        except Exception as e:
            verbal_error = str(e)
            _log.warning("Verbal dispatch failed: %s", e)

    if channel in (ResponseChannel.TEXT_BACK, ResponseChannel.BOTH):
        if not live_chat_id:
            text_back_error = "no live_chat_id"
        else:
            try:
                from agents.publication_bus.youtube_live_chat_publisher import (
                    YoutubeLiveChatPublisher,
                )

                publisher = YoutubeLiveChatPublisher()
                result = await publisher.publish(
                    content=text,
                    metadata={"liveChatId": live_chat_id},
                )
                text_back_sent = not result.refused
                if result.refused:
                    text_back_error = result.reason_code or "refused"
            except Exception as e:
                text_back_error = str(e)
                _log.warning("Text-back dispatch failed: %s", e)

    return DispatchResult(
        verbal_sent=verbal_sent,
        text_back_sent=text_back_sent,
        verbal_error=verbal_error,
        text_back_error=text_back_error,
    )
