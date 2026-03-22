"""Micro-probes — single experiential questions surfaced during idle moments.

Low initiation cost, high discovery value. Selected by gap analysis:
neurocognitive_profile gaps have highest priority, then other sparse dimensions.

All probes are hardcoded experiential questions, NOT LLM-generated.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from shared.cycle_mode import CycleMode, get_cycle_mode


def _probe_idle_threshold() -> int:
    """Minimum idle seconds before a probe can surface."""
    return 900 if get_cycle_mode() == CycleMode.DEV else 300


def _probe_cooldown() -> int:
    """Minimum seconds between probes."""
    return 1800 if get_cycle_mode() == CycleMode.DEV else 600


# Backward-compatible constants for imports
PROBE_IDLE_THRESHOLD = 300
PROBE_COOLDOWN = 600

from shared.config import LOGOS_STATE_DIR

_STATE_PATH = LOGOS_STATE_DIR / "probe-state.json"


@dataclass
class MicroProbe:
    """A single micro-probe question."""

    dimension: str
    topic: str
    question: str
    rationale: str  # shown to operator: why this matters
    follow_up_hint: str  # context for chat agent to continue
    priority: int  # higher = more urgent


# ── Probe pool ──────────────────────────────────────────────────────────────
# Experiential questions, not diagnostic. Ask about situations and experience.

_PROBE_POOL: list[MicroProbe] = [
    MicroProbe(
        dimension="neurocognitive",
        topic="task_initiation",
        question="When you have a task you've been putting off, what's the thing that finally gets you to start?",
        rationale="understanding what breaks through inertia helps me frame suggestions better",
        follow_up_hint="Explore what conditions, triggers, or framings help the operator begin tasks they've been avoiding.",
        priority=90,
    ),
    MicroProbe(
        dimension="neurocognitive",
        topic="task_persistence",
        question="Think of the last time you were deeply locked in on something. What was it, and what about it held your attention?",
        rationale="knowing what sustains your focus helps me protect those conditions",
        follow_up_hint="Explore what qualities of a task or environment sustain deep focus for the operator.",
        priority=85,
    ),
    MicroProbe(
        dimension="neurocognitive",
        topic="time_perception",
        question="Do you ever look up from work and realize way more time has passed than you thought? When does that tend to happen?",
        rationale="time perception shapes how I should frame durations and deadlines",
        follow_up_hint="Explore whether the operator experiences time blindness and in what contexts.",
        priority=80,
    ),
    MicroProbe(
        dimension="neurocognitive",
        topic="decision_making",
        question="When you're choosing between options, what makes you get stuck? What helps you break through?",
        rationale="decision patterns affect how I present choices",
        follow_up_hint="Explore what causes decision paralysis and what helps resolve it.",
        priority=75,
    ),
    MicroProbe(
        dimension="neurocognitive",
        topic="sensory_environment",
        question="What does your ideal focus environment look and feel like? What breaks it?",
        rationale="sensory context affects cognitive performance — I should know what disrupts yours",
        follow_up_hint="Explore the operator's sensory preferences and sensitivities during focused work.",
        priority=70,
    ),
    MicroProbe(
        dimension="neurocognitive",
        topic="energy_cycles",
        question="If you could map your energy across a typical day, where are the peaks and valleys?",
        rationale="energy patterns affect when different types of work are most productive",
        follow_up_hint="Explore the operator's daily energy fluctuations and how they affect different types of work.",
        priority=65,
    ),
    MicroProbe(
        dimension="neurocognitive",
        topic="motivation",
        question="What's the difference between a project you can't stop thinking about and one that stalls?",
        rationale="understanding what drives engagement helps me prioritize what I surface",
        follow_up_hint="Explore what qualities make a project intrinsically motivating vs. prone to abandonment.",
        priority=60,
    ),
    MicroProbe(
        dimension="neurocognitive",
        topic="demand_sensitivity",
        question="When someone suggests you do something, does how they frame it affect whether you actually want to do it?",
        rationale="framing sensitivity shapes how I should present suggestions and nudges",
        follow_up_hint="Explore whether the operator experiences demand avoidance and what framing works better.",
        priority=55,
    ),
    # ── Other dimensions ───────────────────────────────────────────────
    MicroProbe(
        dimension="work_patterns",
        topic="context_switching",
        question="When you're juggling multiple projects, how do you decide what to work on next?",
        rationale="understanding prioritization habits helps me surface the right work at the right time",
        follow_up_hint="Explore how the operator handles competing priorities and what signals drive task selection.",
        priority=50,
    ),
    MicroProbe(
        dimension="tool_usage",
        topic="tool_discovery",
        question="When you find a new tool or workflow that works, how quickly do you commit to it vs. keep exploring alternatives?",
        rationale="knowing your tool adoption style helps me calibrate how I suggest changes",
        follow_up_hint="Explore whether the operator maximizes (keeps searching) or satisfices (picks good-enough early).",
        priority=45,
    ),
    MicroProbe(
        dimension="creative_process",
        topic="creative_process",
        question="When you're making music, do you usually start from a sample, a rhythm, a melody, or something else entirely?",
        rationale="understanding your creative entry point helps me support your production workflow",
        follow_up_hint="Explore the operator's typical creative starting points and how ideas develop into finished work.",
        priority=40,
    ),
    MicroProbe(
        dimension="values",
        topic="reversibility",
        question="Do you tend to agonize over decisions, or make them quickly and adjust later? Does it depend on what's at stake?",
        rationale="your decision-making speed and style affects how I should present options",
        follow_up_hint="Explore whether the operator favors reversible fast decisions or careful deliberation, and what factors shift the balance.",
        priority=35,
    ),
]


class MicroProbeEngine:
    """Selects and manages micro-probe delivery.

    Deterministic selection based on profile gaps. State persisted to disk.
    """

    def __init__(self) -> None:
        self._asked: set[str] = set()
        self._last_probe_time: float = 0.0
        self._loaded = False

    def get_probe(self, analysis=None) -> MicroProbe | None:
        """Get the next probe to ask, or None if cooldown active or all asked.

        Args:
            analysis: ProfileAnalysis from logos.interview.analyze_profile().
                      Used to prioritize probes for gap dimensions.
        """
        if not self._loaded:
            self.load_state()

        # Cooldown check (wall-clock time for persistence across restarts)
        if time.time() - self._last_probe_time < _probe_cooldown():
            return None

        # Filter out already-asked probes
        available = [p for p in _PROBE_POOL if p.topic not in self._asked]
        if not available:
            return None

        # Prioritize based on gaps
        if analysis is not None and analysis.neurocognitive_gap:
            # Neurocognitive gaps exist — prioritize neurocognitive probes
            neuro = [p for p in available if p.dimension == "neurocognitive_profile"]
            if neuro:
                return max(neuro, key=lambda p: p.priority)

        # Return highest priority available probe
        return max(available, key=lambda p: p.priority)

    def mark_asked(self, topic: str) -> None:
        """Mark a probe topic as asked."""
        self._asked.add(topic)
        self._last_probe_time = time.time()
        self.save_state()

    def save_state(self) -> None:
        """Persist probe state to disk (atomic write)."""
        import tempfile

        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "asked_topics": sorted(self._asked),
            "last_probe_time": self._last_probe_time,
        }
        content = json.dumps(data, indent=2)
        tmp_fd, tmp_path = tempfile.mkstemp(dir=_STATE_PATH.parent, suffix=".json")
        try:
            with open(tmp_fd, "w", encoding="utf-8") as f:
                f.write(content)
            Path(tmp_path).replace(_STATE_PATH)
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise

    def load_state(self) -> None:
        """Load probe state from disk."""
        self._loaded = True
        if not _STATE_PATH.exists():
            return
        try:
            data = json.loads(_STATE_PATH.read_text())
            self._asked = set(data.get("asked_topics", []))
            self._last_probe_time = data.get("last_probe_time", 0.0)
        except (json.JSONDecodeError, KeyError):
            pass
