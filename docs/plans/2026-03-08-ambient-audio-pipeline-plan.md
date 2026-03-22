# Ambient Audio Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a 24/7 ambient audio capture and processing pipeline — continuous recording from Blue Yeti, intelligent segmentation/classification/diarization/transcription, RAG ingestion, and Google Drive archival.

**Architecture:** Four independent components: (1) always-on ffmpeg recorder as systemd service, (2) Python audio_processor agent following established sync agent pattern, (3) rclone-based archiver as systemd timer, (4) integration with ingest/profiler/briefing. The recorder uses PipeWire's PulseAudio compat layer (`-f pulse`) so it never locks the mic — concurrent usage (voice chat, LLM voice interface) works in parallel.

**Tech Stack:** ffmpeg (recording), faster-whisper (transcription), silero-vad (VAD), pyannote.audio (diarization), panns_inference (classification), torchaudio (resampling), rclone (archival), systemd (orchestration)

**Design doc:** `docs/plans/2026-03-08-ambient-audio-pipeline-design.md` (in distro-work repo)

---

## Task 1: Audio Recorder systemd Service

**Files:**
- Create: `~/.config/systemd/user/audio-recorder.service`

**Step 1: Create the service file**

```ini
[Unit]
Description=Continuous audio recording (Blue Yeti)
After=pipewire.service pipewire-pulse.service
Requires=pipewire-pulse.service

[Service]
Type=simple
ExecStartPre=/usr/bin/mkdir -p %h/audio-recording/raw
ExecStart=/usr/bin/ffmpeg -nostdin -f pulse \
  -i alsa_input.usb-Blue_Microphones_Yeti_Stereo_Microphone_REV8-00.analog-stereo \
  -ac 1 -f segment -segment_time 900 -strftime 1 -c:a flac \
  %h/audio-recording/raw/rec-%%Y%%m%%d-%%H%%M%%S.flac
Restart=always
RestartSec=10
StartLimitBurst=10
StartLimitIntervalSec=300
StandardOutput=journal
StandardError=journal
SyslogIdentifier=audio-recorder

[Install]
WantedBy=default.target
```

**Step 2: Reload and verify**

```bash
systemctl --user daemon-reload
systemctl --user cat audio-recorder.service
```

Expected: service file displayed correctly.

**Step 3: Start and verify recording**

```bash
systemctl --user start audio-recorder.service
sleep 5
systemctl --user status audio-recorder.service
ls -la ~/audio-recording/raw/
```

Expected: service active, one FLAC file growing in the raw directory.

**Step 4: Verify concurrent mic access works**

```bash
# While recorder is running, test that another app can use the mic
pw-record --target alsa_input.usb-Blue_Microphones_Yeti_Stereo_Microphone_REV8-00.analog-stereo /tmp/test-concurrent.wav &
PW_PID=$!
sleep 3
kill $PW_PID
ls -la /tmp/test-concurrent.wav
rm /tmp/test-concurrent.wav
```

Expected: Both the recorder and pw-record captured audio simultaneously without error.

**Step 5: Enable on boot**

```bash
systemctl --user enable audio-recorder.service
```

**Step 6: Commit (no git repo for systemd files — just verify)**

Verify the service is running and producing files. Wait for one full 15-minute segment to complete to confirm rotation works.

---

## Task 2: Audio Processor — Skeleton + Schemas + Tests

**Files:**
- Create: `~/projects/ai-agents/agents/audio_processor.py`
- Create: `~/projects/ai-agents/tests/test_audio_processor.py`

**Step 1: Write failing tests**

Create `~/projects/ai-agents/tests/test_audio_processor.py`:

```python
"""Tests for audio_processor — schemas, segmentation helpers, RAG formatting."""
from __future__ import annotations


def test_audio_segment_defaults():
    from agents.audio_processor import AudioSegment
    seg = AudioSegment(
        source_file="rec-20260308-143000.flac",
        start_seconds=30.0,
        end_seconds=75.0,
        classification="speech",
        confidence=0.94,
    )
    assert seg.duration_seconds == 45.0
    assert seg.classification == "speech"
    assert seg.speakers == []
    assert seg.sub_classifications == []


def test_processor_state_empty():
    from agents.audio_processor import AudioProcessorState
    s = AudioProcessorState()
    assert s.processed_files == {}
    assert s.last_run == 0.0


def test_format_timestamp():
    from agents.audio_processor import _format_timestamp
    assert _format_timestamp(0.0) == "00:00:00"
    assert _format_timestamp(65.5) == "00:01:05"
    assert _format_timestamp(3661.0) == "01:01:01"


def test_format_transcript_markdown():
    from agents.audio_processor import AudioSegment, _format_transcript_markdown
    seg = AudioSegment(
        source_file="rec-20260308-143000.flac",
        start_seconds=330.0,
        end_seconds=375.0,
        classification="speech",
        confidence=0.94,
        speakers=["SPEAKER_00", "SPEAKER_01"],
        speaker_count=2,
        transcript="Hello world",
    )
    md = _format_transcript_markdown(seg, "2026-03-08T14:30:00")
    assert "source_service: ambient-audio" in md
    assert "content_type: audio_transcript" in md
    assert "speaker_count: 2" in md
    assert "Hello world" in md
    assert "00:05:30" in md  # 330 seconds


def test_format_event_markdown():
    from agents.audio_processor import AudioSegment, _format_event_markdown
    seg = AudioSegment(
        source_file="rec-20260308-150000.flac",
        start_seconds=130.0,
        end_seconds=310.0,
        classification="music",
        sub_classifications=["singing", "acoustic_guitar"],
        confidence=0.87,
        energy_db=-18.4,
    )
    md = _format_event_markdown(seg, "2026-03-08T15:00:00")
    assert "source_service: ambient-audio" in md
    assert "content_type: audio_event" in md
    assert "classification: music" in md
    assert "singing" in md
    assert "acoustic_guitar" in md
    assert "-18.4" in md


def test_generate_profile_facts():
    from agents.audio_processor import AudioProcessorState, ProcessedFileInfo, _generate_profile_facts
    state = AudioProcessorState()
    state.processed_files["f1"] = ProcessedFileInfo(
        filename="rec-20260308-143000.flac",
        processed_at=1741400000.0,
        speech_seconds=1200.0,
        music_seconds=300.0,
        silence_seconds=6000.0,
        segment_count=15,
        speaker_count=2,
    )
    facts = _generate_profile_facts(state)
    assert len(facts) >= 1
    assert any(f["key"] == "audio_daily_summary" for f in facts)


def test_should_skip_segment():
    from agents.audio_processor import _should_skip_segment
    assert _should_skip_segment("silence", 0.9) is True
    assert _should_skip_segment("white_noise", 0.8) is True
    assert _should_skip_segment("air_conditioning", 0.7) is True
    assert _should_skip_segment("speech", 0.9) is False
    assert _should_skip_segment("music", 0.8) is False
    assert _should_skip_segment("singing", 0.7) is False
```

**Step 2: Run tests to verify failure**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_audio_processor.py -v
```

Expected: FAIL (module not found).

**Step 3: Create audio_processor.py skeleton**

```python
"""audio_processor.py — Ambient audio processing for RAG pipeline.

Processes raw FLAC recordings from the audio-recorder service. Runs VAD,
classification, diarization, and transcription to produce structured
RAG output. Non-speech events get metadata-only entries.

Uses PipeWire's PulseAudio compat layer for recording (never ALSA direct),
so the mic remains available for concurrent usage (voice chat, LLM voice, etc).

Usage:
    uv run python -m agents.audio_processor --process    # Process new chunks
    uv run python -m agents.audio_processor --stats      # Show processing state
    uv run python -m agents.audio_processor --reprocess FILE  # Reprocess a specific file
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

RAW_DIR = Path.home() / "audio-recording" / "raw"
PROCESSED_DIR = Path.home() / "audio-recording" / "processed"
CACHE_DIR = Path.home() / ".cache" / "audio-processor"
STATE_FILE = CACHE_DIR / "state.json"
PROFILE_FACTS_FILE = CACHE_DIR / "audio-profile-facts.jsonl"
CHANGES_LOG = CACHE_DIR / "changes.jsonl"
RAG_SOURCES = Path.home() / "documents" / "rag-sources"
AUDIO_RAG_DIR = RAG_SOURCES / "audio"

# Minimum segment duration to keep (seconds)
MIN_SEGMENT_SECONDS = 2.0

# AudioSet classes to discard (noise, silence, mechanical)
SKIP_CLASSIFICATIONS = frozenset({
    "silence", "white_noise", "static", "hum", "buzz",
    "air_conditioning", "mechanical_fan",
    "computer_keyboard", "typing", "mouse_click",
    "noise", "background_noise",
})

# AudioSet classes to keep as events (non-speech, interesting)
KEEP_EVENT_CLASSIFICATIONS = frozenset({
    "music", "singing", "musical_instrument", "guitar", "piano",
    "drum", "bass_guitar", "synthesizer", "electronic_music",
    "laughter", "clapping", "door", "doorbell", "telephone",
    "alarm", "speech", "conversation",
})

# VRAM threshold — skip GPU processing if less than this available (MB)
MIN_VRAM_FREE_MB = 6000


# ── Schemas ──────────────────────────────────────────────────────────────────

class AudioSegment(BaseModel):
    """A classified segment of audio."""
    source_file: str
    start_seconds: float
    end_seconds: float
    classification: str
    confidence: float = 0.0
    sub_classifications: list[str] = Field(default_factory=list)
    speakers: list[str] = Field(default_factory=list)
    speaker_count: int = 0
    transcript: str = ""
    energy_db: float = 0.0

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


class ProcessedFileInfo(BaseModel):
    """State for a single processed raw file."""
    filename: str
    processed_at: float = 0.0
    speech_seconds: float = 0.0
    music_seconds: float = 0.0
    silence_seconds: float = 0.0
    segment_count: int = 0
    speaker_count: int = 0
    error: str = ""


class AudioProcessorState(BaseModel):
    """Persistent processing state."""
    processed_files: dict[str, ProcessedFileInfo] = Field(default_factory=dict)
    last_run: float = 0.0
    stats: dict[str, float] = Field(default_factory=dict)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _format_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _should_skip_segment(classification: str, confidence: float) -> bool:
    """Return True if this segment should be discarded."""
    return classification.lower() in SKIP_CLASSIFICATIONS


def _load_state() -> AudioProcessorState:
    """Load processing state from disk."""
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return AudioProcessorState(**data)
        except (json.JSONDecodeError, Exception) as exc:
            log.warning("Failed to load state: %s", exc)
    return AudioProcessorState()


def _save_state(state: AudioProcessorState) -> None:
    """Persist processing state to disk."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        state.model_dump_json(indent=2),
        encoding="utf-8",
    )


def _log_change(change_type: str, detail: str, extra: dict | None = None) -> None:
    """Append a change entry to the behavioral log."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": change_type,
        "detail": detail,
    }
    if extra:
        entry.update(extra)
    with open(CHANGES_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    log.debug("Logged change: %s — %s", change_type, detail)


def _extract_timestamp_from_filename(filename: str) -> str:
    """Extract ISO timestamp from rec-YYYYMMDD-HHMMSS.flac filename."""
    # rec-20260308-143000.flac → 2026-03-08T14:30:00
    try:
        parts = filename.replace("rec-", "").replace(".flac", "")
        date_part, time_part = parts.split("-")
        return (
            f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
            f"T{time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}"
        )
    except (ValueError, IndexError):
        return datetime.now(timezone.utc).isoformat()[:19]


# ── RAG Output Formatting ────────────────────────────────────────────────────

def _format_transcript_markdown(seg: AudioSegment, base_timestamp: str) -> str:
    """Format a speech segment as markdown with YAML frontmatter."""
    speakers_yaml = "[" + ", ".join(seg.speakers) + "]" if seg.speakers else "[]"
    start_ts = _format_timestamp(seg.start_seconds)
    end_ts = _format_timestamp(seg.end_seconds)
    duration = int(seg.duration_seconds)

    speaker_label = f"{seg.speaker_count} speaker{'s' if seg.speaker_count != 1 else ''}"

    md = f"""---
source_service: ambient-audio
content_type: audio_transcript
timestamp: {base_timestamp}
duration_seconds: {duration}
speakers: {speakers_yaml}
speaker_count: {seg.speaker_count}
audio_source: {seg.source_file}
segment_start: "{start_ts}"
segment_end: "{end_ts}"
classification: {seg.classification}
confidence: {seg.confidence:.2f}
---

# Audio Transcript — {base_timestamp[:10]} {base_timestamp[11:16]} ({duration}s, {speaker_label})

{seg.transcript}
"""
    return md


def _format_event_markdown(seg: AudioSegment, base_timestamp: str) -> str:
    """Format a non-speech event as markdown with YAML frontmatter."""
    start_ts = _format_timestamp(seg.start_seconds)
    end_ts = _format_timestamp(seg.end_seconds)
    duration = int(seg.duration_seconds)
    mins = duration // 60
    secs = duration % 60
    duration_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"

    sub_class_yaml = "[" + ", ".join(seg.sub_classifications) + "]" if seg.sub_classifications else "[]"

    sub_line = ""
    if seg.sub_classifications:
        sub_line = f" ({', '.join(seg.sub_classifications)})"

    md = f"""---
source_service: ambient-audio
content_type: audio_event
timestamp: {base_timestamp}
duration_seconds: {duration}
audio_source: {seg.source_file}
segment_start: "{start_ts}"
segment_end: "{end_ts}"
classification: {seg.classification}
sub_classifications: {sub_class_yaml}
confidence: {seg.confidence:.2f}
energy_db: {seg.energy_db:.1f}
---

# Audio Event — {base_timestamp[:10]} {base_timestamp[11:16]} ({duration_str})

Type: {seg.classification}{sub_line}
Energy: {seg.energy_db:.1f} dB average
"""
    return md


# ── Profiler Integration ─────────────────────────────────────────────────────

def _generate_profile_facts(state: AudioProcessorState) -> list[dict]:
    """Generate deterministic profile facts from audio processing state."""
    facts: list[dict] = []
    source = "audio-processor:audio-profile-facts"

    if not state.processed_files:
        return facts

    total_speech = sum(f.speech_seconds for f in state.processed_files.values())
    total_music = sum(f.music_seconds for f in state.processed_files.values())
    total_silence = sum(f.silence_seconds for f in state.processed_files.values())
    total_segments = sum(f.segment_count for f in state.processed_files.values())

    speech_h = total_speech / 3600
    music_h = total_music / 3600
    silence_h = total_silence / 3600

    facts.append({
        "dimension": "activity",
        "key": "audio_daily_summary",
        "value": (
            f"{speech_h:.1f}h speech, {music_h:.1f}h music, "
            f"{silence_h:.1f}h silence across {len(state.processed_files)} recordings"
        ),
        "confidence": 0.95,
        "source": source,
        "evidence": f"Aggregated from {total_segments} segments",
    })

    # Conversation patterns
    multi_speaker = [
        f for f in state.processed_files.values() if f.speaker_count > 1
    ]
    if multi_speaker:
        facts.append({
            "dimension": "activity",
            "key": "audio_conversation_patterns",
            "value": f"{len(multi_speaker)} recordings with multiple speakers",
            "confidence": 0.90,
            "source": source,
            "evidence": f"Diarization detected multi-speaker in {len(multi_speaker)} files",
        })

    return facts


def _write_profile_facts(state: AudioProcessorState) -> None:
    """Write profile facts JSONL for profiler bridge consumption."""
    facts = _generate_profile_facts(state)
    if not facts:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROFILE_FACTS_FILE, "w", encoding="utf-8") as fh:
        for fact in facts:
            fh.write(json.dumps(fact) + "\n")
    log.info("Wrote %d profile facts to %s", len(facts), PROFILE_FACTS_FILE)


# ── Stats ────────────────────────────────────────────────────────────────────

def _print_stats(state: AudioProcessorState) -> None:
    """Print processing statistics."""
    total_speech = sum(f.speech_seconds for f in state.processed_files.values())
    total_music = sum(f.music_seconds for f in state.processed_files.values())
    total_segments = sum(f.segment_count for f in state.processed_files.values())
    errors = sum(1 for f in state.processed_files.values() if f.error)

    print("Audio Processor State")
    print("=" * 40)
    print(f"Processed files: {len(state.processed_files):,}")
    print(f"Total segments:  {total_segments:,}")
    print(f"Speech:          {total_speech / 3600:.1f}h")
    print(f"Music:           {total_music / 3600:.1f}h")
    print(f"Errors:          {errors:,}")
    print(f"Last run:        {datetime.fromtimestamp(state.last_run, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if state.last_run else 'never'}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Ambient audio processor for RAG pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--process", action="store_true", help="Process new audio chunks")
    group.add_argument("--stats", action="store_true", help="Show processing statistics")
    group.add_argument("--reprocess", type=str, metavar="FILE", help="Reprocess a specific file")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.process:
        log.info("Processing not yet implemented — skeleton only")
    elif args.reprocess:
        log.info("Reprocessing not yet implemented — skeleton only")
    elif args.stats:
        state = _load_state()
        if not state.processed_files:
            print("No processing state found. Run --process first.")
            return
        _print_stats(state)


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_audio_processor.py -v
```

Expected: All 7 tests PASS.

**Step 5: Commit**

```bash
cd ~/projects/ai-agents && git add agents/audio_processor.py tests/test_audio_processor.py
git commit -m "feat: audio_processor skeleton — schemas, helpers, RAG formatting, profiler facts"
```

---

## Task 3: Add ML Dependencies

**Files:**
- Modify: `~/projects/ai-agents/pyproject.toml`

**Step 1: Add audio processing dependencies**

Add these to the `dependencies` list in `pyproject.toml` (after the existing entries):

```python
    "faster-whisper>=1.1.0",
    "silero-vad>=5.1",
    "pyannote-audio>=3.3.0",
    "panns-inference>=0.1.1",
    "torchaudio>=2.0.0",
```

**Step 2: Sync dependencies**

```bash
cd ~/projects/ai-agents && uv sync
```

Expected: All packages install successfully. This may take a few minutes (PyTorch/torchaudio are large).

**Step 3: Verify imports work**

```bash
cd ~/projects/ai-agents && uv run python -c "
import faster_whisper; print(f'faster-whisper: {faster_whisper.__version__}')
import torch; print(f'torch: {torch.__version__}, CUDA: {torch.cuda.is_available()}')
import torchaudio; print(f'torchaudio: {torchaudio.__version__}')
"
```

Expected: All imports succeed, CUDA shows True.

Note: `pyannote.audio` requires a HuggingFace token with accepted model licenses. The token should be stored in `pass`:

```bash
pass insert huggingface/token
# Paste your HuggingFace token (from https://huggingface.co/settings/tokens)
# Must accept licenses at:
#   https://huggingface.co/pyannote/speaker-diarization-3.1
#   https://huggingface.co/pyannote/segmentation-3.0
```

**Step 4: Commit**

```bash
cd ~/projects/ai-agents && git add pyproject.toml uv.lock
git commit -m "feat: add audio processing dependencies (faster-whisper, pyannote, panns, silero-vad)"
```

---

## Task 4: VRAM Check + Audio Resampling Helpers

**Files:**
- Modify: `~/projects/ai-agents/agents/audio_processor.py`
- Modify: `~/projects/ai-agents/tests/test_audio_processor.py`

**Step 1: Write failing tests**

Add to `tests/test_audio_processor.py`:

```python
def test_check_vram_available():
    """Test VRAM check returns a boolean."""
    from agents.audio_processor import _check_vram_available
    # Should return True or False without crashing, even without GPU
    result = _check_vram_available(6000)
    assert isinstance(result, bool)


def test_find_unprocessed_files(tmp_path):
    from agents.audio_processor import AudioProcessorState, _find_unprocessed_files
    # Create some fake FLAC files
    (tmp_path / "rec-20260308-143000.flac").write_bytes(b"fake")
    (tmp_path / "rec-20260308-144500.flac").write_bytes(b"fake")
    (tmp_path / "rec-20260308-150000.flac").write_bytes(b"fake")
    (tmp_path / "not-a-recording.txt").write_bytes(b"ignore")

    state = AudioProcessorState()
    state.processed_files["rec-20260308-143000.flac"] = None  # type: ignore  # already processed

    files = _find_unprocessed_files(tmp_path, state)
    assert len(files) == 2
    assert all(f.suffix == ".flac" for f in files)
    assert all(f.name.startswith("rec-") for f in files)
```

**Step 2: Run tests to verify failure**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_audio_processor.py::test_check_vram_available tests/test_audio_processor.py::test_find_unprocessed_files -v
```

Expected: FAIL (functions not found).

**Step 3: Implement**

Add to `audio_processor.py` in the Helpers section:

```python
def _check_vram_available(min_mb: int = MIN_VRAM_FREE_MB) -> bool:
    """Check if enough GPU VRAM is available for processing."""
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            free_mb = int(result.stdout.strip().split("\n")[0])
            log.debug("GPU VRAM free: %d MB (need %d MB)", free_mb, min_mb)
            return free_mb >= min_mb
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError) as exc:
        log.debug("VRAM check failed: %s", exc)
    return False


def _find_unprocessed_files(
    raw_dir: Path, state: AudioProcessorState
) -> list[Path]:
    """Find raw FLAC files that haven't been processed yet."""
    files = sorted(
        f for f in raw_dir.glob("rec-*.flac")
        if f.name not in state.processed_files
        and f.stat().st_size > 0
    )
    return files
```

**Step 4: Run tests to verify they pass**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_audio_processor.py -v
```

Expected: All 9 tests PASS.

**Step 5: Commit**

```bash
cd ~/projects/ai-agents && git add agents/audio_processor.py tests/test_audio_processor.py
git commit -m "feat: audio_processor VRAM check and unprocessed file discovery"
```

---

## Task 5: VAD + Classification Pipeline

**Files:**
- Modify: `~/projects/ai-agents/agents/audio_processor.py`
- Modify: `~/projects/ai-agents/tests/test_audio_processor.py`

This is the core ML pipeline. Due to GPU model dependencies, the unit tests mock the ML models. Integration testing happens in Task 10.

**Step 1: Write failing tests**

Add to `tests/test_audio_processor.py`:

```python
from unittest.mock import patch, MagicMock
import numpy as np


def test_run_vad_returns_segments():
    """Test that VAD returns speech timestamp pairs."""
    from agents.audio_processor import _run_vad

    # Create 16kHz mono audio: 1 second silence + 1 second tone + 1 second silence
    sr = 16000
    silence = np.zeros(sr, dtype=np.float32)
    tone = 0.5 * np.sin(2 * np.pi * 440 * np.arange(sr) / sr).astype(np.float32)
    waveform = np.concatenate([silence, tone, silence])

    with patch("agents.audio_processor._load_vad_model") as mock_load:
        mock_model = MagicMock()
        mock_load.return_value = (mock_model, MagicMock())
        # Simulate VAD returning one speech segment
        mock_model.return_value = MagicMock()
        with patch("agents.audio_processor.silero_get_speech_timestamps",
                    return_value=[{"start": 16000, "end": 32000}]):
            segments = _run_vad(waveform, sr)
    assert len(segments) == 1
    assert segments[0] == (1.0, 2.0)  # 1s to 2s


def test_classify_segments_returns_labels():
    """Test that classification returns labeled segments."""
    from agents.audio_processor import _classify_audio_frames, AudioSegment

    # Mock PANNs inference
    with patch("agents.audio_processor._load_panns_model") as mock_load:
        mock_at = MagicMock()
        mock_load.return_value = mock_at
        # Simulate classification output: 527 classes, speech is class 0
        fake_output = np.zeros((1, 527), dtype=np.float32)
        fake_output[0, 0] = 0.95  # Speech
        mock_at.inference.return_value = (fake_output, None)

        waveform = np.zeros(16000, dtype=np.float32)
        labels = _classify_audio_frames(waveform, 16000, [(0.0, 1.0)])

    assert len(labels) == 1
    assert labels[0][2] == "Speech"  # classification label
    assert labels[0][3] >= 0.9  # confidence


def test_merge_adjacent_segments():
    """Test merging of adjacent same-type segments."""
    from agents.audio_processor import _merge_segments

    # Three speech segments close together, one music segment far away
    raw = [
        (0.0, 5.0, "speech", 0.9),
        (5.5, 10.0, "speech", 0.85),
        (10.2, 15.0, "speech", 0.92),
        (30.0, 45.0, "music", 0.88),
    ]
    merged = _merge_segments(raw, max_gap=1.0)
    assert len(merged) == 2
    assert merged[0][0] == 0.0  # start of first speech group
    assert merged[0][1] == 15.0  # end of last speech segment
    assert merged[0][2] == "speech"
    assert merged[1][2] == "music"
```

**Step 2: Run tests to verify failure**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_audio_processor.py::test_run_vad_returns_segments tests/test_audio_processor.py::test_classify_segments_returns_labels tests/test_audio_processor.py::test_merge_adjacent_segments -v
```

Expected: FAIL (functions not found).

**Step 3: Implement VAD + classification + merging**

Add to `audio_processor.py`:

```python
# ── ML Model Loading (lazy, cached) ─────────────────────────────────────────

_vad_model = None
_panns_model = None


def _load_vad_model():
    """Load Silero VAD model (lazy, cached)."""
    global _vad_model
    if _vad_model is None:
        import torch
        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
        )
        _vad_model = (model, utils)
    return _vad_model


def _load_panns_model():
    """Load PANNs CNN14 model (lazy, cached)."""
    global _panns_model
    if _panns_model is None:
        from panns_inference import AudioTagging
        _panns_model = AudioTagging(checkpoint_path=None, device="cuda")
    return _panns_model


# Import helper for VAD — used in mocking
try:
    from silero_vad import get_speech_timestamps as silero_get_speech_timestamps
except ImportError:
    def silero_get_speech_timestamps(*args, **kwargs):
        return []


# ── VAD ──────────────────────────────────────────────────────────────────────

def _run_vad(
    waveform: "np.ndarray", sample_rate: int
) -> list[tuple[float, float]]:
    """Run Silero VAD on waveform, return list of (start_sec, end_sec) pairs."""
    import torch

    model, _ = _load_vad_model()

    # Silero requires 16kHz
    tensor = torch.from_numpy(waveform)
    if tensor.dim() > 1:
        tensor = tensor.mean(dim=0)

    timestamps = silero_get_speech_timestamps(
        tensor, model,
        sampling_rate=sample_rate,
        return_seconds=False,
    )

    segments = []
    for ts in timestamps:
        start_s = ts["start"] / sample_rate
        end_s = ts["end"] / sample_rate
        segments.append((start_s, end_s))

    return segments


# ── Audio Classification ─────────────────────────────────────────────────────

# AudioSet class labels (top-level). Full list has 527 classes.
# We load the labels from PANNs at runtime.
_AUDIOSET_LABELS: list[str] | None = None


def _get_audioset_labels() -> list[str]:
    """Get AudioSet class labels."""
    global _AUDIOSET_LABELS
    if _AUDIOSET_LABELS is None:
        try:
            import panns_inference
            from pathlib import Path as _P
            labels_path = _P(panns_inference.__file__).parent / "metadata" / "class_labels_indices.csv"
            if labels_path.exists():
                _AUDIOSET_LABELS = []
                for line in labels_path.read_text().strip().split("\n")[1:]:
                    parts = line.split(",", 2)
                    if len(parts) >= 3:
                        _AUDIOSET_LABELS.append(parts[2].strip().strip('"'))
            else:
                _AUDIOSET_LABELS = [f"class_{i}" for i in range(527)]
        except Exception:
            _AUDIOSET_LABELS = [f"class_{i}" for i in range(527)]
    return _AUDIOSET_LABELS


def _classify_audio_frames(
    waveform: "np.ndarray",
    sample_rate: int,
    vad_segments: list[tuple[float, float]],
) -> list[tuple[float, float, str, float]]:
    """Classify audio segments using PANNs CNN14.

    Returns list of (start, end, label, confidence).
    """
    import numpy as np

    at = _load_panns_model()
    labels = _get_audioset_labels()
    results = []

    for start_s, end_s in vad_segments:
        start_idx = int(start_s * sample_rate)
        end_idx = int(end_s * sample_rate)
        chunk = waveform[start_idx:end_idx]

        if len(chunk) < sample_rate // 4:  # skip very short segments
            continue

        # PANNs expects (batch, samples) at 32kHz or 16kHz
        chunk_2d = chunk[np.newaxis, :]
        clipwise_output, _ = at.inference(chunk_2d)

        top_idx = int(np.argmax(clipwise_output[0]))
        top_conf = float(clipwise_output[0][top_idx])
        label = labels[top_idx] if top_idx < len(labels) else f"class_{top_idx}"

        # Also get sub-classifications (top-3 excluding the primary)
        results.append((start_s, end_s, label, top_conf))

    return results


# ── Segment Merging ──────────────────────────────────────────────────────────

def _merge_segments(
    segments: list[tuple[float, float, str, float]],
    max_gap: float = 1.0,
) -> list[tuple[float, float, str, float]]:
    """Merge adjacent segments of the same classification type.

    Segments within max_gap seconds of each other with the same label get merged.
    """
    if not segments:
        return []

    merged: list[tuple[float, float, str, float]] = []
    current_start, current_end, current_label, current_conf = segments[0]

    for start, end, label, conf in segments[1:]:
        if label == current_label and start - current_end <= max_gap:
            # Extend current segment
            current_end = end
            current_conf = max(current_conf, conf)
        else:
            merged.append((current_start, current_end, current_label, current_conf))
            current_start, current_end, current_label, current_conf = start, end, label, conf

    merged.append((current_start, current_end, current_label, current_conf))
    return merged
```

**Step 4: Run tests to verify they pass**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_audio_processor.py -v
```

Expected: All 12 tests PASS.

**Step 5: Commit**

```bash
cd ~/projects/ai-agents && git add agents/audio_processor.py tests/test_audio_processor.py
git commit -m "feat: audio_processor VAD, PANNs classification, segment merging"
```

---

## Task 6: Diarization + Transcription Pipeline

**Files:**
- Modify: `~/projects/ai-agents/agents/audio_processor.py`
- Modify: `~/projects/ai-agents/tests/test_audio_processor.py`

**Step 1: Write failing tests**

Add to `tests/test_audio_processor.py`:

```python
def test_run_diarization():
    """Test diarization returns speaker-labeled segments."""
    from agents.audio_processor import _run_diarization

    with patch("agents.audio_processor._load_diarization_pipeline") as mock_load:
        mock_pipeline = MagicMock()
        mock_load.return_value = mock_pipeline

        # Simulate diarization output
        mock_turn1 = MagicMock()
        mock_turn1.start = 0.0
        mock_turn1.end = 5.0
        mock_turn2 = MagicMock()
        mock_turn2.start = 5.5
        mock_turn2.end = 10.0
        mock_pipeline.return_value.itertracks.return_value = [
            (mock_turn1, None, "SPEAKER_00"),
            (mock_turn2, None, "SPEAKER_01"),
        ]

        result = _run_diarization("/tmp/fake.wav")

    assert len(result) == 2
    assert result[0] == (0.0, 5.0, "SPEAKER_00")
    assert result[1] == (5.5, 10.0, "SPEAKER_01")


def test_run_transcription():
    """Test transcription returns text with timestamps."""
    from agents.audio_processor import _run_transcription

    with patch("agents.audio_processor._load_whisper_model") as mock_load:
        mock_model = MagicMock()
        mock_load.return_value = mock_model

        # Simulate faster-whisper output
        mock_seg = MagicMock()
        mock_seg.text = " Hello world"
        mock_seg.start = 0.0
        mock_seg.end = 2.5
        mock_model.transcribe.return_value = ([mock_seg], MagicMock(language="en"))

        text = _run_transcription("/tmp/fake.wav", 0.0, 10.0)

    assert "Hello world" in text
```

**Step 2: Run tests to verify failure**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_audio_processor.py::test_run_diarization tests/test_audio_processor.py::test_run_transcription -v
```

Expected: FAIL.

**Step 3: Implement diarization + transcription**

Add to `audio_processor.py`:

```python
_diarization_pipeline = None
_whisper_model = None


def _load_diarization_pipeline():
    """Load pyannote speaker diarization pipeline (lazy, cached)."""
    global _diarization_pipeline
    if _diarization_pipeline is None:
        import os
        import torch
        from pyannote.audio import Pipeline

        hf_token = os.environ.get("HF_TOKEN", "")
        if not hf_token:
            # Try pass store
            import subprocess
            try:
                result = subprocess.run(
                    ["pass", "show", "huggingface/token"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    hf_token = result.stdout.strip()
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

        _diarization_pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token,
        )
        _diarization_pipeline.to(torch.device("cuda"))

    return _diarization_pipeline


def _load_whisper_model():
    """Load faster-whisper model (lazy, cached)."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel(
            "large-v3-turbo",
            device="cuda",
            compute_type="int8",
        )
    return _whisper_model


def _run_diarization(
    audio_path: str,
) -> list[tuple[float, float, str]]:
    """Run speaker diarization on an audio file.

    Returns list of (start_sec, end_sec, speaker_label).
    """
    pipeline = _load_diarization_pipeline()
    diarization = pipeline(audio_path)

    segments = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append((turn.start, turn.end, speaker))

    return segments


def _run_transcription(
    audio_path: str,
    start_seconds: float,
    end_seconds: float,
) -> str:
    """Transcribe a segment of audio using faster-whisper.

    Returns the transcribed text.
    """
    model = _load_whisper_model()

    segments, info = model.transcribe(
        audio_path,
        language="en",
        beam_size=5,
        no_speech_threshold=0.2,
        log_prob_threshold=-0.5,
        condition_on_previous_text=False,
        clip_timestamps=[start_seconds],
    )

    text_parts = []
    for seg in segments:
        # Only keep segments within our time range
        if seg.end <= end_seconds + 1.0:
            text_parts.append(seg.text.strip())

    return " ".join(text_parts)
```

**Step 4: Run tests to verify they pass**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_audio_processor.py -v
```

Expected: All 14 tests PASS.

**Step 5: Commit**

```bash
cd ~/projects/ai-agents && git add agents/audio_processor.py tests/test_audio_processor.py
git commit -m "feat: audio_processor diarization (pyannote) and transcription (faster-whisper)"
```

---

## Task 7: Main Processing Orchestrator

**Files:**
- Modify: `~/projects/ai-agents/agents/audio_processor.py`
- Modify: `~/projects/ai-agents/tests/test_audio_processor.py`

This task wires all the pipeline stages together into the main `_process_file()` and `_process_new_files()` functions.

**Step 1: Write failing test**

Add to `tests/test_audio_processor.py`:

```python
def test_process_file_speech(tmp_path):
    """Test full processing pipeline for a file with speech."""
    from agents.audio_processor import (
        _process_file, AudioProcessorState, AUDIO_RAG_DIR,
    )

    # Create a fake FLAC file
    fake_flac = tmp_path / "rec-20260308-143000.flac"
    fake_flac.write_bytes(b"fake-audio-data")

    state = AudioProcessorState()
    rag_dir = tmp_path / "rag-output"

    with patch("agents.audio_processor.torchaudio") as mock_ta, \
         patch("agents.audio_processor._run_vad") as mock_vad, \
         patch("agents.audio_processor._classify_audio_frames") as mock_classify, \
         patch("agents.audio_processor._merge_segments") as mock_merge, \
         patch("agents.audio_processor._run_diarization") as mock_diar, \
         patch("agents.audio_processor._run_transcription") as mock_trans, \
         patch("agents.audio_processor._check_vram_available", return_value=True), \
         patch("agents.audio_processor.AUDIO_RAG_DIR", rag_dir):

        # Mock audio loading: 3 minutes of 16kHz mono
        mock_ta.load.return_value = (MagicMock(), 48000)
        mock_ta.functional.resample.return_value = MagicMock(
            numpy=MagicMock(return_value=np.zeros(16000 * 180, dtype=np.float32))
        )

        # Mock VAD: one speech region
        mock_vad.return_value = [(10.0, 55.0)]

        # Mock classification
        mock_classify.return_value = [(10.0, 55.0, "Speech", 0.92)]

        # Mock merge (pass through)
        mock_merge.return_value = [(10.0, 55.0, "speech", 0.92)]

        # Mock diarization
        mock_diar.return_value = [(10.0, 30.0, "SPEAKER_00"), (30.5, 55.0, "SPEAKER_01")]

        # Mock transcription
        mock_trans.return_value = "Hello, this is a test conversation."

        info = _process_file(fake_flac, state)

    assert info is not None
    assert info.speech_seconds > 0
    assert info.segment_count >= 1
    assert info.speaker_count == 2
    # Verify RAG file was written
    rag_files = list(rag_dir.glob("*.md"))
    assert len(rag_files) >= 1
```

**Step 2: Run test to verify failure**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_audio_processor.py::test_process_file_speech -v
```

Expected: FAIL.

**Step 3: Implement the orchestrator**

Add to `audio_processor.py`:

```python
try:
    import torchaudio
except ImportError:
    torchaudio = None  # type: ignore


def _resample_to_16k(audio_path: Path) -> tuple["np.ndarray", int]:
    """Load and resample audio to 16kHz mono."""
    import numpy as np

    waveform, sr = torchaudio.load(str(audio_path))

    # Convert to mono
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)

    # Resample to 16kHz
    if sr != 16000:
        waveform = torchaudio.functional.resample(waveform, sr, 16000)

    return waveform.squeeze(0).numpy(), 16000


def _compute_energy_db(waveform: "np.ndarray", start: float, end: float, sr: int) -> float:
    """Compute average energy in dB for a segment."""
    import numpy as np
    start_idx = int(start * sr)
    end_idx = int(end * sr)
    chunk = waveform[start_idx:end_idx]
    if len(chunk) == 0:
        return -100.0
    rms = np.sqrt(np.mean(chunk ** 2))
    if rms < 1e-10:
        return -100.0
    return float(20 * np.log10(rms))


def _process_file(
    audio_path: Path,
    state: AudioProcessorState,
) -> ProcessedFileInfo | None:
    """Process a single raw FLAC file through the full pipeline."""
    import numpy as np

    filename = audio_path.name
    base_timestamp = _extract_timestamp_from_filename(filename)

    log.info("Processing %s", filename)

    # Check VRAM
    if not _check_vram_available():
        log.warning("Insufficient VRAM, deferring %s", filename)
        return None

    # Load and resample
    try:
        waveform, sr = _resample_to_16k(audio_path)
    except Exception as exc:
        log.error("Failed to load %s: %s", filename, exc)
        return ProcessedFileInfo(filename=filename, error=str(exc), processed_at=time.time())

    total_seconds = len(waveform) / sr

    # Stage 1: VAD
    vad_segments = _run_vad(waveform, sr)
    log.debug("VAD found %d segments in %s", len(vad_segments), filename)

    if not vad_segments:
        log.info("No activity detected in %s", filename)
        return ProcessedFileInfo(
            filename=filename, processed_at=time.time(),
            silence_seconds=total_seconds,
        )

    # Stage 2: Classification
    classified = _classify_audio_frames(waveform, sr, vad_segments)

    # Stage 3: Merge adjacent same-type segments
    merged = _merge_segments(classified, max_gap=1.0)

    # Filter out noise
    kept = [
        (s, e, label.lower(), conf)
        for s, e, label, conf in merged
        if not _should_skip_segment(label.lower(), conf)
        and (e - s) >= MIN_SEGMENT_SECONDS
    ]

    if not kept:
        log.info("All segments filtered as noise in %s", filename)
        return ProcessedFileInfo(
            filename=filename, processed_at=time.time(),
            silence_seconds=total_seconds,
        )

    # Stage 4: Process each kept segment
    speech_seconds = 0.0
    music_seconds = 0.0
    all_speakers: set[str] = set()
    segment_count = 0

    AUDIO_RAG_DIR.mkdir(parents=True, exist_ok=True)

    for start, end, label, conf in kept:
        duration = end - start
        energy = _compute_energy_db(waveform, start, end, sr)

        if label in ("speech", "conversation"):
            # Diarize
            try:
                # Write temp segment for diarization
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp_path = tmp.name
                import soundfile  # type: ignore
                start_idx = int(start * sr)
                end_idx = int(end * sr)
                soundfile.write(tmp_path, waveform[start_idx:end_idx], sr)

                diar_segments = _run_diarization(tmp_path)
                speakers = list({s for _, _, s in diar_segments})
                all_speakers.update(speakers)

                # Transcribe
                transcript = _run_transcription(str(audio_path), start, end)

                Path(tmp_path).unlink(missing_ok=True)
            except Exception as exc:
                log.warning("Diarization/transcription failed for segment: %s", exc)
                speakers = []
                transcript = "[transcription failed]"

            seg = AudioSegment(
                source_file=filename,
                start_seconds=start,
                end_seconds=end,
                classification="speech",
                confidence=conf,
                speakers=speakers,
                speaker_count=len(speakers),
                transcript=transcript,
                energy_db=energy,
            )
            md = _format_transcript_markdown(seg, base_timestamp)
            start_tag = _format_timestamp(start).replace(":", "")
            out_name = f"transcript-{filename.replace('.flac', '')}-s{start_tag}.md"
            (AUDIO_RAG_DIR / out_name).write_text(md, encoding="utf-8")
            speech_seconds += duration

        else:
            # Non-speech event — metadata only
            # Get sub-classifications from PANNs top-3
            sub_classes = []
            try:
                at = _load_panns_model()
                labels_list = _get_audioset_labels()
                start_idx = int(start * sr)
                end_idx = int(end * sr)
                chunk = waveform[start_idx:end_idx]
                import numpy as _np
                clipwise, _ = at.inference(chunk[_np.newaxis, :])
                top_indices = _np.argsort(clipwise[0])[-4:][::-1]  # top 4
                sub_classes = [
                    labels_list[i] for i in top_indices[1:4]  # skip primary
                    if clipwise[0][i] > 0.1 and i < len(labels_list)
                ]
            except Exception:
                pass

            seg = AudioSegment(
                source_file=filename,
                start_seconds=start,
                end_seconds=end,
                classification=label,
                confidence=conf,
                sub_classifications=sub_classes,
                energy_db=energy,
            )
            md = _format_event_markdown(seg, base_timestamp)
            start_tag = _format_timestamp(start).replace(":", "")
            out_name = f"event-{filename.replace('.flac', '')}-s{start_tag}.md"
            (AUDIO_RAG_DIR / out_name).write_text(md, encoding="utf-8")
            music_seconds += duration

        segment_count += 1
        _log_change("segment_processed", f"{filename}:{_format_timestamp(start)}", {
            "classification": label,
            "duration": round(duration, 1),
            "speakers": len(all_speakers),
        })

    silence_seconds = total_seconds - speech_seconds - music_seconds

    info = ProcessedFileInfo(
        filename=filename,
        processed_at=time.time(),
        speech_seconds=speech_seconds,
        music_seconds=music_seconds,
        silence_seconds=max(0, silence_seconds),
        segment_count=segment_count,
        speaker_count=len(all_speakers),
    )
    log.info(
        "Processed %s: %d segments, %.0fs speech, %.0fs music, %d speakers",
        filename, segment_count, speech_seconds, music_seconds, len(all_speakers),
    )
    return info


def _process_new_files(state: AudioProcessorState) -> dict[str, int]:
    """Find and process all unprocessed raw FLAC files."""
    from shared.notify import send_notification

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    files = _find_unprocessed_files(RAW_DIR, state)

    if not files:
        log.info("No new audio files to process")
        return {"processed": 0, "skipped": 0}

    # Skip the most recent file — it may still be recording
    if len(files) > 1:
        files = files[:-1]
    else:
        # Check if the only file is still being written (mtime within 60s)
        if time.time() - files[0].stat().st_mtime < 60:
            log.info("Only file is still recording, skipping")
            return {"processed": 0, "skipped": 1}

    processed = 0
    skipped = 0

    for f in files:
        info = _process_file(f, state)
        if info is None:
            skipped += 1
        else:
            state.processed_files[f.name] = info
            processed += 1

    state.last_run = time.time()
    _save_state(state)
    _write_profile_facts(state)

    if processed > 0:
        msg = f"Audio processor: {processed} files, {skipped} skipped"
        send_notification("Audio Processor", msg, tags=["microphone"])

    return {"processed": processed, "skipped": skipped}
```

Update the CLI `main()` to wire up `--process`:

```python
# Replace the placeholder in main():
    if args.process:
        state = _load_state()
        summary = _process_new_files(state)
        log.info("Processing complete: %s", summary)
    elif args.reprocess:
        state = _load_state()
        path = Path(args.reprocess)
        if not path.exists():
            path = RAW_DIR / args.reprocess
        if not path.exists():
            print(f"File not found: {args.reprocess}")
            return
        info = _process_file(path, state)
        if info:
            state.processed_files[path.name] = info
            _save_state(state)
            _write_profile_facts(state)
    elif args.stats:
```

**Step 4: Run tests to verify they pass**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_audio_processor.py -v
```

Expected: All 15 tests PASS.

**Step 5: Commit**

```bash
cd ~/projects/ai-agents && git add agents/audio_processor.py tests/test_audio_processor.py
git commit -m "feat: audio_processor main orchestrator — full processing pipeline"
```

---

## Task 8: Ingest + Profiler Registration

**Files:**
- Modify: `~/projects/ai-agents/agents/ingest.py`
- Modify: `~/projects/ai-agents/agents/profiler_sources.py`

**Step 1: Add ambient-audio to ingest auto-tagging**

In `~/projects/ai-agents/agents/ingest.py`, add to `_SERVICE_PATH_PATTERNS` dict (around line 355):

```python
"rag-sources/audio": "ambient-audio",
```

**Step 2: Add ambient-audio to profiler registration**

In `~/projects/ai-agents/agents/profiler_sources.py`:

Add `"ambient-audio"` to `BRIDGED_SOURCE_TYPES` (line 31).

Add to `SOURCE_TYPE_CHUNK_CAPS` dict:

```python
"ambient-audio": 100,
```

**Step 3: Verify existing tests still pass**

```bash
cd ~/projects/ai-agents && uv run pytest tests/ -q --timeout=30 2>&1 | tail -5
```

Expected: All tests pass.

**Step 4: Commit**

```bash
cd ~/projects/ai-agents && git add agents/ingest.py agents/profiler_sources.py
git commit -m "feat: register ambient-audio in ingest auto-tagging and profiler sources"
```

---

## Task 9: Briefing Integration

**Files:**
- Modify: `~/projects/ai-agents/agents/briefing.py`

**Step 1: Add audio activity section to briefing**

Find the block that builds the `obsidian_section` (around line 454-465). After it, add:

```python
    # Audio activity
    audio_section = ""
    try:
        audio_state_path = Path.home() / ".cache" / "audio-processor" / "state.json"
        if audio_state_path.exists():
            audio_data = json.loads(audio_state_path.read_text())
            files = audio_data.get("processed_files", {})
            cutoff = time.time() - (hours * 3600)
            recent = {k: v for k, v in files.items() if v.get("processed_at", 0) > cutoff}
            if recent:
                total_speech = sum(v.get("speech_seconds", 0) for v in recent.values())
                total_music = sum(v.get("music_seconds", 0) for v in recent.values())
                total_speakers = max((v.get("speaker_count", 0) for v in recent.values()), default=0)
                audio_section = (
                    f"\n## Audio Activity\n"
                    f"{len(recent)} recordings processed. "
                    f"Speech: {total_speech / 3600:.1f}h, Music: {total_music / 3600:.1f}h. "
                    f"Max speakers in a session: {total_speakers}.\n"
                )
    except (ImportError, Exception) as exc:
        log.debug("Audio context unavailable: %s", exc)
```

Then add `{audio_section}` to the prompt assembly string (after `{obsidian_section}`).

**Step 2: Verify it doesn't break anything**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_briefing.py -v 2>&1 | tail -10
```

Expected: All briefing tests pass.

**Step 3: Commit**

```bash
cd ~/projects/ai-agents && git add agents/briefing.py
git commit -m "feat: add audio activity section to briefing agent"
```

---

## Task 10: Systemd Timer for Audio Processor

**Files:**
- Create: `~/.config/systemd/user/audio-processor.service`
- Create: `~/.config/systemd/user/audio-processor.timer`

**Step 1: Create service file**

```ini
[Unit]
Description=Ambient audio RAG processor
OnFailure=notify-failure@%n.service

[Service]
Type=oneshot
WorkingDirectory=/home/hapaxlegomenon/projects/ai-agents
ExecStart=/home/hapaxlegomenon/.local/bin/uv run python -m agents.audio_processor --process
Environment=PATH=/home/hapaxlegomenon/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=/home/hapaxlegomenon
Environment=GNUPGHOME=/home/hapaxlegomenon/.gnupg
Environment=PASSWORD_STORE_DIR=/home/hapaxlegomenon/.password-store
MemoryMax=4G
SyslogIdentifier=audio-processor
```

Note: `MemoryMax=4G` instead of the usual 512M because this agent loads ML models into RAM.

**Step 2: Create timer file**

```ini
[Unit]
Description=Audio processor every 30 minutes

[Timer]
OnCalendar=*-*-* *:05/30:00
Persistent=true
RandomizedDelaySec=120

[Install]
WantedBy=timers.target
```

**Step 3: Reload and verify**

```bash
systemctl --user daemon-reload
systemctl --user list-unit-files | grep audio-processor
```

Do NOT enable yet — Task 13 handles that.

---

## Task 11: Install rclone + Configure Google Drive Remote

**Step 1: Install rclone**

```bash
sudo apt install -y rclone
rclone version
```

**Step 2: Configure Google Drive remote**

```bash
rclone config
# Choose: n (new remote)
# Name: gdrive
# Storage: drive (Google Drive)
# client_id: (leave blank for rclone default)
# client_secret: (leave blank)
# scope: 1 (full access)
# root_folder_id: (leave blank)
# service_account_file: (leave blank)
# Auto config: y
# Follow browser auth flow
# Team drive: n
```

**Step 3: Verify access**

```bash
rclone lsd gdrive:
```

Expected: Lists top-level Drive folders.

**Step 4: Create archive directory**

```bash
rclone mkdir gdrive:audio-archive
rclone lsd gdrive: | grep audio-archive
```

---

## Task 12: Audio Archiver Timer

**Files:**
- Create: `~/.local/bin/audio-archive.sh`
- Create: `~/.config/systemd/user/audio-archiver.service`
- Create: `~/.config/systemd/user/audio-archiver.timer`

**Step 1: Create archive script**

```bash
#!/usr/bin/env bash
set -euo pipefail

RAW_DIR="$HOME/audio-recording/raw"
DRIVE_PATH="gdrive:audio-archive/raw"
LOG_TAG="audio-archiver"

logger -t "$LOG_TAG" "Starting audio archive run"

# Move raw files older than 48h to Google Drive
COUNT=$(rclone move "$RAW_DIR" "$DRIVE_PATH" \
  --min-age 48h \
  --transfers 4 \
  --drive-chunk-size 64M \
  --log-level INFO \
  --stats-one-line \
  2>&1 | tee /dev/stderr | grep -c "Transferred:" || echo 0)

logger -t "$LOG_TAG" "Archive complete"

# Disk space check — alert if audio dir exceeds 50GB
USED=$(du -sb "$HOME/audio-recording" 2>/dev/null | cut -f1)
THRESHOLD=$((50 * 1024 * 1024 * 1024))
if [ "${USED:-0}" -gt "$THRESHOLD" ]; then
    curl -s -d "Audio storage at $(numfmt --to=iec "$USED"), threshold 50GB" \
        "http://127.0.0.1:8090/audio-storage" || true
fi
```

Make executable:

```bash
chmod +x ~/.local/bin/audio-archive.sh
```

**Step 2: Create service file**

```ini
[Unit]
Description=Archive raw audio recordings to Google Drive
OnFailure=notify-failure@%n.service

[Service]
Type=oneshot
ExecStart=/home/hapaxlegomenon/.local/bin/audio-archive.sh
Environment=PATH=/home/hapaxlegomenon/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=/home/hapaxlegomenon
SyslogIdentifier=audio-archiver
```

**Step 3: Create timer file**

```ini
[Unit]
Description=Archive audio recordings daily at 03:00

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

**Step 4: Reload and verify**

```bash
systemctl --user daemon-reload
systemctl --user list-unit-files | grep audio-archiver
```

Do NOT enable yet — Task 13 handles that.

---

## Task 13: Documentation Updates

**Files:**
- Modify: `~/projects/hapax-system/rules/system-context.md`
- Modify: `~/projects/hapaxromana/CLAUDE.md`
- Modify: `~/projects/ai-agents/README.md`
- Modify: `~/projects/ai-agents/CLAUDE.md`

**Step 1: Update system-context.md**

Add to Management Agents table:
```
| audio_processor | No | `--process`, `--stats`, `--reprocess FILE` |
```

Add to Management Timers table:
```
| audio-recorder | Always on | Continuous mic recording (ffmpeg) |
| audio-processor | Every 30min | Audio segmentation + transcription + RAG |
| audio-archiver | Daily 03:00 | rclone move raw audio to Google Drive |
```

**Step 2: Update hapaxromana CLAUDE.md**

Add `audio_processor` to Tier 2 agents table.
Add all 3 timers/services to Tier 3 table.

**Step 3: Update ai-agents README.md and CLAUDE.md**

Add `audio-processor` to agents table. Update agent count. Add timers. Add `ambient-audio` to ingest recognized patterns.

**Step 4: Commit in each repo**

```bash
cd ~/projects/hapax-system && git add rules/system-context.md && git commit -m "docs: add ambient audio pipeline to system context"
cd ~/projects/hapaxromana && git add CLAUDE.md && git commit -m "docs: add ambient audio pipeline to architecture"
cd ~/projects/ai-agents && git add README.md CLAUDE.md && git commit -m "docs: add audio_processor agent to README and CLAUDE.md"
```

---

## Task 14: Integration Test — Full Pipeline

**Step 1: Verify recorder is producing files**

```bash
ls -la ~/audio-recording/raw/ | head -10
```

Expected: Multiple 15-minute FLAC files.

**Step 2: Run audio processor on real data**

```bash
cd ~/projects/ai-agents && uv run python -m agents.audio_processor --process -v
```

Verify: `~/documents/rag-sources/audio/` has transcript and/or event markdown files.

**Step 3: Check RAG output format**

```bash
head -30 ~/documents/rag-sources/audio/*.md | head -50
```

Verify: YAML frontmatter has `source_service: ambient-audio`, correct timestamps, speaker info.

**Step 4: Run stats**

```bash
cd ~/projects/ai-agents && uv run python -m agents.audio_processor --stats
```

**Step 5: Test rclone archival (dry run)**

```bash
rclone move ~/audio-recording/raw/ gdrive:audio-archive/raw/ --min-age 48h --dry-run
```

Expected: Shows files that would be moved (or none if all files are < 48h old).

**Step 6: Enable timers**

```bash
systemctl --user enable --now audio-processor.timer
systemctl --user enable --now audio-archiver.timer
systemctl --user list-timers | grep -E "audio-processor|audio-archiver|audio-recorder"
```

**Step 7: Run all tests**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_audio_processor.py -v
```

Expected: All tests pass.

---

## Summary

| Task | Description | Type |
|------|-------------|------|
| 1 | Audio recorder systemd service | Infrastructure |
| 2 | Audio processor skeleton + schemas + tests | Core |
| 3 | Add ML dependencies | Core |
| 4 | VRAM check + file discovery helpers | Core |
| 5 | VAD + classification pipeline | Core |
| 6 | Diarization + transcription pipeline | Core |
| 7 | Main processing orchestrator | Core |
| 8 | Ingest + profiler registration | Integration |
| 9 | Briefing integration | Integration |
| 10 | Audio processor systemd timer | Infrastructure |
| 11 | Install rclone + configure Drive | Infrastructure |
| 12 | Audio archiver timer | Infrastructure |
| 13 | Documentation updates | Docs |
| 14 | Integration test | Verification |
