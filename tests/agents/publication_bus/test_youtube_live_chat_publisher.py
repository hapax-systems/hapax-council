"""Tests for ``agents.publication_bus.youtube_live_chat_publisher``."""

from unittest.mock import MagicMock

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


class _FakeHttpError(Exception):
    """Stands in for ``googleapiclient.errors.HttpError`` without the dep.

    The publisher's ``_emit`` only reads ``exc.resp.status`` on the
    caught exception, so any ``Exception`` subclass with a ``resp``
    object exposing ``status`` exercises the same code path.
    """

    def __init__(self, *, status: int, reason: str, content: bytes) -> None:
        super().__init__(f"{status} {reason}")
        self.resp = MagicMock(status=status, reason=reason)
        self.content = content


def _http_error(status: int, reason: str, content: bytes) -> _FakeHttpError:
    return _FakeHttpError(status=status, reason=reason, content=content)


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
    clocks = iter([100.0, 105.0, 111.0])
    rl = LiveChatRateLimiter(min_interval_s=10.0, clock=lambda: next(clocks))
    assert rl.acquire("abc") is True
    assert rl.acquire("abc") is False  # too soon
    assert rl.acquire("abc") is True  # past window


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


def test_default_allowlist_is_empty_when_no_config(monkeypatch, tmp_path):
    monkeypatch.setenv("HAPAX_YOUTUBE_LIVE_CHAT_ALLOWLIST", str(tmp_path / "missing.yaml"))
    from agents.publication_bus.youtube_live_chat_publisher import (
        load_default_allowlist,
    )

    gate = load_default_allowlist()
    assert not gate.permits("anything")
