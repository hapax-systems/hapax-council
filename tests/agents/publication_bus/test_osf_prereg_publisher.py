"""Tests for ``agents.publication_bus.osf_prereg_publisher``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.publication_bus.osf_prereg_publisher import (
    OSF_API_BASE,
    OSF_PREREG_SURFACE,
    OSFPreregPublisher,
)
from agents.publication_bus.publisher_kit import PublisherPayload
from agents.publication_bus.publisher_kit.allowlist import load_allowlist


def _mock_response(status_code: int, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    return response


class TestSurfaceMetadata:
    def test_surface_name_is_osf_prereg(self) -> None:
        assert OSFPreregPublisher.surface_name == OSF_PREREG_SURFACE
        assert OSF_PREREG_SURFACE == "osf-prereg"

    def test_does_not_require_legal_name(self) -> None:
        assert OSFPreregPublisher.requires_legal_name is False


class TestPublisher:
    @patch("agents.publication_bus.osf_prereg_publisher.requests")
    def test_emit_posts_to_osf_registrations_endpoint(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(201, text='{"data": {}}')
        OSFPreregPublisher.allowlist = load_allowlist(OSF_PREREG_SURFACE, ["prereg-1"])
        publisher = OSFPreregPublisher(token="test-token")
        result = publisher.publish(
            PublisherPayload(
                target="prereg-1",
                text="Preregistration body text.",
                metadata={"title": "Test prereg"},
            )
        )
        assert result.ok is True
        url = mock_requests.post.call_args[0][0]
        assert url.startswith(OSF_API_BASE)
        assert "registrations" in url

    @patch("agents.publication_bus.osf_prereg_publisher.requests")
    def test_200_also_returns_ok(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(200, text='{"data": {}}')
        OSFPreregPublisher.allowlist = load_allowlist(OSF_PREREG_SURFACE, ["prereg-1"])
        publisher = OSFPreregPublisher(token="test-token")
        result = publisher.publish(PublisherPayload(target="prereg-1", text="body"))
        assert result.ok is True

    @patch("agents.publication_bus.osf_prereg_publisher.requests")
    def test_401_returns_error(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(401, text="unauthorized")
        OSFPreregPublisher.allowlist = load_allowlist(OSF_PREREG_SURFACE, ["prereg-1"])
        publisher = OSFPreregPublisher(token="bad-token")
        result = publisher.publish(PublisherPayload(target="prereg-1", text="body"))
        assert result.error is True
        assert "401" in result.detail or "auth" in result.detail.lower()

    @patch("agents.publication_bus.osf_prereg_publisher.requests")
    def test_403_returns_error(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(403, text="forbidden")
        OSFPreregPublisher.allowlist = load_allowlist(OSF_PREREG_SURFACE, ["prereg-1"])
        publisher = OSFPreregPublisher(token="test-token")
        result = publisher.publish(PublisherPayload(target="prereg-1", text="body"))
        assert result.error is True

    @patch("agents.publication_bus.osf_prereg_publisher.requests")
    def test_429_returns_error_rate_limited(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(429, text="rate limited")
        OSFPreregPublisher.allowlist = load_allowlist(OSF_PREREG_SURFACE, ["prereg-1"])
        publisher = OSFPreregPublisher(token="test-token")
        result = publisher.publish(PublisherPayload(target="prereg-1", text="body"))
        assert result.error is True
        assert "rate" in result.detail.lower() or "429" in result.detail

    @patch("agents.publication_bus.osf_prereg_publisher.requests")
    def test_5xx_returns_error(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(503, text="server error")
        OSFPreregPublisher.allowlist = load_allowlist(OSF_PREREG_SURFACE, ["prereg-1"])
        publisher = OSFPreregPublisher(token="test-token")
        result = publisher.publish(PublisherPayload(target="prereg-1", text="body"))
        assert result.error is True

    def test_missing_token_returns_refused(self) -> None:
        OSFPreregPublisher.allowlist = load_allowlist(OSF_PREREG_SURFACE, ["prereg-1"])
        publisher = OSFPreregPublisher(token="")
        result = publisher.publish(PublisherPayload(target="prereg-1", text="body"))
        assert result.refused is True
        assert "credential" in result.detail.lower() or "token" in result.detail.lower()

    def test_allowlist_deny_short_circuits(self) -> None:
        OSFPreregPublisher.allowlist = load_allowlist(OSF_PREREG_SURFACE, [])
        publisher = OSFPreregPublisher(token="test-token")
        result = publisher.publish(PublisherPayload(target="prereg-1", text="body"))
        assert result.refused is True

    @patch("agents.publication_bus.osf_prereg_publisher.requests")
    def test_request_exception_returns_error(self, mock_requests: MagicMock) -> None:
        import requests as _requests_lib

        mock_requests.post.side_effect = _requests_lib.RequestException("offline")
        mock_requests.RequestException = _requests_lib.RequestException
        OSFPreregPublisher.allowlist = load_allowlist(OSF_PREREG_SURFACE, ["prereg-1"])
        publisher = OSFPreregPublisher(token="test-token")
        result = publisher.publish(PublisherPayload(target="prereg-1", text="body"))
        assert result.error is True

    @patch("agents.publication_bus.osf_prereg_publisher.requests")
    def test_bearer_authorization_header(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(201)
        OSFPreregPublisher.allowlist = load_allowlist(OSF_PREREG_SURFACE, ["prereg-1"])
        publisher = OSFPreregPublisher(token="my-pat-token")
        publisher.publish(PublisherPayload(target="prereg-1", text="body"))
        kwargs = mock_requests.post.call_args.kwargs
        headers = kwargs.get("headers", {})
        auth = headers.get("Authorization", "")
        assert auth == "Bearer my-pat-token"

    @patch("agents.publication_bus.osf_prereg_publisher.requests")
    def test_jsonapi_content_type(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(201)
        OSFPreregPublisher.allowlist = load_allowlist(OSF_PREREG_SURFACE, ["prereg-1"])
        publisher = OSFPreregPublisher(token="t")
        publisher.publish(PublisherPayload(target="prereg-1", text="body"))
        kwargs = mock_requests.post.call_args.kwargs
        headers = kwargs.get("headers", {})
        assert headers.get("Content-Type") == "application/vnd.api+json"

    @patch("agents.publication_bus.osf_prereg_publisher.requests")
    def test_payload_uses_jsonapi_registrations_envelope(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(201)
        OSFPreregPublisher.allowlist = load_allowlist(OSF_PREREG_SURFACE, ["prereg-1"])
        publisher = OSFPreregPublisher(token="t")
        publisher.publish(
            PublisherPayload(
                target="prereg-1",
                text="abstract body",
                metadata={"title": "My Prereg"},
            )
        )
        kwargs = mock_requests.post.call_args.kwargs
        body = kwargs.get("json", {})
        assert body.get("data", {}).get("type") == "registrations"
        assert "title" in body.get("data", {}).get("attributes", {})


class TestSurfaceRegistryEntry:
    def test_osf_prereg_in_surface_registry(self) -> None:
        from agents.publication_bus.surface_registry import (
            SURFACE_REGISTRY,
            AutomationStatus,
        )

        assert OSF_PREREG_SURFACE in SURFACE_REGISTRY
        spec = SURFACE_REGISTRY[OSF_PREREG_SURFACE]
        assert spec.automation_status == AutomationStatus.FULL_AUTO
