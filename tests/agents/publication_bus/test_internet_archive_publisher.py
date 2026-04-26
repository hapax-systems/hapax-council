"""Tests for ``agents.publication_bus.internet_archive_publisher``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.publication_bus.internet_archive_publisher import (
    IA_S3_ENDPOINT,
    IA_S3_SURFACE,
    InternetArchiveS3Publisher,
)
from agents.publication_bus.publisher_kit import PublisherPayload
from agents.publication_bus.publisher_kit.allowlist import load_allowlist


def _mock_response(status_code: int, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    return response


class TestSurfaceMetadata:
    def test_surface_name_is_internet_archive_ias3(self) -> None:
        assert InternetArchiveS3Publisher.surface_name == IA_S3_SURFACE
        assert IA_S3_SURFACE == "internet-archive-ias3"

    def test_does_not_require_legal_name(self) -> None:
        assert InternetArchiveS3Publisher.requires_legal_name is False


class TestPublisher:
    @patch("agents.publication_bus.internet_archive_publisher.requests")
    def test_emit_puts_to_ia_s3(self, mock_requests: MagicMock) -> None:
        mock_requests.put.return_value = _mock_response(200, text="OK")
        InternetArchiveS3Publisher.allowlist = load_allowlist(IA_S3_SURFACE, ["item-1"])
        publisher = InternetArchiveS3Publisher(
            access_key="test-access",
            secret_key="test-secret",
        )
        result = publisher.publish(PublisherPayload(target="item-1", text="audio-bytes-go-here"))
        assert result.ok is True
        # PUT against the S3 endpoint
        url = mock_requests.put.call_args[0][0]
        assert url.startswith(IA_S3_ENDPOINT)
        assert "item-1" in url

    @patch("agents.publication_bus.internet_archive_publisher.requests")
    def test_403_returns_error(self, mock_requests: MagicMock) -> None:
        mock_requests.put.return_value = _mock_response(403, text="forbidden")
        InternetArchiveS3Publisher.allowlist = load_allowlist(IA_S3_SURFACE, ["item-1"])
        publisher = InternetArchiveS3Publisher(
            access_key="test-access",
            secret_key="test-secret",
        )
        result = publisher.publish(PublisherPayload(target="item-1", text="data"))
        assert result.error is True

    def test_missing_creds_returns_refused(self) -> None:
        InternetArchiveS3Publisher.allowlist = load_allowlist(IA_S3_SURFACE, ["item-1"])
        publisher = InternetArchiveS3Publisher(access_key="", secret_key="")
        result = publisher.publish(PublisherPayload(target="item-1", text="data"))
        assert result.refused is True
        assert "creds" in result.detail.lower() or "credential" in result.detail.lower()

    def test_allowlist_deny_short_circuits(self) -> None:
        InternetArchiveS3Publisher.allowlist = load_allowlist(IA_S3_SURFACE, [])
        publisher = InternetArchiveS3Publisher(access_key="x", secret_key="y")
        result = publisher.publish(PublisherPayload(target="item-1", text="data"))
        assert result.refused is True

    @patch("agents.publication_bus.internet_archive_publisher.requests")
    def test_request_exception_returns_error(self, mock_requests: MagicMock) -> None:
        import requests as _requests_lib

        mock_requests.put.side_effect = _requests_lib.RequestException("offline")
        mock_requests.RequestException = _requests_lib.RequestException
        InternetArchiveS3Publisher.allowlist = load_allowlist(IA_S3_SURFACE, ["item-1"])
        publisher = InternetArchiveS3Publisher(access_key="x", secret_key="y")
        result = publisher.publish(PublisherPayload(target="item-1", text="data"))
        assert result.error is True

    @patch("agents.publication_bus.internet_archive_publisher.requests")
    def test_authorization_header_uses_lowercase_authorization(
        self,
        mock_requests: MagicMock,
    ) -> None:
        mock_requests.put.return_value = _mock_response(200)
        InternetArchiveS3Publisher.allowlist = load_allowlist(IA_S3_SURFACE, ["item-1"])
        publisher = InternetArchiveS3Publisher(access_key="ACC", secret_key="SEC")
        publisher.publish(PublisherPayload(target="item-1", text="d"))
        kwargs = mock_requests.put.call_args.kwargs
        headers = kwargs.get("headers", {})
        # IA's S3-compat API uses LOW S3 ACC:SEC authorization style
        assert any("LOW " in v for v in headers.values())
