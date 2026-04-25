"""Tests for ``agents.publication_bus.related_identifier``."""

from __future__ import annotations

from agents.publication_bus.related_identifier import (
    IdentifierType,
    RelatedIdentifier,
    RelationType,
    build_related_identifiers,
)


class TestRelatedIdentifierDataclass:
    def test_constructable(self) -> None:
        edge = RelatedIdentifier(
            identifier="10.5281/zenodo.1234567",
            identifier_type=IdentifierType.DOI,
            relation_type=RelationType.IS_CITED_BY,
        )
        assert edge.identifier == "10.5281/zenodo.1234567"

    def test_to_zenodo_dict_minimal(self) -> None:
        edge = RelatedIdentifier(
            identifier="10.5281/zenodo.1234567",
            identifier_type=IdentifierType.DOI,
            relation_type=RelationType.IS_CITED_BY,
        )
        result = edge.to_zenodo_dict()
        assert result == {
            "identifier": "10.5281/zenodo.1234567",
            "relation": "IsCitedBy",
            "scheme": "DOI",
        }

    def test_to_zenodo_dict_with_resource_type(self) -> None:
        edge = RelatedIdentifier(
            identifier="0000-0000-0000-0000",
            identifier_type=IdentifierType.ORCID,
            relation_type=RelationType.IS_CITED_BY,
            resource_type="Software",
        )
        result = edge.to_zenodo_dict()
        assert result["resource_type"] == "Software"


class TestBuildRelatedIdentifiers:
    def test_empty_inputs_produces_empty_list(self) -> None:
        edges = build_related_identifiers()
        assert edges == []

    def test_orcids_become_is_cited_by(self) -> None:
        edges = build_related_identifiers(
            related_orcids=["0000-0001-0000-0001", "0000-0002-0000-0002"]
        )
        assert len(edges) == 2
        for edge in edges:
            assert edge.identifier_type == IdentifierType.ORCID
            assert edge.relation_type == RelationType.IS_CITED_BY

    def test_cited_dois_become_references(self) -> None:
        edges = build_related_identifiers(cited_dois=["10.5281/zenodo.111"])
        assert len(edges) == 1
        assert edges[0].relation_type == RelationType.REFERENCES
        assert edges[0].identifier_type == IdentifierType.DOI

    def test_supplement_to_single_edge(self) -> None:
        edges = build_related_identifiers(supplement_to="10.5281/zenodo.parent")
        assert len(edges) == 1
        assert edges[0].relation_type == RelationType.IS_SUPPLEMENT_TO
        assert edges[0].identifier == "10.5281/zenodo.parent"

    def test_obsoleted_by_single_edge(self) -> None:
        edges = build_related_identifiers(obsoleted_by="10.5281/zenodo.newer")
        assert len(edges) == 1
        assert edges[0].relation_type == RelationType.IS_OBSOLETED_BY

    def test_combined_inputs_preserve_order(self) -> None:
        edges = build_related_identifiers(
            related_orcids=["0000-0001-0000-0001"],
            cited_dois=["10.5281/zenodo.cited"],
            supplement_to="10.5281/zenodo.parent",
            obsoleted_by="10.5281/zenodo.newer",
        )
        # Order: ORCIDs → cited DOIs → supplement → obsoleted-by
        assert len(edges) == 4
        assert edges[0].identifier_type == IdentifierType.ORCID
        assert edges[1].relation_type == RelationType.REFERENCES
        assert edges[2].relation_type == RelationType.IS_SUPPLEMENT_TO
        assert edges[3].relation_type == RelationType.IS_OBSOLETED_BY

    def test_zenodo_dict_round_trip(self) -> None:
        """Each edge renders to a valid Zenodo REST API entry."""
        edges = build_related_identifiers(
            related_orcids=["0000-0001-0000-0001"],
            cited_dois=["10.5281/zenodo.cited"],
        )
        zenodo_payload = [e.to_zenodo_dict() for e in edges]
        assert zenodo_payload == [
            {
                "identifier": "0000-0001-0000-0001",
                "relation": "IsCitedBy",
                "scheme": "ORCID",
            },
            {
                "identifier": "10.5281/zenodo.cited",
                "relation": "References",
                "scheme": "DOI",
            },
        ]
