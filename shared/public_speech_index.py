"""Public Speech Event Witness Index.

Materializes an append-only public speech event index keyed by speech_event_id.
Private conversation uses this index to safely resolve temporal-deictic references
without cross-contaminating private memory.

Invariants:
- Public route/playback without egress witness is not public-audible truth.
- Private playback cannot enter as public_broadcast.
- The overwrite-only voice-output-witness.json is a source, not the durable index.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

INDEX_PATH = Path("/dev/shm/hapax-daimonion/public-speech-events.jsonl")

PublicSpeechScope = Literal["public_broadcast", "private_only", "blocked", "failed"]


class PublicSpeechIndexError(ValueError):
    """Raised when a record violates public speech index invariants."""


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

    @model_validator(mode="after")
    def _validate_public_broadcast_has_egress(self) -> PublicSpeechEventRecord:
        if self.scope == "public_broadcast" and not self.egress_refs:
            raise PublicSpeechIndexError(
                f"speech_event_id={self.speech_event_id}: public_broadcast scope "
                f"requires at least one egress_ref (no egress = not public-audible truth)"
            )
        return self

    @model_validator(mode="after")
    def _validate_private_not_public(self) -> PublicSpeechEventRecord:
        if self.scope == "public_broadcast":
            rd = self.route_decision
            if rd.get("route") == "private" or rd.get("destination") == "private":
                raise PublicSpeechIndexError(
                    f"speech_event_id={self.speech_event_id}: private route decision "
                    f"cannot have public_broadcast scope"
                )
        return self


def compute_utterance_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def append_public_speech_event(record: PublicSpeechEventRecord, path: Path = INDEX_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = record.model_dump_json() + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)


def read_public_speech_events(
    path: Path = INDEX_PATH,
    scope: PublicSpeechScope | None = None,
) -> list[PublicSpeechEventRecord]:
    if not path.exists():
        return []
    records: list[PublicSpeechEventRecord] = []
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        record = PublicSpeechEventRecord.model_validate(data)
        if scope is None or record.scope == scope:
            records.append(record)
    return records


def lookup_speech_event(
    speech_event_id: str,
    path: Path = INDEX_PATH,
) -> PublicSpeechEventRecord | None:
    for record in read_public_speech_events(path):
        if record.speech_event_id == speech_event_id:
            return record
    return None


def recent_public_speech(
    n: int = 5,
    path: Path = INDEX_PATH,
) -> list[PublicSpeechEventRecord]:
    return read_public_speech_events(path, scope="public_broadcast")[-n:]
