"""Imagination bus — fragment publishing and escalation to impingement cascade.

Produces ImaginationFragments: medium-agnostic creative signals with
content references, expressive dimensions, and salience scoring.
High-salience fragments escalate into Impingements for capability recruitment.
"""

from __future__ import annotations

import logging
import math
import random
import time as time_mod
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from agents._impingement import Impingement, ImpingementType

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SHM_DIR = Path("/dev/shm/hapax-imagination")
CURRENT_PATH = SHM_DIR / "current.json"
STREAM_PATH = SHM_DIR / "stream.jsonl"
STREAM_MAX_LINES = 50

VISUAL_OBSERVATION_PATH = Path("/dev/shm/hapax-dmn/visual-observation.txt")
REVERBERATION_THRESHOLD = 0.5


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
    material: Literal["water", "fire", "earth", "air", "void"] = "water"
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

    # Cap stream at max_lines (atomic: write to tmp, then rename)
    lines = stream_path.read_text().splitlines()
    if len(lines) > max_lines:
        tmp_cap = stream_path.with_suffix(".cap.tmp")
        tmp_cap.write_text("\n".join(lines[-max_lines:]) + "\n")
        tmp_cap.rename(stream_path)


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

    def force_accelerated(self, enabled: bool) -> None:
        """Force acceleration state externally (e.g. reverberation boost)."""
        self._accelerated = enabled

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
        stance = stimmung.get("overall_stance", "unknown")
        stress_d = stimmung.get("operator_stress", {})
        stress = stress_d.get("value", "unknown") if isinstance(stress_d, dict) else "unknown"
        sections.append(f"- Stimmung: stance={stance}, stress={stress}")
    perception = sensor_snapshot.get("perception", {})
    if perception:
        activity = perception.get("activity", "unknown")
        flow = perception.get("flow_score", "unknown")
        sections.append(f"- Perception: activity={activity}, flow={flow}")
    watch = sensor_snapshot.get("watch", {})
    if watch:
        hr = watch.get("heart_rate", "unknown")
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
    """Probabilistic escalation — sigmoid around 0.55, boosted by continuation."""
    midpoint = 0.55
    steepness = 8.0
    probability = 1.0 / (1.0 + math.exp(-steepness * (fragment.salience - midpoint)))

    if fragment.continuation:
        probability = min(1.0, probability * 1.3)

    if random.random() > probability:
        return None

    return Impingement(
        id=fragment.id,
        timestamp=fragment.timestamp,
        source="imagination",
        type=ImpingementType.SALIENCE_INTEGRATION,
        strength=fragment.salience,
        content={
            "narrative": fragment.narrative,
            "content_references": [ref.model_dump() for ref in fragment.content_references],
            "continuation": fragment.continuation,
            "material": fragment.material,
            "dimensions": fragment.dimensions,
        },
        context={},
    )


# ---------------------------------------------------------------------------
# Reverberation
# ---------------------------------------------------------------------------


def reverberation_check(narrative: str, perceived_description: str) -> float:
    """Measure reverberation: how much the visual output surprised the imagination.

    High reverberation (close to 1.0) means the rendered result differs
    significantly from what was imagined — the system surprises itself.
    Low reverberation means the output matched prediction.

    Uses inverted word-overlap similarity: shared words = low reverberation.
    """
    if not narrative or not perceived_description:
        return 0.0

    narrative_words = set(narrative.lower().split())
    perceived_words = set(perceived_description.lower().split())

    if not narrative_words or not perceived_words:
        return 0.0

    intersection = narrative_words & perceived_words
    union = narrative_words | perceived_words

    if not union:
        return 0.0

    similarity = len(intersection) / len(union)  # Jaccard similarity
    return 1.0 - similarity
