"""av_correlator.py — Cross-modal audio/video correlation agent.

Correlates audio and video classifications over the same time windows to produce
joint retention decisions and a unified searchable moments index.

Two isolated pipelines exist:
  - Audio: 15-min FLAC segments in ~/audio-recording/archive/ with .md sidecars
  - Video: 5-min MKV segments in ~/video-recording/{role}/ with .classified JSON sidecars

This agent finds overlapping time windows, applies cross-modal value boosting rules,
updates both sidecars, triggers gdrive uploads for newly-valuable segments, and upserts
correlated moments to the studio_moments Qdrant collection.

Usage:
    uv run python -m agents.av_correlator --correlate   # Run correlation
    uv run python -m agents.av_correlator --stats       # Show stats
    uv run python -m agents.av_correlator --search QUERY  # Search moments
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass
from opentelemetry import trace

_tracer = trace.get_tracer(__name__)

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

AUDIO_ARCHIVE_DIR = Path.home() / "audio-recording" / "archive"
VIDEO_DIR = Path.home() / "video-recording"
CACHE_DIR = Path.home() / ".cache" / "av-correlator"
STATE_FILE = CACHE_DIR / "state.json"
CHANGES_LOG = CACHE_DIR / "changes.jsonl"

from shared.cameras import CAMERA_ROLES

# Audio segments are 15 minutes
AUDIO_SEGMENT_DURATION = timedelta(minutes=15)
# Video segments are 5 minutes
VIDEO_SEGMENT_DURATION = timedelta(minutes=5)

# Value threshold above which we trigger gdrive upload
UPLOAD_THRESHOLD = 0.5

# Maximum windows to process per run
MAX_WINDOWS_PER_RUN = 500

# ── Cross-Modal Boost Rules ──────────────────────────────────────────────────

# (audio_pattern, video_pattern) → (audio_boost, video_boost)
# Patterns match against classification strings
BOOST_RULES: list[tuple[str, str, float, float]] = [
    # Audio "production" + Video "person + high motion" → max value
    ("sample-session", "production_session", 1.0, 1.0),
    # Audio "conversation" + Video "multiple people"
    ("conversation", "conversation", 0.9, 0.9),
    # Audio "silence" + Video "empty_room" → confirm discard
    ("silence", "empty_room", 0.0, 0.0),
    # Audio music/speech + Video person → boost video
    ("sample-session", "active_work", 1.0, 0.8),
    ("sample-session", "idle_occupied", 1.0, 0.7),
    ("vocal-note", "production_session", 0.8, 1.0),
    ("vocal-note", "active_work", 0.7, 0.7),
    ("vocal-note", "idle_occupied", 0.6, 0.6),
    ("listening-log", "production_session", 0.7, 1.0),
    ("listening-log", "active_work", 0.6, 0.7),
    ("listening-log", "idle_occupied", 0.5, 0.5),
    ("conversation", "active_work", 0.8, 0.7),
    ("conversation", "idle_occupied", 0.7, 0.6),
    # Any audio with speech/music + person visible → boost video
    ("sample-session", "conversation", 1.0, 0.9),
    ("vocal-note", "conversation", 0.8, 0.9),
    ("listening-log", "conversation", 0.7, 0.8),
]


# ── Schemas ──────────────────────────────────────────────────────────────────


class AudioSidecar(BaseModel):
    """Parsed audio sidecar metadata."""

    filename: str = ""
    path: Path = Path()
    value_score: float = 0.0
    dominant_classification: str = "silence"
    speech_seconds: float = 0.0
    music_seconds: float = 0.0
    silence_seconds: float = 0.0
    segment_count: int = 0
    speaker_count: int = 0
    sample_sessions: int = 0
    vocal_notes: int = 0
    conversations: int = 0
    listening_logs: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class VideoSidecar(BaseModel):
    """Parsed video sidecar metadata."""

    filename: str = ""
    path: Path = Path()
    role: str = ""
    category: str = "empty_room"
    value_score: float = 0.0
    people_count: int = 0
    max_people: int = 0
    motion_score: float = 0.0
    scene_change: bool = False
    ssim: float = 1.0
    disposition: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CorrelationWindow(BaseModel):
    """A correlated time window (~5 min) with audio+video data."""

    window_id: str = ""
    window_start: datetime = Field(default_factory=lambda: datetime.now(UTC))
    window_end: datetime = Field(default_factory=lambda: datetime.now(UTC))
    audio_file: str = ""
    audio_sidecar_path: str = ""
    video_files: dict[str, str] = Field(default_factory=dict)  # role → filename
    audio_classification: str = "silence"
    audio_score: float = 0.0
    video_classifications: dict[str, str] = Field(default_factory=dict)  # role → category
    video_scores: dict[str, float] = Field(default_factory=dict)  # role → score
    video_people: dict[str, int] = Field(default_factory=dict)  # role → people_count
    video_motion: dict[str, float] = Field(default_factory=dict)  # role → motion_score
    joint_category: str = ""
    joint_score: float = 0.0
    boosted_audio_score: float = 0.0
    boosted_video_scores: dict[str, float] = Field(default_factory=dict)
    speech_seconds: float = 0.0
    music_seconds: float = 0.0
    transcript_snippet: str = ""
    speaker_count: int = 0
    max_people: dict[str, int] = Field(default_factory=dict)  # role → max people
    scene_changes: dict[str, bool] = Field(default_factory=dict)  # role → scene changed
    correlated_at: float = 0.0


class CorrelatorState(BaseModel):
    """Persistent correlator state."""

    processed_windows: dict[str, CorrelationWindow] = Field(default_factory=dict)
    last_run: float = 0.0
    stats: dict[str, int] = Field(default_factory=dict)


# ── State Persistence ────────────────────────────────────────────────────────


def _load_state() -> CorrelatorState:
    """Load processing state from disk."""
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return CorrelatorState(**data)
        except (json.JSONDecodeError, Exception) as exc:
            log.warning("Failed to load state: %s", exc)
    return CorrelatorState()


def _save_state(state: CorrelatorState) -> None:
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


# ── Timestamp Parsing ────────────────────────────────────────────────────────

# Audio: rec-YYYYMMDD-HHMMSS.flac
_AUDIO_TS_RE = re.compile(r"rec-(\d{8})-(\d{6})")
# Video: {role}_YYYYMMDD-HHMMSS_{seq}.mkv
_VIDEO_TS_RE = re.compile(r"_(\d{8})-(\d{6})_")


def _parse_audio_timestamp(filename: str) -> datetime | None:
    """Parse timestamp from audio filename like rec-20260316-121050.flac."""
    m = _AUDIO_TS_RE.search(filename)
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)}{m.group(2)}", "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def _parse_video_timestamp(filename: str) -> datetime | None:
    """Parse timestamp from video filename like brio-operator_20260316-121050_0107.mkv."""
    m = _VIDEO_TS_RE.search(filename)
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)}{m.group(2)}", "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def _deterministic_uuid(timestamp: datetime) -> str:
    """Generate a deterministic UUID from a timestamp for idempotent Qdrant upserts."""
    ts_str = timestamp.isoformat()
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"studio-moment:{ts_str}"))


# ── Sidecar Parsing ──────────────────────────────────────────────────────────


def _parse_audio_sidecar(sidecar_path: Path) -> AudioSidecar | None:
    """Parse a YAML-frontmatter .md sidecar for an audio segment."""
    try:
        text = sidecar_path.read_text(encoding="utf-8")
    except OSError as exc:
        log.debug("Cannot read audio sidecar %s: %s", sidecar_path, exc)
        return None

    # Extract YAML frontmatter between --- delimiters
    parts = text.split("---", 2)
    if len(parts) < 3:
        log.debug("No YAML frontmatter in %s", sidecar_path)
        return None

    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        log.debug("YAML parse error in %s: %s", sidecar_path, exc)
        return None

    if not isinstance(data, dict):
        return None

    filename = data.get("source_file", sidecar_path.stem)
    ts = _parse_audio_timestamp(str(filename))

    return AudioSidecar(
        filename=str(filename),
        path=sidecar_path,
        value_score=float(data.get("value_score", 0.0)),
        dominant_classification=data.get("dominant_classification", "silence"),
        speech_seconds=float(data.get("speech_seconds", 0.0)),
        music_seconds=float(data.get("music_seconds", 0.0)),
        silence_seconds=float(data.get("silence_seconds", 0.0)),
        segment_count=int(data.get("segment_count", 0)),
        speaker_count=int(data.get("speaker_count", 0)),
        sample_sessions=int(data.get("sample_sessions", 0)),
        vocal_notes=int(data.get("vocal_notes", 0)),
        conversations=int(data.get("conversations", 0)),
        listening_logs=int(data.get("listening_logs", 0)),
        timestamp=ts or datetime.now(UTC),
    )


def _parse_video_sidecar(sidecar_path: Path) -> VideoSidecar | None:
    """Parse a .classified JSON sidecar for a video segment."""
    try:
        data = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.debug("Cannot read video sidecar %s: %s", sidecar_path, exc)
        return None

    if not isinstance(data, dict):
        return None

    filename = data.get("filename", sidecar_path.stem)
    role = sidecar_path.parent.name
    ts = _parse_video_timestamp(str(filename))

    return VideoSidecar(
        filename=str(filename),
        path=sidecar_path,
        role=role,
        category=data.get("category", "empty_room"),
        value_score=float(data.get("value_score", 0.0)),
        people_count=int(data.get("people_count", 0)),
        max_people=int(data.get("max_people", 0)),
        motion_score=float(data.get("motion_score", 0.0)),
        scene_change=bool(data.get("scene_change", False)),
        ssim=float(data.get("ssim", 1.0)),
        disposition=data.get("disposition", ""),
        timestamp=ts or datetime.now(UTC),
    )


# ── Discovery ────────────────────────────────────────────────────────────────


def _discover_audio_sidecars() -> list[AudioSidecar]:
    """Find all audio sidecars in the archive directory."""
    sidecars: list[AudioSidecar] = []
    if not AUDIO_ARCHIVE_DIR.is_dir():
        return sidecars
    for md_path in AUDIO_ARCHIVE_DIR.glob("*.md"):
        sidecar = _parse_audio_sidecar(md_path)
        if sidecar:
            sidecars.append(sidecar)
    return sorted(sidecars, key=lambda s: s.timestamp)


def _discover_video_sidecars() -> dict[str, list[VideoSidecar]]:
    """Find all video sidecars, grouped by camera role."""
    by_role: dict[str, list[VideoSidecar]] = {}
    for role in CAMERA_ROLES:
        role_dir = VIDEO_DIR / role
        if not role_dir.is_dir():
            continue
        role_sidecars: list[VideoSidecar] = []
        for suffix in ("*.classified", "*.processed"):
            for sidecar_path in role_dir.glob(suffix):
                sidecar = _parse_video_sidecar(sidecar_path)
                if sidecar:
                    role_sidecars.append(sidecar)
        by_role[role] = sorted(role_sidecars, key=lambda s: s.timestamp)
    return by_role


# ── Temporal Alignment ───────────────────────────────────────────────────────


def _find_overlapping_video(
    window_start: datetime,
    window_end: datetime,
    video_by_role: dict[str, list[VideoSidecar]],
) -> dict[str, VideoSidecar]:
    """Find video sidecars overlapping a given time window, one per role."""
    result: dict[str, VideoSidecar] = {}
    for role, sidecars in video_by_role.items():
        for vs in sidecars:
            vs_start = vs.timestamp
            vs_end = vs_start + VIDEO_SEGMENT_DURATION
            # Check overlap
            if vs_start < window_end and vs_end > window_start:
                # Take the one with the most overlap or the first match
                if role not in result:
                    result[role] = vs
    return result


def _build_correlation_windows(
    audio_sidecars: list[AudioSidecar],
    video_by_role: dict[str, list[VideoSidecar]],
    state: CorrelatorState,
) -> list[tuple[datetime, datetime, AudioSidecar, dict[str, VideoSidecar]]]:
    """Build correlation windows by slicing audio segments into 5-min windows.

    Each 15-min audio segment produces up to 3 windows (at 5-min intervals),
    each aligned with the video segment duration.
    """
    windows: list[tuple[datetime, datetime, AudioSidecar, dict[str, VideoSidecar]]] = []

    for audio in audio_sidecars:
        audio_start = audio.timestamp
        # Slice into 5-minute windows to match video granularity
        for offset_min in range(0, 15, 5):
            window_start = audio_start + timedelta(minutes=offset_min)
            window_end = window_start + VIDEO_SEGMENT_DURATION

            # Skip already-processed windows
            window_id = _deterministic_uuid(window_start)
            if window_id in state.processed_windows:
                continue

            # Find overlapping video
            overlapping = _find_overlapping_video(window_start, window_end, video_by_role)

            # Only create windows where we have at least one video segment
            if overlapping:
                windows.append((window_start, window_end, audio, overlapping))

    return windows


# ── Cross-Modal Boosting ─────────────────────────────────────────────────────


def _apply_boost_rules(
    audio_classification: str,
    audio_score: float,
    video_sidecars: dict[str, VideoSidecar],
) -> tuple[float, dict[str, float], str]:
    """Apply cross-modal boost rules.

    Returns (boosted_audio_score, {role: boosted_video_score}, joint_category).
    """
    boosted_audio = audio_score
    boosted_video: dict[str, float] = {}
    joint_categories: list[str] = []

    for role, vs in video_sidecars.items():
        best_audio_boost = audio_score
        best_video_boost = vs.value_score

        for audio_pattern, video_pattern, a_boost, v_boost in BOOST_RULES:
            if audio_classification == audio_pattern and vs.category == video_pattern:
                best_audio_boost = max(best_audio_boost, a_boost)
                best_video_boost = max(best_video_boost, v_boost)
                joint_categories.append(f"{audio_pattern}+{video_pattern}")
                break

        # Special rule: any audio with speech/music + person visible → boost video
        if (
            audio_classification not in ("silence",)
            and vs.category in ("idle_occupied", "active_work")
            and vs.people_count >= 1
        ):
            best_video_boost = max(best_video_boost, 0.6)

        boosted_audio = max(boosted_audio, best_audio_boost)
        boosted_video[role] = round(min(1.0, best_video_boost), 3)

    boosted_audio = round(min(1.0, boosted_audio), 3)
    joint_category = joint_categories[0] if joint_categories else f"{audio_classification}+mixed"

    return boosted_audio, boosted_video, joint_category


# ── Sidecar Updates ──────────────────────────────────────────────────────────


def _update_audio_sidecar(sidecar_path: Path, new_score: float) -> bool:
    """Update the value_score in an audio .md sidecar's YAML frontmatter."""
    try:
        text = sidecar_path.read_text(encoding="utf-8")
    except OSError:
        return False

    parts = text.split("---", 2)
    if len(parts) < 3:
        return False

    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return False

    if not isinstance(data, dict):
        return False

    old_score = data.get("value_score", 0.0)
    if abs(float(old_score) - new_score) < 0.001:
        return False  # No change needed

    data["value_score"] = round(new_score, 3)
    data["av_correlated"] = True
    data["av_correlated_at"] = datetime.now(UTC).isoformat()

    new_frontmatter = yaml.dump(data, default_flow_style=False, sort_keys=False)
    new_text = f"---\n{new_frontmatter}---{parts[2]}"
    sidecar_path.write_text(new_text, encoding="utf-8")
    log.info("Updated audio sidecar %s: %.3f → %.3f", sidecar_path.name, old_score, new_score)
    return True


def _update_video_sidecar(sidecar_path: Path, new_score: float) -> bool:
    """Update the value_score in a video .classified JSON sidecar."""
    try:
        data = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    old_score = data.get("value_score", 0.0)
    if abs(float(old_score) - new_score) < 0.001:
        return False

    data["value_score"] = round(new_score, 3)
    data["av_correlated"] = True
    data["av_correlated_at"] = datetime.now(UTC).isoformat()

    sidecar_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    log.info("Updated video sidecar %s: %.3f → %.3f", sidecar_path.name, old_score, new_score)
    return True


# ── Upload & Retention ───────────────────────────────────────────────────────


def _trigger_video_upload(video_path: Path, role: str) -> bool:
    """Upload a video segment to gdrive via rclone and create .processed marker."""
    ts = _parse_video_timestamp(video_path.name)
    date_str = ts.strftime("%Y-%m-%d") if ts else datetime.now(UTC).strftime("%Y-%m-%d")
    remote_path = f"gdrive:video-archive/{role}/{date_str}/"

    log.info("Triggering upload: %s → %s", video_path.name, remote_path)

    try:
        result = subprocess.run(
            ["rclone", "copy", str(video_path), remote_path, "--no-traverse"],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode == 0:
            # Create .processed marker
            marker = video_path.with_suffix(video_path.suffix + ".processed")
            marker.write_text(
                json.dumps(
                    {
                        "uploaded_at": datetime.now(UTC).isoformat(),
                        "reason": "av_correlation_boost",
                        "remote_path": f"{remote_path}{video_path.name}",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            log.info("Upload complete + .processed marker: %s", video_path.name)
            return True
        else:
            log.error(
                "rclone failed for %s (rc=%d): %s",
                video_path.name,
                result.returncode,
                result.stderr[-500:] if result.stderr else "",
            )
    except subprocess.TimeoutExpired:
        log.error("rclone timed out for %s", video_path.name)
    except (FileNotFoundError, OSError) as exc:
        log.error("rclone error for %s: %s", video_path.name, exc)
    return False


def _maybe_upload_boosted_video(
    video_sidecar: VideoSidecar,
    old_score: float,
    new_score: float,
) -> bool:
    """Upload a video segment if its score was boosted above the upload threshold."""
    if old_score >= UPLOAD_THRESHOLD:
        return False  # Already would have been uploaded
    if new_score < UPLOAD_THRESHOLD:
        return False  # Still below threshold

    video_path = video_sidecar.path.parent / video_sidecar.filename
    if not video_path.exists():
        log.warning("Video file missing for upload: %s", video_path)
        return False

    return _trigger_video_upload(video_path, video_sidecar.role)


# ── Qdrant Indexing ──────────────────────────────────────────────────────────


def _ensure_collection() -> None:
    """Create the studio_moments Qdrant collection if it doesn't exist."""
    from qdrant_client.models import Distance, VectorParams

    from shared.config import EXPECTED_EMBED_DIMENSIONS, STUDIO_MOMENTS_COLLECTION, get_qdrant

    client = get_qdrant()
    collections = [c.name for c in client.get_collections().collections]
    if STUDIO_MOMENTS_COLLECTION not in collections:
        client.create_collection(
            collection_name=STUDIO_MOMENTS_COLLECTION,
            vectors_config=VectorParams(
                size=EXPECTED_EMBED_DIMENSIONS,
                distance=Distance.COSINE,
            ),
        )
        log.info(
            "Created Qdrant collection '%s' (%d-dim, cosine)",
            STUDIO_MOMENTS_COLLECTION,
            EXPECTED_EMBED_DIMENSIONS,
        )


def _build_summary_text(window: CorrelationWindow) -> str:
    """Build a text summary for embedding from a correlation window."""
    parts = [
        f"Studio moment at {window.window_start.strftime('%Y-%m-%d %H:%M')}.",
        f"Audio: {window.audio_classification}",
    ]
    if window.speech_seconds > 0:
        parts.append(f"({window.speech_seconds:.0f}s speech)")
    if window.music_seconds > 0:
        parts.append(f"({window.music_seconds:.0f}s music)")

    for role, cat in window.video_classifications.items():
        people = window.video_people.get(role, 0)
        motion = window.video_motion.get(role, 0.0)
        parts.append(f"Camera {role}: {cat} (people={people}, motion={motion:.2f})")

    if window.speaker_count > 1:
        parts.append(f"{window.speaker_count} speakers")
    for role, changed in window.scene_changes.items():
        if changed:
            parts.append(f"scene-change:{role}")

    parts.append(f"Joint: {window.joint_category} (score={window.joint_score:.2f})")

    if window.transcript_snippet:
        parts.append(f"Transcript: {window.transcript_snippet[:200]}")

    return " ".join(parts)


def _upsert_moment(window: CorrelationWindow) -> bool:
    """Upsert a correlated moment to the studio_moments Qdrant collection."""
    from shared.config import STUDIO_MOMENTS_COLLECTION, embed_safe, get_qdrant

    summary = _build_summary_text(window)
    vector = embed_safe(summary, prefix="search_document")
    if vector is None:
        log.warning("Embedding unavailable, skipping Qdrant upsert for %s", window.window_id)
        return False

    payload = {
        "window_id": window.window_id,
        "window_start": window.window_start.isoformat(),
        "window_end": window.window_end.isoformat(),
        "audio_file": window.audio_file,
        "audio_classification": window.audio_classification,
        "audio_score": window.boosted_audio_score,
        "video_files": window.video_files,
        "video_classifications": window.video_classifications,
        "video_scores": window.boosted_video_scores,
        "video_people": window.video_people,
        "video_motion": window.video_motion,
        "joint_category": window.joint_category,
        "joint_score": window.joint_score,
        "speech_seconds": window.speech_seconds,
        "music_seconds": window.music_seconds,
        "transcript_snippet": window.transcript_snippet[:500] if window.transcript_snippet else "",
        "correlated_at": window.correlated_at,
    }

    try:
        from qdrant_client.models import PointStruct

        client = get_qdrant()
        client.upsert(
            collection_name=STUDIO_MOMENTS_COLLECTION,
            points=[
                PointStruct(
                    id=window.window_id,
                    vector=vector,
                    payload=payload,
                )
            ],
        )
        return True
    except Exception as exc:
        log.error("Qdrant upsert failed for %s: %s", window.window_id, exc)
        return False


# ── Transcript Extraction ────────────────────────────────────────────────────


def _extract_transcript_snippet(audio_sidecar: AudioSidecar) -> str:
    """Try to extract a transcript snippet from the RAG document for this audio."""
    rag_dir = Path.home() / "documents" / "rag-sources" / "audio"
    if not rag_dir.is_dir():
        return ""

    # Look for a RAG document matching the audio filename
    stem = Path(audio_sidecar.filename).stem
    for md_path in rag_dir.glob(f"{stem}*.md"):
        try:
            text = md_path.read_text(encoding="utf-8")
            # Extract text after frontmatter
            parts = text.split("---", 2)
            body = parts[2] if len(parts) >= 3 else text
            # Find transcript sections
            lines = [
                line.strip()
                for line in body.split("\n")
                if line.strip() and not line.startswith("#")
            ]
            if lines:
                return " ".join(lines[:5])[:300]
        except OSError:
            continue
    return ""


# ── Main Correlation Pipeline ────────────────────────────────────────────────


def _correlate_window(
    window_start: datetime,
    window_end: datetime,
    audio: AudioSidecar,
    video_sidecars: dict[str, VideoSidecar],
) -> CorrelationWindow:
    """Correlate a single time window and apply boost rules."""
    window_id = _deterministic_uuid(window_start)

    # Apply boost rules
    boosted_audio, boosted_video, joint_category = _apply_boost_rules(
        audio.dominant_classification,
        audio.value_score,
        video_sidecars,
    )

    # Joint score = weighted max of boosted scores
    all_scores = [boosted_audio] + list(boosted_video.values())
    joint_score = round(max(all_scores) if all_scores else 0.0, 3)

    # Scale speech/music to this 5-min window (audio is 15 min)
    window_fraction = 5.0 / 15.0
    speech_in_window = round(audio.speech_seconds * window_fraction, 1)
    music_in_window = round(audio.music_seconds * window_fraction, 1)

    transcript = _extract_transcript_snippet(audio)

    return CorrelationWindow(
        window_id=window_id,
        window_start=window_start,
        window_end=window_end,
        audio_file=audio.filename,
        audio_sidecar_path=str(audio.path),
        video_files={role: vs.filename for role, vs in video_sidecars.items()},
        audio_classification=audio.dominant_classification,
        audio_score=audio.value_score,
        video_classifications={role: vs.category for role, vs in video_sidecars.items()},
        video_scores={role: vs.value_score for role, vs in video_sidecars.items()},
        video_people={role: vs.people_count for role, vs in video_sidecars.items()},
        video_motion={role: round(vs.motion_score, 4) for role, vs in video_sidecars.items()},
        joint_category=joint_category,
        joint_score=joint_score,
        boosted_audio_score=boosted_audio,
        boosted_video_scores=boosted_video,
        speech_seconds=speech_in_window,
        music_seconds=music_in_window,
        transcript_snippet=transcript,
        speaker_count=audio.speaker_count,
        max_people={role: vs.max_people for role, vs in video_sidecars.items()},
        scene_changes={role: vs.scene_change for role, vs in video_sidecars.items()},
        correlated_at=time.time(),
    )


def _run_correlation(state: CorrelatorState) -> dict[str, int]:
    """Run the full correlation pipeline."""
    from shared.notify import send_notification

    log.info("Discovering audio sidecars...")
    audio_sidecars = _discover_audio_sidecars()
    log.info("Found %d audio sidecars", len(audio_sidecars))

    log.info("Discovering video sidecars...")
    video_by_role = _discover_video_sidecars()
    total_video = sum(len(v) for v in video_by_role.values())
    log.info("Found %d video sidecars across %d roles", total_video, len(video_by_role))

    if not audio_sidecars or not video_by_role:
        log.info("Not enough data for correlation")
        return {"windows": 0, "boosted_audio": 0, "boosted_video": 0, "uploads": 0, "indexed": 0}

    # Build correlation windows
    windows = _build_correlation_windows(audio_sidecars, video_by_role, state)
    log.info("Found %d new correlation windows", len(windows))

    if not windows:
        return {"windows": 0, "boosted_audio": 0, "boosted_video": 0, "uploads": 0, "indexed": 0}

    # Cap per run
    if len(windows) > MAX_WINDOWS_PER_RUN:
        log.info("Capping to %d windows", MAX_WINDOWS_PER_RUN)
        windows = windows[:MAX_WINDOWS_PER_RUN]

    # Ensure Qdrant collection exists
    try:
        _ensure_collection()
    except Exception as exc:
        log.warning("Could not ensure Qdrant collection: %s", exc)

    correlated = 0
    boosted_audio_count = 0
    boosted_video_count = 0
    upload_count = 0
    indexed_count = 0

    for window_start, window_end, audio, video_sidecars_map in windows:
        try:
            window = _correlate_window(window_start, window_end, audio, video_sidecars_map)

            # Update audio sidecar if score boosted
            if window.boosted_audio_score > audio.value_score + 0.001:
                if _update_audio_sidecar(audio.path, window.boosted_audio_score):
                    boosted_audio_count += 1
                    _log_change(
                        "audio_boosted",
                        audio.filename,
                        {
                            "old_score": audio.value_score,
                            "new_score": window.boosted_audio_score,
                            "reason": window.joint_category,
                        },
                    )

            # Update video sidecars and trigger uploads
            for role, vs in video_sidecars_map.items():
                new_video_score = window.boosted_video_scores.get(role, vs.value_score)
                if new_video_score > vs.value_score + 0.001:
                    if _update_video_sidecar(vs.path, new_video_score):
                        boosted_video_count += 1
                        _log_change(
                            "video_boosted",
                            f"{role}/{vs.filename}",
                            {
                                "old_score": vs.value_score,
                                "new_score": new_video_score,
                                "reason": window.joint_category,
                            },
                        )
                    # Trigger upload if newly above threshold
                    if _maybe_upload_boosted_video(vs, vs.value_score, new_video_score):
                        upload_count += 1
                        _log_change(
                            "video_upload_triggered",
                            f"{role}/{vs.filename}",
                            {
                                "old_score": vs.value_score,
                                "new_score": new_video_score,
                                "reason": "av_correlation_boost",
                            },
                        )

            # Upsert to Qdrant
            if _upsert_moment(window):
                indexed_count += 1

            state.processed_windows[window.window_id] = window
            correlated += 1

        except Exception as exc:
            log.error(
                "Error correlating window %s: %s",
                window_start.isoformat(),
                exc,
                exc_info=True,
            )
            _log_change(
                "correlation_error",
                window_start.isoformat(),
                {"error": str(exc)[:500]},
            )

    state.last_run = time.time()
    state.stats = {
        "last_windows": correlated,
        "last_boosted_audio": boosted_audio_count,
        "last_boosted_video": boosted_video_count,
        "last_uploads": upload_count,
        "last_indexed": indexed_count,
        "total_windows": len(state.processed_windows),
    }
    _save_state(state)

    summary = {
        "windows": correlated,
        "boosted_audio": boosted_audio_count,
        "boosted_video": boosted_video_count,
        "uploads": upload_count,
        "indexed": indexed_count,
    }

    if correlated > 0:
        msg = (
            f"AV Correlator: {correlated} windows — "
            f"{boosted_audio_count} audio boosted, "
            f"{boosted_video_count} video boosted, "
            f"{upload_count} uploads, "
            f"{indexed_count} indexed"
        )
        send_notification("AV Correlator", msg, tags=["link"])

    return summary


# ── Search ───────────────────────────────────────────────────────────────────


def _search_moments(query: str, limit: int = 10) -> None:
    """Search the studio_moments Qdrant collection with a natural language query."""
    from shared.config import STUDIO_MOMENTS_COLLECTION, embed, get_qdrant

    try:
        _ensure_collection()
    except Exception as exc:
        print(f"Could not connect to Qdrant: {exc}")
        return

    try:
        vector = embed(query, prefix="search_query")
    except RuntimeError as exc:
        print(f"Embedding failed: {exc}")
        return

    client = get_qdrant()
    results = client.query_points(
        collection_name=STUDIO_MOMENTS_COLLECTION,
        query=vector,
        limit=limit,
        with_payload=True,
    )

    if not results.points:
        print("No moments found.")
        return

    print(f"Found {len(results.points)} moments:\n")
    for point in results.points:
        p = point.payload or {}
        score = point.score
        ts = p.get("window_start", "?")
        joint = p.get("joint_category", "?")
        joint_score = p.get("joint_score", 0)
        audio_cls = p.get("audio_classification", "?")
        video_cls = p.get("video_classifications", {})
        people = p.get("video_people", {})
        transcript = p.get("transcript_snippet", "")

        print(f"  [{score:.3f}] {ts}  {joint} (score={joint_score:.2f})")
        print(f"          Audio: {audio_cls}")
        for role, cat in video_cls.items():
            p_count = people.get(role, 0)
            print(f"          {role}: {cat} (people={p_count})")
        if transcript:
            print(f"          Transcript: {transcript[:100]}...")
        print()


# ── Stats ────────────────────────────────────────────────────────────────────


def _print_stats(state: CorrelatorState) -> None:
    """Print correlation statistics."""
    total = len(state.processed_windows)
    by_joint: dict[str, int] = {}
    by_audio: dict[str, int] = {}
    score_sum = 0.0

    for w in state.processed_windows.values():
        by_joint[w.joint_category] = by_joint.get(w.joint_category, 0) + 1
        by_audio[w.audio_classification] = by_audio.get(w.audio_classification, 0) + 1
        score_sum += w.joint_score

    print("AV Correlator State")
    print("=" * 50)
    print(f"Total windows:    {total:,}")
    print(f"Avg joint score:  {score_sum / total:.3f}" if total > 0 else "Avg joint score:  N/A")
    print(
        f"Last run:         "
        f"{datetime.fromtimestamp(state.last_run, tz=UTC).strftime('%Y-%m-%d %H:%M UTC') if state.last_run else 'never'}"
    )
    print()

    if state.stats:
        print("Last Run Stats:")
        for k, v in sorted(state.stats.items()):
            print(f"  {k:25s} {v:>6}")
        print()

    if by_joint:
        print("By Joint Category:")
        for cat in sorted(by_joint, key=by_joint.get, reverse=True):  # type: ignore[arg-type]
            print(f"  {cat:40s} {by_joint[cat]:>6,}")
        print()

    if by_audio:
        print("By Audio Classification:")
        for cat in sorted(by_audio, key=by_audio.get, reverse=True):  # type: ignore[arg-type]
            print(f"  {cat:25s} {by_audio[cat]:>6,}")

    # Qdrant collection stats
    try:
        from shared.config import STUDIO_MOMENTS_COLLECTION, get_qdrant

        client = get_qdrant()
        info = client.get_collection(STUDIO_MOMENTS_COLLECTION)
        print(f"\nQdrant '{STUDIO_MOMENTS_COLLECTION}': {info.points_count:,} points")
    except Exception:
        pass


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-modal audio/video correlation agent")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--correlate", action="store_true", help="Run correlation pipeline")
    group.add_argument("--stats", action="store_true", help="Show correlation stats")
    group.add_argument("--search", type=str, metavar="QUERY", help="Search moments index")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    from shared.log_setup import configure_logging

    configure_logging(agent="av-correlator", level="DEBUG" if args.verbose else None)

    action = "correlate" if args.correlate else "search" if args.search else "stats"
    with _tracer.start_as_current_span(
        f"av_correlator.{action}",
        attributes={"agent.name": "av_correlator", "agent.repo": "hapax-council"},
    ):
        if args.correlate:
            state = _load_state()
            summary = _run_correlation(state)
            log.info("Correlation complete: %s", summary)
        elif args.search:
            _search_moments(args.search)
        elif args.stats:
            state = _load_state()
            if not state.processed_windows:
                print("No correlation state found. Run --correlate first.")
                return
            _print_stats(state)


if __name__ == "__main__":
    main()
