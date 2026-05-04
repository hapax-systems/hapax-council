"""V5 publication-bus root namespace (PUB-P0-B keystone — wk1 follow-on).

Per V5 weave §2.1 PUB-P0-B, the publication-bus is the canonical
location for one-shot publish-on-demand publishers (Zenodo, Bridgy,
Internet Archive, philarchive, alphaxiv, etc.). The v4 daemon-tail
``BasePublisher`` at ``shared/governance/publisher_kit.py`` continues
to serve cross-surface JSONL-event publishers (bluesky / mastodon /
arena / discord); this v5 ``publication_bus`` namespace serves the
publish-on-demand pattern.

Two ABCs, two patterns:

- v4 ``shared.governance.publisher_kit.BasePublisher`` — daemon that
  tails ``/dev/shm/hapax-broadcast/events.jsonl``, composes per-event,
  sends; subclass overrides ``compose()`` + ``send()``.
- v5 ``agents.publication_bus.publisher_kit.base.Publisher`` — one-shot
  publish-on-demand for an artifact; subclass overrides ``_emit()``.

The two coexist; cross-surface social posting stays on v4, capacity-
surface long-form publication uses v5.
"""

from __future__ import annotations

from agents.publication_bus.youtube_live_chat_publisher import (
    YOUTUBE_LIVE_CHAT_SURFACE,
    LiveChatTokenBucket,
    YoutubeLiveChatPublisher,
)
from agents.publication_bus.youtube_live_chat_publisher import (
    load_default_allowlist as load_youtube_live_chat_allowlist,
)

__all__ = [
    "YOUTUBE_LIVE_CHAT_SURFACE",
    "LiveChatTokenBucket",
    "YoutubeLiveChatPublisher",
    "load_youtube_live_chat_allowlist",
]
