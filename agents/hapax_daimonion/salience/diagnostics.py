"""Salience routing diagnostics and observability.

Per-utterance activation breakdown logging and concern anchor inspection.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.hapax_daimonion.salience.concern_graph import ConcernGraph
    from agents.hapax_daimonion.salience_router import SalienceRouter

log = logging.getLogger(__name__)


class SalienceDiagnostics:
    """Observability for the salience routing system."""

    def __init__(self, router: SalienceRouter, concern_graph: ConcernGraph) -> None:
        self._router = router
        self._graph = concern_graph
        self._history: list[dict] = []
        self._max_history: int = 200

    def record(self, transcript: str) -> None:
        """Record a routing decision for post-hoc analysis."""
        breakdown = self._router.last_breakdown
        if breakdown is None:
            return

        entry = {
            "transcript": transcript[:100],
            **asdict(breakdown),
        }
        self._history.append(entry)
        if len(self._history) > self._max_history:
            self._history.pop(0)

    def get_history(self) -> list[dict]:
        """Return activation history for the current session."""
        return list(self._history)

    def get_anchor_summary(self) -> dict:
        """Return current concern anchor state for diagnostics."""
        return {
            "anchor_count": self._graph.anchor_count,
            "sources": self._graph.get_anchor_sources(),
            "texts": self._graph.get_anchor_texts()[:20],  # cap for readability
        }

    def get_stats(self) -> dict:
        """Aggregate statistics from activation history."""
        if not self._history:
            return {"entries": 0}

        activations = [h["final_activation"] for h in self._history]
        tiers = {}
        for h in self._history:
            tier = h["tier"]
            tiers[tier] = tiers.get(tier, 0) + 1

        return {
            "entries": len(self._history),
            "mean_activation": sum(activations) / len(activations),
            "min_activation": min(activations),
            "max_activation": max(activations),
            "tier_distribution": tiers,
            "mean_embed_ms": sum(h["embed_ms"] for h in self._history) / len(self._history),
            "mean_total_ms": sum(h["total_ms"] for h in self._history) / len(self._history),
        }
