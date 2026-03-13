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
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

try:
    import torchaudio
except ImportError:
    torchaudio = None  # type: ignore

try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass
from opentelemetry import trace

_tracer = trace.get_tracer(__name__)

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
SKIP_CLASSIFICATIONS = frozenset(
    {
        "silence",
        "white_noise",
        "static",
        "hum",
        "buzz",
        "air_conditioning",
        "mechanical_fan",
        "computer_keyboard",
        "typing",
        "mouse_click",
        "noise",
        "background_noise",
    }
)

# AudioSet classes to keep as events (non-speech, interesting)
KEEP_EVENT_CLASSIFICATIONS = frozenset(
    {
        "music",
        "singing",
        "musical_instrument",
        "guitar",
        "piano",
        "drum",
        "bass_guitar",
        "synthesizer",
        "electronic_music",
        "laughter",
        "clapping",
        "door",
        "doorbell",
        "telephone",
        "alarm",
        "speech",
        "conversation",
    }
)

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
        "timestamp": datetime.now(UTC).isoformat(),
        "type": change_type,
        "detail": detail,
    }
    if extra:
        entry.update(extra)
    with open(CHANGES_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    log.debug("Logged change: %s — %s", change_type, detail)


def _check_vram_available(min_mb: int = MIN_VRAM_FREE_MB) -> bool:
    """Check if enough GPU VRAM is available for processing."""
    try:
        import subprocess

        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            free_mb = int(result.stdout.strip().split("\n")[0])
            log.debug("GPU VRAM free: %d MB (need %d MB)", free_mb, min_mb)
            return free_mb >= min_mb
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError) as exc:
        log.debug("VRAM check failed: %s", exc)
    return False


def _find_unprocessed_files(raw_dir: Path, state: AudioProcessorState) -> list[Path]:
    """Find raw FLAC files that haven't been processed yet."""
    files = sorted(
        f
        for f in raw_dir.glob("rec-*.flac")
        if f.name not in state.processed_files and f.stat().st_size > 0
    )
    return files


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
        return datetime.now(UTC).isoformat()[:19]


# ── Audio Loading ─────────────────────────────────────────────────────────────


def _resample_to_16k(audio_path: Path) -> tuple[np.ndarray, int]:
    """Load and resample audio to 16kHz mono."""

    waveform, sr = torchaudio.load(str(audio_path))

    # Convert to mono
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)

    # Resample to 16kHz
    if sr != 16000:
        waveform = torchaudio.functional.resample(waveform, sr, 16000)

    return waveform.squeeze(0).numpy(), 16000


def _compute_energy_db(waveform: np.ndarray, start: float, end: float, sr: int) -> float:
    """Compute average energy in dB for a segment."""
    import numpy as np

    start_idx = int(start * sr)
    end_idx = int(end * sr)
    chunk = waveform[start_idx:end_idx]
    if len(chunk) == 0:
        return -100.0
    rms = np.sqrt(np.mean(chunk**2))
    if rms < 1e-10:
        return -100.0
    return float(20 * np.log10(rms))


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


def _run_vad(waveform: np.ndarray, sample_rate: int) -> list[tuple[float, float]]:
    """Run Silero VAD on waveform, return list of (start_sec, end_sec) pairs."""
    import torch

    model, _ = _load_vad_model()

    # Silero requires 16kHz
    tensor = torch.from_numpy(waveform)
    if tensor.dim() > 1:
        tensor = tensor.mean(dim=0)

    timestamps = silero_get_speech_timestamps(
        tensor,
        model,
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
            from pathlib import Path as _P

            import panns_inference

            labels_path = (
                _P(panns_inference.__file__).parent / "metadata" / "class_labels_indices.csv"
            )
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
    waveform: np.ndarray,
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

        # CNN14 pooling layers need ~1s minimum input at 16kHz
        if len(chunk) < sample_rate:
            continue

        # PANNs expects (batch, samples) at 32kHz or 16kHz
        chunk_2d = chunk[np.newaxis, :]
        try:
            clipwise_output, _ = at.inference(chunk_2d)
        except RuntimeError:
            log.warning(
                "PANNs failed on segment %.1f-%.1f (len=%d), skipping", start_s, end_s, len(chunk)
            )
            continue

        top_idx = int(np.argmax(clipwise_output[0]))
        top_conf = float(clipwise_output[0][top_idx])
        label = labels[top_idx] if top_idx < len(labels) else f"class_{top_idx}"

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


# ── Diarization & Transcription (lazy, cached) ───────────────────────────────

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
            import subprocess

            try:
                result = subprocess.run(
                    ["pass", "show", "huggingface/token"],
                    capture_output=True,
                    text=True,
                    timeout=5,
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


def _run_diarization(audio_path: str) -> list[tuple[float, float, str]]:
    """Run speaker diarization on an audio file.
    Returns list of (start_sec, end_sec, speaker_label).
    """
    pipeline = _load_diarization_pipeline()
    diarization = pipeline(audio_path)

    segments = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append((turn.start, turn.end, speaker))

    return segments


def _run_transcription(audio_path: str, start_seconds: float, end_seconds: float) -> str:
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
        if seg.end <= end_seconds + 1.0:
            text_parts.append(seg.text.strip())

    return " ".join(text_parts)


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

    sub_class_yaml = (
        "[" + ", ".join(seg.sub_classifications) + "]" if seg.sub_classifications else "[]"
    )

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

    facts.append(
        {
            "dimension": "energy_and_attention",
            "key": "audio_daily_summary",
            "value": (
                f"{speech_h:.1f}h speech, {music_h:.1f}h music, "
                f"{silence_h:.1f}h silence across {len(state.processed_files)} recordings"
            ),
            "confidence": 0.95,
            "source": source,
            "evidence": f"Aggregated from {total_segments} segments",
        }
    )

    # Conversation patterns
    multi_speaker = [f for f in state.processed_files.values() if f.speaker_count > 1]
    if multi_speaker:
        facts.append(
            {
                "dimension": "communication_patterns",
                "key": "audio_conversation_patterns",
                "value": f"{len(multi_speaker)} recordings with multiple speakers",
                "confidence": 0.90,
                "source": source,
                "evidence": f"Diarization detected multi-speaker in {len(multi_speaker)} files",
            }
        )

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


# ── Main Processing Pipeline ──────────────────────────────────────────────────


def _process_file(
    audio_path: Path,
    state: AudioProcessorState,
) -> ProcessedFileInfo | None:
    """Process a single raw FLAC file through the full pipeline."""

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
            filename=filename,
            processed_at=time.time(),
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
        if not _should_skip_segment(label.lower(), conf) and (e - s) >= MIN_SEGMENT_SECONDS
    ]

    if not kept:
        log.info("All segments filtered as noise in %s", filename)
        return ProcessedFileInfo(
            filename=filename,
            processed_at=time.time(),
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
            sub_classes: list[str] = []
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
                    labels_list[i]
                    for i in top_indices[1:4]  # skip primary
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
        _log_change(
            "segment_processed",
            f"{filename}:{_format_timestamp(start)}",
            {
                "classification": label,
                "duration": round(duration, 1),
                "speakers": len(all_speakers),
            },
        )

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
        filename,
        segment_count,
        speech_seconds,
        music_seconds,
        len(all_speakers),
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
    print(
        f"Last run:        {datetime.fromtimestamp(state.last_run, tz=UTC).strftime('%Y-%m-%d %H:%M UTC') if state.last_run else 'never'}"
    )


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Ambient audio processor for RAG pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--process", action="store_true", help="Process new audio chunks")
    group.add_argument("--stats", action="store_true", help="Show processing statistics")
    group.add_argument("--reprocess", type=str, metavar="FILE", help="Reprocess a specific file")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    from shared.log_setup import configure_logging

    configure_logging(agent="audio-processor", level="DEBUG" if args.verbose else None)

    action = "process" if args.process else "reprocess" if args.reprocess else "stats"
    with _tracer.start_as_current_span(
        f"audio_processor.{action}",
        attributes={"agent.name": "audio_processor", "agent.repo": "hapax-council"},
    ):
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
            state = _load_state()
            if not state.processed_files:
                print("No processing state found. Run --process first.")
                return
            _print_stats(state)


if __name__ == "__main__":
    main()
