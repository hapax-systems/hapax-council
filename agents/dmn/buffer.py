"""DMN buffer — accumulates observations, formats for U-curve consumption.

The buffer is the retentional structure. It is NOT the DMN model's memory —
it is an external data structure managed by the system, formatted for
consumption by the TPN (deliberative) model.

Buffer layout aligned to the U-curve (primacy + recency privilege):
  - Position 0: Consolidated retentional summary (primacy zone)
  - Middle: Older observations (naturally deprioritized by lost-in-the-middle)
  - Position end: Most recent observations + deltas (recency zone)
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field

log = logging.getLogger("dmn.buffer")

# Buffer limits
MAX_RAW_ENTRIES = 18  # ~90 seconds at 5s tick
MAX_BUFFER_TOKENS = 1500  # approximate token budget for DMN context
CONSOLIDATION_THRESHOLD = 12  # consolidate when raw entries exceed this


@dataclass
class Observation:
    """A single DMN sensory tick output."""

    tick: int
    timestamp: float
    content: str  # 1-sentence situation fragment
    raw_sensor: str = ""  # raw sensor prompt (external grounding, never DMN output)
    deltas: list[str] = field(default_factory=list)  # what changed

    @property
    def age_s(self) -> float:
        return time.time() - self.timestamp

    def format(self) -> str:
        parts = [f'<dmn_observation tick="{self.tick}" age="{self.age_s:.0f}s">']
        parts.append(self.content)
        for d in self.deltas:
            parts.append(f" DELTA: {d}")
        parts.append("</dmn_observation>")
        return "".join(parts)


@dataclass
class Evaluation:
    """A single DMN evaluative tick output."""

    tick: int
    timestamp: float
    trajectory: str  # "improving", "degrading", "stable"
    concerns: list[str] = field(default_factory=list)

    def format(self) -> str:
        concern_str = "; ".join(self.concerns) if self.concerns else "none"
        return (
            f'<dmn_evaluation tick="{self.tick}" age="{self.age_s:.0f}s">'
            f" Trajectory: {self.trajectory}. Concerns: {concern_str} "
            f"</dmn_evaluation>"
        )

    @property
    def age_s(self) -> float:
        return time.time() - self.timestamp


class DMNBuffer:
    """Manages the DMN observation buffer with U-curve-aligned formatting."""

    def __init__(self) -> None:
        self._observations: deque[Observation] = deque(maxlen=MAX_RAW_ENTRIES)
        self._evaluations: deque[Evaluation] = deque(maxlen=6)
        self._retentional_summary: str = ""
        self._tick_counter: int = 0
        self._last_consolidation: float = 0.0
        self._imagination_context: str = ""

    @property
    def tick(self) -> int:
        return self._tick_counter

    def add_observation(
        self, content: str, deltas: list[str] | None = None, raw_sensor: str = ""
    ) -> None:
        """Add a sensory tick observation.

        Args:
            content: DMN-generated situation fragment (or "stable")
            deltas: list of state changes since prior tick
            raw_sensor: the raw sensor prompt (external grounding, stored for consolidation)
        """
        self._tick_counter += 1
        self._observations.append(
            Observation(
                tick=self._tick_counter,
                timestamp=time.time(),
                content=content,
                deltas=deltas or [],
                raw_sensor=raw_sensor,
            )
        )

    def add_evaluation(self, trajectory: str, concerns: list[str] | None = None) -> None:
        """Add an evaluative tick assessment."""
        self._evaluations.append(
            Evaluation(
                tick=self._tick_counter,
                timestamp=time.time(),
                trajectory=trajectory,
                concerns=concerns or [],
            )
        )

    def set_retentional_summary(self, summary: str) -> None:
        """Set the consolidated retentional summary (position 0)."""
        self._retentional_summary = summary
        self._last_consolidation = time.time()

    def set_imagination_context(self, salience: float, material: str, narrative: str) -> None:
        """Set imagination context for TPN consumption."""
        self._imagination_context = (
            f'<imagination_context salience="{salience:.2f}" material="{material}">'
            f"{narrative[:120]}</imagination_context>"
        )

    def needs_consolidation(self) -> bool:
        """Check if buffer has enough entries to warrant consolidation."""
        if len(self._observations) < CONSOLIDATION_THRESHOLD:
            return False
        # Skip if all entries since last consolidation are "stable"
        cutoff = self._last_consolidation
        recent = [o for o in self._observations if o.timestamp > cutoff]
        return any(o.content != "stable" for o in recent)

    def get_consolidation_input(self) -> str:
        """Get RAW SENSOR DATA for consolidation — never DMN's own output.

        Returns the raw_sensor strings from older observations, which are
        the original sensor prompts (external grounding). This prevents
        hallucination snowballing from the DMN reading its own output.
        """
        lines = []
        for obs in list(self._observations)[: CONSOLIDATION_THRESHOLD // 2]:
            if obs.raw_sensor:
                lines.append(obs.raw_sensor)
            elif obs.content != "stable":
                # Fallback: use content only if no raw_sensor stored (shouldn't happen)
                lines.append(obs.content)
        return "\n".join(lines)

    def prune_consolidated(self) -> int:
        """Remove old observations after consolidation. Returns count removed."""
        count = CONSOLIDATION_THRESHOLD // 2
        removed = 0
        while removed < count and self._observations:
            self._observations.popleft()
            removed += 1
        return removed

    def format_for_tpn(self) -> str:
        """Format the buffer for TPN consumption, aligned to U-curve.

        Layout:
          [PRIMACY] Retentional summary
          [MIDDLE]  Older observations (deprioritized naturally)
          [RECENCY] Latest observations + latest evaluation

        Middle-zone observations are trimmed oldest-first to stay within
        MAX_BUFFER_TOKENS (estimated as len/4).
        """
        primacy = ""
        if self._retentional_summary:
            primacy = f"<retentional_summary>{self._retentional_summary}</retentional_summary>"

        imagination = self._imagination_context if self._imagination_context else ""

        obs_list = list(self._observations)
        middle = [obs.format() for obs in obs_list[:-6]] if len(obs_list) > 6 else []
        recent_obs = obs_list[-6:] if len(obs_list) > 6 else obs_list
        recency = [obs.format() for obs in recent_obs]
        if self._evaluations:
            recency.append(self._evaluations[-1].format())

        # Trim middle zone to stay within token budget
        while middle:
            parts = [p for p in [primacy, imagination] + middle + recency if p]
            text = "\n".join(parts)
            if len(text) // 4 <= MAX_BUFFER_TOKENS:
                return text
            middle.pop(0)

        parts = [p for p in [primacy, imagination] + recency if p]
        return "\n".join(parts)

    def format_delta_context(
        self, prior_snapshot: dict | None, current_snapshot: dict | None
    ) -> list[str]:
        """Compute deltas between two sensor snapshots."""
        if not prior_snapshot or not current_snapshot:
            return []

        deltas = []

        # Perception deltas
        pp = prior_snapshot.get("perception", {})
        cp = current_snapshot.get("perception", {})
        if pp.get("activity") != cp.get("activity"):
            deltas.append(f"activity: {pp.get('activity')} → {cp.get('activity')}")
        flow_delta = abs(cp.get("flow_score", 0) - pp.get("flow_score", 0))
        if flow_delta > 0.1:
            deltas.append(f"flow: {pp.get('flow_score', 0):.1f} → {cp.get('flow_score', 0):.1f}")

        # Stimmung deltas
        ps = prior_snapshot.get("stimmung", {})
        cs = current_snapshot.get("stimmung", {})
        if ps.get("stance") != cs.get("stance"):
            deltas.append(f"stimmung: {ps.get('stance')} → {cs.get('stance')}")

        # Fortress deltas
        pf = prior_snapshot.get("fortress") or {}
        cf = current_snapshot.get("fortress") or {}
        if pf and cf:
            if pf.get("population", 0) != cf.get("population", 0):
                deltas.append(f"population: {pf.get('population')} → {cf.get('population')}")
            if pf.get("drink", 0) != cf.get("drink", 0):
                deltas.append(f"drink: {pf.get('drink')} → {cf.get('drink')}")
            if pf.get("food", 0) != cf.get("food", 0):
                food_delta = cf.get("food", 0) - pf.get("food", 0)
                if abs(food_delta) > 5:
                    deltas.append(f"food: {pf.get('food')} → {cf.get('food')}")
            if pf.get("threats", 0) != cf.get("threats", 0):
                deltas.append(f"threats: {pf.get('threats')} → {cf.get('threats')}")

        return deltas

    def recent_observations(self, n: int = 5) -> list[str]:
        """Return content strings of the last N observations."""
        obs = list(self._observations)
        return [o.content for o in obs[-n:]]

    def __len__(self) -> int:
        return len(self._observations)

    def __repr__(self) -> str:
        return (
            f"DMNBuffer(obs={len(self._observations)}, "
            f"evals={len(self._evaluations)}, "
            f"tick={self._tick_counter})"
        )
