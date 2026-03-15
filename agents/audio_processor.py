"""audio_processor.py — Ambient audio processing for RAG pipeline.

Optimized for a sample-based hip hop producer workflow. Processes raw FLAC
recordings from the audio-recorder service through full-waveform classification,
producing searchable RAG documents in four categories:

  - sample-session: Speech annotations over music (highest value — sample hunting)
  - vocal-note: Spoken notes near music (production thoughts)
  - conversation: Multi-speaker dialogue (production discussions)
  - listening-log: Sustained music sessions with instrument timeline

Each output document is self-contained with enough semantic context to match
natural queries like "that track with the horn stab yesterday" or "production
notes about the snare from Monday."

Raw FLAC files are deleted after successful processing — no archival.

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
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import yaml
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
CACHE_DIR = Path.home() / ".cache" / "audio-processor"
STATE_FILE = CACHE_DIR / "state.json"
PROFILE_FACTS_FILE = CACHE_DIR / "audio-profile-facts.jsonl"
CHANGES_LOG = CACHE_DIR / "changes.jsonl"
RAG_SOURCES = Path.home() / "documents" / "rag-sources"
AUDIO_RAG_DIR = RAG_SOURCES / "audio"

# ── Classification Constants ─────────────────────────────────────────────────

# Sliding window for full-waveform PANNs classification
WINDOW_SECONDS = 10.0
HOP_SECONDS = 5.0

# Minimum durations per category
MIN_SAMPLE_SESSION_SPEECH = 2.0  # seconds — short reactions count
MIN_VOCAL_NOTE_SPEECH = 2.0  # seconds — "flip that" is 2 words
MIN_CONVERSATION_DURATION = 30.0  # seconds — substantial exchange
MIN_LISTENING_DURATION = 60.0  # seconds — sustained session
MIN_TRANSCRIPT_WORDS = 2  # minimum words to keep a transcript

# Probability thresholds for PANNs multi-label detection
MIN_MUSIC_PROB = 0.10  # music class probability threshold
MIN_SPEECH_PROB = 0.10  # speech class probability threshold
MIN_INSTRUMENT_PROB = 0.08  # individual instrument probability

# How close speech must be to music to count as a vocal-note (seconds)
MUSIC_SPEECH_PROXIMITY = 30.0

# VRAM threshold — skip GPU processing if less than this available (MB)
MIN_VRAM_FREE_MB = 6000

# ── Instrument Mapping ───────────────────────────────────────────────────────
# Maps PANNs AudioSet class labels → producer-friendly categories.

INSTRUMENT_MAP: dict[str, str] = {
    # Drums
    "Drum": "drums",
    "Drum kit": "drums",
    "Snare drum": "drums",
    "Bass drum": "drums",
    "Hi-hat": "drums",
    "Cymbal": "drums",
    "Rimshot": "drums",
    "Drum machine": "drums",
    "Drum roll": "drums",
    # Bass
    "Bass guitar": "bass",
    "Electric bass guitar": "bass",
    "Bass": "bass",
    # Keys
    "Piano": "keys",
    "Electric piano": "keys",
    "Keyboard (musical)": "keys",
    "Organ": "keys",
    "Hammond organ": "keys",
    "Harpsichord": "keys",
    # Synth
    "Synthesizer": "synth",
    "Electronic music": "synth",
    # Guitar
    "Guitar": "guitar",
    "Electric guitar": "guitar",
    "Acoustic guitar": "guitar",
    "Steel guitar, slide guitar": "guitar",
    # Horns & woodwinds
    "Trumpet": "horns",
    "Trombone": "horns",
    "French horn": "horns",
    "Brass instrument": "horns",
    "Saxophone": "horns",
    "Clarinet": "horns",
    "Flute": "horns",
    # Strings
    "Violin, fiddle": "strings",
    "Cello": "strings",
    "String section": "strings",
    "Harp": "strings",
    "Viola": "strings",
    "Double bass": "strings",
    # Vocals
    "Singing": "vocals",
    "Male singing": "vocals",
    "Female singing": "vocals",
    "Rapping": "vocals",
    "Humming": "vocals",
    "Choir": "vocals",
    "Vocal music": "vocals",
    # Percussion
    "Percussion": "percussion",
    "Tambourine": "percussion",
    "Cowbell": "percussion",
    "Maracas": "percussion",
    "Shaker": "percussion",
    "Clapping": "percussion",
    "Finger snapping": "percussion",
    "Wood block": "percussion",
    "Vibraphone": "percussion",
}

# AudioSet classes that indicate noise (skip entirely)
NOISE_CLASSES = frozenset(
    {
        "Silence",
        "White noise",
        "Static",
        "Hum",
        "Buzz",
        "Air conditioning",
        "Mechanical fan",
        "Computer keyboard",
        "Typing",
        "Mouse click",
        "Noise",
        "Background noise",
        "Pink noise",
        "Environmental noise",
        "Engine",
    }
)

# ── Consent Gate ─────────────────────────────────────────────────────────────
# interpersonal_transparency axiom (it-consent-001, T0): no persistent state
# about non-operator persons without an active consent contract. Multi-speaker
# conversations may contain non-operator speech. Suppress storage when:
#   1. speaker_count > 1 AND
#   2. Segment overlaps a calendar event (likely a work call) OR
#      no consent contract covers the non-operator speaker(s)

GCALENDAR_RAG_DIR = RAG_SOURCES / "gcalendar"


def _overlaps_calendar_event(segment_start: datetime, segment_end: datetime) -> bool:
    """Check if a time range overlaps any calendar event in the gcalendar RAG source.

    Reads YAML frontmatter from gcalendar RAG documents to find events whose
    timestamp and duration overlap the given segment. This is a heuristic for
    detecting work calls — a multi-speaker conversation during a calendar event
    is very likely a work meeting and should not be stored in the personal RAG.
    """
    if not GCALENDAR_RAG_DIR.exists():
        return False

    for path in GCALENDAR_RAG_DIR.iterdir():
        if path.suffix != ".md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
            if not text.startswith("---"):
                continue
            end_idx = text.index("---", 3)
            fm = yaml.safe_load(text[3:end_idx])
            if not fm or "timestamp" not in fm:
                continue

            event_start = datetime.fromisoformat(fm["timestamp"])
            duration_min = fm.get("duration_minutes", 60)
            event_end = event_start + timedelta(minutes=duration_min)

            # Check overlap
            if segment_start < event_end and segment_end > event_start:
                log.info(
                    "Conversation at %s overlaps calendar event '%s' — suppressing (it-consent-001)",
                    segment_start.isoformat(),
                    path.stem,
                )
                return True
        except Exception:
            continue

    return False


def _check_conversation_consent(
    speaker_count: int,
    base_timestamp: str,
    segment_start_s: float,
    segment_end_s: float,
) -> bool:
    """Check whether a multi-speaker conversation may be stored.

    Returns True if storage is permitted, False if it should be suppressed.

    Enforcement of it-consent-001 (T0): no persistent state about
    non-operator persons without an active consent contract.
    """
    if speaker_count <= 1:
        return True

    # Parse the recording timestamp and compute segment wall-clock times
    try:
        rec_start = datetime.fromisoformat(base_timestamp)
    except (ValueError, TypeError):
        log.warning("Cannot parse timestamp %r for consent check, suppressing", base_timestamp)
        return False

    seg_start = rec_start + timedelta(seconds=segment_start_s)
    seg_end = rec_start + timedelta(seconds=segment_end_s)

    # Heuristic 1: If the segment overlaps a calendar event, it's likely a work
    # call. Suppress entirely — this prevents both it-consent-001 (non-operator
    # PII) and mg-bridge-001 (work/home boundary) violations.
    if _overlaps_calendar_event(seg_start, seg_end):
        return False

    # Heuristic 2: Even without a calendar match, multi-speaker conversations
    # contain non-operator speech. The speakers are anonymous (SPEAKER_00 etc)
    # so we cannot check specific consent contracts. Without positive
    # identification, the safe default is to suppress.
    # This is conservative — false positives (suppressing the operator talking
    # to themselves across diarization splits) are acceptable; false negatives
    # (storing non-operator speech) are T0 violations.
    log.info(
        "Multi-speaker conversation (%d speakers) at %s — suppressing (it-consent-001)",
        speaker_count,
        seg_start.isoformat(),
    )
    return False


# ── Schemas ──────────────────────────────────────────────────────────────────


class WindowClassification(BaseModel):
    """Classification result for a single time window."""

    start: float
    end: float
    music_prob: float = 0.0
    speech_prob: float = 0.0
    instruments: dict[str, float] = Field(default_factory=dict)
    top_label: str = ""
    top_confidence: float = 0.0


class MusicRegion(BaseModel):
    """A contiguous region where music is detected."""

    start: float
    end: float
    instruments: dict[str, float] = Field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.end - self.start


class SpeechRegion(BaseModel):
    """A speech region from VAD, optionally near/during music."""

    start: float
    end: float
    transcript: str = ""
    speakers: list[str] = Field(default_factory=list)
    near_music: bool = False
    during_music: bool = False
    nearby_instruments: dict[str, float] = Field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.end - self.start


class ProcessedFileInfo(BaseModel):
    """State for a single processed raw file."""

    filename: str
    processed_at: float = 0.0
    speech_seconds: float = 0.0
    music_seconds: float = 0.0
    silence_seconds: float = 0.0
    segment_count: int = 0
    speaker_count: int = 0
    sample_sessions: int = 0
    vocal_notes: int = 0
    conversations: int = 0
    listening_logs: int = 0
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


def _format_time_short(seconds: float) -> str:
    """Format seconds as H:MM for display in document headings."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}:{m:02d}" if h > 0 else f"{m}m"


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
    return sorted(
        f
        for f in raw_dir.glob("rec-*.flac")
        if f.name not in state.processed_files and f.stat().st_size > 0
    )


def _extract_timestamp_from_filename(filename: str) -> str:
    """Extract ISO timestamp from rec-YYYYMMDD-HHMMSS.flac filename."""
    try:
        parts = filename.replace("rec-", "").replace(".flac", "")
        date_part, time_part = parts.split("-")
        return (
            f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
            f"T{time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}"
        )
    except (ValueError, IndexError):
        return datetime.now(UTC).isoformat()[:19]


def _offset_timestamp(base_iso: str, offset_seconds: float) -> str:
    """Add offset_seconds to a base ISO timestamp, return HH:MM."""
    try:
        base = datetime.fromisoformat(base_iso)
        adjusted = base.replace(
            hour=base.hour + int(offset_seconds // 3600),
            minute=base.minute + int((offset_seconds % 3600) // 60),
            second=base.second + int(offset_seconds % 60),
        )
        return adjusted.strftime("%H:%M")
    except (ValueError, OverflowError):
        return _format_timestamp(offset_seconds)[:5]


def _instruments_str(instruments: dict[str, float], top_n: int = 6) -> str:
    """Format instrument dict as a readable string, sorted by confidence."""
    sorted_inst = sorted(instruments.items(), key=lambda x: -x[1])[:top_n]
    return ", ".join(name for name, _ in sorted_inst)


# ── Audio Loading ─────────────────────────────────────────────────────────────


def _resample_to_16k(audio_path: Path) -> tuple[np.ndarray, int]:
    """Load and resample audio to 16kHz mono."""
    waveform, sr = torchaudio.load(str(audio_path))
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    if sr != 16000:
        waveform = torchaudio.functional.resample(waveform, sr, 16000)
    return waveform.squeeze(0).numpy(), 16000


def _compute_energy_db(waveform: np.ndarray, start: float, end: float, sr: int) -> float:
    """Compute average energy in dB for a segment."""
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
    tensor = torch.from_numpy(waveform)
    if tensor.dim() > 1:
        tensor = tensor.mean(dim=0)

    timestamps = silero_get_speech_timestamps(
        tensor,
        model,
        sampling_rate=sample_rate,
        return_seconds=False,
    )

    return [(ts["start"] / sample_rate, ts["end"] / sample_rate) for ts in timestamps]


# ── Full-Waveform Classification ─────────────────────────────────────────────

_AUDIOSET_LABELS: list[str] | None = None


def _get_audioset_labels() -> list[str]:
    """Get AudioSet class labels."""
    global _AUDIOSET_LABELS
    if _AUDIOSET_LABELS is None:
        try:
            import panns_inference

            labels_path = (
                Path(panns_inference.__file__).parent / "metadata" / "class_labels_indices.csv"
            )
            if labels_path.exists():
                _AUDIOSET_LABELS = []
                for line in labels_path.read_text().strip().split("\n")[1:]:
                    parts = line.split(",", 2)
                    if len(parts) >= 3:
                        _AUDIOSET_LABELS.append(parts[2].strip().strip('"'))
                return _AUDIOSET_LABELS
        except Exception:
            pass
        _AUDIOSET_LABELS = [f"class_{i}" for i in range(527)]
    return _AUDIOSET_LABELS


def _find_label_indices(labels: list[str], targets: list[str]) -> dict[str, int]:
    """Find indices for specific label names in the AudioSet label list."""
    result = {}
    for i, label in enumerate(labels):
        lower = label.lower()
        for target in targets:
            if target.lower() == lower:
                result[target] = i
    return result


def _classify_full_waveform(waveform: np.ndarray, sample_rate: int) -> list[WindowClassification]:
    """Run PANNs on sliding windows across the full waveform.

    Returns per-window classification with music/speech probabilities
    and detected instruments.
    """
    at = _load_panns_model()
    labels = _get_audioset_labels()

    # Find indices for music and speech classes
    key_indices = _find_label_indices(labels, ["Music", "Speech"])
    music_idx = key_indices.get("Music")
    speech_idx = key_indices.get("Speech")

    total_seconds = len(waveform) / sample_rate
    window_samples = int(WINDOW_SECONDS * sample_rate)
    hop_samples = int(HOP_SECONDS * sample_rate)

    results: list[WindowClassification] = []

    pos = 0
    while pos + window_samples <= len(waveform):
        start_s = pos / sample_rate
        end_s = min(start_s + WINDOW_SECONDS, total_seconds)
        chunk = waveform[pos : pos + window_samples]

        try:
            clipwise_output, _ = at.inference(chunk[np.newaxis, :])
        except RuntimeError:
            log.warning("PANNs failed on window %.1f-%.1f, skipping", start_s, end_s)
            pos += hop_samples
            continue

        probs = clipwise_output[0]

        # Music and speech probabilities
        music_p = float(probs[music_idx]) if music_idx is not None else 0.0
        speech_p = float(probs[speech_idx]) if speech_idx is not None else 0.0

        # Top label
        top_idx = int(np.argmax(probs))
        top_label = labels[top_idx] if top_idx < len(labels) else f"class_{top_idx}"
        top_conf = float(probs[top_idx])

        # Extract instrument probabilities
        instruments: dict[str, float] = {}
        for label_name, category in INSTRUMENT_MAP.items():
            for i, l in enumerate(labels):
                if l == label_name:
                    p = float(probs[i])
                    if p >= MIN_INSTRUMENT_PROB:
                        # Aggregate by category — keep max prob per category
                        if category not in instruments or p > instruments[category]:
                            instruments[category] = round(p, 3)
                    break

        wc = WindowClassification(
            start=start_s,
            end=end_s,
            music_prob=music_p,
            speech_prob=speech_p,
            instruments=instruments,
            top_label=top_label,
            top_confidence=top_conf,
        )
        results.append(wc)
        pos += hop_samples

    return results


# ── Region Detection ─────────────────────────────────────────────────────────


def _detect_music_regions(
    windows: list[WindowClassification], min_duration: float = 10.0
) -> list[MusicRegion]:
    """Merge adjacent windows with music detected into contiguous regions."""
    regions: list[MusicRegion] = []
    current_start: float | None = None
    current_end: float = 0.0
    agg_instruments: dict[str, float] = {}

    for w in windows:
        if w.music_prob >= MIN_MUSIC_PROB:
            if current_start is None:
                current_start = w.start
            current_end = w.end
            # Aggregate instruments (max prob)
            for inst, prob in w.instruments.items():
                if inst not in agg_instruments or prob > agg_instruments[inst]:
                    agg_instruments[inst] = prob
        else:
            if current_start is not None and (current_end - current_start) >= min_duration:
                regions.append(
                    MusicRegion(
                        start=current_start,
                        end=current_end,
                        instruments=dict(agg_instruments),
                    )
                )
            current_start = None
            agg_instruments = {}

    # Close trailing region
    if current_start is not None and (current_end - current_start) >= min_duration:
        regions.append(
            MusicRegion(
                start=current_start,
                end=current_end,
                instruments=dict(agg_instruments),
            )
        )

    return regions


def _instruments_for_time(
    windows: list[WindowClassification], start: float, end: float
) -> dict[str, float]:
    """Get aggregated instruments detected during a time range."""
    instruments: dict[str, float] = {}
    for w in windows:
        if w.end <= start or w.start >= end:
            continue
        for inst, prob in w.instruments.items():
            if inst not in instruments or prob > instruments[inst]:
                instruments[inst] = prob
    return instruments


def _build_instrument_timeline(
    windows: list[WindowClassification], start: float, end: float, resolution: float = 30.0
) -> list[tuple[float, float, list[str]]]:
    """Build an instrument timeline for a time range at the given resolution."""
    timeline: list[tuple[float, float, list[str]]] = []
    t = start
    while t < end:
        slot_end = min(t + resolution, end)
        instruments = _instruments_for_time(windows, t, slot_end)
        if instruments:
            sorted_inst = sorted(instruments.keys(), key=lambda k: -instruments[k])
            timeline.append((t, slot_end, sorted_inst))
        t = slot_end
    return timeline


def _classify_speech_regions(
    vad_segments: list[tuple[float, float]],
    music_regions: list[MusicRegion],
    windows: list[WindowClassification],
) -> list[SpeechRegion]:
    """Classify each VAD speech segment relative to music regions."""
    regions: list[SpeechRegion] = []

    for start, end in vad_segments:
        sr = SpeechRegion(start=start, end=end)

        # Check if this speech overlaps with any music region
        for mr in music_regions:
            if start < mr.end and end > mr.start:
                sr.during_music = True
                sr.near_music = True
                sr.nearby_instruments = mr.instruments
                break

        # If not during music, check proximity
        if not sr.during_music:
            for mr in music_regions:
                gap = min(abs(start - mr.end), abs(mr.start - end))
                if gap <= MUSIC_SPEECH_PROXIMITY:
                    sr.near_music = True
                    sr.nearby_instruments = mr.instruments
                    break

        # If not near any music region, check window instruments
        if not sr.nearby_instruments:
            sr.nearby_instruments = _instruments_for_time(windows, start, end)

        regions.append(sr)

    return regions


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
    """Run speaker diarization on an audio file."""
    pipeline = _load_diarization_pipeline()
    diarization = pipeline(audio_path)
    return [
        (turn.start, turn.end, speaker)
        for turn, _, speaker in diarization.itertracks(yield_label=True)
    ]


def _transcribe_segment(waveform: np.ndarray, sr: int, start: float, end: float) -> str:
    """Transcribe a segment of audio using faster-whisper."""
    import tempfile

    import soundfile

    model = _load_whisper_model()

    start_idx = int(start * sr)
    end_idx = int(end * sr)
    chunk = waveform[start_idx:end_idx]

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        soundfile.write(tmp_path, chunk, sr)
        segments, _info = model.transcribe(
            tmp_path,
            language="en",
            beam_size=5,
            no_speech_threshold=0.2,
            log_prob_threshold=-0.5,
            condition_on_previous_text=False,
        )
        text_parts = [seg.text.strip() for seg in segments]
        return " ".join(text_parts)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _diarize_segment(waveform: np.ndarray, sr: int, start: float, end: float) -> list[str]:
    """Diarize a segment and return unique speaker labels."""
    import tempfile

    import soundfile

    start_idx = int(start * sr)
    end_idx = int(end * sr)
    chunk = waveform[start_idx:end_idx]

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        soundfile.write(tmp_path, chunk, sr)
        diar_segments = _run_diarization(tmp_path)
        return list({s for _, _, s in diar_segments})
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ── RAG Output Formatting ────────────────────────────────────────────────────


def _format_sample_session(
    speech: SpeechRegion,
    base_timestamp: str,
    filename: str,
) -> str:
    """Format a speech-over-music annotation as a self-contained RAG document.

    Optimized for queries like "that horn stab I heard yesterday" or
    "the track with the bass line I wanted to sample."
    """
    inst = _instruments_str(speech.nearby_instruments)
    start_ts = _format_timestamp(speech.start)
    end_ts = _format_timestamp(speech.end)
    duration = int(speech.duration)
    time_display = _offset_timestamp(base_timestamp, speech.start)

    # Build detailed instrument list for sub-classification
    inst_detail = []
    for cat, prob in sorted(speech.nearby_instruments.items(), key=lambda x: -x[1]):
        inst_detail.append(f"{cat} ({prob:.0%})")
    inst_detail_str = ", ".join(inst_detail) if inst_detail else "unknown"

    return f"""---
source_service: ambient-audio
content_type: sample_session
timestamp: {base_timestamp}
duration_seconds: {duration}
instruments: [{inst}]
audio_source: {filename}
segment_start: "{start_ts}"
segment_end: "{end_ts}"
---

# Sample Note — {base_timestamp[:10]} {time_display}

While listening to a track featuring **{inst or "music"}**, I noted:

> {speech.transcript}

Instruments detected: {inst_detail_str}
"""


def _format_vocal_note(
    speech: SpeechRegion,
    base_timestamp: str,
    filename: str,
) -> str:
    """Format a spoken production note near music."""
    inst = _instruments_str(speech.nearby_instruments)
    start_ts = _format_timestamp(speech.start)
    end_ts = _format_timestamp(speech.end)
    duration = int(speech.duration)
    time_display = _offset_timestamp(base_timestamp, speech.start)

    context = f"during a session with **{inst}** nearby" if inst else "between tracks"

    return f"""---
source_service: ambient-audio
content_type: vocal_note
timestamp: {base_timestamp}
duration_seconds: {duration}
nearby_instruments: [{inst}]
audio_source: {filename}
segment_start: "{start_ts}"
segment_end: "{end_ts}"
---

# Production Note — {base_timestamp[:10]} {time_display}

{context.capitalize()}:

> {speech.transcript}
"""


def _format_conversation(
    speech_regions: list[SpeechRegion],
    base_timestamp: str,
    filename: str,
) -> str:
    """Format a multi-region conversation as a single RAG document."""
    all_speakers: set[str] = set()
    for sr in speech_regions:
        all_speakers.update(sr.speakers)

    start = speech_regions[0].start
    end = speech_regions[-1].end
    duration = int(end - start)
    speaker_count = len(all_speakers)
    start_ts = _format_timestamp(start)
    end_ts = _format_timestamp(end)
    time_display = _offset_timestamp(base_timestamp, start)
    speakers_yaml = "[" + ", ".join(sorted(all_speakers)) + "]" if all_speakers else "[]"

    mins = duration // 60
    secs = duration % 60
    dur_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"

    transcript_parts = []
    for sr in speech_regions:
        if sr.transcript:
            transcript_parts.append(sr.transcript)

    full_transcript = "\n\n".join(transcript_parts)

    return f"""---
source_service: ambient-audio
content_type: conversation
timestamp: {base_timestamp}
duration_seconds: {duration}
speakers: {speakers_yaml}
speaker_count: {speaker_count}
audio_source: {filename}
segment_start: "{start_ts}"
segment_end: "{end_ts}"
---

# Conversation — {base_timestamp[:10]} {time_display} ({dur_str}, {speaker_count} speaker{"s" if speaker_count != 1 else ""})

{full_transcript}
"""


def _format_listening_log(
    region: MusicRegion,
    annotations: list[SpeechRegion],
    windows: list[WindowClassification],
    base_timestamp: str,
    filename: str,
) -> str:
    """Format a sustained listening session with instrument timeline.

    Includes inline annotations if speech occurred during the session.
    """
    inst = _instruments_str(region.instruments)
    duration = int(region.duration)
    start_ts = _format_timestamp(region.start)
    end_ts = _format_timestamp(region.end)
    time_start = _offset_timestamp(base_timestamp, region.start)
    time_end = _offset_timestamp(base_timestamp, region.end)

    mins = duration // 60
    dur_str = f"{mins}-minute" if mins > 0 else f"{duration}-second"

    inst_yaml = (
        "["
        + ", ".join(sorted(region.instruments.keys(), key=lambda k: -region.instruments[k]))
        + "]"
    )

    # Build instrument timeline
    timeline = _build_instrument_timeline(windows, region.start, region.end, resolution=30.0)
    timeline_lines = []
    for t_start, t_end, instruments in timeline:
        t_s = _offset_timestamp(base_timestamp, t_start)
        t_e = _offset_timestamp(base_timestamp, t_end)
        timeline_lines.append(f"- {t_s}–{t_e}: {', '.join(instruments)}")

    timeline_block = "\n".join(timeline_lines) if timeline_lines else "- (no instrument detail)"

    # Inline annotations
    annotation_block = ""
    if annotations:
        ann_lines = []
        for ann in annotations:
            t = _offset_timestamp(base_timestamp, ann.start)
            ann_lines.append(f'- {t}: "{ann.transcript}"')
        annotation_block = "\n\n## Annotations During Session\n\n" + "\n".join(ann_lines)

    return f"""---
source_service: ambient-audio
content_type: listening_log
timestamp: {base_timestamp}
duration_seconds: {duration}
instruments: {inst_yaml}
audio_source: {filename}
segment_start: "{start_ts}"
segment_end: "{end_ts}"
---

# Listening Session — {base_timestamp[:10]} {time_start}–{time_end}

{dur_str} listening session featuring **{inst or "music"}**.

## Instrument Timeline

{timeline_block}
{annotation_block}
"""


# ── Profiler Integration ─────────────────────────────────────────────────────


def _generate_profile_facts(state: AudioProcessorState) -> list[dict]:
    """Generate deterministic profile facts from audio processing state."""
    facts: list[dict] = []
    source = "audio-processor:audio-profile-facts"

    if not state.processed_files:
        return facts

    total_speech = sum(f.speech_seconds for f in state.processed_files.values())
    total_music = sum(f.music_seconds for f in state.processed_files.values())
    total_samples = sum(f.sample_sessions for f in state.processed_files.values())
    total_notes = sum(f.vocal_notes for f in state.processed_files.values())
    total_listening = sum(f.listening_logs for f in state.processed_files.values())

    speech_h = total_speech / 3600
    music_h = total_music / 3600

    facts.append(
        {
            "dimension": "energy_and_attention",
            "key": "audio_daily_summary",
            "value": (
                f"{speech_h:.1f}h speech, {music_h:.1f}h music across "
                f"{len(state.processed_files)} recordings"
            ),
            "confidence": 0.95,
            "source": source,
            "evidence": (
                f"{total_samples} sample annotations, {total_notes} vocal notes, "
                f"{total_listening} listening sessions"
            ),
        }
    )

    if total_samples > 0:
        facts.append(
            {
                "dimension": "communication_patterns",
                "key": "sample_hunting_activity",
                "value": f"{total_samples} sample annotations recorded during listening sessions",
                "confidence": 0.90,
                "source": source,
                "evidence": f"Aggregated from {len(state.processed_files)} processed files",
            }
        )

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
    """Process a single raw FLAC file through the full pipeline.

    Pipeline:
    1. Load & resample to 16kHz
    2. Full-waveform PANNs classification (sliding windows)
    3. Detect music regions from classification timeline
    4. Run VAD to find speech boundaries
    5. Cross-reference speech with music regions
    6. Transcribe speech, diarize conversations
    7. Write RAG documents per category
    8. Delete raw FLAC
    """
    filename = audio_path.name
    base_timestamp = _extract_timestamp_from_filename(filename)

    log.info("Processing %s", filename)

    if not _check_vram_available():
        log.warning("Insufficient VRAM, deferring %s", filename)
        return None

    # 1. Load and resample
    try:
        waveform, sr = _resample_to_16k(audio_path)
    except Exception as exc:
        log.error("Failed to load %s: %s", filename, exc)
        return ProcessedFileInfo(filename=filename, error=str(exc), processed_at=time.time())

    total_seconds = len(waveform) / sr

    # 2. Full-waveform classification
    windows = _classify_full_waveform(waveform, sr)
    log.debug("Classified %d windows in %s", len(windows), filename)

    # 3. Detect music regions
    music_regions = _detect_music_regions(windows, min_duration=MIN_LISTENING_DURATION)
    music_seconds = sum(mr.duration for mr in music_regions)
    log.debug(
        "Found %d music regions (%.0fs total) in %s", len(music_regions), music_seconds, filename
    )

    # 4. VAD for speech
    vad_segments = _run_vad(waveform, sr)
    speech_seconds = sum(e - s for s, e in vad_segments)
    log.debug(
        "VAD found %d speech segments (%.0fs total) in %s",
        len(vad_segments),
        speech_seconds,
        filename,
    )

    if not music_regions and not vad_segments:
        log.info("No music or speech detected in %s — discarding", filename)
        return ProcessedFileInfo(
            filename=filename,
            processed_at=time.time(),
            silence_seconds=total_seconds,
        )

    # 5. Cross-reference speech with music
    speech_regions = _classify_speech_regions(vad_segments, music_regions, windows)

    # 6. Process and write RAG documents
    AUDIO_RAG_DIR.mkdir(parents=True, exist_ok=True)

    sample_sessions = 0
    vocal_notes = 0
    conversations = 0
    listening_logs = 0
    all_speakers: set[str] = set()

    # Track which speech regions are consumed by listening logs (avoid double-counting)
    consumed_speech: set[int] = set()

    # 6a. Listening logs (music sessions) — process first to embed annotations
    for mr in music_regions:
        if mr.duration < MIN_LISTENING_DURATION:
            continue

        # Find speech annotations during this music region
        annotations: list[SpeechRegion] = []
        for i, sr in enumerate(speech_regions):
            if sr.during_music and sr.start >= mr.start and sr.end <= mr.end:
                # Transcribe the annotation
                try:
                    sr.transcript = _transcribe_segment(waveform, 16000, sr.start, sr.end)
                except Exception as exc:
                    log.warning("Transcription failed for annotation at %.1f: %s", sr.start, exc)
                    sr.transcript = ""

                if sr.transcript and len(sr.transcript.split()) >= MIN_TRANSCRIPT_WORDS:
                    annotations.append(sr)
                    consumed_speech.add(i)
                    sample_sessions += 1

        md = _format_listening_log(mr, annotations, windows, base_timestamp, filename)
        start_tag = _format_timestamp(mr.start).replace(":", "")
        out_name = f"listening-{filename.replace('.flac', '')}-s{start_tag}.md"
        (AUDIO_RAG_DIR / out_name).write_text(md, encoding="utf-8")
        listening_logs += 1

        _log_change(
            "listening_log",
            f"{filename}:{_format_timestamp(mr.start)}",
            {
                "duration": round(mr.duration, 1),
                "instruments": list(mr.instruments.keys()),
                "annotations": len(annotations),
            },
        )

    # 6b. Sample sessions and vocal notes (speech near/during music, not already consumed)
    for i, sr in enumerate(speech_regions):
        if i in consumed_speech:
            continue
        if not (sr.during_music or sr.near_music):
            continue
        if sr.duration < MIN_SAMPLE_SESSION_SPEECH:
            continue

        # Transcribe
        try:
            sr.transcript = _transcribe_segment(waveform, 16000, sr.start, sr.end)
        except Exception as exc:
            log.warning("Transcription failed at %.1f: %s", sr.start, exc)
            continue

        if not sr.transcript or len(sr.transcript.split()) < MIN_TRANSCRIPT_WORDS:
            continue

        consumed_speech.add(i)

        if sr.during_music:
            md = _format_sample_session(sr, base_timestamp, filename)
            start_tag = _format_timestamp(sr.start).replace(":", "")
            out_name = f"sample-{filename.replace('.flac', '')}-s{start_tag}.md"
            (AUDIO_RAG_DIR / out_name).write_text(md, encoding="utf-8")
            sample_sessions += 1
            _log_change(
                "sample_session",
                f"{filename}:{_format_timestamp(sr.start)}",
                {
                    "duration": round(sr.duration, 1),
                    "instruments": list(sr.nearby_instruments.keys()),
                },
            )
        else:
            md = _format_vocal_note(sr, base_timestamp, filename)
            start_tag = _format_timestamp(sr.start).replace(":", "")
            out_name = f"note-{filename.replace('.flac', '')}-s{start_tag}.md"
            (AUDIO_RAG_DIR / out_name).write_text(md, encoding="utf-8")
            vocal_notes += 1
            _log_change(
                "vocal_note",
                f"{filename}:{_format_timestamp(sr.start)}",
                {
                    "duration": round(sr.duration, 1),
                },
            )

    # 6c. Conversations (standalone multi-speaker speech not near music)
    standalone_speech = [
        sr
        for i, sr in enumerate(speech_regions)
        if i not in consumed_speech and not sr.near_music and not sr.during_music
    ]

    # Merge adjacent standalone speech into conversations
    if standalone_speech:
        conversation_groups: list[list[SpeechRegion]] = []
        current_group: list[SpeechRegion] = [standalone_speech[0]]

        for sr in standalone_speech[1:]:
            if sr.start - current_group[-1].end <= 10.0:
                current_group.append(sr)
            else:
                conversation_groups.append(current_group)
                current_group = [sr]
        conversation_groups.append(current_group)

        for group in conversation_groups:
            total_dur = group[-1].end - group[0].start
            if total_dur < MIN_CONVERSATION_DURATION:
                continue

            # Transcribe and diarize
            for sr in group:
                try:
                    sr.transcript = _transcribe_segment(waveform, 16000, sr.start, sr.end)
                    sr.speakers = _diarize_segment(waveform, 16000, sr.start, sr.end)
                    all_speakers.update(sr.speakers)
                except Exception as exc:
                    log.warning("Conversation processing failed at %.1f: %s", sr.start, exc)

            # Only keep if we got meaningful content
            has_content = any(
                sr.transcript and len(sr.transcript.split()) >= MIN_TRANSCRIPT_WORDS for sr in group
            )
            if not has_content:
                continue

            # Consent gate (it-consent-001 T0): check whether multi-speaker
            # conversation may be stored. Suppresses work calls and
            # unconsented non-operator speech.
            group_speakers: set[str] = set()
            for sr in group:
                group_speakers.update(sr.speakers)
            if not _check_conversation_consent(
                speaker_count=len(group_speakers),
                base_timestamp=base_timestamp,
                segment_start_s=group[0].start,
                segment_end_s=group[-1].end,
            ):
                continue

            md = _format_conversation(group, base_timestamp, filename)
            start_tag = _format_timestamp(group[0].start).replace(":", "")
            out_name = f"conv-{filename.replace('.flac', '')}-s{start_tag}.md"
            (AUDIO_RAG_DIR / out_name).write_text(md, encoding="utf-8")
            conversations += 1
            _log_change(
                "conversation",
                f"{filename}:{_format_timestamp(group[0].start)}",
                {
                    "duration": round(total_dur, 1),
                    "speakers": len(group_speakers),
                },
            )

    segment_count = sample_sessions + vocal_notes + conversations + listening_logs

    info = ProcessedFileInfo(
        filename=filename,
        processed_at=time.time(),
        speech_seconds=speech_seconds,
        music_seconds=music_seconds,
        silence_seconds=max(0, total_seconds - speech_seconds - music_seconds),
        segment_count=segment_count,
        speaker_count=len(all_speakers),
        sample_sessions=sample_sessions,
        vocal_notes=vocal_notes,
        conversations=conversations,
        listening_logs=listening_logs,
    )
    log.info(
        "Processed %s: %d sample notes, %d vocal notes, %d conversations, %d listening logs",
        filename,
        sample_sessions,
        vocal_notes,
        conversations,
        listening_logs,
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

            # Delete raw FLAC after successful processing (no archival)
            if not info.error:
                try:
                    f.unlink()
                    log.info("Deleted processed raw file: %s", f.name)
                except OSError as exc:
                    log.warning("Failed to delete %s: %s", f.name, exc)

    state.last_run = time.time()
    _save_state(state)
    _write_profile_facts(state)

    if processed > 0:
        total_samples = sum(
            state.processed_files[f.name].sample_sessions
            for f in files[:processed]
            if f.name in state.processed_files
        )
        total_listening = sum(
            state.processed_files[f.name].listening_logs
            for f in files[:processed]
            if f.name in state.processed_files
        )
        msg = (
            f"Audio: {processed} files — "
            f"{total_samples} sample notes, {total_listening} listening logs"
        )
        send_notification("Audio Processor", msg, tags=["microphone"])

    return {"processed": processed, "skipped": skipped}


# ── Stats ────────────────────────────────────────────────────────────────────


def _print_stats(state: AudioProcessorState) -> None:
    """Print processing statistics."""
    total_speech = sum(f.speech_seconds for f in state.processed_files.values())
    total_music = sum(f.music_seconds for f in state.processed_files.values())
    total_samples = sum(f.sample_sessions for f in state.processed_files.values())
    total_notes = sum(f.vocal_notes for f in state.processed_files.values())
    total_convos = sum(f.conversations for f in state.processed_files.values())
    total_listening = sum(f.listening_logs for f in state.processed_files.values())
    errors = sum(1 for f in state.processed_files.values() if f.error)

    print("Audio Processor State")
    print("=" * 40)
    print(f"Processed files:  {len(state.processed_files):,}")
    print(f"Speech:           {total_speech / 3600:.1f}h")
    print(f"Music:            {total_music / 3600:.1f}h")
    print(f"Sample sessions:  {total_samples:,}")
    print(f"Vocal notes:      {total_notes:,}")
    print(f"Conversations:    {total_convos:,}")
    print(f"Listening logs:   {total_listening:,}")
    print(f"Errors:           {errors:,}")
    print(
        f"Last run:         {datetime.fromtimestamp(state.last_run, tz=UTC).strftime('%Y-%m-%d %H:%M UTC') if state.last_run else 'never'}"
    )


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ambient audio processor for sample-based hip hop production RAG pipeline"
    )
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
