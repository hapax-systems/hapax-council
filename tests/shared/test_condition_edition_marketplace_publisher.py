"""Tests for shared.condition_edition_marketplace_publisher."""

from __future__ import annotations

from datetime import UTC, datetime

from shared.aesthetic_condition_editions_ledger import (
    EditionKind,
    EditionMetadata,
    PrivacyClass,
    RightsClass,
    SourceSubstrate,
    SurfaceLane,
)
from shared.condition_edition_marketplace_publisher import (
    CatalogStatus,
    evaluate_edition,
    generate_marketplace_manifest,
)

NOW = datetime.now(UTC)
PROVENANCE = "a" * 32


def _make_edition(
    *,
    edition_id: str = "test-edition-01",
    kind: EditionKind = EditionKind.STILL,
    rights: RightsClass = RightsClass.OPERATOR_OWNED,
    privacy: PrivacyClass = PrivacyClass.FULLY_PUBLIC,
) -> EditionMetadata:
    return EditionMetadata(
        edition_id=edition_id,
        kind=kind,
        condition_id="cond-test-01",
        timestamp=NOW,
        broadcast_id="broadcast-01",
        programme_id="prog-01",
        surface_lane=SurfaceLane.REVERIE,
        frame_ref="frame:001",
        rights_class=rights,
        privacy_class=privacy,
        provenance_token=PROVENANCE,
        source_substrates=(SourceSubstrate.HAPAX_IMAGINATION,),
        public_event_link="urn:hapax:event:test",
    )


def test_eligible_edition_becomes_candidate() -> None:
    edition = _make_edition()
    result = evaluate_edition(edition)
    assert result.status == CatalogStatus.CANDIDATE
    assert result.catalog_entry is not None
    assert result.catalog_entry.edition_id == "test-edition-01"
    assert result.catalog_entry.purchaser_visible is False


def test_operator_only_privacy_refused() -> None:
    edition = _make_edition(privacy=PrivacyClass.OPERATOR_ONLY)
    result = evaluate_edition(edition)
    assert result.status == CatalogStatus.REFUSED
    assert "privacy" in result.reason.lower()


def test_public_domain_rights_allowed() -> None:
    edition = _make_edition(rights=RightsClass.PUBLIC_DOMAIN)
    result = evaluate_edition(edition)
    assert result.status == CatalogStatus.CANDIDATE


def test_licensed_rights_allowed() -> None:
    edition = _make_edition(rights=RightsClass.LICENSED)
    result = evaluate_edition(edition)
    assert result.status == CatalogStatus.CANDIDATE


def test_anonymized_privacy_allowed() -> None:
    edition = _make_edition(privacy=PrivacyClass.ANONYMIZED)
    result = evaluate_edition(edition)
    assert result.status == CatalogStatus.CANDIDATE


def test_manifest_counts() -> None:
    editions = (
        _make_edition(edition_id="ok-1"),
        _make_edition(edition_id="ok-2", rights=RightsClass.PUBLIC_DOMAIN),
        _make_edition(edition_id="refused-1", privacy=PrivacyClass.OPERATOR_ONLY),
    )
    manifest = generate_marketplace_manifest(editions)
    assert manifest.total_candidates == 2
    assert manifest.total_refused == 1
    assert len(manifest.entries) == 2


def test_manifest_empty_editions() -> None:
    manifest = generate_marketplace_manifest(())
    assert manifest.total_candidates == 0
    assert len(manifest.entries) == 0


def test_different_edition_kinds_map_to_formats() -> None:
    for kind in EditionKind:
        edition = _make_edition(edition_id=f"kind-{kind.value}", kind=kind)
        result = evaluate_edition(edition)
        assert result.status == CatalogStatus.CANDIDATE
        assert result.catalog_entry is not None
        assert result.catalog_entry.format is not None


def test_catalog_entry_has_provenance() -> None:
    edition = _make_edition()
    result = evaluate_edition(edition)
    assert result.catalog_entry is not None
    assert result.catalog_entry.provenance_token == PROVENANCE
    assert result.catalog_entry.public_event_link == "urn:hapax:event:test"
