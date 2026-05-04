"""Public Speech Event Witness Index.

Materializes an append-only public speech event index keyed by speech_event_id.
Private conversation uses this index to safely resolve temporal-deictic references
without cross-contaminating private memory.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

INDEX_PATH = Path("/dev/shm/hapax-daimonion/public-speech-events.jsonl")

PublicSpeechScope = Literal["public_broadcast", "private_only", "blocked", "failed"]


class PublicSpeechEventRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    speech_event_id: str
    impulse_id: str | None
    triad_ids: list[str]
    utterance_hash: str
    route_decision: dict[str, Any]
    tts_result: dict[str, Any] | None
    playback_result: dict[str, Any] | None
    audio_safety_refs: list[str]
    egress_refs: list[str]
    wcs_snapshot_refs: list[str]
    chronicle_refs: list[str]
    temporal_span_refs: list[str]
    scope: PublicSpeechScope
    created_at: str


def compute_utterance_hash(text: str) -> str:
    """Compute SHA-256 hash of the composed text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def append_public_speech_event(record: PublicSpeechEventRecord, path: Path = INDEX_PATH) -> None:
    """Append a public speech event record to the JSONL index."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = record.model_dump_json() + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
