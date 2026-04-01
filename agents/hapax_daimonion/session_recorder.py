"""Session recorder — captures both sides of every voice conversation.

Records per-session:
  - Raw operator audio (WAV, before STT)
  - STT transcript (what Hapax heard)
  - LLM response text (what Hapax said)
  - TTS audio (what Hapax spoke, if captured)

Review: uv run python -m agents.hapax_daimonion.session_recorder [session_dir]
"""

from __future__ import annotations

import json
import logging
import time
import wave
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.hapax_daimonion.conversation_pipeline import ConversationPipeline

log = logging.getLogger("session_recorder")

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2

RECORDINGS_DIR = Path.home() / ".local" / "share" / "hapax-daimonion" / "recordings"


class SessionRecorder:
    """Records both sides of a voice conversation."""

    def __init__(self, session_id: str) -> None:
        self._session_dir = RECORDINGS_DIR / session_id
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._turn = 0
        self._manifest: list[dict] = []
        self._pending_audio: bytes | None = None
        log.info("Session recorder: %s", self._session_dir)

    def record_operator_audio(self, audio_bytes: bytes) -> None:
        """Stash raw operator audio — transcript comes after STT."""
        self._pending_audio = audio_bytes

    def capture_pipeline_results(self, pipeline: ConversationPipeline) -> None:
        """Capture transcript + response after pipeline processes an utterance."""
        transcript = getattr(pipeline, "_last_transcript", "") or ""
        if not transcript and not self._pending_audio:
            return

        self._turn += 1

        # Save operator audio + transcript
        if self._pending_audio:
            wav_path = self._session_dir / f"{self._turn:03d}_operator.wav"
            _write_wav(wav_path, self._pending_audio)
            duration = len(self._pending_audio) / (SAMPLE_RATE * SAMPLE_WIDTH)
        else:
            wav_path = None
            duration = 0

        txt_path = self._session_dir / f"{self._turn:03d}_operator.txt"
        txt_path.write_text(transcript, encoding="utf-8")

        self._manifest.append(
            {
                "turn": self._turn,
                "speaker": "operator",
                "audio": wav_path.name if wav_path else None,
                "transcript": transcript,
                "audio_duration_s": round(duration, 1),
                "timestamp": time.time(),
            }
        )
        self._pending_audio = None

        # Capture Hapax response from conversation thread
        thread = getattr(pipeline, "_conversation_thread", [])
        if thread:
            last = thread[-1]
            response = getattr(last, "response_summary", "") or ""
            if response:
                self._turn += 1
                txt_path = self._session_dir / f"{self._turn:03d}_hapax.txt"
                txt_path.write_text(response, encoding="utf-8")
                self._manifest.append(
                    {
                        "turn": self._turn,
                        "speaker": "hapax",
                        "audio": None,
                        "transcript": response,
                        "timestamp": time.time(),
                    }
                )

        self._write_manifest()

    def close(self) -> None:
        self._write_manifest()
        log.info("Session recorded: %d turns → %s", self._turn, self._session_dir)

    def _write_manifest(self) -> None:
        p = self._session_dir / "manifest.json"
        p.write_text(json.dumps(self._manifest, indent=2), encoding="utf-8")


def _write_wav(path: Path, pcm_bytes: bytes) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_bytes)


def review_session(session_dir: str) -> None:
    """Print formatted transcript of a recorded session."""
    path = Path(session_dir)
    manifest = path / "manifest.json"
    if not manifest.exists():
        print(f"No manifest in {path}")
        return

    entries = json.loads(manifest.read_text())
    print(f"\n{'=' * 60}")
    print(f"Session: {path.name}")
    print(f"Turns: {len(entries)}")
    print(f"{'=' * 60}\n")

    for e in entries:
        speaker = e["speaker"].upper()
        text = e["transcript"]
        dur = e.get("audio_duration_s", "")
        audio = e.get("audio", "")

        if speaker == "OPERATOR":
            d = f" ({dur}s)" if dur else ""
            print(f"  YOU{d}: {text}")
            if audio:
                print(f"       [audio: {path / audio}]")
        else:
            print(f"  HAPAX: {text}")
        print()


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        if RECORDINGS_DIR.exists():
            sessions = sorted(
                RECORDINGS_DIR.iterdir(),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if sessions:
                print("Recent sessions:")
                for s in sessions[:10]:
                    m = s / "manifest.json"
                    turns = len(json.loads(m.read_text())) if m.exists() else 0
                    print(f"  {s.name} ({turns} turns)")
                print("\nReview: uv run python -m agents.hapax_daimonion.session_recorder <path>")
            else:
                print("No sessions recorded yet.")
        else:
            print("No recordings directory.")
    else:
        review_session(sys.argv[1])
