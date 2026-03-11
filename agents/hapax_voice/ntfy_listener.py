"""ntfy listener — converts ntfy SSE events into VoiceNotifications."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable, Coroutine

import httpx

from agents.hapax_voice.notification_queue import VoiceNotification

log = logging.getLogger(__name__)

_NTFY_PRIORITY_MAP: dict[int, str] = {
    5: "urgent",
    4: "urgent",
    3: "normal",
    2: "low",
    1: "low",
}


def _ntfy_priority_to_str(priority: int) -> str:
    """Map ntfy integer priority to a voice queue priority."""
    return _NTFY_PRIORITY_MAP.get(priority, "normal")


def parse_ntfy_event(raw: str) -> VoiceNotification | None:
    """Parse a raw ntfy JSON event into a VoiceNotification.

    Returns None for non-message events (keepalive, open, etc.).
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Failed to parse ntfy event: %r", raw)
        return None

    if data.get("event") != "message":
        return None

    title = data.get("title", data.get("topic", "ntfy"))
    message = data.get("message", "")
    ntfy_priority = data.get("priority", 3)
    voice_priority = _ntfy_priority_to_str(ntfy_priority)

    return VoiceNotification(
        title=title,
        message=message,
        priority=voice_priority,
        source="ntfy",
    )


async def subscribe_ntfy(
    base_url: str,
    topics: list[str],
    on_notification: Callable[[VoiceNotification], Coroutine],
) -> None:
    """Subscribe to ntfy topics via JSON stream and dispatch notifications.

    Reconnects on failure with exponential backoff (1s → 60s max).
    Uses ntfy's JSON stream endpoint which sends newline-delimited JSON.
    """
    topic_str = ",".join(topics)
    url = f"{base_url.rstrip('/')}/{topic_str}/json"
    backoff = 1.0
    max_backoff = 60.0

    while True:
        try:
            async with httpx.AsyncClient() as client:
                log.info("Connecting to ntfy stream: %s", url)
                async with client.stream("GET", url, timeout=None) as response:
                    response.raise_for_status()
                    backoff = 1.0  # reset on successful connection
                    log.info("Connected to ntfy stream for topics: %s", topic_str)
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        notification = parse_ntfy_event(line)
                        if notification is not None:
                            await on_notification(notification)
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.ReadError,
                httpx.RemoteProtocolError, httpx.ConnectTimeout) as exc:
            log.warning(
                "ntfy connection error (%s), reconnecting in %.0fs",
                exc, backoff,
            )
        except Exception:
            log.exception(
                "Unexpected error in ntfy listener, reconnecting in %.0fs",
                backoff,
            )

        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, max_backoff)
