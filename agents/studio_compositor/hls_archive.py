"""HLS segment rotation from the compositor cache to the research archive.

LRR Phase 2 item 2 + item 3. Walks ``~/.cache/hapax-compositor/hls/`` for
closed segments (``*.ts``), moves them to
``~/hapax-state/stream-archive/hls/YYYY-MM-DD/`` with a per-segment
sidecar JSON. Invoked periodically (systemd timer or operator CLI).

"Closed" = a segment whose mtime has been stable for at least
``STABLE_MTIME_WINDOW_SECONDS`` (default 10 s). This avoids racing the
``hlssink2`` writer — the element rotates segments every
``target-duration`` seconds (default 4 s in ``hls.config``), so the 10 s
window gives a 2.5× safety margin.

Metadata is assembled from:
- ``~/hapax-state/research-registry/current.txt`` → active condition_id
- ``/dev/shm/hapax-compositor/research-marker.json`` → Phase 1 research marker
- ``/dev/shm/hapax-daimonion/current.json`` → stimmung snapshot (best effort)
- ``~/hapax-state/stream-reactions-*.jsonl`` → reaction IDs in the segment window (best effort)
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.stream_archive import (
    SegmentSidecar,
    atomic_write_json,
    hls_archive_dir,
    sidecar_path_for,
)

DEFAULT_STABLE_MTIME_WINDOW_SECONDS = 10.0
"""Minimum mtime-stable age before a segment is considered closed + rotatable."""

DEFAULT_HLS_SOURCE_DIR = Path.home() / ".cache" / "hapax-compositor" / "hls"
"""Compositor HLS output directory — matches ``hls_cfg.output_dir`` default."""

DEFAULT_STIMMUNG_PATH = Path("/dev/shm/hapax-daimonion/current.json")
"""Best-effort stimmung snapshot source. Absent → empty dict."""

DEFAULT_CONDITION_POINTER = Path.home() / "hapax-state" / "research-registry" / "current.txt"
"""Research registry active condition pointer (Phase 1 item 8)."""


@dataclass(frozen=True)
class RotationResult:
    """Summary of a single rotation pass. Used for logging + tests."""

    scanned: int
    rotated: int
    skipped_unstable: int
    skipped_already_rotated: int
    errors: list[str]


def _load_condition_id(pointer_path: Path = DEFAULT_CONDITION_POINTER) -> str | None:
    """Read the active condition_id. None if unset or registry is not initialized."""
    if not pointer_path.exists():
        return None
    try:
        value = pointer_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _load_stimmung_snapshot(
    stimmung_path: Path = DEFAULT_STIMMUNG_PATH,
) -> dict[str, Any]:
    """Best-effort stimmung snapshot. Returns {} if unavailable."""
    if not stimmung_path.exists():
        return {}
    try:
        payload = json.loads(stimmung_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        "stance": payload.get("stance"),
        "dimensions": payload.get("dimensions"),
        "snapshotted_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def is_segment_stable(
    segment_path: Path,
    *,
    now_ts: float,
    window_seconds: float = DEFAULT_STABLE_MTIME_WINDOW_SECONDS,
) -> bool:
    """Return True if the segment's mtime is stable enough to rotate."""
    try:
        mtime = segment_path.stat().st_mtime
    except OSError:
        return False
    return (now_ts - mtime) >= window_seconds


def build_sidecar(
    *,
    segment_path: Path,
    segment_start_ts: datetime,
    segment_end_ts: datetime,
    condition_id: str | None,
    stimmung: dict[str, Any],
    reaction_ids: list[str] | None = None,
    active_activity: str | None = None,
    directives_hash: str | None = None,
) -> SegmentSidecar:
    """Construct the sidecar for a single HLS segment."""
    return SegmentSidecar.new(
        segment_id=segment_path.stem,
        segment_path=segment_path,
        condition_id=condition_id,
        segment_start_ts=segment_start_ts,
        segment_end_ts=segment_end_ts,
        reaction_ids=reaction_ids,
        active_activity=active_activity,
        stimmung_snapshot=stimmung,
        directives_hash=directives_hash,
        archive_kind="hls",
    )


def rotate_segment(
    segment_path: Path,
    *,
    target_dir: Path,
    condition_id: str | None,
    stimmung: dict[str, Any],
    now: datetime | None = None,
) -> Path:
    """Move a single segment to the archive + write its sidecar.

    Returns the new segment path. Sidecar path is derived via
    ``sidecar_path_for(new_path)``. The move is atomic enough for our
    purposes (same filesystem) — ``shutil.move`` uses ``os.rename`` when
    possible and falls back to copy+unlink across filesystems.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    new_path = target_dir / segment_path.name
    if new_path.exists():
        raise FileExistsError(f"archive destination already occupied: {new_path}")

    end_ts = now or datetime.now(UTC)
    try:
        mtime_utc = datetime.fromtimestamp(segment_path.stat().st_mtime, tz=UTC)
    except OSError:
        mtime_utc = end_ts
    # Assume segment duration ~4s if we can't infer it otherwise; the
    # sidecar will be refined by downstream tools that parse the .ts.
    segment_start = mtime_utc

    shutil.move(str(segment_path), str(new_path))

    sidecar = build_sidecar(
        segment_path=new_path,
        segment_start_ts=segment_start,
        segment_end_ts=end_ts,
        condition_id=condition_id,
        stimmung=stimmung,
    )
    atomic_write_json(sidecar_path_for(new_path), sidecar.to_json())
    return new_path


def rotate_pass(
    *,
    source_dir: Path | None = None,
    now_ts: float | None = None,
    window_seconds: float = DEFAULT_STABLE_MTIME_WINDOW_SECONDS,
    condition_pointer: Path | None = None,
    stimmung_path: Path | None = None,
) -> RotationResult:
    """Walk the HLS source dir, rotate stable segments, return a summary.

    Caller is responsible for scheduling (systemd timer, operator CLI).
    Defaults resolve at call time so test monkeypatching against the
    module-level constants takes effect.
    """
    import time as _time

    effective_source = source_dir if source_dir is not None else DEFAULT_HLS_SOURCE_DIR
    effective_pointer = (
        condition_pointer if condition_pointer is not None else DEFAULT_CONDITION_POINTER
    )
    effective_stimmung = stimmung_path if stimmung_path is not None else DEFAULT_STIMMUNG_PATH

    if not effective_source.exists():
        return RotationResult(
            scanned=0, rotated=0, skipped_unstable=0, skipped_already_rotated=0, errors=[]
        )

    now_ts = now_ts if now_ts is not None else _time.time()
    now_dt = datetime.fromtimestamp(now_ts, tz=UTC)
    condition_id = _load_condition_id(effective_pointer)
    stimmung = _load_stimmung_snapshot(effective_stimmung)
    target_dir = hls_archive_dir(at=now_dt)

    scanned = 0
    rotated = 0
    skipped_unstable = 0
    skipped_already_rotated = 0
    errors: list[str] = []

    for segment_path in sorted(effective_source.glob("*.ts")):
        scanned += 1
        if not is_segment_stable(segment_path, now_ts=now_ts, window_seconds=window_seconds):
            skipped_unstable += 1
            continue
        if (target_dir / segment_path.name).exists():
            skipped_already_rotated += 1
            continue
        try:
            rotate_segment(
                segment_path,
                target_dir=target_dir,
                condition_id=condition_id,
                stimmung=stimmung,
                now=now_dt,
            )
            rotated += 1
        except Exception as exc:  # pragma: no cover — defensive log-and-continue
            errors.append(f"{segment_path.name}: {type(exc).__name__}: {exc}")

    return RotationResult(
        scanned=scanned,
        rotated=rotated,
        skipped_unstable=skipped_unstable,
        skipped_already_rotated=skipped_already_rotated,
        errors=errors,
    )


__all__ = [
    "DEFAULT_STABLE_MTIME_WINDOW_SECONDS",
    "DEFAULT_HLS_SOURCE_DIR",
    "DEFAULT_STIMMUNG_PATH",
    "DEFAULT_CONDITION_POINTER",
    "RotationResult",
    "build_sidecar",
    "is_segment_stable",
    "rotate_pass",
    "rotate_segment",
]
