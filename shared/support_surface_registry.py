"""Support surface registry contract for no-perk support rails."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SurfaceDecision = Literal["allowed", "guarded", "refusal_conversion"]
SurfaceFamily = Literal[
    "platform_native",
    "direct_support",
    "patronage",
    "community",
    "commercial",
    "copy",
]
AutomationClass = Literal["AUTO", "BOOTSTRAP", "GUARDED", "REFUSAL_ARTIFACT"]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = REPO_ROOT / "config" / "support-surface-registry.json"

REQUIRED_SURFACE_IDS: frozenset[str] = frozenset(
    {
        "youtube_ads",
        "youtube_supers",
        "youtube_super_thanks",
        "youtube_memberships_no_perk",
        "liberapay_recurring",
        "lightning_invoice_receive",
        "nostr_zaps",
        "kofi_tips_guarded",
        "github_sponsors",
        "patreon",
        "substack_paid_subscription",
        "discord_community_subscriptions",
        "stripe_payment_links",
        "consulting_as_service",
        "sponsor_support_copy",
    }
)
REQUIRED_REFUSAL_CONVERSIONS: frozenset[str] = frozenset(
    {
        "patreon",
        "substack_paid_subscription",
        "discord_community_subscriptions",
        "stripe_payment_links",
        "consulting_as_service",
    }
)


class NoPerkSupportDoctrine(BaseModel):
    """The copy doctrine that keeps support from becoming a perk surface."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    doctrine_id: Literal["no_perk_instrument_support"]
    support_buys_access: Literal[False]
    support_buys_requests: Literal[False]
    support_buys_private_advice: Literal[False]
    support_buys_priority: Literal[False]
    support_buys_shoutouts: Literal[False]
    support_buys_guarantees: Literal[False]
    support_buys_client_service: Literal[False]
    support_buys_deliverables: Literal[False]
    support_buys_control: Literal[False]
    work_continues_regardless: Literal[True]
    allowed_copy_clauses: tuple[str, ...] = Field(min_length=3)
    forbidden_copy_shapes: tuple[str, ...] = Field(min_length=6)

    @model_validator(mode="after")
    def validate_doctrine(self) -> NoPerkSupportDoctrine:
        clauses = " ".join(self.allowed_copy_clauses).lower()
        required_fragments = (
            "no access",
            "requests",
            "private advice",
            "priority",
            "shoutouts",
            "guarantees",
            "client service",
            "deliverables",
            "control",
            "work continues regardless",
        )
        missing = [fragment for fragment in required_fragments if fragment not in clauses]
        if missing:
            msg = f"no-perk support copy clauses are missing {missing!r}"
            raise ValueError(msg)
        return self


class AggregateReceiptPolicy(BaseModel):
    """Public receipt policy: aggregate-only, no identity projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: Literal["aggregate_only_support_receipts"]
    public_state_aggregate_only: Literal[True]
    per_receipt_public_state_allowed: Literal[False]
    identity_retention_allowed: Literal[False]
    comment_text_retention_allowed: Literal[False]
    public_fields: tuple[str, ...] = Field(min_length=4)
    forbidden_public_fields: tuple[str, ...] = Field(min_length=6)
    private_storage_policy: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_receipt_policy(self) -> AggregateReceiptPolicy:
        required_public = {
            "receipt_count",
            "gross_amount_by_currency",
            "rail_counts",
            "surface_counts",
        }
        missing_public = required_public - set(self.public_fields)
        if missing_public:
            msg = f"aggregate receipt policy missing public fields {sorted(missing_public)!r}"
            raise ValueError(msg)

        required_forbidden = {
            "identity",
            "handle",
            "comment_text",
            "message_text",
            "per_receipt_history",
            "supporter_list",
            "leaderboard",
        }
        missing_forbidden = required_forbidden - set(self.forbidden_public_fields)
        if missing_forbidden:
            msg = (
                "aggregate receipt policy missing forbidden public fields "
                f"{sorted(missing_forbidden)!r}"
            )
            raise ValueError(msg)
        return self


class SupportSurface(BaseModel):
    """One support, patronage, fan-funding, sponsor, or refusal surface."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    surface_id: str = Field(pattern=r"^[a-z0-9_]+$")
    display_name: str = Field(min_length=1)
    surface_family: SurfaceFamily
    money_form: str = Field(min_length=1)
    decision: SurfaceDecision
    automation_class: AutomationClass
    no_perk_required: Literal[True]
    aggregate_only_receipts: Literal[True]
    readiness_gates: tuple[str, ...]
    allowed_public_copy: tuple[str, ...]
    refusal_brief_refs: tuple[str, ...]
    buildable_conversion: str | None
    notes: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_surface_policy(self) -> SupportSurface:
        if self.decision == "refusal_conversion":
            if self.automation_class != "REFUSAL_ARTIFACT":
                msg = f"{self.surface_id} refusal conversion must be REFUSAL_ARTIFACT"
                raise ValueError(msg)
            if not self.refusal_brief_refs:
                msg = f"{self.surface_id} refusal conversion needs refusal brief refs"
                raise ValueError(msg)
            if not self.buildable_conversion:
                msg = f"{self.surface_id} refusal conversion needs buildable conversion"
                raise ValueError(msg)
            if self.allowed_public_copy:
                msg = f"{self.surface_id} refusal conversion cannot publish support copy"
                raise ValueError(msg)
        else:
            if self.automation_class == "REFUSAL_ARTIFACT":
                msg = f"{self.surface_id} active surface cannot be REFUSAL_ARTIFACT"
                raise ValueError(msg)
            if not self.allowed_public_copy:
                msg = f"{self.surface_id} active surface needs allowed public copy"
                raise ValueError(msg)
            if self.buildable_conversion is not None:
                msg = f"{self.surface_id} active surface cannot define conversion text"
                raise ValueError(msg)

        if self.decision == "guarded" and not self.readiness_gates:
            msg = f"{self.surface_id} guarded surface needs readiness gates"
            raise ValueError(msg)
        return self


class SupportSurfaceRegistry(BaseModel):
    """Canonical registry consumed by support copy and payment normalizers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1]
    registry_id: Literal["support_surface_registry"]
    declared_at: datetime
    producer: str = Field(min_length=1)
    source_refs: tuple[str, ...] = Field(min_length=1)
    no_perk_support_doctrine: NoPerkSupportDoctrine
    aggregate_receipt_policy: AggregateReceiptPolicy
    surfaces: tuple[SupportSurface, ...] = Field(min_length=10)

    @model_validator(mode="after")
    def validate_registry_contract(self) -> SupportSurfaceRegistry:
        surface_ids = [surface.surface_id for surface in self.surfaces]
        duplicate_ids = sorted(
            {surface_id for surface_id in surface_ids if surface_ids.count(surface_id) > 1}
        )
        if duplicate_ids:
            msg = f"duplicate support surface ids: {duplicate_ids!r}"
            raise ValueError(msg)

        missing_required = REQUIRED_SURFACE_IDS - set(surface_ids)
        if missing_required:
            msg = f"registry missing required surfaces: {sorted(missing_required)!r}"
            raise ValueError(msg)

        surfaces = {surface.surface_id: surface for surface in self.surfaces}
        wrong_refusals = sorted(
            surface_id
            for surface_id in REQUIRED_REFUSAL_CONVERSIONS
            if surfaces[surface_id].decision != "refusal_conversion"
        )
        if wrong_refusals:
            msg = f"surfaces must be refusal conversions: {wrong_refusals!r}"
            raise ValueError(msg)
        return self

    def by_id(self) -> dict[str, SupportSurface]:
        return {surface.surface_id: surface for surface in self.surfaces}


class SupportReceiptEvent(BaseModel):
    """Private input event shape before aggregate public projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    surface_id: str
    rail: str = Field(min_length=1)
    currency: str = Field(min_length=3, max_length=8)
    amount: float = Field(ge=0)
    occurred_at: datetime


class AggregateSupportReceiptProjection(BaseModel):
    """Public/train-readable support receipt projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    window_started_at: datetime
    window_ended_at: datetime
    receipt_count: int = Field(ge=0)
    gross_amount_by_currency: dict[str, float]
    rail_counts: dict[str, int]
    surface_counts: dict[str, int]
    readiness_state: str
    public_state_aggregate_only: Literal[True] = True
    per_receipt_public_state_allowed: Literal[False] = False


def load_support_surface_registry(path: Path = DEFAULT_REGISTRY_PATH) -> SupportSurfaceRegistry:
    """Load and validate the canonical support surface registry."""

    return SupportSurfaceRegistry.model_validate(json.loads(path.read_text(encoding="utf-8")))


def surfaces_by_decision(
    registry: SupportSurfaceRegistry,
    decision: SurfaceDecision,
) -> tuple[SupportSurface, ...]:
    """Return surfaces with a specific support decision."""

    return tuple(surface for surface in registry.surfaces if surface.decision == decision)


def public_prompt_allowed(
    registry: SupportSurfaceRegistry,
    surface_id: str,
    readiness: Mapping[str, bool],
) -> bool:
    """Decide whether a support prompt may be public for this surface."""

    surface = registry.by_id()[surface_id]
    if surface.decision == "refusal_conversion":
        return False
    return all(readiness.get(gate, False) for gate in surface.readiness_gates)


def build_aggregate_receipt_projection(
    registry: SupportSurfaceRegistry,
    events: Iterable[SupportReceiptEvent],
    *,
    readiness_state: str = "unknown",
) -> AggregateSupportReceiptProjection:
    """Project private receipt events into aggregate-only public state."""

    surface_by_id = registry.by_id()
    event_list = list(events)
    for event in event_list:
        surface = surface_by_id[event.surface_id]
        if surface.decision == "refusal_conversion":
            msg = f"{event.surface_id} is refused and cannot emit support receipts"
            raise ValueError(msg)

    if event_list:
        window_started_at = min(event.occurred_at for event in event_list)
        window_ended_at = max(event.occurred_at for event in event_list)
    else:
        now = datetime.now(tz=UTC)
        window_started_at = now
        window_ended_at = now

    amount_by_currency: dict[str, float] = {}
    rail_counts: Counter[str] = Counter()
    surface_counts: Counter[str] = Counter()
    for event in event_list:
        amount_by_currency[event.currency] = (
            amount_by_currency.get(event.currency, 0.0) + event.amount
        )
        rail_counts[event.rail] += 1
        surface_counts[event.surface_id] += 1

    return AggregateSupportReceiptProjection(
        window_started_at=window_started_at,
        window_ended_at=window_ended_at,
        receipt_count=len(event_list),
        gross_amount_by_currency=dict(amount_by_currency),
        rail_counts=dict(rail_counts),
        surface_counts=dict(surface_counts),
        readiness_state=readiness_state,
    )
