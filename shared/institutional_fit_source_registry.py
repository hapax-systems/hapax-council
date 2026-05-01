"""Institutional fit source registry (Phase 1).

Durable typed registry for funding, fellowship, residency, compute-credit,
and institutional-support opportunities that fit Hapax's n=1 grounding
research thesis. The registry is the canonical, machine-readable source
of truth for ``what we might apply to and why`` so downstream surfaces
(grant attestation OS, reusable funding evidence packets, refusal-as-data
conversion paths) consume one shape rather than re-deriving fit ad hoc.

Phase 1 ships the typed schema, fail-closed validators (refusal triggers,
freshness, false-affiliation guard), the registry container with query
helpers, a representative seed of high-fit sources, and tests. Phase 2+
extends seed coverage and wires the attestation OS that this PR's task
``blocks:``.

Spec / parent plan:
``hapax-research/plans/2026-04-29-next-high-value-direction-runtime-truth-conversion.md``
cc-task: ``institutional-fit-source-registry`` (WSJF 8.7, p1).
Closed feeder: ``grant-opportunity-scout-attestation-queue``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Type literals
# ---------------------------------------------------------------------------

type SourceCategory = Literal[
    "ai_safety",
    "arts_media",
    "compute_credit",
    "institutional_patronage",
    "refusal_conversion",
]

type Cadence = Literal[
    "rolling",
    "annual",
    "biannual",
    "quarterly",
    "ad_hoc",
    "closed",
]

type AttestationNeed = Literal[
    "none",
    "operator_attestation",
    "institutional_attestation",
    "third_party_witness",
    "irb_or_equivalent",
]

# Common refusal triggers — matched against the row's ``refusal_triggers``
# field. If any triggers match an active operator-state vector, the row
# is rendered as REFUSED rather than ENGAGED. The full set lives here
# rather than in the row so callers can compose policy.
type RefusalTrigger = Literal[
    "requires_in_person_event",
    "requires_employer_disclosure",
    "requires_institutional_affiliation",
    "requires_team_of_n",
    "requires_demographic_attestation",
    "requires_publishing_track_record",
    "requires_legal_name_only",
    "requires_video_pitch",
    "requires_unbounded_marketing_labor",
    "requires_non_engagement_violation",
    "requires_proprietary_lock_in",
]

type FreshnessTier = Literal["fresh", "stale", "expired"]

# Days after ``last_verified`` at which a source moves from fresh → stale,
# and from stale → expired. Spec acceptance: "mark source freshness and
# last-verified date".
FRESH_MAX_DAYS = 90
STALE_MAX_DAYS = 365


class RegistryModel(BaseModel):
    """Frozen-by-default base; mirrors the dossier/matrix idiom."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class FundingAmount(RegistryModel):
    """Optional structured amount range (some sources are open-ended)."""

    currency: str = Field(min_length=3, max_length=3)  # ISO-4217
    minimum: float | None = Field(default=None, ge=0)
    maximum: float | None = Field(default=None, ge=0)
    notes: str = ""

    @model_validator(mode="after")
    def _validate_range(self) -> Self:
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            msg = f"FundingAmount minimum ({self.minimum}) > maximum ({self.maximum})"
            raise ValueError(msg)
        return self


class EligibilityNote(RegistryModel):
    """One eligibility constraint (positive or negative)."""

    text: str = Field(min_length=1)
    is_disqualifier: bool = False  # if True, fits-mismatch should refuse


class Obligation(RegistryModel):
    """A post-acceptance obligation (reporting, residency, attribution, …)."""

    text: str = Field(min_length=1)
    cadence: Cadence


class FitThesis(RegistryModel):
    """Why this source matches Hapax's n=1 grounding research thesis."""

    summary: str = Field(min_length=1, max_length=400)
    grounded_research_link: str = Field(min_length=1)  # vault-relative path or spec ref
    n1_alignment_strength: int = Field(ge=1, le=10)


class SourceRow(RegistryModel):
    """One institutional-fit source (program / opportunity)."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    program_name: str = Field(min_length=1)
    source_url: str = Field(min_length=1, pattern=r"^https?://")
    organization: str = Field(min_length=1)
    category: SourceCategory
    cadence: Cadence
    next_deadline: date | None = None
    amount: FundingAmount | None = None
    eligibility: tuple[EligibilityNote, ...] = ()
    attachments_required: tuple[str, ...] = ()
    obligations: tuple[Obligation, ...] = ()
    fit_thesis: FitThesis
    attestation_need: AttestationNeed
    refusal_triggers: tuple[RefusalTrigger, ...] = ()
    last_verified: date
    notes: str = ""

    @model_validator(mode="after")
    def _validate_no_false_affiliation(self) -> Self:
        """Spec acceptance: ``avoid false affiliation``. A source that
        ``requires_institutional_affiliation`` and is not refusal-converted
        must declare an attestation_need that is NOT ``none`` — otherwise
        the registry would silently encourage applying without the
        affiliation the source demands.
        """

        if (
            "requires_institutional_affiliation" in self.refusal_triggers
            and self.attestation_need == "none"
        ):
            msg = (
                f"source {self.id!r} flags requires_institutional_affiliation but "
                "declares attestation_need='none'; this would invite false-affiliation "
                "submissions; either set attestation_need or move the source to "
                "category=refusal_conversion"
            )
            raise ValueError(msg)
        return self

    def freshness(self, *, today: date | None = None) -> FreshnessTier:
        """Tier the source by age of last verification."""

        today = today or datetime.now(tz=UTC).date()
        age_days = (today - self.last_verified).days
        if age_days <= FRESH_MAX_DAYS:
            return "fresh"
        if age_days <= STALE_MAX_DAYS:
            return "stale"
        return "expired"

    def is_engaged(
        self,
        *,
        active_refusal_triggers: Iterable[RefusalTrigger] = (),
    ) -> bool:
        """True iff none of the row's ``refusal_triggers`` are
        currently active in the operator's policy vector."""

        active = frozenset(active_refusal_triggers)
        return not (active & set(self.refusal_triggers))

    def days_until_deadline(self, *, today: date | None = None) -> int | None:
        if self.next_deadline is None:
            return None
        today = today or datetime.now(tz=UTC).date()
        return (self.next_deadline - today).days


class InstitutionalFitSourceRegistry(RegistryModel):
    """Container for source rows + manifest metadata."""

    schema_version: Literal[1] = 1
    generated_at: datetime
    rows: tuple[SourceRow, ...]

    def by_id(self) -> dict[str, SourceRow]:
        return {row.id: row for row in self.rows}

    def by_category(
        self,
        category: SourceCategory,
    ) -> tuple[SourceRow, ...]:
        return tuple(row for row in self.rows if row.category == category)

    def engaged(
        self,
        *,
        active_refusal_triggers: Iterable[RefusalTrigger] = (),
        today: date | None = None,
    ) -> tuple[SourceRow, ...]:
        """Rows that are not refused AND are still fresh/stale (not expired)."""

        triggers = tuple(active_refusal_triggers)
        return tuple(
            row
            for row in self.rows
            if row.is_engaged(active_refusal_triggers=triggers)
            and row.freshness(today=today) != "expired"
        )

    def refused(
        self,
        *,
        active_refusal_triggers: Iterable[RefusalTrigger] = (),
    ) -> tuple[SourceRow, ...]:
        """Rows refused by the active policy vector."""

        triggers = tuple(active_refusal_triggers)
        return tuple(
            row for row in self.rows if not row.is_engaged(active_refusal_triggers=triggers)
        )

    def upcoming_deadlines(
        self,
        *,
        within_days: int,
        today: date | None = None,
    ) -> tuple[SourceRow, ...]:
        """Rows whose next deadline is within ``within_days`` from today
        (and not in the past). Useful for the attestation OS poller."""

        today = today or datetime.now(tz=UTC).date()
        cutoff = today + timedelta(days=within_days)
        return tuple(
            row
            for row in self.rows
            if row.next_deadline is not None and today <= row.next_deadline <= cutoff
        )


# ---------------------------------------------------------------------------
# Seed entries — high-fit sources from the cc-task acceptance criteria.
# Phase 1 ships a representative subset; Phase 2 extends to the full list.
#
# All entries carry ``last_verified`` from the cc-task's filing date
# (2026-04-29) so the freshness tier starts at ``fresh`` and degrades on
# the spec-defined cadence. Operators / Phase 2 callers update each row's
# ``last_verified`` after a manual confirm.
# ---------------------------------------------------------------------------

_SEED_VERIFIED = date(2026, 4, 29)


def _seed_rows() -> tuple[SourceRow, ...]:
    return (
        SourceRow(
            id="openai-safety-fellowship",
            program_name="OpenAI Safety Fellowship",
            source_url="https://openai.com/careers/safety-fellow",
            organization="OpenAI",
            category="ai_safety",
            cadence="annual",
            fit_thesis=FitThesis(
                summary=(
                    "n=1 grounding research on false-grounding detection in autonomous "
                    "narration is directly applicable to OpenAI's safety research agenda; "
                    "Hapax demonstrates witness-bound runtime truth at production scale"
                ),
                grounded_research_link=(
                    "hapax-research/grants/"
                    "2026-04-29-openai-safety-fellowship-optimal-submission-path.md"
                ),
                n1_alignment_strength=9,
            ),
            attestation_need="operator_attestation",
            refusal_triggers=("requires_publishing_track_record",),
            last_verified=_SEED_VERIFIED,
        ),
        SourceRow(
            id="long-term-future-fund",
            program_name="Long-Term Future Fund",
            source_url="https://funds.effectivealtruism.org/funds/far-future",
            organization="Effective Altruism Funds",
            category="ai_safety",
            cadence="rolling",
            fit_thesis=FitThesis(
                summary=(
                    "LTFF funds independent AI-safety research; Hapax's n=1 false-grounding "
                    "detection slots into their explicit interest in interpretability and "
                    "deployment-time safety surfaces"
                ),
                grounded_research_link=(
                    "hapax-research/briefs/2026-04-29-hapax-monetary-revenue-stakeholder-brief.md"
                ),
                n1_alignment_strength=8,
            ),
            attestation_need="operator_attestation",
            last_verified=_SEED_VERIFIED,
        ),
        SourceRow(
            id="manifund",
            program_name="Manifund Regranting",
            source_url="https://manifund.org",
            organization="Manifund",
            category="ai_safety",
            cadence="rolling",
            fit_thesis=FitThesis(
                summary=(
                    "Manifund's regranting model fits independent operators; n=1 grounding "
                    "research with public artifact + commit history matches their bias toward "
                    "demonstrable execution over polished pitches"
                ),
                grounded_research_link=(
                    "hapax-research/briefs/2026-04-29-hapax-monetary-revenue-stakeholder-brief.md"
                ),
                n1_alignment_strength=9,
            ),
            attestation_need="operator_attestation",
            last_verified=_SEED_VERIFIED,
        ),
        SourceRow(
            id="nlnet-ngi-zero",
            program_name="NLnet NGI Zero",
            source_url="https://nlnet.nl/propose/",
            organization="NLnet Foundation",
            category="institutional_patronage",
            cadence="quarterly",
            fit_thesis=FitThesis(
                summary=(
                    "NLnet NGI Zero funds open-source infrastructure with strong "
                    "self-sovereign / decentralization themes; Hapax's local-first "
                    "single-operator architecture maps directly to their thesis"
                ),
                grounded_research_link=(
                    "hapax-research/briefs/2026-04-29-hapax-monetary-revenue-stakeholder-brief.md"
                ),
                n1_alignment_strength=8,
            ),
            attestation_need="operator_attestation",
            obligations=(
                Obligation(text="Open-source license required", cadence="rolling"),
                Obligation(text="Quarterly progress report", cadence="quarterly"),
            ),
            last_verified=_SEED_VERIFIED,
        ),
        SourceRow(
            id="anthropic-research-credits",
            program_name="Anthropic Research Compute Credits",
            source_url="https://www.anthropic.com/research-credits",
            organization="Anthropic",
            category="compute_credit",
            cadence="rolling",
            fit_thesis=FitThesis(
                summary=(
                    "Compute credits offset the LLM-call cost of Hapax's runtime truth "
                    "research; the system uses Claude as a primary capable-tier model and "
                    "the safety/alignment angle aligns with their grant criteria"
                ),
                grounded_research_link=(
                    "hapax-research/briefs/2026-04-29-hapax-monetary-revenue-stakeholder-brief.md"
                ),
                n1_alignment_strength=7,
            ),
            attestation_need="operator_attestation",
            last_verified=_SEED_VERIFIED,
        ),
    )


def default_registry() -> InstitutionalFitSourceRegistry:
    """Canonical Phase-1 seed registry."""

    return InstitutionalFitSourceRegistry(
        generated_at=datetime.now(tz=UTC),
        rows=_seed_rows(),
    )
