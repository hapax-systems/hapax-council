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

# If a satellite hasn't been recruited for this many seconds after dismissal,
# its habituation counter resets and re-recruitment starts fresh. Shorter gaps
# (satellite flickers out and back) retain habituation.
_HABITUATION_RESET_S = 15.0


class SatelliteManager:
    """Manages satellite node recruitment, decay, and graph rebuilds."""

    def __init__(self, core_vocab: dict, decay_rate: float = 0.02) -> None:
        self._core_vocab = core_vocab
        self._decay_rate = decay_rate
        self._recruited: dict[str, float] = {}
        self._recruit_count: dict[str, int] = {}
        self._last_recruit_ts: dict[str, float] = {}
        self._recruited_this_tick: set[str] = set()
        self._active_set: frozenset[str] = frozenset()
        self._last_rebuild = 0.0

    def begin_tick(self) -> None:
        """Reset per-tick dedup gate. Call once at the start of each mixer tick."""
        self._recruited_this_tick.clear()

    @property
    def recruited(self) -> dict[str, float]:
        return dict(self._recruited)

    @property
    def active_count(self) -> int:
        return len(self._recruited)

    def recruit(self, node_type: str, strength: float) -> None:
        """Recruit a satellite node with habituating refresh.

        Per-tick dedup: only one recruit per satellite type per tick. Multiple
        impingements targeting the same satellite within a single tick are
        redundant — the governance cadence is 1s, not per-impingement.

        First-ever recruitment (or after prolonged absence) sets full strength.
        Re-recruitment applies divisive normalization (Carandini-Heeger):
        gain = 1 / (1 + count * 0.5). Habituation resets after _HABITUATION_RESET_S.
        """
        if strength < RECRUITMENT_THRESHOLD:
            return
        if node_type in self._recruited_this_tick:
            return
        self._recruited_this_tick.add(node_type)
        now = time.monotonic()
        prev = self._recruited.get(node_type, 0.0)
        count = self._recruit_count.get(node_type, 0)
        last_ts = self._last_recruit_ts.get(node_type, 0.0)

        # Reset habituation if satellite hasn't been recruited for a while
        if count > 0 and (now - last_ts) > _HABITUATION_RESET_S:
            count = 0

        if prev > 0 or count > 0:
            effective = strength / (1.0 + count * 0.5)
            gain = effective / strength  # = 1 / (1 + count * 0.5)
            if prev > 0:
                self._recruited[node_type] = prev + (effective - prev) * gain
            else:
                self._recruited[node_type] = effective
            self._recruit_count[node_type] = count + 1
        else:
            self._recruited[node_type] = strength
            self._recruit_count[node_type] = 1
        self._last_recruit_ts[node_type] = now
        if node_type not in self._active_set:
            log.info("Satellite recruited: %s (strength=%.2f)", node_type, strength)

    def decay(self, dt: float) -> None:
        """Decay all satellite strengths, dismiss below threshold."""
        for node_type in list(self._recruited):
            self._recruited[node_type] -= self._decay_rate * dt
            if self._recruited[node_type] < DISMISSAL_THRESHOLD:
                del self._recruited[node_type]
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
