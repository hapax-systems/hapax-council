"""video_processor.py — Video segment classification and retention pipeline.

Optimized for a hip hop producer's multi-camera studio setup. Processes 5-minute
MKV segments from continuous recording cameras through lightweight CPU-only
classification, deciding which segments to archive to Google Drive and which
to discard.

Four cameras record 24/7 as 5-minute MKV segments to ~/video-recording/{role}/:
  - brio-operator: Logitech BRIO on operator (primary camera)
  - c920-room: C920 wide room shot
  - c920-desk: C920 high angle monitors/desk
  - c920-overhead: C920 top-down over operator

Classification is CPU-only using OpenCV haar cascades and frame differencing:
  - Person detection via haar cascade face/upper body detection
  - Motion scoring via frame differencing between keyframes
  - Scene change detection via structural similarity

Value scoring (0.0-1.0):
  - production_session: Person + high motion + audio production window → 1.0
  - conversation: Multiple people visible → 0.8
  - active_work: Person + moderate motion → 0.6
  - idle_occupied: Person + low motion → 0.3
  - empty_room: No person detected → 0.0

Retention policy:
  - Score >= 0.5 → upload to gdrive:video-archive/{role}/{date}/ via rclone
  - Score 0.1-0.5 → keep locally 48h for manual review
  - Score < 0.1 → mark processed immediately (retention script deletes)

Usage:
    uv run python -m agents.video_processor --process    # Process new segments
    uv run python -m agents.video_processor --stats      # Show processing state
    uv run python -m agents.video_processor --reprocess FILE  # Reprocess a specific file
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass
from opentelemetry import trace

_tracer = trace.get_tracer(__name__)

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

VIDEO_DIR = Path.home() / "video-recording"
CACHE_DIR = Path.home() / ".cache" / "video-processor"
STATE_FILE = CACHE_DIR / "state.json"
CHANGES_LOG = CACHE_DIR / "changes.jsonl"
PERCEPTION_MINUTES_PATH = Path.home() / ".cache" / "hapax-daimonion" / "perception-minutes.jsonl"

from shared.cameras import CAMERA_ROLES

# Number of keyframes to extract per segment for temporal coverage
NUM_KEYFRAMES = 5

# ── Classification Thresholds ────────────────────────────────────────────────

# Minimum motion score (0-1) to consider "active"
MOTION_THRESHOLD_HIGH = 0.15
MOTION_THRESHOLD_MODERATE = 0.05

# Minimum face/body detection confidence
MIN_DETECT_CONFIDENCE = 3  # minimum # of cascade hits to count as "person present"

# Scene change: if SSIM between first and last keyframe is below this, scene changed
SCENE_CHANGE_SSIM = 0.85

# Value thresholds for retention decisions
UPLOAD_THRESHOLD = 0.5
LOCAL_KEEP_THRESHOLD = 0.1

# VRAM threshold — skip GPU processing if less than this available (MB)
MIN_VRAM_FREE_MB = 6000

# Maximum segments to process per run (avoid hogging CPU for hours)
MAX_SEGMENTS_PER_RUN = 200

# Skip segments still being written (modified within last N seconds)
MIN_AGE_SECONDS = 120

# ── Schemas ──────────────────────────────────────────────────────────────────


class FrameAnalysis(BaseModel):
    """Analysis result for a single extracted keyframe."""

    frame_index: int = 0
    people_count: int = 0
    face_count: int = 0
    body_count: int = 0


class SegmentClassification(BaseModel):
    """Full classification result for a video segment."""

    category: str = "empty_room"
    value_score: float = 0.0
    people_count: int = 0
    max_people: int = 0
    motion_score: float = 0.0
    scene_change: bool = False
    ssim: float = 1.0
    frame_analyses: list[FrameAnalysis] = Field(default_factory=list)


class ProcessedSegmentInfo(BaseModel):
    """State for a single processed video segment."""

    filename: str
    role: str = ""
    processed_at: float = 0.0
    category: str = "empty_room"
    value_score: float = 0.0
    people_count: int = 0
    motion_score: float = 0.0
    scene_change: bool = False
    disposition: str = ""  # "uploaded", "local_keep", "discard"
    uploaded: bool = False
    upload_path: str = ""
    error: str = ""


class VideoProcessorState(BaseModel):
    """Persistent processing state."""

    processed_files: dict[str, ProcessedSegmentInfo] = Field(default_factory=dict)
    last_run: float = 0.0
    stats: dict[str, float] = Field(default_factory=dict)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _load_state() -> VideoProcessorState:
    """Load processing state from disk."""
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return VideoProcessorState(**data)
        except (json.JSONDecodeError, Exception) as exc:
            log.warning("Failed to load state: %s", exc)
    return VideoProcessorState()


def _save_state(state: VideoProcessorState) -> None:
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
    """Check if enough GPU VRAM is available (informational for this CPU-only pipeline)."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            free_mb = int(result.stdout.strip().split("\n")[0])
            log.debug("GPU VRAM free: %d MB", free_mb)
            return free_mb >= min_mb
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError) as exc:
        log.debug("VRAM check failed: %s", exc)
    return False


def _extract_role_from_path(segment_path: Path) -> str:
    """Extract camera role from the segment's parent directory name."""
    return segment_path.parent.name


def _extract_timestamp_from_filename(filename: str) -> str:
    """Extract ISO timestamp from {role}_{YYYYMMDD}-{HHMMSS}_{NNNN}.mkv filename."""
    try:
        # e.g. brio-operator_20260316-121050_0107.mkv
        parts = filename.rsplit(".", 1)[0]  # strip extension
        segments = parts.split("_")
        if len(segments) >= 2:
            date_time = segments[1]  # 20260316-121050
            date_part, time_part = date_time.split("-")
            return (
                f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
                f"T{time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}"
            )
    except (ValueError, IndexError):
        pass
    return datetime.now(UTC).isoformat()[:19]


def _extract_date_from_filename(filename: str) -> str:
    """Extract YYYY-MM-DD date from segment filename."""
    try:
        parts = filename.rsplit(".", 1)[0]
        segments = parts.split("_")
        if len(segments) >= 2:
            date_time = segments[1]
            date_part = date_time.split("-")[0]
            return f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
    except (ValueError, IndexError):
        pass
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _find_unprocessed_segments(state: VideoProcessorState) -> list[Path]:
    """Find MKV segments across all camera roles that haven't been processed."""
    segments: list[Path] = []
    now = time.time()

    for role_dir in sorted(VIDEO_DIR.iterdir()):
        if not role_dir.is_dir():
            continue
        for mkv in role_dir.glob("*.mkv"):
            # Skip if already processed
            if mkv.name in state.processed_files:
                continue
            # Skip if already has a sidecar (classified or processed marker)
            if (mkv.with_suffix(mkv.suffix + ".processed")).exists():
                continue
            if (mkv.with_suffix(mkv.suffix + ".classified")).exists():
                # Check if we have state for it — if not, it was classified
                # by a previous version or manually. Re-read sidecar.
                continue
            # Skip if still being written
            try:
                if now - mkv.stat().st_mtime < MIN_AGE_SECONDS:
                    continue
                if mkv.stat().st_size == 0:
                    continue
            except OSError:
                continue
            segments.append(mkv)

    return sorted(segments)


# ── Keyframe Extraction ──────────────────────────────────────────────────────


def _extract_keyframes(segment_path: Path, num_frames: int = NUM_KEYFRAMES) -> list[Path]:
    """Extract keyframes from a video segment using ffmpeg.

    Extracts frames at start, middle, and end of the segment.
    Returns list of temporary file paths to extracted JPEG frames.
    """
    # Get video duration
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(segment_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        duration = float(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
        log.warning("Failed to probe duration for %s: %s", segment_path.name, exc)
        return []

    if duration <= 0:
        return []

    # Calculate timestamps for keyframes (avoid exact 0 and end)
    timestamps = []
    if num_frames == 1:
        timestamps = [duration / 2]
    else:
        for i in range(num_frames):
            t = (duration * (i + 0.5)) / num_frames
            timestamps.append(min(t, duration - 0.1))

    frame_paths: list[Path] = []
    tmp_dir = Path(tempfile.mkdtemp(prefix="vidproc_"))

    for idx, ts in enumerate(timestamps):
        out_path = tmp_dir / f"frame_{idx:03d}.jpg"
        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-ss",
                    f"{ts:.2f}",
                    "-i",
                    str(segment_path),
                    "-vframes",
                    "1",
                    "-q:v",
                    "2",
                    "-y",
                    str(out_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
                frame_paths.append(out_path)
            else:
                log.debug(
                    "ffmpeg frame extraction failed for %s at %.1fs: %s",
                    segment_path.name,
                    ts,
                    result.stderr[-200:] if result.stderr else "unknown",
                )
        except (subprocess.TimeoutExpired, OSError) as exc:
            log.debug("Frame extraction error for %s at %.1fs: %s", segment_path.name, ts, exc)

    return frame_paths


def _cleanup_frames(frame_paths: list[Path]) -> None:
    """Remove temporary keyframe files and their parent directory."""
    if not frame_paths:
        return
    parent = frame_paths[0].parent
    for fp in frame_paths:
        try:
            fp.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        parent.rmdir()
    except OSError:
        pass


# ── Person Detection (OpenCV Haar Cascade) ───────────────────────────────────


def _detect_people(frame_path: Path) -> FrameAnalysis:
    """Run person detection on a single frame using OpenCV haar cascades.

    Uses both face and upper body cascades for robustness.
    Returns FrameAnalysis with detection counts.
    """
    import cv2

    frame = cv2.imread(str(frame_path))
    if frame is None:
        return FrameAnalysis()

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)

    # Face detection
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    profile_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml")
    body_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_upperbody.xml")

    faces_front = face_cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=4, minSize=(30, 30)
    )
    faces_profile = profile_cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=4, minSize=(30, 30)
    )
    bodies = body_cascade.detectMultiScale(gray, scaleFactor=1.05, minNeighbors=3, minSize=(50, 50))

    face_count = len(faces_front) + len(faces_profile)
    body_count = len(bodies)

    # People count is max of face and body detections (they overlap)
    people_count = max(face_count, body_count)

    return FrameAnalysis(
        people_count=people_count,
        face_count=face_count,
        body_count=body_count,
    )


# ── Motion and Scene Change Detection ────────────────────────────────────────


def _compute_motion_score(frame_paths: list[Path]) -> float:
    """Compute motion score from frame differencing between keyframes.

    Returns a normalized score 0.0-1.0 where higher = more motion.
    """
    import cv2
    import numpy as np

    if len(frame_paths) < 2:
        return 0.0

    frames = []
    for fp in frame_paths:
        img = cv2.imread(str(fp), cv2.IMREAD_GRAYSCALE)
        if img is not None:
            # Resize for consistent comparison
            img = cv2.resize(img, (320, 240))
            frames.append(img.astype(np.float32))

    if len(frames) < 2:
        return 0.0

    # Compute mean absolute difference between consecutive frames
    diffs = []
    for i in range(len(frames) - 1):
        diff = np.abs(frames[i + 1] - frames[i])
        # Normalize by 255 (max pixel value)
        mean_diff = float(np.mean(diff)) / 255.0
        diffs.append(mean_diff)

    # Return average motion across frame pairs
    return float(np.mean(diffs))


def _compute_ssim(frame_paths: list[Path]) -> float:
    """Compute structural similarity between first and last keyframes.

    Returns SSIM score 0.0-1.0 where 1.0 = identical frames.
    Low SSIM indicates scene change.
    """
    import cv2
    import numpy as np

    if len(frame_paths) < 2:
        return 1.0

    img1 = cv2.imread(str(frame_paths[0]), cv2.IMREAD_GRAYSCALE)
    img2 = cv2.imread(str(frame_paths[-1]), cv2.IMREAD_GRAYSCALE)

    if img1 is None or img2 is None:
        return 1.0

    # Resize for consistent comparison
    img1 = cv2.resize(img1, (320, 240)).astype(np.float64)
    img2 = cv2.resize(img2, (320, 240)).astype(np.float64)

    # Simple SSIM approximation (no scipy dependency)
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2

    mu1 = np.mean(img1)
    mu2 = np.mean(img2)
    sigma1_sq = np.var(img1)
    sigma2_sq = np.var(img2)
    sigma12 = np.mean((img1 - mu1) * (img2 - mu2))

    ssim = ((2 * mu1 * mu2 + c1) * (2 * sigma12 + c2)) / (
        (mu1**2 + mu2**2 + c1) * (sigma1_sq + sigma2_sq + c2)
    )

    return float(np.clip(ssim, 0.0, 1.0))


# ── Perception-Informed Classification ──────────────────────────────────────


def _parse_segment_timestamp(filename: str) -> float | None:
    """Parse Unix timestamp from segment filename.

    Format: {role}_{YYYYMMDD-HHMMSS}_{fragment:04d}.mkv
    """
    try:
        parts = filename.rsplit(".", 1)[0].split("_")
        if len(parts) >= 2:
            dt = datetime.strptime(parts[1], "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
            return dt.timestamp()
    except (ValueError, IndexError):
        pass
    return None


def _read_perception_minutes(start_ts: float, end_ts: float) -> list[dict]:
    """Read perception minute entries covering [start_ts, end_ts]."""
    if not PERCEPTION_MINUTES_PATH.exists():
        return []
    entries = []
    for line in PERCEPTION_MINUTES_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            ts = entry.get("timestamp", 0)
            if start_ts <= ts <= end_ts:
                entries.append(entry)
        except json.JSONDecodeError:
            continue
    return entries


def _perception_mode(values: list[str]) -> str:
    """Return the most common non-empty string value."""
    counts: dict[str, int] = {}
    for v in values:
        if v:
            counts[v] = counts.get(v, 0) + 1
    if not counts:
        return ""
    return max(counts, key=counts.get)  # type: ignore[arg-type]


def _aggregate_perception_minutes(minutes: list[dict]) -> dict:
    """Aggregate perception minute summaries over a segment window."""
    if not minutes:
        return {
            "operator_present": False,
            "operator_present_ratio": 0.0,
            "person_count_max": 0,
            "flow_score_mean": 0.0,
            "flow_score_peak": 0.0,
            "activity_mode": "",
            "audio_energy_mean": 0.0,
            "voice_active": False,
            "consent_phase": "no_guest",
            "stress_elevated": False,
            "hr_mean": 0.0,
            "activity_changed": False,
        }
    n = len(minutes)
    return {
        "operator_present": any(m.get("operator_present", False) for m in minutes),
        "operator_present_ratio": sum(1 for m in minutes if m.get("operator_present")) / n,
        "person_count_max": max((m.get("person_count_max", 0) for m in minutes), default=0),
        "flow_score_mean": sum(m.get("flow_mean", 0) for m in minutes) / n,
        "flow_score_peak": max((m.get("flow_mean", 0) for m in minutes), default=0),
        "activity_mode": _perception_mode([m.get("activity", "") for m in minutes]),
        "audio_energy_mean": sum(m.get("audio_mean", 0) for m in minutes) / n,
        "voice_active": any(m.get("voice_active", False) for m in minutes),
        "consent_phase": _perception_mode([m.get("consent_phase", "no_guest") for m in minutes])
        or "no_guest",
        "stress_elevated": any(m.get("stress_elevated", False) for m in minutes),
        "hr_mean": sum(m.get("hr_mean", 0) for m in minutes) / n,
        "activity_changed": len(set(m.get("activity", "") for m in minutes if m.get("activity")))
        > 1,
    }


def _classify_from_perception(agg: dict) -> SegmentClassification:
    """Score a segment using aggregated perception minute data."""
    person_count = agg["person_count_max"]
    present = agg["operator_present"]
    present_ratio = agg["operator_present_ratio"]
    activity = agg["activity_mode"]
    flow_mean = agg["flow_score_mean"]
    flow_peak = agg["flow_score_peak"]
    consent = agg["consent_phase"]
    activity_changed = agg["activity_changed"]

    if present and activity == "producing" and flow_peak > 0.5:
        category = "production_session"
        score = 1.0
    elif person_count > 1 and consent == "consent_granted":
        category = "conversation"
        score = 0.8
    elif present and activity in ("coding", "meeting", "producing") and flow_mean > 0.3:
        category = "active_work"
        score = 0.6
    elif present and present_ratio > 0.3:
        category = "idle_occupied"
        score = 0.3
    else:
        category = "empty_room"
        score = 0.0

    # Activity transition bonus
    if activity_changed and score > 0:
        score = min(1.0, score + 0.1)

    # Voice session bonus
    if agg["voice_active"] and score > 0:
        score = min(1.0, score + 0.1)

    return SegmentClassification(
        category=category,
        value_score=round(score, 2),
        people_count=person_count,
        max_people=person_count,
        motion_score=round(min(1.0, agg.get("audio_energy_mean", 0.0)), 4),
        scene_change=activity_changed,
        ssim=round(max(0.0, min(1.0, 1.0 - agg.get("audio_energy_mean", 0.0))), 4),
    )


def _classify_segment_dispatch(segment_path: Path) -> SegmentClassification:
    """Classify a segment using perception data, falling back to haar cascades.

    Reads the perception-minutes.jsonl log for the segment's 5-minute time
    window. If perception data covers the window, classification is based on
    operator presence, activity mode, flow state, and person count from the
    real-time perception system (YOLO, MediaPipe, Bayesian presence).

    Falls back to the original haar cascade pipeline when perception data is
    unavailable (e.g., daemon was restarting during the segment's recording).
    """
    ts = _parse_segment_timestamp(segment_path.name)
    if ts is not None:
        minutes = _read_perception_minutes(ts, ts + 300)
        if minutes:
            agg = _aggregate_perception_minutes(minutes)
            classification = _classify_from_perception(agg)
            log.info(
                "Perception-classified %s: %s (score=%.2f, present=%.0f%%, "
                "activity=%s, flow=%.2f, people=%d)",
                segment_path.name,
                classification.category,
                classification.value_score,
                agg["operator_present_ratio"] * 100,
                agg["activity_mode"],
                agg["flow_score_mean"],
                agg["person_count_max"],
            )
            return classification
    # Fallback: original haar cascade pipeline
    log.info("No perception data for %s — falling back to haar cascades", segment_path.name)
    return _classify_segment(segment_path)


# ── Haar Cascade Classification Pipeline (fallback) ───────────────────────


def _classify_segment(segment_path: Path) -> SegmentClassification:
    """Classify a video segment by extracting keyframes and analyzing them.

    Pipeline:
    1. Extract 3 keyframes (start, middle, end) via ffmpeg
    2. Run person detection on each keyframe (haar cascades)
    3. Compute motion score (frame differencing)
    4. Compute scene change (SSIM between first/last frame)
    5. Assign category and value score
    """
    frame_paths = _extract_keyframes(segment_path)
    if not frame_paths:
        log.warning("No keyframes extracted from %s", segment_path.name)
        return SegmentClassification(category="empty_room", value_score=0.0)

    try:
        # Person detection on each frame
        frame_analyses: list[FrameAnalysis] = []
        for idx, fp in enumerate(frame_paths):
            analysis = _detect_people(fp)
            analysis.frame_index = idx
            frame_analyses.append(analysis)

        # Aggregate people count (max across frames)
        max_people = max((fa.people_count for fa in frame_analyses), default=0)
        avg_people = (
            sum(fa.people_count for fa in frame_analyses) / len(frame_analyses)
            if frame_analyses
            else 0
        )

        # Motion score
        motion_score = _compute_motion_score(frame_paths)

        # Scene change (SSIM)
        ssim = _compute_ssim(frame_paths)
        scene_change = ssim < SCENE_CHANGE_SSIM

        # Classify
        person_present = max_people >= 1
        multiple_people = max_people >= 2

        if multiple_people:
            category = "conversation"
            value_score = 0.8
        elif person_present and motion_score >= MOTION_THRESHOLD_HIGH:
            category = "production_session"
            value_score = 1.0
        elif person_present and motion_score >= MOTION_THRESHOLD_MODERATE:
            category = "active_work"
            value_score = 0.6
        elif person_present:
            category = "idle_occupied"
            value_score = 0.3
        else:
            category = "empty_room"
            value_score = 0.0

        # Boost score if scene changed significantly (something interesting happened)
        if scene_change and value_score > 0:
            value_score = min(1.0, value_score + 0.1)

        return SegmentClassification(
            category=category,
            value_score=round(value_score, 2),
            people_count=round(avg_people),
            max_people=max_people,
            motion_score=round(motion_score, 4),
            scene_change=scene_change,
            ssim=round(ssim, 4),
            frame_analyses=frame_analyses,
        )
    finally:
        _cleanup_frames(frame_paths)


# ── Sidecar Files ────────────────────────────────────────────────────────────


def _write_sidecar(
    segment_path: Path,
    classification: SegmentClassification,
    disposition: str,
    suffix: str = ".classified",
) -> Path:
    """Write a JSON sidecar file alongside the video segment.

    Sidecar contains classification metadata for the retention script
    and for any future reprocessing.
    """
    sidecar_path = segment_path.with_suffix(segment_path.suffix + suffix)
    data = {
        "filename": segment_path.name,
        "classified_at": datetime.now(UTC).isoformat(),
        "category": classification.category,
        "value_score": classification.value_score,
        "people_count": classification.people_count,
        "max_people": classification.max_people,
        "motion_score": classification.motion_score,
        "scene_change": classification.scene_change,
        "ssim": classification.ssim,
        "disposition": disposition,
    }
    sidecar_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return sidecar_path


# ── Upload to Google Drive ───────────────────────────────────────────────────


def _upload_to_gdrive(segment_path: Path, role: str, date: str) -> bool:
    """Upload a video segment to Google Drive via rclone.

    Target: gdrive:video-archive/{role}/{date}/
    """
    remote_path = f"gdrive:video-archive/{role}/{date}/"
    log.info("Uploading %s → %s", segment_path.name, remote_path)

    try:
        result = subprocess.run(
            [
                "rclone",
                "copy",
                str(segment_path),
                remote_path,
                "--no-traverse",
                "--transfers",
                "4",
            ],
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout per segment
        )
        if result.returncode == 0:
            log.info("Upload complete: %s", segment_path.name)
            return True
        else:
            log.error(
                "rclone upload failed for %s (rc=%d): %s",
                segment_path.name,
                result.returncode,
                result.stderr[-500:] if result.stderr else "no stderr",
            )
            return False
    except subprocess.TimeoutExpired:
        log.error("rclone upload timed out for %s", segment_path.name)
        return False
    except (FileNotFoundError, OSError) as exc:
        log.error("rclone not available or OS error: %s", exc)
        return False


# ── Main Processing Pipeline ─────────────────────────────────────────────────


def _process_segment(
    segment_path: Path,
    state: VideoProcessorState,
) -> ProcessedSegmentInfo | None:
    """Process a single video segment through the classification pipeline.

    Pipeline:
    1. Extract keyframes via ffmpeg
    2. Classify (person detection, motion, scene change)
    3. Decide retention disposition
    4. Upload to gdrive if valuable
    5. Write sidecar and mark state
    """
    filename = segment_path.name
    role = _extract_role_from_path(segment_path)
    date = _extract_date_from_filename(filename)

    log.info("Processing %s (role=%s)", filename, role)

    # Classify — perception-informed with haar cascade fallback
    try:
        classification = _classify_segment_dispatch(segment_path)
    except Exception as exc:
        log.error("Classification failed for %s: %s", filename, exc)
        return ProcessedSegmentInfo(
            filename=filename,
            role=role,
            error=str(exc),
            processed_at=time.time(),
        )

    score = classification.value_score
    category = classification.category

    # Decide disposition
    disposition = "discard"
    uploaded = False
    upload_path = ""

    if score >= UPLOAD_THRESHOLD:
        # Upload to gdrive
        disposition = "uploaded"
        if _upload_to_gdrive(segment_path, role, date):
            uploaded = True
            upload_path = f"gdrive:video-archive/{role}/{date}/{filename}"
            # Mark as processed so retention script can delete local copy
            _write_sidecar(segment_path, classification, disposition, suffix=".processed")
        else:
            # Upload failed — keep locally, mark classified for retry
            disposition = "local_keep"
            _write_sidecar(segment_path, classification, disposition, suffix=".classified")
            log.warning("Upload failed for %s — keeping locally", filename)
    elif score >= LOCAL_KEEP_THRESHOLD:
        # Keep locally for 48h review window
        disposition = "local_keep"
        _write_sidecar(segment_path, classification, disposition, suffix=".classified")
    else:
        # Discard — mark processed so retention script deletes it
        disposition = "discard"
        _write_sidecar(segment_path, classification, disposition, suffix=".processed")

    info = ProcessedSegmentInfo(
        filename=filename,
        role=role,
        processed_at=time.time(),
        category=category,
        value_score=score,
        people_count=classification.people_count,
        motion_score=classification.motion_score,
        scene_change=classification.scene_change,
        disposition=disposition,
        uploaded=uploaded,
        upload_path=upload_path,
    )

    log.info(
        "Classified %s: %s (score=%.2f, people=%d, motion=%.4f, disp=%s)",
        filename,
        category,
        score,
        classification.people_count,
        classification.motion_score,
        disposition,
    )

    _log_change(
        "segment_classified",
        f"{role}/{filename}",
        {
            "category": category,
            "value_score": score,
            "people_count": classification.people_count,
            "motion_score": round(classification.motion_score, 4),
            "scene_change": classification.scene_change,
            "disposition": disposition,
            "uploaded": uploaded,
        },
    )

    return info


def _process_new_segments(state: VideoProcessorState) -> dict[str, int]:
    """Find and process all unprocessed video segments."""
    from agents._notify import send_notification

    segments = _find_unprocessed_segments(state)

    if not segments:
        log.info("No new video segments to process")
        return {"processed": 0, "skipped": 0, "uploaded": 0, "errors": 0}

    # Cap per run to avoid monopolizing CPU
    if len(segments) > MAX_SEGMENTS_PER_RUN:
        log.info("Found %d segments, processing first %d", len(segments), MAX_SEGMENTS_PER_RUN)
        segments = segments[:MAX_SEGMENTS_PER_RUN]
    else:
        log.info("Found %d new segments to process", len(segments))

    processed = 0
    skipped = 0
    uploaded = 0
    errors = 0

    for segment in segments:
        try:
            info = _process_segment(segment, state)
        except Exception as exc:
            log.error("Unexpected error processing %s: %s", segment.name, exc)
            info = ProcessedSegmentInfo(
                filename=segment.name,
                role=_extract_role_from_path(segment),
                error=str(exc),
                processed_at=time.time(),
            )
            errors += 1

        if info is None:
            skipped += 1
        else:
            state.processed_files[segment.name] = info
            processed += 1
            if info.uploaded:
                uploaded += 1
            if info.error:
                errors += 1

    state.last_run = time.time()
    _save_state(state)

    if processed > 0:
        # Summarize by category
        run_files = [
            state.processed_files[s.name]
            for s in segments[:processed]
            if s.name in state.processed_files
        ]
        categories: dict[str, int] = {}
        for f in run_files:
            categories[f.category] = categories.get(f.category, 0) + 1

        cat_str = ", ".join(f"{k}: {v}" for k, v in sorted(categories.items()))
        msg = f"Video: {processed} segments — {uploaded} uploaded, {cat_str}"
        send_notification("Video Processor", msg, tags=["movie_camera"])

    return {
        "processed": processed,
        "skipped": skipped,
        "uploaded": uploaded,
        "errors": errors,
    }


# ── Stats ────────────────────────────────────────────────────────────────────


def _print_stats(state: VideoProcessorState) -> None:
    """Print processing statistics."""
    total = len(state.processed_files)
    by_role: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_disposition: dict[str, int] = {}
    uploaded_count = 0
    error_count = 0

    for f in state.processed_files.values():
        by_role[f.role] = by_role.get(f.role, 0) + 1
        by_category[f.category] = by_category.get(f.category, 0) + 1
        by_disposition[f.disposition] = by_disposition.get(f.disposition, 0) + 1
        if f.uploaded:
            uploaded_count += 1
        if f.error:
            error_count += 1

    print("Video Processor State")
    print("=" * 50)
    print(f"Total processed:  {total:,}")
    print(f"Uploaded:         {uploaded_count:,}")
    print(f"Errors:           {error_count:,}")
    print(
        f"Last run:         "
        f"{datetime.fromtimestamp(state.last_run, tz=UTC).strftime('%Y-%m-%d %H:%M UTC') if state.last_run else 'never'}"
    )
    print()

    if by_role:
        print("By Camera Role:")
        for role in sorted(by_role):
            print(f"  {role:20s} {by_role[role]:>6,}")
        print()

    if by_category:
        print("By Category:")
        for cat in sorted(by_category):
            print(f"  {cat:20s} {by_category[cat]:>6,}")
        print()

    if by_disposition:
        print("By Disposition:")
        for disp in sorted(by_disposition):
            print(f"  {disp:20s} {by_disposition[disp]:>6,}")

    # Pending segments
    pending = _find_unprocessed_segments(state)
    print(f"\nPending segments:   {len(pending):,}")

    # Current disk usage
    try:
        result = subprocess.run(
            ["du", "-sh", str(VIDEO_DIR)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            size = result.stdout.strip().split("\t")[0]
            print(f"Video dir size:     {size}")
    except (subprocess.TimeoutExpired, OSError):
        pass


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Video segment classification and retention pipeline for multi-camera studio"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--process", action="store_true", help="Process new video segments")
    group.add_argument("--stats", action="store_true", help="Show processing statistics")
    group.add_argument("--reprocess", type=str, metavar="FILE", help="Reprocess a specific segment")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    from agents._log_setup import configure_logging

    configure_logging(agent="video-processor", level="DEBUG" if args.verbose else None)

    action = "process" if args.process else "reprocess" if args.reprocess else "stats"
    with _tracer.start_as_current_span(
        f"video_processor.{action}",
        attributes={"agent.name": "video_processor", "agent.repo": "hapax-council"},
    ):
        if args.process:
            state = _load_state()
            summary = _process_new_segments(state)
            log.info("Processing complete: %s", summary)
        elif args.reprocess:
            state = _load_state()
            path = Path(args.reprocess)
            if not path.exists():
                # Try to find it under video-recording dirs
                for role in CAMERA_ROLES:
                    candidate = VIDEO_DIR / role / args.reprocess
                    if candidate.exists():
                        path = candidate
                        break
            if not path.exists():
                print(f"File not found: {args.reprocess}")
                return
            # Remove from state so it gets reprocessed
            if path.name in state.processed_files:
                del state.processed_files[path.name]
            # Remove existing sidecars
            for suffix in (".processed", ".classified"):
                sidecar = path.with_suffix(path.suffix + suffix)
                sidecar.unlink(missing_ok=True)
            info = _process_segment(path, state)
            if info:
                state.processed_files[path.name] = info
                _save_state(state)
        elif args.stats:
            state = _load_state()
            if not state.processed_files:
                print("No processing state found. Run --process first.")
                return
            _print_stats(state)


if __name__ == "__main__":
    main()
