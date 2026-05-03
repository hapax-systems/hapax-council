"""M8 song-queue control — load M8 projects programmatically by symbolic name.

cc-task ``m8-song-queue-control``. Layers on top of
``m8-remote-button-control-daemon`` (Gap 4) to navigate the M8's
LOAD PROJECT view by symbolic project name. Drives a YAML-pinned
mapping ``{project_name: button_sequence}`` so the director or
content-programme decision logic can request "queue M8 project
``mood_drift_03``" and the M8's own queued-song-loading mechanism
swaps the project at end of current chain.

Brittleness: the M8's file browser sorts FAT32 entries alphabetically
and the host can't read the SD card live. The YAML must be regenerated
(via ``scripts/m8-rescan-projects.py``) whenever the SD card layout
changes. Stale YAML manifests as a wrong-project queue or
"button-sequence ran but no project loaded" — the dispatcher logs
this, but cannot detect it from the daemon side.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from agents.m8_control.client import M8ControlClient

log = logging.getLogger("m8_control.song_queue")

DEFAULT_INDEX_PATH = Path("config/m8/project_index.yaml")


class M8ProjectEntry(BaseModel):
    """One project entry in the M8 SD-card index."""

    name: str = Field(..., min_length=1)
    button_sequence: list[str] = Field(default_factory=list)
    duration_estimate_s: int | None = Field(default=None, ge=0)
    tempo_bpm: float | None = Field(default=None, gt=0)
    tonal_tags: list[str] = Field(default_factory=list)


class M8ProjectIndex(BaseModel):
    """Top-level YAML schema."""

    projects: list[M8ProjectEntry] = Field(default_factory=list)


def load_project_index(path: Path = DEFAULT_INDEX_PATH) -> M8ProjectIndex:
    """Read the YAML index and validate via Pydantic.

    Raises ``FileNotFoundError`` on missing path, ``ValidationError`` on
    schema mismatch, and ``yaml.YAMLError`` on parse failure. Callers
    that prefer a soft-fail surface should catch all three.
    """
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    return M8ProjectIndex.model_validate(data)


class M8SongQueueError(RuntimeError):
    """Raised when a song-queue dispatch can't be completed."""


class M8SongQueue:
    """Resolve project name → button sequence → daemon dispatch.

    Each ``queue(project_name)`` call:
      1. Looks up the entry by exact name match (case-sensitive).
      2. Validates the button_sequence is non-empty.
      3. Dispatches each button as a separate request through
         ``M8ControlClient.button(name, hold_ms=DEFAULT_HOLD)`` so the
         M8 sees discrete press-then-release frames per step.
      4. Returns a structured report dict.

    Raises ``M8SongQueueError`` on unknown project, empty sequence, or
    daemon error. Caller decides whether to log + skip or escalate.
    """

    def __init__(
        self,
        index: M8ProjectIndex,
        client: M8ControlClient | None = None,
        *,
        hold_ms: int = 80,
    ) -> None:
        self._index = index
        self._client = client or M8ControlClient()
        self._hold_ms = hold_ms
        # Pre-build name → entry map for O(1) lookup. Case-sensitive
        # because M8 file-browser names are case-sensitive on FAT32.
        self._by_name: dict[str, M8ProjectEntry] = {p.name: p for p in index.projects}

    def queue(self, project_name: str) -> dict:
        """Dispatch the button-sequence for `project_name`.

        Returns ``{"ok": True, "project": ..., "steps": N}`` on success.
        Raises `M8SongQueueError` on unknown project or empty sequence.
        Re-raises daemon errors (typed as `M8SongQueueError` for
        upstream uniformity) when the daemon ACK reports `ok: False`.
        """
        entry = self._by_name.get(project_name)
        if entry is None:
            raise M8SongQueueError(
                f"unknown project: {project_name!r}; known: {sorted(self._by_name)}"
            )
        if not entry.button_sequence:
            raise M8SongQueueError(f"project {project_name!r} has empty button_sequence")
        for step_idx, button_name in enumerate(entry.button_sequence):
            ack = self._client.button(button_name, hold_ms=self._hold_ms)
            if not ack.get("ok"):
                raise M8SongQueueError(
                    f"daemon error at step {step_idx} ({button_name!r}): "
                    f"{ack.get('error', 'unknown')}"
                )
        return {"ok": True, "project": project_name, "steps": len(entry.button_sequence)}

    @classmethod
    def from_yaml(
        cls,
        path: Path = DEFAULT_INDEX_PATH,
        client: M8ControlClient | None = None,
        *,
        hold_ms: int = 80,
    ) -> M8SongQueue:
        """Convenience: load index from YAML + construct."""
        index = load_project_index(path)
        return cls(index, client=client, hold_ms=hold_ms)
