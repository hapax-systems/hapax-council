"""Caption JSONL writer (ytb-009 Phase 2).

Counterpart to ``CaptionReader``: appends one event per line to the
shared captions JSONL stream. Designed to be called from the
daimonion's STT pipeline as soon as a transcribed utterance lands —
the writer carries no model dependencies, just the shape contract.

The shape mirrors what ``CaptionReader`` parses (see ``reader.py``).
A separate writer class — rather than letting the daimonion craft the
JSONL by hand — makes the contract revisable in one place when the
diarization or per-source-routing follow-ups land.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_CAPTIONS_PATH = Path(
    os.environ.get(
        "HAPAX_CAPTIONS_PATH",
        "/dev/shm/hapax-captions/live.jsonl",
    )
)


class CaptionWriter:
    """Atomically append timestamped captions to the shared JSONL stream.

    Constructor parameters
    ----------------------
    captions_path:
        Output JSONL path. Defaults to
        ``/dev/shm/hapax-captions/live.jsonl``. Parent directory is
        ``mkdir -p``'ed on first write.

    Thread-safety
    -------------
    Multiple daimonion threads may emit captions concurrently (STT
    callback + tool-narration); writes are serialised behind an
    instance-level lock and use append-mode opens with line buffering
    so each line lands atomically on POSIX.
    """

    def __init__(self, *, captions_path: Path = DEFAULT_CAPTIONS_PATH) -> None:
        self._captions_path = captions_path
        self._lock = threading.Lock()

    def emit(
        self,
        *,
        ts: float,
        text: str,
        duration_ms: int = 0,
        speaker: str | None = None,
    ) -> None:
        """Append one caption event.

        Failures (no /dev/shm, permission denied, parent missing on a
        host without tmpfs) log without raising — captions are
        best-effort observability for the live broadcast and a
        broken writer must not propagate into the STT callback.

        Empty ``text`` is silently dropped: an empty caption has no
        consumer and just bloats the cursor by a no-op line.
        """
        if not text:
            return
        record: dict[str, object] = {
            "ts": ts,
            "text": text,
            "duration_ms": int(duration_ms),
        }
        if speaker:
            record["speaker"] = speaker
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self._lock:
            try:
                self._captions_path.parent.mkdir(parents=True, exist_ok=True)
                with self._captions_path.open("a", encoding="utf-8") as fh:
                    fh.write(line)
            except OSError:
                log.warning("captions write failed at %s", self._captions_path, exc_info=True)


__all__ = ["CaptionWriter"]
