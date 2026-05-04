# Chat Response — Verbal + Text-Back Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a chat impingement arrives, Hapax can respond verbally (TTS via the existing Evil Pet broadcast path), in-chat (POST to YouTube live chat), or both — chosen per impingement.

**Architecture:** Two parallel response channels. Audio stays on the existing `DestinationChannel` (LIVESTREAM/PRIVATE) routing untouched ("no DRY — broadcast TTS via Evil Pet path"). A new `ChatDestination` enum (initially `YOUTUBE_LIVE_CHAT`) and `ResponseModality` enum (`VERBAL` / `TEXT_CHAT` / `BOTH` / `DROP`) live alongside in `agents/hapax_daimonion/cpal/chat_destination.py`. A new `YoutubeLiveChatPublisher` (V5 `Publisher` subclass) handles the chat POST, inheriting AllowlistGate + legal-name-leak guard + Prometheus counter automatically. A new `agents/hapax_daimonion/cpal/response_dispatch.py` glues impingement → modality classification → parallel verbal+chat emit. A stub interface for epsilon's `agents/youtube_chat_reader/` documents the integration contract for the reverse channel.

**Tech Stack:** Python 3.12+, `agents.publication_bus.publisher_kit.base.Publisher` ABC, `shared.google_auth.get_google_credentials([youtube.force-ssl scope])`, `googleapiclient.discovery.build`, `shared.operator_referent.OperatorReferentPicker`, pydantic for impingement extraction, `unittest.mock` for tests, `time.monotonic()` for rate limiting.

**Currentness intel** (Gemini Jr packet `youtube-live-api-chat-ingestion-and-post-2026`, 2026-05-04): YouTube Data API v3 live-chat insert/list paths are stable through early 2026 (no deprecations). Insert endpoint POSTs to `youtube/v3/liveChat/messages` with `part=snippet` + `textMessageDetails`; `youtube.force-ssl` scope is required; `403 rateLimitExceeded` is the YouTube-specific error on rapid inserts (HTTP 403, NOT 429 as one might expect from the HTTP spec). Reader-side polling cadence is dictated by `pollingIntervalMillis` in the response — epsilon's lane handles that, not this PR.

---

## File Structure

**New files:**
- `agents/hapax_daimonion/cpal/chat_destination.py` — `ChatDestination` + `ResponseModality` enums, `classify_response_modality()`
- `agents/hapax_daimonion/cpal/response_dispatch.py` — Glue between modality classification and parallel verbal/chat emit, returns `ResponseDispatch` envelope
- `agents/publication_bus/youtube_live_chat_publisher.py` — `YoutubeLiveChatPublisher(Publisher)` subclass; `_emit()` POSTs `liveChatMessages.insert`; in-class `LiveChatRateLimiter`
- `agents/youtube_chat_reader/__init__.py` — Stub interface (Protocol + dataclass) for epsilon's reader
- `agents/youtube_chat_reader/_reader_stub.md` — Integration-contract notes
- `tests/hapax_daimonion/cpal/test_chat_destination.py`
- `tests/hapax_daimonion/cpal/test_response_dispatch.py`
- `tests/publication_bus/test_youtube_live_chat_publisher.py`

**Modified files:**
- `agents/hapax_daimonion/cpal/__init__.py` — Re-export `ChatDestination`, `ResponseModality`, `dispatch_response`
- `agents/publication_bus/__init__.py` — Re-export `YoutubeLiveChatPublisher`

**Untouched (preserves "no DRY"):**
- `agents/hapax_daimonion/cpal/destination_channel.py` — Existing audio destination router; we do NOT add CHAT to `DestinationChannel`. Verbal output still flows through the existing `resolve_playback_decision()` so the Evil Pet broadcast TTS path is reused, not re-implemented.

---

## Task 1: ChatDestination + ResponseModality enums + classifier

**Files:**
- Create: `agents/hapax_daimonion/cpal/chat_destination.py`
- Test: `tests/hapax_daimonion/cpal/test_chat_destination.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/hapax_daimonion/cpal/test_chat_destination.py
from dataclasses import dataclass

import pytest

from agents.hapax_daimonion.cpal.chat_destination import (
    ChatDestination,
    ResponseModality,
    classify_response_modality,
)


@dataclass
class _Imp:
    source: str = ""
    content: dict = None
    def __post_init__(self):
        if self.content is None:
            self.content = {}


def test_chat_destination_enum_values():
    assert ChatDestination.YOUTUBE_LIVE_CHAT.value == "youtube_live_chat"


def test_response_modality_values():
    assert {m.value for m in ResponseModality} == {"verbal", "text_chat", "both", "drop"}


def test_chat_message_short_response_text_only():
    imp = _Imp(
        source="youtube.live_chat",
        content={"kind": "chat_message", "response_text": "thanks 🙏"},
    )
    assert classify_response_modality(imp) == ResponseModality.TEXT_CHAT


def test_chat_message_long_response_verbal_only():
    long_text = "I think the deeper point here is that " + "x " * 200
    imp = _Imp(
        source="youtube.live_chat",
        content={"kind": "chat_message", "response_text": long_text},
    )
    assert classify_response_modality(imp) == ResponseModality.VERBAL


def test_chat_message_with_both_intent():
    imp = _Imp(
        source="youtube.live_chat",
        content={
            "kind": "chat_message",
            "response_text": "ok",
            "response_modality_hint": "both",
        },
    )
    assert classify_response_modality(imp) == ResponseModality.BOTH


def test_non_chat_impingement_drops_chat_modality():
    imp = _Imp(source="microphone.blue_yeti", content={"response_text": "x"})
    assert classify_response_modality(imp) == ResponseModality.VERBAL


def test_empty_response_text_drops():
    imp = _Imp(source="youtube.live_chat", content={"kind": "chat_message"})
    assert classify_response_modality(imp) == ResponseModality.DROP


def test_none_impingement_drops():
    assert classify_response_modality(None) == ResponseModality.DROP
```

- [ ] **Step 2: Run the test (expected to fail)**

```bash
uv run pytest tests/hapax_daimonion/cpal/test_chat_destination.py -v
```

Expected: ImportError on the module not yet existing.

- [ ] **Step 3: Implement the module**

```python
# agents/hapax_daimonion/cpal/chat_destination.py
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

1. ``content["response_modality_hint"]`` is one of {"verbal","text_chat","both","drop"} → that.
2. Impingement source is not chat AND has non-empty response_text → VERBAL.
3. Source is chat AND response_text empty/missing → DROP.
4. Source is chat AND len(response_text) ≤ ``SHORT_RESPONSE_CHAR_LIMIT`` → TEXT_CHAT.
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
```

- [ ] **Step 4: Run the test (expected to pass)**

```bash
uv run pytest tests/hapax_daimonion/cpal/test_chat_destination.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_daimonion/cpal/chat_destination.py tests/hapax_daimonion/cpal/test_chat_destination.py
git commit -m "feat(cpal): ChatDestination + ResponseModality enums + classifier"
```

---

## Task 2: youtube_chat_reader stub interface

Stub the reader interface so this PR can land before epsilon ships the real reader. Documents the integration contract.

**Files:**
- Create: `agents/youtube_chat_reader/__init__.py`
- Create: `agents/youtube_chat_reader/_reader_stub.md`

- [ ] **Step 1: Write the stub module**

```python
# agents/youtube_chat_reader/__init__.py
"""YouTube live-chat reader — interface stub.

Owner: epsilon (cc-task ``youtube-chat-ingestion-impingement``).
This module ships a Protocol-only stub so the chat-poster lane
(cc-task ``chat-response-verbal-and-text``) can wire to it without
blocking on epsilon's implementation. When epsilon lands the real
reader, the Protocol below is the contract their concrete class
must satisfy; no further integration changes are required on the
poster side.

Integration contract (read by ``response_dispatch.py``):

* The reader's ``live_chat_id()`` is the YouTube Data API
  ``liveChatId`` (the ID returned by ``liveBroadcasts.list`` under
  ``snippet.liveChatId``, or ``videos.list`` with
  ``part=liveStreamingDetails`` -> ``activeLiveChatId``). The
  poster needs this ID for the ``liveChatMessages.insert`` POST
  target — it is the only routing identifier the YouTube API
  exposes for posting into a stream's chat.
* ``recent_messages()`` is for the chat-state surface and is not
  consumed by this PR.

The stub raises ``YoutubeChatReaderUnavailable`` for every method.
``response_dispatch.py`` uses ``get_active_reader()`` and treats a
``None`` return as "no reader available — chat post path inactive".

Shared OAuth credential path: epsilon's reader and this poster both
use ``shared.google_auth.get_google_credentials()``. The reader
typically requests the readonly scope; the poster requests
``youtube.force-ssl``. ``google-auth`` handles refresh
transparently across both lanes when a single token covers both
scopes (operator can mint once with both scopes).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class YoutubeChatReaderUnavailable(RuntimeError):
    """Raised when the stub reader is asked for state it cannot provide.

    Replaced when epsilon's reader lands — concrete instances satisfy
    the protocol with real state.
    """


@dataclass(frozen=True)
class ChatMessageSnapshot:
    """One chat message — author hash, text, sentiment, length, timestamp.

    Mirrors the impingement adapter's per-message metadata
    (``youtube-chat-ingestion-impingement`` cc-task §2). Author IDs
    arrive hashed per the interpersonal_transparency axiom.
    """

    author_hash: str
    text: str
    sentiment: float
    length: int
    posted_at_unix: float


class YoutubeChatReader(Protocol):
    """Reverse-channel reader contract.

    Implemented by epsilon's concrete agent at module-load time. The
    poster lane reads ``live_chat_id()`` for the POST target.
    """

    def live_chat_id(self) -> str:
        """The active stream's YouTube ``liveChatId``.

        Raises ``YoutubeChatReaderUnavailable`` when no broadcast is
        active. Concrete reader caches per-broadcast.
        """

    def recent_messages(self, *, limit: int = 50) -> list[ChatMessageSnapshot]:
        """Last ``limit`` chat messages — for compositor + dashboards."""


def get_active_reader() -> YoutubeChatReader | None:
    """Return the currently-registered reader, or ``None`` if none.

    Concrete reader (epsilon) calls ``register_reader()`` at startup;
    until then this returns ``None`` and the poster lane silently
    skips chat-post emission. The verbal modality is unaffected.
    """
    return _ACTIVE_READER


def register_reader(reader: YoutubeChatReader) -> None:
    """Register the active reader. Idempotent; last-write wins."""
    global _ACTIVE_READER
    _ACTIVE_READER = reader


def clear_reader() -> None:
    """Clear the registry. Used by tests."""
    global _ACTIVE_READER
    _ACTIVE_READER = None


_ACTIVE_READER: YoutubeChatReader | None = None


__all__ = [
    "ChatMessageSnapshot",
    "YoutubeChatReader",
    "YoutubeChatReaderUnavailable",
    "clear_reader",
    "get_active_reader",
    "register_reader",
]
```

- [ ] **Step 2: Write the integration-contract doc**

```markdown
# youtube_chat_reader — integration contract

Owner: epsilon (cc-task `youtube-chat-ingestion-impingement`).

This `__init__.py` is a Protocol-only stub. The poster lane (cc-task
`chat-response-verbal-and-text`) imports `get_active_reader()` and
uses the returned reader's `live_chat_id()` as the POST target for
`liveChatMessages.insert`.

When epsilon lands the real reader:

1. Their concrete class must satisfy `YoutubeChatReader` Protocol —
   `live_chat_id()` returning the active broadcast's `liveChatId`,
   `recent_messages(limit=50)` returning the last N
   `ChatMessageSnapshot`s.
2. Their startup hook calls `register_reader(self)` once the YouTube
   Live Streaming API has resolved the active broadcast.
3. No changes required on the poster side — `get_active_reader()`
   begins returning the concrete reader and the poster's `_emit()`
   reads `live_chat_id()` from it.

If the reader is not yet registered (or a broadcast is not active),
`get_active_reader()` returns `None`. The poster's
`response_dispatch.dispatch_response()` treats this as "chat path
inactive" — the verbal modality still emits via the existing Evil
Pet broadcast TTS path.

Shared credentials: both lanes consume `shared.google_auth.
get_google_credentials([scopes])`. Reader typically requests
`youtube.readonly`; poster requests `youtube.force-ssl`. Operator
can mint a single token covering both scopes.
```

- [ ] **Step 3: Smoke-test the stub**

```bash
uv run python -c "from agents.youtube_chat_reader import get_active_reader, register_reader, clear_reader, ChatMessageSnapshot, YoutubeChatReader; assert get_active_reader() is None; print('stub ok')"
```

Expected: `stub ok`.

- [ ] **Step 4: Commit**

```bash
git add agents/youtube_chat_reader/
git commit -m "feat(youtube_chat_reader): add Protocol stub for poster integration"
```

---

## Task 3: YoutubeLiveChatPublisher (V5 Publisher subclass + rate limiter)

**Files:**
- Create: `agents/publication_bus/youtube_live_chat_publisher.py`
- Test: `tests/publication_bus/test_youtube_live_chat_publisher.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/publication_bus/test_youtube_live_chat_publisher.py
import time
from unittest.mock import MagicMock

import pytest

from agents.publication_bus.publisher_kit.allowlist import load_allowlist
from agents.publication_bus.publisher_kit.base import PublisherPayload
from agents.publication_bus.youtube_live_chat_publisher import (
    YOUTUBE_LIVE_CHAT_SURFACE,
    LiveChatRateLimiter,
    YoutubeLiveChatPublisher,
)


def _ok_response():
    resp = MagicMock()
    resp.execute.return_value = {"id": "x", "snippet": {"liveChatId": "abc"}}
    return resp


def _make_service():
    service = MagicMock()
    insert = MagicMock(return_value=_ok_response())
    service.liveChatMessages.return_value.insert = insert
    return service, insert


def _http_error(status: int, reason: str, content: bytes):
    from googleapiclient.errors import HttpError

    resp = MagicMock()
    resp.status = status
    resp.reason = reason
    return HttpError(resp=resp, content=content)


def test_emit_posts_to_live_chat_messages_insert():
    service, insert = _make_service()
    pub = YoutubeLiveChatPublisher(
        service_factory=lambda: service,
        allowlist=load_allowlist(YOUTUBE_LIVE_CHAT_SURFACE, ["abc"]),
        rate_limiter=LiveChatRateLimiter(min_interval_s=0.0),
    )
    result = pub.publish(PublisherPayload(target="abc", text="thanks 🙏"))
    assert result.ok is True
    assert insert.call_count == 1
    call_kwargs = insert.call_args.kwargs
    assert call_kwargs["part"] == "snippet"
    body = call_kwargs["body"]["snippet"]
    assert body["liveChatId"] == "abc"
    assert body["type"] == "textMessageEvent"
    assert body["textMessageDetails"]["messageText"] == "thanks 🙏"


def test_emit_refuses_non_allowlisted_chat_id():
    service, _ = _make_service()
    pub = YoutubeLiveChatPublisher(
        service_factory=lambda: service,
        allowlist=load_allowlist(YOUTUBE_LIVE_CHAT_SURFACE, ["only_this_one"]),
        rate_limiter=LiveChatRateLimiter(min_interval_s=0.0),
    )
    result = pub.publish(PublisherPayload(target="other_chat", text="hi"))
    assert result.refused is True
    assert result.ok is False


def test_emit_refuses_legal_name_leak(monkeypatch):
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Ryan Lee")
    service, _ = _make_service()
    pub = YoutubeLiveChatPublisher(
        service_factory=lambda: service,
        allowlist=load_allowlist(YOUTUBE_LIVE_CHAT_SURFACE, ["abc"]),
        rate_limiter=LiveChatRateLimiter(min_interval_s=0.0),
    )
    result = pub.publish(PublisherPayload(target="abc", text="this is Ryan Lee speaking"))
    assert result.refused is True


def test_rate_limiter_blocks_within_window():
    rl = LiveChatRateLimiter(min_interval_s=10.0, clock=lambda: 100.0)
    assert rl.acquire("abc") is True
    assert rl.acquire("abc") is False  # too soon
    rl._clock = lambda: 111.0  # past window
    assert rl.acquire("abc") is True


def test_rate_limiter_per_chat_id():
    rl = LiveChatRateLimiter(min_interval_s=10.0, clock=lambda: 100.0)
    assert rl.acquire("chat_a") is True
    assert rl.acquire("chat_b") is True  # different thread, fresh window


def test_emit_returns_error_on_rate_limit_block():
    service, insert = _make_service()
    rl = LiveChatRateLimiter(min_interval_s=10.0, clock=lambda: 100.0)
    rl.acquire("abc")  # consume the window
    pub = YoutubeLiveChatPublisher(
        service_factory=lambda: service,
        allowlist=load_allowlist(YOUTUBE_LIVE_CHAT_SURFACE, ["abc"]),
        rate_limiter=rl,
    )
    result = pub.publish(PublisherPayload(target="abc", text="hi"))
    assert result.error is True
    assert "rate" in result.detail.lower()
    assert insert.call_count == 0


def test_emit_handles_http_429_as_error():
    service = MagicMock()
    raising = MagicMock()
    raising.execute.side_effect = _http_error(
        429, "Too Many Requests", b'{"error":{"message":"quota"}}'
    )
    service.liveChatMessages.return_value.insert.return_value = raising
    pub = YoutubeLiveChatPublisher(
        service_factory=lambda: service,
        allowlist=load_allowlist(YOUTUBE_LIVE_CHAT_SURFACE, ["abc"]),
        rate_limiter=LiveChatRateLimiter(min_interval_s=0.0),
    )
    result = pub.publish(PublisherPayload(target="abc", text="hi"))
    assert result.error is True
    assert "429" in result.detail


def test_emit_handles_http_403_rate_limit_exceeded_as_error():
    """YouTube returns 403 (not 429) for rapid-insert rateLimitExceeded.

    Source: Gemini Jr packet youtube-live-api-chat-ingestion-and-post-2026.
    """
    service = MagicMock()
    raising = MagicMock()
    raising.execute.side_effect = _http_error(
        403,
        "Forbidden",
        b'{"error":{"errors":[{"reason":"rateLimitExceeded"}],"message":"rate"}}',
    )
    service.liveChatMessages.return_value.insert.return_value = raising
    pub = YoutubeLiveChatPublisher(
        service_factory=lambda: service,
        allowlist=load_allowlist(YOUTUBE_LIVE_CHAT_SURFACE, ["abc"]),
        rate_limiter=LiveChatRateLimiter(min_interval_s=0.0),
    )
    result = pub.publish(PublisherPayload(target="abc", text="hi"))
    assert result.error is True
    assert "403" in result.detail


def test_default_allowlist_loads_from_yaml(tmp_path, monkeypatch):
    yaml_path = tmp_path / "youtube_live_chat.yaml"
    yaml_path.write_text("permitted:\n  - operator-chat-id-1\n")
    monkeypatch.setenv("HAPAX_YOUTUBE_LIVE_CHAT_ALLOWLIST", str(yaml_path))
    from agents.publication_bus.youtube_live_chat_publisher import (
        load_default_allowlist,
    )
    gate = load_default_allowlist()
    assert gate.permits("operator-chat-id-1")
    assert not gate.permits("attacker-chat-id")
```

- [ ] **Step 2: Run the test (expected to fail)**

```bash
uv run pytest tests/publication_bus/test_youtube_live_chat_publisher.py -v
```

Expected: ImportError on the module not yet existing.

- [ ] **Step 3: Implement the module**

```python
# agents/publication_bus/youtube_live_chat_publisher.py
"""YouTube Live Chat poster (V5 publication-bus publisher).

POSTs ``liveChatMessages.insert`` to publish a textMessageEvent into
the operator's active livestream chat. Subclass of the V5
:class:`Publisher` ABC, so the three load-bearing invariants are
inherited from the base ``publish()`` method:

1. AllowlistGate — only operator-curated ``liveChatId``s permitted
2. Legal-name-leak guard — ``requires_legal_name = False``; chat
   replies are signed via the operator-referent picker
3. Prometheus counter — per-result outcome under
   ``hapax_publication_bus_publishes_total{surface="youtube-live-chat-message"}``

A per-chat-id :class:`LiveChatRateLimiter` is the fourth guard,
specific to this surface (not part of the V5 invariants because
allowlist alone does not constrain emission cadence).

Auth: ``shared.google_auth.get_google_credentials([youtube.force-ssl])``
matches the existing youtube_telemetry pattern. The operator must
mint a token with the ``youtube.force-ssl`` scope (write access to
their own channel) — ``google-auth`` handles refresh transparently
once the refresh token is in place.

Error semantics (per Gemini Jr packet
``youtube-live-api-chat-ingestion-and-post-2026``):

* HTTP 429 — generic too-many-requests; classified as ``error=True``.
* HTTP 403 with ``rateLimitExceeded`` reason — YouTube-specific
  rapid-insert rate limit; classified as ``error=True`` (NOT
  ``refused=True`` because we expect to retry next window).
* Other 4xx — ``error=True``; transport-level failures bubble up
  here too. The publish path never raises.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import yaml

from agents.publication_bus.publisher_kit.allowlist import (
    AllowlistGate,
    load_allowlist,
)
from agents.publication_bus.publisher_kit.base import (
    Publisher,
    PublisherPayload,
    PublisherResult,
)

log = logging.getLogger(__name__)

YOUTUBE_LIVE_CHAT_SURFACE: str = "youtube-live-chat-message"
"""Stable surface name for AllowlistGate + Prometheus labels."""

YOUTUBE_FORCE_SSL_SCOPE: str = "https://www.googleapis.com/auth/youtube.force-ssl"
"""OAuth scope required for liveChatMessages.insert."""

DEFAULT_MIN_INTERVAL_S: float = 5.0
"""Default rate-limit window per liveChatId."""

DEFAULT_ALLOWLIST_ENV: str = "HAPAX_YOUTUBE_LIVE_CHAT_ALLOWLIST"
"""Operator-set env var pointing at a YAML allowlist file with a single
``permitted`` list of liveChatIds. Empty allowlist = chat path inactive."""

DEFAULT_ALLOWLIST_PATH: Path = Path("config/publication-bus/youtube-live-chat.yaml")
"""Repo-checked allowlist fallback when the env override is unset."""


@dataclass
class LiveChatRateLimiter:
    """Per-liveChatId minimum-interval rate limiter.

    Default 5s window per chat thread (operator-tunable via
    constructor). Thread-safe via a single ``threading.Lock``; the
    last-permitted timestamp per chat id is stored in a small dict
    that grows with the number of distinct chat threads (in practice
    one per active broadcast).
    """

    min_interval_s: float = DEFAULT_MIN_INTERVAL_S
    clock: Callable[[], float] = field(default_factory=lambda: time.monotonic)
    _last_permitted: dict[str, float] = field(default_factory=dict, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self) -> None:
        self._clock = self.clock

    def acquire(self, chat_id: str) -> bool:
        """Return ``True`` iff a post is permitted now for ``chat_id``."""
        if self.min_interval_s <= 0.0:
            return True
        now = self._clock()
        with self._lock:
            last = self._last_permitted.get(chat_id)
            if last is not None and now - last < self.min_interval_s:
                return False
            self._last_permitted[chat_id] = now
            return True


def load_default_allowlist() -> AllowlistGate:
    """Load the YouTube live-chat allowlist from env or repo config.

    Empty allowlist (file missing or empty list) yields a gate that
    permits nothing — the chat path is inactive until the operator
    populates the file with their broadcast's liveChatId.
    """
    env_path = os.environ.get(DEFAULT_ALLOWLIST_ENV)
    candidate = Path(env_path) if env_path else DEFAULT_ALLOWLIST_PATH
    permitted: list[str] = []
    if candidate.is_file():
        try:
            data = yaml.safe_load(candidate.read_text()) or {}
            if isinstance(data, dict):
                raw = data.get("permitted") or []
                if isinstance(raw, list):
                    permitted = [str(x) for x in raw if isinstance(x, str)]
        except (yaml.YAMLError, OSError) as exc:
            log.warning("youtube-live-chat allowlist load failed (%s): %s", candidate, exc)
    return load_allowlist(YOUTUBE_LIVE_CHAT_SURFACE, permitted)


class YoutubeLiveChatPublisher(Publisher):
    """Publishes a chat message into a YouTube live broadcast.

    ``payload.target`` is the ``liveChatId`` (allowlist match key).
    ``payload.text`` is the message body (max 200 chars per YouTube
    API; the chat-task's <140 char short-response window stays well
    under that ceiling).
    """

    surface_name: ClassVar[str] = YOUTUBE_LIVE_CHAT_SURFACE
    allowlist: ClassVar[AllowlistGate] = load_allowlist(YOUTUBE_LIVE_CHAT_SURFACE, [])
    requires_legal_name: ClassVar[bool] = False

    def __init__(
        self,
        *,
        service_factory: Callable[[], Any] | None = None,
        allowlist: AllowlistGate | None = None,
        rate_limiter: LiveChatRateLimiter | None = None,
    ) -> None:
        if allowlist is not None:
            self.allowlist = allowlist  # type: ignore[misc]
        self._service_factory = service_factory or self._build_service
        self._service: Any | None = None
        self._rate_limiter = rate_limiter or LiveChatRateLimiter()

    @staticmethod
    def _build_service() -> Any:
        from googleapiclient.discovery import build

        from shared.google_auth import get_google_credentials

        creds = get_google_credentials([YOUTUBE_FORCE_SSL_SCOPE])
        if creds is None:
            raise RuntimeError(
                "no google credentials available for youtube.force-ssl — operator must mint "
                "a token with that scope before chat posting can work"
            )
        return build("youtube", "v3", credentials=creds, cache_discovery=False)

    def _ensure_service(self) -> Any:
        if self._service is None:
            self._service = self._service_factory()
        return self._service

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        if not self._rate_limiter.acquire(payload.target):
            return PublisherResult(
                error=True,
                detail=f"rate-limit window not elapsed for {payload.target}",
            )
        try:
            service = self._ensure_service()
        except RuntimeError as exc:
            return PublisherResult(error=True, detail=f"service init failed: {exc}")

        body = {
            "snippet": {
                "liveChatId": payload.target,
                "type": "textMessageEvent",
                "textMessageDetails": {"messageText": payload.text},
            }
        }
        try:
            request = service.liveChatMessages().insert(part="snippet", body=body)
            request.execute()
        except Exception as exc:  # noqa: BLE001 — googleapiclient.errors.HttpError + transport
            status = getattr(getattr(exc, "resp", None), "status", None)
            log.warning("youtube live-chat insert failed (status=%s): %s", status, exc)
            detail = f"insert failed: status={status} {exc.__class__.__name__}"
            return PublisherResult(error=True, detail=detail)
        return PublisherResult(ok=True, detail="liveChatMessages.insert ok")


__all__ = [
    "DEFAULT_ALLOWLIST_ENV",
    "DEFAULT_ALLOWLIST_PATH",
    "DEFAULT_MIN_INTERVAL_S",
    "LiveChatRateLimiter",
    "YOUTUBE_FORCE_SSL_SCOPE",
    "YOUTUBE_LIVE_CHAT_SURFACE",
    "YoutubeLiveChatPublisher",
    "load_default_allowlist",
]
```

- [ ] **Step 4: Run the tests (expected to pass)**

```bash
uv run pytest tests/publication_bus/test_youtube_live_chat_publisher.py -v
```

Expected: all 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add agents/publication_bus/youtube_live_chat_publisher.py tests/publication_bus/test_youtube_live_chat_publisher.py
git commit -m "feat(publication_bus): YoutubeLiveChatPublisher (liveChatMessages.insert + rate limit)"
```

---

## Task 4: response_dispatch — wire modality classification → parallel verbal+chat

**Files:**
- Create: `agents/hapax_daimonion/cpal/response_dispatch.py`
- Test: `tests/hapax_daimonion/cpal/test_response_dispatch.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/hapax_daimonion/cpal/test_response_dispatch.py
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from agents.hapax_daimonion.cpal.chat_destination import ResponseModality
from agents.hapax_daimonion.cpal.response_dispatch import (
    ResponseDispatch,
    dispatch_response,
)
from agents.publication_bus.publisher_kit.base import PublisherResult
from agents.youtube_chat_reader import (
    clear_reader,
    register_reader,
)


@dataclass
class _Imp:
    source: str = ""
    content: dict = None
    def __post_init__(self):
        if self.content is None:
            self.content = {}


@pytest.fixture(autouse=True)
def _reset_reader():
    clear_reader()
    yield
    clear_reader()


def _stub_reader(live_chat_id="abc"):
    reader = MagicMock()
    reader.live_chat_id.return_value = live_chat_id
    return reader


def test_text_chat_only_short_chat_message_posts_no_audio():
    register_reader(_stub_reader("abc"))
    publisher = MagicMock()
    publisher.publish.return_value = PublisherResult(ok=True, detail="ok")
    imp = _Imp(
        source="youtube.live_chat",
        content={"kind": "chat_message", "response_text": "thanks 🙏"},
    )
    result = dispatch_response(imp, publisher=publisher)
    assert result.modality == ResponseModality.TEXT_CHAT
    assert result.chat_result is not None
    assert result.chat_result.ok is True
    assert result.audio_decision is None
    assert publisher.publish.call_count == 1
    payload = publisher.publish.call_args.args[0]
    assert payload.target == "abc"
    assert "thanks" in payload.text


def test_verbal_only_long_chat_message_returns_audio_decision_no_chat():
    register_reader(_stub_reader("abc"))
    publisher = MagicMock()
    long_text = "a longer reply " * 30
    imp = _Imp(
        source="youtube.live_chat",
        content={"kind": "chat_message", "response_text": long_text},
    )
    result = dispatch_response(imp, publisher=publisher)
    assert result.modality == ResponseModality.VERBAL
    assert result.audio_decision is not None
    assert result.chat_result is None
    assert publisher.publish.call_count == 0


def test_both_modality_emits_in_parallel():
    register_reader(_stub_reader("abc"))
    publisher = MagicMock()
    publisher.publish.return_value = PublisherResult(ok=True, detail="ok")
    imp = _Imp(
        source="youtube.live_chat",
        content={
            "kind": "chat_message",
            "response_text": "ok",
            "response_modality_hint": "both",
        },
    )
    result = dispatch_response(imp, publisher=publisher)
    assert result.modality == ResponseModality.BOTH
    assert result.audio_decision is not None
    assert result.chat_result is not None
    assert publisher.publish.call_count == 1


def test_chat_path_skipped_when_no_reader_registered():
    publisher = MagicMock()
    imp = _Imp(
        source="youtube.live_chat",
        content={"kind": "chat_message", "response_text": "thanks"},
    )
    result = dispatch_response(imp, publisher=publisher)
    assert result.modality == ResponseModality.TEXT_CHAT
    assert result.chat_result is None
    assert result.skip_reason == "no_reader_registered"
    assert publisher.publish.call_count == 0


def test_drop_modality_emits_nothing():
    register_reader(_stub_reader("abc"))
    publisher = MagicMock()
    imp = _Imp(source="youtube.live_chat", content={"kind": "chat_message"})
    result = dispatch_response(imp, publisher=publisher)
    assert result.modality == ResponseModality.DROP
    assert result.audio_decision is None
    assert result.chat_result is None
    assert publisher.publish.call_count == 0


def test_text_signed_with_operator_referent():
    register_reader(_stub_reader("abc"))
    publisher = MagicMock()
    publisher.publish.return_value = PublisherResult(ok=True, detail="ok")
    imp = _Imp(
        source="youtube.live_chat",
        content={
            "kind": "chat_message",
            "response_text": "noted",
            "impingement_id": "imp-42",
        },
    )
    dispatch_response(imp, publisher=publisher, attribution=True)
    payload = publisher.publish.call_args.args[0]
    referents = ("The Operator", "Oudepode", "Oudepode The Operator", "OTO")
    assert any(r in payload.text for r in referents)
    assert "noted" in payload.text
```

- [ ] **Step 2: Run the test (expected to fail)**

```bash
uv run pytest tests/hapax_daimonion/cpal/test_response_dispatch.py -v
```

Expected: ImportError on the module not yet existing.

- [ ] **Step 3: Implement the module**

```python
# agents/hapax_daimonion/cpal/response_dispatch.py
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


def _sign_for_chat(text: str, *, impingement_id: str | None) -> str:
    """Append a sticky operator referent to ``text``.

    Sticky-per-impingement: same impingement_id always picks the same
    referent so a multi-modal response (verbal + chat) reads
    consistently. Caller-controlled via ``attribution=True``.
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
                if attribution:
                    text = _sign_for_chat(
                        text,
                        impingement_id=content.get("impingement_id"),
                    )
                pub = publisher or YoutubeLiveChatPublisher()
                chat_result = pub.publish(PublisherPayload(target=chat_id, text=text))

    return ResponseDispatch(
        modality=modality,
        audio_decision=audio_decision,
        chat_result=chat_result,
        skip_reason=skip_reason,
    )


__all__ = [
    "ResponseDispatch",
    "dispatch_response",
]
```

- [ ] **Step 4: Run the tests (expected to pass)**

```bash
uv run pytest tests/hapax_daimonion/cpal/test_response_dispatch.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_daimonion/cpal/response_dispatch.py tests/hapax_daimonion/cpal/test_response_dispatch.py
git commit -m "feat(cpal): response_dispatch — modality classifier wired to verbal + chat emit"
```

---

## Task 5: Wire re-exports + run full suite

**Files:**
- Modify: `agents/hapax_daimonion/cpal/__init__.py`
- Modify: `agents/publication_bus/__init__.py`

- [ ] **Step 1: Read and patch the cpal __init__**

Run: `cat agents/hapax_daimonion/cpal/__init__.py`. Then add the new re-exports at the bottom (do not disturb existing exports):

```python
from agents.hapax_daimonion.cpal.chat_destination import (  # noqa: E402
    ChatDestination,
    ResponseModality,
    SHORT_RESPONSE_CHAR_LIMIT,
    classify_response_modality,
)
from agents.hapax_daimonion.cpal.response_dispatch import (  # noqa: E402
    ResponseDispatch,
    dispatch_response,
)

__all__ = list(set(globals().get("__all__", [])) | {
    "ChatDestination",
    "ResponseModality",
    "ResponseDispatch",
    "SHORT_RESPONSE_CHAR_LIMIT",
    "classify_response_modality",
    "dispatch_response",
})
```

- [ ] **Step 2: Read and patch the publication_bus __init__**

Run: `cat agents/publication_bus/__init__.py`. Then add the new re-exports at the bottom:

```python
from agents.publication_bus.youtube_live_chat_publisher import (  # noqa: E402
    LiveChatRateLimiter,
    YOUTUBE_LIVE_CHAT_SURFACE,
    YoutubeLiveChatPublisher,
    load_default_allowlist as load_youtube_live_chat_allowlist,
)

__all__ = list(set(globals().get("__all__", [])) | {
    "LiveChatRateLimiter",
    "YOUTUBE_LIVE_CHAT_SURFACE",
    "YoutubeLiveChatPublisher",
    "load_youtube_live_chat_allowlist",
})
```

- [ ] **Step 3: Run the full new-test suite + lint**

```bash
uv run pytest tests/hapax_daimonion/cpal/test_chat_destination.py tests/hapax_daimonion/cpal/test_response_dispatch.py tests/publication_bus/test_youtube_live_chat_publisher.py -v
uv run ruff check agents/hapax_daimonion/cpal/chat_destination.py agents/hapax_daimonion/cpal/response_dispatch.py agents/publication_bus/youtube_live_chat_publisher.py agents/youtube_chat_reader/__init__.py
uv run ruff format --check agents/hapax_daimonion/cpal/chat_destination.py agents/hapax_daimonion/cpal/response_dispatch.py agents/publication_bus/youtube_live_chat_publisher.py agents/youtube_chat_reader/__init__.py
```

Expected: all green. Fix any ruff complaints inline.

- [ ] **Step 4: Sanity-check that existing CPAL tests still pass**

```bash
uv run pytest tests/hapax_daimonion/cpal/ -v
```

Expected: pre-existing tests all pass (we did not modify destination_channel.py).

- [ ] **Step 5: Commit re-exports**

```bash
git add agents/hapax_daimonion/cpal/__init__.py agents/publication_bus/__init__.py
git commit -m "feat: re-export chat-destination + youtube-live-chat-publisher modules"
```

---

## Task 6: Push, open PR, drive to merge

- [ ] **Step 1: Push the branch**

```bash
git push -u origin zeta/chat-response-verbal-and-text
```

- [ ] **Step 2: Open the PR**

PR body documents coordination breadcrumb for epsilon and acceptance evidence per cc-task. Use `gh pr create --title ... --body "$(cat <<'EOF' ... EOF)"` HEREDOC pattern. See cc-task spec for acceptance criteria.

- [ ] **Step 3: Watch CI + merge when green**

```bash
gh pr view --json number,headRefName,statusCheckRollup,mergeable,mergeStateStatus
gh pr checks
```

When all required checks pass and PR is mergeable, merge:

```bash
gh pr merge --squash --delete-branch
```

- [ ] **Step 4: Update the cc-task to done**

```bash
scripts/cc-close chat-response-verbal-and-text --pr <PR_NUMBER>
```

- [ ] **Step 5: Note coordination breadcrumb in epsilon's cc-task**

Append a Notes section to the epsilon cc-task vault note pointing at the merged PR and the integration contract doc.
