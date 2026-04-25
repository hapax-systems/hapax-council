"""DataCite RelatedIdentifier graph constructor for Zenodo deposits.

Per V5 weave §2.1 PUB-P0-B keystone follow-on
(``pub-bus-zenodo-related-identifier-graph``). Each Zenodo deposit
carries a list of ``relatedIdentifiers`` pointing at named-target
ORCIDs, DOIs, arXiv IDs, and GitHub release URLs so Hapax's outputs
become discoverable via the DataCite citation graph without sending
direct outreach.

DataCite RelatedIdentifier vocabulary reference:
https://datacite-metadata-schema.readthedocs.io/en/4.5/properties/relatedidentifier/

The Hapax-canonical relation types used in publish-bus deposits:

- ``IsCitedBy`` — this artifact is cited by the related target
- ``References`` — this artifact references the related target
- ``IsSupplementTo`` — this artifact supplements the related target
- ``IsObsoletedBy`` — this artifact is obsoleted by the related target
- ``IsRequiredBy`` — this artifact is required by the related target
- ``IsCompiledBy`` — this artifact is compiled from the related target

Identifier types follow DataCite vocabulary: ``DOI``, ``URL``,
``ORCID``, ``arXiv``, ``Handle``, ``ISBN``, ``ISSN``, etc.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RelationType(Enum):
    """DataCite RelatedIdentifier relation types used in Hapax deposits.

    Subset of the full DataCite vocabulary; expansion is allowed but
    each addition should have a documented use-case in the Hapax
    publish-bus.
    """

    IS_CITED_BY = "IsCitedBy"
    REFERENCES = "References"
    IS_SUPPLEMENT_TO = "IsSupplementTo"
    IS_OBSOLETED_BY = "IsObsoletedBy"
    IS_REQUIRED_BY = "IsRequiredBy"
    IS_COMPILED_BY = "IsCompiledBy"


class IdentifierType(Enum):
    """DataCite identifier types used in Hapax deposits."""

    DOI = "DOI"
    URL = "URL"
    ORCID = "ORCID"
    ARXIV = "arXiv"
    HANDLE = "Handle"
    ISBN = "ISBN"
    ISSN = "ISSN"


@dataclass(frozen=True)
class RelatedIdentifier:
    """One DataCite RelatedIdentifier graph edge.

    Carries the related target's identifier, its identifier type, and
    the relation type from the deposit's perspective. ``relation_type``
    is read from the deposit-side: "this deposit IsCitedBy the related
    target" means the deposit cites the target.

    Resource type is optional but recommended; DataCite uses it for
    typed graph traversal (e.g., "show me all Software resources that
    cite this Dataset").
    """

    identifier: str
    identifier_type: IdentifierType
    relation_type: RelationType
    resource_type: str | None = None

    def to_zenodo_dict(self) -> dict[str, str]:
        """Render to the Zenodo REST API's ``related_identifiers`` shape.

        Zenodo's API uses snake_case ``identifier`` / ``relation`` /
        ``scheme`` / ``resource_type`` rather than DataCite's camelCase.
        This method produces the snake_case form.
        """
        result: dict[str, str] = {
            "identifier": self.identifier,
            "relation": self.relation_type.value,
            "scheme": self.identifier_type.value,
        }
        if self.resource_type is not None:
            result["resource_type"] = self.resource_type
        return result


def build_related_identifiers(
    related_orcids: list[str] | None = None,
    cited_dois: list[str] | None = None,
    references_dois: list[str] | None = None,
    supplement_to: str | None = None,
    obsoleted_by: str | None = None,
) -> list[RelatedIdentifier]:
    """Construct a list of RelatedIdentifier edges from typed inputs.

    Convenience constructor for the deposit_builder. Each kwarg
    represents one relation type's targets:

    - ``related_orcids`` — author ORCIDs cited by this deposit
      (``IsCitedBy`` from author-perspective; useful for academic
      author-graph discovery)
    - ``cited_dois`` — DOIs of works this deposit cites
      (``References``)
    - ``references_dois`` — alias for cited_dois (kept for clarity)
    - ``supplement_to`` — DOI of the parent work this supplements
      (``IsSupplementTo``)
    - ``obsoleted_by`` — DOI of the deposit that obsoletes this one
      (``IsObsoletedBy``); typically populated on re-deposit

    Returns a list (order is stable: ORCIDs → cited DOIs → references
    DOIs → supplement → obsoleted-by) so deposit metadata is
    deterministic.
    """
    edges: list[RelatedIdentifier] = []

    for orcid in related_orcids or []:
        edges.append(
            RelatedIdentifier(
                identifier=orcid,
                identifier_type=IdentifierType.ORCID,
                relation_type=RelationType.IS_CITED_BY,
            )
        )

    for doi in cited_dois or []:
        edges.append(
            RelatedIdentifier(
                identifier=doi,
                identifier_type=IdentifierType.DOI,
                relation_type=RelationType.REFERENCES,
            )
        )

    for doi in references_dois or []:
        edges.append(
            RelatedIdentifier(
                identifier=doi,
                identifier_type=IdentifierType.DOI,
                relation_type=RelationType.REFERENCES,
            )
        )

    if supplement_to is not None:
        edges.append(
            RelatedIdentifier(
                identifier=supplement_to,
                identifier_type=IdentifierType.DOI,
                relation_type=RelationType.IS_SUPPLEMENT_TO,
            )
        )

    if obsoleted_by is not None:
        edges.append(
            RelatedIdentifier(
                identifier=obsoleted_by,
                identifier_type=IdentifierType.DOI,
                relation_type=RelationType.IS_OBSOLETED_BY,
            )
        )

    return edges


__all__ = [
    "IdentifierType",
    "RelatedIdentifier",
    "RelationType",
    "build_related_identifiers",
]
