"""Tests for ``agents.publication_bus.omg_statuslog_publisher``."""

from __future__ import annotations

from unittest.mock import MagicMock

import requests

from agents.publication_bus.omg_statuslog_publisher import (
    OMG_STATUSLOG_SURFACE,
    OmgLolStatuslogPublisher,
)
from agents.publication_bus.publisher_kit import PublisherPayload


def _payload(target: str = "hapax") -> PublisherPayload:
    return PublisherPayload(
        target=target,
        text="hapax status 02:00Z stream live",
        metadata={"token": "tok", "skip_mastodon_post": True, "timeout_s": 2.0},
    )


class TestSurfaceMetadata:
    def test_surface_name(self) -> None:
        assert OmgLolStatuslogPublisher.surface_name == OMG_STATUSLOG_SURFACE
        assert OMG_STATUSLOG_SURFACE == "omg-lol-statuslog"

    def test_does_not_require_legal_name(self) -> None:
        assert OmgLolStatuslogPublisher.requires_legal_name is False


class TestPublisher:
    def test_emit_posts_statuslog(self) -> None:
        session = MagicMock()
        session.post.return_value.status_code = 200
        publisher = OmgLolStatuslogPublisher(session=session)

        result = publisher.publish(_payload())

        assert result.ok is True
        session.post.assert_called_once()
        assert "address/hapax/statuses" in session.post.call_args.args[0]
        assert session.post.call_args.kwargs["json"] == {
            "content": "hapax status 02:00Z stream live",
            "skip_mastodon_post": True,
        }

    def test_allowlist_deny_short_circuits(self) -> None:
        session = MagicMock()
        publisher = OmgLolStatuslogPublisher(session=session)

        result = publisher.publish(_payload(target="unexpected"))

        assert result.refused is True
        session.post.assert_not_called()

    def test_missing_token_refuses(self) -> None:
        session = MagicMock()
        publisher = OmgLolStatuslogPublisher(session=session)
        payload = PublisherPayload(target="hapax", text="status", metadata={})

        result = publisher.publish(payload)

        assert result.refused is True
        session.post.assert_not_called()

    def test_http_error_returns_error(self) -> None:
        session = MagicMock()
        session.post.return_value.status_code = 500
        publisher = OmgLolStatuslogPublisher(session=session)

        result = publisher.publish(_payload())

        assert result.error is True
        assert result.detail.startswith("http_error")

    def test_network_error_returns_error(self) -> None:
        session = MagicMock()
        session.post.side_effect = requests.exceptions.ConnectionError("dns down")
        publisher = OmgLolStatuslogPublisher(session=session)

        result = publisher.publish(_payload())

        assert result.error is True
        assert result.detail == "network_error"
