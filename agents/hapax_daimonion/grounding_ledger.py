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
import json
import logging
import statistics
import time as _time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Effort word-limit envelope (the documented EffortDecision range). These are range
# bounds, not presets: word_limit is a continuum across [WORD_MIN, WORD_MAX], never
# discrete buckets (no-presets — variance comes from parametric modulation).
WORD_MIN = 22
WORD_MAX = 48


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
        self._effort_level: str = "BASELINE"  # latest band label (snapshot/display only)
        self._effort_ewma: float = 0.5  # smoothed effort score (asymmetric slew)

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

    def _gqi_discount(self) -> float:
        """Ledger-fit coefficient for how much GQI discounts effort (replaces the
        former fixed 0.6).

        GQI is trusted to reduce effort MORE when grounding has proven reliable
        (high, stable acceptance) and LESS when acceptance has been low or volatile
        — fitted from the acceptance ledger, never a preset. Coefficient ∈ [0, 1].
        """
        hist = self._acceptance_history
        if len(hist) < 3:
            return self._ewma_acceptance  # cold prior: trust ∝ early acceptance (0.5 neutral)
        volatility = statistics.pstdev(hist)
        # high + stable acceptance trusts GQI; volatility erodes that trust.
        fit = self._ewma_acceptance * (1.0 - min(1.0, 2.0 * volatility))
        return max(0.0, min(1.0, fit))

    @staticmethod
    def _effort_label(score: float) -> str:
        """Qualitative band label for the directive/snapshot. Display only — the
        actual verbosity is the continuum word_limit, not this label."""
        if score > 0.66:
            return "ELABORATIVE"
        if score > 0.33:
            return "BASELINE"
        return "EFFICIENT"

    def effort_calibration(self, activation: float = 0.5) -> EffortDecision:
        """2D effort calibration: activation × (1 − GQI·discount), slewed.

        High activation + low GQI ⇒ maximum effort (complex + poorly grounded);
        low activation + high GQI ⇒ minimum effort. The word limit is a continuum
        over [WORD_MIN, WORD_MAX] (no preset buckets); the GQI discount is
        ledger-fit (no fixed 0.6). De-escalation is damped by an asymmetric EWMA
        (escalation immediate) — the parametric successor to the former discrete
        level hysteresis.
        """
        gqi = self.compute_gqi()
        raw = max(0.0, min(1.0, activation * (1.0 - gqi * self._gqi_discount())))

        # Asymmetric slew: escalate immediately, de-escalate gradually.
        if raw >= self._effort_ewma:
            self._effort_ewma = raw
        else:
            self._effort_ewma = 0.5 * raw + 0.5 * self._effort_ewma
        score = self._effort_ewma

        word_limit = round(WORD_MIN + score * (WORD_MAX - WORD_MIN))
        self._effort_level = self._effort_label(score)
        return EffortDecision(
            effort_score=round(score, 3),
            word_limit=word_limit,
            level_name=self._effort_level,
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

    # ── Session persistence (CHI evidence trail) ────────────────────────

    _SESSIONS_DIR = Path.home() / "hapax-state" / "research" / "grounding-sessions"

    def _session_snapshot(self) -> dict[str, object]:
        """Build a JSON-serialisable snapshot of the current session."""
        grounded = sum(1 for du in self._units if du.state == DUState.GROUNDED)
        repair = sum(1 for du in self._units if du.state in (DUState.REPAIR_1, DUState.REPAIR_2))
        return {
            "final_gqi": round(self.compute_gqi(), 4),
            "total_dus": len(self._units),
            "grounded_count": grounded,
            "ungrounded_count": self.ungrounded_count,
            "repair_count": repair,
            "effort_level": self._effort_level,
            "acceptance_trajectory": list(self._acceptance_history),
            "units": [
                {
                    "turn": du.turn,
                    "summary": du.content_summary,
                    "state": du.state.value,
                    "repair_count": du.repair_count,
                    "concern_weight": du.concern_weight,
                }
                for du in self._units
            ],
        }

    def save_session(self, session_id: str, *, directory: Path | None = None) -> Path:
        """Persist session snapshot to ``{directory}/{session_id}.json``.

        Creates the directory on first write. Returns the written path.
        """
        target_dir = directory or self._SESSIONS_DIR
        target_dir.mkdir(parents=True, exist_ok=True)

        snapshot = self._session_snapshot()
        snapshot["session_id"] = session_id
        snapshot["timestamp"] = _time.time()

        path = target_dir / f"{session_id}.json"
        path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        log.info("GQI session saved: %s", path)
        return path

    @classmethod
    def load_session(cls, session_id: str, *, directory: Path | None = None) -> dict[str, object]:
        """Load a previously saved session snapshot.

        Returns the parsed JSON dict. Raises ``FileNotFoundError`` if no
        snapshot exists for *session_id*.
        """
        target_dir = directory or cls._SESSIONS_DIR
        path = target_dir / f"{session_id}.json"
        return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[return-value]
