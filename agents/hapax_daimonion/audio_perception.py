"""agents/hapax_daimonion/audio_perception.py"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

IMPINGEMENT_BUS = Path("/dev/shm/hapax-dmn/impingements.jsonl")
OPERATOR_SPEAKER_THRESHOLD = 0.60


class AudioPerceptionBackend:
    def __init__(self, stt: Any = None, speaker_id: Any = None) -> None:
        self._stt = stt
        self._speaker_id = speaker_id
        self._pending_impingements: deque[dict] = deque(maxlen=32)
        self._active = False

    @property
    def name(self) -> str:
        return "audio"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"speech_detected", "audio_event", "vad_confidence"})

    @property
    def tier(self) -> str:
        return "FAST"

    def available(self) -> bool:
        return self._stt is not None and self._stt.is_loaded

    def start(self) -> None:
        self._active = True
        log.info("AudioPerceptionBackend started")

    def stop(self) -> None:
        self._active = False

    def contribute(self, behaviors: dict) -> None:
        pass

    def _emit_speech_impingement(
        self,
        transcript: str,
        speaker: str,
        speaker_confidence: float,
        vad_confidence: float,
        duration_s: float,
        energy_db: float,
        utterance_ref: str | None = None,
    ) -> None:
        is_operator = speaker == "operator" and speaker_confidence >= OPERATOR_SPEAKER_THRESHOLD
        strength = vad_confidence * speaker_confidence if is_operator else vad_confidence * 0.3

        imp = {
            "id": str(uuid.uuid4()),
            "timestamp": time.time(),
            "source": "audio.operator_speech" if is_operator else "audio.scene",
            "type": "PATTERN_MATCH" if is_operator else "STATISTICAL_DEVIATION",
            "strength": round(min(1.0, strength), 4),
            "content": {
                "transcript": transcript,
                "audio_event": "directed_speech" if is_operator else "ambient_speech",
                "speaker": speaker,
                "speaker_confidence": round(speaker_confidence, 4),
                "energy_db": round(energy_db, 1),
                "duration_s": round(duration_s, 2),
            },
        }
        if utterance_ref:
            imp["content"]["utterance_bytes_ref"] = utterance_ref

        self._pending_impingements.append(imp)
        self._write_to_bus(imp)
        log.info(
            "Audio impingement: source=%s strength=%.2f speaker=%s transcript=%.40s",
            imp["source"],
            imp["strength"],
            speaker,
            transcript,
        )

    def _write_to_bus(self, imp: dict) -> None:
        try:
            with IMPINGEMENT_BUS.open("a") as f:
                f.write(json.dumps(imp) + "\n")
        except OSError:
            log.debug("Failed to write impingement to bus", exc_info=True)

    def drain_impingements(self) -> list[dict]:
        result = list(self._pending_impingements)
        self._pending_impingements.clear()
        return result

    async def process_utterance(
        self,
        audio_bytes: bytes,
        vad_confidence: float,
        duration_s: float,
        energy_db: float,
    ) -> None:
        if not self._active or self._stt is None:
            return

        transcript = await self._stt.transcribe(audio_bytes)
        if not transcript or not transcript.strip():
            return

        speaker = "unknown"
        speaker_confidence = 0.0
        if self._speaker_id is not None:
            try:
                speaker, speaker_confidence = self._speaker_id.identify(audio_bytes)
            except Exception:
                log.debug("Speaker ID failed", exc_info=True)

        self._emit_speech_impingement(
            transcript=transcript,
            speaker=speaker,
            speaker_confidence=speaker_confidence,
            vad_confidence=vad_confidence,
            duration_s=duration_s,
            energy_db=energy_db,
        )
