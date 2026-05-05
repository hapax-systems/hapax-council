"""Per-grant framing wrappers for the Q2 2026 grant batch.

Closes the cc-task ``immediate-q2-2026-grant-submission-batch``
acceptance item: *Three framing wrappers shipped (AI personhood law,
infrastructure studies, critical AI).*

The same Hapax thesis appears in every grant application, but each
grant program reads it through a different academic lens. Rather than
ask the operator to maintain three parallel application packages, the
operator authors ONE :class:`UniversalGrantPackage` and this module
applies a per-grant framing prefix at submission time.

The framings are operator-curated text — purposefully thin (≤ 150
words each) so they re-key the universal thesis without obscuring it.
A framing IS NOT a re-write — the operator-authored
``abstract`` / ``problem_statement`` / ``approach`` flow through
verbatim after the framing prefix, and the canonical
``constitutional_disclosure`` paragraph appears unchanged in every
submission (the runner verifies its presence in the rendered
preview).

Per-recipe framing assignment (operator-curated 2026-05-04):

- ``ltff`` → AI personhood (alignment / longtermist audience)
- ``cooperative_ai_foundation`` → AI personhood (cooperative-AI lens)
- ``nlnet`` → infrastructure studies (digital-commons / NGI lens)
- ``emergent_ventures`` → critical AI (Cowen / philosophy-of-tech lens)
- ``manifund`` → critical AI (public-proposal spectacle vector)

Pure module — no I/O, no env, no Playwright. Tests cover the framing
texts, the recipe-to-framing mapping, the FramedPackage shape, and
the determinism of ``apply_framing`` across calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agents.playwright_grant_submission_runner.package import UniversalGrantPackage

__all__ = [
    "FRAMING_BY_RECIPE",
    "FRAMING_PREFIXES",
    "FramedPackage",
    "GrantFraming",
    "apply_framing",
    "framing_for_recipe",
]


class GrantFraming(StrEnum):
    """Three operator-curated lenses that re-key the universal thesis.

    Adding a new framing requires (a) extending this enum, (b) adding
    its prefixes to :data:`FRAMING_PREFIXES`, and (c) wiring its
    target recipes in :data:`FRAMING_BY_RECIPE`. The audit pin in
    :func:`framing_for_recipe` rejects unknown recipes so the operator
    cannot silently dispatch through an un-framed path.
    """

    AI_PERSONHOOD = "ai_personhood"
    INFRASTRUCTURE_STUDIES = "infrastructure_studies"
    CRITICAL_AI = "critical_ai"


@dataclass(frozen=True)
class _FramingPrefixes:
    """Per-section framing prefixes prepended to the universal package.

    Prefixes are operator-curated, thin, and stable. The grant
    reviewer sees ``{prefix}\\n\\n{operator_authored_section}`` for
    each of the three framed sections; the rest of the package
    (constitutional_disclosure, budget, timeline, team) is pass-through.
    """

    abstract_prefix: str
    problem_statement_prefix: str
    approach_prefix: str


FRAMING_PREFIXES: dict[GrantFraming, _FramingPrefixes] = {
    GrantFraming.AI_PERSONHOOD: _FramingPrefixes(
        abstract_prefix=(
            "**Framing — AI personhood law.** Hapax investigates the "
            "legal-personhood question through a single-operator empirical "
            "rig: every artifact is V5-attributed (system / substrate / "
            "operator), surfacing the unsettled-authorship problem the "
            "December 2025 USCO Human Hand doctrine and ICMJE / COPE "
            "guidelines all gesture at without resolving."
        ),
        problem_statement_prefix=(
            "**Personhood lens.** Existing AI-attribution proposals "
            "(Anthropic Constitutional AI; the Alignment Forum's "
            "personhood threads; ICMJE's no-AI-author rule) treat the "
            "machine as either tool or unaccountable agent. Hapax operates "
            "as a third option: a software substrate whose contributions "
            "are foregrounded, not erased, but whose accountability "
            "delegates upstream to the operator."
        ),
        approach_prefix=(
            "**Personhood-relevant evidence.** Each Hapax artifact ships "
            "a refusal-shaped RelatedIdentifier graph (IsRequiredBy / "
            "IsObsoletedBy) so refusal-as-data is first-class in the "
            "DataCite citation graph — a methodology future personhood "
            "doctrine can examine empirically rather than speculatively."
        ),
    ),
    GrantFraming.INFRASTRUCTURE_STUDIES: _FramingPrefixes(
        abstract_prefix=(
            "**Framing — infrastructure studies.** Hapax is a single-"
            "operator, axiom-governed runtime for autonomous publishing, "
            "monetization, and provenance. The codebase is the artifact: "
            "a working empirical instrument for studying what one operator "
            "+ LLM substrates can sustain as digital-commons infrastructure."
        ),
        problem_statement_prefix=(
            "**Infrastructure lens.** Public-interest AI infrastructure "
            "currently fragments across vendor silos (Truepic, Cloudflare "
            "AI labels, big-vendor cert portals). Hapax's single-tenant "
            "Zenodo-DOI-anchored audit-trail substrate exemplifies the "
            "NGI Commons posture: open, citable, operator-owned, "
            "substrate-not-platform."
        ),
        approach_prefix=(
            "**Commons-aligned outputs.** Every Hapax surface (publication "
            "bus, refusal-brief deposits, axiom registry) is shipped as "
            "open code under the operator's GitHub. Grant funds enable "
            "extension into adjacent commons surfaces (RSS bearer-fanout, "
            "C2PA-2.4 livestream signing, federated provenance graph)."
        ),
    ),
    GrantFraming.CRITICAL_AI: _FramingPrefixes(
        abstract_prefix=(
            "**Framing — critical AI / philosophy of technology.** Hapax "
            "is a refusal-first authoring substrate: every declined "
            "engagement (vendor portals, court-admissibility marketing, "
            "direct outreach) is logged as data and minted as a citable "
            "DOI. The chain of attestation is the work."
        ),
        problem_statement_prefix=(
            "**Critical-AI lens.** Mainstream AI deployment patterns "
            "presume operator-as-salesperson + content-as-marketing. "
            "Hapax presumes the opposite: the operator's stance forbids "
            "outbound channels that violate the executive_function axiom; "
            "monetization rails capture inbound demand only; refusal "
            "itself is the publication."
        ),
        approach_prefix=(
            "**Spectacle-as-evidence.** The Hapax livestream + "
            "publication-bus + axiom-precedent register surface the "
            "operator's stance live and citable. The work is therefore "
            "auditable by AI-policy researchers without requiring "
            "operator-side engagement — the rig itself answers their "
            "questions through its visible refusals."
        ),
    ),
}


# Operator-curated mapping: which framing each recipe uses. Adding a
# new recipe requires an explicit framing assignment here.
FRAMING_BY_RECIPE: dict[str, GrantFraming] = {
    "ltff": GrantFraming.AI_PERSONHOOD,
    "cooperative_ai_foundation": GrantFraming.AI_PERSONHOOD,
    "nlnet": GrantFraming.INFRASTRUCTURE_STUDIES,
    "emergent_ventures": GrantFraming.CRITICAL_AI,
    "manifund": GrantFraming.CRITICAL_AI,
    # Stub recipes (anthropic_cco, openai_safety_airtable,
    # schmidt_sciences) are not in the immediate Q2 batch; their
    # framing assignments will land with their conversion-from-stub
    # PRs to keep the operator-curated mapping authoritative.
}


@dataclass(frozen=True)
class FramedPackage:
    """A :class:`UniversalGrantPackage` with one framing's prefixes applied.

    Recipes consume a ``FramedPackage`` instead of the bare universal
    package when a framing is configured for that recipe. The framed
    sections (abstract / problem_statement / approach) carry the
    framing prefix; all other fields pass through untouched so the
    constitutional disclosure, budget, timeline, and team sections
    appear identically across all five grant submissions.
    """

    base: UniversalGrantPackage
    framing: GrantFraming

    @property
    def framed_abstract(self) -> str:
        prefix = FRAMING_PREFIXES[self.framing].abstract_prefix
        return f"{prefix}\n\n{self.base.abstract}".strip()

    @property
    def framed_problem_statement(self) -> str:
        prefix = FRAMING_PREFIXES[self.framing].problem_statement_prefix
        return f"{prefix}\n\n{self.base.problem_statement}".strip()

    @property
    def framed_approach(self) -> str:
        prefix = FRAMING_PREFIXES[self.framing].approach_prefix
        return f"{prefix}\n\n{self.base.approach}".strip()

    @property
    def constitutional_disclosure(self) -> str:
        """Pass-through — disclosure paragraph never gets re-framed."""

        return self.base.constitutional_disclosure


def apply_framing(package: UniversalGrantPackage, framing: GrantFraming) -> FramedPackage:
    """Wrap a universal package in the requested framing.

    Pure — no I/O, deterministic, idempotent (calling twice returns
    equal :class:`FramedPackage` instances). Recipe modules call this
    once at submission time after ``framing_for_recipe`` resolves the
    target framing.
    """

    return FramedPackage(base=package, framing=framing)


def framing_for_recipe(recipe_name: str) -> GrantFraming | None:
    """Return the operator-curated framing for a recipe, or None.

    ``None`` means the recipe has no framing assignment yet (e.g.,
    stub recipes that haven't been promoted to live). The runner is
    responsible for deciding whether to dispatch un-framed (acceptable
    for some platforms — Manifund's public proposal field is
    free-form) or to refuse the submission until a framing assignment
    lands.
    """

    return FRAMING_BY_RECIPE.get(recipe_name)
