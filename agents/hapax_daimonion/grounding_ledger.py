"""Discourse Unit grounding ledger — tracks grounding state per system utterance.

Implements a simplified Traum (1994) grounding automaton with concern-aware
repair thresholds (Clark & Brennan 1991 "sufficient for current purposes").

The ledger is external to the LLM — it makes mechanical decisions about
when to advance, repair, or abandon based on acceptance signals and concern
weight. The LLM receives the RESULT (a grounding directive) not the logic.

Three core functions:
  1. DU state tracking (PENDING → GROUNDED/REPAIR/ABANDONED/CONTESTED/UNGROUNDED)
  2. Grounding Quality Index (GQI) — composite of acceptance, coherence, engagement
  3. 2D effort calibration (activation × GQI → word limit + effort level)
"""

from __future__ import annotations

import enum
import logging
from collections import deque
from dataclasses import dataclass

log = logging.getLogger(__name__)


class DUState(enum.Enum):
    """Discourse Unit grounding states (simplified Traum automaton)."""

    PENDING = "PENDING"
    GROUNDED = "GROUNDED"
    REPAIR_1 = "REPAIR-1"
    REPAIR_2 = "REPAIR-2"
    ABANDONED = "ABANDONED"
    CONTESTED = "CONTESTED"
    UNGROUNDED = "UNGROUNDED"


@dataclass
class DiscourseUnit:
    """A single system utterance tracked for grounding."""

    turn: int
    content_summary: str
    state: DUState = DUState.PENDING
    repair_count: int = 0
    concern_weight: float = 0.5


@dataclass
class EffortDecision:
    """Result of 2D effort calibration (activation × GQI)."""

    effort_score: float  # 0.0-1.0
    word_limit: int  # 22-48
    level_name: str  # EFFICIENT/BASELINE/ELABORATIVE


# Strategy directives injected into VOLATILE band (Traum 1994 responsive grounding acts)
_STRATEGY_DIRECTIVES: dict[str, str] = {
    "advance": "The operator accepted your previous point. Advance to new content. Do not repeat or revisit what was already understood.",
    "rephrase": "The operator asked for clarification. First, acknowledge their question (e.g. 'Good question' or 'Let me put that differently'). Then rephrase your previous point using different words. Do not introduce new information yet.",
    "elaborate": "Understanding has not been established after rephrasing. Ask the operator what specifically isn't clear before continuing. Keep your question short and specific.",
    "present_reasoning": "The operator disagreed. Acknowledge their position first (e.g. 'I hear you' or 'That's a fair point'). Then present your reasoning without retracting. Do not apologize or cave.",
    "move_on": "Previous point was not grounded after multiple attempts. Move on. Do not reference the ungrounded content as established. Start fresh with the operator's current interest.",
    "neutral": "No prior context to repair. Respond naturally to the operator's input. After responding, briefly check understanding (e.g. 'Does that make sense?' or 'What do you think?').",
    "ungrounded_caution": "The operator did not engage with your previous point. Do not build on it or reference it as established. Respond to what the operator actually said.",
}


class GroundingLedger:
    """Per-session grounding state tracker with concern-aware repair thresholds.

    Tracks each system utterance as a Discourse Unit (DU) through a simplified
    Traum grounding automaton. Computes Grounding Quality Index (GQI) from
    acceptance history and provides 2D effort calibration.
    """

    def __init__(self) -> None:
        self._units: list[DiscourseUnit] = []
        self._acceptance_history: deque[float] = deque(maxlen=20)
        self._ewma_acceptance: float = 0.5  # cold start: neutral
        self._consecutive_negative: int = 0
        self._effort_level: str = "BASELINE"
        self._effort_hold_turns: int = 0  # hysteresis: de-escalation delay

    def add_du(self, turn: int, summary: str, concern_overlap: float = 0.5) -> DiscourseUnit:
        """Register a new system utterance as a Discourse Unit."""
        du = DiscourseUnit(turn=turn, content_summary=summary, concern_weight=concern_overlap)
        self._units.append(du)
        return du

    def update_from_acceptance(
        self,
        acceptance: str,
        concern_overlap: float = 0.5,
    ) -> str:
        """Update the most recent DU's state based on operator acceptance.

        Returns the strategy name for the grounding directive.
        """
        acceptance_score = {"ACCEPT": 1.0, "CLARIFY": 0.7, "IGNORE": 0.3, "REJECT": 0.0}.get(
            acceptance, 0.3
        )

        # Update EWMA (alpha=0.3)
        self._ewma_acceptance = 0.3 * acceptance_score + 0.7 * self._ewma_acceptance
        self._acceptance_history.append(acceptance_score)

        # Track consecutive negatives
        if acceptance in ("REJECT", "IGNORE"):
            self._consecutive_negative += 1
        else:
            self._consecutive_negative = 0

        # No DU to update on first turn
        if not self._units:
            return "neutral"

        du = self._units[-1]
        if du.state in (DUState.GROUNDED, DUState.ABANDONED):
            return "advance"  # already resolved

        # State transitions — explicit signals checked first
        if acceptance == "REJECT":
            if du.state == DUState.CONTESTED:
                du.state = DUState.ABANDONED
                return "move_on"
            du.state = DUState.CONTESTED
            return "present_reasoning"

        if acceptance == "CLARIFY":
            # CLARIFY always triggers repair — operator explicitly asked for help
            if du.state == DUState.REPAIR_2:
                du.state = DUState.ABANDONED
                return "move_on"
            if du.state == DUState.REPAIR_1:
                du.state = DUState.REPAIR_2
                du.repair_count += 1
                return "elaborate"
            du.state = DUState.REPAIR_1
            du.repair_count += 1
            return "rephrase"

        # ACCEPT: always grounds
        if acceptance == "ACCEPT":
            du.state = DUState.GROUNDED
            return "advance"

        # IGNORE: grounding depends on concern overlap only
        if acceptance == "IGNORE":
            if concern_overlap < 0.3:
                du.state = DUState.GROUNDED
                return "advance"
            du.state = DUState.UNGROUNDED
            return "ungrounded_caution"

        return "neutral"

    def compute_gqi(self) -> float:
        """Grounding Quality Index: composite of acceptance and engagement signals.

        50% rolling acceptance EWMA + 25% trend + 15% (1 - consecutive neg) + 10% engagement.
        """
        # Component 1: EWMA acceptance (50%)
        ewma = self._ewma_acceptance

        # Component 2: Trend — are recent turns better than history? (25%)
        if len(self._acceptance_history) >= 3:
            recent = sum(list(self._acceptance_history)[-3:]) / 3
            older = sum(list(self._acceptance_history)[:-3]) / max(
                1, len(self._acceptance_history) - 3
            )
            trend = 0.5 + (recent - older) * 0.5  # normalize around 0.5
            trend = max(0.0, min(1.0, trend))
        else:
            trend = 0.5  # unknown

        # Component 3: Consecutive negatives penalty (15%)
        neg_penalty = 1.0 - min(1.0, self._consecutive_negative / 3.0)

        # Component 4: Engagement — are we past phatic phase? (10%)
        engagement = 1.0 if len(self._acceptance_history) >= 3 else 0.5

        gqi = 0.50 * ewma + 0.25 * trend + 0.15 * neg_penalty + 0.10 * engagement
        return max(0.0, min(1.0, gqi))

    def effort_calibration(self, activation: float = 0.5) -> EffortDecision:
        """2D effort calibration: activation × (1 - gqi_discount).

        High activation + low GQI = maximum effort (complex + poorly grounded).
        Low activation + high GQI = minimum effort (simple + well grounded).

        Hysteresis: escalation immediate, de-escalation requires 2 consecutive
        turns at the lower level.
        """
        gqi = self.compute_gqi()
        effort_score = activation * (1.0 - gqi * 0.6)  # GQI discounts up to 60%
        effort_score = max(0.0, min(1.0, effort_score))

        # Map to discrete level
        if effort_score > 0.6:
            raw_level = "ELABORATIVE"
            word_limit = 45
        elif effort_score > 0.3:
            raw_level = "BASELINE"
            word_limit = 33
        else:
            raw_level = "EFFICIENT"
            word_limit = 23

        # Hysteresis: escalation is immediate, de-escalation is damped
        level_order = {"EFFICIENT": 0, "BASELINE": 1, "ELABORATIVE": 2}
        current_rank = level_order.get(self._effort_level, 1)
        new_rank = level_order.get(raw_level, 1)

        if new_rank > current_rank:
            # Escalation: immediate
            self._effort_level = raw_level
            self._effort_hold_turns = 0
        elif new_rank < current_rank:
            # De-escalation: require 2 consecutive turns at lower level
            self._effort_hold_turns += 1
            if self._effort_hold_turns >= 2:
                self._effort_level = raw_level
                self._effort_hold_turns = 0
            else:
                # Hold at current level
                raw_level = self._effort_level
                word_limit = {
                    "EFFICIENT": 23,
                    "BASELINE": 33,
                    "ELABORATIVE": 45,
                }[self._effort_level]
        else:
            # Same rank: preserve hold counter for in-progress de-escalation
            pass

        return EffortDecision(
            effort_score=round(effort_score, 3),
            word_limit=word_limit,
            level_name=raw_level,
        )

    def grounding_directive(self) -> str:
        """Generate the grounding directive for VOLATILE band injection.

        Encodes Traum (1994) responsive grounding acts as directive text.
        """
        if not self._units:
            return ""

        du = self._units[-1]
        strategy = "neutral"

        if du.state == DUState.GROUNDED:
            strategy = "advance"
        elif du.state == DUState.REPAIR_1:
            strategy = "rephrase"
        elif du.state == DUState.REPAIR_2:
            strategy = "elaborate"
        elif du.state == DUState.CONTESTED:
            strategy = "present_reasoning"
        elif du.state == DUState.ABANDONED:
            strategy = "move_on"
        elif du.state == DUState.UNGROUNDED:
            strategy = "ungrounded_caution"
        elif du.state == DUState.PENDING and len(self._units) >= 2:
            strategy = "neutral"  # neutral includes check-understanding act

        directive = _STRATEGY_DIRECTIVES.get(strategy, _STRATEGY_DIRECTIVES["neutral"])
        return f"## Grounding Directive\n{directive}"

    @property
    def last_du_state(self) -> str:
        """Current state of the most recent DU, for Langfuse logging."""
        if not self._units:
            return "none"
        return self._units[-1].state.value

    @property
    def ungrounded_count(self) -> int:
        """Number of DUs that ended ungrounded or abandoned."""
        return sum(1 for du in self._units if du.state in (DUState.UNGROUNDED, DUState.ABANDONED))
