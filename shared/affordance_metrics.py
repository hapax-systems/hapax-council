"""Affordance pipeline metrics for validation.

Collects and aggregates performance data to measure whether
affordance-retrieval produces better outcomes than static matching.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("affordance_metrics")

METRICS_DIR = Path.home() / ".cache" / "hapax" / "affordance-metrics"


@dataclass
class SelectionEvent:
    """Record of a single pipeline selection."""

    timestamp: float
    impingement_source: str
    impingement_metric: str
    candidates_count: int
    winner: str | None  # capability name or None if no match
    winner_similarity: float
    winner_combined: float
    was_interrupt: bool
    was_fallback: bool  # keyword fallback used (Ollama unavailable)


@dataclass
class OutcomeEvent:
    """Record of a capability activation outcome."""

    timestamp: float
    capability_name: str
    success: bool
    context_cues: dict[str, str] = field(default_factory=dict)


class AffordanceMetrics:
    """Collects pipeline metrics for R5 validation."""

    def __init__(self) -> None:
        self._selections: list[SelectionEvent] = []
        self._outcomes: list[OutcomeEvent] = []

    def record_selection(
        self,
        impingement_source: str,
        impingement_metric: str,
        candidates_count: int,
        winner: str | None,
        winner_similarity: float = 0.0,
        winner_combined: float = 0.0,
        was_interrupt: bool = False,
        was_fallback: bool = False,
    ) -> None:
        self._selections.append(
            SelectionEvent(
                timestamp=time.time(),
                impingement_source=impingement_source,
                impingement_metric=impingement_metric,
                candidates_count=candidates_count,
                winner=winner,
                winner_similarity=winner_similarity,
                winner_combined=winner_combined,
                was_interrupt=was_interrupt,
                was_fallback=was_fallback,
            )
        )

    def record_outcome(
        self,
        capability_name: str,
        success: bool,
        context_cues: dict[str, str] | None = None,
    ) -> None:
        self._outcomes.append(
            OutcomeEvent(
                timestamp=time.time(),
                capability_name=capability_name,
                success=success,
                context_cues=context_cues or {},
            )
        )

    def compute_summary(self) -> dict[str, Any]:
        """Compute validation metrics summary."""
        total_selections = len(self._selections)
        total_outcomes = len(self._outcomes)

        if total_selections == 0:
            return {"status": "no_data", "selections": 0, "outcomes": 0}

        # Selection metrics
        matched = sum(1 for s in self._selections if s.winner is not None)
        interrupts = sum(1 for s in self._selections if s.was_interrupt)
        fallbacks = sum(1 for s in self._selections if s.was_fallback)
        avg_similarity = sum(s.winner_similarity for s in self._selections if s.winner) / max(
            1, matched
        )
        avg_candidates = sum(s.candidates_count for s in self._selections) / total_selections

        # Outcome metrics
        successes = sum(1 for o in self._outcomes if o.success)
        failures = sum(1 for o in self._outcomes if not o.success)
        success_rate = successes / max(1, total_outcomes)

        # Per-capability breakdown
        cap_outcomes: dict[str, dict[str, int]] = {}
        for o in self._outcomes:
            entry = cap_outcomes.setdefault(o.capability_name, {"success": 0, "failure": 0})
            if o.success:
                entry["success"] += 1
            else:
                entry["failure"] += 1

        # Novel associations: capabilities matched for metrics they weren't designed for
        # (detected by low similarity but successful outcome)
        novel_associations = sum(
            1
            for s in self._selections
            if s.winner
            and s.winner_similarity < 0.7
            and any(
                o.capability_name == s.winner and o.success
                for o in self._outcomes
                if abs(o.timestamp - s.timestamp) < 60  # within 1 minute
            )
        )

        return {
            "status": "active",
            "period_start": self._selections[0].timestamp if self._selections else 0,
            "period_end": self._selections[-1].timestamp if self._selections else 0,
            "selections": {
                "total": total_selections,
                "matched": matched,
                "match_rate": matched / total_selections,
                "interrupts": interrupts,
                "fallbacks": fallbacks,
                "avg_similarity": round(avg_similarity, 3),
                "avg_candidates": round(avg_candidates, 1),
            },
            "outcomes": {
                "total": total_outcomes,
                "successes": successes,
                "failures": failures,
                "success_rate": round(success_rate, 3),
            },
            "per_capability": cap_outcomes,
            "novel_associations": novel_associations,
            "convergence": self._estimate_convergence(),
        }

    def _estimate_convergence(self) -> dict[str, Any]:
        """Estimate whether Thompson Sampling has converged.

        Convergence = the last 10 selections for each capability
        have <10% variance in combined score.
        """
        if len(self._selections) < 20:
            return {"converged": False, "reason": "insufficient_data"}

        # Group recent selections by winner
        recent_by_cap: dict[str, list[float]] = defaultdict(list)
        for s in self._selections[-50:]:
            if s.winner:
                recent_by_cap[s.winner].append(s.winner_combined)

        converged_caps = 0
        total_caps = 0
        for _cap, scores in recent_by_cap.items():
            if len(scores) >= 5:
                total_caps += 1
                mean = sum(scores) / len(scores)
                variance = sum((x - mean) ** 2 for x in scores) / len(scores)
                if variance < 0.01:  # <10% std dev
                    converged_caps += 1

        return {
            "converged": converged_caps == total_caps and total_caps > 0,
            "converged_capabilities": converged_caps,
            "total_capabilities": total_caps,
        }

    def save(self) -> None:
        """Persist metrics to disk."""
        METRICS_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "selections": [
                {
                    "timestamp": s.timestamp,
                    "source": s.impingement_source,
                    "metric": s.impingement_metric,
                    "candidates": s.candidates_count,
                    "winner": s.winner,
                    "similarity": s.winner_similarity,
                    "combined": s.winner_combined,
                    "interrupt": s.was_interrupt,
                    "fallback": s.was_fallback,
                }
                for s in self._selections
            ],
            "outcomes": [
                {
                    "timestamp": o.timestamp,
                    "capability": o.capability_name,
                    "success": o.success,
                    "context": o.context_cues,
                }
                for o in self._outcomes
            ],
        }
        path = METRICS_DIR / "metrics.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.rename(path)

    def load(self) -> None:
        """Load persisted metrics."""
        path = METRICS_DIR / "metrics.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            self._selections = [
                SelectionEvent(
                    timestamp=s["timestamp"],
                    impingement_source=s["source"],
                    impingement_metric=s["metric"],
                    candidates_count=s["candidates"],
                    winner=s["winner"],
                    winner_similarity=s["similarity"],
                    winner_combined=s["combined"],
                    was_interrupt=s.get("interrupt", False),
                    was_fallback=s.get("fallback", False),
                )
                for s in data.get("selections", [])
            ]
            self._outcomes = [
                OutcomeEvent(
                    timestamp=o["timestamp"],
                    capability_name=o["capability"],
                    success=o["success"],
                    context_cues=o.get("context", {}),
                )
                for o in data.get("outcomes", [])
            ]
        except Exception:
            log.warning("Failed to load metrics", exc_info=True)
