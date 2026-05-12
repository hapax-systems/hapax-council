"""Extract clips from the HLS stream archive using ffmpeg."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from shared.stream_archive import SegmentSidecar, archive_root

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractedClip:
    path: Path
    duration_seconds: float
    source_segments: list[str]
    window_start: datetime
    window_end: datetime


def _discover_segments(
    archive_dir: Path,
    date_str: str,
    start_ts: datetime,
    end_ts: datetime,
) -> list[tuple[Path, SegmentSidecar]]:
    day_dir = archive_dir / "hls" / date_str
    if not day_dir.is_dir():
        return []

    results: list[tuple[Path, SegmentSidecar]] = []
    for sidecar_path in sorted(day_dir.glob("*.sidecar.json")):
        try:
            sidecar = SegmentSidecar.from_path(sidecar_path)
        except (ValueError, KeyError, OSError):
            continue

        seg_start = datetime.fromisoformat(sidecar.segment_start_ts.replace("Z", "+00:00"))
        seg_end = datetime.fromisoformat(sidecar.segment_end_ts.replace("Z", "+00:00"))
        if seg_start.tzinfo is None:
            seg_start = seg_start.replace(tzinfo=UTC)
        if seg_end.tzinfo is None:
            seg_end = seg_end.replace(tzinfo=UTC)

        if seg_end <= start_ts or seg_start >= end_ts:
            continue

        stem = sidecar_path.name.removesuffix(".sidecar.json")
        ts_path = sidecar_path.parent / f"{stem}.ts"
        if ts_path.is_file():
            results.append((ts_path, sidecar))

    return results


def _concat_and_extract(
    segments: list[Path],
    output_path: Path,
    trim_start: float,
    trim_duration: float,
) -> bool:
    if not segments:
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if len(segments) == 1:
        input_args = ["-i", str(segments[0])]
    else:
        concat_arg = "concat:" + "|".join(str(s) for s in segments)
        input_args = ["-i", concat_arg]

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        *input_args,
        "-ss",
        f"{trim_start:.3f}",
        "-t",
        f"{trim_duration:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            log.warning("ffmpeg extract failed: %s", result.stderr[:500])
            return False
        return output_path.is_file() and output_path.stat().st_size >= 1
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        log.warning("ffmpeg extract error: %s", exc)
        return False


def extract_clip(
    window_start: datetime,
    start_offset: float,
    end_offset: float,
    output_dir: Path,
    clip_id: str,
    *,
    archive_path: Path | None = None,
) -> ExtractedClip | None:
    root = archive_path or archive_root()
    clip_start = window_start if window_start.tzinfo else window_start.replace(tzinfo=UTC)
    abs_start = clip_start + timedelta(seconds=start_offset)
    abs_end = clip_start + timedelta(seconds=end_offset)

    date_strs = {abs_start.strftime("%Y-%m-%d"), abs_end.strftime("%Y-%m-%d")}

    all_segments: list[tuple[Path, SegmentSidecar]] = []
    for ds in sorted(date_strs):
        all_segments.extend(_discover_segments(root, ds, abs_start, abs_end))

    if not all_segments:
        log.info("No archive segments found for clip %s", clip_id)
        return None

    all_segments.sort(key=lambda t: t[1].segment_start_ts)
    seg_paths = [p for p, _ in all_segments]
    seg_ids = [s.segment_id for _, s in all_segments]

    first_seg_start = datetime.fromisoformat(
        all_segments[0][1].segment_start_ts.replace("Z", "+00:00")
    )
    trim_start = max(0.0, (abs_start - first_seg_start).total_seconds())
    trim_duration = end_offset - start_offset

    output_path = output_dir / f"{clip_id}_raw.mp4"
    if not _concat_and_extract(seg_paths, output_path, trim_start, trim_duration):
        return None

    return ExtractedClip(
        path=output_path,
        duration_seconds=trim_duration,
        source_segments=seg_ids,
        window_start=abs_start,
        window_end=abs_end,
    )
