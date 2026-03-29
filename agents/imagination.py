"""Imagination bus — fragment publishing and escalation to impingement cascade.

Produces ImaginationFragments: medium-agnostic creative signals with
content references, expressive dimensions, and salience scoring.
High-salience fragments escalate into Impingements for capability recruitment.
"""

from __future__ import annotations

import logging
import time as time_mod
import uuid
from pathlib import Path

from pydantic import BaseModel, Field

from shared.impingement import Impingement, ImpingementType

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SHM_DIR = Path("/dev/shm/hapax-imagination")
CURRENT_PATH = SHM_DIR / "current.json"
STREAM_PATH = SHM_DIR / "stream.jsonl"
STREAM_MAX_LINES = 50
ESCALATION_THRESHOLD = 0.6


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class ContentReference(BaseModel, frozen=True):
    """A reference to source material feeding an imagination fragment."""

    kind: str  # "qdrant_query", "camera_frame", "text", "url", "file", "audio_clip"
    source: str
    query: str | None = None
    salience: float = Field(ge=0.0, le=1.0)


class ImaginationFragment(BaseModel, frozen=True):
    """A single imagination output — medium-agnostic creative signal."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = Field(default_factory=time_mod.time)
    content_references: list[ContentReference]
    dimensions: dict[str, float]  # 9 expressive dimensions, medium-agnostic
    salience: float = Field(ge=0.0, le=1.0)
    continuation: bool
    narrative: str
    parent_id: str | None = None


# ---------------------------------------------------------------------------
# SHM publisher
# ---------------------------------------------------------------------------


def publish_fragment(
    fragment: ImaginationFragment,
    current_path: Path | None = None,
    stream_path: Path | None = None,
    max_lines: int = STREAM_MAX_LINES,
) -> None:
    """Publish a fragment to shared memory (atomic write + append stream)."""
    if current_path is None:
        current_path = CURRENT_PATH
    if stream_path is None:
        stream_path = STREAM_PATH

    current_path = Path(current_path)
    stream_path = Path(stream_path)

    # Ensure directories exist
    current_path.parent.mkdir(parents=True, exist_ok=True)
    stream_path.parent.mkdir(parents=True, exist_ok=True)

    payload = fragment.model_dump_json()

    # Atomic write to current.json via tmp+rename
    tmp_path = current_path.with_suffix(".tmp")
    tmp_path.write_text(payload)
    tmp_path.rename(current_path)

    # Append to stream.jsonl
    with stream_path.open("a") as f:
        f.write(payload + "\n")

    # Cap stream at max_lines
    lines = stream_path.read_text().splitlines()
    if len(lines) > max_lines:
        stream_path.write_text("\n".join(lines[-max_lines:]) + "\n")


# ---------------------------------------------------------------------------
# Cadence controller
# ---------------------------------------------------------------------------


class CadenceController:
    """Governs the pacing of imagination ticks based on salience and TPN state."""

    def __init__(
        self,
        base_s: float = 12.0,
        accelerated_s: float = 4.0,
        salience_threshold: float = 0.3,
        decel_count: int = 3,
    ):
        self._base_s = base_s
        self._accelerated_s = accelerated_s
        self._salience_threshold = salience_threshold
        self._decel_count = decel_count
        self._accelerated = False
        self._non_continuation_streak = 0
        self._tpn_active = False

    def update(self, fragment: ImaginationFragment) -> None:
        """Update cadence state based on the latest fragment."""
        if fragment.continuation and fragment.salience > self._salience_threshold:
            self._accelerated = True
            self._non_continuation_streak = 0
        elif not fragment.continuation:
            self._non_continuation_streak += 1
            if self._non_continuation_streak >= self._decel_count:
                self._accelerated = False
        else:
            self._non_continuation_streak = 0

    def current_interval(self) -> float:
        """Return the current tick interval in seconds."""
        interval = self._accelerated_s if self._accelerated else self._base_s
        if self._tpn_active:
            interval *= 2.0
        return interval

    def set_tpn_active(self, active: bool) -> None:
        """Set task-positive network active state."""
        self._tpn_active = active


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------


def assemble_context(
    observations: list[str],
    recent_fragments: list[ImaginationFragment],
    sensor_snapshot: dict,
) -> str:
    """Build a prompt string from observations, sensor state, and recent fragments."""
    sections: list[str] = []

    # Observations (last 5)
    sections.append("## Current Observations (from DMN)")
    if observations:
        for obs in observations[-5:]:
            sections.append(f"- {obs}")
    else:
        sections.append("(none)")

    # System state from sensor snapshot
    sections.append("")
    sections.append("## System State")
    stimmung = sensor_snapshot.get("stimmung", {})
    if stimmung:
        stance = stimmung.get("stance", "unknown")
        stress = stimmung.get("stress", "unknown")
        sections.append(f"- Stimmung: stance={stance}, stress={stress}")
    perception = sensor_snapshot.get("perception", {})
    if perception:
        activity = perception.get("activity", "unknown")
        flow = perception.get("flow", "unknown")
        sections.append(f"- Perception: activity={activity}, flow={flow}")
    watch = sensor_snapshot.get("watch", {})
    if watch:
        hr = watch.get("hr", "unknown")
        sections.append(f"- Watch: HR={hr}")
    weather = sensor_snapshot.get("weather", {})
    if weather:
        sections.append(f"- Weather: {weather}")
    if not any(sensor_snapshot.get(k) for k in ("stimmung", "perception", "watch", "weather")):
        sections.append("(none)")

    # Recent fragments (last 3)
    sections.append("")
    sections.append("## Recent Imagination")
    if recent_fragments:
        for frag in recent_fragments[-3:]:
            prefix = "(continuing) " if frag.continuation else ""
            sections.append(f"- {prefix}{frag.narrative}")
    else:
        sections.append("(none)")

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------


def maybe_escalate(fragment: ImaginationFragment) -> Impingement | None:
    """Escalate high-salience fragments into impingements for capability recruitment."""
    if fragment.salience < ESCALATION_THRESHOLD:
        return None

    return Impingement(
        timestamp=fragment.timestamp,
        source="imagination",
        type=ImpingementType.SALIENCE_INTEGRATION,
        strength=fragment.salience,
        content={
            "narrative": fragment.narrative,
            "content_references": [ref.model_dump() for ref in fragment.content_references],
            "continuation": fragment.continuation,
        },
        context={
            "dimensions": fragment.dimensions,
        },
        parent_id=fragment.parent_id,
    )


# ---------------------------------------------------------------------------
# Imagination loop
# ---------------------------------------------------------------------------

IMAGINATION_SYSTEM_PROMPT = """\
You are the imagination process of a personal computing system. You observe
the system's current state and produce spontaneous associations, memories,
projections, and novel connections — the way a human mind wanders during
idle moments.

Your output is a structured fragment describing what you're currently
"imagining." This is not evaluation or analysis — it is free association
grounded in what you observe.

Content sources you can reference:
- camera_frame: overhead, hero, left, right (live camera feeds)
- qdrant_query: profile-facts, documents, operator-episodes, studio-moments (vector knowledge)
- text: any text you want to display
- url: any image URL
- file: any file path

Produce one ImaginationFragment. Be specific in content_references —
point to real things. Set dimensional coloring to match the emotional
tone of what you're imagining. Assess salience honestly — most fragments
are low salience (0.1-0.3). Only mark high salience (>0.6) for genuine
insights or concerns worth escalating.

If your previous fragment had continuation=true, you may continue that
train of thought or let it go. Don't force continuation.\
"""

MAX_RECENT_FRAGMENTS = 5


class ImaginationLoop:
    """Main loop that drives imagination ticks via an LLM agent."""

    def __init__(
        self,
        current_path: Path | None = None,
        stream_path: Path | None = None,
    ):
        self.cadence = CadenceController()
        self.recent_fragments: list[ImaginationFragment] = []
        self._pending_impingements: list[Impingement] = []
        self._current_path = current_path or CURRENT_PATH
        self._stream_path = stream_path or STREAM_PATH
        self._agent = None  # lazy-init

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

            from shared.config import get_model

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

    async def tick(
        self, observations: list[str], sensor_snapshot: dict
    ) -> ImaginationFragment | None:
        """Run one imagination tick: assemble context, call agent, process result."""
        context = assemble_context(observations, self.recent_fragments, sensor_snapshot)
        try:
            agent = self._get_agent()
            result = await agent.run(context)
            fragment = result.output
            self._process_fragment(fragment)
            return fragment
        except Exception:
            log.warning("Imagination tick failed", exc_info=True)
            return None
