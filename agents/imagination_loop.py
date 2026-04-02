"""Imagination loop — LLM-driven imagination tick via pydantic-ai.

Drives the continuous imagination process: assembles context from observations
and sensor state, calls a reasoning model, and processes the resulting fragment
(publish, cadence update, escalation).
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

from agents._impingement import Impingement
from agents.imagination import (
    CURRENT_PATH,
    REVERBERATION_THRESHOLD,
    STREAM_PATH,
    VISUAL_OBSERVATION_PATH,
    CadenceController,
    ImaginationFragment,
    assemble_context,
    detect_convergence,
    maybe_escalate,
    publish_fragment,
    reverberation_check,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

IMAGINATION_SYSTEM_PROMPT = """\
You are the imagination process of a personal computing system. You observe
the system's current state and produce spontaneous associations, memories,
projections, and novel connections — the way a human mind wanders during
idle moments.

Your output carries semantic intent only: a narrative describing what you
are imagining, expressive dimensions characterizing its quality, a material
quality, and a salience assessment. You do not decide how or where the
thought is expressed — that is handled by downstream recruitment. Focus on
WHAT you are imagining and WHY it matters.

## Material Quality
Each fragment has an elemental material that determines how it interacts
with the field:
- water: dissolving, flowing, reflective. For contemplative, fluid thoughts.
- fire: consuming, vertical, rapid. For urgent, transformative insights.
- earth: dense, persistent, resistant. For grounded, factual observations.
- air: translucent, drifting, dispersing. For light, fleeting associations.
- void: darkening, absorbing. For absence, loss, emptiness.
Choose the material that matches the character of your thought.

## Expressive Dimensions
Rate the fragment on the nine dimensions (0.0-1.0):
intensity, tension, depth, coherence, spectral_color,
temporal_distortion, degradation, pitch_displacement, diffusion.

Produce one ImaginationFragment. Assess salience honestly — most fragments
are low salience (0.1-0.3). Only mark high salience (>0.6) for genuine
insights or concerns worth escalating.

If your previous fragment had continuation=true, you may continue that
train of thought or let it go. Don't force continuation.\
"""

MAX_RECENT_FRAGMENTS = 5


def observations_are_fresh(*, published_at: float, cadence_s: float) -> bool:
    """Check if observations are fresh enough for imagination.

    Threshold: 2x current cadence. If observations are older than this,
    generating a fragment would be based on stale data.
    """
    age = time.time() - published_at
    return age <= cadence_s * 2.0


class ImaginationLoop:
    """Main loop that drives imagination ticks via an LLM agent."""

    def __init__(
        self,
        current_path: Path | None = None,
        stream_path: Path | None = None,
        visual_observation_path: Path | None = None,
    ):
        self.cadence = CadenceController()
        self.recent_fragments: list[ImaginationFragment] = []
        self._pending_impingements: list[Impingement] = []
        self._current_path = current_path or CURRENT_PATH
        self._stream_path = stream_path or STREAM_PATH
        self._visual_observation_path = visual_observation_path or VISUAL_OBSERVATION_PATH
        self._agent = None  # lazy-init
        self._last_reverberation: float = 0.0

    @property
    def activation_level(self) -> float:
        """Return the salience of the most recent fragment, or 0."""
        if not self.recent_fragments:
            return 0.0
        return self.recent_fragments[-1].salience

    def _get_agent(self):
        """Lazy-init pydantic_ai Agent for imagination generation."""
        if self._agent is None:
            from pydantic_ai import Agent

            from agents._config import get_model

            self._agent = Agent(
                get_model("reasoning"),
                output_type=ImaginationFragment,
                system_prompt=IMAGINATION_SYSTEM_PROMPT,
            )
        return self._agent

    def _record_fragment(self, fragment: ImaginationFragment) -> None:
        """Append fragment to recent list, capping at MAX_RECENT_FRAGMENTS."""
        self.recent_fragments.append(fragment)
        if len(self.recent_fragments) > MAX_RECENT_FRAGMENTS:
            self.recent_fragments = self.recent_fragments[-MAX_RECENT_FRAGMENTS:]

    def _process_fragment(self, fragment: ImaginationFragment) -> None:
        """Record, publish, update cadence, and maybe escalate a fragment."""
        # Force real timestamp and ID — LLMs hallucinate these fields with
        # training-data values (e.g. timestamps from 2024), which makes the
        # silence factor treat every fragment as stale.
        updates: dict = {"timestamp": time.time(), "id": uuid.uuid4().hex[:12]}

        # Break continuation chain when imagination has converged.
        # The context assembly injects a convergence warning, but the LLM may
        # still set continuation=True. Force it False to reset the thought train.
        if detect_convergence(self.recent_fragments):
            updates["continuation"] = False
            self.cadence.force_accelerated(False)
            log.info("Convergence detected — breaking continuation chain")

        fragment = fragment.model_copy(update=updates)
        self._record_fragment(fragment)
        publish_fragment(fragment, self._current_path, self._stream_path)
        self.cadence.update(fragment)
        imp = maybe_escalate(fragment)
        if imp is not None:
            self._pending_impingements.append(imp)

    def drain_impingements(self) -> list[Impingement]:
        """Return and clear pending impingements."""
        result = list(self._pending_impingements)
        self._pending_impingements.clear()
        return result

    def set_tpn_active(self, active: bool) -> None:
        """Delegate TPN state to cadence controller."""
        self.cadence.set_tpn_active(active)

    def _read_visual_observation(self) -> str:
        """Read the DMN's visual observation from shm."""
        try:
            if self._visual_observation_path.exists():
                return self._visual_observation_path.read_text().strip()
        except OSError:
            pass
        return ""

    def _check_reverberation(self) -> float:
        """Compare last fragment's narrative against DMN visual observation."""
        if not self.recent_fragments:
            return 0.0
        perceived = self._read_visual_observation()
        if not perceived:
            return 0.0
        last_narrative = self.recent_fragments[-1].narrative
        reverb = reverberation_check(last_narrative, perceived)
        self._last_reverberation = reverb
        if reverb > REVERBERATION_THRESHOLD:
            log.info("Reverberation %.2f — visual output surprised imagination", reverb)
        return reverb

    async def tick(
        self, observations: list[str], sensor_snapshot: dict
    ) -> ImaginationFragment | None:
        """Run one imagination tick: assemble context, call agent, process result."""
        reverb = self._check_reverberation()

        context = assemble_context(observations, self.recent_fragments, sensor_snapshot)

        if reverb > REVERBERATION_THRESHOLD:
            context += (
                "\n\n## Reverberation\n"
                "The visual output surprised you — what you see differs from what you "
                "imagined. This is generative tension. Lean into the surprise."
            )
            self.cadence.force_accelerated(True)

        try:
            agent = self._get_agent()
            result = await agent.run(context)
            fragment = result.output
            self._process_fragment(fragment)
            return fragment
        except Exception:
            log.warning("Imagination tick failed", exc_info=True)
            return None


# ── Positive Feedback: Engagement → Imagination Acceleration ──────────────

PRESENCE_THRESHOLD = 0.7
AUDIO_ENERGY_THRESHOLD = 0.3


def should_accelerate_from_engagement(perception: dict) -> bool:
    """Check if operator engagement is high enough to accelerate imagination.
    Positive feedback: high presence + audio energy → faster imagination.
    """
    presence = perception.get("presence_probability", 0.0)
    audio = perception.get("audio_energy", 0.0)
    return presence >= PRESENCE_THRESHOLD and audio >= AUDIO_ENERGY_THRESHOLD
