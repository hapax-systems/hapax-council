"""CapabilityEvidenceCard — evidence wrapper, not authority grant.

Cards describe what a capability can and cannot prove, with freshness,
privacy, consumer-permission, and blocking-card gates. A card CANNOT
authorize route dispatch, platform launch, or resource allocation —
it is strictly an evidence container that consumers query for
admissibility before acting on their own authority.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LifecycleStatus(StrEnum):
    DRAFT = "draft"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"
    TOMBSTONED = "tombstoned"


class PrivacyClass(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    OPERATOR_ONLY = "operator_only"
    CONSENT_GATED = "consent_gated"


_PRIVACY_HIERARCHY: dict[PrivacyClass, int] = {
    PrivacyClass.PUBLIC: 0,
    PrivacyClass.INTERNAL: 1,
    PrivacyClass.OPERATOR_ONLY: 2,
    PrivacyClass.CONSENT_GATED: 3,
}


class CardAdmissibility(BaseModel):
    model_config = ConfigDict(frozen=True)

    admissible: bool
    reason: str | None = None


class CapabilityEvidenceCard(BaseModel):
    """Evidence wrapper for a capability claim. Does not grant route authority."""

    model_config = ConfigDict(frozen=True)

    card_id: str = Field(min_length=1)
    target: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    producer: str = Field(min_length=1)
    consumer_permissions: list[str] = Field(default_factory=list)
    freshness_deadline: datetime | None = None
    privacy_class: PrivacyClass = PrivacyClass.INTERNAL
    lifecycle_status: LifecycleStatus = LifecycleStatus.DRAFT
    limitations: list[str] = Field(default_factory=list)
    cannot_prove: str | None = None
    blocking_card_ids: list[str] = Field(default_factory=list)
    supersedes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def is_fresh(self, *, now: datetime | None = None) -> bool:
        if self.freshness_deadline is None:
            return True
        current = now or datetime.now(UTC)
        if self.freshness_deadline.tzinfo is None:
            return current.replace(tzinfo=None) <= self.freshness_deadline
        return current <= self.freshness_deadline

    def is_admissible_for(
        self,
        consumer: str,
        context_privacy: PrivacyClass,
        *,
        now: datetime | None = None,
    ) -> CardAdmissibility:
        if self.lifecycle_status != LifecycleStatus.ACCEPTED:
            return CardAdmissibility(
                admissible=False,
                reason=f"lifecycle_status is {self.lifecycle_status}, not accepted",
            )

        if not self.is_fresh(now=now):
            return CardAdmissibility(
                admissible=False,
                reason="freshness_deadline has passed",
            )

        if self.consumer_permissions and consumer not in self.consumer_permissions:
            return CardAdmissibility(
                admissible=False,
                reason=f"consumer {consumer!r} not in consumer_permissions",
            )

        card_level = _PRIVACY_HIERARCHY.get(self.privacy_class, 0)
        context_level = _PRIVACY_HIERARCHY.get(context_privacy, 0)
        if card_level > context_level:
            return CardAdmissibility(
                admissible=False,
                reason=(
                    f"privacy_class {self.privacy_class} is more restrictive "
                    f"than context {context_privacy}"
                ),
            )

        if self.blocking_card_ids:
            return CardAdmissibility(
                admissible=False,
                reason=f"blocked by {len(self.blocking_card_ids)} card(s): "
                + ", ".join(self.blocking_card_ids[:3]),
            )

        if self.cannot_prove is not None:
            return CardAdmissibility(
                admissible=False,
                reason=f"cannot_prove: {self.cannot_prove}",
            )

        return CardAdmissibility(admissible=True)


__all__ = [
    "CapabilityEvidenceCard",
    "CardAdmissibility",
    "LifecycleStatus",
    "PrivacyClass",
]
