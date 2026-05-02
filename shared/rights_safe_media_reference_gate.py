"""Rights-safe media reference gate.

Per cc-task ``rights-safe-media-reference-gate`` (WSJF 9.0). React,
review, comparison, and watch-along formats reference upstream media
to make commentary legible. Without a rights gate those references
drift into rebroadcast / clip-channel territory — a posture the
Hapax constitution explicitly refuses ('not a clip channel, not a
scraper').

This gate is the **fail-CLOSED predicate** every media-reference
emission consults. The gate accepts a ``MediaReferenceProposal`` and
returns a :class:`GateResult` carrying ALLOW / REFUSE / DOWNGRADE
plus a ``fair_use_memo`` describing the four-factor evidence the
operator can take to a rights review.

Phase 0 (this PR) ships the gate as a reusable predicate library;
Phase 1 follow-on wires it into ``react-watchalong-media-reference-
adapter`` and ``content-programme-scheduler-policy``.

Spec reference (acceptance criteria from cc-task):

* Fail closed on unknown rights, stream ripping, full or near-full
  rebroadcast, sparse commentary, or substitution risk.
* Define excerpt plan, transformation evidence, commentary density,
  non-substitution rationale, and monetization decision fields.
* Support link-along and metadata-first modes.
* Define fair-use memo generator as evidence prep, not legal
  automation.
* Integrate Content ID, advertiser suitability, disclosure, and live
  rights kill-switch evidence where available.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

# ── Constants ────────────────────────────────────────────────────────

#: Maximum excerpt fraction (of the upstream work's total runtime) that
#: counts as "excerpt", not "rebroadcast". Above this we DOWNGRADE to
#: link-along / metadata-first mode.
MAX_EXCERPT_FRACTION: float = 0.20

#: Minimum commentary density (commentary seconds / excerpt seconds).
#: Below this the use is "sparse commentary" — closer to clip than
#: criticism. Refuse below this floor.
MIN_COMMENTARY_DENSITY: float = 1.0


class ReferenceMode(enum.StrEnum):
    """The three modes a media reference can take.

    ``link_along`` and ``metadata_first`` are the rights-safer fallbacks
    when ``excerpt`` would not pass the gate.
    """

    EXCERPT = "excerpt"
    """The ward plays a short excerpt of the upstream work alongside
    commentary."""

    LINK_ALONG = "link_along"
    """The ward references the upstream by URL only; no excerpt is
    rendered into the broadcast."""

    METADATA_FIRST = "metadata_first"
    """The ward renders title / creator / cover-art / metadata only,
    no audio or video excerpt."""


class RightsClass(enum.StrEnum):
    """How the upstream rights status was determined."""

    UNKNOWN = "unknown"
    """Rights status not determined; gate fails CLOSED."""

    EXPLICIT_LICENSE = "explicit_license"
    """Operator has an explicit license / agreement (Creative Commons,
    direct grant, public domain)."""

    FAIR_USE_PREP = "fair_use_prep"
    """Operator has prepared a four-factor fair-use memo. Not a legal
    determination — evidence prep only."""

    PLATFORM_PROVIDED = "platform_provided"
    """Platform (YouTube Content ID Match Policy, Twitch Sound Track,
    etc) marks the use as licensed for the operator's account."""

    REFUSED = "refused"
    """Rights cleared as forbidden — must not reference the work."""


class Decision(enum.StrEnum):
    """The gate's three-verdict decision."""

    ALLOW = "allow"
    """Reference may emit as proposed."""

    REFUSE = "refuse"
    """Reference must not emit. The result's ``reason`` carries the
    blocker; the consumer should construct a refusal articulation."""

    DOWNGRADE = "downgrade"
    """Reference may emit only in a more rights-safe mode (e.g.,
    ``link_along`` instead of ``excerpt``). The result's
    ``downgrade_to`` carries the safer mode."""


@dataclass(frozen=True)
class MediaReferenceProposal:
    """One proposed media reference the gate evaluates.

    All fields are operator-supplied / source-system-supplied; the
    gate consults them but does not generate them. Defaults are the
    safest values (UNKNOWN rights, no excerpt plan, monetization
    declined) so missing-evidence configurations fail CLOSED.
    """

    upstream_id: str
    """Stable identifier for the upstream work (URL, ISRC, Content ID,
    etc). Empty string is treated as 'unknown source' and refused."""

    upstream_total_seconds: float
    """Total runtime of the upstream work. Used to compute excerpt
    fraction; zero or negative is treated as 'unknown duration' and
    refused."""

    rights_class: RightsClass = RightsClass.UNKNOWN

    proposed_mode: ReferenceMode = ReferenceMode.EXCERPT

    excerpt_seconds: float = 0.0
    """For excerpt mode, the proposed excerpt duration in seconds."""

    commentary_seconds: float = 0.0
    """Commentary / transformation duration in seconds. Used to compute
    commentary density (commentary / excerpt)."""

    transformation_evidence: str = ""
    """Free-text description of how the excerpt is transformed (frame
    overlay, voice commentary, comparative cut, etc)."""

    non_substitution_rationale: str = ""
    """Operator-authored rationale for why this reference does NOT
    substitute for the upstream work — i.e., why a viewer who watches
    Hapax would still want to watch the upstream."""

    content_id_match: str = ""
    """Platform Content ID match policy result, if known. Free text:
    ``allowed``, ``track``, ``block``, etc. Empty when unknown."""

    advertiser_suitability: str = ""
    """Advertiser-suitability flag from the platform when known."""

    disclosure_text: str = ""
    """Operator's public disclosure of the reference (e.g., 'used
    under fair-use commentary; original at <url>')."""

    live_rights_kill_switch_active: bool = False
    """Operator-controlled kill switch for live broadcast — when True,
    the gate REFUSES regardless of other evidence (the operator has
    asserted rights uncertainty for this run)."""

    monetization_requested: bool = False
    """Whether the operator wants to monetize the rendering format."""


@dataclass(frozen=True)
class FairUseMemo:
    """Four-factor fair-use evidence prep.

    NOT a legal determination — evidence prep only, intended to be
    handed to a rights review. The gate produces this regardless of
    decision so the operator always has the artifact for follow-up.
    """

    purpose_and_character: str
    """Factor 1 — transformation, commentary, criticism, parody."""

    nature_of_work: str
    """Factor 2 — published vs. unpublished, factual vs. creative."""

    amount_and_substantiality: str
    """Factor 3 — fraction of the work used + whether the heart of
    the work is taken."""

    market_effect: str
    """Factor 4 — non-substitution rationale + market harm reasoning."""


@dataclass(frozen=True)
class GateResult:
    decision: Decision
    reason: str
    downgrade_to: ReferenceMode | None = None
    fair_use_memo: FairUseMemo | None = None
    refused_factors: tuple[str, ...] = field(default_factory=tuple)
    """Names of the cc-task acceptance factors that triggered REFUSE
    (used by Phase 1 consumers to surface granular block reasons in
    refusal articulations)."""


def _compose_fair_use_memo(proposal: MediaReferenceProposal) -> FairUseMemo:
    """Compose the four-factor memo from operator-supplied evidence.

    Evidence-prep only; the memo records what the operator asserted,
    not a determination of fair use.
    """
    excerpt_fraction = (
        proposal.excerpt_seconds / proposal.upstream_total_seconds
        if proposal.upstream_total_seconds > 0
        else 0.0
    )
    commentary_density = (
        proposal.commentary_seconds / proposal.excerpt_seconds
        if proposal.excerpt_seconds > 0
        else 0.0
    )
    return FairUseMemo(
        purpose_and_character=(
            proposal.transformation_evidence or "no transformation evidence supplied"
        ),
        nature_of_work=(
            f"upstream_id={proposal.upstream_id!r}, rights_class={proposal.rights_class.value}"
        ),
        amount_and_substantiality=(
            f"excerpt {proposal.excerpt_seconds:.1f}s of "
            f"{proposal.upstream_total_seconds:.1f}s "
            f"({excerpt_fraction * 100:.1f}%); "
            f"commentary density {commentary_density:.2f}"
        ),
        market_effect=(
            proposal.non_substitution_rationale or "no non-substitution rationale supplied"
        ),
    )


def _check_basic_validity(
    proposal: MediaReferenceProposal,
) -> GateResult | None:
    """Pre-check for unknown source / kill-switch / unknown rights.

    Returns a REFUSE result when any of the fail-closed preconditions
    fire; returns None when basic validity passes (caller proceeds to
    mode-specific checks).
    """
    memo = _compose_fair_use_memo(proposal)

    if not proposal.upstream_id:
        return GateResult(
            decision=Decision.REFUSE,
            reason="no upstream_id (unknown source)",
            fair_use_memo=memo,
            refused_factors=("unknown_source",),
        )
    if proposal.upstream_total_seconds <= 0:
        return GateResult(
            decision=Decision.REFUSE,
            reason="upstream_total_seconds <= 0 (unknown duration)",
            fair_use_memo=memo,
            refused_factors=("unknown_duration",),
        )
    if proposal.live_rights_kill_switch_active:
        return GateResult(
            decision=Decision.REFUSE,
            reason="operator kill switch active (live rights uncertainty)",
            fair_use_memo=memo,
            refused_factors=("kill_switch",),
        )
    if proposal.rights_class is RightsClass.REFUSED:
        return GateResult(
            decision=Decision.REFUSE,
            reason="rights_class=REFUSED (forbidden upstream)",
            fair_use_memo=memo,
            refused_factors=("rights_refused",),
        )
    if proposal.rights_class is RightsClass.UNKNOWN:
        return GateResult(
            decision=Decision.REFUSE,
            reason="rights_class=UNKNOWN (fail closed)",
            fair_use_memo=memo,
            refused_factors=("rights_unknown",),
        )
    return None


def _evaluate_excerpt(
    proposal: MediaReferenceProposal,
    *,
    max_excerpt_fraction: float,
    min_commentary_density: float,
) -> GateResult:
    """Excerpt-mode rights checks: fraction, density, transformation,
    non-substitution, advertiser+disclosure obligations."""
    memo = _compose_fair_use_memo(proposal)

    excerpt_fraction = (
        proposal.excerpt_seconds / proposal.upstream_total_seconds
        if proposal.upstream_total_seconds > 0
        else 0.0
    )
    if proposal.excerpt_seconds <= 0:
        return GateResult(
            decision=Decision.REFUSE,
            reason="excerpt mode requires excerpt_seconds > 0",
            fair_use_memo=memo,
            refused_factors=("missing_excerpt_plan",),
        )
    if excerpt_fraction > max_excerpt_fraction:
        return GateResult(
            decision=Decision.DOWNGRADE,
            reason=(
                f"excerpt fraction {excerpt_fraction:.2f} exceeds "
                f"max {max_excerpt_fraction:.2f} (rebroadcast risk)"
            ),
            downgrade_to=ReferenceMode.LINK_ALONG,
            fair_use_memo=memo,
            refused_factors=("rebroadcast_risk",),
        )
    if not proposal.transformation_evidence:
        return GateResult(
            decision=Decision.REFUSE,
            reason="excerpt mode requires transformation_evidence",
            fair_use_memo=memo,
            refused_factors=("no_transformation",),
        )
    if not proposal.non_substitution_rationale:
        return GateResult(
            decision=Decision.REFUSE,
            reason=("excerpt mode requires non_substitution_rationale (substitution risk)"),
            fair_use_memo=memo,
            refused_factors=("substitution_risk",),
        )
    commentary_density = (
        proposal.commentary_seconds / proposal.excerpt_seconds
        if proposal.excerpt_seconds > 0
        else 0.0
    )
    if commentary_density < min_commentary_density:
        return GateResult(
            decision=Decision.REFUSE,
            reason=(
                f"commentary density {commentary_density:.2f} below "
                f"floor {min_commentary_density:.2f} "
                "(sparse commentary risk)"
            ),
            fair_use_memo=memo,
            refused_factors=("sparse_commentary",),
        )
    if proposal.monetization_requested and not proposal.disclosure_text:
        return GateResult(
            decision=Decision.REFUSE,
            reason=("monetization requested but no disclosure_text (advertiser suitability gate)"),
            fair_use_memo=memo,
            refused_factors=("no_disclosure_for_monetization",),
        )
    return GateResult(
        decision=Decision.ALLOW,
        reason=(
            f"excerpt {excerpt_fraction:.2f} of upstream with "
            f"density {commentary_density:.2f}; "
            f"rights_class={proposal.rights_class.value}"
        ),
        fair_use_memo=memo,
    )


def _evaluate_link_along_or_metadata(
    proposal: MediaReferenceProposal,
) -> GateResult:
    """Link-along / metadata-first modes are rights-safer fallbacks;
    they ALLOW once basic validity passes (no excerpt rendered)."""
    memo = _compose_fair_use_memo(proposal)
    return GateResult(
        decision=Decision.ALLOW,
        reason=(
            f"{proposal.proposed_mode.value} mode does not render an "
            "excerpt; rights-safe by construction"
        ),
        fair_use_memo=memo,
    )


def evaluate_media_reference(
    proposal: MediaReferenceProposal,
    *,
    max_excerpt_fraction: float = MAX_EXCERPT_FRACTION,
    min_commentary_density: float = MIN_COMMENTARY_DENSITY,
) -> GateResult:
    """Evaluate one media-reference proposal against the rights gate.

    Returns a :class:`GateResult` with ALLOW / REFUSE / DOWNGRADE +
    structured ``refused_factors`` + a fair-use memo. Consumers should
    surface the memo regardless of decision so the operator has the
    artifact ready for follow-up rights review.
    """
    basic = _check_basic_validity(proposal)
    if basic is not None:
        return basic

    if proposal.proposed_mode is ReferenceMode.EXCERPT:
        return _evaluate_excerpt(
            proposal,
            max_excerpt_fraction=max_excerpt_fraction,
            min_commentary_density=min_commentary_density,
        )
    return _evaluate_link_along_or_metadata(proposal)


__all__ = [
    "MAX_EXCERPT_FRACTION",
    "MIN_COMMENTARY_DENSITY",
    "Decision",
    "FairUseMemo",
    "GateResult",
    "MediaReferenceProposal",
    "ReferenceMode",
    "RightsClass",
    "evaluate_media_reference",
]
