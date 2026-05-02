"""Temporal deictic reference resolver.

Per cc-task ``temporal-deictic-reference-resolver`` (WSJF 10.4, p0).
Operator + autonomous-narration utterances routinely use deictics —
"what you just said on stream", "that thing on livestream", "do that
publicly", "earlier in the broadcast" — that bind to public speech
events, livestream visual referents, public-action proposals, or
private-screen referents. Without a resolver, those deictics either
fall back to free-form prompt completion (hallucination) or cross the
private-public firewall (a constitutional violation).

This module is the **fail-CLOSED resolver** every voice / director /
caption / archive consumer consults to bind a deictic phrase to a
witnessed referent. Phase 0 (this PR) ships the schema + predicate;
Phase 1 wires consumers as the upstream witness index +
broadcast-surface deictic index + voice clause gate land.

Operating law (cc-task §"Best-Version Synthesis"):

* Deictics bind to **witnessed aperture events**, not generic memory.
* Temporal bands orient every world-state claim — no non-temporal
  perceptual claim is allowed.
* Private referents cannot be **laundered into public action** or
  public claim.
* The private/public Hapax relationship becomes fluid without
  becoming unsafe.
* Ambiguous, stale, private-only, or unsupported referents produce
  uncertainty / dry-run / refusal — never silent best-guess.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

# ── Constants ────────────────────────────────────────────────────────

#: Maximum age (seconds) for a public-speech referent to count as
#: "fresh" enough for "just said on stream" deictics. Above this we
#: STALE the referent.
DEFAULT_FRESH_PUBLIC_SPEECH_S: float = 30.0

#: Maximum age (seconds) for a livestream-visual referent.
#: Compositor frames are ephemeral so we keep this tighter than
#: speech.
DEFAULT_FRESH_LIVESTREAM_VISUAL_S: float = 10.0

#: Ambiguity-score threshold above which the resolver returns
#: AMBIGUOUS rather than committing to one candidate. The score is
#: computed as ``1.0 - (top_candidate_weight / sum_of_weights)`` —
#: equal-weight candidates yield 1.0, single-candidate yields 0.0.
AMBIGUITY_REFUSAL_THRESHOLD: float = 0.40


class ReferentKind(enum.StrEnum):
    """The taxonomy of referents the resolver binds to.

    The taxonomy enforces the cc-task private/public firewall:
    ``PRIVATE_*`` referents NEVER appear in public-action / public-
    claim resolutions; ``PUBLIC_*`` referents NEVER appear in
    private-only consumers.
    """

    PUBLIC_SPEECH = "public_speech"
    """A witnessed public broadcast speech event (what Hapax actually
    said on stream)."""

    LIVESTREAM_VISUAL = "livestream_visual"
    """A surface / compositor / WCS referent currently visible on the
    livestream."""

    PUBLIC_ACTION_PROPOSAL = "public_action_proposal"
    """The deictic asks Hapax to do something publicly; binds the
    referent + proposes the action without executing."""

    ARCHIVE = "archive"
    """A VOD / replay span (older than the live freshness window but
    still public)."""

    PRIVATE_SPEECH = "private_speech"
    """A private-channel utterance (operator-private dashboard,
    internal narration)."""

    PRIVATE_SCREEN = "private_screen"
    """A private-screen referent (operator's editor / DURF capture
    not on broadcast)."""


class ScopeIntent(enum.StrEnum):
    """Where the consumer wants to USE the resolved referent.

    The intent gates which ``ReferentKind`` values can satisfy the
    deictic. ``PUBLIC_*`` intents reject ``PRIVATE_*`` referents
    (the firewall) and vice versa.
    """

    PUBLIC_LIVE = "public_live"
    PUBLIC_ARCHIVE = "public_archive"
    PRIVATE_DASHBOARD = "private_dashboard"
    INTERNAL_TRIAGE = "internal_triage"


class Decision(enum.StrEnum):
    """The resolver's verdict on one query."""

    SINGLE_REFERENT = "single_referent"
    """Exactly one candidate matches; result carries the ``referent_id``
    + evidence + span refs."""

    AMBIGUOUS = "ambiguous"
    """Two or more candidates with comparable weight. Consumers should
    surface a clarification prompt rather than picking silently."""

    STALE = "stale"
    """A candidate matches but freshness is exceeded; consumer should
    treat as "the older event you mean is from <span_ref>" rather
    than as a current referent."""

    PRIVATE_ONLY = "private_only"
    """The best candidate is a private referent but the consumer's
    scope_intent is public. The deictic cannot be honored without
    laundering."""

    NO_REFERENT = "no_referent"
    """No candidate matches the deictic at all."""

    REFUSED = "refused"
    """The deictic cannot be resolved at any cost (e.g., asks to
    cross the private-public firewall)."""


@dataclass(frozen=True)
class ReferentCandidate:
    """One witnessed referent the resolver may bind to."""

    referent_id: str
    kind: ReferentKind
    aperture_ref: str
    """Aperture registry reference identifying the surface where the
    referent occurred."""

    captured_at_s: float
    """Unix timestamp when the referent was witnessed."""

    weight: float = 1.0
    """Relevance score in [0.0, 1.0+]. Higher means closer match to
    the deictic phrase. Used for ambiguity computation."""

    evidence_refs: tuple[str, ...] = ()
    """Free-form evidence pointers (chronicle event IDs, public-event
    IDs, frame URIs, etc.)."""

    span_ref: str = ""
    """Reference to a temporal-span registry row anchoring the
    referent in time."""


@dataclass(frozen=True)
class DeicticReferenceQuery:
    """One deictic phrase the resolver evaluates."""

    utterance_text: str
    """Free-form deictic ('what I just said on stream', 'that thing
    on livestream', 'do that publicly', etc)."""

    scope_intent: ScopeIntent
    """Where the consumer wants to use the resolved referent."""

    now_s: float
    """Wall-clock timestamp at query time. Freshness is computed
    against this."""


@dataclass(frozen=True)
class ResolverResult:
    """The resolver's structured verdict."""

    decision: Decision
    referent_id: str = ""
    """Bound referent ID when ``decision == SINGLE_REFERENT``;
    empty string for STALE / AMBIGUOUS / PRIVATE_ONLY / NO_REFERENT
    / REFUSED."""

    referent_kind: ReferentKind | None = None
    aperture_ref: str = ""
    freshness_age_s: float | None = None
    """Age (now - captured_at) of the bound referent in seconds; None
    when no referent bound."""

    ambiguity_score: float = 0.0
    """Computed as ``1.0 - (top_weight / sum_weights)``. 0.0 means
    unambiguous; 1.0 means perfectly equal-weight competitors."""

    scope: ScopeIntent | None = None
    """Echoes the query's scope_intent so consumers can route the
    result without re-passing context."""

    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    span_ref: str = ""

    blockers: tuple[str, ...] = field(default_factory=tuple)
    """Named blockers contributing to non-SINGLE decisions; consumers
    iterate to construct refusal articulations."""

    reason: str = ""
    """Short human-readable summary of the verdict."""


# ── Helpers ──────────────────────────────────────────────────────────


_PUBLIC_INTENTS: frozenset[ScopeIntent] = frozenset(
    {ScopeIntent.PUBLIC_LIVE, ScopeIntent.PUBLIC_ARCHIVE}
)
_PRIVATE_KINDS: frozenset[ReferentKind] = frozenset(
    {ReferentKind.PRIVATE_SPEECH, ReferentKind.PRIVATE_SCREEN}
)
_PUBLIC_KINDS: frozenset[ReferentKind] = frozenset(
    {
        ReferentKind.PUBLIC_SPEECH,
        ReferentKind.LIVESTREAM_VISUAL,
        ReferentKind.PUBLIC_ACTION_PROPOSAL,
        ReferentKind.ARCHIVE,
    }
)


def _is_kind_compatible_with_scope(kind: ReferentKind, scope: ScopeIntent) -> bool:
    """The private/public firewall predicate.

    Public scopes accept only PUBLIC_* kinds. Private/internal scopes
    accept any kind (private dashboards may legitimately reference
    public events too — the firewall only goes one direction).
    """
    if scope in _PUBLIC_INTENTS:
        return kind in _PUBLIC_KINDS
    return True


def _compute_ambiguity_score(weights: list[float]) -> float:
    """``1.0 - (top / total)``; clamped to [0.0, 1.0]."""
    if not weights:
        return 0.0
    total = sum(weights)
    if total <= 0:
        return 0.0
    top = max(weights)
    score = 1.0 - (top / total)
    return max(0.0, min(1.0, score))


def resolve_deictic_reference(
    query: DeicticReferenceQuery,
    candidates: tuple[ReferentCandidate, ...],
    *,
    fresh_public_speech_s: float = DEFAULT_FRESH_PUBLIC_SPEECH_S,
    fresh_livestream_visual_s: float = DEFAULT_FRESH_LIVESTREAM_VISUAL_S,
    ambiguity_threshold: float = AMBIGUITY_REFUSAL_THRESHOLD,
) -> ResolverResult:
    """Bind a deictic phrase to one of the supplied candidates.

    Decision precedence:

      1. No candidates at all → NO_REFERENT.
      2. After firewall filter, no candidates → REFUSED (private
         referent for public intent) or PRIVATE_ONLY when private
         candidates exist but were filtered.
      3. After freshness filter, all candidates stale → STALE
         (returns the freshest stale candidate's metadata for context).
      4. Multiple candidates above ambiguity threshold → AMBIGUOUS.
      5. Otherwise → SINGLE_REFERENT bound to the highest-weight
         survivor.
    """
    # 1. Empty input.
    if not candidates:
        return ResolverResult(
            decision=Decision.NO_REFERENT,
            scope=query.scope_intent,
            blockers=("no_candidates",),
            reason="no candidates supplied for the deictic",
        )

    # 2. Firewall: drop kind/scope mismatches.
    firewall_filtered: list[ReferentCandidate] = []
    private_only_remaining: list[ReferentCandidate] = []
    for c in candidates:
        if _is_kind_compatible_with_scope(c.kind, query.scope_intent):
            firewall_filtered.append(c)
        elif c.kind in _PRIVATE_KINDS:
            private_only_remaining.append(c)

    if not firewall_filtered:
        if private_only_remaining and query.scope_intent in _PUBLIC_INTENTS:
            # Best private candidate exists but consumer wants public.
            # PRIVATE_ONLY communicates this explicitly so the consumer
            # can refuse rather than cross the firewall.
            return ResolverResult(
                decision=Decision.PRIVATE_ONLY,
                scope=query.scope_intent,
                blockers=("firewall_private_for_public_intent",),
                reason=(
                    f"best candidate is private "
                    f"({private_only_remaining[0].kind.value}) "
                    f"but scope_intent={query.scope_intent.value}"
                ),
            )
        return ResolverResult(
            decision=Decision.REFUSED,
            scope=query.scope_intent,
            blockers=("no_compatible_candidate",),
            reason="no candidate satisfies the scope_intent firewall",
        )

    # 3. Freshness filter (per-kind ceilings).
    fresh: list[ReferentCandidate] = []
    stale: list[ReferentCandidate] = []
    for c in firewall_filtered:
        if c.kind is ReferentKind.PUBLIC_SPEECH:
            ceiling = fresh_public_speech_s
        elif c.kind is ReferentKind.LIVESTREAM_VISUAL:
            ceiling = fresh_livestream_visual_s
        else:
            # ARCHIVE / PRIVATE_SCREEN / etc. don't have a freshness
            # gate at this layer; consumer-side policy handles it.
            ceiling = float("inf")
        age = query.now_s - c.captured_at_s
        if age <= ceiling:
            fresh.append(c)
        else:
            stale.append(c)

    if not fresh:
        # All candidates stale; surface the freshest stale one.
        freshest_stale = max(stale, key=lambda c: c.captured_at_s)
        age = query.now_s - freshest_stale.captured_at_s
        return ResolverResult(
            decision=Decision.STALE,
            referent_id=freshest_stale.referent_id,
            referent_kind=freshest_stale.kind,
            aperture_ref=freshest_stale.aperture_ref,
            freshness_age_s=age,
            scope=query.scope_intent,
            evidence_refs=freshest_stale.evidence_refs,
            span_ref=freshest_stale.span_ref,
            blockers=("freshness_exceeded",),
            reason=(
                f"best candidate is stale "
                f"(age={age:.1f}s exceeds {freshest_stale.kind.value} ceiling)"
            ),
        )

    # 4. Ambiguity computation.
    weights = [c.weight for c in fresh]
    ambiguity = _compute_ambiguity_score(weights)
    if ambiguity > ambiguity_threshold and len(fresh) > 1:
        return ResolverResult(
            decision=Decision.AMBIGUOUS,
            ambiguity_score=ambiguity,
            scope=query.scope_intent,
            blockers=("ambiguity_above_threshold",),
            reason=(
                f"{len(fresh)} candidates with ambiguity score "
                f"{ambiguity:.2f} above threshold {ambiguity_threshold:.2f}"
            ),
        )

    # 5. Single best candidate.
    best = max(fresh, key=lambda c: c.weight)
    age = query.now_s - best.captured_at_s
    return ResolverResult(
        decision=Decision.SINGLE_REFERENT,
        referent_id=best.referent_id,
        referent_kind=best.kind,
        aperture_ref=best.aperture_ref,
        freshness_age_s=age,
        ambiguity_score=ambiguity,
        scope=query.scope_intent,
        evidence_refs=best.evidence_refs,
        span_ref=best.span_ref,
        reason=(
            f"single candidate {best.referent_id!r} "
            f"({best.kind.value}, age={age:.1f}s, weight={best.weight:.2f})"
        ),
    )


__all__ = [
    "AMBIGUITY_REFUSAL_THRESHOLD",
    "DEFAULT_FRESH_LIVESTREAM_VISUAL_S",
    "DEFAULT_FRESH_PUBLIC_SPEECH_S",
    "Decision",
    "DeicticReferenceQuery",
    "ReferentCandidate",
    "ReferentKind",
    "ResolverResult",
    "ScopeIntent",
    "resolve_deictic_reference",
]
