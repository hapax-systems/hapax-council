"""Tests for ``agents.marketing.refusal_annex_publisher``."""

from __future__ import annotations

from pathlib import Path

from agents.marketing.refusal_annex_publisher import (
    REFUSAL_ANNEX_SURFACE,
    RefusalAnnexPublisher,
)
from agents.publication_bus.publisher_kit import PublisherPayload
from agents.publication_bus.publisher_kit.allowlist import load_allowlist


class TestSurfaceMetadata:
    def test_surface_name_is_marketing_refusal_annex(self) -> None:
        assert RefusalAnnexPublisher.surface_name == REFUSAL_ANNEX_SURFACE
        assert REFUSAL_ANNEX_SURFACE == "marketing-refusal-annex"

    def test_does_not_require_legal_name(self) -> None:
        assert RefusalAnnexPublisher.requires_legal_name is False


class TestPublisher:
    def test_writes_annex_to_output_dir(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "publications"
        RefusalAnnexPublisher.allowlist = load_allowlist(
            REFUSAL_ANNEX_SURFACE, ["declined-bandcamp"]
        )
        publisher = RefusalAnnexPublisher(output_dir=output_dir)
        result = publisher.publish(
            PublisherPayload(
                target="declined-bandcamp",
                text="# Refusal Annex: Bandcamp\n\nbody\n",
            )
        )
        assert result.ok is True
        out_file = output_dir / "refusal-annex-declined-bandcamp.md"
        assert out_file.exists()
        assert "Refusal Annex: Bandcamp" in out_file.read_text()

    def test_allowlist_deny_returns_refused(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "publications"
        RefusalAnnexPublisher.allowlist = load_allowlist(REFUSAL_ANNEX_SURFACE, [])
        publisher = RefusalAnnexPublisher(output_dir=output_dir)
        result = publisher.publish(
            PublisherPayload(
                target="declined-unknown",
                text="# Refusal Annex\n",
            )
        )
        assert result.refused is True
        assert "allowlist" in result.detail
        # No file written
        assert not (output_dir / "refusal-annex-declined-unknown.md").exists()

    def test_idempotent_replay_overwrites_existing(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "publications"
        RefusalAnnexPublisher.allowlist = load_allowlist(
            REFUSAL_ANNEX_SURFACE, ["declined-bandcamp"]
        )
        publisher = RefusalAnnexPublisher(output_dir=output_dir)
        publisher.publish(PublisherPayload(target="declined-bandcamp", text="first"))
        publisher.publish(PublisherPayload(target="declined-bandcamp", text="second"))
        out_file = output_dir / "refusal-annex-declined-bandcamp.md"
        assert out_file.read_text() == "second"

    def test_creates_output_dir_if_missing(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "nested" / "publications"
        RefusalAnnexPublisher.allowlist = load_allowlist(
            REFUSAL_ANNEX_SURFACE, ["declined-bandcamp"]
        )
        publisher = RefusalAnnexPublisher(output_dir=output_dir)
        result = publisher.publish(PublisherPayload(target="declined-bandcamp", text="x"))
        assert result.ok is True
        assert (output_dir / "refusal-annex-declined-bandcamp.md").exists()


class TestSurfaceRegistry:
    def test_surface_present_in_registry(self) -> None:
        from agents.publication_bus.surface_registry import (
            SURFACE_REGISTRY,
            AutomationStatus,
        )

        assert REFUSAL_ANNEX_SURFACE in SURFACE_REGISTRY
        spec = SURFACE_REGISTRY[REFUSAL_ANNEX_SURFACE]
        assert spec.automation_status == AutomationStatus.FULL_AUTO
