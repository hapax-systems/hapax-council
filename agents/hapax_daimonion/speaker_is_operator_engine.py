"""SpeakerIsOperatorEngine — Bayesian Phase 6c-i identity claim.

Wraps :class:`shared.claim.ClaimEngine[bool]` to express the identity
claim ``speaker_is_operator`` with calibrated posterior + hysteresis.

Surface migrated from: ``agents/hapax_daimonion/perception_loop.py:214``,
which previously produced a raw ``bool`` from the session.speaker
check. The raw signal flips on/off instantly with session state; the
ClaimEngine wrapper adds:

  * **Asymmetric temporal profile** — fast-enter (operator speaks → assert
    immediately, ``k_enter=2``) / slow-exit (silence ≠ absence,
    ``k_exit=10``). A brief pause from the operator does not flip the
    posterior; a sustained silence does.
  * **Calibrated posterior** — single signal but full Bayesian framing
    so future sub-signals (voice biometric match, IR overlap with desk
    zone, contact-mic-keystroke-during-utterance) compose cleanly via
    the ``LRDerivation`` registry.
  * **Hysteresis state machine** — ``ASSERTED`` / ``UNCERTAIN`` /
    ``RETRACTED``, mirroring :class:`PresenceEngine`'s pattern.

Phase 6c-i.A (this module) ships the engine. Phase 6c-i.B wires it into
``perception_loop._tick_consent`` to replace the raw bool consumer.
Staged for cleaner audit + revertability — same pattern as Phase 5
module first / Phase 6 wiring later.

Spec: ``docs/research/2026-04-24-universal-bayesian-claim-confidence.md``.
v3-final dispatch: epsilon-canonical Phase 6c.
Scope direction: ``~/.cache/hapax/relay/beta-to-epsilon-2026-04-25-phase-6c-scope-direction.md``.
"""

from __future__ import annotations

from typing import Final

from shared.claim import ClaimEngine, ClaimState, LRDerivation, TemporalProfile

CLAIM_NAME: Final[str] = "speaker_is_operator"

# Single-signal canonical name. Phase 6c-i.B's wire-in passes this
# string when ticking the engine; subsequent phases (voice biometric,
# IR overlap) add new signal names alongside.
SESSION_SPEAKER_SIGNAL: Final[str] = "session_speaker_says_operator"
VOICE_BIOMETRIC_SIGNAL: Final[str] = "voice_biometric_match"

# Calibration: session.speaker is a self-reported field set by the
# session manager. When the operator is speaking it is ~95% accurate
# (the dominant failure modes are stale state mid-handoff and pre-
# enrollment guests where the field defaults to "operator"). When a
# non-operator is speaking it is ~5% incorrectly stuck on "operator"
# (e.g., session ended without handoff).
DEFAULT_LR: Final[LRDerivation] = LRDerivation(
    signal_name=SESSION_SPEAKER_SIGNAL,
    claim_name=CLAIM_NAME,
    source_category="expert_elicitation_shelf",
    p_true_given_h1=0.95,
    p_true_given_h0=0.05,
    positive_only=False,  # bidirectional — bool flips both ways
    estimation_reference=(
        "Operator-elicited 2026-04-25 (Phase 6c-i scope direction); "
        "calibration window pending live recalibration after wire-in."
    ),
)


# Asymmetric temporal profile — fast-enter (operator speaks → assert
# in 2 ticks) / slow-exit (silence ≠ absence, k_exit=10). Mirrors the
# PresenceEngine pattern but with a more aggressive entry given the
# self-report signal is high-LR.
DEFAULT_TEMPORAL_PROFILE: Final[TemporalProfile] = TemporalProfile(
    enter_threshold=0.7,
    exit_threshold=0.3,
    k_enter=2,
    k_exit=10,
    k_uncertain=4,
)

# Beta(1,1) uniform — single_user axiom + voice biometric structural
# commitments will narrow this once additional signals come online
# (Phase 6c-i.B / 6c-iii). Reference: prior_provenance.yaml.
VOICE_BIOMETRIC_LR: Final[LRDerivation] = LRDerivation(
    signal_name=VOICE_BIOMETRIC_SIGNAL,
    claim_name=CLAIM_NAME,
    source_category="expert_elicitation_shelf",
    p_true_given_h1=0.90,
    p_true_given_h0=0.05,
    positive_only=False,
    estimation_reference=(
        "Shelf estimate 2026-05-21; pyannote embedding cosine similarity "
        "accept >= 0.60, reject < 0.35. Pending live calibration."
    ),
)

DEFAULT_PRIOR: Final[float] = 0.5


class SpeakerIsOperatorEngine:
    """Calibrated ``speaker_is_operator`` claim.

    Thin wrapper around :class:`ClaimEngine[bool]`. Exposes the same
    delegation surface (``tick``, ``posterior``, ``state``) for
    ergonomic access from ``perception_loop._tick_consent``.

    Initial-tick semantics: starts at ``UNCERTAIN`` with posterior
    equal to ``prior``. The engine reaches ``ASSERTED`` after 2
    consecutive ticks above the enter_threshold (per the temporal
    profile); it remains ``ASSERTED`` until 10 consecutive ticks below
    the exit_threshold. This means a momentary silence (one tick of
    False) does NOT retract the assertion — by design.
    """

    def __init__(
        self,
        *,
        prior: float = DEFAULT_PRIOR,
        lr: LRDerivation | None = None,
        temporal_profile: TemporalProfile | None = None,
    ) -> None:
        self._engine: ClaimEngine[bool] = ClaimEngine(
            name=CLAIM_NAME,
            prior=prior,
            temporal_profile=temporal_profile or DEFAULT_TEMPORAL_PROFILE,
            signal_weights={
                SESSION_SPEAKER_SIGNAL: lr or DEFAULT_LR,
                VOICE_BIOMETRIC_SIGNAL: VOICE_BIOMETRIC_LR,
            },
        )

    def tick(
        self,
        *,
        session_speaker_says_operator: bool | None,
        voice_biometric_match: bool | None = None,
    ) -> None:
        """Process observation signals for speaker identity.

        ``None`` signals are no-observation (engine decays toward prior).
        ``voice_biometric_match`` is True when pyannote cosine similarity
        exceeds accept threshold (0.60), False when below reject (0.35),
        and None when uncertain or no audio available.
        """
        observations: dict[str, bool | None] = {
            SESSION_SPEAKER_SIGNAL: session_speaker_says_operator,
            VOICE_BIOMETRIC_SIGNAL: voice_biometric_match,
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

    def asserted(self, *, threshold: float = 0.7) -> bool:
        """Convenience: posterior ≥ threshold.

        Default threshold matches ``DEFAULT_TEMPORAL_PROFILE.enter_threshold``;
        the wire-in call site uses this to replace the raw bool consumer.
        """
        return self._engine.posterior >= threshold


__all__ = [
    "CLAIM_NAME",
    "DEFAULT_LR",
    "DEFAULT_PRIOR",
    "DEFAULT_TEMPORAL_PROFILE",
    "SESSION_SPEAKER_SIGNAL",
    "VOICE_BIOMETRIC_LR",
    "VOICE_BIOMETRIC_SIGNAL",
    "SpeakerIsOperatorEngine",
]
