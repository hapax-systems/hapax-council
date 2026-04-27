"""Endogenous drive evaluator — Bayesian surfacing for internal pressures.

An endogenous drive is a latent variable that accumulates pressure over
time and, when a Bayesian posterior crosses a stochastic threshold, emits
an impingement onto the bus.  Drives are NOT timers — they are
probabilistic estimators that compute ``P(emit_now | context)``.

Design reference:
    docs/research/2026-04-27-endogenous-drive-role-semantic-surfacing.md

Constitutional compliance:
    - feedback_no_expert_system_rules: no if-then-else gates; all
      modifiers are continuous multipliers, never boolean.
    - project_programmes_enable_grounding: role context modulates
      drive pressure but never zeroes it.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DriveContext:
    """Snapshot of system state consumed by the drive evaluator.

    All fields have soft defaults so a partially-assembled context
    (e.g. in tests or during daemon startup) produces a neutral
    evaluation, never an error.
    """

    # Number of chronicle events since the last narration emission.
    chronicle_event_count: int = 0

    # Current stimmung stance (e.g. "ambient", "hothouse").
    stimmung_stance: str = "ambient"

    # Bayesian posterior for operator physical presence [0, 1].
    operator_presence_score: float = 0.0

    # Active programme role (e.g. "listening", "ritual").
    programme_role: str | None = None

    # Wall-clock time override (for testing).
    now: float | None = None


# -- Stimmung stance modifiers ------------------------------------------
#
# Higher modifier = more pressure to narrate.  Every value is strictly
# positive (architectural invariant: no zero multipliers).

_STIMMUNG_MODIFIERS: dict[str, float] = {
    "ambient": 1.2,  # relaxed → narration welcome
    "attentive": 1.0,  # neutral
    "hothouse": 0.5,  # high intensity → suppress (but allow)
    "critical": 0.3,  # system stress → strongly suppress
    "reflective": 1.4,  # introspective → narration very welcome
}
_STIMMUNG_DEFAULT: float = 1.0


# -- Role affinity modifiers -------------------------------------------
#
# Semantic role → narration affinity.  In Phase 2 these are replaced by
# embedding cosine similarity; for Phase 1 they are hand-tuned soft
# priors that replicate the old gate logic WITHOUT being boolean.

_ROLE_AFFINITY: dict[str, float] = {
    "listening": 1.3,
    "showcase": 0.8,
    "ritual": 0.35,
    "interlude": 0.5,
    "work_block": 0.6,
    "tutorial": 0.7,
    "wind_down": 0.4,
    "hothouse_pressure": 0.3,
    "ambient": 1.5,  # no operator → narrate freely
    "experiment": 0.9,
    "repair": 0.4,
    "invitation": 0.7,
}
_ROLE_AFFINITY_DEFAULT: float = 1.0


@dataclass
class EndogenousDrive:
    """A single endogenous drive with Bayesian surfacing.

    Parameters
    ----------
    tau : float
        Characteristic time constant in seconds.  Pressure reaches
        ~0.63 at *tau* seconds, ~0.86 at 2*tau*, ~0.95 at 3*tau*.
    threshold : float
        Base surfacing threshold.  The actual threshold is perturbed
        by ±20% stochastically to prevent lock-step periodicity.
    name : str
        Human-readable drive identifier (e.g. "narration").
    """

    tau: float = 120.0
    threshold: float = 0.12
    name: str = "narration"

    # Thompson sampling prior (Beta distribution).
    _ts_alpha: float = field(default=2.0, repr=False)
    _ts_beta: float = field(default=1.0, repr=False)

    # Timestamp of last emission (wall clock).
    _last_emission_ts: float = field(default=0.0, repr=False)

    def base_pressure(self, now: float | None = None) -> float:
        """Exponential accumulation since last emission.

        Returns a value in [0, 1) that rises toward 1.0 as time
        since last emission increases.
        """
        now = now or time.time()
        elapsed = max(0.0, now - self._last_emission_ts)
        return 1.0 - math.exp(-elapsed / self.tau)

    def _chronicle_modifier(self, count: int) -> float:
        """More unnarrated events → higher pressure to narrate.

        Soft curve: modifier = 1 + log2(1 + count) * 0.3
        0 events → 1.0, 4 events → 1.69, 16 events → 2.2, 64 events → 2.8
        """
        if count <= 0:
            return 1.0
        return 1.0 + math.log2(1 + count) * 0.3

    def _stimmung_modifier(self, stance: str) -> float:
        return _STIMMUNG_MODIFIERS.get(stance, _STIMMUNG_DEFAULT)

    def _role_modifier(self, role: str | None) -> float:
        if role is None:
            return _ROLE_AFFINITY_DEFAULT
        return _ROLE_AFFINITY.get(role, _ROLE_AFFINITY_DEFAULT)

    def _presence_modifier(self, score: float) -> float:
        """Operator presence suppresses autonomous narration.

        High presence → conversation likely → suppress narration.
        Low presence → narrate freely.

        Modifier: 1.3 - 0.6 * presence_score
        At score=0: 1.3 (boost)
        At score=0.5: 1.0 (neutral)
        At score=1.0: 0.7 (suppress but allow)
        """
        return max(0.3, 1.3 - 0.6 * min(1.0, score))

    def _thompson_sample(self) -> float:
        """Sample from the learned outcome prior."""
        return random.betavariate(self._ts_alpha, self._ts_beta)

    def evaluate(self, context: DriveContext) -> float:
        """Compute the posterior surfacing probability.

        Returns a float in [0, ∞) — the product of base pressure and
        all contextual modifiers.  Compare against the stochastic
        threshold to decide emission.
        """
        now = context.now or time.time()
        bp = self.base_pressure(now)
        return (
            bp
            * self._chronicle_modifier(context.chronicle_event_count)
            * self._stimmung_modifier(context.stimmung_stance)
            * self._role_modifier(context.programme_role)
            * self._presence_modifier(context.operator_presence_score)
            * self._thompson_sample()
        )

    def should_emit(self, context: DriveContext) -> bool:
        """Evaluate and decide whether to emit an impingement.

        The threshold is perturbed by ±20% to prevent periodicity.
        """
        posterior = self.evaluate(context)
        jittered_threshold = self.threshold * (0.8 + 0.4 * random.random())
        return posterior > jittered_threshold

    def record_emission(self, now: float | None = None) -> None:
        """Reset accumulation clock after successful emission."""
        self._last_emission_ts = now or time.time()

    def record_outcome(self, success: bool) -> None:
        """Update Thompson sampling prior based on outcome."""
        if success:
            self._ts_alpha += 1
        else:
            self._ts_beta += 1

    def build_narrative(self, context: DriveContext) -> str:
        """Build semantically rich narrative for the emitted impingement.

        This text is what gets embedded for Qdrant cosine similarity
        against affordance descriptions.  It must be semantically close
        to the narration capability description so the pipeline can
        recruit it.
        """
        now = context.now or time.time()
        elapsed = now - self._last_emission_ts
        parts = [
            "Internal drive to compose a narration grounding "
            "recently observed perceptual events into speech.",
        ]
        if context.chronicle_event_count > 0:
            parts.append(
                f"{context.chronicle_event_count} chronicle events "
                f"have accumulated without narration."
            )
        if elapsed > 60:
            parts.append(
                f"It has been {elapsed:.0f} seconds since the last autonomous narration emission."
            )
        if context.stimmung_stance:
            parts.append(f"Current attunement: {context.stimmung_stance}.")
        if context.programme_role:
            parts.append(f"Active programme role: {context.programme_role}.")
        return " ".join(parts)
