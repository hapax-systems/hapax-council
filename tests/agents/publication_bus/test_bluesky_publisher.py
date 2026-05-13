"""Tests for ``agents.publication_bus.bluesky_publisher``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.publication_bus.bluesky_publisher import (
    BLUESKY_ATPROTO_ENDPOINT,
    BLUESKY_POST_SURFACE,
    BLUESKY_SURFACE,
    BlueskyPostPublisher,
    BlueskyPublisher,
)
from agents.publication_bus.publisher_kit import PublisherPayload
from agents.publication_bus.publisher_kit.allowlist import load_allowlist


def _mock_response(status_code: int, json_data=None, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    response.json = MagicMock(return_value={} if json_data is None else json_data)
    return response


_LOGIN_OK = {
    "accessJwt": "test-jwt",
    "did": "did:plc:test123",
    "handle": "operator.bsky.social",
}

_POST_OK = {
    "uri": "at://did:plc:test123/app.bsky.feed.post/3a4b5c6d",
    "cid": "bafyreigh2akiscaildc...",
}


class TestSurfaceMetadata:
    def test_surface_name_is_bluesky_atproto(self) -> None:
        assert BlueskyPublisher.surface_name == BLUESKY_SURFACE
        assert BLUESKY_SURFACE == "bluesky-atproto-multi-identity"

    def test_public_event_surface_uses_bluesky_post_slug(self) -> None:
        assert BlueskyPostPublisher.surface_name == BLUESKY_POST_SURFACE
        assert BLUESKY_POST_SURFACE == "bluesky-post"

    def test_does_not_require_legal_name(self) -> None:
        assert BlueskyPublisher.requires_legal_name is False
        assert BlueskyPostPublisher.requires_legal_name is False


class TestPublisher:
    @patch("agents.publication_bus.bluesky_publisher.requests")
    def test_emit_creates_session_then_posts(self, mock_requests: MagicMock) -> None:
        mock_requests.post.side_effect = [
            _mock_response(200, _LOGIN_OK),
            _mock_response(200, _POST_OK),
        ]
        BlueskyPublisher.allowlist = load_allowlist(BLUESKY_SURFACE, ["operator"])
        publisher = BlueskyPublisher(handle="operator.bsky.social", app_password="x-y-z-w")
        result = publisher.publish(PublisherPayload(target="operator", text="post content"))
        assert result.ok is True
        # Two POSTs: createSession + createRecord
        assert mock_requests.post.call_count == 2

    def test_missing_creds_returns_refused(self) -> None:
        BlueskyPublisher.allowlist = load_allowlist(BLUESKY_SURFACE, ["operator"])
        publisher = BlueskyPublisher(handle="", app_password="")
        result = publisher.publish(PublisherPayload(target="operator", text="post"))
        assert result.refused is True
        assert "creds" in result.detail.lower() or "credential" in result.detail.lower()

    def test_allowlist_deny_short_circuits(self) -> None:
        BlueskyPublisher.allowlist = load_allowlist(BLUESKY_SURFACE, [])
        publisher = BlueskyPublisher(handle="x", app_password="y")
        result = publisher.publish(PublisherPayload(target="operator", text="post"))
        assert result.refused is True

    @patch("agents.publication_bus.bluesky_publisher.requests")
    def test_login_failure_returns_error(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(401, text="invalid")
        BlueskyPublisher.allowlist = load_allowlist(BLUESKY_SURFACE, ["operator"])
        publisher = BlueskyPublisher(handle="operator.bsky.social", app_password="bad")
        result = publisher.publish(PublisherPayload(target="operator", text="post"))
        assert result.error is True

    @patch("agents.publication_bus.bluesky_publisher.requests")
    def test_post_failure_returns_error(self, mock_requests: MagicMock) -> None:
        mock_requests.post.side_effect = [
            _mock_response(200, _LOGIN_OK),
            _mock_response(500, text="server error"),
        ]
        BlueskyPublisher.allowlist = load_allowlist(BLUESKY_SURFACE, ["operator"])
        publisher = BlueskyPublisher(handle="operator.bsky.social", app_password="x-y-z-w")
        result = publisher.publish(PublisherPayload(target="operator", text="post"))
        assert result.error is True

    @patch("agents.publication_bus.bluesky_publisher.requests")
    def test_request_exception_returns_error(self, mock_requests: MagicMock) -> None:
        import requests as _requests_lib

        mock_requests.post.side_effect = _requests_lib.RequestException("offline")
        mock_requests.RequestException = _requests_lib.RequestException
        BlueskyPublisher.allowlist = load_allowlist(BLUESKY_SURFACE, ["operator"])
        publisher = BlueskyPublisher(handle="operator.bsky.social", app_password="x-y-z-w")
        result = publisher.publish(PublisherPayload(target="operator", text="post"))
        assert result.error is True

    @patch("agents.publication_bus.bluesky_publisher.requests")
    def test_endpoint_is_bsky_atproto_xrpc(self, mock_requests: MagicMock) -> None:
        mock_requests.post.side_effect = [
            _mock_response(200, _LOGIN_OK),
            _mock_response(200, _POST_OK),
        ]
        BlueskyPublisher.allowlist = load_allowlist(BLUESKY_SURFACE, ["operator"])
        publisher = BlueskyPublisher(handle="operator.bsky.social", app_password="x-y-z-w")
        publisher.publish(PublisherPayload(target="operator", text="post"))
        # First call is to createSession
        login_url = mock_requests.post.call_args_list[0].args[0]
        assert login_url.startswith(BLUESKY_ATPROTO_ENDPOINT)
        assert "createSession" in login_url
        # Second call is to createRecord
        post_url = mock_requests.post.call_args_list[1].args[0]
        assert "createRecord" in post_url
