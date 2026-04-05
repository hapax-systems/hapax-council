"""Satellite recruitment state management for the Reverie mixer.

Tracks which shader nodes are recruited, handles decay/dismissal,
and triggers graph rebuilds when the set changes.
"""

from __future__ import annotations

import logging
import time

from agents.effect_graph.wgsl_compiler import compile_to_wgsl_plan, write_wgsl_pipeline
from agents.reverie._graph_builder import build_graph

log = logging.getLogger("reverie.satellites")

RECRUITMENT_THRESHOLD = 0.3
DISMISSAL_THRESHOLD = 0.05
REBUILD_COOLDOWN_S = 2.0

# When a single decay call removes more than this amount, the satellite is treated as
# "genuinely absent" and its habituation counter resets. This distinguishes gradual
# attrition (small dt, counter persists → re-recruitment stays habituated) from
# deliberate or long-interval dismissal (large dt, counter clears → fresh start).
_HABITUATION_RESET_REMOVED = 0.5


class SatelliteManager:
    """Manages satellite node recruitment, decay, and graph rebuilds."""

    def __init__(self, core_vocab: dict, decay_rate: float = 0.02) -> None:
        self._core_vocab = core_vocab
        self._decay_rate = decay_rate
        self._recruited: dict[str, float] = {}
        self._recruit_count: dict[str, int] = {}
        self._active_set: frozenset[str] = frozenset()
        self._last_rebuild = 0.0

    @property
    def recruited(self) -> dict[str, float]:
        return dict(self._recruited)

    @property
    def active_count(self) -> int:
        return len(self._recruited)

    def recruit(self, node_type: str, strength: float) -> None:
        """Recruit a satellite node with habituating refresh.

        First-ever recruitment (or after deliberate absence) sets full strength.
        Re-recruitment of an active or recently-dismissed satellite applies
        divisive normalization (Carandini-Heeger): gain = 1 / (1 + count * 0.5),
        where count grows with each recruit call and persists across gradual decay
        dismissals. This ensures:

        - Monotonic input: decay eventually wins (gain → 0 as count grows).
        - Novel stronger signals: still boost effectively (gain > 0 ensures headroom).
        - Deliberate absence (large decay in one call): habituation resets to fresh.
        """
        if strength < RECRUITMENT_THRESHOLD:
            return
        prev = self._recruited.get(node_type, 0.0)
        count = self._recruit_count.get(node_type, 0)
        if prev > 0 or count > 0:
            # Divisive normalization: effective strength decreases with recruit count.
            # count=1: gain=0.667 (first re-recruit, moderate attenuation)
            # count=5: gain=0.286 (repeated re-recruit, strong attenuation)
            # gain = eff/strength = 1/(1+count*0.5) ensures new always drifts toward eff.
            effective = strength / (1.0 + count * 0.5)
            gain = effective / strength  # = 1 / (1 + count * 0.5)
            if prev > 0:
                self._recruited[node_type] = prev + (effective - prev) * gain
            else:
                # Re-recruited after gradual dismissal: start from habituated effective.
                self._recruited[node_type] = effective
            self._recruit_count[node_type] = count + 1
        else:
            # First-ever recruitment (or after deliberate/long absence): full strength.
            self._recruited[node_type] = strength
            self._recruit_count[node_type] = 1
        if node_type not in self._active_set:
            log.info("Satellite recruited: %s (strength=%.2f)", node_type, strength)

    def decay(self, dt: float) -> None:
        """Decay all satellite strengths, dismiss below threshold.

        If a single decay call removes more than _HABITUATION_RESET_REMOVED units
        of strength (i.e., a large dt representing deliberate or long absence),
        the habituation counter is cleared so re-recruitment starts fresh.
        For small incremental decay calls, the counter persists to keep re-entry
        habituated.
        """
        removed_per_call = self._decay_rate * dt
        for node_type in list(self._recruited):
            self._recruited[node_type] -= removed_per_call
            if self._recruited[node_type] < DISMISSAL_THRESHOLD:
                del self._recruited[node_type]
                if removed_per_call > _HABITUATION_RESET_REMOVED:
                    self._recruit_count.pop(node_type, None)
                # else: count persists for habituated re-entry
                log.info("Satellite dismissed: %s", node_type)

    def maybe_rebuild(self) -> bool:
        """Rebuild the shader graph if the recruited set changed. Returns True if rebuilt."""
        current_set = frozenset(self._recruited.keys())
        if current_set == self._active_set:
            return False

        now = time.monotonic()
        if now - self._last_rebuild < REBUILD_COOLDOWN_S:
            return False

        try:
            graph = build_graph(self._core_vocab, self._recruited)
            plan = compile_to_wgsl_plan(graph)
            write_wgsl_pipeline(plan)
        except Exception:
            log.exception("Graph rebuild failed — keeping previous graph")
            return False

        pass_count = len(plan.get("passes", []))
        log.info(
            "Graph rebuilt: %d passes (%d satellites: %s)",
            pass_count,
            len(self._recruited),
            ", ".join(sorted(self._recruited.keys())) or "none",
        )

        self._active_set = current_set
        self._last_rebuild = now
        return True
