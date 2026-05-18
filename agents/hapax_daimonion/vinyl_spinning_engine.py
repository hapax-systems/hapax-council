"""Bayesian vinyl-spinning engine — replaces the Boolean ``_vinyl_is_playing``.

Replaces ``agents/studio_compositor/director_loop.py::_vinyl_is_playing``
with a posterior-driven ``ClaimEngine[bool]`` that fuses heterogeneous
signals (operator override flag, album-cover identification + freshness,
hand-on-turntable IR perception, future YAMNet audio classification)
into a calibrated probability, with per-claim asymmetric temporal
hysteresis (slow-enter / fast-exit — vinyl claims should be cautious to
assert, fast to retract).

## Why a Bayesian engine instead of a 3-signal Boolean

The Boolean version had a structural problem: each signal was a hard
short-circuit. When ANY signal fired (operator flag OR album-cover
fresh-AND-hand-recent), the predicate returned True; when none fired
it returned False. This let single-signal weak evidence (e.g., a still-
fresh ALBUM_STATE_FILE from a previous spin even after the operator
removed the album) drive a True even when the actual platter was
silent — the hallucination class operator reported as
"director claiming vinyl playing when it isn't" (Task #185, fixed
tactically in #1208/#1210/#1211/#1220, but the underlying Boolean
predicate kept regressing as new signals were added).

The Bayesian fusion is structural: each signal contributes a likelihood
ratio (LR = P(signal | vinyl_spinning) / P(signal | not_spinning)) per
``LRDerivation``, the engine combines them into a log-odds posterior,
and an asymmetric ``TemporalProfile`` (slow-enter, fast-exit per the
research §6 music profile) prevents both flicker and false-positives.

## Signals

Phase 2 ships with three signals — same set as the Boolean predicate
plus the operator override as a hard-conjunctive lift:

- ``operator_override``: ``/dev/shm/hapax-compositor/vinyl-operator-active.flag``
  exists. Hard-positive (LR ≈ 100/0.01) — operator-asserted ground truth.
- ``album_cover_fresh``: ALBUM_STATE_FILE exists, mtime within
  ``_VINYL_STATE_STALE_S`` (300s), and confidence ≥
  ``_VINYL_CONFIDENCE_THRESHOLD`` (0.5). Necessary-but-not-sufficient
  — the album-identifier writes state when the cover is in the IR
  field even if the platter idles. LR moderate (0.6 / 0.3).
- ``hand_on_turntable``: Pi-6 IR overhead camera saw a hand in the
  turntable zone within ``_TURNTABLE_ACTIVE_STALE_S`` (120s) OR
  scratching/scratch activity classified by contact_mic_ir cross-
  modal fusion. Strong corroboration when present, weak absence
  signal (operator may have set the platter spinning then walked
  away). Positive-only: LR (0.85 / 0.10).

Phase 2b will add ``yamnet_music_present`` (broadcast L-12 audio
classification — pure-audio evidence, zero upstream coupling). That
signal is the structural fix to the third hallucination axis (audio-
silent + cover-fresh + hand-recent → still claims vinyl) but it
lives in a separate engine call site once shipped.

## Temporal profile (asymmetric — research §6 music)

- enter_threshold: 0.75 (require strong evidence to assert)
- exit_threshold: 0.40
- k_enter: 6 (≈6 ticks, cautious entry)
- k_exit: 2 (fast retraction — when the audio drops, claim drops fast)
- k_uncertain: 4 (default)

Rationale: false-positive vinyl claims are operator-perceptible
hallucination (they break the livestream's grounding contract);
false-negative vinyl claims are silent-degrade (the director stops
narrating vinyl correctly, falling back to youtube/curated framing).
Operator's pain is squarely on the false-positive axis, so the
profile is biased to slow-enter / fast-exit.

## Public API

::

    engine = VinylSpinningEngine()
    engine.tick()          # gather signals, update posterior + state
    engine.posterior       # 0..1 calibrated probability
    engine.is_spinning     # bool — True iff state == ASSERTED
    engine.state           # "ASSERTED" | "UNCERTAIN" | "RETRACTED"

## Bypass

When ``HAPAX_BAYESIAN_BYPASS=1`` is set, the underlying ``ClaimEngine``
``update`` is a no-op — posterior pinned to prior, state pinned to
UNCERTAIN. Combined with a caller-side fallback to the legacy Boolean
predicate, this is the single rollback knob for the entire vinyl-
spinning Bayesian layer.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

from shared.claim import Claim, ClaimEngine, LRDerivation, TemporalProfile

log = logging.getLogger(__name__)

# ── Signal source paths + thresholds (mirrored from director_loop) ──────

ALBUM_STATE_FILE = Path("/dev/shm/hapax-compositor/album-state.json")
PERCEPTION_STATE_FILE = Path.home() / ".cache/hapax-daimonion/perception-state.json"
VINYL_OPERATOR_OVERRIDE_FLAG = Path("/dev/shm/hapax-compositor/vinyl-operator-active.flag")

# Stale cutoffs match the Boolean predicate so behavior is comparable.
_VINYL_STATE_STALE_S = 300.0
_TURNTABLE_ACTIVE_STALE_S = 120.0
_VINYL_CONFIDENCE_THRESHOLD = 0.5


# ── Signal LR weights (registered in shared/lr_registry.yaml) ───────────


def _default_signal_weights() -> dict[str, LRDerivation]:
    """Build the LRDerivation dict the engine consumes.

    Two signals only — conjunctive structure preserved from the legacy
    Boolean predicate by upstream composition (album-cover-fresh AND
    hand-on-turntable becomes a single derived signal). This is the
    structural fix for the operator's reported hallucination:
    cover-fresh-alone-while-platter-idle should contribute ZERO log-
    odds, not slowly accumulate via repeated weak positive evidence.

    Construction matches the YAML entries in
    ``shared/lr_registry.yaml::vinyl_spinning_signals``. The engine
    accepts pre-built ``LRDerivation`` records to keep import-time
    side-effects minimal; the YAML is the canonical source.
    """
    return {
        "operator_override": LRDerivation(
            signal_name="operator_override",
            claim_name="vinyl_spinning",
            source_category="expert_elicitation_shelf",
            p_true_given_h1=0.99,
            p_true_given_h0=0.01,
            positive_only=True,
            estimation_reference=(
                "Operator-asserted ground truth via "
                "/dev/shm/hapax-compositor/vinyl-operator-active.flag — "
                "hard-conjunctive lift; operator wouldn't set the flag "
                "while the platter idles."
            ),
            calibration_window_s=None,
        ),
        "cover_and_hand": LRDerivation(
            signal_name="cover_and_hand",
            claim_name="vinyl_spinning",
            source_category="expert_elicitation_shelf",
            p_true_given_h1=0.95,
            p_true_given_h0=0.05,
            positive_only=True,
            estimation_reference=(
                "Conjunction of two readings: ALBUM_STATE_FILE fresh "
                "(<300s mtime, confidence ≥ 0.5 from gemini-flash IR "
                "overhead) AND Pi-6 NoIR ir_hand_zone == 'turntable' "
                "OR contact_mic_ir scratching activity (<120s mtime). "
                "The conjunction is load-bearing: cover alone fires "
                "while the platter idles (the bug operator reported); "
                "hand alone fires when the operator handles equipment "
                "without playing. Both together is strong evidence. "
                "Calibration baseline 2026-03-17 first-live-run + "
                "Task #185 fix retrospective."
            ),
            calibration_window_s=120.0,
        ),
    }


# ── Temporal profile (asymmetric — slow-enter, fast-exit) ───────────────

DEFAULT_PROFILE = TemporalProfile(
    enter_threshold=0.75,
    exit_threshold=0.40,
    k_enter=6,
    k_exit=2,
    k_uncertain=4,
)

# Prior from prior_provenance.yaml; vinyl-spinning is rare across the
# operator's day (most ticks the platter is idle), so prior is low.
DEFAULT_PRIOR = 0.10


# ── Engine ──────────────────────────────────────────────────────────────


class VinylSpinningEngine:
    """Bayesian vinyl-spinning posterior + 3-state hysteresis machine.

    Replaces the Boolean ``_vinyl_is_playing`` short-circuit gate. Each
    ``tick()`` reads signal sources from disk, contributes observations
    to the underlying ``ClaimEngine[bool]``, and exposes a posterior +
    state that the director loop consumes.

    Construction takes no required arguments — defaults match the
    shipped Boolean predicate's calibration. Tests can inject signal-
    source paths via constructor parameters.
    """

    def __init__(
        self,
        *,
        album_state_file: Path = ALBUM_STATE_FILE,
        perception_state_file: Path = PERCEPTION_STATE_FILE,
        operator_override_flag: Path = VINYL_OPERATOR_OVERRIDE_FLAG,
        hand_on_turntable_fn: Callable[[], bool] | None = None,
        prior: float = DEFAULT_PRIOR,
        profile: TemporalProfile | None = None,
        signal_weights: dict[str, LRDerivation] | None = None,
    ) -> None:
        self._album_state_file = album_state_file
        self._perception_state_file = perception_state_file
        self._operator_override_flag = operator_override_flag
        # Optional override: when provided, the engine delegates the
        # hand-on-turntable read to this callable instead of parsing the
        # perception state file directly. Used by ``director_loop`` to
        # share the same predicate the legacy fallback uses, so test
        # fixtures only need to monkeypatch one function.
        self._hand_on_turntable_fn = hand_on_turntable_fn

        self._engine: ClaimEngine[bool] = ClaimEngine[bool](
            name="vinyl_spinning",
            prior=prior,
            temporal_profile=profile or DEFAULT_PROFILE,
            signal_weights=signal_weights or _default_signal_weights(),
            # Aggressive decay (4× the default 0.02) — false-positive
            # vinyl claims are operator-perceptible hallucination that
            # break the livestream's grounding contract; fast retraction
            # is the priority once signals drop.
            decay_rate=0.08,
        )

    # ── Public API ─────────────────────────────────────────────────

    def tick(self) -> None:
        """Read all signal sources + update the underlying ClaimEngine.

        Atomic batch tick: collects observations from disk, derives the
        ``cover_and_hand`` conjunction, then contributes them in a
        single ``ClaimEngine.tick()`` call so the state machine ticks
        once per perceptual moment.
        """
        prev_state = self._engine.state
        prev_posterior = self._engine.posterior
        cover_fresh = self._read_album_cover_fresh()
        hand_recent = self._read_hand_on_turntable()
        # Conjunction: only contribute True when BOTH fire. None when
        # either is missing — this preserves the load-bearing AND from
        # the legacy Boolean predicate while keeping LR fusion clean.
        if cover_fresh is True and hand_recent is True:
            cover_and_hand: bool | None = True
        else:
            cover_and_hand = None

        observations: dict[str, bool | None] = {
            "operator_override": self._read_operator_override(),
            "cover_and_hand": cover_and_hand,
        }
        self._engine.tick(observations)
        if self._engine.state != prev_state:
            from shared.bayesian_impingement_emitter import emit_state_transition_impingement

            emit_state_transition_impingement(
                source="audio.vinyl_spinning",
                claim_name="vinyl-spinning",
                from_state=prev_state,
                to_state=self._engine.state,
                posterior=self._engine.posterior,
                prev_posterior=prev_posterior,
                active_signals={k: v for k, v in observations.items() if v is not None},
            )

    @property
    def posterior(self) -> float:
        """Calibrated 0..1 probability the platter is currently spinning."""
        return self._engine.posterior

    @property
    def state(self) -> str:
        """Discrete state: ASSERTED | UNCERTAIN | RETRACTED."""
        return self._engine.state

    @property
    def is_spinning(self) -> bool:
        """Drop-in replacement for the legacy ``_vinyl_is_playing()``.

        True iff the engine has reached the ASSERTED hysteresis state
        (posterior >= enter_threshold sustained for k_enter ticks).
        Returns False during UNCERTAIN ramp-up, even at high posterior,
        to honor the slow-enter discipline.
        """
        return self._engine.state == "ASSERTED"

    def to_claim(self, *, narration_floor: float = 0.60) -> Claim:
        """Render the current engine state as a Phase 4/5/6 ``Claim`` envelope.

        Phase 6 wire-up: surfaces (director, persona, narrative) call this
        to populate ``render_envelope``'s claim list. The proposition is
        stable across ticks; the posterior reflects the live ClaimEngine
        state. Below-floor posteriors render as ``[UNKNOWN] ...`` per
        ``shared.claim_prompt``.
        """
        return Claim(
            name="vinyl_spinning",
            domain="activity",
            proposition="The operator is spinning vinyl on the turntable.",
            posterior=self.posterior,
            prior_source="empirical",
            prior_provenance_ref="vinyl_spinning",
            evidence_sources=[],
            last_update_t=time.time(),
            temporal_profile=DEFAULT_PROFILE,
            composition=None,
            narration_floor=narration_floor,
            staleness_cutoff_s=_TURNTABLE_ACTIVE_STALE_S,
        )

    # ── Signal readers (private) ───────────────────────────────────

    def _read_operator_override(self) -> bool | None:
        """Operator override flag — hard-positive when present."""
        try:
            if self._operator_override_flag.exists():
                return True
        except OSError:
            pass
        # Positive-only signal: absence contributes None (no evidence).
        return None

    def _read_album_cover_fresh(self) -> bool | None:
        """Album-cover identified within stale cutoff at ≥ confidence threshold."""
        try:
            if not self._album_state_file.exists():
                return None
            age = time.time() - self._album_state_file.stat().st_mtime
            if age > _VINYL_STATE_STALE_S:
                return None
            data = json.loads(self._album_state_file.read_text())
            conf = float(data.get("confidence") or 0.0)
            if conf < _VINYL_CONFIDENCE_THRESHOLD:
                return None
            return True
        except Exception:
            log.debug("album_cover_fresh signal read failed", exc_info=True)
            return None

    def _read_hand_on_turntable(self) -> bool | None:
        """Pi-6 IR overhead hand-zone == turntable, or scratch activity."""
        if self._hand_on_turntable_fn is not None:
            try:
                return True if self._hand_on_turntable_fn() else None
            except Exception:
                log.debug("hand_on_turntable_fn raised; treating as no signal", exc_info=True)
                return None
        try:
            if not self._perception_state_file.exists():
                return None
            age = time.time() - self._perception_state_file.stat().st_mtime
            if age > _TURNTABLE_ACTIVE_STALE_S:
                return None
            data = json.loads(self._perception_state_file.read_text())
            hand_zone = str(data.get("ir_hand_zone") or "").lower()
            hand_activity = str(data.get("ir_hand_activity") or "").lower()
            if "turntable" in hand_zone:
                return True
            if hand_activity in {"scratching", "scratch"}:
                return True
            return None
        except Exception:
            log.debug("hand_on_turntable signal read failed", exc_info=True)
            return None


__all__ = [
    "VinylSpinningEngine",
    "DEFAULT_PRIOR",
    "DEFAULT_PROFILE",
    "ALBUM_STATE_FILE",
    "PERCEPTION_STATE_FILE",
    "VINYL_OPERATOR_OVERRIDE_FLAG",
]
