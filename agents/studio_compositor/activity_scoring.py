"""LRR Phase 9 §3.2 — stimmung-modulated activity selection.

Pure scoring helpers for the director-loop activity selector. Given a
candidate activity (``react`` / ``chat`` / ``vinyl`` / ``study`` /
``observe`` / ``silence``) plus three terms, returns a single number:

    score(a) = momentary_weight · momentary
             + objective_weight · objective_alignment
             + stimmung_weight  · stimmung_term

The weights default to ``0.70 / 0.25 / 0.05`` per spec §3.2 — conservative
start per the §6 oscillation-risk note. The stimmung term is derived
from the published chat-signals SHM (see ``agents/chat_monitor/sink.py``
and PR #998), mapped to a per-activity modulation: high engagement +
many threads lifts ``chat``, low engagement lifts ``study`` / ``silence``.

The module is side-effect-free and injection-friendly. The caller
passes ``momentary`` and ``objective_alignment`` from whatever upstream
logic already has them; ``stimmung_term`` is either supplied directly
or read via ``stimmung_term_for_activity``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_MOMENTARY_WEIGHT: float = 0.70
DEFAULT_OBJECTIVE_WEIGHT: float = 0.25
DEFAULT_STIMMUNG_WEIGHT: float = 0.05

# Continuous-Loop §3.2 — override thresholds. Tunable in
# config/director_scoring.yaml; these module-level constants are the
# fallback when that file is absent / malformed.
DEFAULT_OVERRIDE_MARGIN: float = 0.08  # alternate must beat proposed by this much
DEFAULT_PROPOSAL_FLOOR: float = 0.55  # proposed composite must be ≤ this to override
DEFAULT_OVERRIDE_COOLDOWN_S: float = 60.0  # min seconds between overrides
DEFAULT_STIMMUNG_STALENESS_S: float = 90.0  # max age for stimmung term to count

# Override is never allowed to flip into silence — that's operator prerogative.
NEVER_OVERRIDE_TO: frozenset[str] = frozenset({"silence"})

CANDIDATE_ACTIVITIES: tuple[str, ...] = (
    "react",
    "chat",
    "vinyl",
    "music",
    "study",
    "observe",
    "silence",
)

# Chat-signal thresholds for high / low engagement (derived from
# participant_diversity + thread_count + semantic_coherence).
HIGH_ENGAGEMENT_SCORE: float = 0.65
LOW_ENGAGEMENT_SCORE: float = 0.30


# ── Engagement score from chat signals ──────────────────────────────────────


def engagement_from_chat_signals(chat_signals: dict[str, Any] | None) -> float:
    """Compute a single 0..1 engagement score from the published signals.

    Combines participant diversity (broad engagement), thread count
    (conversational liveliness, capped / normalised), and semantic
    coherence (audience focus) — each 0..1 — into a mean.
    Returns 0.0 when the signals dict is missing or malformed.
    """
    if not isinstance(chat_signals, dict):
        return 0.0

    try:
        diversity = max(0.0, min(1.0, float(chat_signals.get("participant_diversity", 0.0))))
        coherence = max(0.0, min(1.0, float(chat_signals.get("semantic_coherence", 0.0))))
        threads = max(0, int(chat_signals.get("thread_count", 0)))
    except (TypeError, ValueError):
        return 0.0

    # Thread count normalized so 3+ threads ≥ 1.0 (studio-lively upper bound).
    thread_signal = min(1.0, threads / 3.0)
    return (diversity + coherence + thread_signal) / 3.0


# ── Per-activity stimmung term ──────────────────────────────────────────────


def stimmung_term_for_activity(
    activity: str,
    *,
    engagement: float,
    active_chat_messages: int = 0,
) -> float:
    """Return a signed modulation term for ``activity`` in [-1, 1].

    * High engagement + active chat threads → raise ``chat`` / ``react``.
    * Low engagement → raise ``study`` / ``silence``.
    * ``observe`` / ``vinyl`` / ``music`` neutral (0.0) — they're
      operator-facing, not audience-facing.

    The caller multiplies by the stimmung weight (0.05 default) so the
    effective push is small; we keep the raw value in [-1, 1] for
    introspection.
    """
    engagement = max(0.0, min(1.0, engagement))
    high = engagement >= HIGH_ENGAGEMENT_SCORE and active_chat_messages > 0
    low = engagement < LOW_ENGAGEMENT_SCORE

    if activity == "chat":
        if high:
            return 1.0
        if low:
            return -0.5
        return 0.0
    if activity == "react":
        if high:
            return 0.5
        if low:
            return -0.25
        return 0.0
    if activity in ("study", "silence"):
        if low:
            return 1.0 if activity == "study" else 0.5
        if high:
            return -0.5
        return 0.0
    # observe / vinyl / music / unknown → neutral.
    return 0.0


# ── Top-level score ─────────────────────────────────────────────────────────


def score_activity(
    activity: str,
    *,
    momentary: float,
    objective_alignment: float,
    stimmung_term: float = 0.0,
    momentary_weight: float = DEFAULT_MOMENTARY_WEIGHT,
    objective_weight: float = DEFAULT_OBJECTIVE_WEIGHT,
    stimmung_weight: float = DEFAULT_STIMMUNG_WEIGHT,
) -> float:
    """Weighted sum per spec §3.2. Inputs are clamped to [0, 1] / [-1, 1]."""
    m = max(0.0, min(1.0, momentary))
    o = max(0.0, min(1.0, objective_alignment))
    s = max(-1.0, min(1.0, stimmung_term))
    del activity  # name retained for caller-clarity + trace tagging
    return momentary_weight * m + objective_weight * o + stimmung_weight * s


# ── Convenience: SHM-backed stimmung term ───────────────────────────────────


def _read_chat_signals_from_shm(path: Path | None = None) -> dict[str, Any] | None:
    """Read the published chat signals JSON; return the dict or ``None``."""
    from agents.chat_monitor.sink import read_latest

    return read_latest(path)


def stimmung_term_for_activity_from_shm(
    activity: str,
    *,
    active_chat_messages: int = 0,
    path: Path | None = None,
) -> float:
    """Convenience wrapper: read signals, derive engagement, return the term."""
    signals = _read_chat_signals_from_shm(path)
    engagement = engagement_from_chat_signals(signals)
    return stimmung_term_for_activity(
        activity, engagement=engagement, active_chat_messages=active_chat_messages
    )


# ── §3.2 Override gate ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ActivityOverrideDecision:
    """Result of :func:`choose_activity_with_override`."""

    final_activity: str
    was_override: bool
    proposed_activity: str
    proposed_score: float
    winner_score: float
    reason: str
    scores: dict[str, float]


def _signals_are_stale(
    signals_ts: float | None,
    *,
    now_epoch: float,
    staleness_s: float,
) -> bool:
    if signals_ts is None:
        return True
    return (now_epoch - signals_ts) > staleness_s


def choose_activity_with_override(
    proposed_activity: str,
    *,
    momentary: float,
    objective_alignment_fn,
    engagement: float,
    active_chat_messages: int,
    signals_ts: float | None,
    now_epoch: float,
    last_override_at: float,
    override_margin: float = DEFAULT_OVERRIDE_MARGIN,
    proposal_floor: float = DEFAULT_PROPOSAL_FLOOR,
    cooldown_s: float = DEFAULT_OVERRIDE_COOLDOWN_S,
    staleness_s: float = DEFAULT_STIMMUNG_STALENESS_S,
) -> ActivityOverrideDecision:
    """Score every candidate and decide whether to override the LLM's choice.

    Guards (all must pass for override to fire):

    * chat signals are fresh (``signals_ts`` within ``staleness_s`` of now);
    * cooldown has elapsed since the last override (``now - last_override_at
      >= cooldown_s``);
    * the best alternate beats ``proposed_activity`` by at least
      ``override_margin`` and the proposed composite is at or below
      ``proposal_floor``;
    * the best alternate is not in :data:`NEVER_OVERRIDE_TO` (never flip
      into silence).

    ``objective_alignment_fn`` is a callable ``(activity) -> float`` so the
    caller can plug in whatever per-activity objective scoring they have.
    A constant-returning lambda is fine.
    """
    # Score every activity
    scores: dict[str, float] = {}
    for activity in CANDIDATE_ACTIVITIES:
        objective_alignment = float(objective_alignment_fn(activity) or 0.0)
        stimmung_term = stimmung_term_for_activity(
            activity, engagement=engagement, active_chat_messages=active_chat_messages
        )
        scores[activity] = score_activity(
            activity,
            momentary=momentary if activity == proposed_activity else momentary * 0.7,
            objective_alignment=objective_alignment,
            stimmung_term=stimmung_term,
        )

    proposed_score = scores.get(proposed_activity, 0.0)

    # Pick best alternate (not equal to proposed + not in no-flip set)
    best_alt = None
    best_alt_score = -1.0
    for activity, score in scores.items():
        if activity == proposed_activity:
            continue
        if activity in NEVER_OVERRIDE_TO:
            continue
        if score > best_alt_score:
            best_alt = activity
            best_alt_score = score

    # Guards
    if _signals_are_stale(signals_ts, now_epoch=now_epoch, staleness_s=staleness_s):
        return ActivityOverrideDecision(
            final_activity=proposed_activity,
            was_override=False,
            proposed_activity=proposed_activity,
            proposed_score=proposed_score,
            winner_score=proposed_score,
            reason="stimmung signals stale",
            scores=scores,
        )
    if now_epoch - last_override_at < cooldown_s:
        return ActivityOverrideDecision(
            final_activity=proposed_activity,
            was_override=False,
            proposed_activity=proposed_activity,
            proposed_score=proposed_score,
            winner_score=proposed_score,
            reason=f"cooldown ({cooldown_s - (now_epoch - last_override_at):.0f}s remaining)",
            scores=scores,
        )
    if best_alt is None:
        return ActivityOverrideDecision(
            final_activity=proposed_activity,
            was_override=False,
            proposed_activity=proposed_activity,
            proposed_score=proposed_score,
            winner_score=proposed_score,
            reason="no valid alternate",
            scores=scores,
        )
    if proposed_score > proposal_floor:
        return ActivityOverrideDecision(
            final_activity=proposed_activity,
            was_override=False,
            proposed_activity=proposed_activity,
            proposed_score=proposed_score,
            winner_score=proposed_score,
            reason=(f"proposed confident ({proposed_score:.2f} > floor {proposal_floor:.2f})"),
            scores=scores,
        )
    if (best_alt_score - proposed_score) < override_margin:
        return ActivityOverrideDecision(
            final_activity=proposed_activity,
            was_override=False,
            proposed_activity=proposed_activity,
            proposed_score=proposed_score,
            winner_score=best_alt_score,
            reason=(
                f"insufficient margin ({best_alt_score - proposed_score:.2f} < "
                f"{override_margin:.2f})"
            ),
            scores=scores,
        )

    return ActivityOverrideDecision(
        final_activity=best_alt,
        was_override=True,
        proposed_activity=proposed_activity,
        proposed_score=proposed_score,
        winner_score=best_alt_score,
        reason=(
            f"stimmung-override: {proposed_activity}→{best_alt} "
            f"({best_alt_score:.2f} vs {proposed_score:.2f})"
        ),
        scores=scores,
    )
