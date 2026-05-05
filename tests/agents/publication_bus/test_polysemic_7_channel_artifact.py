"""Tests for the seven-channel polysemic refusal artifact composer."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml

from agents.publication_bus.polysemic_7_channel_artifact import (
    POLYSEMIC_ARTIFACT_BRAID_SCORE,
    POLYSEMIC_ARTIFACT_CHANNEL_BONUS,
    POLYSEMIC_ARTIFACT_SLUG,
    POLYSEMIC_ARTIFACT_TITLE,
    POLYSEMIC_CHANNELS,
    PolysemicSevenChannelArtifact,
    braid_frontmatter,
    build_payload_metadata,
    compose_related_identifiers,
    render_brief_body,
)
from agents.publication_bus.refusal_brief_publisher import DEFAULT_REFUSAL_DEPOSIT_ALLOWLIST
from agents.publication_bus.related_identifier import IdentifierType, RelationType
from scripts.braided_value_snapshot_runner import (
    braid_vector_from_frontmatter,
    recompute_braid_score,
)
from shared.frontmatter import parse_frontmatter

REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_DIR = REPO_ROOT / "docs/published-artifacts/polysemic-7-channel-artifact-compounder"


class TestSlugAndAllowlist:
    def test_slug_matches_cc_task_id(self) -> None:
        assert POLYSEMIC_ARTIFACT_SLUG == "polysemic-7-channel-artifact-compounder"

    def test_title_carries_refused_prefix(self) -> None:
        assert POLYSEMIC_ARTIFACT_TITLE.startswith("Refused:")

    def test_refusal_deposit_allowlist_permits_artifact(self) -> None:
        assert DEFAULT_REFUSAL_DEPOSIT_ALLOWLIST.permits(POLYSEMIC_ARTIFACT_SLUG)


class TestChannels:
    def test_channels_are_exactly_manifesto_v0_ids_1_through_7(self) -> None:
        assert [channel.channel_id for channel in POLYSEMIC_CHANNELS] == [1, 2, 3, 4, 5, 6, 7]

    def test_channel_names_match_schema_taxonomy(self) -> None:
        assert [channel.name for channel in POLYSEMIC_CHANNELS] == [
            "visual",
            "sonic",
            "linguistic",
            "typographic",
            "structural-form",
            "marker-as-membership",
            "authorship",
        ]

    def test_each_channel_surface_exists(self) -> None:
        for channel in POLYSEMIC_CHANNELS:
            assert (ARTIFACT_DIR / channel.artifact_surface).exists(), channel.artifact_surface


class TestBriefBody:
    def test_body_includes_every_channel(self) -> None:
        body = render_brief_body()
        for channel in POLYSEMIC_CHANNELS:
            assert f"| {channel.channel_id} | {channel.name} |" in body
            assert channel.artifact_surface in body

    def test_body_states_no_live_external_commitment(self) -> None:
        body = render_brief_body()
        assert "does not mint a DOI" in body
        assert "live external commitment" in body


class TestMetadata:
    def test_metadata_carries_all_channels_and_braid_bonus(self) -> None:
        metadata = build_payload_metadata()
        assert metadata["slug"] == POLYSEMIC_ARTIFACT_SLUG
        assert metadata["polysemic_channels"] == [
            {
                "id": channel.channel_id,
                "name": channel.name,
                "artifact_surface": channel.artifact_surface,
                "evidence": channel.evidence,
            }
            for channel in POLYSEMIC_CHANNELS
        ]
        assert metadata["braid_channel_bonus"] == POLYSEMIC_ARTIFACT_CHANNEL_BONUS
        assert metadata["braid"]["braid_score"] == POLYSEMIC_ARTIFACT_BRAID_SCORE

    def test_metadata_related_identifiers_are_zenodo_shaped(self) -> None:
        metadata = build_payload_metadata()
        for entry in metadata["related_identifiers"]:
            assert {"identifier", "relation", "scheme"}.issubset(entry)

    def test_related_identifiers_cover_manifesto_and_repo_evidence(self) -> None:
        edges = compose_related_identifiers()
        assert any(edge.relation_type is RelationType.IS_SUPPLEMENT_TO for edge in edges)
        assert any(edge.relation_type is RelationType.REFERENCES for edge in edges)
        assert {edge.identifier_type for edge in edges} == {IdentifierType.DOI, IdentifierType.URL}


class TestBraidFormula:
    NOW = datetime(2026, 5, 5, 3, 28, tzinfo=UTC)

    def test_declared_braid_score_recomputes(self) -> None:
        vector = braid_vector_from_frontmatter(braid_frontmatter())
        assert recompute_braid_score(vector, now=self.NOW) == POLYSEMIC_ARTIFACT_BRAID_SCORE

    def test_full_channel_set_contributes_exactly_point_seven(self) -> None:
        with_channels = dict(braid_frontmatter())
        without_channels = dict(with_channels)
        without_channels["braid_polysemic_channels"] = []

        with_score = recompute_braid_score(
            braid_vector_from_frontmatter(with_channels),
            now=self.NOW,
        )
        without_score = recompute_braid_score(
            braid_vector_from_frontmatter(without_channels),
            now=self.NOW,
        )

        assert with_score is not None
        assert without_score is not None
        assert round(with_score - without_score, 2) == POLYSEMIC_ARTIFACT_CHANNEL_BONUS


class TestStagedDocs:
    def test_source_frontmatter_matches_composer_braid_vector(self) -> None:
        frontmatter, body = parse_frontmatter(ARTIFACT_DIR / "source.md")
        assert frontmatter["slug"] == POLYSEMIC_ARTIFACT_SLUG
        assert frontmatter["braid_polysemic_channels"] == [1, 2, 3, 4, 5, 6, 7]
        assert frontmatter["braid_score"] == POLYSEMIC_ARTIFACT_BRAID_SCORE
        assert "Seven-channel ledger" in body

    def test_metadata_yaml_matches_composer_channels(self) -> None:
        metadata = yaml.safe_load((ARTIFACT_DIR / "metadata.yaml").read_text(encoding="utf-8"))
        assert metadata["slug"] == POLYSEMIC_ARTIFACT_SLUG
        assert metadata["braid"]["channel_bonus"] == POLYSEMIC_ARTIFACT_CHANNEL_BONUS
        assert [entry["id"] for entry in metadata["channels"]] == [1, 2, 3, 4, 5, 6, 7]

    def test_facade_returns_pure_composer_outputs(self) -> None:
        artifact = PolysemicSevenChannelArtifact()
        assert artifact.slug == POLYSEMIC_ARTIFACT_SLUG
        assert artifact.title == POLYSEMIC_ARTIFACT_TITLE
        assert artifact.body() == render_brief_body()
        assert artifact.metadata() == build_payload_metadata()
        assert artifact.channels() == POLYSEMIC_CHANNELS
