"""Active correction seeking — system asks for corrections when uncertain.

WS3 Level 4: instead of waiting for the operator to notice errors, the
system proactively surfaces low-confidence interpretations as ambient
questions. Minimally intrusive: appears in the visual layer's ambient
text, not as an interruption.

Constraints:
  - Exploration budget: max queries per day (default 5)
  - Diminishing: don't re-ask about the same dimension+value combo
  - Cooldown: minimum time between queries (default 10 min)
  - Only asks when confidence is below threshold

Uses:
  - Stimmung perception_confidence for uncertainty detection
  - Correction memory similarity for "have we asked about this before?"
  - Visual layer ambient text channel for non-intrusive surfacing
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

log = logging.getLogger("active_correction")

QUESTION_FILE = Path("/dev/shm/hapax-compositor/correction-question.json")

# ── Data Models ──────────────────────────────────────────────────────────────


class CorrectionQuestion(BaseModel):
    """A question the system wants to ask the operator."""

    dimension: str  # what we're uncertain about (activity, flow, etc.)
    current_value: str  # what the system currently thinks
    confidence: float  # how uncertain we are (lower = more uncertain)
    question: str  # human-readable question text
    timestamp: float = 0.0
    answered: bool = False


class CorrectionSeeker:
    """Manages the system's proactive correction-seeking behavior.

    Pure logic + file writes. Call evaluate() each perception tick with
    current state. If uncertain enough, writes a question for the visual
    layer to surface.

    Usage:
        seeker = CorrectionSeeker()
        question = seeker.evaluate(
            activity="coding",
            flow_score=0.4,
            confidence=0.3,  # low confidence
            hour=14,
        )
        if question:
            # question written to /dev/shm for visual layer
            pass
    """

    def __init__(
        self,
        daily_budget: int = 5,
        cooldown_s: float = 600.0,  # 10 min
        confidence_threshold: float = 0.4,
    ) -> None:
        self._daily_budget = daily_budget
        self._cooldown_s = cooldown_s
        self._confidence_threshold = confidence_threshold

        # State
        self._queries_today: list[CorrectionQuestion] = []
        self._last_query_time: float = 0.0
        self._asked_combos: set[tuple[str, str]] = set()  # (dimension, value)
        self._current_day: int = 0  # day number for budget reset

    def evaluate(
        self,
        activity: str = "",
        flow_score: float = 0.0,
        confidence: float = 1.0,
        hour: int = 0,
        stimmung_stance: str = "nominal",
        correction_store: Any | None = None,
    ) -> CorrectionQuestion | None:
        """Evaluate whether to ask a correction question.

        Returns a CorrectionQuestion if we should ask, None otherwise.
        """
        now = time.time()

        # Reset daily budget
        day = int(now / 86400)
        if day != self._current_day:
            self._current_day = day
            self._queries_today = []

        # Budget exhausted
        if len(self._queries_today) >= self._daily_budget:
            return None

        # Cooldown
        if now - self._last_query_time < self._cooldown_s:
            return None

        # System stressed — don't bother operator
        if stimmung_stance in ("degraded", "critical"):
            return None

        # Find the most uncertain dimension
        question = self._find_uncertainty(activity, flow_score, confidence, hour, correction_store)
        if question is None:
            return None

        # Record and write
        question.timestamp = now
        self._queries_today.append(question)
        self._last_query_time = now
        self._asked_combos.add((question.dimension, question.current_value))

        self._write_question(question)
        log.info("Asked correction question: %s", question.question)
        return question

    def record_answer(self, dimension: str, value: str) -> None:
        """Record that the operator answered a question (via correction file).

        Called by the aggregator when it detects a correction was submitted.
        """
        self._asked_combos.add((dimension, value))

    @property
    def queries_remaining_today(self) -> int:
        return max(0, self._daily_budget - len(self._queries_today))

    @property
    def total_asked(self) -> int:
        return len(self._asked_combos)

    def _find_uncertainty(
        self,
        activity: str,
        flow_score: float,
        confidence: float,
        hour: int,
        correction_store: Any | None,
    ) -> CorrectionQuestion | None:
        """Find the most actionable uncertainty to ask about."""

        # Check if overall confidence is below threshold
        if confidence >= self._confidence_threshold:
            return None

        # Activity uncertainty — most common and most actionable
        if activity and (("activity", activity) not in self._asked_combos):
            # Check if we've been corrected on this before
            similar_corrections = 0
            if correction_store is not None:
                try:
                    matches = correction_store.search_for_dimension("activity", activity, limit=3)
                    similar_corrections = len(matches)
                except Exception:
                    log.warning(
                        "Correction search failed during uncertainty estimation", exc_info=True
                    )

            # More prior corrections → more reason to ask
            urgency = "often" if similar_corrections >= 2 else "sometimes"
            question_text = f"Is '{activity}' right? (I'm {urgency} uncertain about this)"

            return CorrectionQuestion(
                dimension="activity",
                current_value=activity,
                confidence=confidence,
                question=question_text,
            )

        # Flow state uncertainty
        flow_state = "active" if flow_score >= 0.6 else ("warming" if flow_score >= 0.3 else "idle")
        if ("flow", flow_state) not in self._asked_combos and flow_score > 0.2:
            return CorrectionQuestion(
                dimension="flow",
                current_value=flow_state,
                confidence=confidence,
                question=f"Flow looks '{flow_state}' — accurate?",
            )

        return None

    @staticmethod
    def _write_question(question: CorrectionQuestion) -> None:
        """Write question to /dev/shm for visual layer to surface."""
        try:
            QUESTION_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = QUESTION_FILE.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(question.model_dump()),
                encoding="utf-8",
            )
            tmp.rename(QUESTION_FILE)
        except OSError:
            log.debug("Failed to write correction question", exc_info=True)


# ── Visual Layer Integration ─────────────────────────────────────────────────


def read_pending_question() -> CorrectionQuestion | None:
    """Read the current pending question (for visual layer to display).

    Returns None if no question or question is stale (>30 min).

    Catches Pydantic ``ValidationError`` alongside the json parse
    errors. A writer producing valid JSON whose root is null, a list,
    a string, or a number raised ValidationError out of the visual-
    layer correction-question display path. Same shape as the other
    recent SHM-read fixes — the leak channel is Pydantic
    model_validate rather than .get(), but the failure mode is
    identical: corrupt SHM crashes the consumer.
    """
    from pydantic import ValidationError

    try:
        data = json.loads(QUESTION_FILE.read_text(encoding="utf-8"))
        question = CorrectionQuestion.model_validate(data)
        if question.answered:
            return None
        # Stale after 30 min
        if question.timestamp and (time.time() - question.timestamp) > 1800:
            return None
        return question
    except (OSError, json.JSONDecodeError, ValidationError):
        return None
