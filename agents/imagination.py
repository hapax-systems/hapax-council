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
