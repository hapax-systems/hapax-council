"""Public support / artifact offer page generator.

Renders a public-facing offer page from the support surface registry
and monetization readiness ledger, respecting no-perk doctrine. The
page can ask for money but MUST NOT create perks, supporter identity,
leaderboards, requests, private access, priority, guarantees, or
subscriber language. Aggregate receipt counts are included only when
the registry's AggregateReceiptPolicy permits.

Generation fails closed when:
- the support registry is missing or rejects validation
- the monetization ledger does not place the support_prompt family in
  a public-monetizable / public-live / public-archive state
- the requested target family is not represented in the ledger

Spec: hapax-research/plans/2026-04-29-autonomous-grounding-revenue-doubling-plan.md
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.conversion_target_readiness import ReadinessState, TargetFamilyId
from shared.monetization_readiness_ledger import MonetizationReadinessLedger
from shared.support_copy_readiness import evaluate_support_copy_readiness
from shared.support_surface_registry import SupportSurfaceRegistry, public_prompt_allowed

#: ReadinessStates under which the page may show live / archive support
#: rails. "blocked", "private-evidence", "dry-run", and "refused" all
#: trigger the refusal-page path; only public-* states render rails.
_PUBLIC_RENDER_STATES: Final[frozenset[ReadinessState]] = frozenset(
    {"public-archive", "public-live", "public-monetizable"}
)

#: ReadinessStates that admit live (not archive-only) public support.
_LIVE_RENDER_STATES: Final[frozenset[ReadinessState]] = frozenset(
    {"public-live", "public-monetizable"}
)

#: Field names that downstream consumers may NOT include in the rendered
#: page. The OfferPage model has no slots for these — they're enforced
#: by Pydantic's `extra="forbid"`. The list here is documentation +
#: regression-pin for the no-perk doctrine.
PROHIBITED_PAGE_FIELDS: Final[tuple[str, ...]] = (
    "payer_identity",
    "supporter_identity",
    "leaderboard",
    "leaderboards",
    "shoutout",
    "shoutouts",
    "requests",
    "private_access",
    "priority",
    "guarantees",
    "subscriber_status",
    "subscriber_language",
    "tier_perks",
    "perks",
)


class OfferPageKind(StrEnum):
    """Discriminator for the two renderable shapes."""

    OFFER = "offer"
    REFUSAL = "refusal"


class _OfferModel(BaseModel):
    """Frozen + extra-forbid base. The extra=forbid is the load-bearing
    no-perk invariant: any consumer that tries to attach a payer_identity
    or perks field gets a ValidationError at construction time."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class SupportRail(_OfferModel):
    """One renderable support rail (e.g. GitHub Sponsors, OSC, Liberapay).

    Mirrors a SupportSurface with the public-safe fields only —
    surface-internal config (refusal_brief_refs, automation_class,
    notes) is stripped before reaching the page.
    """

    surface_id: str
    display_name: str
    money_form: str
    allowed_public_copy: tuple[str, ...]


class RefusalEntry(_OfferModel):
    """Surface that publishes a refusal-as-data instead of a rail.

    Keeps the refusal visible on the page so the operator's stance is
    legible to readers. Carries refusal_brief_refs so the page can link
    to the canonical refusal artefact.
    """

    surface_id: str
    display_name: str
    refusal_brief_refs: tuple[str, ...]


class AggregateReceiptSummary(_OfferModel):
    """Aggregate-only receipt summary; no per-receipt or identity data."""

    aggregate_count: int = Field(ge=0)
    public_fields: tuple[str, ...] = Field(min_length=1)


class OfferPage(_OfferModel):
    """Public offer page assembled from registry + ledger evidence."""

    kind: Literal[OfferPageKind.OFFER] = OfferPageKind.OFFER
    generated_at: datetime
    target_family_id: TargetFamilyId
    readiness_state: ReadinessState
    no_perk_doctrine_summary: str
    rails: tuple[SupportRail, ...]
    refusal_entries: tuple[RefusalEntry, ...]
    aggregate_receipt_summary: AggregateReceiptSummary | None
    artifact_links: tuple[str, ...]

    @model_validator(mode="after")
    def validate_offer_invariants(self) -> OfferPage:
        if self.readiness_state not in _PUBLIC_RENDER_STATES:
            raise ValueError(
                f"OfferPage cannot be constructed in state {self.readiness_state!r}; "
                f"must be one of {sorted(_PUBLIC_RENDER_STATES)}"
            )
        if not self.rails and not self.refusal_entries:
            raise ValueError("OfferPage must include at least one rail OR one refusal entry")
        return self


class RefusalPage(_OfferModel):
    """Returned instead of OfferPage when the ledger blocks public support.

    This is itself a publishable artefact — operators can show why the
    support page is currently unavailable + what evidence is missing.
    """

    kind: Literal[OfferPageKind.REFUSAL] = OfferPageKind.REFUSAL
    generated_at: datetime
    target_family_id: TargetFamilyId
    readiness_state: ReadinessState
    blocked_reason: str
    missing_evidence_dimensions: tuple[str, ...]
    refusal_brief_refs: tuple[str, ...]


def generate_offer_page(
    registry: SupportSurfaceRegistry,
    ledger: MonetizationReadinessLedger,
    *,
    target_family_id: TargetFamilyId = "support_prompt",
    support_surface_id: str = "sponsor_support_copy",
    support_readiness_refs: Mapping[str, bool] | None = None,
    artifact_links: Iterable[str] = (),
    now: datetime | None = None,
) -> OfferPage | RefusalPage:
    """Render an OfferPage or RefusalPage from registry + ledger evidence.

    Returns RefusalPage (NOT raises) when the ledger blocks public
    support — the refusal is itself a publishable artefact. Raises
    only when the inputs are structurally invalid (registry malformed,
    target family unknown).
    """
    when = now or datetime.now(tz=UTC)

    entry = next(
        (e for e in ledger.entries if e.target_family_id == target_family_id),
        None,
    )
    if entry is None:
        raise ValueError(
            f"target_family_id {target_family_id!r} not present in ledger; "
            f"available: {sorted({e.target_family_id for e in ledger.entries})}"
        )

    state = entry.decision.effective_state
    support_readiness = evaluate_support_copy_readiness(
        registry,
        ledger,
        readiness_refs=support_readiness_refs,
        surface_id=support_surface_id,
        target_family_id=target_family_id,
    )
    if state not in _PUBLIC_RENDER_STATES or not support_readiness.public_copy_allowed:
        missing = tuple(sorted(set(entry.relevant_dimensions) - set(entry.satisfied_dimensions)))
        support_missing = tuple(
            str(item)
            for item in (
                *support_readiness.missing_gate_dimensions,
                *support_readiness.missing_readiness_refs,
            )
        )
        if support_missing:
            missing = tuple(dict.fromkeys((*missing, *support_missing)))
        return RefusalPage(
            generated_at=when,
            target_family_id=target_family_id,
            readiness_state=state,
            blocked_reason=(
                f"target family {target_family_id!r} is in state "
                f"{state!r}; support-copy readiness is "
                f"{support_readiness.state!r}; needs public-safe for public offer rendering"
            ),
            missing_evidence_dimensions=missing,
            refusal_brief_refs=support_readiness.refusal_brief_refs
            or tuple(
                ref
                for surface in registry.surfaces
                if surface.decision == "refusal_conversion"
                for ref in surface.refusal_brief_refs
            ),
        )

    rails: list[SupportRail] = []
    refusals: list[RefusalEntry] = []
    readiness_refs = dict(support_readiness_refs or {})
    for surface in registry.surfaces:
        if surface.decision in {"allowed", "guarded"} and public_prompt_allowed(
            registry,
            surface.surface_id,
            readiness_refs,
        ):
            rails.append(
                SupportRail(
                    surface_id=surface.surface_id,
                    display_name=surface.display_name,
                    money_form=surface.money_form,
                    allowed_public_copy=surface.allowed_public_copy,
                )
            )
        elif surface.decision == "refusal_conversion":
            refusals.append(
                RefusalEntry(
                    surface_id=surface.surface_id,
                    display_name=surface.display_name,
                    refusal_brief_refs=surface.refusal_brief_refs,
                )
            )
        # Other decisions (e.g. "evaluate", "blocked") are intentionally
        # dropped — they're not yet ready for public rendering.

    aggregate_summary: AggregateReceiptSummary | None = None
    if state in _LIVE_RENDER_STATES:
        # Live rendering admits aggregate receipts. Aggregate count is
        # 0 here (no live receipts in seed registry); the page uses the
        # registry's public_fields list to show the operator what
        # public-safe receipt fields would render if receipts existed.
        aggregate_summary = AggregateReceiptSummary(
            aggregate_count=0,
            public_fields=registry.aggregate_receipt_policy.public_fields,
        )

    return OfferPage(
        generated_at=when,
        target_family_id=target_family_id,
        readiness_state=state,
        no_perk_doctrine_summary=support_readiness.no_perk_doctrine_summary,
        rails=tuple(rails),
        refusal_entries=tuple(refusals),
        aggregate_receipt_summary=aggregate_summary,
        artifact_links=tuple(artifact_links),
    )


def render_offer_page_markdown(page: OfferPage | RefusalPage) -> str:
    """Render an OfferPage or RefusalPage as plain Markdown.

    Intentionally does not include any HTML, JavaScript, or external
    asset references — the markdown can be embedded into omg.lol,
    GitHub README, or static-site surfaces without sanitization.
    """
    if isinstance(page, RefusalPage):
        lines = [
            "# Support Currently Unavailable",
            "",
            f"_Generated {page.generated_at.isoformat()} • state: `{page.readiness_state}`_",
            "",
            page.blocked_reason,
        ]
        if page.missing_evidence_dimensions:
            lines.append("")
            lines.append("**Missing evidence:**")
            for dim in page.missing_evidence_dimensions:
                lines.append(f"- {dim}")
        if page.refusal_brief_refs:
            lines.append("")
            lines.append("**Refusal briefs:**")
            for ref in page.refusal_brief_refs:
                lines.append(f"- {ref}")
        return "\n".join(lines) + "\n"

    lines = [
        "# Support",
        "",
        f"_Generated {page.generated_at.isoformat()} • state: `{page.readiness_state}`_",
        "",
        page.no_perk_doctrine_summary,
    ]
    if page.rails:
        lines.append("")
        lines.append("## Rails")
        for rail in page.rails:
            lines.append(f"- **{rail.display_name}** ({rail.money_form})")
            for copy in rail.allowed_public_copy:
                lines.append(f"  - {copy}")
    if page.refusal_entries:
        lines.append("")
        lines.append("## Refused Surfaces")
        for entry in page.refusal_entries:
            lines.append(f"- **{entry.display_name}**")
            for ref in entry.refusal_brief_refs:
                lines.append(f"  - {ref}")
    if page.aggregate_receipt_summary is not None:
        lines.append("")
        lines.append("## Aggregate Receipts")
        lines.append(f"- count: {page.aggregate_receipt_summary.aggregate_count}")
        lines.append(f"- public fields: {', '.join(page.aggregate_receipt_summary.public_fields)}")
    if page.artifact_links:
        lines.append("")
        lines.append("## Artifacts")
        for link in page.artifact_links:
            lines.append(f"- {link}")
    return "\n".join(lines) + "\n"
