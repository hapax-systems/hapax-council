"""Chunk compressor — reduces fortress state to 4 perceptual chunks.

Each chunk is one sentence (max ~25 tokens) summarizing a domain.
Chunks compress per Cowan's 4-item working memory limit.
Severity detection drives chunk expansion under crisis.
"""

from __future__ import annotations

import logging
from enum import StrEnum

from agents.fortress.schema import FastFortressState, FullFortressState

log = logging.getLogger(__name__)


class Severity(StrEnum):
    NOMINAL = "nominal"
    WARNING = "warning"
    CRITICAL = "critical"


class ChunkCompressor:
    """Compresses fortress state into exactly 4 natural-language chunks."""

    def compress(
        self,
        state: FastFortressState | FullFortressState,
        prev: FastFortressState | FullFortressState | None = None,
    ) -> list[str]:
        return [
            self._food_chunk(state, prev),
            self._population_chunk(state, prev),
            self._industry_chunk(state, prev),
            self._safety_chunk(state, prev),
        ]

    def severity(self, state: FastFortressState | FullFortressState) -> dict[str, Severity]:
        """Return severity per domain for expansion decisions."""
        pop = max(1, state.population)
        return {
            "food": (
                Severity.CRITICAL
                if state.food_count < pop * 5 or state.drink_count < pop * 2
                else Severity.WARNING
                if state.food_count < pop * 10 or state.drink_count < pop * 5
                else Severity.NOMINAL
            ),
            "population": (
                Severity.CRITICAL
                if state.most_stressed_value > 100_000
                else Severity.WARNING
                if state.most_stressed_value > 50_000 or state.idle_dwarf_count > pop * 0.5
                else Severity.NOMINAL
            ),
            "industry": Severity.NOMINAL,  # needs FullFortressState for workshop data
            "safety": (
                Severity.CRITICAL
                if state.active_threats > 20
                else Severity.WARNING
                if state.active_threats > 0
                else Severity.NOMINAL
            ),
        }

    def _delta(self, current: int, prev: int | None) -> str:
        if prev is None:
            return ""
        diff = current - prev
        if diff > 0:
            return f", +{diff}"
        if diff < 0:
            return f", {diff}"
        return ", stable"

    def _food_chunk(self, state, prev) -> str:
        pop = max(1, state.population)
        food_per = state.food_count / pop
        drink_per = state.drink_count / pop

        if state.drink_count < pop * 2:
            urgency = "CRITICAL"
        elif state.food_count < pop * 5:
            urgency = "WARNING"
        else:
            urgency = ""

        food_d = self._delta(state.food_count, prev.food_count if prev else None)
        drink_d = self._delta(state.drink_count, prev.drink_count if prev else None)

        prefix = f"[{urgency}] " if urgency else ""
        return (
            f"{prefix}Food: {state.food_count}{food_d}. "
            f"Drink: {state.drink_count}{drink_d}. "
            f"({food_per:.0f}/{drink_per:.0f} per dwarf)"
        )

    def _population_chunk(self, state, prev) -> str:
        pop_d = self._delta(state.population, prev.population if prev else None)
        idle = state.idle_dwarf_count
        stress = state.most_stressed_value

        if stress > 100_000:
            mood = "in crisis"
        elif stress > 50_000:
            mood = "stressed"
        else:
            mood = "content"

        return f"Pop: {state.population}{pop_d}. {idle} idle. Mood: {mood}."

    def _industry_chunk(self, state, prev) -> str:
        if isinstance(state, FullFortressState) and state.workshops:
            active = sum(1 for w in state.workshops if w.is_active)
            total = len(state.workshops)
            return f"Workshops: {active}/{total} active. Jobs queued: {state.job_queue_length}."
        return f"Industry: {state.job_queue_length} jobs queued."

    def _safety_chunk(self, state, prev) -> str:
        if state.active_threats > 0:
            return f"[CRITICAL] THREATS: {state.active_threats} hostiles detected!"
        return "Safety: clear. No threats."
