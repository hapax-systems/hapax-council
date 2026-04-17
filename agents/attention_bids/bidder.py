"""Attention-bid scoring and winner selection.

Pure: given a list of bids + a context snapshot (stimmung, active
objectives, stream-mode), returns a BidResult with the winner (or None)
and the reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AttentionBid:
    """A single bid for operator attention.

    Attributes:
        source: Identifier of the bidding subsystem (e.g., "briefing").
        salience: Self-assessed importance, 0-1.
        summary: Short description (for observer / chronicle).
        requires_broadcast_consent: True iff content references a non-
            operator person and needs active broadcast contract on public.
        objective_id: Optional ID of the active objective this bid
            advances; boosts the score.
    """

    source: str
    salience: float
    summary: str = ""
    requires_broadcast_consent: bool = False
    objective_id: str | None = None


@dataclass(frozen=True)
class BidResult:
    """Result of a bid-selection cycle."""

    winner: AttentionBid | None
    reason: str
    scores: dict[str, float] = field(default_factory=dict)
    filtered: dict[str, str] = field(default_factory=dict)


OBJECTIVE_ALIGNMENT_BOOST: float = 0.20
OPERATOR_STRESS_ATTENUATION: float = 0.60
ACCEPT_THRESHOLD: float = 0.25

_SOURCE_TIE_BREAK_ORDER: tuple[str, ...] = (
    "code_narration",
    "briefing",
    "goal-advance",
    "nudge",
)


def _source_rank(source: str) -> int:
    try:
        return _SOURCE_TIE_BREAK_ORDER.index(source)
    except ValueError:
        return -1


def _stress_attenuation(stimmung: dict[str, Any]) -> float:
    try:
        stress_block = stimmung.get("operator_stress") or {}
        if isinstance(stress_block, dict):
            value = float(stress_block.get("value", 0.0))
        else:
            value = float(stress_block)
    except (TypeError, ValueError):
        return 1.0
    value = max(0.0, min(1.0, value))
    return 1.0 - (OPERATOR_STRESS_ATTENUATION * value)


def _is_objective_aligned(bid: AttentionBid, active_objective_ids: frozenset[str]) -> bool:
    return bid.objective_id is not None and bid.objective_id in active_objective_ids


def _filter_bid(
    bid: AttentionBid,
    stream_mode: str,
    broadcast_contract_holders: frozenset[str],
) -> str | None:
    is_public = stream_mode in {"public", "public_research"}
    if bid.requires_broadcast_consent and is_public:
        target = bid.objective_id or ""
        if target not in broadcast_contract_holders:
            return "broadcast_consent_missing"
    return None


def score_bid(
    bid: AttentionBid,
    stimmung: dict[str, Any],
    active_objective_ids: frozenset[str],
) -> float:
    """Return the scored salience for ``bid``."""
    base = max(0.0, min(1.0, bid.salience))
    attenuation = _stress_attenuation(stimmung)
    adjusted = base * attenuation
    if _is_objective_aligned(bid, active_objective_ids):
        adjusted += OBJECTIVE_ALIGNMENT_BOOST
    return min(1.0, adjusted)


def select_winner(
    bids: list[AttentionBid],
    *,
    stimmung: dict[str, Any],
    active_objective_ids: frozenset[str] = frozenset(),
    stream_mode: str = "private",
    broadcast_contract_holders: frozenset[str] = frozenset(),
    accept_threshold: float = ACCEPT_THRESHOLD,
) -> BidResult:
    """Score, filter, pick the winner.

    Reasons: "no_bids" | "all_filtered" | "below_threshold" | "accepted".
    """
    if not bids:
        return BidResult(winner=None, reason="no_bids")

    scores: dict[str, float] = {}
    filtered: dict[str, str] = {}
    survivors: list[tuple[float, int, AttentionBid]] = []

    for bid in bids:
        reject_reason = _filter_bid(bid, stream_mode, broadcast_contract_holders)
        if reject_reason is not None:
            filtered[bid.source] = reject_reason
            scores[bid.source] = 0.0
            continue
        score = score_bid(bid, stimmung, active_objective_ids)
        scores[bid.source] = score
        survivors.append((score, _source_rank(bid.source), bid))

    if not survivors:
        return BidResult(winner=None, reason="all_filtered", scores=scores, filtered=filtered)

    survivors.sort(key=lambda t: (t[0], t[1]), reverse=True)
    top_score, _rank, top_bid = survivors[0]

    if top_score < accept_threshold:
        return BidResult(winner=None, reason="below_threshold", scores=scores, filtered=filtered)

    return BidResult(winner=top_bid, reason="accepted", scores=scores, filtered=filtered)
