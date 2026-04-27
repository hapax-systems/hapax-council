"""Tests for ``agents.bridgy_adapter`` orchestrator entry-point."""

from __future__ import annotations

from unittest.mock import patch

from agents.bridgy_adapter import (
    WEBLOG_TARGET_URL,
    _source_url_for_artifact,
    publish_artifact,
)
from agents.publication_bus.publisher_kit import PublisherResult
from shared.preprint_artifact import PreprintArtifact


def _artifact(slug: str = "refusal-annex-declined-bandcamp") -> PreprintArtifact:
    return PreprintArtifact(
        slug=slug,
        title="Refusal Annex: Bandcamp",
        body_md="# Refusal\n\nbody",
        surfaces_targeted=["bridgy-webmention-publish"],
    )


class TestSourceUrlForArtifact:
    def test_constructs_omg_lol_weblog_url_from_slug(self) -> None:
        artifact = _artifact("refusal-annex-declined-bandcamp")
        assert (
            _source_url_for_artifact(artifact)
            == "https://hapax.omg.lol/weblog/refusal-annex-declined-bandcamp"
        )

    def test_uses_bare_slug_for_non_annex_artifacts(self) -> None:
        artifact = _artifact("hapax-manifesto-v0")
        assert (
            _source_url_for_artifact(artifact) == "https://hapax.omg.lol/weblog/hapax-manifesto-v0"
        )


class TestPublishArtifact:
    """``publish_artifact`` translates orchestrator → V5 → orchestrator strings."""

    def test_returns_ok_on_publisher_ok(self) -> None:
        with patch("agents.bridgy_adapter.BridgyPublisher") as PublisherCls:
            PublisherCls.return_value.publish.return_value = PublisherResult(
                ok=True, detail="bridgy 201"
            )
            result = publish_artifact(_artifact())
        assert result == "ok"

    def test_returns_denied_on_publisher_refused(self) -> None:
        with patch("agents.bridgy_adapter.BridgyPublisher") as PublisherCls:
            PublisherCls.return_value.publish.return_value = PublisherResult(
                refused=True, detail="bridgy 400"
            )
            result = publish_artifact(_artifact())
        assert result == "denied"

    def test_returns_error_on_publisher_error(self) -> None:
        with patch("agents.bridgy_adapter.BridgyPublisher") as PublisherCls:
            PublisherCls.return_value.publish.return_value = PublisherResult(
                error=True, detail="bridgy 500"
            )
            result = publish_artifact(_artifact())
        assert result == "error"

    def test_passes_allowlisted_target_to_publisher(self) -> None:
        """``payload.target`` must match the BridgyPublisher allowlist
        exactly so the gate doesn't reject every artifact."""
        with patch("agents.bridgy_adapter.BridgyPublisher") as PublisherCls:
            PublisherCls.return_value.publish.return_value = PublisherResult(ok=True)
            publish_artifact(_artifact())
            payload = PublisherCls.return_value.publish.call_args.args[0]
            assert payload.target == WEBLOG_TARGET_URL
            assert payload.target == "https://hapax.omg.lol/weblog"

    def test_passes_source_url_as_payload_text(self) -> None:
        """``payload.text`` is the source URL Bridgy will crawl."""
        with patch("agents.bridgy_adapter.BridgyPublisher") as PublisherCls:
            PublisherCls.return_value.publish.return_value = PublisherResult(ok=True)
            publish_artifact(_artifact("declined-discord-community"))
            payload = PublisherCls.return_value.publish.call_args.args[0]
            assert payload.text == "https://hapax.omg.lol/weblog/declined-discord-community"

    def test_target_in_publisher_allowlist(self) -> None:
        """End-to-end constraint: WEBLOG_TARGET_URL must be in BridgyPublisher
        allowlist or every publish gets rejected at the gate."""
        from agents.publication_bus.bridgy_publisher import BridgyPublisher

        assert BridgyPublisher.allowlist.permits(WEBLOG_TARGET_URL)


class TestSurfaceRegistryWiring:
    """The SURFACE_REGISTRY must point at this adapter for the V5 wire to take effect."""

    def test_orchestrator_registry_routes_to_bridgy_adapter(self) -> None:
        from agents.publish_orchestrator import orchestrator

        entry = orchestrator.SURFACE_REGISTRY.get("bridgy-webmention-publish")
        assert entry == "agents.bridgy_adapter:publish_artifact"

    def test_wire_status_registry_says_wired(self) -> None:
        from agents.publication_bus.wire_status import PUBLISHER_WIRE_REGISTRY

        entry = PUBLISHER_WIRE_REGISTRY["agents.publication_bus.bridgy_publisher"]
        assert entry.status == "WIRED"
