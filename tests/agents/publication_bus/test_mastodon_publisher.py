"""Tests for ``agents.publication_bus.mastodon_publisher``."""

from __future__ import annotations

import json
from unittest import mock

from agents.publication_bus.mastodon_publisher import (
    MASTODON_SURFACE,
    MastodonPublisher,
)
from agents.publication_bus.publisher_kit import PublisherPayload
from agents.publication_bus.publisher_kit.allowlist import load_allowlist


class TestSurfaceMetadata:
    def test_surface_name_is_mastodon_post(self) -> None:
        assert MastodonPublisher.surface_name == MASTODON_SURFACE
        assert MASTODON_SURFACE == "mastodon-post"

    def test_does_not_require_legal_name(self) -> None:
        assert MastodonPublisher.requires_legal_name is False


class TestPublisher:
    def test_emit_posts_status_and_returns_receipt_detail(self) -> None:
        client = mock.Mock()
        client.status_post.return_value = mock.Mock(
            uri="tag:mastodon.test,2026-05-12:objectId=1234:objectType=Status",
            url="https://mastodon.test/@hapax/1234",
        )
        MastodonPublisher.allowlist = load_allowlist(MASTODON_SURFACE, ["hapax"])
        publisher = MastodonPublisher(
            instance_url="https://mastodon.test",
            access_token="tok",
            client_factory=mock.Mock(return_value=client),
        )

        result = publisher.publish(PublisherPayload(target="hapax", text="post content"))

        assert result.ok is True
        client.status_post.assert_called_once_with("post content")
        detail = json.loads(result.detail)
        assert detail == {
            "public_url": "https://mastodon.test/@hapax/1234",
            "uri": "tag:mastodon.test,2026-05-12:objectId=1234:objectType=Status",
        }

    def test_missing_creds_returns_refused(self) -> None:
        MastodonPublisher.allowlist = load_allowlist(MASTODON_SURFACE, ["hapax"])
        publisher = MastodonPublisher(instance_url="", access_token="")
        result = publisher.publish(PublisherPayload(target="hapax", text="post"))
        assert result.refused is True
        assert "credential" in result.detail.lower()

    def test_allowlist_deny_short_circuits(self) -> None:
        MastodonPublisher.allowlist = load_allowlist(MASTODON_SURFACE, [])
        publisher = MastodonPublisher(instance_url="https://mastodon.test", access_token="tok")
        result = publisher.publish(PublisherPayload(target="hapax", text="post"))
        assert result.refused is True

    def test_status_exception_returns_error(self) -> None:
        client = mock.Mock()
        client.status_post.side_effect = RuntimeError("api down")
        MastodonPublisher.allowlist = load_allowlist(MASTODON_SURFACE, ["hapax"])
        publisher = MastodonPublisher(
            instance_url="https://mastodon.test",
            access_token="tok",
            client_factory=mock.Mock(return_value=client),
        )

        result = publisher.publish(PublisherPayload(target="hapax", text="post"))

        assert result.error is True
