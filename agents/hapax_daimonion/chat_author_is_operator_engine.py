"""ChatAuthorIsOperatorEngine — Bayesian Phase 6c-ii identity claim.

Wraps :class:`shared.claim.ClaimEngine[bool]` to express the identity
claim ``chat_author_is_operator`` for chat / interactive surfaces
(Discord, Bluesky, Mastodon, IRC + persona-similarity). The decision
question this engine answers: *given evidence about a chat author,
what's the calibrated posterior that the author is the operator?*

Multi-source positive-only design (per scope direction
``beta-to-epsilon-2026-04-25-phase-6c-scope-direction.md``):

  * **``authenticated_handle_match``** — True when the chat author's
    cryptographic identifier (Discord user ID, Bluesky DID, Mastodon
    acct, IRC nick + cert) appears in the operator's known-handles set.
    Strong evidence (LR ≫ 1) because authenticated handles are not
    spoofable by chance.
  * **``persona_similarity_above_threshold``** — True when the message
    text scores above a vector-distance threshold against the operator's
    persona-fingerprint. Moderate evidence (LR ≫ 1 but bounded — guests
    can sometimes write in similar register).

Both signals are **positive-only**: absence of a match is *not*
refutation. A generic message from an unknown handle proves nothing
about non-operator-ness — there's no test for "definitely not the
operator," only for "consistent with operator." This is the noisy-OR
shape (Phase 0 schema ``ClaimComposition(operator="noisy_or")``):
each source independently can raise the posterior; none can crash it.

Governance posture (``interpersonal_transparency`` axiom):

  * **Conservative prior** (~0.05): broadcast chat is dominated by
    non-operator authors. The default belief is *not operator* unless
    positive evidence accumulates.
  * **Cautious entry** (``k_enter=4``): a single accidental positive
    (similar-register guest message) does not flip state to
    ``ASSERTED``; sustained agreement is required.
  * **High narration floor** (0.85): when downstream consumers consult
    the posterior for narration / attribution / persistence decisions,
    the convention is "unclear → unknown" rather than "unclear →
    operator." Default ``asserted()`` threshold reflects this.
  * **No per-author state inside the engine**: the engine tracks
    posterior for *one chat author at a time*. The consumer scopes the
    lifecycle (per-conversation, per-message-stream, or per-author with
    explicit lifecycle). This keeps any persistent multi-author cache
    visible at the *consumer* level for governance review, not hidden
    inside this module.

Phase 6c-ii.A (this module) ships the engine + LR derivations + tests +
prior_provenance entry. Phase 6c-ii.B wires it into the consumer
surface (``shared/attribution.py`` chat-author flows + ``director_loop``
+ ``shared/governance/qdrant_gate``). Staged for cleaner audit +
revertability — same pattern as 6c-i.A → 6c-i.B.

Spec: ``docs/research/2026-04-24-universal-bayesian-claim-confidence.md``.
v3-final dispatch: epsilon-canonical Phase 6c.
Scope direction: ``~/.cache/hapax/relay/beta-to-epsilon-2026-04-25-phase-6c-scope-direction.md``.
"""

from __future__ import annotations

from typing import Final

from shared.claim import ClaimEngine, ClaimState, LRDerivation, TemporalProfile

CLAIM_NAME: Final[str] = "chat_author_is_operator"

AUTHENTICATED_HANDLE_SIGNAL: Final[str] = "authenticated_handle_match"
PERSONA_SIMILARITY_SIGNAL: Final[str] = "persona_similarity_above_threshold"

# Calibration: authenticated handle match is high-LR evidence.
# Discord user IDs / Bluesky DIDs / Mastodon acct strings are
# cryptographic identifiers — when the operator is the author the
# handle ~always matches (set membership lookup); when the author is
# someone else the chance of accidentally matching the operator's
# handle is essentially zero (modulo handle-set staleness, which
# this LR records under p_true_given_h0).
DEFAULT_HANDLE_LR: Final[LRDerivation] = LRDerivation(
    signal_name=AUTHENTICATED_HANDLE_SIGNAL,
    claim_name=CLAIM_NAME,
    source_category="expert_elicitation_shelf",
    p_true_given_h1=0.95,
    p_true_given_h0=0.001,
    positive_only=True,
    estimation_reference=(
        "Operator-elicited 2026-04-25 (Phase 6c-ii scope direction); "
        "authenticated handles are cryptographic — false-positive rate "
        "bounded by handle-set staleness, not by collision."
    ),
)

# Calibration: persona-similarity above threshold is moderate-LR.
# The operator's typical message style scores above the threshold ~70%
# of the time; non-operator messages score above the threshold ~5% of
# the time (similar register, common phrasing, copy-paste). LR ≈ 14x.
DEFAULT_PERSONA_LR: Final[LRDerivation] = LRDerivation(
    signal_name=PERSONA_SIMILARITY_SIGNAL,
    claim_name=CLAIM_NAME,
    source_category="expert_elicitation_shelf",
    p_true_given_h1=0.70,
    p_true_given_h0=0.05,
    positive_only=True,
    estimation_reference=(
        "Operator-elicited 2026-04-25 (Phase 6c-ii scope direction); "
        "rough Beta(7,3) for operator above-threshold rate, Beta(1,19) "
        "for non-operator above-threshold rate. Pending live "
        "recalibration after wire-in."
    ),
)


# Asymmetric temporal profile — cautious-enter (k_enter=4) +
# conservative-exit (k_exit=4). Per scope direction:
#
#  * **Cautious entry**: misidentifying as operator is the costly
#    error under interpersonal_transparency — a single accidental
#    positive must not flip state.
#  * **Conservative exit**: once asserted within a conversation, brief
#    no-evidence messages should not flicker the state back to
#    UNCERTAIN — that creates downstream noise (qdrant gate flicker,
#    narration register flicker).
DEFAULT_TEMPORAL_PROFILE: Final[TemporalProfile] = TemporalProfile(
    enter_threshold=0.7,
    exit_threshold=0.3,
    k_enter=4,
    k_exit=4,
    k_uncertain=4,
)

# Conservative prior — broadcast chat is dominated by non-operator
# authors (audience > 1 by design). The interpersonal_transparency
# axiom requires the engine to default to "non-operator" absent
# positive evidence. 0.05 reflects ~1-in-20 baseline message-from-
# operator rate during a typical session (operator interjects, audience
# chats more frequently).
DEFAULT_PRIOR: Final[float] = 0.05

# High narration floor — unclear authors collapse to "[UNKNOWN]" rather
# than mis-attribute. The default ``asserted()`` threshold matches this
# floor so callers that don't pass an explicit threshold inherit the
# governance-correct default.
DEFAULT_NARRATION_FLOOR: Final[float] = 0.85


class ChatAuthorIsOperatorEngine:
    """Calibrated ``chat_author_is_operator`` claim.

    Thin wrapper around :class:`ClaimEngine[bool]`. Exposes the same
    delegation surface (``tick``, ``posterior``, ``state``) for
    ergonomic access from chat-author consumer surfaces.

    Initial-tick semantics: starts at ``UNCERTAIN`` with posterior
    equal to the conservative ``prior`` (0.05 by default). The engine
    reaches ``ASSERTED`` after ``k_enter=4`` consecutive ticks above
    ``enter_threshold=0.7``; remains ``ASSERTED`` until ``k_exit=4``
    consecutive ticks below ``exit_threshold=0.3``.

    Single-author-at-a-time scope: the engine has no author identifier
    in its state. Consumers handling multiple chat authors must
    instantiate one engine per author OR scope a single engine to a
    single sustained interaction (Q&A turn, conversation thread).
    Per-author CACHING is the consumer's responsibility, surfacing
    the persistent-state-about-non-operator-persons concern for
    governance review at the consumer layer (not buried here).
    """

    def __init__(
        self,
        *,
        prior: float = DEFAULT_PRIOR,
        handle_lr: LRDerivation | None = None,
        persona_lr: LRDerivation | None = None,
        temporal_profile: TemporalProfile | None = None,
    ) -> None:
        self._engine: ClaimEngine[bool] = ClaimEngine(
            name=CLAIM_NAME,
            prior=prior,
            temporal_profile=temporal_profile or DEFAULT_TEMPORAL_PROFILE,
            signal_weights={
                AUTHENTICATED_HANDLE_SIGNAL: handle_lr or DEFAULT_HANDLE_LR,
                PERSONA_SIMILARITY_SIGNAL: persona_lr or DEFAULT_PERSONA_LR,
            },
        )

    def tick(
        self,
        *,
        handle_match: bool | None,
        persona_match: bool | None,
    ) -> None:
        """Process one observation across both signals.

        ``None`` is the no-evidence-this-tick case (signal not produced
        for this message — e.g., persona scorer hasn't run, or no
        handle observable). Positive-only semantics mean ``False`` is
        equivalent to ``None`` modulo the explicit recording — neither
        decreases the posterior.
        """
        observations: dict[str, bool | None] = {
            AUTHENTICATED_HANDLE_SIGNAL: handle_match,
            PERSONA_SIMILARITY_SIGNAL: persona_match,
        }
        self._engine.tick(observations)

    @property
    def posterior(self) -> float:
        """Current calibrated posterior in ``[0, 1]``."""
        return self._engine.posterior

    @property
    def state(self) -> ClaimState:
        """Current hysteresis state."""
        return self._engine.state

    def asserted(self, *, threshold: float = DEFAULT_NARRATION_FLOOR) -> bool:
        """Convenience: posterior ≥ threshold.

        Default threshold matches ``DEFAULT_NARRATION_FLOOR`` (0.85) so
        downstream consumers that delegate to ``asserted()`` without
        an explicit threshold inherit the governance-correct
        "unclear → unknown" default.
        """
        return self._engine.posterior >= threshold


__all__ = [
    "AUTHENTICATED_HANDLE_SIGNAL",
    "CLAIM_NAME",
    "ChatAuthorIsOperatorEngine",
    "DEFAULT_HANDLE_LR",
    "DEFAULT_NARRATION_FLOOR",
    "DEFAULT_PERSONA_LR",
    "DEFAULT_PRIOR",
    "DEFAULT_TEMPORAL_PROFILE",
    "PERSONA_SIMILARITY_SIGNAL",
]
