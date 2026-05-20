"""Condition edition marketplace publisher.

Consumes eligible editions from the aesthetic condition editions ledger
and generates marketplace-ready catalog manifests. Enforces rights/privacy
gates and keeps purchaser identity out of public state.

Authority case: CASE-LIVESTREAM-RESEARCH-VEHICLE-SUITCASE-PAR
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.aesthetic_condition_editions_ledger import (
    EditionKind,
    EditionMetadata,
    PrivacyClass,
    RightsClass,
    _evaluate_creation_blockers,
)

log = logging.getLogger(__name__)

PUBLISHABLE_RIGHTS: frozenset[RightsClass] = frozenset(
    {
        RightsClass.OPERATOR_OWNED,
        RightsClass.PUBLIC_DOMAIN,
        RightsClass.LICENSED,
    }
)

PUBLISHABLE_PRIVACY: frozenset[PrivacyClass] = frozenset(
    {
        PrivacyClass.FULLY_PUBLIC,
        PrivacyClass.ANONYMIZED,
    }
)


class CatalogStatus(StrEnum):
    CANDIDATE = "candidate"
    MINTED = "minted"
    PUBLISHED = "published"
    SOLD = "sold"
    REFUSED = "refused"
    RIGHTS_BLOCKED = "rights_blocked"


class CatalogFormat(StrEnum):
    STILL = "still"
    LOOP = "loop"
    VISUAL_PACK = "visual_pack"
    ZINE_LOGBOOK = "zine_logbook"
    INSTALLATION_SCREENING = "installation_screening"


class _PublisherModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CatalogEntry(_PublisherModel):
    catalog_id: str = Field(pattern=r"^cat-[a-z0-9_-]+$")
    edition_id: str = Field(min_length=1)
    kind: EditionKind
    format: CatalogFormat
    status: CatalogStatus
    title: str = Field(min_length=1)
    condition_id: str = Field(min_length=1)
    provenance_token: str = Field(min_length=1)
    rights_class: RightsClass
    privacy_class: PrivacyClass
    source_substrates: tuple[str, ...]
    public_event_link: str = Field(min_length=1)
    generated_at: str
    refuse_reason: str | None = None
    purchaser_visible: Literal[False] = False

    @model_validator(mode="after")
    def _purchaser_never_public(self):
        if self.purchaser_visible:
            raise ValueError("purchaser identity must never be in public state")
        return self


class MarketplaceManifest(_PublisherModel):
    schema_version: Literal[1] = 1
    generated_at: str
    entries: tuple[CatalogEntry, ...]
    total_candidates: int = 0
    total_refused: int = 0
    total_rights_blocked: int = 0


class PublishResult(_PublisherModel):
    edition_id: str
    status: CatalogStatus
    reason: str
    catalog_entry: CatalogEntry | None = None


def _edition_to_format(kind: EditionKind) -> CatalogFormat:
    mapping: dict[EditionKind, CatalogFormat] = {
        EditionKind.STILL: CatalogFormat.STILL,
        EditionKind.LOOP: CatalogFormat.LOOP,
        EditionKind.VISUAL_PACK: CatalogFormat.VISUAL_PACK,
        EditionKind.GEM_MURAL: CatalogFormat.STILL,
        EditionKind.CBIP_SIGNAL_EDITION: CatalogFormat.VISUAL_PACK,
        EditionKind.INSTALLATION_SCREENING_PACKAGE: CatalogFormat.INSTALLATION_SCREENING,
    }
    return mapping.get(kind, CatalogFormat.STILL)


def evaluate_edition(edition: EditionMetadata) -> PublishResult:
    """Evaluate a single edition for marketplace eligibility."""
    blockers = _evaluate_creation_blockers(edition)
    if blockers:
        return PublishResult(
            edition_id=edition.edition_id,
            status=CatalogStatus.RIGHTS_BLOCKED,
            reason=f"creation blockers: {', '.join(b.value for b in blockers)}",
        )

    if edition.rights_class not in PUBLISHABLE_RIGHTS:
        return PublishResult(
            edition_id=edition.edition_id,
            status=CatalogStatus.REFUSED,
            reason=f"rights class {edition.rights_class.value} not publishable",
        )

    if edition.privacy_class not in PUBLISHABLE_PRIVACY:
        return PublishResult(
            edition_id=edition.edition_id,
            status=CatalogStatus.REFUSED,
            reason=f"privacy class {edition.privacy_class.value} not publishable",
        )

    now = datetime.now(UTC).isoformat()
    entry = CatalogEntry(
        catalog_id=f"cat-{edition.edition_id}",
        edition_id=edition.edition_id,
        kind=edition.kind,
        format=_edition_to_format(edition.kind),
        status=CatalogStatus.CANDIDATE,
        title=f"{edition.kind.value}: {edition.condition_id}",
        condition_id=edition.condition_id,
        provenance_token=edition.provenance_token,
        rights_class=edition.rights_class,
        privacy_class=edition.privacy_class,
        source_substrates=tuple(s.value for s in edition.source_substrates),
        public_event_link=edition.public_event_link,
        generated_at=now,
    )

    return PublishResult(
        edition_id=edition.edition_id,
        status=CatalogStatus.CANDIDATE,
        reason="eligible for marketplace",
        catalog_entry=entry,
    )


def generate_marketplace_manifest(
    editions: tuple[EditionMetadata, ...],
) -> MarketplaceManifest:
    """Generate a marketplace manifest from a sequence of editions."""
    entries: list[CatalogEntry] = []
    refused = 0
    blocked = 0

    for edition in editions:
        result = evaluate_edition(edition)
        if result.status == CatalogStatus.REFUSED:
            refused += 1
        elif result.status == CatalogStatus.RIGHTS_BLOCKED:
            blocked += 1
        elif result.catalog_entry is not None:
            entries.append(result.catalog_entry)

    return MarketplaceManifest(
        generated_at=datetime.now(UTC).isoformat(),
        entries=tuple(entries),
        total_candidates=len(entries),
        total_refused=refused,
        total_rights_blocked=blocked,
    )


__all__ = [
    "PUBLISHABLE_PRIVACY",
    "PUBLISHABLE_RIGHTS",
    "CatalogEntry",
    "CatalogFormat",
    "CatalogStatus",
    "MarketplaceManifest",
    "PublishResult",
    "evaluate_edition",
    "generate_marketplace_manifest",
]
