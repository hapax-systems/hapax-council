"""Tests for ``agents.publication_bus.arena_publisher``."""

from __future__ import annotations

from unittest import mock

from agents.publication_bus.arena_publisher import ARENA_SURFACE, ArenaPublisher
from agents.publication_bus.publisher_kit import PublisherPayload
from agents.publication_bus.publisher_kit.allowlist import load_allowlist


class TestSurfaceMetadata:
    def test_surface_name_is_arena_post(self) -> None:
        assert ArenaPublisher.surface_name == ARENA_SURFACE
        assert ARENA_SURFACE == "arena-post"

    def test_does_not_require_legal_name(self) -> None:
        assert ArenaPublisher.requires_legal_name is False


class TestPublisher:
    def test_emit_adds_block_and_returns_success(self) -> None:
        client = mock.Mock()
        ArenaPublisher.allowlist = load_allowlist(ARENA_SURFACE, ["hapax"])
        publisher = ArenaPublisher(
            token="tok",
            channel_slug="hapax-visual-surface",
            client_factory=mock.Mock(return_value=client),
        )

        result = publisher.publish(
            PublisherPayload(
                target="hapax",
                text="block content",
                metadata={"source_url": "https://hapax.example/block"},
            )
        )

        assert result.ok is True
        client.add_block.assert_called_once_with(
            "hapax-visual-surface",
            content="block content",
            source="https://hapax.example/block",
        )

    def test_missing_creds_returns_refused(self) -> None:
        ArenaPublisher.allowlist = load_allowlist(ARENA_SURFACE, ["hapax"])
        publisher = ArenaPublisher(token="", channel_slug="")

        result = publisher.publish(PublisherPayload(target="hapax", text="post"))

        assert result.refused is True
        assert "credential" in result.detail.lower()

    def test_allowlist_deny_short_circuits(self) -> None:
        ArenaPublisher.allowlist = load_allowlist(ARENA_SURFACE, [])
        client_factory = mock.Mock()
        publisher = ArenaPublisher(
            token="tok",
            channel_slug="hapax-visual-surface",
            client_factory=client_factory,
        )

        result = publisher.publish(PublisherPayload(target="hapax", text="post"))

        assert result.refused is True
        client_factory.assert_not_called()

    def test_add_block_exception_returns_error(self) -> None:
        client = mock.Mock()
        client.add_block.side_effect = RuntimeError("api down")
        ArenaPublisher.allowlist = load_allowlist(ARENA_SURFACE, ["hapax"])
        publisher = ArenaPublisher(
            token="tok",
            channel_slug="hapax-visual-surface",
            client_factory=mock.Mock(return_value=client),
        )

        result = publisher.publish(PublisherPayload(target="hapax", text="post"))

        assert result.error is True
